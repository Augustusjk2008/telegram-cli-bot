from __future__ import annotations

from pathlib import Path

from bot.plugins.service import PluginService


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
