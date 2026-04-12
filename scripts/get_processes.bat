@echo off
:: 进程列表
:: Shows top 20 processes by memory usage
chcp 65001 >nul
echo ===== Process List (by Memory) =====
echo.

powershell -NoProfile -Command "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 | ForEach-Object { Write-Host ($_.Name + ' (PID: ' + $_.Id + ') - Memory: ' + ([math]::Round($_.WorkingSet64 / 1MB, 1)) + ' MB') }"

echo.
powershell -NoProfile -Command "$total = (Get-WmiObject -Class Win32_ComputerSystem).TotalPhysicalMemory / 1MB; $used = (Get-Process | Measure-Object WorkingSet64 -Sum).Sum / 1MB; Write-Host ('Total RAM: ' + ([math]::Round($total, 0)) + ' MB, Used: ' + ([math]::Round($used, 0)) + ' MB')"

echo.
echo ==========================================
