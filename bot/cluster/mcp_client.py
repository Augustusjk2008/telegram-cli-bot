from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class McpBridgeConfig:
    bridge_url: str
    token: str


_TRANSIENT_HTTP_STATUSES = {502, 503, 504}
_MAX_TRANSIENT_HTTP_ATTEMPTS = 3
_TRANSIENT_RETRY_DELAY_SECONDS = 0.2


def load_mcp_bridge_config(path: Path) -> McpBridgeConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    token_file = Path(str(data["token_file"]))
    return McpBridgeConfig(
        bridge_url=str(data["bridge_url"]).rstrip("/"),
        token=token_file.read_text(encoding="utf-8").strip(),
    )


def _http_error_result(exc: urllib.error.HTTPError, *, tool_name: str) -> dict[str, Any]:
    text = exc.read().decode("utf-8", errors="replace")
    error = text.strip()
    if not error:
        error = f"HTTP {exc.code} from TCB cluster bridge while calling {tool_name}: empty response body"
    return {"ok": False, "error": error, "status": exc.code}


def post_mcp_tool(config: McpBridgeConfig, tool_name: str, payload: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{config.bridge_url}/api/internal/cluster/mcp/tools/{tool_name}"
    for attempt in range(1, _MAX_TRANSIENT_HTTP_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Content-Type": "application/json",
                "X-TCB-Cluster-Run-Id": run_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in _TRANSIENT_HTTP_STATUSES and attempt < _MAX_TRANSIENT_HTTP_ATTEMPTS:
                time.sleep(_TRANSIENT_RETRY_DELAY_SECONDS * attempt)
                continue
            return _http_error_result(exc, tool_name=tool_name)
    return {
        "ok": False,
        "error": f"TCB cluster bridge request failed while calling {tool_name}: retry attempts exhausted",
        "status": 0,
    }
