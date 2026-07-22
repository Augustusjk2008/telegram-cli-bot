from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bot.language_server.catalog import LanguageServerCatalog
from bot.language_server.manifest import LanguageServerManifestError, load_language_server_manifest


class FakeInstaller:
    def __init__(self, manifest, *, platform_key: str = "windows-x64") -> None:
        self.manifest = manifest
        self.platform_key = platform_key
        self.managed: dict[str, dict[str, Any]] = {}
        self.installing: set[str] = set()
        self.errors: dict[str, dict[str, str]] = {}

    def can_install(self, provider_id: str) -> bool:
        return bool(self.manifest.get(provider_id).select_assets(self.platform_key))

    def current_installation(self, provider_id: str) -> dict[str, Any] | None:
        return self.managed.get(provider_id)

    def is_installing(self, provider_id: str) -> bool:
        return provider_id in self.installing

    def last_error(self, provider_id: str) -> dict[str, str] | None:
        return self.errors.get(provider_id)


def _manifest():
    return load_language_server_manifest("tools/language-servers/manifest.json")


def test_catalog_selects_platform_assets_from_fixed_manifest() -> None:
    manifest = _manifest()
    clangd = manifest.get("clangd")

    windows_asset = clangd.select_assets("win32-x64")
    linux_asset = clangd.select_assets("linux-x64")
    mac_asset = clangd.select_assets("darwin-arm64")

    assert windows_asset[0].platform == "windows-x64"
    assert windows_asset[0].entrypoint == "bin/clangd.exe"
    assert linux_asset[0].entrypoint == "bin/clangd"
    assert mac_asset[0].url.endswith("clangd-mac-22.1.0.zip")
    assert manifest.get("typescript").select_assets("linux-x64")[0].platform == "any"


def test_fixed_manifest_contains_pinned_assets_and_license_metadata() -> None:
    manifest = _manifest()

    for provider_id in ("pyright", "typescript", "clangd"):
        provider = manifest.get(provider_id)
        assert provider.version
        assert provider.license_spdx
        assert provider.license_url.startswith("https://")
        for asset in provider.assets:
            assert asset.version
            assert asset.url.startswith("https://")
            assert len(asset.sha256) == 64
            assert "latest" not in asset.url.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_version", "latest"),
        ("asset_version", "main"),
        ("asset_url", "https:///missing-host.tgz"),
        ("asset_url", "https://example.test/releases/latest/download/pyright.tgz"),
    ],
)
def test_manifest_loader_rejects_dynamic_versions_and_invalid_download_urls(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = json.loads(Path("tools/language-servers/manifest.json").read_text(encoding="utf-8"))
    pyright = payload["providers"]["pyright"]
    if field == "provider_version":
        pyright["version"] = value
    elif field == "asset_version":
        pyright["assets"][0]["version"] = value
    else:
        pyright["assets"][0]["url"] = value
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LanguageServerManifestError):
        load_language_server_manifest(path)


def test_catalog_prefers_explicit_command_over_path_and_managed() -> None:
    installer = FakeInstaller(_manifest())
    installer.managed["pyright"] = {
        "provider": "pyright",
        "version": "1.1.410",
        "entrypoint": "C:/managed/pyright/langserver.index.js",
    }
    resolver_calls: list[str] = []
    probe_calls: list[tuple[str, ...]] = []

    def resolver(command: str) -> str | None:
        resolver_calls.append(command)
        return {
            "custom-pyright": "C:/custom/custom-pyright.cmd",
            "pyright-langserver": "C:/path/pyright-langserver.cmd",
            "node": "C:/node/node.exe",
        }.get(command)

    def version_probe(command: tuple[str, ...]) -> str:
        probe_calls.append(command)
        return "custom 1.0"

    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        commands={"pyright": "custom-pyright --stdio"},
        executable_resolver=resolver,
        version_probe=version_probe,
    )

    status = catalog.provider_status("pyright")

    assert status["status"] == "available"
    assert status["source"] == "custom"
    assert status["version"] == "custom 1.0"
    assert status["commandSummary"] == "custom-pyright.cmd"
    assert resolver_calls == ["custom-pyright"]
    assert "--stdio" not in probe_calls[0]


def test_catalog_does_not_fall_back_when_explicit_command_is_missing() -> None:
    installer = FakeInstaller(_manifest())

    def resolver(command: str) -> str | None:
        if command == "pyright-langserver":
            return "C:/path/pyright-langserver.cmd"
        return None

    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        commands={"pyright": "missing-custom"},
        executable_resolver=resolver,
    )

    status = catalog.provider_status("pyright")

    assert status["status"] == "missing"
    assert status["source"] == "custom"
    assert "显式配置" in status["message"]


def test_catalog_rejects_shell_metacharacters_in_explicit_batch_command() -> None:
    installer = FakeInstaller(_manifest())
    probe_calls: list[tuple[str, ...]] = []
    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        commands={"pyright": "custom-pyright --stdio & calc.exe"},
        executable_resolver=lambda command: "C:/tools/custom-pyright.cmd" if command == "custom-pyright" else None,
        version_probe=lambda command: probe_calls.append(tuple(command)) or "1.0.0",
    )

    status = catalog.provider_status("pyright")

    assert status["status"] == "missing"
    assert status["source"] == "custom"
    assert status["canInstall"] is False
    assert probe_calls == []


