from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.remote_workspace.chat import MAX_RESPONSE_BYTES, remote_tools, validate_bridge_url, validate_tool_arguments


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_remote_tool(config_path: Path, tool: str, arguments: Any) -> Any:
    arguments = validate_tool_arguments(tool, arguments)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base_url = validate_bridge_url(config["bridge_url"])
    request = urllib.request.Request(
        f"{base_url}/api/remote/agent-tools",
        data=json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-TCB-Remote-Token": config["token"]},
        method="POST",
    )
    # Never retry mutations: a timeout may occur after the remote command ran.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=arguments.get("timeout_seconds", 60) + 15) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        message = f"Remote bridge HTTP {exc.code}"
        try:
            error = json.loads(exc.read(MAX_RESPONSE_BYTES + 1)).get("error", {})
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = f"{error.get('code', 'remote_error')}: {error['message']}"[:1800]
        except (ValueError, AttributeError, OSError):
            pass
        finally:
            exc.close()
        raise RuntimeError(f"{message}; operation was not retried") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError("Remote bridge unavailable; operation was not retried") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Remote bridge response exceeded the output limit")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(str(result.get("error", "Remote tool failed"))[:2000] if isinstance(result, dict) else "Invalid remote bridge response")
    return result.get("data")


def handle_request(config_path: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    if "id" not in request:
        return None
    method = request.get("method")
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if method == "initialize":
        response["result"] = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "tcb-remote", "version": "1.0.0"}}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": remote_tools()}
    elif method == "tools/call":
        try:
            params = request.get("params") or {}
            result = post_remote_tool(config_path, params.get("name"), params.get("arguments", {}))
            response["result"] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}]}
        except Exception as exc:
            response["result"] = {"content": [{"type": "text", "text": str(exc)[:2000]}], "isError": True}
    else:
        response["error"] = {"code": -32601, "message": "Unknown method"}
    return response


def main(argv: list[str] | None = None) -> int:
    # MCP JSON-RPC is UTF-8 regardless of the Windows host's locale or which
    # environment variables the launching CLI forwards to its MCP subprocesses.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Invalid request")
            response = handle_request(Path(args.config), request)
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON request"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
