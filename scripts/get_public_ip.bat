@echo off
:: 公网IP
:: Shows current public IP address
chcp 65001 >nul
echo ===== Public IP Info =====
echo.

powershell -NoProfile -Command "try { $ip = Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 5; Write-Host ('Public IP: ' + $ip) } catch { Write-Host 'Failed to get public IP' }"

echo.
echo =======================
