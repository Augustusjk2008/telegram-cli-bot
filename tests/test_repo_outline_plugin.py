from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bot.plugins.service import PluginService


@pytest.mark.asyncio
async def test_repo_outline_open_children_file_symbols_and_search(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "bot" / "web").mkdir(parents=True)
    (repo_root / "bot" / "web" / "api_service.py").write_text(
        "class ApiService:\n    def run_cli_chat(self):\n        return True\n",
        encoding="utf-8",
    )
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    shutil.copytree(Path("examples/plugins/repo-outline"), plugins_root / "repo-outline")

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="repo-outline",
        view_id="repo-tree",
        input_payload={},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    bot_node = next(node for node in opened["initialWindow"]["nodes"] if node["label"] == "bot")
    bot_children = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": bot_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    web_node = next(node for node in bot_children["nodes"] if node["label"] == "web")

    web_children = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": web_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    file_node = next(node for node in web_children["nodes"] if node["label"] == "api_service.py")

    symbols = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": file_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    search = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "search", "query": "run_cli_chat"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert opened["renderer"] == "tree"
    assert opened["initialWindow"]["op"] == "children"
    assert any(node["label"] == "README.md" for node in opened["initialWindow"]["nodes"])
    assert any(node["label"] == "run_cli_chat" and node["kind"] == "function" for node in symbols["nodes"])
    assert search["nodes"][0]["label"] == "api_service.py"
    assert search["nodes"][0]["children"][0]["label"] == "run_cli_chat"

    await service.shutdown()


@pytest.mark.asyncio
async def test_repo_outline_respects_hidden_and_symbol_limits(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".hidden").mkdir(parents=True)
    (repo_root / ".hidden" / "secret.py").write_text("def hide():\n    return True\n", encoding="utf-8")
    (repo_root / "src").mkdir(parents=True)
    many_symbols = "\n\n".join(f"def func_{index}():\n    return {index}" for index in range(25))
    (repo_root / "src" / "app.py").write_text(many_symbols + "\n", encoding="utf-8")

    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    target_plugin_dir = plugins_root / "repo-outline"
    shutil.copytree(Path("examples/plugins/repo-outline"), target_plugin_dir)

    manifest_path = target_plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["maxSymbolsPerFile"] = 20
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="repo-outline",
        view_id="repo-tree",
        input_payload={},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert all(node["label"] != ".hidden" for node in opened["initialWindow"]["nodes"])

    src_node = next(node for node in opened["initialWindow"]["nodes"] if node["label"] == "src")
    src_children = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": src_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    app_node = next(node for node in src_children["nodes"] if node["label"] == "app.py")
    symbols = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": app_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert len(symbols["nodes"]) == 20
    assert symbols["nodes"][0]["label"] == "func_0"

    await service.shutdown()


@pytest.mark.asyncio
async def test_repo_outline_opens_from_selected_folder(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "bot" / "web").mkdir(parents=True)
    (repo_root / "bot" / "web" / "api_service.py").write_text("def serve():\n    return True\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    shutil.copytree(Path("examples/plugins/repo-outline"), plugins_root / "repo-outline")

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="repo-outline",
        view_id="repo-tree",
        input_payload={"path": "bot"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert opened["title"] == "文件夹大纲"
    assert any(node["label"] == "web" for node in opened["initialWindow"]["nodes"])
    assert all(node["label"] != "README.md" for node in opened["initialWindow"]["nodes"])

    search = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "search", "query": "serve"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert search["nodes"][0]["label"] == "api_service.py"

    await service.shutdown()


@pytest.mark.asyncio
async def test_repo_outline_ignores_file_outline_decode_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "legacy.py").write_bytes(b"def ok():\n    return '\\xce'\n")

    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    shutil.copytree(Path("examples/plugins/repo-outline"), plugins_root / "repo-outline")

    def raise_decode_error(_workspace: Path | str, _path: str) -> dict[str, object]:
        raise UnicodeDecodeError("utf-8", b"\xce", 0, 1, "invalid continuation byte")

    monkeypatch.setattr("bot.plugins.host_api.build_file_outline", raise_decode_error)

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="repo-outline",
        view_id="repo-tree",
        input_payload={},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    file_node = next(node for node in opened["initialWindow"]["nodes"] if node["label"] == "legacy.py")

    symbols = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "children", "nodeId": file_node["id"]},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    search = await service.get_view_window(
        bot_alias="main",
        plugin_id="repo-outline",
        session_id=opened["sessionId"],
        request_payload={"op": "search", "query": "legacy"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert symbols["nodes"] == []
    assert search["nodes"][0]["label"] == "legacy.py"

    await service.shutdown()
