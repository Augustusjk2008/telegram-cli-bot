from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.cluster.config import CLUSTER_CLI_TYPES, MODEL_TIER_KEYS
from bot.cluster.mcp_client import load_mcp_bridge_config, post_mcp_tool


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _tool_annotations(*, read_only: bool, idempotent: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": False,
        "openWorldHint": False,
        "idempotentHint": idempotent,
    }


def _tools_for_environment() -> list[dict[str, Any]]:
    tier_fields = {
        "run_id": {"type": "string"},
        "model_tier": {"type": "string", "enum": list(MODEL_TIER_KEYS)},
        "cli_type": {"type": "string", "enum": ["", *sorted(CLUSTER_CLI_TYPES)],
                     "description": "An empty string inherits the Bot CLI."},
    }
    return [
        {
            "name": "configure_team",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
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
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "description": "Inspect the current team, internal agent IDs for roles, capacity, free slots, and task occupancy. Always pass run_id.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        },
        {
            "name": "list_agents",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "description": "List the current team, internal agent IDs for roles, capacity, free slots, and task occupancy. Always pass run_id.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"include_disabled": {"type": "boolean"}, "run_id": {"type": "string"}},
            },
        },
        {
            "name": "get_agent_tiers",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "description": "Read the Bot's four child-agent tiers, their configured and effective settings, and revisions. Supply model_tier for executable availability, models and reasoning efforts. Add cli_type to preview switching that tier. Use the returned choices and revision for update_agent_tier.",
            "inputSchema": {
                "type": "object", "required": ["run_id"], "additionalProperties": False,
                "properties": tier_fields,
            },
        },
        {
            "name": "update_agent_tier",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "description": "As the main agent, persist a requested edit to one Bot-wide child tier. Read get_agent_tiers for the target CLI first. Supply its revision and the fields to change. Empty strings restore inheritance. Switching backends clears the old backend's overrides. Edits apply to future tasks. Use the professional tier only on explicit user request.",
            "inputSchema": {
                "type": "object", "additionalProperties": False,
                "required": ["run_id", "model_tier", "expected_revision"],
                "minProperties": 4,
                "properties": {
                    **tier_fields,
                    "expected_revision": {"type": "string", "minLength": 1},
                    "model": {"type": "string", "description": "A listed model ID, or an empty string to inherit."},
                    "reasoning_effort": {"type": "string", "description": "A listed effort for this model, or an empty string to inherit."},
                },
            },
        },
        {
            "name": "new_agent_session",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
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
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "description": "Queue a child task and return its task_id and execution settings. Pass run_id and choose a model_tier from get_agent_tiers (default medium). Use professional only on explicit user request. Poll for the result or let completion notify the main session. timeout_seconds is a soft deadline and defaults to the Bot setting.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "agent_id", "message"],
                "properties": {
                    "agent_id": {"type": "string"},
                    "message": {"type": "string"},
                    "model_tier": {"type": "string", "enum": list(MODEL_TIER_KEYS)},
                    "expected_revision": {"type": "string", "description": "Use the inspected tier revision to reject a change before enqueue."},
                    "timeout_seconds": {"type": "integer"},
                    "allow_write": {"type": "boolean"},
                    "run_id": {"type": "string"},
                },
            },
        },
        {
            "name": "cancel_agent_task",
            "annotations": _tool_annotations(read_only=False, idempotent=True),
            "description": "Cancel one queued or running child agent task by task_id without stopping other tasks in the current run. Always pass run_id. The cancellation terminates the child agent execution and returns its final cancelled status; canceling an already finished task is idempotent.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id", "task_id"],
                "properties": {
                    "run_id": {"type": "string", "description": "TCB cluster run id."},
                    "task_id": {"type": "string", "description": "The task_id returned by ask_agent."},
                    "message": {"type": "string", "description": "Optional cancellation reason shown in task status."},
                },
            },
        },
        {
            "name": "poll_agent_tasks",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
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
            "annotations": _tool_annotations(read_only=False, idempotent=False),
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
        content = _tool_error if result.get("ok") is False else _content_text
        return {"jsonrpc": "2.0", "id": request_id, "result": content(json.dumps(result, ensure_ascii=False))}
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
