"""固定语言服务器清单的加载与平台资产选择。"""

from __future__ import annotations

import json
import platform
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROVIDER_IDS = ("pyright", "typescript", "clangd")
_PROVIDER_ENV = {
    "pyright": "TCB_LSP_PYRIGHT_COMMAND",
    "typescript": "TCB_LSP_TYPESCRIPT_COMMAND",
    "clangd": "TCB_LSP_CLANGD_COMMAND",
}
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PINNED_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.-]+)?$")
_DYNAMIC_RELEASE_RE = re.compile(r"(?<![a-z0-9])latest(?![a-z0-9])", re.IGNORECASE)


class LanguageServerManifestError(ValueError):
    """语言服务器清单不满足固定安装安全约束。"""


@dataclass(frozen=True)
class LanguageServerAsset:
    asset_id: str
    version: str
    platform: str
    url: str
    sha256: str
    archive: str
    archive_root: str
    target: str
    entrypoint: str = ""


@dataclass(frozen=True)
class LanguageServerProvider:
    provider_id: str
    display_name: str
    version: str
    runtime: str
    environment_variable: str
    path_commands: tuple[str, ...]
    managed_entrypoint: str
    managed_args: tuple[str, ...]
    extensions: tuple[str, ...]
    license_spdx: str
    license_url: str
    assets: tuple[LanguageServerAsset, ...]

    def select_assets(self, platform_key: str) -> tuple[LanguageServerAsset, ...]:
        """返回当前平台完整的一组资产；不返回部分资产。"""

        normalized_platform = normalize_platform_key(platform_key)
        by_id: dict[str, list[LanguageServerAsset]] = defaultdict(list)
        for asset in self.assets:
            by_id[asset.asset_id].append(asset)

        selected: list[LanguageServerAsset] = []
        for asset_id in sorted(by_id):
            candidates = by_id[asset_id]
            exact = [asset for asset in candidates if asset.platform == normalized_platform]
            generic = [asset for asset in candidates if asset.platform == "any"]
            if len(exact) > 1 or len(generic) > 1:
                raise LanguageServerManifestError(f"{self.provider_id} 存在重复资产: {asset_id}")
            if exact:
                selected.append(exact[0])
            elif generic:
                selected.append(generic[0])
            else:
                return ()
        return tuple(selected)

    def entrypoint_for(self, platform_key: str) -> str:
        if self.runtime == "node":
            return self.managed_entrypoint
        assets = self.select_assets(platform_key)
        if len(assets) != 1:
            return ""
        return assets[0].entrypoint


@dataclass(frozen=True)
class LanguageServerManifest:
    schema_version: int
    providers: dict[str, LanguageServerProvider]

    def get(self, provider_id: str) -> LanguageServerProvider:
        normalized = str(provider_id or "").strip().lower()
        try:
            return self.providers[normalized]
        except KeyError as exc:
            raise LanguageServerManifestError(f"不支持的语言服务器: {provider_id}") from exc


def normalize_platform_key(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "win32-x64": "windows-x64",
        "win32-amd64": "windows-x64",
        "windows-amd64": "windows-x64",
        "win32-arm64": "windows-arm64",
        "macos-x64": "darwin-x64",
        "macos-arm64": "darwin-arm64",
        "osx-x64": "darwin-x64",
        "osx-arm64": "darwin-arm64",
        "linux-amd64": "linux-x64",
    }
    return aliases.get(normalized, normalized)


def current_platform_key() -> str:
    system = sys.platform.lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        architecture = "x64"
    elif machine in {"aarch64", "arm64"}:
        architecture = "arm64"
    else:
        architecture = machine or "unknown"
    if system.startswith("win"):
        return f"windows-{architecture}"
    if system.startswith("darwin"):
        return f"darwin-{architecture}"
    if system.startswith("linux"):
        return f"linux-{architecture}"
    return f"{system}-{architecture}"


