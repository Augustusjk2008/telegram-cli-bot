from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class McpBridgeConfig:
    bridge_url: str
    token: str


def load_mcp_bridge_config(path: Path) -> McpBridgeConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    token_file = Path(str(data["token_file"]))
    return McpBridgeConfig(
        bridge_url=str(data["bridge_url"]).rstrip("/"),
        token=token_file.read_text(encoding="utf-8").strip(),
    )


def post_mcp_tool(config: McpBridgeConfig, tool_name: str, payload: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{config.bridge_url}/api/internal/cluster/mcp/tools/{tool_name}",
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
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": text, "status": exc.code}
