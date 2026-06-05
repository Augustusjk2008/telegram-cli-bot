from __future__ import annotations

from typing import Any

from bot import config
from bot.models import normalize_native_agent_config


def global_native_agent_config() -> dict[str, Any]:
    resolved = normalize_native_agent_config({
        "provider": getattr(config, "NATIVE_AGENT_PROVIDER", ""),
        "model": getattr(config, "NATIVE_AGENT_MODEL", ""),
        "base_url": getattr(config, "NATIVE_AGENT_BASE_URL", ""),
        "api_key": getattr(config, "NATIVE_AGENT_API_KEY", ""),
        "opencode_agent": getattr(config, "NATIVE_AGENT_OPENCODE_AGENT", ""),
        "reasoning_effort": getattr(config, "NATIVE_AGENT_REASONING_EFFORT", ""),
        "thinking_depth": getattr(config, "NATIVE_AGENT_THINKING_DEPTH", ""),
    })
    provider = str(resolved.get("provider") or "").strip()
    model = str(resolved.get("model") or "").strip()
    if not provider and "/" in model:
        provider, model_id = model.split("/", 1)
        if provider.strip() and model_id.strip():
            resolved["provider"] = provider.strip()
            resolved["model"] = model_id.strip()
    return resolved


def effective_native_agent_config(fallback: Any = None) -> dict[str, Any]:
    resolved = global_native_agent_config()
    if not resolved.get("opencode_agent"):
        fallback_config = normalize_native_agent_config(fallback)
        fallback_agent = str(fallback_config.get("opencode_agent") or "").strip()
        if fallback_agent:
            resolved["opencode_agent"] = fallback_agent
    return {key: value for key, value in resolved.items() if value}


def validate_native_agent_model_config(native_agent: dict[str, Any]) -> None:
    provider = str(native_agent.get("provider") or "").strip()
    model = str(native_agent.get("model") or "").strip()
    base_url = str(native_agent.get("base_url") or "").strip()
    api_key = str(native_agent.get("api_key") or "").strip()
    if model and not provider and (base_url or api_key):
        raise RuntimeError(
            "原生 agent 全局配置缺少 NATIVE_AGENT_PROVIDER；请设置 provider，"
            "或把 NATIVE_AGENT_MODEL 写成 provider/model 格式"
        )
