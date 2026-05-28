param(
    [string]$GitRoot = "C:\Program Files\Git",
    [string]$PackageName = "",
    [string]$ArtifactPath = "",
    [switch]$SkipFrontBuild
)

$ErrorActionPreference = "Stop"

$script:PortableRoot = $PSScriptRoot
$script:ReleaseLocalRoot = Split-Path -Parent $script:PortableRoot
$script:RepoRoot = Split-Path -Parent $script:ReleaseLocalRoot
$script:StageRoot = Join-Path $script:PortableRoot "stage"
$script:ArtifactsRoot = Join-Path $script:PortableRoot "artifacts"
$script:DownloadsRoot = Join-Path $script:PortableRoot "downloads"
$script:FrontDir = Join-Path $script:RepoRoot "front"
$script:VersionFile = Join-Path $script:RepoRoot "VERSION"
$script:PackageBaseName = "orbit-safe-claw"

function Write-Step {
    param([string]$Message)
    Write-Host ("[步骤] {0}" -f $Message) -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host ("[信息] {0}" -f $Message)
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $originalLocation = Get-Location
    try {
        Set-Location $WorkingDirectory
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        Set-Location $originalLocation
    }

    if ($exitCode -ne 0) {
        throw "{0} (退出码 {1})" -f $FailureMessage, $exitCode
    }
}

function Get-AppVersion {
    if (Test-Path -LiteralPath $script:VersionFile) {
        return (Get-Content -LiteralPath $script:VersionFile -Raw -Encoding UTF8).Trim()
    }
    return "dev"
}

function New-WebToken {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([Convert]::ToBase64String($bytes)).TrimEnd("=") -replace "[+/]", "A"
}

function Reset-Directory {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    [void](New-Item -ItemType Directory -Path $Path -Force)
}

function Get-PythonEmbedUrl {
    $currentVersion = (& python --version 2>&1 | Select-Object -First 1)
    if ($currentVersion -notmatch "Python (?<major>\d+)\.(?<minor>\d+)\.\d+") {
        throw "无法读取当前 Python 版本。"
    }
    $majorMinor = "{0}.{1}" -f $Matches["major"], $Matches["minor"]

    $cachedZip = Get-ChildItem -LiteralPath $script:DownloadsRoot -Filter ("python-{0}.*-embed-amd64.zip" -f $majorMinor) -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($cachedZip -and $cachedZip.Name -match "^python-(?<version>\d+\.\d+\.\d+)-embed-amd64\.zip$") {
        $version = $Matches["version"]
        return [pscustomobject]@{
            Version = $version
            Url = "https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip"
            FileName = $cachedZip.Name
        }
    }

    $page = Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/downloads/windows/" -TimeoutSec 30
    $match = [regex]::Match(
        $page.Content,
        "https://www\.python\.org/ftp/python/(" + [regex]::Escape($majorMinor) + "\.[0-9]+)/python-\1-amd64\.exe"
    )
    if (-not $match.Success) {
        throw "无法解析 Python $majorMinor embeddable 包地址。"
    }
    $version = $match.Groups[1].Value
    return [pscustomobject]@{
        Version = $version
        Url = "https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip"
        FileName = "python-$version-embed-amd64.zip"
    }
}

function Copy-WorktreeFiles {
    param([string]$DestinationRoot)

    Write-Step "复制 tracked 文件"
    $rawFiles = & git -C $script:RepoRoot ls-files
    if ($LASTEXITCODE -ne 0) {
        throw "读取 tracked 文件失败。"
    }

    $seen = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($relativePath in $rawFiles) {
        $cleanPath = [string]$relativePath
        if ([string]::IsNullOrWhiteSpace($cleanPath)) {
            continue
        }
        if (-not $seen.Add($cleanPath)) {
            continue
        }

        $sourcePath = Join-Path $script:RepoRoot $cleanPath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }
        $destinationPath = Join-Path $DestinationRoot $cleanPath
        $destinationDir = Split-Path -Parent $destinationPath
        if ($destinationDir) {
            [void](New-Item -ItemType Directory -Path $destinationDir -Force)
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force -Recurse
    }

    $frontDist = Join-Path $script:FrontDir "dist"
    if (-not (Test-Path -LiteralPath $frontDist)) {
        throw "未找到 front/dist。"
    }
    $frontDistTarget = Join-Path $DestinationRoot "front\dist"
    if (Test-Path -LiteralPath $frontDistTarget) {
        Remove-Item -LiteralPath $frontDistTarget -Recurse -Force
    }
    [void](New-Item -ItemType Directory -Path $frontDistTarget -Force)
    Copy-Item -Path (Join-Path $frontDist "*") -Destination $frontDistTarget -Recurse -Force
}

