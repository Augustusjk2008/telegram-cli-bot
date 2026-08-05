from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.plugins.service import PluginService
from bot.plugins.view_sessions import PluginViewSessionRecord


def _service(tmp_path: Path, **kwargs) -> PluginService:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    return PluginService(
        tmp_path,
        plugins_root=tmp_path / "plugins",
        source_plugins_root=source_root,
        **kwargs,
    )


def test_snapshot_cache_uses_lru_entry_limit_and_reports_diagnostics(tmp_path: Path) -> None:
    service = _service(tmp_path, snapshot_cache_max_entries=2, snapshot_cache_max_bytes=1000)

    service._snapshot_cache_remember("plugin", "a", {"value": "a"})
    service._snapshot_cache_remember("plugin", "b", {"value": "b"})
    assert service._snapshot_cache_get("a") == {"value": "a"}
    service._snapshot_cache_remember("plugin", "c", {"value": "c"})

    assert service._snapshot_cache_get("b") is None
    assert service._snapshot_cache_get("a") == {"value": "a"}
    assert service._snapshot_cache_get("c") == {"value": "c"}
    assert service.snapshot_cache_diagnostics() == {
        "entries": 2,
        "bytes": service._snapshot_cache_bytes,
        "hits": 3,
        "misses": 1,
        "evictions": 1,
    }


def test_snapshot_cache_enforces_byte_budget_and_plugin_invalidation(tmp_path: Path) -> None:
    service = _service(tmp_path, snapshot_cache_max_entries=5, snapshot_cache_max_bytes=30)

    service._snapshot_cache_remember("first", "a", {"value": "1234567890"})
    service._snapshot_cache_remember("second", "b", {"value": "abcdefghij"})

    assert service.snapshot_cache_diagnostics()["bytes"] <= 30
    assert service.snapshot_cache_diagnostics()["evictions"] == 1
    assert service._snapshot_cache_get("a") is None
    assert service._snapshot_cache_get("b") == {"value": "abcdefghij"}

    service._snapshot_cache_clear_plugin("second")
    assert service.snapshot_cache_diagnostics()["entries"] == 0
    assert service.snapshot_cache_diagnostics()["bytes"] == 0


@pytest.mark.asyncio
async def test_plugin_update_reloads_manifest_and_disposes_session_runtime(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "test-plugin"
    plugin_dir.mkdir(parents=True)
    manifest_path = plugin_dir / "plugin.json"
    manifest_path.write_text(json.dumps({
        "schemaVersion": 2, "id": "test-plugin", "name": "Test", "version": "1.0.0", "description": "", "enabled": True,
        "config": {"color": "blue"}, "runtime": {"type": "python", "entry": "main.py", "protocol": "jsonrpc-stdio", "permissions": {}},
        "views": [{"id": "main", "title": "Main", "renderer": "document", "viewMode": "session", "dataProfile": "light"}], "fileHandlers": [],
    }), encoding="utf-8")
    service = _service(tmp_path)
    calls: list[tuple[str, ...]] = []

    async def dispose_view(bot_alias, manifest, session_id):
        calls.append(("dispose", bot_alias, manifest.plugin_id, session_id))
        return {"disposed": True}

    async def stop_plugin_instances(plugin_id):
        calls.append(("stop", plugin_id))

    service.runtime = SimpleNamespace(dispose_view=dispose_view, stop_plugin_instances=stop_plugin_instances)
    service.sessions.replace(PluginViewSessionRecord("bot-a", "test-plugin", "main", "session-a", "document", "source", "fingerprint", {}, {}))

    updated = await service.update_plugin("test-plugin", config={"color": "green"})

    assert updated["config"] == {"color": "green"}
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["config"] == {"color": "green"}
    assert service.sessions.get_optional("session-a") is None
    assert calls == [("dispose", "bot-a", "test-plugin", "session-a"), ("stop", "test-plugin")]
