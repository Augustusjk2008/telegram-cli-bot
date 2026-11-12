param(
    [string]$GitRoot = "C:\Program Files\Git",
    [string]$PackageName = "",
    [string]$ArtifactPath = "",
    [switch]$SkipFrontBuild,
    [switch]$KeepStage
)

$ErrorActionPreference = "Stop"

$script:Utf8BomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $true
$script:Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false

$script:PortableRoot = $PSScriptRoot
$script:ReleaseLocalRoot = Split-Path -Parent $script:PortableRoot
$script:RepoRoot = Split-Path -Parent $script:ReleaseLocalRoot
$script:StageRoot = Join-Path $script:PortableRoot "stage"
$script:ArtifactsRoot = Join-Path $script:PortableRoot "artifacts"
$script:DownloadsRoot = Join-Path $script:PortableRoot "downloads"
$script:FrontDir = Join-Path $script:RepoRoot "front"
$script:VersionFile = Join-Path $script:RepoRoot "VERSION"
$script:PackageBaseName = "orbit-safe-claw"
$script:NodeVersion = "22.17.1"
$script:RequiredReleaseLegalFiles = @(
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "CONTRIBUTING.md",
    "front/dist/THIRD_PARTY_LICENSES.txt"
)
$script:RequiredThemeFiles = @(
    "bot/web/theme_presets.json",
    "bot/web/theme_illustrations.json"
)

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

function Invoke-FrontDistAssetCheck {
    Write-Step "校验前端构建资源路径"
    Invoke-CheckedCommand -FilePath "node" -Arguments @("scripts/verify-build-assets.mjs") -FailureMessage "前端构建资源路径校验失败" -WorkingDirectory $script:FrontDir
}

function Invoke-PortableFrontBuild {
    Write-Step "构建前端（绿色版根路径资源）"
    $originalValue = [Environment]::GetEnvironmentVariable("TCB_FRONT_BUILD_ROOT_BASE", "Process")
    try {
        [Environment]::SetEnvironmentVariable("TCB_FRONT_BUILD_ROOT_BASE", "1", "Process")
        Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory $script:FrontDir
    } finally {
        [Environment]::SetEnvironmentVariable("TCB_FRONT_BUILD_ROOT_BASE", $originalValue, "Process")
    }
    Invoke-FrontDistAssetCheck
}

function Export-ReleaseAnnouncements {
    param([string]$DestinationRoot)

    $relativePath = ".web_announcements.json"
    $destinationPath = Join-Path $DestinationRoot $relativePath
    $runtimePath = (& python -c "from bot.runtime_paths import get_announcements_content_path; print(get_announcements_content_path())").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "读取运行态公告路径失败。"
    }
    if ([string]::IsNullOrWhiteSpace($runtimePath) -or -not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        Write-Info "未找到运行态公告内容，沿用仓库内 .web_announcements.json。"
        return
    }
    Copy-Item -LiteralPath $runtimePath -Destination $destinationPath -Force
    Write-Info ("已导出公告内容到绿色包: {0}" -f $relativePath)
}

function Get-AppVersion {
    if (Test-Path -LiteralPath $script:VersionFile) {
        return (Get-Content -LiteralPath $script:VersionFile -Raw -Encoding UTF8).Trim()
    }
    return "dev"
}

function Reset-Directory {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    [void](New-Item -ItemType Directory -Path $Path -Force)
}

function Remove-PortableStageDirectory {
    param([string]$Path)

    try {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            Write-Info ("已清理绿色包临时目录: {0}" -f $Path)
        }
    } catch {
        Write-Warning ("清理绿色包临时目录失败，已保留 {0}: {1}" -f $Path, $_.Exception.Message)
    }
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

function Assert-ReleaseLegalFilesInStage {
    param([string]$StageDir)

    $missing = @(
        foreach ($relativePath in $script:RequiredReleaseLegalFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $StageDir $relativePath) -PathType Leaf)) {
                $relativePath
            }
        }
    )
    if ($missing.Count -gt 0) {
        throw "发布暂存区缺少必需法律文件（请确认文件已由 Git 跟踪）: $($missing -join ', ')"
    }
}