function Install-EmbeddedPython {
    param([string]$PackageRoot)

    Write-Step "准备包内 Python"
    $embed = Get-PythonEmbedUrl
    [void](New-Item -ItemType Directory -Path $script:DownloadsRoot -Force)
    $zipPath = Join-Path $script:DownloadsRoot $embed.FileName
    if (-not (Test-Path -LiteralPath $zipPath)) {
        Write-Info ("下载 Python embeddable: {0}" -f $embed.Url)
        Invoke-WebRequest -UseBasicParsing -Uri $embed.Url -OutFile $zipPath
    }

    $pythonRoot = Join-Path $PackageRoot "runtime\python"
    Reset-Directory -Path $pythonRoot
    Expand-Archive -LiteralPath $zipPath -DestinationPath $pythonRoot -Force

    $pthFile = Get-ChildItem -LiteralPath $pythonRoot -Filter "python*._pth" | Select-Object -First 1
    if (-not $pthFile) {
        throw "未找到 Python _pth 文件。"
    }

    $sitePackages = Join-Path $pythonRoot "Lib\site-packages"
    [void](New-Item -ItemType Directory -Path $sitePackages -Force)
    $pthContent = @(
        (Split-Path -Leaf (Get-ChildItem -LiteralPath $pythonRoot -Filter "python*.zip" | Select-Object -First 1).Name),
        ".",
        "..\..",
        "Lib",
        "Lib\site-packages",
        "import site"
    )
    Set-Content -LiteralPath $pthFile.FullName -Value $pthContent -Encoding ASCII

    $siteCustomizePath = Join-Path $sitePackages "sitecustomize.py"
    $siteCustomize = @'
from pathlib import Path
import sys

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[4]
_ROOT_TEXT = str(_ROOT)

if _ROOT_TEXT not in sys.path:
    sys.path.insert(0, _ROOT_TEXT)
'@
    Set-Content -LiteralPath $siteCustomizePath -Value $siteCustomize -Encoding ASCII

    Write-Step "安装包内 Python 依赖"
    $pipEnvRoot = Join-Path $script:DownloadsRoot "pip-build-env"
    Reset-Directory -Path $pipEnvRoot
    try {
        Invoke-CheckedCommand -FilePath "python" -Arguments @(
            "-m", "venv", $pipEnvRoot
        ) -FailureMessage "创建临时 pip 环境失败"

        $pipPython = Join-Path $pipEnvRoot "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $pipPython)) {
            throw "未找到临时 pip 环境 Python: $pipPython"
        }

        Invoke-CheckedCommand -FilePath $pipPython -Arguments @(
            "-m", "pip", "install",
            "--upgrade", "pip"
        ) -FailureMessage "初始化临时 pip 环境失败"

        Invoke-CheckedCommand -FilePath $pipPython -Arguments @(
            "-m", "pip", "install",
            "--upgrade",
            "--ignore-installed",
            "--target", $sitePackages,
            "-r", "requirements.txt"
        ) -FailureMessage "安装包内 Python 依赖失败"
    } finally {
        if (Test-Path -LiteralPath $pipEnvRoot) {
            Remove-Item -LiteralPath $pipEnvRoot -Recurse -Force
        }
    }
}

function Install-PortableGit {
    param(
        [string]$PackageRoot,
        [string]$SourceGitRoot
    )

    if (-not (Test-Path -LiteralPath $SourceGitRoot)) {
        throw "未找到 Git 安装目录: $SourceGitRoot"
    }

    Write-Step "复制包内 Git"
    $targetGitRoot = Join-Path $PackageRoot "tools\git"
    Reset-Directory -Path $targetGitRoot
    Copy-Item -Path (Join-Path $SourceGitRoot "*") -Destination $targetGitRoot -Recurse -Force
}

