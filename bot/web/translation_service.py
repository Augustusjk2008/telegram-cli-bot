"""有界、可取消的聊天翻译及最终回答后台调度。"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

from aiohttp import ClientError

from bot.web.openai_compatible_client import OpenAICompatibleClient, OpenAICompatibleClientError
from bot.web.translation_config import PROMPT_TARGET_LANGUAGE, TranslationConfig, TranslationConfigStore


TranslationUpdate = Callable[[dict[str, Any]], Awaitable[Any]]

# 明确可识别的控制内容先替换为随机占位符，避免依赖模型逐字保留。
_PROTECTED_RE = re.compile(
    r"(?P<fence>^[ \t]{0,3}(?P<backticks>`{3,})[^\n]*\n"
    r"[\s\S]*?(?:^[ \t]{0,3}(?P=backticks)`*[ \t]*(?=\r?$)|\Z)"
    r"|^[ \t]{0,3}(?P<tildes>~{3,})[^\n]*\n"
    r"[\s\S]*?(?:^[ \t]{0,3}(?P=tildes)~*[ \t]*(?=\r?$)|\Z))"
    r"|(?P<attachment>^(?:Attachment path:|附件路径为[:：])[^\r\n]*)"
    r"|(?P<protocol><(?P<tag>tcb_[\w-]+)\b[^>]*>[\s\S]*?</(?P=tag)>)"
    r"|(?P<inline>(?<!`)(?P<ticks>`+)(?!`)[^\n]*?(?<!`)(?P=ticks)(?!`))"
    r"|(?P<indented>^(?:(?: {4}|\t)[^\r\n]+(?:\r?\n|$))+)"
    r"|(?P<command>^[ \t]*(?:(?:\$|PS [^>\n]+>) +[^\r\n]+|"
    r"(?:git|python[\d.]*|pip[\d.]*|npm|npx|pnpm|yarn|uv|bash|pwsh|powershell|"
    r"cmd|curl|wget|docker|kubectl|cargo|node|pytest|rg|cd|ls|mkdir|"
    r"Get-[\w-]+|Set-[\w-]+|Remove-[\w-]+)[ \t]+[^\r\n]+|"
    r"(?:go (?:build|test|run|mod|get|fmt|vet)|make (?:all|build|clean|test|check|install))"
    r"\b[^\r\n]*))"
    r"|(?P<link_target>\]\([ \t]*(?:<[^>\n]+>|(?:[^\s()]|\([^()\n]*\))+?)"
    r"(?:[ \t]+[\"'][^\n]*?[\"'])?[ \t]*\))"
    r"|(?P<quoted_path>\"(?:[A-Za-z]:[\\/]|\\\\|/|\.{1,2}/|~/)[^\"\n]+\""
    r"|'(?:[A-Za-z]:[\\/]|\\\\|/|\.{1,2}/|~/)[^'\n]+')"
    r"|(?P<url>\b[a-zA-Z][\w+.-]*://[^\s<>\"'，。！？；、）]+|"
    r"\b(?:mailto|sandbox):[^\s<>\"'，。！？；、）]+)"
    r"|(?P<path>(?<![\w])(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}[/\\]|~/|/)"
    r"[^\s<>\"'`，。！？；、）\]\)]+|"
    r"(?<![\w])(?:[\w.@-]+[/\\])+[\w.@-]+)"
    r"|(?P<placeholder><\|[^\n]*?\|>|</?[A-Za-z_][^>\n]*>|"
    r"\{\{[^\n]*?\}\}|\$\{[^}\n]+\}|\$[A-Za-z_]\w*|%[A-Za-z_]\w*%|\[\[[^\n]*?\]\])",
    re.MULTILINE,
)


class _TranslationFailure(Exception):
    pass


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _protect(text: str) -> tuple[str, dict[str, str], str]:
    prefix = f"__TCB_TRANSLATION_{uuid.uuid4().hex}_"
    while prefix in text:
        prefix = f"__TCB_TRANSLATION_{uuid.uuid4().hex}_"
    originals: dict[str, str] = {}

    def substitute(match: re.Match[str]) -> str:
        token = f"{prefix}{len(originals)}__"
        originals[token] = match.group(0)
        return token

    return _PROTECTED_RE.sub(substitute, text), originals, prefix


def _restore(text: str, originals: dict[str, str], prefix: str) -> str:
    for token in originals:
        if text.count(token) != 1:
            raise _TranslationFailure("protected_content_mismatch")
    for token, original in originals.items():
        text = text.replace(token, original)
    if prefix in text:
        raise _TranslationFailure("protected_content_mismatch")
    return text


def _extract_text(raw: Any) -> str:
    if not isinstance(raw, dict) or not isinstance(raw.get("choices"), list) or not raw["choices"]:
        raise _TranslationFailure("invalid_response")
    choice = raw["choices"][0]
    if not isinstance(choice, dict):
        raise _TranslationFailure("invalid_response")
    reason = choice.get("finish_reason")
    if reason in ("length", "max_tokens"):
        raise _TranslationFailure("truncated")
    if reason not in (None, "stop"):
        raise _TranslationFailure("invalid_response")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("tool_calls") or message.get("refusal"):
        raise _TranslationFailure("invalid_response")
    text = message.get("content")
    if text is None or (isinstance(text, str) and not text.strip()):
        raise _TranslationFailure("empty_response")
    if not isinstance(text, str):
        raise _TranslationFailure("invalid_response")
    return text


class TranslationService:
    def __init__(
        self,
        *,
        config_store: TranslationConfigStore | None = None,
        client: OpenAICompatibleClient | Any | None = None,
        max_concurrency: int = 4,
        max_background_tasks: int = 32,
    ) -> None:
        if max_concurrency < 1 or max_background_tasks < 1:
            raise ValueError("翻译并发数和后台任务数必须大于零")
        self.config_store = config_store if config_store is not None else TranslationConfigStore()
        self.client = client if client is not None else OpenAICompatibleClient()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_background_tasks = max_background_tasks
        self._requests: set[asyncio.Task[str]] = set()
        self._answer_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._recent_answers: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._closed = False

    async def translate(
        self, text: str, *, config: TranslationConfig, direction: Literal["user", "assistant"],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "failed", "target_language": PROMPT_TARGET_LANGUAGE,
            "source_digest": source_digest(text),
        }
        if self._closed:
            return {**result, "error": "service_closed"}
        if not config.configured or direction not in ("user", "assistant"):
            return {**result, "error": "invalid_config"}
        if not text.strip():
            return {**result, "error": "empty_source"}
        prompt = config.user_prompt if direction == "user" else config.assistant_prompt
        task = asyncio.create_task(self._request(text, config, prompt))
        self._requests.add(task)
        try:
            translated = await asyncio.wait_for(task, timeout=config.request_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            result["error"] = "timeout"
        except _TranslationFailure as exc:
            result["error"] = str(exc)
        except OpenAICompatibleClientError as exc:
            result["error"] = (
                "authentication_error" if exc.status in (401, 403)
                else "invalid_response" if exc.code == "invalid_remote_response"
                else "http_error"
            )
        except ClientError:
            result["error"] = "network_error"
        except (ValueError, TypeError):
            result["error"] = "invalid_response"
        except Exception:
            # 上游异常可能携带认证信息，只保存固定分类。
            result["error"] = "translation_error"
        else:
            result.update(
                status="completed", text=translated,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            self._requests.discard(task)
        return result

    async def _request(self, text: str, config: TranslationConfig, prompt: str) -> str:
        async with self._semaphore:
            protected, originals, prefix = _protect(text)
            raw = await self.client.post_chat_completion(
                base_url=config.base_url,
                api_key=config.api_key,
                body={
                    "model": config.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": protected},
                    ],
                },
                timeout_seconds=config.request_timeout_seconds,
            )
            translated = _extract_text(raw)
            marker = translated.strip()
            if marker == "<skip translation>":
                raise _TranslationFailure("translation_skipped")
            if marker == "<translation failed>":
                raise _TranslationFailure("translation_failed")
            return _restore(translated, originals, prefix)

    def submit_answer(
        self, *, text: str, config: TranslationConfig, message_id: str,
        update: TranslationUpdate,
    ) -> bool:
        if (
            self._closed or not config.translate_assistant_enabled or not config.configured
            or not text.strip() or not message_id
            or len(self._answer_tasks) >= self._max_background_tasks
        ):
            return False
        key = (str(message_id), source_digest(text))
        if key in self._answer_tasks or key in self._recent_answers:
            return False
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._run_answer(
            text, config, key[1], update, loop.time() + config.request_timeout_seconds,
        ))
        self._answer_tasks[key] = task

        def finished(done: asyncio.Task[None]) -> None:
            self._answer_tasks.pop(key, None)
            self._recent_answers[key] = None
            if len(self._recent_answers) > 1024:
                self._recent_answers.popitem(last=False)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return True

    async def _run_answer(
        self, text: str, config: TranslationConfig, digest: str, update: TranslationUpdate,
        deadline: float,
    ) -> None:
        state: dict[str, Any] = {
            "status": "pending", "target_language": PROMPT_TARGET_LANGUAGE,
            "source_digest": digest,
        }
        try:
            async with asyncio.timeout_at(deadline):
                if await update(dict(state)) is False:
                    return
                result = await self.translate(text, config=config, direction="assistant")
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            result = {**state, "status": "failed", "error": "timeout"}
        except Exception:
            return
        try:
            async with asyncio.timeout(config.request_timeout_seconds):
                await update(result)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 消息可能已删除或存储不可用；后台写回不影响聊天完成事件。
            return

    async def close(self) -> None:
        self._closed = True
        tasks = [*self._answer_tasks.values(), *self._requests]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._answer_tasks.clear()
        self._requests.clear()
        self._recent_answers.clear()
        await self.client.close()


_translation_service: TranslationService | None = None


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None or _translation_service._closed:
        _translation_service = TranslationService()
    return _translation_service
