from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bot.native_agent.legacy_migration import (
    LEGACY_NATIVE_AGENT_DOCUMENT_KEYS,
    migrate_native_agent_payload,
)


def get_pi_settings_path() -> Path:
    override = os.environ.get("PI_AGENT_SETTINGS")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".pi" / "agent" / "settings.json"


def get_pi_models_path() -> Path:
    override = os.environ.get("PI_AGENT_MODELS")
    if override:
        return Path(override).expanduser()
    settings_override = os.environ.get("PI_AGENT_SETTINGS")
    if settings_override:
        return Path(settings_override).expanduser().with_name("models.json")
    return get_pi_settings_path().with_name("models.json")


def load_native_agent_config() -> dict[str, Any]:
    settings_payload = _read_json_object(get_pi_settings_path(), "原生 Agent 配置", default=_default_config())
    models_payload = _read_json_object(get_pi_models_path(), "Pi models.json", default={})
    if not _has_pi_models(models_payload):
        migrated_models = _models_config_from_native(settings_payload)
        if _has_pi_models(migrated_models):
            models_payload = migrated_models
            _write_json(get_pi_models_path(), models_payload)
    return normalize_native_agent_config_document(_merge_settings_and_models(settings_payload, models_payload))


def save_native_agent_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_native_agent_config_document(config)
    settings_path = get_pi_settings_path()
    models_path = get_pi_models_path()
    existing_settings = _read_json_object(settings_path, "原生 Agent 配置", default={})
    settings_payload = _settings_document_from_config(normalized, existing=existing_settings)
    models_payload = _models_config_from_native(normalized)
    _write_json(settings_path, settings_payload)
    if _has_model_source(normalized) or _has_pi_models(models_payload):
        _write_json(models_path, models_payload)
    combined = normalize_native_agent_config_document(_merge_settings_and_models(settings_payload, models_payload))
    return {
        "config": combined,
        "backend": "pi",
        "config_path": str(settings_path),
        "models_path": str(models_path),
        "workspace_history_enabled": bool(combined.get("workspace_history_enabled", True)),
        "models": list_configured_models(combined),
        "selected_model": str(combined.get("model") or "").strip(),
        "selected_reasoning_effort": str(combined.get("reasoning_effort") or "").strip(),
        "needs_restart": True,
    }


