@echo off
:: USB设备
:: Shows currently connected USB devices
chcp 65001 >nul
echo ===== USB Devices =====
echo.

powershell -NoProfile -Command "Get-WmiObject -Class Win32_DiskDrive | Where-Object { $_.InterfaceType -eq 'USB' } | ForEach-Object { Write-Host ('USB Storage: ' + $_.Model + ' - ' + ([math]::Round($_.Size / 1GB, 2)) + ' GB') }"

echo.
powershell -NoProfile -Command "Get-WmiObject -Class Win32_USBHub | Where-Object { $_.Name -notlike '*Root*' } | ForEach-Object { Write-Host ('USB Device: ' + $_.Name) }"

echo.
echo =========================
