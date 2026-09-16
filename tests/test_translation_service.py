from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientConnectionError

from bot.web.openai_compatible_client import OpenAICompatibleClient, OpenAICompatibleClientError
from bot.web.translation_config import TranslationConfig, TranslationConfigStore
from bot.web.translation_service import TranslationService


CONFIG = TranslationConfig(
    translate_user_enabled=True, translate_assistant_enabled=True,
    base_url="https://provider.test/v1", api_key="sk-secret", model="translator",
    user_target_language="葡萄牙语（巴西）", assistant_target_language="繁體中文（臺灣）",
    request_timeout_seconds=2,
)


def completion(text="译文", finish_reason="stop"):
    return {"choices": [{"message": {"content": text}, "finish_reason": finish_reason}]}


def build_service(tmp_path, **kwargs):
    client = AsyncMock()
    client.post_chat_completion.return_value = completion()
    return TranslationService(
        config_store=TranslationConfigStore(tmp_path / "config.json"), client=client, **kwargs,
    )


@pytest.mark.asyncio
async def test_translation_uses_shared_http_client_and_restores_protected_content(tmp_path):
    source = (
        "请翻译下面的说明：\n\n"
        "```powershell\nWrite-Host '原样保留'\n```\n"
        "使用 `git status` 查看状态。\n"
        "附件路径为：C:\\Users\\张三\\My Project\\报告.pdf\n"
        "[说明](https://example.test/a_(b)?q=中文) 和 [本地](../docs/说明.md)\n"
        "路径 \"C:\\My Project\\app.py\" 与 /tmp/app.py、bot/web/main.py\n"
        "链接 https://example.test/api?q=中文\n"
        "git diff -- app.py\n"
        "<tcb_protocol>原样控制内容</tcb_protocol>\n"
        "<|tool_call|> {{KEEP_ME}} ${WORKSPACE} $PATH %TEMP% [[file:abc]]\n"
    )
    captured = {}
    response = MagicMock(status=200)

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        protected = kwargs["json"]["messages"][1]["content"]
        response.json = AsyncMock(return_value=completion(protected.replace("请翻译下面的说明", "Translated introduction")))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    session = MagicMock(closed=False)
    session.post.side_effect = post
    service = TranslationService(
        config_store=TranslationConfigStore(tmp_path / "config.json"),
        client=OpenAICompatibleClient(session=session),
    )
    result = await service.translate(source, config=CONFIG, target_language=CONFIG.user_target_language)
    assert result["status"] == "completed"
    assert result["text"] == source.replace("请翻译下面的说明", "Translated introduction")
    assert result["source_digest"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert result["target_language"] == CONFIG.user_target_language
    assert datetime.fromisoformat(result["completed_at"]).tzinfo is not None
    assert captured["url"] == "https://provider.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-secret"
    assert captured["json"]["model"] == CONFIG.model
    assert captured["json"]["stream"] is False
    messages = captured["json"]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system" and CONFIG.user_target_language in messages[0]["content"]
    protected = messages[1]["content"]
    for literal in ("Write-Host", "git status", "附件路径为", "https://example.test", "C:\\My Project", "../docs/说明.md", "git diff", "<tcb_protocol>", "{{KEEP_ME}}"):
        assert literal not in protected
    assert CONFIG.api_key not in json.dumps(captured["json"])
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", [
    "```python\nprint('未闭合代码块')",
    "~~~python\r\nprint('代码块')\r\n~~~~",
    "``code containing `inner` backticks``",
    "$ echo '保留命令'",
])
async def test_code_fences_inline_backticks_and_shell_commands_are_protected(tmp_path, protected):
    service = build_service(tmp_path)
    prose = "go home and make dinner"

    async def respond(**kwargs):
        content = kwargs["body"]["messages"][1]["content"]
        assert protected not in content
        assert prose in content
        return completion(content.replace(prose, "回家做晚饭"))

    service.client.post_chat_completion.side_effect = respond
    result = await service.translate(prose + "\n" + protected, config=CONFIG, target_language="中文")
    assert result["status"] == "completed"
    assert result["text"] == "回家做晚饭\n" + protected


