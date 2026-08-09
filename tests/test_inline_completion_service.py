from pathlib import Path

from typing import Any

import pytest

from bot.web.inline_completion_config import InlineCompletionConfigStore

from bot.web.inline_completion_service import InlineCompletionService, InlineCompletionServiceError

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
