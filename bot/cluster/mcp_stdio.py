from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.cluster.mcp_client import load_mcp_bridge_config, post_mcp_tool


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _tools_for_environment() -> list[dict[str, Any]]:
    return [
        {
            "name": "configure_team",
            "description": "Configure the current main session's team. The main agent may autonomously use extend to add roles in free slots; use replace only when the user explicitly requests regrouping, reducing, or clearing the team. Always pass run_id. After success, check changed in the response: if changed=true, immediately use the new run_id from the response for all subsequent tool calls in this turn; if changed=false, keep using the original run_id. The stdio MCP adapter does not cache or automatically switch run_id.",
            "inputSchema": {
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
            },
        },
        {
            "name": "cluster_status",
            "description": "Inspect the current team, internal agent IDs for roles, capacity, free slots, and task occupancy. Always pass run_id.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        },
        {
            "name": "list_agents",
            "description": "List the current team, internal agent IDs for roles, capacity, free slots, and task occupancy. Always pass run_id.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"include_disabled": {"type": "boolean"}, "run_id": {"type": "string"}},
            },
        },
        {
            "name": "new_agent_session",
            "description": "Start a new session for a child agent whose current session is idle and has no queued/running cluster tasks. Always pass run_id. Previous session history is preserved.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id", "agent_id"],
                "properties": {
                    "agent_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
            },
        },
        {
            "name": "ask_agent",
            "description": "Start an asynchronous TCB child agent task and immediately return task_id. Always pass run_id. The main agent may continue calling poll_agent_tasks to wait for and summarize results, or end its turn while the task runs in the background. timeout_seconds is a soft deadline and defaults to the Bot setting when omitted; exceeding it does not forcibly interrupt the child agent, and poll_agent_tasks reports deadline_exceeded. model_tier accepts low/medium/high and uses the model and reasoning effort configured for that tier; blank tier settings inherit from the main agent.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id", "agent_id", "message"],
                "properties": {
                    "agent_id": {"type": "string"},
                    "message": {"type": "string"},
                    "model_tier": {"type": "string", "enum": ["low", "medium", "high"]},
                    "timeout_seconds": {"type": "integer"},
                    "allow_write": {"type": "boolean"},
                    "run_id": {"type": "string"},
                },
            },
        },
        {
            "name": "poll_agent_tasks",
            "description": "Poll asynchronous child agent task status, progress messages, and results in the current TCB cluster. Always pass run_id. Empty task_ids returns all tasks in the current run. Optional wait_seconds waits for task completion within this tool call; it defaults to 0 for an immediate return. include_messages defaults to true; messages[].kind is progress or final, and messages exclude events/tool calls.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "task_ids": {"type": "array", "items": {"type": "string"}},
                    "include_output": {"type": "boolean"},
                    "include_messages": {"type": "boolean"},
                    "message_limit": {"type": "integer"},
                    "wait_seconds": {"type": "number"},
                },
            },
        },
        {
            "name": "wait_agent_messages",
            "description": "Block until the next unread message from any child agent in the current TCB cluster. Always pass run_id. Use the server's unread cursor by default; pass after_sequence to override it. wait_seconds specifies the maximum wait; return timed_out=true if no message arrives before it expires. Return messages[].agent_id/task_id/kind to distinguish progress from final messages; exclude events/tool calls.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "after_sequence": {"type": "integer"},
                    "wait_seconds": {"type": "number"},
                    "include_progress": {"type": "boolean"},
                    "include_final": {"type": "boolean"},
                    "message_limit": {"type": "integer"},
                },
            },
        },
    ]


def _content_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle_request(config_path: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    method = str(request.get("method") or "")
    request_id = request.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tcb-cluster", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tools_for_environment()}}
    if method == "tools/call":
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        name = str(params.get("name") or "")
        arguments = dict(params.get("arguments")) if isinstance(params.get("arguments"), dict) else {}
        try:
            run_id = str(arguments.pop("run_id", "") or "").strip()
            if not run_id:
                raise ValueError("run_id is required")
            config = load_mcp_bridge_config(config_path)
            result = post_mcp_tool(config, name, arguments, run_id=run_id)
        except Exception as exc:
            message = json.dumps(
                {"ok": False, "error": str(exc), "error_type": type(exc).__name__},
                ensure_ascii=False,
            )
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_error(message)}
        return {"jsonrpc": "2.0", "id": request_id, "result": _content_text(json.dumps(result, ensure_ascii=False))}
    if method == "notifications/initialized":
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    config_path = Path(args.config)
    if args.self_test:
        loaded = load_mcp_bridge_config(config_path)
        print(json.dumps({"ok": True, "bridge_url": loaded.bridge_url}, ensure_ascii=False))
        return 0
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        response = handle_request(config_path, json.loads(stripped))
        if response is not None:
            _write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
