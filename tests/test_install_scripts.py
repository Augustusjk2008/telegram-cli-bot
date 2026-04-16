import json
import os
import subprocess
from pathlib import Path

import pytest


WINDOWS_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def _run_install_ps1_command(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script_path = Path("install.ps1").resolve()
    wrapped = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$env:CLI_BRIDGE_INSTALLER_TEST_SKIP_MAIN = '1'",
            f". '{script_path}'",
            command,
        ]
    )
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=merged_env,
        cwd=Path.cwd(),
    )


def test_install_bat_forwards_arguments_to_install_ps1_and_pauses():
    content = Path("install.bat").read_text(encoding="utf-8")

    assert "install.ps1" in content
    assert "%*" in content
    assert "pause" in content.lower()


def test_install_sh_mentions_apt_node_check_only_and_cli_warning():
    content = Path("install.sh").read_text(encoding="utf-8")

    assert "apt-get" in content
    assert "--check-only" in content
    assert "--non-interactive" in content
    assert "codex" in content
    assert "claude" in content
    assert ".env.example" in content


def test_env_example_preconfigures_default_update_repository():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot" in content


def test_env_example_defaults_web_host_to_wildcard():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "WEB_HOST=0.0.0.0" in content
    assert "WEB_HOST=127.0.0.1" not in content


