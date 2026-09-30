from pathlib import Path

import pytest

from bot.cluster.setup import (
    build_cli_install_command,
    build_cli_remove_command,
    build_cli_verify_command,
    normalize_cli_kind,
)


@pytest.mark.parametrize("cli_type", ["codex", "codex_server"])
@pytest.mark.parametrize("cli_path", ["", "C:/tools/custom codex.cmd"])
def test_codex_mcp_setup_preserves_backend_and_uses_codex_commands(cli_type, cli_path):
    launcher = Path("bridge/tcb-cluster-mcp.cmd")
    executable = cli_path or "codex"

    assert normalize_cli_kind(cli_type) == cli_type
    assert build_cli_install_command(cli_type=cli_type, cli_path=cli_path, launcher_path=launcher) == [
        executable, "mcp", "add", "tcb-cluster", "--", str(launcher),
    ]
    assert build_cli_verify_command(cli_type, cli_path) == [executable, "mcp", "get", "tcb-cluster"]
    assert build_cli_remove_command(cli_type, cli_path) == [executable, "mcp", "remove", "tcb-cluster"]


def test_codex_server_mcp_injection_keeps_codex_params_isolated(tmp_path, monkeypatch):
    from bot.cli_params import CliParamsConfig
    from bot.models import BotProfile
    from bot.web.api_service import _cluster_mcp_injected_params

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    params = CliParamsConfig.from_dict({
        "codex": {"model": "exec-model", "extra_args": ["-c", "exec_only=true"]},
        "codex_server": {"model": "server-model", "extra_args": ["-c", "server_only=true"]},
    })
    before = params.to_dict()
    result = _cluster_mcp_injected_params(BotProfile(alias="cluster", cli_type="codex_server"), params)

    assert params.to_dict() == before
    assert result.get_params("codex") == before["codex"]
    assert result.get_param("codex_server", "model") == "server-model"
    args = result.get_param("codex_server", "extra_args")
    assert args[:2] == ["-c", "server_only=true"]
    assert any(arg.startswith("mcp_servers.tcb-cluster.command=") for arg in args)
    assert 'mcp_servers.tcb-cluster.default_tools_approval_mode="approve"' in args
