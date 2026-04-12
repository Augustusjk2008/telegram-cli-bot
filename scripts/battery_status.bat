@echo off
:: 电池状态
:: Shows laptop battery level, charging status and estimated runtime
chcp 65001 >nul
echo ===== Battery Status =====
echo.

powershell -NoProfile -Command "Get-WmiObject Win32_Battery -EA SilentlyContinue | Select-Object EstimatedChargeRemaining,BatteryStatus,EstimatedRunTime | Format-List"

echo.
echo ===================