def test_env_example_omits_unused_assistant_mode_settings():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "Assistant Mode Optional" not in content
    assert "ANTHROPIC_API_KEY=" not in content
    assert "ANTHROPIC_MODEL=" not in content
    assert "ANTHROPIC_BASE_URL=" not in content


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_parses_in_windows_powershell():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    command = "\n".join(
        [
            "$errors = $null",
            "$tokens = $null",
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors)",
            "'count=' + $errors.Count",
            "$errors | ForEach-Object { $_.Message }",
        ]
    )

    result = subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert result.returncode == 0
    assert "count=0" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_can_skip_main_for_function_level_tests():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$env:CLI_BRIDGE_INSTALLER_TEST_SKIP_MAIN = '1'",
            f". '{script_path}'",
            "'skip-main-ok'",
        ]
    )

    result = subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "skip-main-ok" in result.stdout


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_check_only_mode_warns_when_no_cli():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    env = os.environ.copy()
    env["CLI_BRIDGE_INSTALLER_TEST_FORCE_NO_CLI"] = "1"

    result = subprocess.run(
        [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-CheckOnly",
            "-NonInteractive",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
        cwd=Path.cwd(),
    )

    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "[警告]" in output
    assert "codex" in output.lower()
    assert "claude" in output.lower()


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_install_repo_executable_places_binary_under_tools_dir(tmp_path: Path):
    result = _run_install_ps1_command(
        f"""
$script:RootDir = '{tmp_path}'
function Download-File {{
    param([string]$Url, [string]$FileName)
    $downloaded = Join-Path '{tmp_path}' 'downloaded.exe'
    Set-Content -Path $downloaded -Value 'binary'
    return $downloaded
}}
$installed = Install-RepoExecutable -DisplayName 'codex' -Url 'https://example.test/codex.exe' -RelativeDirectory 'tools\\codex' -TargetFileName 'codex.exe'
@{{ Path = $installed; Exists = [bool](Test-Path -LiteralPath $installed) }} | ConvertTo-Json -Compress
"""
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Exists"] is True
    assert payload["Path"].endswith("tools\\codex\\codex.exe")


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_optional_codex_install_uses_x64_download_and_updates_path(tmp_path: Path):
    result = _run_install_ps1_command(
        f"""
$script:RootDir = '{tmp_path}'
$captured = [ordered]@{{}}
function Read-Choice {{
    param([string]$Prompt, [string[]]$Choices, [string]$DefaultChoice)
    return '1'
}}
function Download-File {{
    param([string]$Url, [string]$FileName)
    $captured['Url'] = $Url
    $downloaded = Join-Path '{tmp_path}' 'codex-download.exe'
    Set-Content -Path $downloaded -Value 'binary'
    return $downloaded
}}
function Add-UserPathEntry {{
    param([string]$PathEntry)
    $captured['PathEntry'] = $PathEntry
}}
$cliInfo = [pscustomobject]@{{ Codex = $null; Claude = $null }}
$updated = Ensure-OptionalCodexInstall -CliInfo $cliInfo
$captured['InstalledPath'] = $updated.Codex.Path
$captured | ConvertTo-Json -Compress
"""
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Url"] == "https://github.com/openai/codex/releases/download/rust-v0.121.0/codex-x86_64-pc-windows-msvc.exe"
    assert payload["PathEntry"].endswith("tools\\codex")
    assert payload["InstalledPath"].endswith("tools\\codex\\codex.exe")


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_cloudflared_defaults_to_quick_mode_and_installs_when_requested(tmp_path: Path):
    result = _run_install_ps1_command(
        f"""
$script:RootDir = '{tmp_path}'
$captured = [ordered]@{{}}
function Read-Choice {{
    param([string]$Prompt, [string[]]$Choices, [string]$DefaultChoice)
    switch -Wildcard ($Prompt) {{
        '*启用 cloudflared*' {{ return '2' }}
        '*自动安装 cloudflared*' {{ return '1' }}
        default {{ return $DefaultChoice }}
    }}
}}
function Read-TextWithDefault {{
    param([string]$Prompt, [string]$DefaultValue)
    return ''
}}
function Get-CommandPath {{
    param([string]$Name)
    return $null
}}
function Install-RepoExecutable {{
    param([string]$DisplayName, [string]$Url, [string]$RelativeDirectory, [string]$TargetFileName)
    $captured['Url'] = $Url
    $captured['TargetFileName'] = $TargetFileName
    return 'C:\\repo\\tools\\cloudflared\\cloudflared.exe'
}}
$config = Resolve-TunnelConfiguration
$captured['Mode'] = $config.Mode
$captured['CloudflaredPath'] = $config.CloudflaredPath
$captured | ConvertTo-Json -Compress
"""
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Mode"] == "cloudflare_quick"
    assert payload["Url"] == "https://github.com/cloudflare/cloudflared/releases/download/2026.3.0/cloudflared-windows-amd64.exe"
    assert payload["TargetFileName"] == "cloudflared.exe"
    assert payload["CloudflaredPath"].endswith("cloudflared.exe")


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_public_url_disables_cloudflare_quick(tmp_path: Path):
    result = _run_install_ps1_command(
        f"""
$script:RootDir = '{tmp_path}'
function Read-Choice {{
    param([string]$Prompt, [string[]]$Choices, [string]$DefaultChoice)
    if ($Prompt -like '*启用 cloudflared*') {{ return '2' }}
    return $DefaultChoice
}}
function Read-TextWithDefault {{
    param([string]$Prompt, [string]$DefaultValue)
    if ($Prompt -like '*WEB_PUBLIC_URL*') {{ return 'https://bot.example.com' }}
    return $DefaultValue
}}
$config = Resolve-TunnelConfiguration
$config | ConvertTo-Json -Compress
"""
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Mode"] == "disabled"
    assert payload["PublicUrl"] == "https://bot.example.com"


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_configure_env_writes_tunnel_values(tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "\n".join(
            [
                "CLI_TYPE=codex",
                "CLI_PATH=codex",
                "WORKING_DIR=C:\\\\work",
                "WEB_ENABLED=true",
                "WEB_HOST=0.0.0.0",
                "WEB_PORT=8765",
                "WEB_API_TOKEN=change-this-password",
                "WEB_PUBLIC_URL=",
                "WEB_TUNNEL_MODE=disabled",
                "WEB_TUNNEL_CLOUDFLARED_PATH=",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_install_ps1_command(
        f"""
$script:RootDir = '{tmp_path}'
function Read-Choice {{
    param([string]$Prompt, [string[]]$Choices, [string]$DefaultChoice)
    return '1'
}}
function Read-TextWithDefault {{
    param([string]$Prompt, [string]$DefaultValue)
    if ($Prompt -like '*默认工作目录*') {{ return '{tmp_path}' }}
    if ($Prompt -like '*WEB_API_TOKEN*') {{ return 'token-123' }}
    return $DefaultValue
}}
$cliInfo = [pscustomobject]@{{ Codex = [pscustomobject]@{{ Path = 'C:\\repo\\tools\\codex\\codex.exe' }}; Claude = $null }}
$tunnelConfig = [pscustomobject]@{{ Mode = 'cloudflare_quick'; PublicUrl = ''; CloudflaredPath = 'C:\\repo\\tools\\cloudflared\\cloudflared.exe' }}
Configure-EnvFile -CliInfo $cliInfo -TunnelConfig $tunnelConfig
Get-Content (Join-Path $script:RootDir '.env')
"""
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "CLI_PATH=C:\\repo\\tools\\codex\\codex.exe" in output
    assert "WEB_TUNNEL_MODE=cloudflare_quick" in output
    assert "WEB_TUNNEL_CLOUDFLARED_PATH=C:\\repo\\tools\\cloudflared\\cloudflared.exe" in output
