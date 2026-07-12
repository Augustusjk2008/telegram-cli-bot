from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from bot.agents import normalize_agent_id, normalize_agent_name, normalize_agent_prompt
from bot.cluster.config import normalize_agent_cluster_config, normalize_bot_cluster_config
from bot.models import BotProfile

_DEFAULT_TEMPLATE_PATH = Path(__file__).with_name("templates.default.json")
_LOCAL_TEMPLATE_PATH = Path.cwd() / "cluster_templates.json"
_AGENT_ID_PATTERN_TEXT = "Agent ID 仅允许小写字母/数字/_/-，2-32 位，以小写字母开头，且不能为 main"


class ClusterBundleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_cluster_template_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    env_path = os.environ.get("TCB_CLUSTER_TEMPLATES_FILE", "").strip()
    if env_path:
        return Path(env_path)
    if _LOCAL_TEMPLATE_PATH.exists():
        return _LOCAL_TEMPLATE_PATH
    return _DEFAULT_TEMPLATE_PATH


def load_cluster_template_catalog(path: str | Path | None = None) -> dict[str, Any]:
    template_path = resolve_cluster_template_path(path)
    try:
        raw = json.loads(template_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClusterBundleError("cluster_template_file_not_found", f"集群模板配置不存在: {template_path}") from exc
    except json.JSONDecodeError as exc:
        raise ClusterBundleError("cluster_template_json_invalid", f"集群模板 JSON 无效: {exc.msg}") from exc
    return normalize_template_catalog(raw)


def normalize_template_catalog(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ClusterBundleError("cluster_template_catalog_invalid", "集群模板配置必须是对象")
    if raw.get("version") != 1:
        raise ClusterBundleError("cluster_template_version_invalid", "集群模板 version 必须为 1")
    templates = raw.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ClusterBundleError("cluster_template_list_empty", "集群模板 templates 必须是非空数组")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in templates:
        bundle = normalize_cluster_bundle(item)
        template_id = bundle["id"]
        if template_id in seen:
            raise ClusterBundleError("cluster_template_id_duplicate", f"集群模板 ID 重复: {template_id}")
        seen.add(template_id)
        normalized.append(bundle)
    return {"version": 1, "templates": normalized}


def list_cluster_templates(path: str | Path | None = None) -> list[dict[str, Any]]:
    catalog = load_cluster_template_catalog(path)
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "agent_count": len(item["agents"]),
            "write_agent_count": sum(1 for agent in item["agents"] if agent["cluster"]["allow_write"]),
            "max_parallel_agents": item["cluster"]["max_parallel_agents"],
        }
        for item in catalog["templates"]
    ]


def get_cluster_template(template_id: str, path: str | Path | None = None) -> dict[str, Any]:
    normalized_id = _normalize_template_id(template_id)
    catalog = load_cluster_template_catalog(path)
    for item in catalog["templates"]:
        if item["id"] == normalized_id:
            return copy.deepcopy(item)
    raise ClusterBundleError("cluster_template_not_found", f"集群模板不存在: {normalized_id}")


def normalize_cluster_bundle(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ClusterBundleError("cluster_bundle_invalid", "集群配置 bundle 必须是对象")
    bundle_id = _normalize_template_id(raw.get("id", raw.get("template_id", raw.get("templateId", "custom"))))
    name = str(raw.get("name") or "自定义集群").strip()
    description = str(raw.get("description") or "").strip()
    cluster = normalize_bot_cluster_config(raw.get("cluster")).to_dict()
    agents = _normalize_bundle_agents(raw.get("agents"))
    if any(agent["cluster"]["allow_write"] for agent in agents) and cluster["write_policy"] == "main_only":
        raise ClusterBundleError("cluster_bundle_write_policy_conflict", "存在可写 agent 时 write_policy 不能为 main_only")
    return {
        "id": bundle_id,
        "name": name[:64] or "自定义集群",
        "description": description[:240],
        "cluster": cluster,
        "agents": agents,
    }


def build_cluster_bundle_schema() -> dict[str, Any]:
    return {
        "version": 1,
        "schema": {
            "type": "object",
            "required": ["cluster", "agents"],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{1,31}$"},
                "name": {"type": "string", "minLength": 1, "maxLength": 64},
                "description": {"type": "string", "maxLength": 240},
                "cluster": {
                    "type": "object",
                    "required": ["enabled", "write_policy", "conflict_policy", "max_parallel_agents", "default_timeout_seconds", "model_tiers"],
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "write_policy": {"enum": ["main_only", "selected_agents", "all_agents"]},
                        "conflict_policy": {"enum": ["warn_only", "snapshot_diff", "block_same_file"]},
                        "max_parallel_agents": {"type": "integer", "minimum": 1, "maximum": 8},
                        "default_timeout_seconds": {"type": "integer", "minimum": 60, "maximum": 3600},
                        "model_tiers": {
                            "type": "object",
                            "properties": {
                                "low": {"type": "string"},
                                "medium": {"type": "string"},
                                "high": {"type": "string"}
                            }
                        },
                        "reasoning_efforts": {
                            "type": "object",
                            "properties": {
                                "low": {"type": "string"},
                                "medium": {"type": "string"},
                                "high": {"type": "string"}
                            }
                        }
                    }
                },
                "agents": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "required": ["id", "name", "system_prompt", "enabled", "cluster"]
                    }
                }
            }
        },
        "instructions": (
            "只输出 JSON bundle。默认所有 agent 只读。只有用户明确要求并行写代码时，才设置某个 agent 的 cluster.allow_write=true。"
            "不要创建 main agent。agent id 必须小写英文开头。system_prompt 必须说明职责、边界和输出格式。"
            "cluster.reasoning_efforts 可按 low/medium/high 设置思考深度；留空表示继承主 agent。"
        ),
    }


