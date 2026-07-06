"""Configuration store for AI inline completion."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bot.runtime_paths import get_inline_completion_config_path


DEFAULT_DENY_GLOBS = [
    ".env*",
    "managed_bots.json",
    "*.pem",
    "*.key",
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
]


class InlineCompletionConfigError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "invalid_inline_completion_config") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass
class InlineCompletionConfig:
    enabled: bool = False
    provider_type: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 96
    request_timeout_seconds: int = 8
    auto_trigger_enabled: bool = True
    auto_trigger_delay_ms: int = 700
    manual_trigger_enabled: bool = True
    max_prefix_chars: int = 16000
    max_suffix_chars: int = 4000
    max_related_files: int = 4
    max_related_file_bytes: int = 4096
    deny_globs: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_GLOBS))

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.model)

    def to_file_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        data = self.to_file_dict()
        data.pop("api_key", None)
        data["api_key_set"] = bool(self.api_key)
        data["configured"] = self.configured
        return data


class InlineCompletionConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_inline_completion_config_path()
        self.config = InlineCompletionConfig()
        self.load()
        self.apply_env_config()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            self._apply_update(data, preserve_empty_key=False)

    def apply_env_config(self) -> None:
        env_map: dict[str, tuple[str, Any]] = {
            "INLINE_COMPLETION_BASE_URL": ("base_url", str),
            "INLINE_COMPLETION_API_KEY": ("api_key", str),
            "INLINE_COMPLETION_MODEL": ("model", str),
            "INLINE_COMPLETION_TIMEOUT_SECONDS": ("request_timeout_seconds", int),
        }
        for env_key, (attr, caster) in env_map.items():
            if env_key not in os.environ:
                continue
            raw_value = os.environ[env_key]
            try:
                value = caster(raw_value)
            except (TypeError, ValueError) as exc:
                raise InlineCompletionConfigError(400, f"{env_key} 配置无效") from exc
            setattr(self.config, attr, value)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.config.to_file_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_public_config(self) -> dict[str, Any]:
        return self.config.to_public_dict()

    def update(self, data: dict[str, Any], *, save: bool = True) -> dict[str, Any]:
        self._apply_update(data, preserve_empty_key=True)
        if save:
            self.save()
        return self.get_public_config()

    def _apply_update(self, data: dict[str, Any], *, preserve_empty_key: bool) -> None:
        if "base_url" in data:
            base_url = str(data.get("base_url") or "").strip()
            if base_url:
                parsed = urlparse(base_url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise InlineCompletionConfigError(400, "Base URL 仅支持 http/https URL", code="invalid_inline_completion_base_url")
            self.config.base_url = base_url
        if data.get("clear_api_key") is True:
            self.config.api_key = ""
        elif "api_key" in data:
            api_key = data.get("api_key")
            if not preserve_empty_key or (api_key is not None and str(api_key) != ""):
                self.config.api_key = str(api_key or "")

        bool_fields = {"enabled", "auto_trigger_enabled", "manual_trigger_enabled"}
        int_fields = {
            "max_output_tokens": (1, 4096),
            "request_timeout_seconds": (1, 60),
            "auto_trigger_delay_ms": (100, 5000),
            "max_prefix_chars": (1000, 64000),
            "max_suffix_chars": (0, 32000),
            "max_related_files": (0, 20),
            "max_related_file_bytes": (256, 65536),
        }
        float_fields = {"temperature": (0.0, 2.0)}
        str_fields = {"provider_type", "model"}

        for field_name in bool_fields:
            if field_name in data:
                setattr(self.config, field_name, bool(data[field_name]))
        for field_name, (minimum, maximum) in int_fields.items():
            if field_name in data:
                value = self._coerce_int(data[field_name], field_name=field_name)
                setattr(self.config, field_name, min(maximum, max(minimum, value)))
        for field_name, (minimum, maximum) in float_fields.items():
            if field_name in data:
                value = self._coerce_float(data[field_name], field_name=field_name)
                setattr(self.config, field_name, min(maximum, max(minimum, value)))
        for field_name in str_fields:
            if field_name in data:
                setattr(self.config, field_name, str(data[field_name] or "").strip())
        if "deny_globs" in data:
            raw_globs = data.get("deny_globs")
            if not isinstance(raw_globs, list):
                raise InlineCompletionConfigError(400, "deny_globs 必须是数组", code="invalid_inline_completion_deny_globs")
            self.config.deny_globs = [str(item).strip() for item in raw_globs if str(item or "").strip()]

    @staticmethod
    def _coerce_int(value: Any, *, field_name: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise InlineCompletionConfigError(400, f"{field_name} 必须是整数") from exc

    @staticmethod
    def _coerce_float(value: Any, *, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise InlineCompletionConfigError(400, f"{field_name} 必须是数字") from exc
