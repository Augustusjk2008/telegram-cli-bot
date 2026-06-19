from __future__ import annotations

from typing import Any

from bot import config
from bot.models import normalize_native_agent_config
from bot.native_agent.config_store import find_configured_model, first_configured_model, list_configured_models, load_native_agent_config


def global_native_agent_config() -> dict[str, Any]:
    settings = load_native_agent_config()
    configured_models = list_configured_models(settings)
    configured_model_ids = {
        str(item.get("id") or "").strip()
        for item in configured_models
        if str(item.get("id") or "").strip()
    }
    first_model_id = str((configured_models[0].get("id") if configured_models else "") or "").strip()
    settings_model = str(settings.get("model") or "").strip()
    settings_config = normalize_native_agent_config({
        "model": settings_model,
        "pi_agent": settings.get("pi_agent"),
        "pi_command": settings.get("pi_command"),
        "system_prompt": settings.get("system_prompt"),
        "workspace_history_enabled": settings.get("workspace_history_enabled", True),
        "reasoning_effort": settings.get("reasoning_effort"),
        "thinking_depth": settings.get("thinking_depth"),
    })
    env_config = normalize_native_agent_config({
        "provider": getattr(config, "NATIVE_AGENT_PROVIDER", ""),
        "model": getattr(config, "NATIVE_AGENT_MODEL", ""),
        "base_url": getattr(config, "NATIVE_AGENT_BASE_URL", ""),
        "api_key": getattr(config, "NATIVE_AGENT_API_KEY", ""),
        "pi_agent": getattr(config, "NATIVE_AGENT_PI_AGENT", ""),
        "pi_command": (
            getattr(config, "NATIVE_AGENT_PI_COMMAND", "")
            or getattr(config, "NATIVE_AGENT_COMMAND", "")
            or getattr(config, "NATIVE_AGENT_PATH", "")
        ),
        "workspace_history_enabled": getattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True),
        "reasoning_effort": getattr(config, "NATIVE_AGENT_REASONING_EFFORT", ""),
        "thinking_depth": getattr(config, "NATIVE_AGENT_THINKING_DEPTH", ""),
    })
    resolved = dict(settings_config)
    env_model = str(env_config.get("model") or "").strip()
    if configured_model_ids:
        if settings_model:
            resolved["model"] = settings_model
        elif env_model and env_model in configured_model_ids:
            resolved["model"] = env_model
        elif first_model_id:
            resolved["model"] = first_model_id
    elif env_model:
        resolved["model"] = env_model
    selected_provider = _provider_from_model(str(resolved.get("model") or ""))
    if selected_provider:
        resolved["provider"] = selected_provider
    for key, value in env_config.items():
        if key == "model":
            continue
        if key == "provider" and selected_provider and str(value or "").strip() != selected_provider:
            continue
        if value not in ("", None) and key not in resolved:
            resolved[key] = value
    return resolved


def effective_native_agent_config(fallback: Any = None) -> dict[str, Any]:
    resolved = global_native_agent_config()
    fallback_config = normalize_native_agent_config(fallback)
    fallback_model = str(fallback_config.get("model") or "").strip()
    if fallback_model:
        resolved["model"] = fallback_model
    elif not resolved.get("model"):
        first_model = first_configured_model()
        if first_model:
            resolved["model"] = first_model["id"]
    if not resolved.get("pi_agent"):
        fallback_agent = str(fallback_config.get("pi_agent") or "").strip()
        if fallback_agent:
            resolved["pi_agent"] = fallback_agent
    if not resolved.get("system_prompt"):
        fallback_system_prompt = str(fallback_config.get("system_prompt") or "").strip()
        if fallback_system_prompt:
            resolved["system_prompt"] = fallback_system_prompt
    fallback_reasoning_effort = str(fallback_config.get("reasoning_effort") or "").strip()
    if fallback_reasoning_effort:
        resolved["reasoning_effort"] = fallback_reasoning_effort
    _normalize_reasoning_effort_for_selected_model(resolved)
    return {key: value for key, value in resolved.items() if value}


def validate_native_agent_model_config(native_agent: dict[str, Any]) -> None:
    selected_model = str(native_agent.get("model") or "").strip()
    provider = str(native_agent.get("provider") or "").strip()
    model = str(native_agent.get("model") or "").strip()
    base_url = str(native_agent.get("base_url") or "").strip()
    api_key = str(native_agent.get("api_key") or "").strip()
    if model and not provider and (base_url or api_key):
        raise RuntimeError(
            "原生 agent 全局配置缺少 NATIVE_AGENT_PROVIDER；请设置 provider，"
            "或把 NATIVE_AGENT_MODEL 写成 provider/model 格式"
        )
    if selected_model and list_configured_models():
        if find_configured_model(selected_model) is None:
            raise RuntimeError(f"原生 agent 模型未在 Pi 配置中找到: {selected_model}")
        return


def _normalize_reasoning_effort_for_selected_model(native_agent: dict[str, Any]) -> None:
    selected_model = str(
        native_agent.get("model")
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


def _provider_from_model(model_id: str) -> str:
    if "/" not in model_id:
        return ""
    return model_id.split("/", 1)[0].strip().lower()