def build_cluster_bundle_diff(profile: BotProfile, bundle: dict[str, Any]) -> dict[str, Any]:
    current_agents = {agent.id: agent for agent in profile.agents if agent.id != "main"}
    next_agents = {agent["id"]: agent for agent in bundle["agents"]}
    delete_ids = sorted(set(current_agents) - set(next_agents))
    create_ids = sorted(set(next_agents) - set(current_agents))
    update_ids = sorted(
        agent_id for agent_id in set(current_agents) & set(next_agents)
        if current_agents[agent_id].to_dict() != next_agents[agent_id]
    )
    current_cluster = profile.cluster.to_dict()
    next_cluster = bundle["cluster"]
    cluster_changes = {
        key: {"before": current_cluster.get(key), "after": next_cluster.get(key)}
        for key in sorted(next_cluster)
        if current_cluster.get(key) != next_cluster.get(key)
    }
    return {
        "delete_agents": delete_ids,
        "create_agents": create_ids,
        "update_agents": update_ids,
        "cluster_changes": cluster_changes,
        "overwrites_agents": bool(delete_ids or create_ids or update_ids),
    }


def _normalize_template_id(value: Any) -> str:
    raw = str(value or "").strip().lower()
    try:
        normalized = normalize_agent_id(raw, allow_main=False)
    except ValueError as exc:
        raise ClusterBundleError("cluster_template_id_invalid", str(exc)) from exc
    if normalized == "main":
        raise ClusterBundleError("cluster_template_id_invalid", "集群模板 ID 不能为 main")
    return normalized


def _normalize_bundle_agents(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ClusterBundleError("cluster_bundle_agents_empty", "agents 必须是非空数组")
    if len(raw) > 8:
        raise ClusterBundleError("cluster_bundle_agents_too_many", "agents 最多 8 个")
    seen: set[str] = set()
    agents: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ClusterBundleError("cluster_bundle_agent_invalid", "agent 必须是对象")
        try:
            agent_id = normalize_agent_id(item.get("id"), allow_main=False)
        except ValueError as exc:
            raise ClusterBundleError("cluster_bundle_agent_id_invalid", _AGENT_ID_PATTERN_TEXT) from exc
        if agent_id == "main":
            raise ClusterBundleError("cluster_bundle_agent_id_invalid", _AGENT_ID_PATTERN_TEXT)
        if agent_id in seen:
            raise ClusterBundleError("cluster_bundle_agent_id_duplicate", f"agent id 重复: {agent_id}")
        seen.add(agent_id)
        try:
            name = normalize_agent_name(item.get("name"))
            system_prompt = normalize_agent_prompt(item.get("system_prompt", item.get("systemPrompt")))
        except ValueError as exc:
            raise ClusterBundleError("cluster_bundle_agent_invalid", str(exc)) from exc
        agents.append({
            "id": agent_id,
            "name": name,
            "system_prompt": system_prompt,
            "enabled": bool(item.get("enabled", True)),
            "cluster": normalize_agent_cluster_config(item.get("cluster")).to_dict(),
        })
    return agents
