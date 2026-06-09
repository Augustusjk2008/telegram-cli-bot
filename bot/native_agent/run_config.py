from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import bot.config as config
from bot.cluster.setup import CLUSTER_MCP_SERVER_NAME, prepare_cluster_mcp_launcher
from bot.models import build_native_agent_model_id, normalize_native_agent_config
from bot.native_agent.config_store import ensure_opencode_config
from bot.runtime_paths import get_app_data_root

_REPO_ROOT = Path(__file__).resolve().parents[2]


def cluster_bridge_url() -> str:
    return f"http://127.0.0.1:{int(config.WEB_PORT)}"


def cluster_mcp_launcher_signature() -> dict[str, str]:
    launcher_name = "tcb-cluster-mcp.cmd" if os.name == "nt" else "tcb-cluster-mcp.sh"
    return {
        "server_name": CLUSTER_MCP_SERVER_NAME,
        "launcher_path": str(Path.home() / ".tcb" / "bin" / launcher_name),
        "bridge_url": cluster_bridge_url(),
    }


def prepare_cluster_mcp_launcher_for_native() -> Path:
    launcher = prepare_cluster_mcp_launcher(
        home_dir=Path.home(),
        repo_root=_REPO_ROOT,
        bridge_url=cluster_bridge_url(),
    )
    return launcher.launcher_path


def runtime_config_key(*, working_dir: str, command: str, native_agent: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "command": str(command or "opencode"),
            "working_dir": _normalize_working_dir(working_dir),
            "native_agent": normalize_native_agent_config(native_agent),
            "cluster_mcp": cluster_mcp_launcher_signature(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def runtime_config_path(key: str) -> Path:
    return get_app_data_root() / "native-agent" / f"opencode-run-{str(key or 'default')}.json"


def write_runtime_opencode_config(*, key: str, native_agent: dict[str, Any]) -> Path:
    normalized_native_agent = normalize_native_agent_config(native_agent)
    base_path = ensure_opencode_config(normalized_native_agent)
    try:
        payload = json.loads(base_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base_path
    if not isinstance(payload, dict):
        return base_path

    runtime_payload = copy.deepcopy(payload)
    selected_model = build_native_agent_model_id(normalized_native_agent)
    if selected_model:
        runtime_payload["model"] = selected_model
        apply_model_options(runtime_payload, selected_model, model_options(normalized_native_agent))
    opencode_agent = str(normalized_native_agent.get("opencode_agent") or "").strip()
    if opencode_agent:
        runtime_payload["agent"] = opencode_agent

    launcher_path = prepare_cluster_mcp_launcher_for_native()
    mcp = runtime_payload.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
        runtime_payload["mcp"] = mcp
    mcp[CLUSTER_MCP_SERVER_NAME] = {
        "type": "local",
        "command": [str(launcher_path)],
        "enabled": True,
    }

    path = runtime_config_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runtime_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def apply_model_options(payload: dict[str, Any], model_id: str, options: dict[str, Any]) -> None:
    if not options or "/" not in model_id:
        return
    provider_id, model_name = model_id.split("/", 1)
    provider_map = payload.get("provider")
    if not isinstance(provider_map, dict):
        return
    provider_config = provider_map.get(provider_id)
    if not isinstance(provider_config, dict):
        return
    models = provider_config.get("models")
    if not isinstance(models, dict):
        return
    model_config = models.get(model_name)
    if not isinstance(model_config, dict):
        return
    model_options = model_config.get("options")
    if not isinstance(model_options, dict):
        model_options = {}
        model_config["options"] = model_options
    model_options.update(options)


def model_options(native_agent: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    reasoning_effort = str(native_agent.get("reasoning_effort") or "").strip()
    if reasoning_effort:
        options["reasoningEffort"] = reasoning_effort
    raw_thinking_depth = str(native_agent.get("thinking_depth") or "").strip()
    if raw_thinking_depth:
        try:
            thinking_depth = int(float(raw_thinking_depth))
        except (TypeError, ValueError):
            thinking_depth = 0
        if thinking_depth > 0:
            options["thinking"] = {
                "type": "enabled",
                "budgetTokens": thinking_depth,
            }
    return options


def _normalize_working_dir(working_dir: str) -> str:
    candidate = str(working_dir or config.WORKING_DIR or ".").strip() or "."
    return str(Path(candidate).expanduser().resolve())


_runtime_config_path = runtime_config_path
_write_opencode_config = write_runtime_opencode_config
_apply_model_options = apply_model_options
_model_options = model_options
