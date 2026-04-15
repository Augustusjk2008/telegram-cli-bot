@echo off
setlocal
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "SCRIPT_PATH=%SCRIPT_DIR%start.ps1"
set "CLI_BRIDGE_START_ARGS=%*"
set "CLI_BRIDGE_START_MODE=%~1"

if not exist ".env" (
    echo [错误] 未找到 .env，请先运行 install.bat 生成配置。
    pause
    exit /b 1
)

set "PS_EXE="
where pwsh >nul 2>nul
if not errorlevel 1 set "PS_EXE=pwsh"

if not defined PS_EXE (
    where powershell >nul 2>nul
    if not errorlevel 1 set "PS_EXE=powershell"
)

if not defined PS_EXE (
    echo [错误] 未找到 pwsh 或 powershell，请先安装 PowerShell。
    pause
    exit /b 1
)

set "CLI_BRIDGE_PS_EXE=%PS_EXE%"
echo [信息] 使用 %PS_EXE% 启动服务...

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$hostExe = $env:CLI_BRIDGE_PS_EXE;" ^
  "$scriptPath = $env:SCRIPT_PATH;" ^
  "$mode = $env:CLI_BRIDGE_START_MODE;" ^
  "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent());" ^
  "$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);" ^
  "$argumentList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $scriptPath);" ^
  "if ($mode) { $argumentList += @('-Mode', $mode) }" ^
  "if ($isAdmin) { & $hostExe @argumentList; exit $LASTEXITCODE }" ^
  "Write-Host '[信息] 正在请求管理员权限...';" ^
  "$proc = Start-Process -FilePath $hostExe -Verb RunAs -WorkingDirectory (Split-Path -Parent $scriptPath) -ArgumentList $argumentList -Wait -PassThru;" ^
  "if ($null -eq $proc) { exit 1 }" ^
  "exit $proc.ExitCode"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [错误] 服务已退出，退出码: %EXIT_CODE%
    pause
)
exit /b %EXIT_CODE%