def load_language_server_manifest(path: Path | str) -> LanguageServerManifest:
    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageServerManifestError(f"无法读取语言服务器清单: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise LanguageServerManifestError("语言服务器清单必须是 JSON 对象")

    schema_version = _expect_int(raw.get("schemaVersion"), "schemaVersion")
    if schema_version != 1:
        raise LanguageServerManifestError(f"不支持的语言服务器清单版本: {schema_version}")
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict):
        raise LanguageServerManifestError("providers 必须是对象")
    if set(providers_raw) != set(PROVIDER_IDS):
        raise LanguageServerManifestError("providers 必须且只能包含 pyright、typescript、clangd")

    providers: dict[str, LanguageServerProvider] = {}
    for provider_id in PROVIDER_IDS:
        providers[provider_id] = _parse_provider(provider_id, providers_raw[provider_id])
    return LanguageServerManifest(schema_version=schema_version, providers=providers)


def _parse_provider(provider_id: str, raw: Any) -> LanguageServerProvider:
    if not isinstance(raw, dict):
        raise LanguageServerManifestError(f"providers.{provider_id} 必须是对象")
    runtime = _expect_choice(raw.get("runtime"), f"providers.{provider_id}.runtime", {"node", "native"})
    environment_variable = _expect_text(raw.get("environmentVariable"), f"providers.{provider_id}.environmentVariable")
    if environment_variable != _PROVIDER_ENV[provider_id]:
        raise LanguageServerManifestError(f"{provider_id} 的环境变量必须是 {_PROVIDER_ENV[provider_id]}")
    path_commands = _expect_text_list(raw.get("pathCommands"), f"providers.{provider_id}.pathCommands")
    extensions = _expect_text_list(raw.get("extensions"), f"providers.{provider_id}.extensions")
    license_raw = raw.get("license")
    if not isinstance(license_raw, dict):
        raise LanguageServerManifestError(f"providers.{provider_id}.license 必须是对象")
    license_spdx = _expect_text(license_raw.get("spdx"), f"providers.{provider_id}.license.spdx")
    license_url = _expect_https_url(license_raw.get("url"), f"providers.{provider_id}.license.url")

    managed_raw = raw.get("managedCommand")
    if not isinstance(managed_raw, dict):
        raise LanguageServerManifestError(f"providers.{provider_id}.managedCommand 必须是对象")
    managed_entrypoint = _expect_relative_path(
        managed_raw.get("entrypoint", ""),
        f"providers.{provider_id}.managedCommand.entrypoint",
        allow_empty=runtime == "native",
    )
    managed_args = tuple(
        _expect_text_list(
            managed_raw.get("args"),
            f"providers.{provider_id}.managedCommand.args",
            allow_empty=provider_id == "clangd",
        )
    )
    if runtime == "node" and not managed_entrypoint:
        raise LanguageServerManifestError(f"providers.{provider_id} 缺少 Node 入口")

    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list) or not assets_raw:
        raise LanguageServerManifestError(f"providers.{provider_id}.assets 必须是非空数组")
    assets = tuple(_parse_asset(provider_id, runtime, item) for item in assets_raw)
    target_platform_pairs = [(asset.target, asset.platform) for asset in assets]
    if len(target_platform_pairs) != len(set(target_platform_pairs)):
        raise LanguageServerManifestError(f"providers.{provider_id} 存在重复的安装目标")
    if runtime == "native" and any(not asset.entrypoint for asset in assets):
        raise LanguageServerManifestError(f"providers.{provider_id} 缺少本机入口")

    return LanguageServerProvider(
        provider_id=provider_id,
        display_name=_expect_text(raw.get("displayName"), f"providers.{provider_id}.displayName"),
        version=_expect_pinned_version(raw.get("version"), f"providers.{provider_id}.version"),
        runtime=runtime,
        environment_variable=environment_variable,
        path_commands=tuple(path_commands),
        managed_entrypoint=managed_entrypoint,
        managed_args=managed_args,
        extensions=tuple(extensions),
        license_spdx=license_spdx,
        license_url=license_url,
        assets=assets,
    )


