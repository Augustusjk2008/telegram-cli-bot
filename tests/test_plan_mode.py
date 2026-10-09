from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.web import api_service
from bot.web.plan_mode import save_execution_plan


@pytest.mark.asyncio
async def test_execute_plan_uses_title_for_filename_and_saves_only_body(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *args: (SimpleNamespace(remote_workspace=None), None, SimpleNamespace(working_dir=tmp_path)),
    )
    create_conversation = AsyncMock(return_value={"conversation": {"id": "new"}, "messages": []})
    monkeypatch.setattr(api_service, "create_conversation", create_conversation)
    title = "修复 Pi 会话复用"
    content = "## 目标\n修复会话复用。\n\n## 验证\n运行相关测试。"

    result = await api_service.execute_plan(None, "main", 42, content, title=title)

    path = tmp_path / result["plan_path"]
    assert path.name.endswith("-修复-pi-会话复用.md")
    assert path.read_text(encoding="utf-8") == content + "\n"
    assert result["plan_path"] in result["execution_message"]
    assert create_conversation.call_args.kwargs["title"] == title


def test_save_plan_sanitizes_title_and_preserves_existing_file(tmp_path):
    title = '../修复\\命名: *?"<>|'
    first = save_execution_plan(tmp_path, "原方案", title=title)
    second = save_execution_plan(tmp_path, "更新方案", title=title)

    assert first.path.parent == tmp_path / "docs" / "plan"
    assert first.path.name.endswith("-修复-命名.md")
    assert second.path.name == first.path.stem + "-2.md"
    assert Path(first.path).read_text(encoding="utf-8") == "原方案\n"
    assert Path(second.path).read_text(encoding="utf-8") == "更新方案\n"