function Write-PortableEnv {
    param(
        [string]$PackageRoot,
        [string]$Token
    )

    Write-Step "写入包内 .env"
    $content = @"
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=.
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8765
WEB_API_TOKEN=$Token
WEB_PUBLIC_URL=
WEB_TUNNEL_MODE=disabled
WEB_TUNNEL_AUTOSTART=false
APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot
WEB_TUNNEL_CLOUDFLARED_PATH=
WEB_ALLOWED_ORIGINS=
CLI_EXEC_TIMEOUT=4000
SESSION_TIMEOUT=3600
MANAGED_BOTS_FILE=managed_bots.json
"@
    Set-Content -LiteralPath (Join-Path $PackageRoot ".env") -Value $content -Encoding UTF8
}

function Write-PortableScripts {
    param([string]$PackageRoot)

    Write-Step "写入绿色版启动脚本"
    $startPs1 = @'
param(
    [ValidateSet("default", "web")]
    [string]$Mode = "default"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$envPath = Join-Path $scriptDir ".env"
$restartExitCode = 75

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator) -and $env:TCB_PORTABLE_SKIP_ELEVATE -ne "1") {
    Write-Host "[INFO] Requesting administrator privileges..."
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $MyInvocation.MyCommand.Definition,
        "-Mode", $Mode
    )
    Start-Process -FilePath "powershell.exe" -Verb RunAs -WorkingDirectory $scriptDir -ArgumentList $arguments
    exit 0
}

function Prepend-Path {
    param([string[]]$Entries)
    $existing = @()
    if ($env:Path) {
        $existing = $env:Path -split ";"
    }
    $valid = @()
    foreach ($entry in $Entries) {
        if (-not [string]::IsNullOrWhiteSpace($entry) -and (Test-Path -LiteralPath $entry)) {
            $valid += $entry
        }
    }
    $env:Path = (@($valid + $existing) | Where-Object { $_ }) -join ";"
}

function Import-DotEnv {
    param([string]$Path)

    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

function Invoke-RepoModule {
    param(
        [string]$Module,
        [string[]]$Arguments = @()
    )

    $bootstrapPath = Join-Path $scriptDir "runtime\portable_bootstrap.py"
    & $pythonExe $bootstrapPath $Module $scriptDir @Arguments
    return $LASTEXITCODE
}

Set-Location $scriptDir

$pythonExe = Join-Path $scriptDir "runtime\python\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Can't find Python: $pythonExe"
}

Prepend-Path -Entries @(
    (Join-Path $scriptDir "tools\git\cmd"),
    (Join-Path $scriptDir "tools\git\bin"),
    (Join-Path $scriptDir "tools\git\usr\bin"),
    (Join-Path $scriptDir "tools\git\mingw64\bin")
)

$env:CLI_BRIDGE_SUPERVISOR = "1"
$env:WEB_ENABLED = "true"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"

Write-Host ("[INFO] Start dir: {0}" -f $scriptDir)
Write-Host ("[INFO] Start mode: {0}" -f $Mode)
Write-Host ("[INFO] Using Python: {0}" -f $pythonExe)

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Can't find .env: $envPath"
}

$migrationExitCode = Invoke-RepoModule -Module "bot.env_migration" -Arguments @("--env-path", $envPath)
if ($migrationExitCode -ne 0) {
    throw "Copy .env failed."
}
Import-DotEnv -Path $envPath
$env:WEB_ENABLED = "true"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"

while ($true) {
    $exitCode = Invoke-RepoModule -Module "bot"
    if ($exitCode -ne $restartExitCode) {
        exit $exitCode
    }
    Write-Host "[INFO] Restarting in 1 sec..."
    Start-Sleep -Seconds 1
}
'@
    Set-Content -LiteralPath (Join-Path $PackageRoot "start.ps1") -Value $startPs1 -Encoding UTF8

$bootstrapPy = @'
from __future__ import annotations

import importlib
import importlib.util
import runpy
import sys
import traceback
from pathlib import Path


def _is_user_python_path(path: str) -> bool:
    return "\\appdata\\roaming\\python\\" in path.lower()


def main() -> None:
    module = sys.argv[1]
    project_root = Path(sys.argv[2]).resolve()
    args = sys.argv[3:]
    python_root = project_root / "runtime" / "python"
    site_packages = python_root / "Lib" / "site-packages"
    stdlib = python_root / "Lib"
    python_zip = python_root / "python313.zip"

    preferred = [
        str(project_root),
        str(site_packages),
        str(stdlib),
        str(python_root),
        str(python_zip),
    ]
    rest = [
        path
        for path in sys.path
        if path and path not in preferred and not _is_user_python_path(path)
    ]
    sys.path[:] = preferred + rest
    importlib.invalidate_caches()
    _force_load_package(site_packages, "aiohttp")

    sys.argv = [module, *args]
    run_name = "_portable_smoke_" if module == "bot" and sys.argv and _smoke_import_only() else "__main__"
    try:
        runpy.run_module(module, run_name=run_name)
    except Exception:
        _write_debug_log(project_root)
        raise