def test_catalog_requires_nonempty_version_probe_for_path_commands() -> None:
    installer = FakeInstaller(_manifest())
    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        executable_resolver=lambda command: "C:/tools/pyright-langserver.cmd" if command == "pyright-langserver" else None,
        version_probe=lambda _command: "",
    )

    status = catalog.provider_status("pyright")

    assert status["status"] == "missing"
    assert status["source"] == ""
    assert status["canInstall"] is True


def test_catalog_uses_path_then_managed_and_disabled_state_never_installs() -> None:
    manifest = _manifest()
    installer = FakeInstaller(manifest)
    installer.managed["clangd"] = {
        "provider": "clangd",
        "version": "22.1.0",
        "entrypoint": "C:/managed/clangd.exe",
    }

    def resolver(command: str) -> str | None:
        return {
            "typescript-language-server": "C:/path/typescript-language-server.cmd",
            "node": "C:/node/node.exe",
        }.get(command)

    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=False,
        executable_resolver=resolver,
        version_probe=lambda _command: "found",
    )
    snapshot = catalog.snapshot()
    statuses = {item["id"]: item for item in snapshot["providers"]}

    assert snapshot["enabled"] is False
    assert statuses["typescript"]["source"] == "path"
    assert statuses["typescript"]["status"] == "disabled"
    assert statuses["clangd"]["source"] == "managed"
    assert statuses["clangd"]["version"] == "22.1.0"
    assert statuses["pyright"]["status"] == "disabled"
    assert not hasattr(installer, "install_calls")
    api_statuses = {item["provider"]: item for item in catalog.api_snapshot()["providers"]}
    assert {item["status"] for item in api_statuses.values()} == {"missing"}
    assert all(not item["can_install"] and not item["can_update"] for item in api_statuses.values())
    assert all(item["message"] for item in api_statuses.values())


def test_catalog_action_flags_follow_discovery_source_and_managed_update_state() -> None:
    installer = FakeInstaller(_manifest())
    installer.managed["clangd"] = {
        "provider": "clangd",
        "version": "21.0.0",
        "entrypoint": "C:/managed/clangd.exe",
        "updateAvailable": True,
    }

    def resolver(command: str) -> str | None:
        if command == "pyright-langserver":
            return "C:/path/pyright-langserver.cmd"
        return None

    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        executable_resolver=resolver,
        version_probe=lambda _command: "found",
    )
    statuses = {item["provider"]: item for item in catalog.api_snapshot()["providers"]}

    assert statuses["pyright"]["source"] == "path"
    assert statuses["pyright"]["can_install"] is False
    assert statuses["pyright"]["can_update"] is False
    assert statuses["typescript"]["status"] == "missing"
    assert statuses["typescript"]["can_install"] is True
    assert statuses["clangd"]["source"] == "managed"
    assert statuses["clangd"]["can_install"] is False
    assert statuses["clangd"]["can_update"] is True

    installer.managed["clangd"]["updateAvailable"] = False
    current = next(item for item in catalog.api_snapshot()["providers"] if item["provider"] == "clangd")
    assert current["can_update"] is False


def test_catalog_retains_install_errors_and_keeps_an_old_managed_version_available() -> None:
    installer = FakeInstaller(_manifest())
    installer.managed["clangd"] = {
        "provider": "clangd",
        "version": "21.0.0",
        "entrypoint": "C:/managed/clangd.exe",
        "updateAvailable": True,
    }
    installer.errors["clangd"] = {"code": "language_server_checksum_mismatch", "message": "更新包校验失败"}
    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        executable_resolver=lambda _command: None,
    )

    status = next(item for item in catalog.api_snapshot()["providers"] if item["provider"] == "clangd")

    assert status["status"] == "available"
    assert status["version"] == "21.0.0"
    assert status["can_update"] is True
    assert "更新包校验失败" in status["message"]


def test_catalog_reports_last_install_error_when_no_command_is_available() -> None:
    installer = FakeInstaller(_manifest())
    installer.errors["pyright"] = {"code": "language_server_download_failed", "message": "下载失败"}
    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        executable_resolver=lambda _command: None,
    )

    status = next(item for item in catalog.api_snapshot()["providers"] if item["provider"] == "pyright")

    assert status["status"] == "error"
    assert status["can_install"] is True
    assert status["error"] == "下载失败"
    assert status["message"] == "下载失败"


def test_catalog_reports_missing_manifest_without_blocking_disabled_configuration(tmp_path: Path) -> None:
    catalog = LanguageServerCatalog(manifest_path=tmp_path / "missing-manifest.json", enabled=False)

    snapshot = catalog.snapshot()

    assert snapshot["enabled"] is False
    assert {item["id"] for item in snapshot["providers"]} == {"pyright", "typescript", "clangd"}
    assert {item["status"] for item in snapshot["providers"]} == {"error"}


def test_catalog_api_snapshot_uses_stable_snake_case_contract() -> None:
    installer = FakeInstaller(_manifest())
    catalog = LanguageServerCatalog(
        installer=installer,  # type: ignore[arg-type]
        enabled=True,
        executable_resolver=lambda _command: None,
    )

    payload = catalog.api_snapshot()
    pyright = next(item for item in payload["providers"] if item["provider"] == "pyright")

    assert payload["can_refresh"] is True
    assert pyright == {
        "provider": "pyright",
        "status": "missing",
        "source": None,
        "version": "",
        "command_summary": "",
        "can_install": True,
        "can_update": False,
        "message": "未发现可用命令；可由管理员安装受支持的托管版本",
        "error": "",
    }
