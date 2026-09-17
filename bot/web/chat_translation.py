"""Shared translation boundary for accepted CLI and native chat turns."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from .translation_config import PROMPT_TARGET_LANGUAGE, TranslationConfig
from .translation_service import get_translation_service


class ChatInputCancelled(Exception):
    """The accepted turn was stopped before sending its prompt."""


_INPUT_TASKS: dict[int, asyncio.Task[Any]] = {}


def input_is_preparing(session: Any) -> bool:
    return id(session) in _INPUT_TASKS


def cancel_input_preparation(session: Any) -> None:
    task = _INPUT_TASKS.get(id(session))
    if task is not None:
        task.cancel()


def check_chat_stopped(session: Any) -> None:
    with session._lock:
        if session.stop_requested:
            raise ChatInputCancelled()


def translation_snapshot(*, enabled: bool = True) -> TranslationConfig | None:
    return get_translation_service().config_store.get_config() if enabled else None


def input_translation_pending(text: str, config: TranslationConfig | None) -> dict[str, Any] | None:
    if config is None or not config.translate_user_enabled:
        return None
    return {"status": "pending", "target_language": PROMPT_TARGET_LANGUAGE,
            "source_digest": hashlib.sha256(text.encode("utf-8")).hexdigest()}


async def prepare_chat_input(
    *, text: str, session: Any, history: Any, turn: Any, config: TranslationConfig | None,
) -> tuple[str, dict[str, Any] | None]:
    check_chat_stopped(session)
    translated = None
    execution_text = text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if config is not None and config.translate_user_enabled:
        async def translate() -> dict[str, Any]:
            pending = input_translation_pending(text, config)
            await asyncio.to_thread(history.update_message_translation, turn.user_message_id, source_digest=digest, translation=pending)
            return await get_translation_service().translate(text, config=config, direction="user")

        task = asyncio.create_task(translate(), name="chat-input-translation")
        _INPUT_TASKS[id(session)] = task
        try:
            translated = await task
        except asyncio.CancelledError:
            if session.stop_requested:
                await asyncio.to_thread(history.update_message_translation, turn.user_message_id, source_digest=digest,
                                        translation={"status": "failed", "error": "cancelled", "target_language": PROMPT_TARGET_LANGUAGE, "source_digest": digest})
                raise ChatInputCancelled() from None
            raise
        finally:
            _INPUT_TASKS.pop(id(session), None)
        check_chat_stopped(session)
        if translated.get("status") == "completed":
            execution_text = translated["text"]
    if execution_text.startswith("//"):
        execution_text = "/" + execution_text[2:]
    # Even disabled translation records the exact body used for native trace recovery.
    await asyncio.to_thread(history.update_message_translation, turn.user_message_id, source_digest=digest, translation=translated, agent_input_text=execution_text)
    check_chat_stopped(session)
    return execution_text, translated


def submit_answer_translation(
    *, history: Any, message: dict[str, Any], config: TranslationConfig | None, completion_state: str,
) -> None:
    if config is None or not config.translate_assistant_enabled or completion_state != "completed":
        return
    text = str(message.get("content") or "")
    message_id = str(message.get("id") or "")
    if not text.strip() or not message_id:
        return
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def update(translation: dict[str, Any]) -> bool:
        return await asyncio.to_thread(history.update_message_translation, message_id, source_digest=digest, translation=translation)

    if get_translation_service().submit_answer(text=text, config=config, message_id=message_id, update=update):
        message["translation"] = {"status": "pending", "target_language": PROMPT_TARGET_LANGUAGE, "source_digest": digest}
