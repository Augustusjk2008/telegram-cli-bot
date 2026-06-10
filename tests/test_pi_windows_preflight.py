from __future__ import annotations

from pathlib import Path
from typing import Any

from bot.native_agent.pi_rpc_preflight import PiWindowsPreflightRequest, run_pi_windows_preflight


def _check(result: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in result["checks"] if item["key"] == key)


def _resolver(mapping: dict[str, str | None]):
    def resolve(command: str, _cwd: str | None = None) -> str | None:
        return mapping.get(command)

    return resolve


def _runner(stdout: str = "v22.0.0\n", returncode: int = 0):
    def run(_command: list[str]) -> tuple[int, str, str]:
        return returncode, stdout, ""

    return run


def _request(tmp_path: Path, **kwargs: Any) -> PiWindowsPreflightRequest:
    return PiWindowsPreflightRequest(cwd=tmp_path, data_dir=tmp_path / "data", **kwargs)


def test_pi_windows_preflight_reports_missing_node(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path),
        os_name="nt",
        resolve_executable=_resolver({"pi": "C:/npm/pi.cmd", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is False
    assert _check(result, "node")["ok"] is False
    assert "未找到 node" in _check(result, "node")["message"]
    assert "Node.js 22" in _check(result, "node")["fix"]


def test_pi_windows_preflight_rejects_node_below_22(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "pi": "C:/npm/pi.cmd", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner("v21.11.0\n"),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is False
    assert _check(result, "node")["ok"] is False
    assert "当前版本 v21.11.0" in _check(result, "node")["message"]


def test_pi_windows_preflight_reports_missing_pi(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path, pi_command="pi"),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is False
    assert _check(result, "pi")["ok"] is False
    assert "未找到 pi" in _check(result, "pi")["message"]
    assert "NATIVE_AGENT_PI_COMMAND" in _check(result, "pi")["fix"]


def test_pi_windows_preflight_reports_missing_bash_on_windows(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "pi": "C:/npm/pi.cmd"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is False
    assert _check(result, "bash")["ok"] is False
    assert "未找到 bash" in _check(result, "bash")["message"]


def test_pi_windows_preflight_reports_unwritable_data_dir(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "pi": "C:/npm/pi.cmd", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: False,
    )

    assert result["ok"] is False
    assert _check(result, "data_dir")["ok"] is False
    assert "不可写" in _check(result, "data_dir")["message"]


def test_pi_windows_preflight_reports_workspace_history_unknown(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path, workspace_history_enabled=None),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "pi": "C:/npm/pi.cmd", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is False
    assert _check(result, "workspace_history")["ok"] is False
    assert "无法判定" in _check(result, "workspace_history")["message"]


def test_pi_windows_preflight_accepts_workspace_history_disabled(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path, workspace_history_enabled=False),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "pi": "C:/npm/pi.cmd", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    assert result["ok"] is True
    assert _check(result, "workspace_history")["ok"] is True
    assert "已关闭" in _check(result, "workspace_history")["message"]


def test_pi_windows_preflight_uses_chinese_executable_errors(tmp_path: Path) -> None:
    result = run_pi_windows_preflight(
        _request(tmp_path, pi_command="C:/Missing/pi.cmd"),
        os_name="nt",
        resolve_executable=_resolver({"node": "C:/node/node.exe", "bash": "C:/Git/bin/bash.exe"}),
        run_command=_runner(),
        is_dir_writable=lambda _path: True,
    )

    message = _check(result, "pi")["message"]
    assert "未找到" in message
    assert "C:/Missing/pi.cmd" in message