@pytest.mark.asyncio
@pytest.mark.parametrize(("remote", "error"), [
    (TimeoutError("sk-secret"), "timeout"),
    (OpenAICompatibleClientError(401, "sk-secret"), "authentication_error"),
    (OpenAICompatibleClientError(500, "sk-secret"), "http_error"),
    (OpenAICompatibleClientError(502, "sk-secret", code="invalid_remote_response"), "invalid_response"),
    (ClientConnectionError("sk-secret"), "network_error"),
    (ValueError("sk-secret"), "invalid_response"),
    ({}, "invalid_response"),
    ({"choices": [None]}, "invalid_response"),
    (completion(" \n"), "empty_response"),
    (completion("部分译文", "length"), "truncated"),
    (completion("部分译文", "max_tokens"), "truncated"),
    (completion("拒绝", "content_filter"), "invalid_response"),
    (completion([{"text": "unexpected"}]), "invalid_response"),
])
async def test_failures_are_classified_without_secrets_or_retries(tmp_path, caplog, remote, error):
    service = build_service(tmp_path)
    if isinstance(remote, Exception):
        service.client.post_chat_completion.side_effect = remote
    else:
        service.client.post_chat_completion.return_value = remote
    result = await service.translate("源文本", config=CONFIG, target_language="任意语言")
    assert result == {
        "status": "failed", "error": error, "target_language": "任意语言",
        "source_digest": hashlib.sha256("源文本".encode("utf-8")).hexdigest(),
    }
    service.client.post_chat_completion.assert_awaited_once()
    assert "sk-secret" not in json.dumps(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "duplicate", "invented"])
async def test_incomplete_placeholder_restoration_fails(tmp_path, damage):
    service = build_service(tmp_path)

    async def respond(**kwargs):
        protected = kwargs["body"]["messages"][1]["content"]
        token = re.search(r"__TCB_TRANSLATION_\w+?__", protected).group()
        if damage == "missing":
            protected = protected.replace(token, "translated path")
        elif damage == "duplicate":
            protected += token
        else:
            protected += token.replace("_0__", "_999__")
        return completion(protected)

    service.client.post_chat_completion.side_effect = respond
    result = await service.translate("说明：`git status`", config=CONFIG, target_language="日语")
    assert result["status"] == "failed"
    assert result["error"] == "protected_content_mismatch"
    assert "text" not in result


