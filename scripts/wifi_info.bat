@echo off
:: WiFi信息
:: Shows current WiFi connection details
chcp 65001 >nul
echo ===== WiFi Info =====
echo.

netsh wlan show interfaces 2>nul | findstr /I "SSID Signal BSSID State" || echo No WiFi connection found or WiFi adapter disabled

echo.
echo =========================