def _smoke_import_only() -> bool:
    import os

    return os.environ.get("TCB_PORTABLE_SMOKE_IMPORT_ONLY") == "1"


def _force_load_package(site_packages: Path, package_name: str) -> None:
    init_file = site_packages / package_name / "__init__.py"
    if not init_file.exists():
        return

    for name in list(sys.modules):
        if name == package_name or name.startswith(f"{package_name}."):
            del sys.modules[name]

    spec = importlib.util.spec_from_file_location(
        package_name,
        init_file,
        submodule_search_locations=[str(init_file.parent)],
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)


def _write_debug_log(project_root: Path) -> None:
    log_path = project_root / "runtime" / "portable_bootstrap_debug.log"
    lines = ["sys.path:"]
    lines.extend(sys.path)
    for name in ("aiohttp", "aiohttp.client_exceptions", "aiohttp.http", "aiohttp.web"):
        spec = importlib.util.find_spec(name)
        lines.append(f"{name}: {spec!r}")
        lines.append(f"{name}.origin: {getattr(spec, 'origin', None)!r}")
        lines.append(f"{name}.locations: {list(getattr(spec, 'submodule_search_locations', []) or [])!r}")
    lines.append("traceback:")
    lines.append(traceback.format_exc())
    log_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
'@
    Set-Content -LiteralPath (Join-Path $PackageRoot "runtime\portable_bootstrap.py") -Value $bootstrapPy -Encoding ASCII

    $startBat = @'
@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Service exited with code: %EXIT_CODE%
    pause
)
exit /b %EXIT_CODE%
'@
    Set-Content -LiteralPath (Join-Path $PackageRoot "start.bat") -Value $startBat -Encoding ASCII

    $installPs1 = @'
Write-Host "[信息] 这是绿色版，无需安装。直接运行 start.bat。"
exit 0
'@
    Set-Content -LiteralPath (Join-Path $PackageRoot "install.ps1") -Value $installPs1 -Encoding UTF8

    $installBat = @'
@echo off
chcp 65001 >nul
echo [INFO] Portable build. No install is required. Run start.bat.
exit /b 0
'@
    Set-Content -LiteralPath (Join-Path $PackageRoot "install.bat") -Value $installBat -Encoding ASCII
}

function Write-PortableReadme {
    param(
        [string]$PackageRoot,
        [string]$Token,
        [string]$Version
    )

    $content = @"
Orbit Safe Claw Windows 绿色版

版本: $Version
WEB_API_TOKEN: $Token

使用:
1. 直接运行 start.bat
2. 浏览器打开 http://127.0.0.1:8765
3. 用上面的 WEB_API_TOKEN 登录

说明:
- 绿色包无需安装 Python / Node / Git
- 包内已带 Python、Git 和前端构建产物
- 不内置 AI CLI；请先在本机安装 codex / claude / kimi
- 使用前确认 codex --version / claude --version / kimi info 可运行
- 可在 Web 设置页或 .env 修改 CLI_TYPE / CLI_PATH
- 默认 WORKING_DIR=当前解压目录，可在设置页再改
"@
    Set-Content -LiteralPath (Join-Path $PackageRoot "PORTABLE-README.txt") -Value $content -Encoding UTF8
}

