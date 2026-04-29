from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.web.terminal_actions import (
    TerminalActionConfigConflict,
    TerminalActionValidationError,
    load_terminal_actions_config,
    resolve_terminal_action,
    save_terminal_actions_config,
)


def _write_config(workspace: Path, payload: dict) -> Path:
    config_path = workspace / "scripts" / "terminal-actions.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_load_terminal_actions_config_reads_valid_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.web.terminal_actions.get_runtime_platform", lambda: "linux")
    _write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {
                    "id": "build",
                    "label": "构建",
                    "icon": "Hammer",
                    "command": "npm run build",
                    "cwd": ".",
                    "confirm": False,
                    "enabled": True,
                }
            ],
        },
    )

    result = load_terminal_actions_config(tmp_path)

    assert result.exists is True
    assert result.errors == []
    assert result.config.schema_version == 1
    assert result.config.actions[0].id == "build"
    assert result.config.actions[0].linux_command == "npm run build"
    assert result.config.actions[0].windows_command == ""
    assert result.config.actions[0].command == "npm run build"
    assert result.config.actions[0].resolved_cwd == str(tmp_path.resolve())


def test_load_terminal_actions_config_returns_empty_when_missing(tmp_path: Path) -> None:
    result = load_terminal_actions_config(tmp_path)

    assert result.exists is False
    assert result.errors == []
    assert result.config.actions == ()
    assert result.mtime_ns == ""


def test_load_terminal_actions_config_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "scripts" / "terminal-actions.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")

    result = load_terminal_actions_config(tmp_path)

    assert result.exists is True
    assert result.config.actions == ()
    assert result.errors
    assert "无法解析" in result.errors[0]


def test_validate_rejects_duplicate_action_id(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {"id": "build", "label": "构建", "icon": "Hammer", "command": "npm run build"},
                {"id": "build", "label": "再次构建", "icon": "Hammer", "command": "npm run build"},
            ],
        },
    )

    result = load_terminal_actions_config(tmp_path)

    assert result.config.actions == ()
    assert any("重复" in item for item in result.errors)


def test_validate_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {"id": "bad", "label": "越界", "icon": "Hammer", "command": "pwd", "cwd": ".."},
            ],
        },
    )

    result = load_terminal_actions_config(tmp_path)

    assert result.config.actions == ()
    assert any("路径越界" in item for item in result.errors)


def test_save_terminal_actions_config_writes_normalized_json(tmp_path: Path) -> None:
    saved = save_terminal_actions_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {
                    "id": "test",
                    "label": "测试",
                    "icon": "TestTube2",
                    "windowsCommand": "python -m pytest tests -q",
                    "linuxCommand": "",
                }
            ],
        },
        expected_mtime_ns="",
    )

    assert saved.exists is True
    assert saved.errors == []
    assert (tmp_path / "scripts" / "terminal-actions.json").is_file()
    raw = json.loads((tmp_path / "scripts" / "terminal-actions.json").read_text(encoding="utf-8"))
    assert raw["actions"][0]["enabled"] is True
    assert raw["actions"][0]["windowsCommand"] == "python -m pytest tests -q"
    assert raw["actions"][0]["linuxCommand"] == ""
    assert "command" not in raw["actions"][0]


def test_save_terminal_actions_config_detects_mtime_conflict(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"schemaVersion": 1, "actions": []})
    current_mtime = str(path.stat().st_mtime_ns)

    with pytest.raises(TerminalActionConfigConflict):
        save_terminal_actions_config(
            tmp_path,
            {"schemaVersion": 1, "actions": []},
            expected_mtime_ns=str(int(current_mtime) - 1),
        )


def test_resolve_terminal_action_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.web.terminal_actions.get_runtime_platform", lambda: "linux")
    _write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {
                    "id": "clean",
                    "label": "清理",
                    "icon": "Trash2",
                    "windowsCommand": "",
                    "linuxCommand": "git clean -fdx",
                    "confirm": True,
                }
            ],
        },
    )

    with pytest.raises(TerminalActionValidationError, match="需要确认"):
        resolve_terminal_action(tmp_path, "clean", confirmed=False)

    action = resolve_terminal_action(tmp_path, "clean", confirmed=True)
    assert action.command == "git clean -fdx"


def test_resolve_terminal_action_rejects_missing_current_platform_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.web.terminal_actions.get_runtime_platform", lambda: "linux")
    _write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "actions": [
                {
                    "id": "build",
                    "label": "构建",
                    "icon": "Hammer",
                    "windowsCommand": "npm run build",
                    "linuxCommand": "",
                }
            ],
        },
    )

    with pytest.raises(TerminalActionValidationError, match="当前平台未配置命令"):
        resolve_terminal_action(tmp_path, "build", confirmed=True)
