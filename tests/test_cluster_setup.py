import json
from pathlib import Path

import pytest

from bot.cluster.setup import (
    CLUSTER_MCP_SERVER_NAME,
    build_cli_install_command,
    build_cli_remove_command,
    build_cli_verify_command,
    ensure_antigravity_mcp_config,
    inspect_antigravity_mcp_config,
    normalize_cli_kind,
    remove_antigravity_mcp_config,
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


def test_antigravity_workspace_mcp_setup_preserves_other_servers_and_restores_on_stop(tmp_path):
    config_path = tmp_path / ".agents" / "mcp_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({
        "mcpServers": {
            "user-server": {"command": "user-tool", "args": ["--keep"]},
        },
    }), encoding="utf-8")
    launcher = tmp_path / "bin" / "tcb-cluster-mcp.cmd"

    setup = ensure_antigravity_mcp_config(tmp_path, launcher)
    assert setup["installed"] is True
    assert setup["conflict"] is False
    configured = json.loads(config_path.read_text(encoding="utf-8"))
    assert configured["mcpServers"]["user-server"] == {"command": "user-tool", "args": ["--keep"]}
    assert configured["mcpServers"][CLUSTER_MCP_SERVER_NAME]["command"] == str(launcher)
    assert configured["mcpServers"][CLUSTER_MCP_SERVER_NAME]["args"] == []

    removed = remove_antigravity_mcp_config(tmp_path)
    assert removed["changed"] is True
    restored = json.loads(config_path.read_text(encoding="utf-8"))
    assert restored == {"mcpServers": {"user-server": {"command": "user-tool", "args": ["--keep"]}}}


def test_antigravity_workspace_mcp_setup_does_not_overwrite_user_entry(tmp_path):
    config_path = tmp_path / ".agents" / "mcp_config.json"
    config_path.parent.mkdir(parents=True)
    original = {
        "mcpServers": {
            CLUSTER_MCP_SERVER_NAME: {"command": "user-owned", "args": ["--custom"]},
        },
    }
    config_path.write_text(json.dumps(original), encoding="utf-8")

    setup = ensure_antigravity_mcp_config(tmp_path, tmp_path / "generated.cmd")

    assert setup["conflict"] is True
    assert json.loads(config_path.read_text(encoding="utf-8")) == original
    assert inspect_antigravity_mcp_config(tmp_path, tmp_path / "generated.cmd")["state"] == "conflict"


def test_antigravity_workspace_mcp_setup_keeps_user_edit_when_removing(tmp_path):
    launcher = tmp_path / "generated.cmd"
    ensure_antigravity_mcp_config(tmp_path, launcher)
    config_path = tmp_path / ".agents" / "mcp_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["mcpServers"][CLUSTER_MCP_SERVER_NAME]["args"] = ["user-edited"]
    config_path.write_text(json.dumps(config), encoding="utf-8")

    removed = remove_antigravity_mcp_config(tmp_path)

    assert removed["conflict"] is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"][CLUSTER_MCP_SERVER_NAME]["args"] == ["user-edited"]
