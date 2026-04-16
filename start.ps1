param(
    [ValidateSet("default", "web")]
    [string]$Mode = "default"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$envPath = Join-Path $scriptDir ".env"
$restartExitCode = 75

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

function Show-TunnelHint {
    param([string]$Path)

    $webPublicUrl = Get-DotEnvValue -Path $Path -Name "WEB_PUBLIC_URL"
    $webTunnelMode = Get-DotEnvValue -Path $Path -Name "WEB_TUNNEL_MODE"

    if (
        [string]::IsNullOrWhiteSpace($webPublicUrl) -and
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
