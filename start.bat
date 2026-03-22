@echo off
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist ".env" (
    echo [Warning] .env file not found!
    pause
    exit /b 1
)

powershell.exe -ExecutionPolicy Bypass -File "%~dp0start_tray.ps1"
