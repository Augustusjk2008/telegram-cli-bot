"""语言服务器的只读发现目录。"""

from __future__ import annotations

import shlex
import subprocess
import sys
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from bot import config
from bot.platform.executables import build_executable_invocation, resolve_cli_executable

from .installer import LanguageServerInstaller
from .manifest import (
    PROVIDER_IDS,
    LanguageServerManifest,
    LanguageServerManifestError,
    LanguageServerProvider,
    current_platform_key,
    normalize_platform_key,
)


_DEFAULT_COMMANDS = {
    "pyright": "pyright-langserver",
    "typescript": "typescript-language-server",
    "clangd": "clangd",
}


class LanguageServerCatalog:
    """按“显式命令 → PATH → 托管目录”顺序发现语言服务器。

    本类只检查命令和已安装文件，从不调用安装器的 ``install``，因此普通状态
    查询和打开文件均不会产生网络下载或运行时进程。
    """

    def __init__(
        self,
        *,
        installer: LanguageServerInstaller | None = None,
        manifest: LanguageServerManifest | None = None,
        manifest_path: Path | str | None = None,
        enabled: bool | None = None,
        commands: Mapping[str, str] | None = None,
        platform_key: str | None = None,
        executable_resolver: Callable[[str], str | None] | None = None,
        version_probe: Callable[[Sequence[str]], str | None] | None = None,
    ) -> None:
        if installer is not None and (manifest is not None or manifest_path is not None):
            raise ValueError("指定 installer 时不能同时指定 manifest 或 manifest_path")
        self.installer = installer or LanguageServerInstaller(manifest=manifest, manifest_path=manifest_path)
        self.manifest = self.installer.manifest
        self.enabled = config.TCB_LSP_ENABLED if enabled is None else bool(enabled)
        configured = {
            "pyright": config.TCB_LSP_PYRIGHT_COMMAND,
            "typescript": config.TCB_LSP_TYPESCRIPT_COMMAND,
            "clangd": config.TCB_LSP_CLANGD_COMMAND,
        }
        if commands is not None:
            configured.update({key: str(value or "") for key, value in commands.items() if key in PROVIDER_IDS})
        self.commands = configured
        self.platform_key = normalize_platform_key(platform_key or self.installer.platform_key or current_platform_key())
        self._resolve_executable = executable_resolver or resolve_cli_executable
        self._version_probe = version_probe or _probe_version

    def snapshot(self) -> dict[str, Any]:
        if self.manifest is None:
            return {
                "enabled": self.enabled,
                "platform": self.platform_key,
                "providers": [self._manifest_unavailable_status(provider_id) for provider_id in PROVIDER_IDS],
            }
        return {
            "enabled": self.enabled,
            "platform": self.platform_key,
            "providers": [self.provider_status(provider_id) for provider_id in PROVIDER_IDS],
        }

    def redetect(self) -> dict[str, Any]:
        """重新执行只读发现；保留为管理员重新检测 API 的明确入口。"""

        return self.api_snapshot()

    def api_snapshot(self) -> dict[str, Any]:
        """转换为稳定的 Web API 字段；不暴露本机绝对命令路径。"""

        snapshot = self.snapshot()
        providers: list[dict[str, Any]] = []
        for item in snapshot["providers"]:
            internal_status = str(item.get("status") or "missing")
            if internal_status == "disabled":
                status = "missing"
            elif internal_status == "installing":
                status = "installing"
            elif internal_status == "error":
                status = "error"
            elif bool(item.get("available")):
                # TCB_LSP_ENABLED 关闭时仍可安全展示已发现工具；前端的可用
                # 状态类型不包含 disabled，实际运行时会在后续阶段读取该开关。
                status = "available"
            else:
                status = "missing"
            source = str(item.get("source") or "").strip() or None
            message = str(item.get("message") or "").strip()
            providers.append(
                {
                    "provider": item["id"],
                    "status": status,
                    "source": source,
                    "version": str(item.get("version") or ""),
                    "command_summary": str(item.get("commandSummary") or ""),
                    "can_install": bool(item.get("canInstall")),
                    "can_update": bool(item.get("canUpdate")),
                    "message": message,
                    "error": (
                        message
                        if status == "error" or (internal_status == "missing" and source == "custom")
                        else ""
                    ),
                }
            )
        return {
            "providers": providers,
            "can_refresh": True,
            "enabled": bool(snapshot["enabled"]),
            "platform": snapshot["platform"],
        }

    def provider_status(self, provider_id: str) -> dict[str, Any]:
        provider = self._provider(provider_id)
        installing = self.installer.is_installing(provider.provider_id)
        installation = self.installer.current_installation(provider.provider_id)
        result = self._base_status(provider, installing=installing, installation=installation)
        last_error = self._last_error(provider.provider_id)
        managed_supported = bool(result["managedSupported"])
        if installing:
            return {
                **result,
                "status": "installing",
                "canInstall": False,
                "canUpdate": False,
                "message": "正在安装或更新托管版本",
            }

        discovered = self._discover(provider)
        if discovered is None:
            explicit = str(self.commands.get(provider.provider_id, "") or "").strip()
            message = (
                "显式配置的命令不可用；请修正配置后重新检测"
                if explicit
                else ("未发现可用命令；可由管理员安装受支持的托管版本" if self.enabled else "语言服务已关闭")
            )
            status = "disabled" if not self.enabled else "missing"
            if self.enabled and not explicit and last_error is not None:
                status = "error"
                message = last_error["message"]
            return {
                **result,
                "status": status,
                "available": False,
                "source": "custom" if explicit else "",
                "canInstall": bool(self.enabled and not explicit and managed_supported),
                "canUpdate": False,
                "message": message,
            }

        source, command, version, message, summary_executable = discovered
        if last_error is not None:
            message = f"{message}；最近一次托管操作失败：{last_error['message']}"
        return {
            **result,
            "status": "available" if self.enabled else "disabled",
            "available": True,
            "source": source,
            "version": version,
            "commandSummary": _command_summary((summary_executable,)),
            "canInstall": False,
            "canUpdate": bool(
                self.enabled
                and source == "managed"
                and managed_supported
                and installation is not None
                and installation.get("updateAvailable")
            ),
            "message": message if self.enabled else "语言服务已关闭；已检测到可用命令",
        }

    def command_for(self, provider_id: str) -> tuple[str, ...] | None:
        """返回发现后的 argv，供后续运行时阶段使用；不启动进程。"""

        if self.manifest is None:
            return None
        provider = self._provider(provider_id)
        discovered = self._discover(provider)
        return discovered[1] if discovered is not None else None

    def _base_status(
        self,
        provider: LanguageServerProvider,
        *,
        installing: bool,
        installation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        managed_supported = self.installer.can_install(provider.provider_id)
        return {
            "id": provider.provider_id,
            "displayName": provider.display_name,
            "extensions": list(provider.extensions),
            "status": "missing",
            "available": False,
            "installing": installing,
            "source": "",
            "version": "",
            "managedVersion": str((installation or {}).get("version") or ""),
            "commandSummary": "",
            "canInstall": False,
            "canUpdate": False,
            "managedSupported": managed_supported,
            "license": {"spdx": provider.license_spdx, "url": provider.license_url},
            "message": "",
        }

    def _discover(self, provider: LanguageServerProvider) -> tuple[str, tuple[str, ...], str, str, str] | None:
        explicit = str(self.commands.get(provider.provider_id, "") or "").strip()
        if explicit:
            parts = _split_command(explicit)
            if not parts:
                return None
            resolved = self._resolve_executable(parts[0])
            if not resolved:
                return None
            if not _shell_wrapped_command_is_safe(resolved, parts[1:]):
                return None
            invocation = build_executable_invocation(resolved)
            command = tuple(invocation + list(parts[1:]))
            version = str(self._version_probe(tuple(invocation)) or "").strip()
            if not version:
                return None
            return "custom", command, version, "使用显式配置命令", resolved

        for candidate in provider.path_commands or (_DEFAULT_COMMANDS[provider.provider_id],):
            resolved = self._resolve_executable(candidate)
            if not resolved:
                continue
            if not _shell_wrapped_command_is_safe(resolved, provider.managed_args):
                continue
            invocation = build_executable_invocation(resolved)
            command = tuple(invocation + list(provider.managed_args))
            version = str(self._version_probe(tuple(invocation)) or "").strip()
            if not version:
                continue
            return "path", command, version, "使用 PATH 中的命令", resolved

        installation = self.installer.current_installation(provider.provider_id)
        if installation is None:
            return None
        entrypoint = str(installation["entrypoint"])
        if provider.runtime == "node":
            node = self._resolve_executable("node")
            if not node:
                return None
            invocation = build_executable_invocation(node) + [entrypoint]
            command = tuple(invocation + list(provider.managed_args))
        else:
            invocation = build_executable_invocation(entrypoint)
            command = tuple(invocation + list(provider.managed_args))
        version = str(installation.get("version") or "") or self._version_probe(tuple(invocation))
        return "managed", command, version, "使用托管版本", entrypoint

    def _last_error(self, provider_id: str) -> dict[str, str] | None:
        getter = getattr(self.installer, "last_error", None)
        if not callable(getter):
            return None
        error = getter(provider_id)
        if not isinstance(error, dict):
            return None
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        if not code or not message:
            return None
        return {"code": code, "message": message}

    def _provider(self, provider_id: str) -> LanguageServerProvider:
        if self.manifest is None:
            raise ValueError("语言服务器清单不可用，请检查安装包完整性")
        try:
            return self.manifest.get(provider_id)
        except LanguageServerManifestError as exc:
            raise ValueError(str(exc)) from exc

    def _manifest_unavailable_status(self, provider_id: str) -> dict[str, Any]:
        labels = {
            "pyright": "Pyright",
            "typescript": "TypeScript Language Server",
            "clangd": "clangd",
        }
        return {
            "id": provider_id,
            "displayName": labels[provider_id],
            "extensions": [],
            "status": "error",
            "available": False,
            "installing": False,
            "source": "",
            "version": "",
            "managedVersion": "",
            "commandSummary": "",
            "canInstall": False,
            "license": {"spdx": "", "url": ""},
            "message": "语言服务器清单不可用，请检查安装包完整性",
        }


def _split_command(value: str) -> tuple[str, ...]:
    try:
        parts = shlex.split(value, posix=sys.platform != "win32")
    except ValueError:
        return ()
    normalized = [str(part).strip().strip('"').strip("'") for part in parts]
    return tuple(part for part in normalized if part)


def _command_summary(command: Sequence[str]) -> str:
    if not command:
        return ""
    executable = str(command[0]).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return executable or "语言服务器命令"


def _probe_version(command: Sequence[str]) -> str | None:
    if not command:
        return None
    try:
        completed = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    output = f"{completed.stdout}\n{completed.stderr}"
    for line in output.splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            return cleaned[:160]
    return None


_BATCH_PATH_UNSAFE_RE = re.compile(r"[&|<>^%!\r\n\"]")
_BATCH_ARGUMENT_UNSAFE_RE = re.compile(r"[&|<>^()%!\r\n\"]")


def _shell_wrapped_command_is_safe(resolved: str, arguments: Sequence[str]) -> bool:
    if Path(resolved).suffix.lower() not in {".cmd", ".bat"}:
        return True
    if _BATCH_PATH_UNSAFE_RE.search(str(resolved)):
        return False
    return not any(_BATCH_ARGUMENT_UNSAFE_RE.search(str(argument)) for argument in arguments)