function Test-PortableBundle {
    param([string]$PackageRoot)

    Write-Step "校验绿色包"
    $pythonExe = Join-Path $PackageRoot "runtime\python\python.exe"
    $gitExe = Join-Path $PackageRoot "tools\git\cmd\git.exe"
    $envPath = Join-Path $PackageRoot ".env"
    $bootstrap = Join-Path $PackageRoot "runtime\portable_bootstrap.py"

    Invoke-CheckedCommand -FilePath $pythonExe -Arguments @(
        "-c",
        "import aiohttp, dotenv, yaml, qrcode, psutil, pypdf; import bot.main; print('portable-python-ok')"
    ) -FailureMessage "包内 Python import 校验失败" -WorkingDirectory $PackageRoot

    Invoke-CheckedCommand -FilePath $pythonExe -Arguments @(
        $bootstrap,
        "bot.env_migration",
        $PackageRoot,
        "--env-path",
        $envPath
    ) -FailureMessage "包内 env_migration 校验失败" -WorkingDirectory $PackageRoot

    $previousSmoke = $env:TCB_PORTABLE_SMOKE_IMPORT_ONLY
    $previousSkipElevate = $env:TCB_PORTABLE_SKIP_ELEVATE
    try {
        $env:TCB_PORTABLE_SMOKE_IMPORT_ONLY = "1"
        $env:TCB_PORTABLE_SKIP_ELEVATE = "1"
        Invoke-CheckedCommand -FilePath (Join-Path $PackageRoot "start.bat") -Arguments @() -FailureMessage "包内 start.bat smoke 校验失败" -WorkingDirectory $PackageRoot
    } finally {
        if ($null -eq $previousSmoke) {
            Remove-Item Env:TCB_PORTABLE_SMOKE_IMPORT_ONLY -ErrorAction SilentlyContinue
        } else {
            $env:TCB_PORTABLE_SMOKE_IMPORT_ONLY = $previousSmoke
        }
        if ($null -eq $previousSkipElevate) {
            Remove-Item Env:TCB_PORTABLE_SKIP_ELEVATE -ErrorAction SilentlyContinue
        } else {
            $env:TCB_PORTABLE_SKIP_ELEVATE = $previousSkipElevate
        }
    }

    Invoke-CheckedCommand -FilePath $gitExe -Arguments @("--version") -FailureMessage "包内 Git 校验失败" -WorkingDirectory $PackageRoot

    Invoke-CheckedCommand -FilePath $pythonExe -Arguments @(
        "-m", "pytest",
        "tests/test_docx_preview_plugin.py",
        "tests/test_pdf_preview_plugin.py",
        "-q"
    ) -FailureMessage "包内插件测试失败" -WorkingDirectory $PackageRoot
}

function New-ZipArchive {
    param(
        [string]$SourceDir,
        [string]$DestinationFile
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $DestinationFile) {
        Remove-Item -LiteralPath $DestinationFile -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $SourceDir,
        $DestinationFile,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}

function Write-DistributionMarker {
    param(
        [string]$Root,
        [string]$PackageKind,
        [string]$Platform,
        [string]$Version
    )

    $payload = [ordered]@{
        packageKind = $PackageKind
        platform = $Platform
        version = $Version
    } | ConvertTo-Json
    Set-Content -LiteralPath (Join-Path $Root ".distribution.json") -Value $payload -Encoding UTF8
}

try {
    $version = Get-AppVersion
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $packageName = if ([string]::IsNullOrWhiteSpace($PackageName)) {
        "{0}-windows-x64-portable-{1}-{2}" -f $script:PackageBaseName, $version, $stamp
    } else {
        $PackageName.Trim()
    }
    $packageRoot = Join-Path $script:StageRoot $packageName
    $artifactPath = if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
        Join-Path $script:ArtifactsRoot ($packageName + ".zip")
    } else {
        $ArtifactPath
    }
    $token = New-WebToken

    [void](New-Item -ItemType Directory -Force -Path $script:StageRoot, $script:ArtifactsRoot, $script:DownloadsRoot)
    Reset-Directory -Path $packageRoot

    if (-not $SkipFrontBuild) {
        Write-Step "构建前端"
        Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory $script:FrontDir
    }

    Copy-WorktreeFiles -DestinationRoot $packageRoot
    Install-EmbeddedPython -PackageRoot $packageRoot
    Install-PortableGit -PackageRoot $packageRoot -SourceGitRoot $GitRoot
    Write-PortableEnv -PackageRoot $packageRoot -Token $token
    Write-PortableScripts -PackageRoot $packageRoot
    Write-PortableReadme -PackageRoot $packageRoot -Token $token -Version $version
    Test-PortableBundle -PackageRoot $packageRoot
    Write-DistributionMarker -Root $packageRoot -PackageKind "portable" -Platform "windows-x64" -Version $version

    Write-Step "压缩绿色包"
    New-ZipArchive -SourceDir $packageRoot -DestinationFile $artifactPath

    Write-Host ""
    Write-Host ("[完成] 绿色包目录: {0}" -f $packageRoot) -ForegroundColor Green
    Write-Host ("[完成] ZIP: {0}" -f $artifactPath) -ForegroundColor Green
    Write-Host ("[完成] WEB_API_TOKEN: {0}" -f $token) -ForegroundColor Green
} catch {
    Write-Host ("[错误] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
