@echo off
:: 重启资源管理器
:: Restarts Windows Explorer process
chcp 65001 >nul
echo Restarting Explorer...
echo.
echo Step 1: Stopping explorer.exe...
taskkill /f /im explorer.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo Step 2: Starting explorer.exe...
start explorer.exe
echo.
echo Explorer restarted
