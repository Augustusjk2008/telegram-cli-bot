@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "SCRIPT_PATH=%SCRIPT_DIR%start.ps1"
set "CLI_BRIDGE_START_ARGS=%*"
set "CLI_BRIDGE_START_MODE=%~1"

if not exist ".env" (
    echo [INFO] .env not found. Running install.bat...
    if not exist "install.bat" (
        echo [ERROR] Missing .env and install.bat was not found.
        pause
        exit /b 1
    )

    set "CLI_BRIDGE_INSTALLER_NO_PAUSE=1"
    call "%SCRIPT_DIR%install.bat"
    set "EXIT_CODE=!ERRORLEVEL!"
    if not "!EXIT_CODE!"=="0" (
        echo [ERROR] install.bat exited with code: !EXIT_CODE!
        pause
        exit /b !EXIT_CODE!
    )

    if not exist ".env" (
        echo [ERROR] install.bat completed, but .env is still missing.
        pause
        exit /b 1
    )
)

set "PS_EXE="
where pwsh >nul 2>nul
if not errorlevel 1 set "PS_EXE=pwsh"

if not defined PS_EXE (
    where powershell >nul 2>nul
    if not errorlevel 1 set "PS_EXE=powershell"
)

if not defined PS_EXE (
    echo [ERROR] PowerShell was not found. Install pwsh or Windows PowerShell.
    pause
    exit /b 1
)

set "CLI_BRIDGE_PS_EXE=%PS_EXE%"
echo [INFO] Starting service with %PS_EXE%...

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
  "Write-Host '[INFO] Requesting administrator privileges...';" ^
  "$proc = Start-Process -FilePath $hostExe -Verb RunAs -WorkingDirectory (Split-Path -Parent $scriptPath) -ArgumentList $argumentList -Wait -PassThru;" ^
  "if ($null -eq $proc) { exit 1 }" ^
  "exit $proc.ExitCode"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Service exited with code: %EXIT_CODE%
    pause
)
exit /b %EXIT_CODE%
