@echo off
:: 运行时间
:: Shows how long the computer has been running since last boot
chcp 65001 >nul
echo ===== System Uptime =====
echo.

powershell -NoProfile -Command "$os = Get-WmiObject -Class Win32_OperatingSystem; $boot = $os.ConvertToDateTime($os.LastBootUpTime); $up = (Get-Date) - $boot; Write-Host ('Boot Time: ' + $boot); Write-Host ''; Write-Host ('Uptime:'); Write-Host ('  ' + [math]::Floor($up.TotalDays) + ' days'); Write-Host ('  ' + $up.Hours + ' hours'); Write-Host ('  ' + $up.Minutes + ' minutes'); Write-Host ('  ' + $up.Seconds + ' seconds')"

echo.
echo ========================
