from __future__ import annotations

import json
from pathlib import Path

from bot.cluster import mcp_stdio


_CLUSTER_TOOL_NAMES = {
    "configure_team",
    "cluster_status",
    "list_agents",
    "new_agent_session",
    "ask_agent",
    "poll_agent_tasks",
    "wait_agent_messages",
}

_CONFIGURE_TEAM_SCHEMA = {
    "type": "object",
    "required": ["run_id", "mode", "roles"],
    "properties": {
        "run_id": {"type": "string", "description": "TCB cluster run id."},
        "mode": {"type": "string", "enum": ["extend", "replace"]},
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "responsibility"],
                "properties": {
                    "name": {"type": "string"},
                    "responsibility": {"type": "string"},
                },
            },
        },
    },
}


def test_python_mcp_registers_required_run_id_and_configure_team_schema() -> None:
    tools = {tool["name"]: tool for tool in mcp_stdio._tools_for_environment()}

    assert set(tools) == _CLUSTER_TOOL_NAMES
    assert tools["configure_team"]["inputSchema"] == _CONFIGURE_TEAM_SCHEMA
    description = tools["configure_team"]["description"]
    assert "必须查看响应中的 changed" in description
    assert "changed=true" in description
    assert "本轮所有后续工具立即改用响应中的新 run_id" in description
    assert "changed=false" in description
    assert "继续使用原 run_id" in description
    assert "stdio MCP 不缓存或自动切换 run_id" in description
    for tool in tools.values():
        assert "run_id" in tool["inputSchema"]["required"]


def test_pi_extension_matches_configure_team_schema_and_requires_run_id() -> None:
    source = (
        Path(__file__).parents[1]
        / "bot"
        / "cluster"
        / "pi_extension"
        / "tcb-cluster.ts"
    ).read_text(encoding="utf-8")
    compact = " ".join(source.split())

    assert "TCB_CLUSTER_RUN_ID" not in source
    assert 'const runIdParam = Type.String({ description: "TCB cluster run id." });' in compact
    assert compact.count("run_id: runIdParam") == len(_CLUSTER_TOOL_NAMES)
    assert '"configure_team", "Configure Team"' in compact
    assert 'mode: Type.String({ enum: ["extend", "replace"] })' in compact
    assert "roles: Type.Array(Type.Object({ name: Type.String(), responsibility: Type.String(), }))" in compact
    assert "必须查看响应中的 changed" in source
    assert "changed=true" in source
    assert "本轮所有后续工具立即改用响应中的新 run_id" in source
    assert "changed=false" in source
    assert "继续使用原 run_id" in source
    assert "Pi 适配层不缓存或自动切换 run_id" in source
    assert "const runId = clusterRunId(params.run_id);" in source


def test_python_mcp_forwards_each_call_run_id_without_caching(monkeypatch, tmp_path: Path) -> None:
    seen_run_ids: list[str] = []

    monkeypatch.setattr(mcp_stdio, "load_mcp_bridge_config", lambda _path: object())

    def record_call(_config, _name, _arguments, *, run_id: str):
        seen_run_ids.append(run_id)
        return {"ok": True}

    monkeypatch.setattr(mcp_stdio, "post_mcp_tool", record_call)

    for request_id, run_id in enumerate(("run-1", "run-2"), start=1):
        response = mcp_stdio.handle_request(
            tmp_path / "bridge.json",
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "cluster_status",
                    "arguments": {"run_id": run_id},
                },
            },
        )
        assert response is not None
        assert response["result"].get("isError") is not True

    assert seen_run_ids == ["run-1", "run-2"]


def test_python_mcp_rejects_missing_run_id_before_loading_bridge_config(monkeypatch, tmp_path: Path) -> None:
    config_loaded = False

    def fail_if_loaded(_path: Path):
        nonlocal config_loaded
        config_loaded = True
        raise AssertionError("missing run_id must fail before config loading")

    monkeypatch.setenv("TCB_CLUSTER_RUN_ID", "legacy-env-run")
    monkeypatch.setattr(mcp_stdio, "load_mcp_bridge_config", fail_if_loaded)

    response = mcp_stdio.handle_request(
        tmp_path / "missing.json",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "cluster_status", "arguments": {}},
        },
    )

    assert response is not None
    assert response["result"]["isError"] is True
    error = json.loads(response["result"]["content"][0]["text"])
    assert error["error"] == "run_id is required"
    assert error["error_type"] == "ValueError"
    assert config_loaded is False
