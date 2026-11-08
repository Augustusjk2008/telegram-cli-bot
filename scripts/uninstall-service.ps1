[CmdletBinding()]
param(
    [string]$Repository = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)),
    [string]$TaskName = "",
    [switch]$WhatIf
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

if ([string]::IsNullOrWhiteSpace($TaskName)) {
    $TaskName = Get-DefaultTaskName -Root $repositoryPath
}
$exists = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($WhatIf) {
    [ordered]@{ TaskName = $TaskName; Exists = [bool]$exists; Action = "Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:false" } |
        ConvertTo-Json -Depth 3
    return
}
if (-not $exists) {
    Write-Output "未找到 Orbit Safe Claw 任务：$TaskName"
    return
}
if ([string]$exists.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(15)
    $current = $exists
    do {
        Start-Sleep -Milliseconds 250
        $current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $current -or [string]$current.State -ne "Running") { break }
    } while ((Get-Date) -lt $deadline)
    if ($null -ne $current -and [string]$current.State -eq "Running") {
        throw "任务仍在运行，已停止删除以避免遗留宿主进程：$TaskName"
    }
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "已删除 Orbit Safe Claw 后台任务：$TaskName"
