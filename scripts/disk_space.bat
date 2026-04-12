@echo off
:: 磁盘空间
:: Shows capacity, used space, free space and usage percentage for all disks
chcp 65001 >nul
echo ===== Disk Space Usage =====
echo.

powershell -NoProfile -Command "Get-WmiObject -Class Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 } | ForEach-Object { $size = [math]::Round($_.Size / 1GB, 2); $free = [math]::Round($_.FreeSpace / 1GB, 2); $used = [math]::Round(($_.Size - $_.FreeSpace) / 1GB, 2); $pct = [math]::Round(($_.FreeSpace / $_.Size) * 100, 1); Write-Host ('Drive ' + $_.DeviceID); Write-Host ('  Total: ' + $size + ' GB'); Write-Host ('  Used:  ' + $used + ' GB'); Write-Host ('  Free:  ' + $free + ' GB (' + $pct + '%%)'); Write-Host ('  Label: ' + $_.VolumeName); Write-Host '' }"

echo.
echo =============================
