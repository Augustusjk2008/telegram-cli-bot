from pathlib import Path
from typing import Any

import pytest

from bot.web.inline_completion_config import InlineCompletionConfigStore
from bot.web.inline_completion_service import InlineCompletionService, InlineCompletionServiceError


class FakeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    async def post_chat_completion(self, *, base_url: str, api_key: str, body: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.requests.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class CountingClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def post_chat_completion(self, *, base_url: str, api_key: str, body: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.requests.append({"base_url": base_url, "api_key": api_key, "body": body, "timeout_seconds": timeout_seconds})
        return {
            "model": body["model"],
            "choices": [{"message": {"content": f"completion-{len(self.requests)}"}}],
        }


@pytest.mark.asyncio
async def test_inline_completion_service_requires_enabled_config(tmp_path: Path) -> None:
    store = InlineCompletionConfigStore(tmp_path / "inline.json")
    service = InlineCompletionService(config_store=store, client=FakeClient({}))

    with pytest.raises(InlineCompletionServiceError) as exc_info:
        await service.complete(
            account_id="acct",
            alias="main",
            workspace_root=tmp_path,
            request={
                "requestId": "req-1",
                "editorId": "editor-1",
                "path": "app.py",
                "languageId": "python",
                "cursor": {"line": 1, "column": 1, "offset": 0},
                "prefix": "",
                "suffix": "",
                "trigger": "manual",
            },
        )

    assert exc_info.value.status == 503
    assert exc_info.value.code == "inline_completion_not_configured"


@pytest.mark.asyncio
async def test_inline_completion_service_returns_clean_insert_text(tmp_path: Path) -> None:
    store = InlineCompletionConfigStore(tmp_path / "inline.json")
    store.update(
        {
            "enabled": True,
            "base_url": "https://provider.test/v1",
            "api_key": "sk-test",
            "model": "coder",
            "max_output_tokens": 64,
        }
    )
    client = FakeClient(
        {
            "model": "coder",
            "choices": [{"message": {"content": "```python\nprint('ok')\n```"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
    )
    service = InlineCompletionService(config_store=store, client=client)

    result = await service.complete(
        account_id="acct",
        alias="main",
        workspace_root=tmp_path,
        request={
            "requestId": "req-1",
            "editorId": "editor-1",
            "path": "app.py",
            "languageId": "python",
            "cursor": {"line": 1, "column": 1, "offset": 0},
            "prefix": "",
            "suffix": "",
            "trigger": "manual",
        },
    )

    assert result["requestId"] == "req-1"
    assert result["model"] == "coder"
    assert result["items"] == [{"insertText": "print('ok')", "displayText": "print('ok')"}]
    assert result["usage"] == {"inputTokens": 12, "outputTokens": 3}
    assert client.requests[0]["body"]["model"] == "coder"


@pytest.mark.asyncio
async def test_inline_completion_cache_is_scoped_to_workspace_and_related_context(tmp_path: Path) -> None:
    workspace_a = tmp_path / "a"
    workspace_b = tmp_path / "b"
    (workspace_a / "pkg").mkdir(parents=True)
    (workspace_b / "pkg").mkdir(parents=True)
    (workspace_a / "pkg" / "helper.py").write_text("VALUE = 'a'\n", encoding="utf-8")
    (workspace_b / "pkg" / "helper.py").write_text("VALUE = 'b'\n", encoding="utf-8")
    store = InlineCompletionConfigStore(tmp_path / "inline.json")
    store.update(
        {
            "enabled": True,
            "base_url": "https://provider.test/v1",
            "api_key": "sk-test",
            "model": "coder",
        }
    )
    client = CountingClient()
    service = InlineCompletionService(config_store=store, client=client)
    request = {
        "requestId": "req-1",
        "editorId": "editor-1",
        "path": "app.py",
        "languageId": "python",
        "cursor": {"line": 1, "column": 1, "offset": 0},
        "prefix": "from pkg import helper\n",
        "suffix": "",
        "trigger": "manual",
    }

    first = await service.complete(account_id="acct", alias="main", workspace_root=workspace_a, request=request)
    second = await service.complete(
        account_id="acct",
        alias="main",
        workspace_root=workspace_b,
        request={**request, "requestId": "req-2"},
    )

    assert first["items"][0]["insertText"] == "completion-1"
    assert second["items"][0]["insertText"] == "completion-2"
    assert len(client.requests) == 2