function Assert-ThemeFilesInStage {
    param([string]$StageDir)

    $missing = @(
        foreach ($relativePath in $script:RequiredThemeFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $StageDir $relativePath) -PathType Leaf)) {
                $relativePath
            }
        }
    )
    if ($missing.Count -gt 0) {
        throw "绿色包暂存区缺少预置主题文件: $($missing -join ', ')"
    }
}

function Assert-PortableRuntimeLicenseFiles {
    param([string]$PackageRoot)

    $requiredFiles = @(
        "runtime/python/LICENSE.txt",
        "runtime/node/LICENSE",
        "tools/git/LICENSE.txt"
    )
    $missing = @(
        foreach ($relativePath in $requiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $relativePath) -PathType Leaf)) {
                $relativePath
            }
        }
    )
    if ($missing.Count -gt 0) {
        throw "Windows 绿色包缺少捆绑运行时许可证文件: $($missing -join ', ')"
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

    Assert-ThemeFilesInStage -StageDir $DestinationRoot
    Export-ReleaseAnnouncements -DestinationRoot $DestinationRoot
    Assert-ReleaseLegalFilesInStage -StageDir $DestinationRoot
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

function Install-EmbeddedNode {
    param([string]$PackageRoot)

    Write-Step "准备包内 Node.js"
    [void](New-Item -ItemType Directory -Path $script:DownloadsRoot -Force)
    $fileName = "node-v$($script:NodeVersion)-win-x64.zip"
    $url = "https://nodejs.org/dist/v$($script:NodeVersion)/$fileName"
    $zipPath = Join-Path $script:DownloadsRoot $fileName
    if (-not (Test-Path -LiteralPath $zipPath)) {
        Write-Info ("下载 Node.js: {0}" -f $url)
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zipPath
    }

    $nodeRoot = Join-Path $PackageRoot "runtime\node"
    $extractRoot = Join-Path $script:DownloadsRoot "node-extract"
    Reset-Directory -Path $nodeRoot
    Reset-Directory -Path $extractRoot
    try {
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force
        $expanded = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
        if (-not $expanded) {
            throw "Node.js 压缩包结构无效。"
        }
        Copy-Item -Path (Join-Path $expanded.FullName "*") -Destination $nodeRoot -Recurse -Force
    } finally {
        if (Test-Path -LiteralPath $extractRoot) {
            Remove-Item -LiteralPath $extractRoot -Recurse -Force
        }
    }
}

function Write-PortableEnv {
    param([string]$PackageRoot)

    Write-Step "写入包内 .env"
    $content = @"
CLI_TYPE=codex
CLI_PATH=codex
WORKING_DIR=.
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8765
WEB_API_TOKEN=
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
    [System.IO.File]::WriteAllText((Join-Path $PackageRoot ".env"), $content, $script:Utf8NoBomEncoding)
}

function Write-PortableScripts {
    param([string]$PackageRoot)

    Write-Step "写入绿色版启动脚本"
    $startPs1 = @'
param(
    [ValidateSet("default", "web", "service")]
    [string]$Mode = "default",

    [Parameter(DontShow = $true)]
    [switch]$ServiceProcess
)

$ErrorActionPreference = "Stop"
$script:Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$envPath = Join-Path $scriptDir ".env"
$restartExitCode = 75

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator) -and -not $ServiceProcess -and $env:TCB_PORTABLE_SKIP_ELEVATE -ne "1") {
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

    $env:TCB_PORTABLE_DOTENV_PATH = $Path
    $python = @(
        "from __future__ import annotations",
        "",
        "import os",
        "from pathlib import Path",
        "",
        "from dotenv import dotenv_values",
        "",
        "path = Path(os.environ['TCB_PORTABLE_DOTENV_PATH'])",
        "for key, value in dotenv_values(path).items():",
        "    if value is not None:",
        "        print(f'{key}={value}')"
    ) -join "`n"
    try {
        $output = & $pythonExe -c $python
        if ($LASTEXITCODE -ne 0) {
            throw "解析 .env 失败。"
        }
    } finally {
        Remove-Item Env:TCB_PORTABLE_DOTENV_PATH -ErrorAction SilentlyContinue
    }
    foreach ($line in $output) {
        if ($line -notmatch "^(?<key>[A-Za-z_][A-Za-z0-9_]*)=(?<value>.*)$") {
            continue
        }
        [Environment]::SetEnvironmentVariable($Matches["key"], $Matches["value"], "Process")
    }
}

