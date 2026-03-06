@echo off
:: 性能模式
:: Sets power plan to Best Performance (High Performance)
chcp 65001 >nul
echo Setting power plan to Best Performance...

:: High Performance plan GUID (standard Windows GUID)
set "highPerfGUID=8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

:: Check if High Performance exists
powercfg /list | findstr "%highPerfGUID%" >nul
if %errorlevel% neq 0 (
    echo High Performance plan not found. Creating...
    powercfg /duplicatescheme %highPerfGUID%
    timeout /t 1 >nul
)

:: Activate the high performance plan
powercfg /setactive %highPerfGUID%
echo Power plan set to Best Performance (High Performance)
