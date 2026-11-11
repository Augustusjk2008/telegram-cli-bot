[CmdletBinding()]
param(
    [string]$Repository = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)),
    [string]$TaskName = "",
    [string]$User = "",
    [ValidateSet("Logon", "Startup")]
    [string]$TriggerType = "Logon",
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
if ([string]::IsNullOrWhiteSpace($User)) {
    $User = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
}
if ([string]::IsNullOrWhiteSpace($User)) {
    throw "无法确定运行账户，请使用 -User 指定拥有 CLI 凭据的用户。"
}

$startScript = Join-Path $repositoryPath "start.ps1"
if (-not (Test-Path -LiteralPath $startScript)) {
    throw "未找到启动脚本：$startScript"
}
$powerShellCommand = Get-Command powershell.exe -ErrorAction Stop
$powerShell = if ($powerShellCommand.Path) { $powerShellCommand.Path } else { $powerShellCommand.Source }
$escapedScript = '"' + $startScript.Replace('"', '\"') + '"'
$actionArguments = "-NoProfile -ExecutionPolicy Bypass -File $escapedScript -ServiceProcess -Mode service"
$trigger = if ($TriggerType -eq "Startup") {
    New-ScheduledTaskTrigger -AtStartup
} else {
    New-ScheduledTaskTrigger -AtLogOn -User $User
}
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $actionArguments -WorkingDirectory $repositoryPath
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
$logonType = if ($TriggerType -eq "Startup") { "S4U" } else { "InteractiveToken" }
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType $logonType -RunLevel Highest

$plan = [ordered]@{
    TaskName = $TaskName
    User = $User
    Trigger = $TriggerType
    Repository = $repositoryPath
    Action = "$powerShell $actionArguments"
    RestartCount = 3
    RestartDelay = "00:01:00"
    LogonType = $logonType
}
if ($WhatIf) {
    Write-Output (($plan | ConvertTo-Json -Depth 4))
    return
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Orbit Safe Claw background service" -Force | Out-Null
if ($existing) {
    Write-Output "已更新现有 Orbit Safe Claw 任务（同一任务名不会创建重复实例）：$TaskName"
} else {
    Write-Output "已注册 Orbit Safe Claw 后台任务：$TaskName"
}
Write-Output "运行账户：$User；该账户必须拥有 Codex、Claude、Antigravity、DeepSeek Harness 和 Telegram 凭据。"
