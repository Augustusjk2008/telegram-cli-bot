@echo off
:: 网络信息
:: Shows IP address, MAC address, gateway and other network config
chcp 65001 >nul
echo ===== Network Info =====
echo.
echo Hostname: %COMPUTERNAME%
echo.

powershell -NoProfile -Command "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { $ip = Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue; Write-Host ('Adapter: ' + $_.Name); Write-Host ('  MAC: ' + $_.MacAddress); if ($ip) { Write-Host ('  IP: ' + $ip.IPAddress) } }"

echo.
echo =========================