function New-PortableWebToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([Convert]::ToBase64String($bytes)).TrimEnd("=") -replace "\+", "-" -replace "/", "_"
}

function Ensure-PortableWebToken {
    param([string]$Path)

    if ($env:TCB_PORTABLE_SMOKE_IMPORT_ONLY -eq "1") {
        return
    }

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    }
    $tokenIndex = -1
    $currentToken = ""
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^\s*WEB_API_TOKEN\s*=\s*(?<value>.*)$") {
            $tokenIndex = $index
            $currentToken = $Matches["value"].Trim()
            break
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($currentToken) -and $currentToken -ne "__GENERATE_ON_FIRST_START__") {
        return
    }
    $token = New-PortableWebToken
    if ($tokenIndex -ge 0) {
        $lines[$tokenIndex] = "WEB_API_TOKEN=$token"
    } else {
        $lines += "WEB_API_TOKEN=$token"
    }
    [System.IO.File]::WriteAllLines($Path, [string[]]$lines, $script:Utf8NoBomEncoding)
}

function Set-PortableRuntimeEnv {
    param([string]$PackageRoot)

    $env:WEB_ENABLED = "true"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONNOUSERSITE = "1"
    $env:TCB_PORTABLE_ROOT = $PackageRoot
    $portableDataRoot = Join-Path $PackageRoot "data\orbit-safe-claw"
    $portableLocator = Join-Path $PackageRoot ".tcb\storage.json"
    if (Test-Path -LiteralPath $portableLocator -PathType Leaf) {
        Remove-Item Env:TCB_DATA_DIR -ErrorAction SilentlyContinue
    } else {
        $env:TCB_DATA_DIR = $portableDataRoot
    }
    $env:TCB_CLUSTER_MCP_CONFIG = Join-Path $PackageRoot ".tcb\cluster-mcp\config.json"
}

function Invoke-RepoModule {
    param(
        [string]$Module,
        [string[]]$Arguments = @()
    )

    $bootstrapPath = Join-Path $scriptDir "runtime\portable_bootstrap.py"
    & $pythonExe $bootstrapPath $Module $scriptDir @Arguments | Out-Host
    return [int]$LASTEXITCODE
}

Set-Location $scriptDir

$pythonExe = Join-Path $scriptDir "runtime\python\python.exe"

Prepend-Path -Entries @(
    (Join-Path $scriptDir "runtime\node"),
    (Join-Path $scriptDir "tools\git\cmd"),
    (Join-Path $scriptDir "tools\git\bin"),
    (Join-Path $scriptDir "tools\git\usr\bin"),
    (Join-Path $scriptDir "tools\git\mingw64\bin")
)

$env:CLI_BRIDGE_SUPERVISOR = "1"
Set-PortableRuntimeEnv -PackageRoot $scriptDir

$cachedLauncherPath = Join-Path $scriptDir ".tcb/startup/update-launcher.json"
if (Test-Path -LiteralPath $cachedLauncherPath) {
$cachedLauncher = Get-Content -Raw -Encoding UTF8 -LiteralPath $cachedLauncherPath | ConvertFrom-Json
    if (Test-Path -LiteralPath $cachedLauncher.state_file) {
        $cachedState = Get-Content -Raw -Encoding UTF8 -LiteralPath $cachedLauncher.state_file | ConvertFrom-Json
        if ($cachedState.job.phase -in @("applying", "awaiting_health", "rolling_back", "recovery_required")) {
            & $cachedLauncher.control_python_executable $cachedLauncher.runner_path supervise --repo-root $scriptDir --state-file $cachedLauncher.state_file --python $cachedLauncher.python_executable
            exit $LASTEXITCODE
        }
    }
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Can't find Python: $pythonExe"
}

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
Ensure-PortableWebToken -Path $envPath
Import-DotEnv -Path $envPath
if ($Mode -eq "service") {
    $env:CLI_BRIDGE_SERVICE_MODE = "1"
    if ([string]::IsNullOrWhiteSpace($env:WEB_AUTO_OPEN_BROWSER)) {
        $env:WEB_AUTO_OPEN_BROWSER = "false"
    }
    if ([string]::IsNullOrWhiteSpace($env:TCB_KEEP_AWAKE)) {
        $env:TCB_KEEP_AWAKE = "false"
    }
}
Set-PortableRuntimeEnv -PackageRoot $scriptDir

