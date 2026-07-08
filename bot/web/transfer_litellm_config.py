"""LiteLLM transfer gateway config helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass
class LiteLLMTransferConfig:
    litellm_model: str = ""
    model_alias: str = ""
    provider_base_url: str = ""
    provider_api_key: str = ""
    drop_params: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.litellm_model and self.model_alias and self.provider_api_key)

    def to_file_dict(self) -> dict[str, Any]:
        return {
            "litellm_model": self.litellm_model,
            "model_alias": self.model_alias,
            "provider_base_url": self.provider_base_url,
            "provider_api_key": self.provider_api_key,
            "drop_params": self.drop_params,
        }

    def runtime_fingerprint(self) -> str:
        return json.dumps(self.to_file_dict(), ensure_ascii=False, sort_keys=True)


def default_model_alias(litellm_model: str) -> str:
    model = str(litellm_model or "").strip()
    if "/" in model:
        tail = model.rsplit("/", 1)[-1].strip()
        if tail:
            return tail
    return model


def validate_optional_http_url(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} 仅支持 http/https URL")
    return text


def update_litellm_transfer_config(config: LiteLLMTransferConfig, data: dict[str, Any]) -> None:
    if "provider_base_url" in data:
        config.provider_base_url = validate_optional_http_url(data.get("provider_base_url"), field_name="provider_base_url")
    elif "remote_base_url" in data:
        config.provider_base_url = validate_optional_http_url(data.get("remote_base_url"), field_name="provider_base_url")

    if data.get("clear_provider_api_key") is True or data.get("clear_remote_api_key") is True:
        config.provider_api_key = ""
    elif "provider_api_key" in data:
        provider_api_key = data.get("provider_api_key")
        if provider_api_key is not None and str(provider_api_key) != "":
            config.provider_api_key = str(provider_api_key)
    elif "remote_api_key" in data:
        remote_api_key = data.get("remote_api_key")
        if remote_api_key is not None and str(remote_api_key) != "":
            config.provider_api_key = str(remote_api_key)

    if "litellm_model" in data:
        config.litellm_model = str(data.get("litellm_model") or "").strip()
    elif "remote_model" in data:
        config.litellm_model = str(data.get("remote_model") or "").strip()

    if "model_alias" in data:
        config.model_alias = str(data.get("model_alias") or "").strip()
    elif "remote_model" in data:
        config.model_alias = str(data.get("remote_model") or "").strip()

    if not config.model_alias and config.litellm_model:
        config.model_alias = default_model_alias(config.litellm_model)

    if "drop_params" in data:
        config.drop_params = bool(data.get("drop_params"))


def load_litellm_transfer_config(path: Path) -> LiteLLMTransferConfig:
    config = LiteLLMTransferConfig()
    if not path.exists():
        return config
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        update_litellm_transfer_config(config, data)
    return config


def build_litellm_proxy_config(config: LiteLLMTransferConfig, master_key: str) -> dict[str, Any]:
    litellm_params: dict[str, Any] = {
        "model": config.litellm_model,
        "api_key": config.provider_api_key,
    }
    if config.provider_base_url:
        litellm_params["api_base"] = config.provider_base_url
    return {
        "model_list": [
            {
                "model_name": config.model_alias,
                "litellm_params": litellm_params,
            }
        ],
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
