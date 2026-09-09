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


def test_python_mcp_registers_tools_with_required_run_id() -> None:
    tools = {tool["name"]: tool for tool in mcp_stdio._tools_for_environment()}

    assert set(tools) == _CLUSTER_TOOL_NAMES
    for tool in tools.values():
        assert "run_id" in tool["inputSchema"]["required"]


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
