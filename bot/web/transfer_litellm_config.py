"""LiteLLM transfer gateway config helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

DEFAULT_CONVERSION_TYPE = "model_api"
CONVERSION_TYPES = {"model", "api", DEFAULT_CONVERSION_TYPE}
DEFAULT_UPSTREAM_API = "responses"
UPSTREAM_APIS = {DEFAULT_UPSTREAM_API, "chat_completions"}


@dataclass
class LiteLLMRouteConfig:
    id: str = ""
    name: str = ""
    conversion_type: str = DEFAULT_CONVERSION_TYPE
    upstream_api: str = DEFAULT_UPSTREAM_API
    litellm_model: str = ""
    model_alias: str = ""
    provider_base_url: str = ""
    provider_api_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.litellm_model and self.model_alias and self.provider_api_key)

    def to_file_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "conversion_type": self.conversion_type,
            "upstream_api": self.upstream_api,
            "litellm_model": self.litellm_model,
            "model_alias": self.model_alias,
            "provider_base_url": self.provider_base_url,
            "provider_api_key": self.provider_api_key,
        }

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "conversion_type": self.conversion_type,
            "upstream_api": self.upstream_api,
            "litellm_model": self.litellm_model,
            "model_alias": self.model_alias,
            "provider_base_url": self.provider_base_url,
            "provider_api_key_set": bool(self.provider_api_key),
            "configured": self.configured,
        }


@dataclass
class LiteLLMTransferConfig:
    litellm_model: str = ""
    model_alias: str = ""
    provider_base_url: str = ""
    provider_api_key: str = ""
    conversion_type: str = DEFAULT_CONVERSION_TYPE
    drop_params: bool = True
    routes: list[LiteLLMRouteConfig] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return bool(self.configured_routes())

    def effective_routes(self) -> list[LiteLLMRouteConfig]:
        if self.routes:
            return list(self.routes)
        route = self._legacy_route()
        return [route] if _route_has_content(route) else []

    def configured_routes(self) -> list[LiteLLMRouteConfig]:
        return [route for route in self.effective_routes() if route.configured]

    def to_file_dict(self) -> dict[str, Any]:
        return {
            "routes": [route.to_file_dict() for route in self.effective_routes()],
            "drop_params": self.drop_params,
        }

    def runtime_fingerprint(self) -> str:
        return json.dumps(self.to_file_dict(), ensure_ascii=False, sort_keys=True)

    def sync_legacy_fields(self) -> None:
        first = self.effective_routes()[0] if self.effective_routes() else LiteLLMRouteConfig()
        self.litellm_model = first.litellm_model
        self.model_alias = first.model_alias
        self.provider_base_url = first.provider_base_url
        self.provider_api_key = first.provider_api_key
        self.conversion_type = first.conversion_type or DEFAULT_CONVERSION_TYPE

    def _legacy_route(self) -> LiteLLMRouteConfig:
        return LiteLLMRouteConfig(
            id="route-1",
            conversion_type=normalize_conversion_type(self.conversion_type),
            upstream_api=DEFAULT_UPSTREAM_API,
            litellm_model=self.litellm_model,
            model_alias=self.model_alias,
            provider_base_url=self.provider_base_url,
            provider_api_key=self.provider_api_key,
        )


def default_model_alias(litellm_model: str) -> str:
    model = str(litellm_model or "").strip()
    if "/" in model:
        tail = model.rsplit("/", 1)[-1].strip()
        if tail:
            return tail
    return model


def normalize_conversion_type(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in CONVERSION_TYPES else DEFAULT_CONVERSION_TYPE


def normalize_upstream_api(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace("/", "_")
    return text if text in UPSTREAM_APIS else DEFAULT_UPSTREAM_API


def validate_optional_http_url(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} 仅支持 http/https URL")
    return text


def _route_has_content(route: LiteLLMRouteConfig) -> bool:
    return any(
        bool(value)
        for value in (
            route.name,
            route.litellm_model,
            route.model_alias,
            route.provider_base_url,
            route.provider_api_key,
        )
    )


def _route_id(value: object, index: int) -> str:
    text = str(value or "").strip()
    return text or f"route-{index + 1}"


def _first_route(config: LiteLLMTransferConfig) -> LiteLLMRouteConfig:
    routes = config.effective_routes()
    return routes[0] if routes else LiteLLMRouteConfig(id="route-1")


def _find_existing_route(
    existing_routes: list[LiteLLMRouteConfig],
    route_id: str,
    index: int,
) -> LiteLLMRouteConfig | None:
    if route_id:
        for route in existing_routes:
            if route.id == route_id:
                return route
    if index < len(existing_routes):
        return existing_routes[index]
    return None


def _route_from_data(
    data: dict[str, Any],
    *,
    existing: LiteLLMRouteConfig | None = None,
    index: int = 0,
) -> LiteLLMRouteConfig:
    existing = existing or LiteLLMRouteConfig()
    provider_base_url = existing.provider_base_url
    if "provider_base_url" in data:
        provider_base_url = validate_optional_http_url(data.get("provider_base_url"), field_name="provider_base_url")
    elif "remote_base_url" in data:
        provider_base_url = validate_optional_http_url(data.get("remote_base_url"), field_name="provider_base_url")

    provider_api_key = existing.provider_api_key
    if data.get("clear_provider_api_key") is True or data.get("clear_remote_api_key") is True:
        provider_api_key = ""
    elif "provider_api_key" in data:
        next_key = data.get("provider_api_key")
        if next_key is not None and str(next_key) != "":
            provider_api_key = str(next_key)
    elif "remote_api_key" in data:
        next_key = data.get("remote_api_key")
        if next_key is not None and str(next_key) != "":
            provider_api_key = str(next_key)

    litellm_model = existing.litellm_model
    if "litellm_model" in data:
        litellm_model = str(data.get("litellm_model") or "").strip()
    elif "remote_model" in data:
        litellm_model = str(data.get("remote_model") or "").strip()

    model_alias = existing.model_alias
    if "model_alias" in data:
        model_alias = str(data.get("model_alias") or "").strip()
    elif "remote_model" in data:
        model_alias = str(data.get("remote_model") or "").strip()
    if not model_alias and litellm_model:
        model_alias = default_model_alias(litellm_model)

    return LiteLLMRouteConfig(
        id=_route_id(data.get("id", data.get("route_id", existing.id)), index),
        name=str(data.get("name", existing.name) or "").strip(),
        conversion_type=normalize_conversion_type(data.get("conversion_type", existing.conversion_type)),
        upstream_api=normalize_upstream_api(data.get("upstream_api", existing.upstream_api)),
        litellm_model=litellm_model,
        model_alias=model_alias,
        provider_base_url=provider_base_url,
        provider_api_key=provider_api_key,
    )


def _validate_routes(routes: list[LiteLLMRouteConfig]) -> None:
    aliases: set[str] = set()
    for route in routes:
        alias = route.model_alias.strip()
        if not alias:
            continue
        if alias in aliases:
            raise ValueError(f"model_alias 重复: {alias}")
        aliases.add(alias)


def update_litellm_transfer_config(config: LiteLLMTransferConfig, data: dict[str, Any]) -> None:
    if "routes" in data:
        raw_routes = data.get("routes")
        if not isinstance(raw_routes, list):
            raise ValueError("routes 必须是数组")
        existing_routes = config.effective_routes()
        routes: list[LiteLLMRouteConfig] = []
        for index, raw_route in enumerate(raw_routes):
            if not isinstance(raw_route, dict):
                raise ValueError("routes 中的每一项都必须是对象")
            route_id = _route_id(raw_route.get("id", raw_route.get("route_id", "")), index)
            existing = _find_existing_route(existing_routes, route_id, index)
            route = _route_from_data(raw_route, existing=existing, index=index)
            if _route_has_content(route):
                routes.append(route)
        _validate_routes(routes)
        config.routes = routes
    else:
        route = _route_from_data(data, existing=_first_route(config), index=0)
        config.routes = [route] if _route_has_content(route) else []
        _validate_routes(config.routes)
    if "drop_params" in data:
        config.drop_params = bool(data.get("drop_params"))
    config.sync_legacy_fields()


def load_litellm_transfer_config(path: Path) -> LiteLLMTransferConfig:
    config = LiteLLMTransferConfig()
    if not path.exists():
        return config
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        update_litellm_transfer_config(config, data)
    return config


def build_litellm_proxy_config(config: LiteLLMTransferConfig, master_key: str) -> dict[str, Any]:
    model_list: list[dict[str, Any]] = []
    for route in config.configured_routes():
        litellm_params: dict[str, Any] = {
            "model": route.litellm_model,
            "api_key": route.provider_api_key,
        }
        if route.provider_base_url:
            litellm_params["api_base"] = route.provider_base_url
        model_list.append(
            {
                "model_name": route.model_alias,
                "litellm_params": litellm_params,
            }
        )
    return {
        "model_list": model_list,
        "litellm_settings": {
            "drop_params": bool(config.drop_params),
        },
        "general_settings": {
            "master_key": master_key,
        },
    }


def write_litellm_proxy_config(path: Path, config: LiteLLMTransferConfig, master_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            build_litellm_proxy_config(config, master_key),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
