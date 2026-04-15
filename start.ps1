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

try {
    Set-Location $scriptDir

    if (-not (Test-Path -LiteralPath $envPath)) {
        Write-Fail "未找到 .env，请先运行 install.bat 生成配置。"
        exit 1
    }

    $pythonRuntime = Get-PythonRuntime
    if (-not $pythonRuntime) {
        Write-Fail "未找到 python 或 py -3，请先安装 Python 并加入 PATH。"
        exit 127
    }

    $env:CLI_BRIDGE_SUPERVISOR = "1"
    $env:WEB_ENABLED = "true"

    Write-Info ("启动目录: {0}" -f $scriptDir)
    Write-Info ("启动模式: {0}" -f $Mode)

    & $pythonRuntime.Command @($pythonRuntime.Arguments + @("-m", "bot.updater", "apply-pending", "--repo-root", $scriptDir))
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "应用待更新版本失败，请检查 .web_admin_settings.json 和更新包缓存。"
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
