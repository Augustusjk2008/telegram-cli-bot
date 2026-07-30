from __future__ import annotations

import hashlib
import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .models import ProviderInfo

try:
    import tomllib
except ImportError:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]


_CONFIG_ASSIGNMENT_RE = re.compile(r"^\s*([^=]+?)\s*=")


def get_root_config_path(
    env: Mapping[str, str] | None = None,
    *,
    home_dir: Path | str | None = None,
) -> Path:
    """Locate only Codex's user-root ``config.toml``.

    Provider attribution intentionally does not imitate Codex's broader profile or
    project configuration precedence.
    """

    source = os.environ if env is None else env
    codex_home = str(source.get("CODEX_HOME") or "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / "config.toml"
    home = Path.home() if home_dir is None else Path(home_dir).expanduser()
    return home / ".codex" / "config.toml"


def normalize_base_url(value: object) -> str | None:
    """Return a non-sensitive, stable provider URL or ``None`` when unsafe."""

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in hostname)
    ):
        return None
    hostname = hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    authority = hostname if not include_port else f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    return f"{scheme}://{authority}{path}"


def stable_provider_key(base_url: str | None) -> str:
    if base_url is None:
        return "openai_official"
    digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()
    return f"base_url_sha256:{digest}"


def _unknown(resolution: str) -> ProviderInfo:
    return ProviderInfo(
        key="unknown",
        kind="unknown",
        base_url=None,
        resolution=resolution,
    )


def _official(resolution: str = "resolved") -> ProviderInfo:
    return ProviderInfo(
        key="openai_official",
        kind="openai_official",
        base_url=None,
        resolution=resolution,
    )


def _base_url_provider(base_url: str) -> ProviderInfo:
    return ProviderInfo(
        key=stable_provider_key(base_url),
        kind="base_url",
        base_url=base_url,
        resolution="resolved",
    )


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise ValueError("根 TOML 必须是对象")
    return value


def _config_value_affects_provider(value: str) -> bool:
    match = _CONFIG_ASSIGNMENT_RE.match(value)
    if match is None:
        return False
    raw_key = match.group(1).strip()
    try:
        parsed: Any = tomllib.loads(f"{raw_key} = 0")
    except tomllib.TOMLDecodeError:
        normalized = re.sub(r"[\s\"']+", "", raw_key).casefold()
        return normalized in {"model_provider", "openai_base_url", "model_providers"} or (
            normalized.startswith("model_providers.") and normalized.endswith(".base_url")
        )

    path: list[str] = []
    current = parsed
    while isinstance(current, Mapping) and len(current) == 1:
        segment, current = next(iter(current.items()))
        path.append(str(segment).casefold())
    if current != 0 or not path:
        return False
    if path in (["model_provider"], ["openai_base_url"]):
        return True
    return path[0] == "model_providers" and (len(path) <= 2 or path[-1] == "base_url")


def has_unsupported_provider_override(argv: Sequence[str] | str | None) -> bool:
    """Detect CLI flags that make root-config attribution unreliable."""

    if argv is None:
        return False
    arguments = shlex.split(argv) if isinstance(argv, str) else [str(item) for item in argv]
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--profile" or argument.startswith("--profile="):
            return True
        if argument == "-p" or (argument.startswith("-p") and not argument.startswith("--")):
            return True
        if argument == "--oss" or argument.startswith("--oss="):
            return True
        config_value: str | None = None
        if argument in {"-c", "--config"}:
            if index + 1 < len(arguments):
                index += 1
                config_value = arguments[index]
        elif argument.startswith("--config="):
            config_value = argument.split("=", 1)[1]
        elif argument.startswith("-c") and argument != "-c":
            config_value = argument[2:]
        if config_value is not None and _config_value_affects_provider(config_value):
            return True
        index += 1
    return False


class CodexProviderResolver:
    """Resolve a provider snapshot and cache unmodified root configuration files."""

    def __init__(self, *, home_dir: Path | str | None = None) -> None:
        self._home_dir = Path(home_dir).expanduser() if home_dir is not None else None
        self._cache: dict[Path, tuple[tuple[Path, int, int], ProviderInfo]] = {}

    def resolve(
        self,
        *,
        env: Mapping[str, str] | None = None,
        argv: Sequence[str] | str | None = None,
    ) -> ProviderInfo:
        if has_unsupported_provider_override(argv):
            return _unknown("unsupported_override")
        path = get_root_config_path(env, home_dir=self._home_dir).resolve()
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._cache.pop(path, None)
            return _official("config_missing")
        except OSError:
            self._cache.pop(path, None)
            return _unknown("config_invalid")
        cache_key = (path, stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(path)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        try:
            config = _load_toml(path)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            result = _unknown("config_invalid")
        else:
            result = self._resolve_config(config)
        self._cache[path] = (cache_key, result)
        return result

    @staticmethod
    def _resolve_config(config: Mapping[str, Any]) -> ProviderInfo:
        model_provider = config.get("model_provider", "openai")
        if not isinstance(model_provider, str):
            return _unknown("provider_missing")
        provider_id = model_provider.strip() or "openai"
        if provider_id == "openai":
            base_url = config.get("openai_base_url")
        else:
            providers = config.get("model_providers")
            if not isinstance(providers, Mapping):
                return _unknown("provider_missing")
            provider_config = providers.get(provider_id)
            if not isinstance(provider_config, Mapping):
                return _unknown("provider_missing")
            base_url = provider_config.get("base_url")
        if base_url is None or (isinstance(base_url, str) and not base_url.strip()):
            return _official() if provider_id == "openai" else _unknown("provider_missing")
        normalized = normalize_base_url(base_url)
        if normalized is None:
            return _unknown("invalid_base_url")
        return _base_url_provider(normalized)


def resolve_provider(
    *,
    env: Mapping[str, str] | None = None,
    argv: Sequence[str] | str | None = None,
) -> ProviderInfo:
    return CodexProviderResolver().resolve(env=env, argv=argv)


get_codex_config_path = get_root_config_path
provider_key_for_base_url = stable_provider_key
