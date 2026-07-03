param(
    [ValidateSet("default", "web")]
    [string]$Mode = "default"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$envPath = Join-Path $scriptDir ".env"
$restartExitCode = 75
$startupStateDir = Join-Path $scriptDir ".tcb\startup"

function Write-Info {
    param([string]$Message)

    Write-Host ("[信息] {0}" -f $Message)
}

function Write-Warn {
    param([string]$Message)

    Write-Host ("[提示] {0}" -f $Message) -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)

    Write-Host ("[错误] {0}" -f $Message) -ForegroundColor Red
}

function Test-Truthy {
    param([string]$Value)

    if ($null -eq $Value) {
        return $false
    }

    return $Value.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $pattern = "^{0}=(.*)$" -f [regex]::Escape($Name)
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        if ($trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -match $pattern) {
            $value = $Matches[1].Trim()
            if (
                $value.Length -ge 2 -and
                (
                    ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                    ($value.StartsWith("'") -and $value.EndsWith("'"))
                )
            ) {
                return $value.Substring(1, $value.Length - 2)
            }

            return $value
        }
    }

    return $null
}

function Get-PythonRuntime {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand) {
        if ($pythonCommand.Path) {
            return [pscustomobject]@{
                Command   = $pythonCommand.Path
                Arguments = @()
            }
        }

        return [pscustomobject]@{
            Command   = $pythonCommand.Source
            Arguments = @()
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyCommand) {
        if ($pyCommand.Path) {
            return [pscustomobject]@{
                Command   = $pyCommand.Path
                Arguments = @("-3")
            }
        }

        return [pscustomobject]@{
            Command   = $pyCommand.Source
            Arguments = @("-3")
        }
    }

    return $null
}

function Get-ProjectVenvPythonPath {
    param([string]$RootDir)

    $venvDir = Join-Path $RootDir ".venv"
    $candidates = @(
        (Join-Path (Join-Path $venvDir "Scripts") "python.exe"),
        (Join-Path (Join-Path $venvDir "bin") "python")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $null
}

function New-PythonRuntime {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    return [pscustomobject]@{
        Command   = $Command
        Arguments = @($Arguments)
    }
}

function Ensure-ProjectPythonRuntime {
    param(
        [pscustomobject]$PythonRuntime,
        [string]$RootDir
    )

    $venvPythonPath = Get-ProjectVenvPythonPath -RootDir $RootDir
    if ($venvPythonPath) {
        return New-PythonRuntime -Command $venvPythonPath
    }

    if (Test-Truthy $env:TCB_STARTUP_USE_SYSTEM_PYTHON) {
        return $PythonRuntime
    }

    $venvDir = Join-Path $RootDir ".venv"
    Write-Info "未检测到 .venv，正在创建项目虚拟环境..."
    & $PythonRuntime.Command @($PythonRuntime.Arguments + @("-m", "venv", $venvDir))
    if ($LASTEXITCODE -ne 0) {
        throw "创建 .venv 失败。请先运行 install.ps1，或确认 Python venv 模块可用。"
    }

    $venvPythonPath = Get-ProjectVenvPythonPath -RootDir $RootDir
    if (-not $venvPythonPath) {
        throw "创建 .venv 后未找到 Python 解释器。"
    }

    return New-PythonRuntime -Command $venvPythonPath
}

function Ensure-Pip {
    param([pscustomobject]$PythonRuntime)

    & $PythonRuntime.Command @($PythonRuntime.Arguments + @("-m", "pip", "--version")) *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    & $PythonRuntime.Command @($PythonRuntime.Arguments + @("-m", "ensurepip", "--upgrade")) *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "当前 Python 无法使用 pip。请先运行 install.ps1 修复运行环境。"
    }
}

function Get-StartupPathsHash {
    param(
        [pscustomobject]$PythonRuntime,
        [string]$RootDir,
        [string[]]$RelativePaths
    )

    $hashScript = @'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
files: list[Path] = []
ignored_parts = {"node_modules", "dist", "test-results", "__pycache__"}

for raw_path in sys.argv[2:]:
    path = root / raw_path
    if not path.exists():
        continue
    if path.is_file():
        files.append(path)
        continue
    if path.is_dir():
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            try:
                rel_parts = child.relative_to(root).parts
            except ValueError:
                continue
            if any(part in ignored_parts for part in rel_parts):
                continue
            files.append(child)

digest = hashlib.sha256()
for file_path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
    rel_path = file_path.relative_to(root).as_posix()
    digest.update(rel_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(file_path.read_bytes())
    digest.update(b"\0")

print(digest.hexdigest())
'@

    $output = & $PythonRuntime.Command @($PythonRuntime.Arguments + @("-c", $hashScript, $RootDir) + $RelativePaths)
    if ($LASTEXITCODE -ne 0) {
        throw "计算启动依赖状态失败。"
    }

    $hashValue = [string]($output | Select-Object -Last 1)
    return $hashValue.Trim()
}

function Test-StartupStampMatches {
    param(
        [string]$StampPath,
        [string]$ExpectedHash
    )

    if (-not (Test-Path -LiteralPath $StampPath)) {
        return $false
    }

    $currentHash = (Get-Content -LiteralPath $StampPath -Raw).Trim()
    return $currentHash -eq $ExpectedHash
}

function Write-StartupStamp {
    param(
        [string]$StampPath,
        [string]$Value
    )

    $parentDir = Split-Path -Parent $StampPath
    if ($parentDir) {
        New-Item -ItemType Directory -Force -Path $parentDir | Out-Null
    }
    Set-Content -LiteralPath $StampPath -Value $Value -Encoding UTF8
}

function Get-NpmCommand {
    foreach ($name in @("npm.cmd", "npm")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            if ($command.Path) {
                return $command.Path
            }
            return $command.Source
        }
    }

    return $null
}

