from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.plugins.catalog import classify_plugin_install
from bot.plugins.service import PluginService


def _write_plugin(root: Path, plugin_id: str, version: str) -> None:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({
            "schemaVersion": 2,
            "id": plugin_id,
            "name": plugin_id.title(),
            "version": version,
            "runtime": {"type": "python", "entry": "main.py", "protocol": "jsonrpc-stdio"},
        }),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_directory_install_reports_each_plugin_outcome_against_installed_versions(tmp_path: Path) -> None:
    service = PluginService(
        tmp_path,
        plugins_root=tmp_path / "plugins",
        source_plugins_root=tmp_path / "bundled",
    )
    first = tmp_path / "first"
    _write_plugin(first, "alpha", "0.1.0")
    _write_plugin(first, "beta", "0.3.0")
    _write_plugin(first, "gamma", "1.0.0")
    initial = await service.install_plugins_from_path(first, force=True)
    assert [(item["id"], item["installOutcome"], item["previousVersion"]) for item in initial["installed"]] == [
        ("alpha", "installed", None),
        ("beta", "installed", None),
        ("gamma", "installed", None),
    ]

    second = tmp_path / "second"
    _write_plugin(second, "alpha", "0.2.0")
    _write_plugin(second, "beta", "0.3.0")
    _write_plugin(second, "delta", "0.1.0")
    _write_plugin(second, "gamma", "0.9.0")
    result = await service.install_plugins_from_path(second, force=True)

    assert result["discovered"] == 4
    assert [
        (item["id"], item["version"], item["installOutcome"], item["previousVersion"])
        for item in result["installed"]
    ] == [
        ("alpha", "0.2.0", "upgraded", "0.1.0"),
        ("beta", "0.3.0", "reinstalled", "0.3.0"),
        ("delta", "0.1.0", "installed", None),
        ("gamma", "0.9.0", "downgraded", "1.0.0"),
    ]
    assert {plugin["id"]: plugin["version"] for plugin in service.list_plugins()} == {
        "alpha": "0.2.0",
        "beta": "0.3.0",
        "delta": "0.1.0",
        "gamma": "0.9.0",
    }


@pytest.mark.parametrize(
    ("previous_version", "version", "outcome"),
    [
        ("1.0.0", "v1.0.0", "reinstalled"),
        ("", "0.1.0", "upgraded"),
        ("1.1", "1.0", "upgraded"),
    ],
)
def test_install_outcome_treats_equal_semver_as_reinstall_and_unordered_changes_as_upgrade(
    previous_version: str,
    version: str,
    outcome: str,
) -> None:
    assert classify_plugin_install(previous_version, version) == outcome