if ($env:TCB_PORTABLE_SMOKE_IMPORT_ONLY -eq "1") {
    exit (Invoke-RepoModule -Module "bot")
}
$env:CLI_BRIDGE_UPDATE_PROTOCOL = "1"
$launcherJson = & $pythonExe (Join-Path $scriptDir "scripts\update_runner.py") launcher-info --repo-root $scriptDir
if ($LASTEXITCODE -ne 0) { throw "Cannot prepare the independent update launcher." }
$launcher = ($launcherJson -join "`n") | ConvertFrom-Json
$env:CLI_BRIDGE_UPDATE_STATE_FILE = $launcher.state_file
& $launcher.control_python_executable $launcher.runner_path supervise --repo-root $scriptDir --state-file $launcher.state_file --python $launcher.python_executable
exit $LASTEXITCODE

'@
    $startPs1 = $startPs1 -replace "`r?`n", "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $PackageRoot "start.ps1"), $startPs1, $script:Utf8BomEncoding)

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
    $installPs1 = $installPs1 -replace "`r?`n", "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $PackageRoot "install.ps1"), $installPs1, $script:Utf8BomEncoding)

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
        [string]$Version
    )

    $content = @"
Orbit Safe Claw Windows 绿色版

版本: $Version

使用:
1. 直接运行 start.bat
2. 浏览器打开 http://127.0.0.1:8765
3. 使用 .env 内的 WEB_API_TOKEN 登录；首次启动会自动生成并写入本机 .env

说明:
- 绿色包无需安装 Python / Node / Git
- 登录口令仅保存在本机解压目录的 .env
- 包内已带 Python、Node 22、Git 和前端构建产物
- 请安装并配置所需的 Codex、Claude、Antigravity 或 DeepSeek Harness CLI
- 可在 Web 设置页或 .env 修改 CLI_TYPE / CLI_PATH
- 默认 WORKING_DIR=当前解压目录，可在设置页再改
"@
    Set-Content -LiteralPath (Join-Path $PackageRoot "PORTABLE-README.txt") -Value $content -Encoding UTF8
}