@pytest.mark.asyncio
async def test_timeout_includes_concurrency_queue(tmp_path):
    service = build_service(tmp_path, max_concurrency=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return completion()

    service.client.post_chat_completion.side_effect = delayed
    first = asyncio.create_task(service.translate("第一条", config=CONFIG, target_language="日语"))
    await asyncio.wait_for(entered.wait(), 1)
    second = await service.translate(
        "第二条", config=replace(CONFIG, request_timeout_seconds=0.03), target_language="日语",
    )
    assert second["error"] == "timeout"
    assert service.client.post_chat_completion.await_count == 1
    release.set()
    assert (await first)["status"] == "completed"
    assert (await service.translate("第三条", config=CONFIG, target_language="日语"))["status"] == "completed"
    assert service.client.post_chat_completion.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_cancellation_propagates_and_releases_request_slots(tmp_path, queued):
    service = build_service(tmp_path, max_concurrency=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return completion()

    service.client.post_chat_completion.side_effect = delayed
    first = asyncio.create_task(service.translate("第一条", config=CONFIG, target_language="日语"))
    await asyncio.wait_for(entered.wait(), 1)
    cancelled = first
    if queued:
        cancelled = asyncio.create_task(service.translate("排队", config=CONFIG, target_language="日语"))
        await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert service.client.post_chat_completion.await_count == 1
    release.set()
    if queued:
        await first
    assert (await service.translate("恢复", config=CONFIG, target_language="日语"))["status"] == "completed"
    assert not service._requests


@pytest.mark.asyncio
async def test_answer_submission_is_nonblocking_bounded_and_deduplicated(tmp_path):
    service = build_service(tmp_path, max_concurrency=1, max_background_tasks=2)
    entered, release = asyncio.Event(), asyncio.Event()
    updates = []

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return completion()

    async def update(state):
        updates.append(state)

    service.client.post_chat_completion.side_effect = delayed
    args = dict(text="回答", config=CONFIG, message_id="answer-1", update=update)
    assert service.submit_answer(**args) is True
    assert updates == []
    service.client.post_chat_completion.assert_not_awaited()
    assert service.submit_answer(**args) is False
    assert service.submit_answer(**{**args, "message_id": "answer-2"}) is True
    assert service.submit_answer(**{**args, "message_id": "answer-3"}) is False
    await asyncio.wait_for(entered.wait(), 1)
    assert [state["status"] for state in updates] == ["pending", "pending"]
    assert service.client.post_chat_completion.await_count == 1
    release.set()
    await asyncio.gather(*service._answer_tasks.values())
    assert [state["status"] for state in updates] == ["pending", "pending", "completed", "completed"]
    assert all(state["target_language"] == CONFIG.assistant_target_language for state in updates)
    assert not service._answer_tasks
    assert service.submit_answer(**args) is False
    assert service.submit_answer(**{**args, "text": "修改后的回答"}) is True
    await asyncio.gather(*service._answer_tasks.values())
    await service.close()


@pytest.mark.asyncio
async def test_background_timeout_includes_pending_write(tmp_path):
    service = build_service(tmp_path)
    updates = []

    async def update(state):
        updates.append(state)
        if state["status"] == "pending":
            await asyncio.Event().wait()

    assert service.submit_answer(
        text="回答", config=replace(CONFIG, request_timeout_seconds=0.03), message_id="answer", update=update,
    )
    await asyncio.gather(*service._answer_tasks.values())
    assert [state["status"] for state in updates] == ["pending", "failed"]
    assert updates[-1]["error"] == "timeout"
    service.client.post_chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_failure_is_written_and_callback_errors_are_contained(tmp_path):
    service = build_service(tmp_path)
    service.client.post_chat_completion.side_effect = OpenAICompatibleClientError(401, "sk-secret")
    update = AsyncMock()
    assert service.submit_answer(text="回答", config=CONFIG, message_id="one", update=update)
    await asyncio.gather(*service._answer_tasks.values())
    assert update.await_args_list[-1].args[0]["error"] == "authentication_error"

    update.side_effect = RuntimeError("storage unavailable")
    assert service.submit_answer(text="回答", config=CONFIG, message_id="two", update=update)
    await asyncio.gather(*service._answer_tasks.values())
    assert not service._answer_tasks
    assert service.client.post_chat_completion.await_count == 1


@pytest.mark.asyncio
async def test_disabled_answers_stale_messages_and_close_do_not_schedule_work(tmp_path):
    service = build_service(tmp_path)
    update = AsyncMock(return_value=False)
    args = dict(text="回答", config=CONFIG, message_id="one", update=update)
    assert service.submit_answer(**{**args, "config": replace(CONFIG, translate_assistant_enabled=False)}) is False
    assert service.submit_answer(**args) is True
    await asyncio.gather(*service._answer_tasks.values())
    service.client.post_chat_completion.assert_not_awaited()

    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    update.return_value = None
    service.client.post_chat_completion.side_effect = delayed
    assert service.submit_answer(**{**args, "message_id": "two"}) is True
    await asyncio.wait_for(entered.wait(), 1)
    await service.close()
    assert cancelled.is_set()
    assert not service._requests and not service._answer_tasks
    service.client.close.assert_awaited_once()
    assert service.submit_answer(**{**args, "message_id": "three"}) is False
    result = await service.translate("提问", config=CONFIG, target_language="日语")
    assert result["error"] == "service_closed"


@pytest.mark.asyncio
async def test_singleton_is_shared_until_closed(tmp_path, monkeypatch):
    import bot.web.translation_service as module

    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "_translation_service", None)
    first = module.get_translation_service()
    assert module.get_translation_service() is first
    await first.close()
    second = module.get_translation_service()
    assert second is not first
    await second.close()
