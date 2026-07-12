from __future__ import annotations

import argparse
import json
import os
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
            "name": "cluster_status",
            "description": "查看当前 TCB 集群运行状态和可用子 agent。必须传 run_id。返回 agent session_policy/timeout_seconds。",
            "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}},
        },
        {
            "name": "list_agents",
            "description": "列出当前 TCB 集群可调用子 agent。必须传 run_id。返回 agent session_policy/timeout_seconds。",
            "inputSchema": {
                "type": "object",
                "properties": {"include_disabled": {"type": "boolean"}, "run_id": {"type": "string"}},
            },
        },
        {
            "name": "ask_agent",
            "description": "异步启动个 TCB 子 agent 任务并立即返回 task_id。必须传 run_id。主 agent 可继续调用 poll_agent_tasks 等待/汇总，也可先结束让任务后台运行。timeout_seconds 是软期限，未传时使用目标 agent 的 cluster.timeout_seconds，超时不强行中断子 agent；poll_agent_tasks 会返回 deadline_exceeded。model_tier 可选 low/medium/high，并使用该档配置的模型和思考深度；档位配置留空时继承主 agent。",
            "inputSchema": {
                "type": "object",
                "required": ["agent_id", "message"],
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
            "description": "轮询当前 TCB 集群子 agent 异步任务状态、过程消息和结果。必须传 run_id。task_ids 为空时返回当前 run 全部任务。wait_seconds 可选，用于本次工具调用内等待任务完成；默认 0 立即返回。include_messages 默认 true；messages[].kind 为 progress 或 final，且不包含事件/工具调用。",
            "inputSchema": {
                "type": "object",
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
            "description": "阻塞等待当前 TCB 集群任意子 agent 的下一条未读回告。必须传 run_id。默认使用服务端未读游标；可传 after_sequence 覆盖。wait_seconds 指定最长等待时间；到时间无回告返回 timed_out=true。返回 messages[].agent_id/task_id/kind，可区分 progress 和 final；不返回事件/工具调用。",
            "inputSchema": {
                "type": "object",
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
        run_id = str(arguments.pop("run_id", "") or os.environ.get("TCB_CLUSTER_RUN_ID", ""))
        try:
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
