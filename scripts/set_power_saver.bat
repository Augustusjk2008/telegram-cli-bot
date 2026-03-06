@echo off
:: 能效模式
:: Sets power plan to Best Power Efficiency (Power Saver)
chcp 65001 >nul
echo Setting power plan to Best Power Efficiency...

:: Power Saver plan GUID (standard Windows GUID)
set "powerSaverGUID=a1841308-3541-4fab-bc81-f71556f20b4a"

:: Check if Power Saver exists
powercfg /list | findstr "%powerSaverGUID%" >nul
if %errorlevel% neq 0 (
    echo Power Saver plan not found. Creating...
    powercfg /duplicatescheme %powerSaverGUID%
    timeout /t 1 >nul
)

:: Activate the power saver plan
powercfg /setactive %powerSaverGUID%
echo Power plan set to Best Power Efficiency (Power Saver)
