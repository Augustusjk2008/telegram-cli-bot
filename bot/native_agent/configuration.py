from __future__ import annotations

from typing import Any

from bot import config
from bot.models import normalize_native_agent_config
from bot.native_agent.config_store import first_configured_model, find_configured_model, list_configured_models


def global_native_agent_config() -> dict[str, Any]:
    first_model = first_configured_model()
    resolved = normalize_native_agent_config({
        "native_agent_model": first_model.get("id") if first_model else "",
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
            provider = provider.strip()
            model = model_id.strip()
    if not resolved.get("native_agent_model") and provider and model:
        resolved["native_agent_model"] = f"{provider}/{model}"
    return resolved


def effective_native_agent_config(fallback: Any = None) -> dict[str, Any]:
    resolved = global_native_agent_config()
    fallback_config = normalize_native_agent_config(fallback)
    fallback_model = str(fallback_config.get("native_agent_model") or "").strip()
    if fallback_model:
        resolved["native_agent_model"] = fallback_model
        resolved["model"] = fallback_model
    elif not resolved.get("native_agent_model"):
        first_model = first_configured_model()
        if first_model:
            resolved["native_agent_model"] = first_model["id"]
            resolved["model"] = first_model["id"]
    if not resolved.get("opencode_agent"):
        fallback_agent = str(fallback_config.get("opencode_agent") or "").strip()
        if fallback_agent:
            resolved["opencode_agent"] = fallback_agent
    fallback_reasoning_effort = str(fallback_config.get("reasoning_effort") or "").strip()
    if fallback_reasoning_effort:
        resolved["reasoning_effort"] = fallback_reasoning_effort
    _normalize_reasoning_effort_for_selected_model(resolved)
    return {key: value for key, value in resolved.items() if value}


def validate_native_agent_model_config(native_agent: dict[str, Any]) -> None:
    selected_model = str(native_agent.get("native_agent_model") or "").strip()
    if selected_model and list_configured_models():
        if find_configured_model(selected_model) is None:
            raise RuntimeError(f"原生 agent 模型未在 OpenCode 配置中找到: {selected_model}")
        return
    provider = str(native_agent.get("provider") or "").strip()
    model = str(native_agent.get("model") or "").strip()
    base_url = str(native_agent.get("base_url") or "").strip()
    api_key = str(native_agent.get("api_key") or "").strip()
    if model and not provider and (base_url or api_key):
        raise RuntimeError(
            "原生 agent 全局配置缺少 NATIVE_AGENT_PROVIDER；请设置 provider，"
            "或把 NATIVE_AGENT_MODEL 写成 provider/model 格式"
        )


def _normalize_reasoning_effort_for_selected_model(native_agent: dict[str, Any]) -> None:
    selected_model = str(
        native_agent.get("native_agent_model")
        or native_agent.get("model")
        or ""
    ).strip()
    if not selected_model:
        return
    configured_model = find_configured_model(selected_model)
    if configured_model is None:
        return
    efforts = [
        str(item or "").strip()
        for item in configured_model.get("reasoning_efforts", [])
        if str(item or "").strip()
    ]
    if not efforts:
        return
    current_effort = str(native_agent.get("reasoning_effort") or "").strip()
    if current_effort in efforts:
        return
    default_effort = str(configured_model.get("default_reasoning_effort") or "").strip()
    native_agent["reasoning_effort"] = default_effort if default_effort in efforts else efforts[0]