def list_configured_models(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = normalize_native_agent_config_document(
        load_native_agent_config() if config is None else config,
        validate_limits=False,
    )
    providers = payload.get("providers")
    if isinstance(providers, dict):
        items = _list_models_from_pi_providers(providers)
        if items:
            return items
    direct_models = payload.get("models")
    if isinstance(direct_models, list):
        items: list[dict[str, Any]] = []
        for raw_item in direct_models:
            if not isinstance(raw_item, dict):
                continue
            item_id = str(raw_item.get("id") or "").strip()
            provider = str(raw_item.get("provider") or (item_id.split("/", 1)[0] if "/" in item_id else "")).strip()
            model = str(raw_item.get("model") or (item_id.split("/", 1)[1] if "/" in item_id else "")).strip()
            if not provider or not model:
                continue
            name = str(raw_item.get("name") or model).strip() or model
            model_key = item_id or f"{provider}/{model}"
            if isinstance(raw_item.get("variants"), dict):
                reasoning_efforts = _string_list(list(raw_item["variants"].keys()))
            else:
                reasoning_efforts = _string_list(
                    raw_item.get("reasoning_efforts", raw_item.get("reasoningEfforts"))
                )
            items.append(
                {
                    "id": model_key,
                    "provider": provider,
                    "model": model,
                    "name": name,
                    "label": str(raw_item.get("label") or f"{provider} / {name}"),
                    "context_window": _positive_int_or_none(
                        raw_item.get("context_window", raw_item.get("contextWindow"))
                    ),
                    "output_limit": _positive_int_or_none(
                        raw_item.get("output_limit", raw_item.get("outputLimit"))
                    ),
                    "reasoning_efforts": reasoning_efforts,
                    "default_reasoning_effort": str(
                        raw_item.get("default_reasoning_effort")
                        or raw_item.get("defaultReasoningEffort")
                        or ""
                    ).strip(),
                }
            )
        if items:
            return items
    provider_map = payload.get("provider")
    if not isinstance(provider_map, dict):
        return []
    items: list[dict[str, Any]] = []
    for provider_id, provider_config in provider_map.items():
        provider = str(provider_id or "").strip()
        if not provider or not isinstance(provider_config, dict):
            continue
        models = provider_config.get("models")
        if not isinstance(models, dict):
            continue
        for model_id, model_config in models.items():
            model = str(model_id or "").strip()
            if not model or not isinstance(model_config, dict):
                continue
            limit = model_config.get("limit") if isinstance(model_config.get("limit"), dict) else {}
            context = _positive_int_or_none(limit.get("context")) if isinstance(limit, dict) else None
            output = _positive_int_or_none(limit.get("output")) if isinstance(limit, dict) else None
            model_name = str(model_config.get("name") or model).strip() or model
            model_key = f"{provider}/{model}"
            reasoning_efforts, default_reasoning_effort = _model_reasoning_efforts(model_config)
            items.append(
                {
                    "id": model_key,
                    "provider": provider,
                    "model": model,
                    "name": model_name,
                    "label": f"{provider} / {model_name}",
                    "context_window": context,
                    "output_limit": output,
                    "reasoning_efforts": reasoning_efforts,
                    "default_reasoning_effort": default_reasoning_effort,
                }
            )
    return items


def find_configured_model(model_id: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    normalized = str(model_id or "").strip()
    if not normalized:
        return None
    for item in list_configured_models(config):
        if item.get("id") == normalized:
            return item
    return None


def first_configured_model(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    models = list_configured_models(config)
    return models[0] if models else None


def normalize_native_agent_config_document(
    config: dict[str, Any],
    *,
    validate_limits: bool = True,
) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("原生 Agent 配置必须是 JSON 对象")
    payload = migrate_native_agent_payload(config)
    payload["backend"] = "pi"
    if "selected_model" in payload and not payload.get("model"):
        payload["model"] = str(payload.get("selected_model") or "").strip()
    if "selectedModel" in payload and not payload.get("model"):
        payload["model"] = str(payload.get("selectedModel") or "").strip()
    if "piCommand" in payload and "pi_command" not in payload:
        payload["pi_command"] = str(payload.get("piCommand") or "").strip()
    if "systemPrompt" in payload and "system_prompt" not in payload:
        payload["system_prompt"] = str(payload.get("systemPrompt") or "").strip()
    if "workspaceHistoryEnabled" in payload and "workspace_history_enabled" not in payload:
        payload["workspace_history_enabled"] = bool(payload.get("workspaceHistoryEnabled"))
    payload.setdefault("workspace_history_enabled", True)
    for legacy_key in (
        "selected_model",
        "selectedModel",
        "piCommand",
        "systemPrompt",
        "workspaceHistoryEnabled",
        "backup_path",
        "backupPath",
        *LEGACY_NATIVE_AGENT_DOCUMENT_KEYS,
    ):
        payload.pop(legacy_key, None)
    pi_providers = payload.get("providers")
    if pi_providers is not None:
        if not isinstance(pi_providers, dict):
            raise ValueError("providers 必须是对象")
        for provider_id, provider_config in pi_providers.items():
            provider = str(provider_id or "").strip()
            if not provider:
                raise ValueError("providers 的 provider id 不能为空")
            if not isinstance(provider_config, dict):
                raise ValueError(f"providers.{provider} 必须是对象")
            _require_headers_object(provider_config.get("headers"), f"providers.{provider}.headers")
            models = provider_config.get("models")
            if models is None:
                continue
            if not isinstance(models, list):
                raise ValueError(f"providers.{provider}.models 必须是数组")
            for index, model_config in enumerate(models):
                if not isinstance(model_config, dict):
                    raise ValueError(f"providers.{provider}.models[{index}] 必须是对象")
                model = str(model_config.get("id") or "").strip()
                if not model:
                    raise ValueError(f"providers.{provider}.models[{index}].id 不能为空")
                if validate_limits:
                    for key, field in (("contextWindow", "contextWindow"), ("maxTokens", "maxTokens")):
                        if key in model_config and model_config.get(key) is not None:
                            _require_positive_int(model_config.get(key), f"providers.{provider}.models[{index}].{field}")
    providers = payload.get("provider")
    if providers is not None:
        if not isinstance(providers, dict):
            raise ValueError("provider 必须是对象")
        for provider_id, provider_config in providers.items():
            provider = str(provider_id or "").strip()
            if not provider:
                raise ValueError("provider id 不能为空")
            if not isinstance(provider_config, dict):
                raise ValueError(f"provider.{provider} 必须是对象")
            _require_headers_object(provider_config.get("headers"), f"provider.{provider}.headers")
            options = provider_config.get("options")
            if isinstance(options, dict):
                _require_headers_object(options.get("headers"), f"provider.{provider}.options.headers")
            models = provider_config.get("models")
            if models is None:
                continue
            if not isinstance(models, dict):
                raise ValueError(f"provider.{provider}.models 必须是对象")
            for model_id, model_config in models.items():
                model = str(model_id or "").strip()
                if not model:
                    raise ValueError(f"provider.{provider}.models 的 model id 不能为空")
                if not isinstance(model_config, dict):
                    raise ValueError(f"provider.{provider}.models.{model} 必须是对象")
                if "limit" not in model_config or model_config.get("limit") is None:
                    continue
                limit = model_config.get("limit")
                if not isinstance(limit, dict):
                    raise ValueError(f"provider.{provider}.models.{model}.limit 必须是对象")
                if validate_limits:
                    for key in ("context", "output"):
                        if key in limit and limit.get(key) is not None:
                            _require_positive_int(limit.get(key), f"provider.{provider}.models.{model}.limit.{key}")
    direct_models = payload.get("models")
    if isinstance(direct_models, list):
        for index, model_config in enumerate(direct_models):
            if isinstance(model_config, dict):
                _require_headers_object(model_config.get("headers"), f"models[{index}].headers")
    return payload


def _default_config() -> dict[str, Any]:
    return {
        "backend": "pi",
        "model": "",
        "reasoning_effort": "",
        "pi_agent": "",
        "pi_command": "pi",
        "system_prompt": "",
        "workspace_history_enabled": True,
        "models": [],
    }


def _read_json_object(path: Path, label: str, *, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(default)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}不是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return payload


def _merge_settings_and_models(settings: dict[str, Any], models_config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(settings)
    if _has_pi_models(models_config):
        merged["providers"] = dict(models_config.get("providers") or {})
    return merged


def _settings_document_from_config(config: dict[str, Any], *, existing: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in dict(existing or {}).items()
        if key not in {"provider", "providers", "models", "selected_model", "selectedModel"}
    }
    for key in (
        "backend",
        "model",
        "reasoning_effort",
        "pi_agent",
        "pi_command",
        "system_prompt",
        "workspace_history_enabled",
        "thinking_depth",
        "shellPath",
        "shell_path",
    ):
        if key in config:
            value = config.get(key)
            if value is not None:
                result[key] = value
    result["backend"] = "pi"
    result.setdefault("workspace_history_enabled", True)
    return result


def _has_model_source(config: dict[str, Any]) -> bool:
    return any(isinstance(config.get(key), expected) for key, expected in (
        ("providers", dict),
        ("provider", dict),
        ("models", list),
    ))


def _has_pi_models(config: dict[str, Any]) -> bool:
    providers = config.get("providers")
    return isinstance(providers, dict) and bool(providers)


def _models_config_from_native(config: dict[str, Any]) -> dict[str, Any]:
    providers = config.get("providers")
    if isinstance(providers, dict):
        return {"providers": _copy_pi_providers(providers)}
    legacy_providers = config.get("provider")
    if isinstance(legacy_providers, dict):
        return {"providers": _legacy_providers_to_pi(legacy_providers)}
    direct_models = config.get("models")
    if isinstance(direct_models, list):
        return {"providers": _direct_models_to_pi(direct_models)}
    return {"providers": {}}


def _copy_pi_providers(providers: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for provider_id, provider_config in providers.items():
        provider = str(provider_id or "").strip()
        if provider and isinstance(provider_config, dict):
            result[provider] = json.loads(json.dumps(provider_config, ensure_ascii=False))
    return result


def _legacy_providers_to_pi(providers: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for provider_id, provider_config in providers.items():
        provider = str(provider_id or "").strip()
        if not provider or not isinstance(provider_config, dict):
            continue
        options = provider_config.get("options") if isinstance(provider_config.get("options"), dict) else {}
        converted: dict[str, Any] = {}
        base_url = (
            provider_config.get("baseUrl")
            or provider_config.get("baseURL")
            or provider_config.get("base_url")
            or options.get("baseUrl")
            or options.get("baseURL")
            or options.get("base_url")
        )
        api_key = (
            provider_config.get("apiKey")
            or provider_config.get("api_key")
            or options.get("apiKey")
            or options.get("api_key")
        )
        api = provider_config.get("api") or options.get("api")
        headers = _provider_headers(provider_config, options)
        if base_url:
            converted["baseUrl"] = str(base_url).strip().rstrip("/")
        if api_key:
            converted["apiKey"] = str(api_key).strip()
        if api:
            converted["api"] = str(api).strip()
        elif converted.get("baseUrl") or converted.get("apiKey"):
            converted["api"] = "openai-completions"
        if headers is not None:
            converted["headers"] = headers
        models = provider_config.get("models")
        converted_models: list[dict[str, Any]] = []
        if isinstance(models, dict):
            for model_id, model_config in models.items():
                if isinstance(model_config, dict):
                    converted_models.append(_legacy_model_to_pi(str(model_id or "").strip(), model_config))
        if converted_models:
            converted["models"] = converted_models
        if converted:
            result[provider] = converted
    return result


def _direct_models_to_pi(models: list[Any]) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for raw_item in models:
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("id") or "").strip()
        provider = str(raw_item.get("provider") or (item_id.split("/", 1)[0] if "/" in item_id else "")).strip()
        model = str(raw_item.get("model") or (item_id.split("/", 1)[1] if "/" in item_id else "")).strip()
        if not provider or not model:
            continue
        provider_config = providers.setdefault(provider, {"models": []})
        provider_config["models"].append(_direct_model_to_pi(model, raw_item))
    return providers


def _provider_headers(provider_config: dict[str, Any], options: dict[str, Any]) -> dict[str, Any] | None:
    for source in (provider_config, options):
        headers = source.get("headers")
        if isinstance(headers, dict):
            return json.loads(json.dumps(headers, ensure_ascii=False))
    return None


def _legacy_model_to_pi(model_id: str, model_config: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"id": model_id}
    name = str(model_config.get("name") or "").strip()
    if name and name != model_id:
        item["name"] = name
    limit = model_config.get("limit") if isinstance(model_config.get("limit"), dict) else {}
    context = _positive_int_or_none(limit.get("context")) if isinstance(limit, dict) else None
    output = _positive_int_or_none(limit.get("output")) if isinstance(limit, dict) else None
    if context:
        item["contextWindow"] = context
    if output:
        item["maxTokens"] = output
    efforts, _default_effort = _model_reasoning_efforts(model_config)
    if efforts:
        item["reasoning"] = True
        item["thinkingLevelMap"] = _thinking_level_map(efforts)
    _copy_known_pi_model_fields(model_config, item)
    return item


def _direct_model_to_pi(model_id: str, model_config: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"id": model_id}
    name = str(model_config.get("name") or "").strip()
    if name and name != model_id:
        item["name"] = name
    context = _positive_int_or_none(model_config.get("contextWindow", model_config.get("context_window")))
    output = _positive_int_or_none(model_config.get("maxTokens", model_config.get("outputLimit", model_config.get("output_limit"))))
    if context:
        item["contextWindow"] = context
    if output:
        item["maxTokens"] = output
    efforts, _default_effort = _model_reasoning_efforts(model_config)
    if efforts:
        item["reasoning"] = True
        item["thinkingLevelMap"] = _thinking_level_map(efforts)
    _copy_known_pi_model_fields(model_config, item)
    return item


def _copy_known_pi_model_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in ("api", "reasoning", "input", "cost", "thinkingLevelMap", "compat", "headers"):
        if key in source and source.get(key) is not None:
            target[key] = source[key]


def _thinking_level_map(efforts: list[str]) -> dict[str, str | None]:
    allowed = ("off", "minimal", "low", "medium", "high", "xhigh")
    supported = {item for item in efforts if item in allowed}
    return {level: (level if level in supported else None) for level in allowed}


def _list_models_from_pi_providers(providers: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for provider_id, provider_config in providers.items():
        provider = str(provider_id or "").strip()
        if not provider or not isinstance(provider_config, dict):
            continue
        models = provider_config.get("models")
        if not isinstance(models, list):
            continue
        for model_config in models:
            if not isinstance(model_config, dict):
                continue
            model = str(model_config.get("id") or "").strip()
            if not model:
                continue
            name = str(model_config.get("name") or model).strip() or model
            context = _positive_int_or_none(model_config.get("contextWindow"))
            output = _positive_int_or_none(model_config.get("maxTokens"))
            reasoning_efforts, default_reasoning_effort = _model_reasoning_efforts(model_config)
            items.append(
                {
                    "id": f"{provider}/{model}",
                    "provider": provider,
                    "model": model,
                    "name": name,
                    "label": f"{provider} / {name}",
                    "context_window": context,
                    "output_limit": output,
                    "reasoning_efforts": reasoning_efforts,
                    "default_reasoning_effort": default_reasoning_effort,
                }
            )
    return items


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _model_reasoning_efforts(model_config: dict[str, Any]) -> tuple[list[str], str]:
    options = model_config.get("options") if isinstance(model_config.get("options"), dict) else {}
    thinking_level_map = model_config.get("thinkingLevelMap")
    if isinstance(thinking_level_map, dict):
        efforts = [
            str(key or "").strip()
            for key, value in thinking_level_map.items()
            if str(key or "").strip() and value is not None
        ]
        return efforts, ""
    efforts = _string_list(
        model_config.get(
            "reasoningEfforts",
            model_config.get("reasoning_efforts"),
        )
    )
    if not efforts:
        efforts = _string_list(
            options.get(
                "reasoningEfforts",
                options.get("reasoning_efforts"),
            )
        )
    if not efforts:
        variants = model_config.get("variants")
        if isinstance(variants, dict):
            efforts = _string_list(list(variants.keys()))
    default_effort = str(options.get("reasoningEffort") or "").strip() if isinstance(options, dict) else ""
    if default_effort and not efforts:
        efforts = [default_effort]
    return efforts, default_effort


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        return []
    result: list[str] = []
    for item in candidates:
        normalized = str(item or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _positive_int_or_none(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _require_positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是正整数") from exc
    if parsed <= 0:
        raise ValueError(f"{field} 必须是正整数")
    return parsed


def _require_headers_object(value: Any, field: str) -> None:
    if value is not None and not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