function Sync-PythonDependencies {
    param(
        [pscustomobject]$PythonRuntime,
        [string]$RootDir
    )

    if (Test-Truthy $env:TCB_STARTUP_SKIP_DEP_SYNC) {
        Write-Warn "已跳过启动依赖同步。"
        return $PythonRuntime
    }

    $requirementsPath = Join-Path $RootDir "requirements.txt"
    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        throw "未找到 requirements.txt，无法检查后端依赖。"
    }

    $runtime = Ensure-ProjectPythonRuntime -PythonRuntime $PythonRuntime -RootDir $RootDir
    $requirementsHash = Get-StartupPathsHash -PythonRuntime $runtime -RootDir $RootDir -RelativePaths @("requirements.txt")
    $stampPath = Join-Path $startupStateDir "python-requirements.sha256"

    if (
        (Test-StartupStampMatches -StampPath $stampPath -ExpectedHash $requirementsHash) -and
        -not (Test-Truthy $env:TCB_STARTUP_FORCE_DEP_INSTALL)
    ) {
        return $runtime
    }

    Write-Info "检测到后端依赖清单变化，正在安装 requirements.txt..."
    Ensure-Pip -PythonRuntime $runtime
    & $runtime.Command @($runtime.Arguments + @("-m", "pip", "install", "--upgrade", "pip"))
    if ($LASTEXITCODE -ne 0) {
        throw "升级 pip 失败。"
    }
    & $runtime.Command @($runtime.Arguments + @("-m", "pip", "install", "-r", $requirementsPath))
    if ($LASTEXITCODE -ne 0) {
        throw "安装后端依赖失败。"
    }
    Write-StartupStamp -StampPath $stampPath -Value $requirementsHash

    return $runtime
}

function Sync-FrontendAssets {
    param(
        [pscustomobject]$PythonRuntime,
        [string]$RootDir
    )

    if ((Test-Truthy $env:TCB_STARTUP_SKIP_DEP_SYNC) -or (Test-Truthy $env:TCB_STARTUP_SKIP_FRONTEND_BUILD)) {
        return
    }

    $frontPackagePath = Join-Path $RootDir "front\package.json"
    if (-not (Test-Path -LiteralPath $frontPackagePath)) {
        return
    }

    $frontendInputs = @(
        "front\package.json",
        "front\package-lock.json",
        "front\index.html",
        "front\vite.config.ts",
        "front\tsconfig.json",
        "front\src",
        "front\public",
        "scripts\build_web_frontend.bat"
    )
    $frontendHash = Get-StartupPathsHash -PythonRuntime $PythonRuntime -RootDir $RootDir -RelativePaths $frontendInputs
    $stampPath = Join-Path $startupStateDir "frontend-build-windows.sha256"
    $distIndex = Join-Path $RootDir "front\dist\index.html"

    if (
        (Test-StartupStampMatches -StampPath $stampPath -ExpectedHash $frontendHash) -and
        (Test-Path -LiteralPath $distIndex) -and
        -not (Test-Truthy $env:TCB_STARTUP_FORCE_FRONTEND_BUILD)
    ) {
        return
    }

    $npmCommand = Get-NpmCommand
    if (-not $npmCommand) {
        throw "检测到前端资源需要重建，但未找到 npm。请先运行 install.ps1 安装 Node.js 依赖。"
    }

    Write-Info "检测到前端源码或依赖变化，正在安装并构建前端..."
    $buildScript = Join-Path $RootDir "scripts\build_web_frontend.bat"
    if (($env:OS -eq "Windows_NT") -and (Test-Path -LiteralPath $buildScript)) {
        & $buildScript
        if ($LASTEXITCODE -ne 0) {
            throw "前端构建失败。"
        }
    } else {
        Push-Location (Join-Path $RootDir "front")
        try {
            & $npmCommand install
            if ($LASTEXITCODE -ne 0) {
                throw "安装前端依赖失败。"
            }
            & $npmCommand run build
            if ($LASTEXITCODE -ne 0) {
                throw "前端构建失败。"
            }
        } finally {
            Pop-Location
        }
    }

    $frontendHash = Get-StartupPathsHash -PythonRuntime $PythonRuntime -RootDir $RootDir -RelativePaths $frontendInputs
    Write-StartupStamp -StampPath $stampPath -Value $frontendHash
}

