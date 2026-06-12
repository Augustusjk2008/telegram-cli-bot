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


def load_native_agent_config() -> dict[str, Any]:
    source_path = get_pi_settings_path()
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _default_config()
    except json.JSONDecodeError as exc:
        raise ValueError(f"原生 Agent 配置不是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("原生 Agent 配置必须是 JSON 对象")
    return normalize_native_agent_config_document(payload)


def save_native_agent_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_native_agent_config_document(config)
    settings_path = get_pi_settings_path()
    _write_json(settings_path, normalized)
    return {
        "config": normalized,
        "backend": "pi",
        "config_path": str(settings_path),
        "workspace_history_enabled": bool(normalized.get("workspace_history_enabled", True)),
        "models": list_configured_models(normalized),
        "selected_model": str(normalized.get("model") or "").strip(),
        "selected_reasoning_effort": str(normalized.get("reasoning_effort") or "").strip(),
        "needs_restart": True,
    }


def list_configured_models(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = normalize_native_agent_config_document(
        load_native_agent_config() if config is None else config,
        validate_limits=False,
    )
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
    if "workspaceHistoryEnabled" in payload and "workspace_history_enabled" not in payload:
        payload["workspace_history_enabled"] = bool(payload.get("workspaceHistoryEnabled"))
    payload.setdefault("workspace_history_enabled", True)
    for legacy_key in (
        "selected_model",
        "selectedModel",
        "piCommand",
        "workspaceHistoryEnabled",
        "backup_path",
        "backupPath",
        *LEGACY_NATIVE_AGENT_DOCUMENT_KEYS,
    ):
        payload.pop(legacy_key, None)
    providers = payload.get("provider")
    if providers is None:
        return payload
    if not isinstance(providers, dict):
        raise ValueError("provider 必须是对象")
    for provider_id, provider_config in providers.items():
        provider = str(provider_id or "").strip()
        if not provider:
            raise ValueError("provider id 不能为空")
        if not isinstance(provider_config, dict):
            raise ValueError(f"provider.{provider} 必须是对象")
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
    return payload


def _default_config() -> dict[str, Any]:
    return {
        "backend": "pi",
        "model": "",
        "reasoning_effort": "",
        "pi_agent": "",
        "pi_command": "pi",
        "workspace_history_enabled": True,
        "models": [],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _model_reasoning_efforts(model_config: dict[str, Any]) -> tuple[list[str], str]:
    options = model_config.get("options") if isinstance(model_config.get("options"), dict) else {}
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