function Test-PortableBundle {
    param([string]$PackageRoot)

    Write-Step "校验绿色包"
    $pythonExe = Join-Path $PackageRoot "runtime\python\python.exe"
    $nodeExe = Join-Path $PackageRoot "runtime\node\node.exe"
    $gitExe = Join-Path $PackageRoot "tools\git\cmd\git.exe"
    $envPath = Join-Path $PackageRoot ".env"
    $bootstrap = Join-Path $PackageRoot "runtime\portable_bootstrap.py"

    Invoke-CheckedCommand -FilePath $nodeExe -Arguments @("--version") -FailureMessage "包内 Node 校验失败" -WorkingDirectory $PackageRoot

    Invoke-CheckedCommand -FilePath $pythonExe -Arguments @(
        "-c",
        "import aiohttp, dotenv, qrcode, psutil, pypdf; import bot.main; print('portable-python-ok')"
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

    $previousReleaseCommit = [Environment]::GetEnvironmentVariable("TCB_RELEASE_SOURCE_COMMIT", "Process")
    $previousReleaseFingerprint = [Environment]::GetEnvironmentVariable("TCB_RELEASE_SOURCE_FINGERPRINT", "Process")
    try {
        Remove-Item Env:TCB_RELEASE_SOURCE_COMMIT -ErrorAction SilentlyContinue
        Remove-Item Env:TCB_RELEASE_SOURCE_FINGERPRINT -ErrorAction SilentlyContinue
        Invoke-CheckedCommand -FilePath $pythonExe -Arguments @(
            "-m", "pytest",
            "tests",
            "examples/plugins",
            "-q"
        ) -FailureMessage "包内插件测试失败" -WorkingDirectory $PackageRoot
    } finally {
        if ($null -eq $previousReleaseCommit) {
            Remove-Item Env:TCB_RELEASE_SOURCE_COMMIT -ErrorAction SilentlyContinue
        } else {
            $env:TCB_RELEASE_SOURCE_COMMIT = $previousReleaseCommit
        }
        if ($null -eq $previousReleaseFingerprint) {
            Remove-Item Env:TCB_RELEASE_SOURCE_FINGERPRINT -ErrorAction SilentlyContinue
        } else {
            $env:TCB_RELEASE_SOURCE_FINGERPRINT = $previousReleaseFingerprint
        }
    }
}

function New-ZipArchive {
    param(
        [string]$SourceDir,
        [string]$DestinationFile
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationDir = Split-Path -Parent $DestinationFile
    if ($destinationDir) {
        [void](New-Item -ItemType Directory -Path $destinationDir -Force)
    }
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
        updateProtocol = 1
        architecture = "x64"
    } | ConvertTo-Json
    Set-Content -LiteralPath (Join-Path $Root ".distribution.json") -Value $payload -Encoding UTF8
    Invoke-CheckedCommand -FilePath "python" -Arguments @(
        (Join-Path $script:RepoRoot "scripts/update_package.py"), "create",
        "--root", $Root, "--source-root", $script:RepoRoot
    ) -FailureMessage "生成绿色版更新清单失败"
}

try {
    $identityArguments = @((Join-Path $script:RepoRoot "scripts/update_package.py"), "identity", "--source-root", $script:RepoRoot)
    if ($env:TCB_RELEASE_SOURCE_COMMIT) { $identityArguments += "--verify" }
    $identityJson = & python @identityArguments
    if ($LASTEXITCODE -ne 0) { throw "无法固定绿色版构建源码身份。" }
    $identity = ($identityJson -join "`n") | ConvertFrom-Json
    $env:TCB_RELEASE_SOURCE_COMMIT = $identity.commit
    $env:TCB_RELEASE_SOURCE_FINGERPRINT = $identity.fingerprint
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
    [void](New-Item -ItemType Directory -Force -Path $script:StageRoot, $script:ArtifactsRoot, $script:DownloadsRoot)
    Reset-Directory -Path $packageRoot

    if (-not $SkipFrontBuild) {
        Invoke-PortableFrontBuild
    } else {
        Invoke-FrontDistAssetCheck
    }

    Copy-WorktreeFiles -DestinationRoot $packageRoot
    Install-EmbeddedPython -PackageRoot $packageRoot
    Install-PortableGit -PackageRoot $packageRoot -SourceGitRoot $GitRoot
    Install-EmbeddedNode -PackageRoot $packageRoot
    Write-PortableEnv -PackageRoot $packageRoot
    Write-PortableScripts -PackageRoot $packageRoot
    Write-PortableReadme -PackageRoot $packageRoot -Version $version
    Assert-PortableRuntimeLicenseFiles -PackageRoot $packageRoot
    Test-PortableBundle -PackageRoot $packageRoot
    Write-DistributionMarker -Root $packageRoot -PackageKind "portable" -Platform "windows-x64" -Version $version

    Write-Step "压缩绿色包"
    New-ZipArchive -SourceDir $packageRoot -DestinationFile $artifactPath

    if (-not $KeepStage) {
        Remove-PortableStageDirectory -Path $packageRoot
    }

    Write-Host ""
    if (Test-Path -LiteralPath $packageRoot) {
        Write-Host ("[完成] 绿色包目录: {0}" -f $packageRoot) -ForegroundColor Green
    }
    Write-Host ("[完成] ZIP: {0}" -f $artifactPath) -ForegroundColor Green
} catch {
    Write-Host ("[错误] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
