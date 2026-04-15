@echo off
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not defined CLI_BRIDGE_INSTALLER_NO_PAUSE pause
exit /b %EXIT_CODE%