def _parse_asset(provider_id: str, runtime: str, raw: Any) -> LanguageServerAsset:
    if not isinstance(raw, dict):
        raise LanguageServerManifestError(f"providers.{provider_id}.assets 项必须是对象")
    asset_id = _expect_text(raw.get("id"), f"providers.{provider_id}.assets.id")
    if not _IDENTIFIER_RE.fullmatch(asset_id):
        raise LanguageServerManifestError(f"无效资产 ID: {asset_id}")
    platform_key = normalize_platform_key(_expect_text(raw.get("platform"), f"providers.{provider_id}.assets.platform"))
    if not platform_key or platform_key == "unknown":
        raise LanguageServerManifestError(f"无效资产平台: {provider_id}/{asset_id}")
    archive = _expect_choice(raw.get("archive"), f"providers.{provider_id}.assets.archive", {"zip", "tar.gz"})
    archive_root = _expect_relative_path(
        raw.get("archiveRoot", ""),
        f"providers.{provider_id}.assets.archiveRoot",
        allow_empty=True,
    )
    target = _expect_relative_path(raw.get("target"), f"providers.{provider_id}.assets.target", allow_empty=False)
    entrypoint = _expect_relative_path(
        raw.get("entrypoint", ""),
        f"providers.{provider_id}.assets.entrypoint",
        allow_empty=runtime == "node",
    )
    sha256 = _expect_text(raw.get("sha256"), f"providers.{provider_id}.assets.sha256").lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise LanguageServerManifestError(f"无效 SHA-256: {provider_id}/{asset_id}")
    return LanguageServerAsset(
        asset_id=asset_id,
        version=_expect_pinned_version(raw.get("version"), f"providers.{provider_id}.assets.version"),
        platform=platform_key,
        url=_expect_download_url(raw.get("url"), f"providers.{provider_id}.assets.url"),
        sha256=sha256,
        archive=archive,
        archive_root=archive_root,
        target=target,
        entrypoint=entrypoint,
    )


def _expect_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LanguageServerManifestError(f"{label} 必须是整数") from exc


def _expect_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LanguageServerManifestError(f"{label} 不能为空")
    return text


def _expect_pinned_version(value: Any, label: str) -> str:
    text = _expect_text(value, label)
    if not _PINNED_VERSION_RE.fullmatch(text):
        raise LanguageServerManifestError(f"{label} 必须是固定数字版本")
    return text


def _expect_text_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        message = "字符串数组" if allow_empty else "非空字符串数组"
        raise LanguageServerManifestError(f"{label} 必须是{message}")
    return [_expect_text(item, label) for item in value]


def _expect_choice(value: Any, label: str, allowed: set[str]) -> str:
    text = _expect_text(value, label)
    if text not in allowed:
        raise LanguageServerManifestError(f"{label} 仅支持: {', '.join(sorted(allowed))}")
    return text


def _expect_relative_path(value: Any, label: str, *, allow_empty: bool) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        if allow_empty:
            return ""
        raise LanguageServerManifestError(f"{label} 不能为空")
    candidate = Path(text)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in text.split("/")):
        raise LanguageServerManifestError(f"{label} 必须是安全的相对路径")
    return text


def _expect_download_url(value: Any, label: str) -> str:
    text = _expect_text(value, label)
    if _DYNAMIC_RELEASE_RE.search(text):
        raise LanguageServerManifestError(f"{label} 不允许使用动态 latest 地址")
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme == "https" and parsed.netloc:
        return text
    if scheme == "file" and parsed.path:
        return text
    if scheme not in {"https", "file"}:
        raise LanguageServerManifestError(f"{label} 只允许 https 或测试用 file URI")
    raise LanguageServerManifestError(f"{label} 缺少有效的下载地址")


def _expect_https_url(value: Any, label: str) -> str:
    text = _expect_text(value, label)
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise LanguageServerManifestError(f"{label} 必须是 https URL")
    return text
