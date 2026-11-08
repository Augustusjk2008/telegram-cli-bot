[CmdletBinding()]
param(
    [string]$Repository = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)),
    [string]$TaskName = ""
)

$ErrorActionPreference = "Stop"
$repositoryPath = (Resolve-Path -LiteralPath $Repository).Path

function Get-DefaultTaskName {
    param([string]$Root)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant())
    $digest = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    $suffix = ([BitConverter]::ToString($digest) -replace "-", "").Substring(0, 12)
    return "OrbitSafeClaw-$suffix"
}

function Get-AppDataRoot {
    $locator = Join-Path (Join-Path $HOME ".tcb") "storage.json"
    if (Test-Path -LiteralPath $locator) {
        try {
            $payload = Get-Content -Raw -LiteralPath $locator | ConvertFrom-Json
            if ($payload.appDataRoot) { return [string]$payload.appDataRoot }
            if ($payload.targetRoot) { return (Join-Path ([string]$payload.targetRoot) "orbit-safe-claw") }
        } catch {
            # Fall through to the legacy location; status must remain readable.
        }
    }
    if ($env:TCB_DATA_DIR) { return $env:TCB_DATA_DIR }
    return (Join-Path (Join-Path $HOME ".tcb") "orbit-safe-claw")
}

if ([string]::IsNullOrWhiteSpace($TaskName)) {
    $TaskName = Get-DefaultTaskName -Root $repositoryPath
}
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$info = $null
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
}

$updatePhase = ""
$launcherPath = Join-Path $repositoryPath ".tcb\startup\update-launcher.json"
if (Test-Path -LiteralPath $launcherPath) {
    try {
        $launcher = Get-Content -Raw -LiteralPath $launcherPath | ConvertFrom-Json
        if ($launcher.state_file -and (Test-Path -LiteralPath $launcher.state_file)) {
            $state = Get-Content -Raw -LiteralPath $launcher.state_file | ConvertFrom-Json
            $updatePhase = [string]$state.job.phase
        }
    } catch {
        $updatePhase = "unreadable"
    }
}

$healthOk = $false
$healthReady = $false
$healthUrl = ""
$runtimeState = Join-Path (Join-Path (Get-AppDataRoot) "web") "runtime_state.json"
if (Test-Path -LiteralPath $runtimeState) {
    try {
        $runtime = Get-Content -Raw -LiteralPath $runtimeState | ConvertFrom-Json
        $healthHost = if ($runtime.host -eq "0.0.0.0") { "127.0.0.1" } elseif ($runtime.host -eq "::") { "::1" } else { [string]$runtime.host }
        if ($healthHost.Contains(":") -and -not $healthHost.StartsWith("[")) {
            $healthHost = "[$healthHost]"
        }
        $healthUrl = "http://{0}:{1}/api/health" -f $healthHost, [int]$runtime.actual_port
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
        $healthOk = $health.ok -eq $true
        $healthReady = $health.ready -eq $true
    } catch {
        $healthOk = $false
        $healthReady = $false
    }
}

$serviceLogPath = if ($env:TCB_SERVICE_LOG_PATH) {
    $env:TCB_SERVICE_LOG_PATH
} else {
    Join-Path (Join-Path (Get-AppDataRoot) "logs") "orbit-safe-claw-service.log"
}

[ordered]@{
    TaskName = $TaskName
    Registered = [bool]$task
    State = if ($task) { [string]$task.State } else { "NotFound" }
    LastRunTime = if ($info) { $info.LastRunTime } else { $null }
    LastTaskResult = if ($info) { $info.LastTaskResult } else { $null }
    UpdatePhase = $updatePhase
    HealthOk = $healthOk
    HealthReady = $healthReady
    HealthUrl = $healthUrl
    ServiceLogPath = $serviceLogPath
} | ConvertTo-Json -Depth 4
