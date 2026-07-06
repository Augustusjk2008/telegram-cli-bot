"""AI inline completion orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from .inline_completion_config import InlineCompletionConfigStore
from .inline_completion_context import InlineCompletionContext, build_inline_completion_context
from .openai_compatible_client import OpenAICompatibleClient, OpenAICompatibleClientError


class InlineCompletionServiceError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "inline_completion_error") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class InlineCompletionService:
    def __init__(
        self,
        *,
        config_store: InlineCompletionConfigStore | None = None,
        client: OpenAICompatibleClient | Any | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.config_store = config_store or InlineCompletionConfigStore()
        self.client = client or OpenAICompatibleClient()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active_tasks: dict[tuple[str, str, str], asyncio.Task[dict[str, Any]]] = {}
        self._last_auto_request_at: dict[tuple[str, str], float] = {}
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            await close()

    async def complete(
        self,
        *,
        account_id: str,
        alias: str,
        workspace_root: Path | str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        config = self.config_store.config
        if not config.configured:
            raise InlineCompletionServiceError(503, "AI inline 补全未配置", code="inline_completion_not_configured")
        normalized = self._validate_request(request)
        trigger = normalized["trigger"]
        if trigger == "auto" and not config.auto_trigger_enabled:
            return self._empty_result(normalized, model=config.model, latency_ms=0, context=None)
        if trigger == "manual" and not config.manual_trigger_enabled:
            return self._empty_result(normalized, model=config.model, latency_ms=0, context=None)

        key = (account_id, alias, normalized["editorId"])
        old_task = self._active_tasks.get(key)
        if old_task is not None and not old_task.done():
            old_task.cancel()
        self._check_auto_rate_limit(account_id=account_id, alias=alias, trigger=trigger)

        task = asyncio.create_task(
            self._complete_now(account_id=account_id, alias=alias, workspace_root=workspace_root, normalized=normalized)
        )
        self._active_tasks[key] = task
        try:
            return await task
        except asyncio.CancelledError as exc:
            raise InlineCompletionServiceError(409, "补全请求已被新的请求取代", code="inline_completion_superseded") from exc
        finally:
            if self._active_tasks.get(key) is task:
                self._active_tasks.pop(key, None)

    async def _complete_now(
        self,
        *,
        account_id: str,
        alias: str,
        workspace_root: Path | str,
        normalized: dict[str, Any],
    ) -> dict[str, Any]:
        config = self.config_store.config
        start = time.perf_counter()
        context = build_inline_completion_context(
            workspace_root=workspace_root,
            relative_path=normalized["path"],
            prefix=normalized["prefix"],
            suffix=normalized["suffix"],
            language_id=normalized["languageId"],
            config=config,
        )
        if context.denied:
            raise InlineCompletionServiceError(403, "当前文件不允许用于 AI inline 补全", code="inline_completion_forbidden")
        cache_key = self._cache_key(
            normalized,
            context,
            account_id=account_id,
            alias=alias,
            workspace_root=workspace_root,
        )
        cached = self._cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] <= 60:
            return dict(cached[1])

        body = self._build_chat_body(normalized, context)
        timeout_seconds = 12 if normalized["trigger"] == "manual" else config.request_timeout_seconds
        try:
            async with self._semaphore:
                raw = await asyncio.wait_for(
                    self.client.post_chat_completion(
                        base_url=config.base_url,
                        api_key=config.api_key,
                        body=body,
                        timeout_seconds=timeout_seconds,
                    ),
                    timeout=timeout_seconds + 0.5,
                )
        except asyncio.TimeoutError as exc:
            raise InlineCompletionServiceError(504, "AI inline 补全请求超时", code="inline_completion_timeout") from exc
        except OpenAICompatibleClientError as exc:
            raise InlineCompletionServiceError(exc.status, exc.message, code=exc.code) from exc

        text = self._extract_text(raw)
        insert_text = self._clean_completion(text, context.prefix)
        latency_ms = int((time.perf_counter() - start) * 1000)
        result = self._result_from_text(
            normalized=normalized,
            model=str(raw.get("model") or config.model),
            insert_text=insert_text,
            usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else None,
            latency_ms=latency_ms,
            context=context,
        )
        self._cache[cache_key] = (now, result)
        return dict(result)

    def _validate_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("requestId") or "").strip()
        editor_id = str(request.get("editorId") or "").strip()
        path = str(request.get("path") or "").strip()
        trigger = str(request.get("trigger") or "auto").strip()
        cursor = request.get("cursor") or {}
        if not request_id or not editor_id or not path or trigger not in {"auto", "manual"} or not isinstance(cursor, dict):
            raise InlineCompletionServiceError(400, "补全请求参数无效", code="invalid_inline_completion_request")
        try:
            line = int(cursor.get("line") or 0)
            column = int(cursor.get("column") or 0)
            offset = int(cursor.get("offset") or 0)
        except (TypeError, ValueError) as exc:
            raise InlineCompletionServiceError(400, "补全请求参数无效", code="invalid_inline_completion_request") from exc
        return {
            "requestId": request_id,
            "editorId": editor_id,
            "path": path,
            "languageId": str(request.get("languageId") or ""),
            "cursor": {
                "line": line,
                "column": column,
                "offset": offset,
            },
            "prefix": str(request.get("prefix") or ""),
            "suffix": str(request.get("suffix") or ""),
            "trigger": trigger,
            "lastModifiedNs": str(request.get("lastModifiedNs") or ""),
        }

    def _check_auto_rate_limit(self, *, account_id: str, alias: str, trigger: str) -> None:
        if trigger != "auto":
            return
        key = (account_id, alias)
        now = time.monotonic()
        last = self._last_auto_request_at.get(key, 0.0)
        if now - last < 0.7:
            raise InlineCompletionServiceError(429, "AI inline 补全请求过于频繁", code="inline_completion_rate_limited")
        self._last_auto_request_at[key] = now

    def _build_chat_body(self, normalized: dict[str, Any], context: InlineCompletionContext) -> dict[str, Any]:
        config = self.config_store.config
        related_blocks = "\n\n".join(
            f"<related_file path=\"{item.path}\">\n{item.content}\n</related_file>"
            for item in context.related_files
        )
        max_lines = "1-20" if normalized["trigger"] == "manual" else "1-6"
        user_content = (
            f"File: {context.path}\n"
            f"Language: {normalized['languageId']}\n"
            f"Trigger: {normalized['trigger']}\n\n"
            f"<prefix>\n{context.prefix}\n</prefix>\n"
            f"<suffix>\n{context.suffix}\n</suffix>\n"
            f"{related_blocks}"
        )
        return {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You complete code at the cursor. Return only text to insert. "
                        "Do not use Markdown fences. Do not repeat text already present before the cursor. "
                        f"For this trigger return {max_lines} lines. Return an empty string if unsure."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": config.temperature,
            "max_completion_tokens": config.max_output_tokens,
        }

    @staticmethod
    def _extract_text(raw: dict[str, Any]) -> str:
        choices = raw.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        return str(content or "")

    @staticmethod
    def _clean_completion(text: str, prefix: str) -> str:
        cleaned = str(text or "").strip("\r\n")
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip("\r\n")
        prefix_tail = prefix[-200:]
        if cleaned and prefix_tail.endswith(cleaned):
            return ""
        for size in range(min(len(cleaned), len(prefix_tail)), 0, -1):
            if prefix_tail.endswith(cleaned[:size]):
                cleaned = cleaned[size:]
                break
        return cleaned.strip("\r\n")

    def _result_from_text(
        self,
        *,
        normalized: dict[str, Any],
        model: str,
        insert_text: str,
        usage: dict[str, Any] | None,
        latency_ms: int,
        context: InlineCompletionContext,
    ) -> dict[str, Any]:
        items = []
        if insert_text.strip():
            display_text = insert_text.splitlines()[0] if insert_text.splitlines() else insert_text
            items.append({"insertText": insert_text, "displayText": display_text})
        result: dict[str, Any] = {
            "requestId": normalized["requestId"],
            "model": model,
            "items": items,
            "latencyMs": latency_ms,
            "context": {
                "relatedFiles": [item.path for item in context.related_files],
                "truncated": context.truncated,
            },
        }
        if usage:
            result["usage"] = {
                "inputTokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                "outputTokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            }
        return result

    def _empty_result(
        self,
        normalized: dict[str, Any],
        *,
        model: str,
        latency_ms: int,
        context: InlineCompletionContext | None,
    ) -> dict[str, Any]:
        return {
            "requestId": normalized["requestId"],
            "model": model,
            "items": [],
            "latencyMs": latency_ms,
            "context": {
                "relatedFiles": [item.path for item in context.related_files] if context else [],
                "truncated": bool(context.truncated) if context else False,
            },
        }

    def _cache_key(
        self,
        normalized: dict[str, Any],
        context: InlineCompletionContext,
        *,
        account_id: str,
        alias: str,
        workspace_root: Path | str,
    ) -> str:
        config = self.config_store.config
        digest = hashlib.sha256()
        digest.update(str(account_id).encode("utf-8"))
        digest.update(str(alias).encode("utf-8"))
        digest.update(str(Path(workspace_root).expanduser().resolve()).encode("utf-8"))
        digest.update(config.base_url.encode("utf-8"))
        digest.update(config.model.encode("utf-8"))
        digest.update(str(config.temperature).encode("ascii"))
        digest.update(str(config.max_output_tokens).encode("ascii"))
        digest.update(normalized["path"].encode("utf-8"))
        digest.update(str(normalized["cursor"].get("offset", 0)).encode("ascii"))
        digest.update(context.prefix[-1000:].encode("utf-8"))
        digest.update(context.suffix[:1000].encode("utf-8"))
        for item in context.related_files:
            digest.update(item.path.encode("utf-8"))
            digest.update(hashlib.sha256(item.content.encode("utf-8", errors="replace")).digest())
        return digest.hexdigest()
