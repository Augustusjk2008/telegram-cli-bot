"""Shared translation boundary for accepted CLI and native chat turns."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
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


def translation_snapshot(*, enabled: bool = True, profile: Any | None = None) -> TranslationConfig | None:
    if not enabled:
        return None
    config = get_translation_service().config_store.get_config()
    if profile is None:
        return config
    # CLI translation follows the selected Bot's normal CLI configuration;
    # copy it into the immutable turn snapshot so later profile edits do not
    # change an in-flight translation.
    return replace(
        config,
        cli_type=str(getattr(profile, "cli_type", config.cli_type) or config.cli_type),
        cli_path=str(getattr(profile, "cli_path", config.cli_path) or config.cli_path),
        cli_params=getattr(getattr(profile, "cli_params", None), "to_dict", lambda: config.cli_params)(),
        cli_working_dir=str(getattr(profile, "working_dir", config.cli_working_dir) or config.cli_working_dir),
    )


def input_translation_pending(text: str, config: TranslationConfig | None) -> dict[str, Any] | None:
    if config is None or not config.translate_user_enabled:
        return None
    return {"status": "pending", "target_language": PROMPT_TARGET_LANGUAGE,
            "source_digest": hashlib.sha256(text.encode("utf-8")).hexdigest()}


async def prepare_chat_input(
    *,
    text: str,
    session: Any,
    history: Any,
    turn: Any,
    config: TranslationConfig | None,
    persist_input: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    execution_text, translated = await translate_chat_input(
        text=text,
        session=session,
        config=config,
        history=history if persist_input else None,
        message_id=turn.user_message_id if persist_input else "",
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if persist_input:
        await asyncio.to_thread(
            history.update_message_translation,
            turn.user_message_id,
            source_digest=digest,
            translation=translated,
            agent_input_text=execution_text,
        )
    check_chat_stopped(session)
    return execution_text, translated


async def translate_chat_input(
    *,
    text: str,
    session: Any,
    config: TranslationConfig | None,
    history: Any | None = None,
    message_id: str = "",
) -> tuple[str, dict[str, Any] | None]:
    check_chat_stopped(session)
    translated = None
    execution_text = text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if config is not None and config.translate_user_enabled:
        async def translate() -> dict[str, Any]:
            pending = input_translation_pending(text, config)
            if history is not None and message_id:
                await asyncio.to_thread(
                    history.update_message_translation,
                    message_id,
                    source_digest=digest,
                    translation=pending,
                )
            return await get_translation_service().translate(text, config=config, direction="user")

        task = asyncio.create_task(translate(), name="chat-input-translation")
        _INPUT_TASKS[id(session)] = task
        try:
            translated = await task
        except asyncio.CancelledError:
            if session.stop_requested:
                if history is not None and message_id:
                    await asyncio.to_thread(
                        history.update_message_translation,
                        message_id,
                        source_digest=digest,
                        translation={
                            "status": "failed",
                            "error": "cancelled",
                            "target_language": PROMPT_TARGET_LANGUAGE,
                            "source_digest": digest,
                        },
                    )
                raise ChatInputCancelled() from None
            raise
        finally:
            _INPUT_TASKS.pop(id(session), None)
        check_chat_stopped(session)
        if translated.get("status") == "completed":
            execution_text = translated["text"]
    if execution_text.startswith("//"):
        execution_text = "/" + execution_text[2:]
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