function Sync-RuntimeDependencies {
    param(
        [pscustomobject]$PythonRuntime,
        [string]$RootDir
    )

    $runtime = Sync-PythonDependencies -PythonRuntime $PythonRuntime -RootDir $RootDir
    Sync-FrontendAssets -PythonRuntime $runtime -RootDir $RootDir
    return $runtime
}

function Show-TunnelHint {
    param([string]$Path)

    $webPublicUrl = Get-DotEnvValue -Path $Path -Name "WEB_PUBLIC_URL"
    $webTunnelMode = Get-DotEnvValue -Path $Path -Name "WEB_TUNNEL_MODE"
    $fixedForwardEnabled = Get-DotEnvValue -Path $Path -Name "WEB_FIXED_PUBLIC_FORWARD_ENABLED"
    $fixedForwardUrl = Get-DotEnvValue -Path $Path -Name "WEB_FIXED_PUBLIC_FORWARD_URL"
    $fixedForwardEnabledValue = if ($null -eq $fixedForwardEnabled) { "" } else { $fixedForwardEnabled.Trim().ToLowerInvariant() }
    $hasFixedForward = (
        $fixedForwardEnabledValue -in @("1", "true", "yes", "on") -and
        -not [string]::IsNullOrWhiteSpace($fixedForwardUrl)
    )

    if (
        [string]::IsNullOrWhiteSpace($webPublicUrl) -and
        -not $hasFixedForward -and
        (
            [string]::IsNullOrWhiteSpace($webTunnelMode) -or
            $webTunnelMode -eq "disabled"
        )
    ) {
        Write-Warn "当前未配置公网访问。"
        Write-Host "如需外网访问，可在 .env 中设置 WEB_TUNNEL_MODE=cloudflare_quick，或配置反向代理后填写 WEB_PUBLIC_URL。"
    }
}

function Ensure-EnvFile {
    param(
        [string]$Path,
        [string]$RootDir
    )

    if (Test-Path -LiteralPath $Path) {
        return
    }

    $installBatPath = Join-Path $RootDir "install.bat"
    if (-not (Test-Path -LiteralPath $installBatPath)) {
        throw "未找到 .env，且 install.bat 不存在。"
    }

    Write-Warn "未找到 .env，正在运行 install.bat 生成配置。"

    $previousNoPause = $env:CLI_BRIDGE_INSTALLER_NO_PAUSE
    $installExitCode = 1

    try {
        $env:CLI_BRIDGE_INSTALLER_NO_PAUSE = "1"
        & $installBatPath
        $installExitCode = $LASTEXITCODE
    } finally {
        if ($null -ne $previousNoPause) {
            $env:CLI_BRIDGE_INSTALLER_NO_PAUSE = $previousNoPause
        } else {
            Remove-Item Env:CLI_BRIDGE_INSTALLER_NO_PAUSE -ErrorAction SilentlyContinue
        }
    }

    if ($installExitCode -ne 0) {
        throw ("install.bat 执行失败，退出码: {0}" -f $installExitCode)
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "install.bat 执行完成，但仍未生成 .env。"
    }
}

try {
    Set-Location $scriptDir

    Ensure-EnvFile -Path $envPath -RootDir $scriptDir

    $pythonRuntime = Get-PythonRuntime
    if (-not $pythonRuntime) {
        Write-Fail "未找到 python 或 py -3，请先安装 Python 并加入 PATH。"
        exit 127
    }

    $env:CLI_BRIDGE_SUPERVISOR = "1"
    $env:WEB_ENABLED = "true"

    Write-Info ("启动目录: {0}" -f $scriptDir)
    Write-Info ("启动模式: {0}" -f $Mode)

    $pythonRuntime = Sync-PythonDependencies -PythonRuntime $pythonRuntime -RootDir $scriptDir

    & $pythonRuntime.Command @($pythonRuntime.Arguments + @("-m", "bot.env_migration", "--env-path", $envPath))
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "迁移旧版 .env 配置失败。"
        exit $LASTEXITCODE
    }

    Write-Info "正在检查并应用待更新版本..."
    & $pythonRuntime.Command @($pythonRuntime.Arguments + @("-m", "bot.updater", "apply-pending", "--repo-root", $scriptDir))
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "应用待更新版本失败，请检查 .web_admin_settings.json 和更新包缓存。"
        Write-Warn "更新未成功应用，继续启动当前程序。"
    }

    $pythonRuntime = Sync-RuntimeDependencies -PythonRuntime $pythonRuntime -RootDir $scriptDir

    Write-Info "正在迁移运行数据..."
    & $pythonRuntime.Command @($pythonRuntime.Arguments + @("-m", "bot.migrations", "run", "--repo-root", $scriptDir))
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "运行数据迁移失败。"
        exit $LASTEXITCODE
    }

    Show-TunnelHint -Path $envPath

    while ($true) {
        & $pythonRuntime.Command @($pythonRuntime.Arguments + @("-m", "bot"))
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne $restartExitCode) {
            exit $exitCode
        }

        Write-Info "收到重启请求，1 秒后重新启动。"
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
