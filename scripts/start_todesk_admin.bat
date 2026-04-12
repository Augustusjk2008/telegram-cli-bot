@echo off
:: 远程操作
:: Starts ToDesk with administrator privileges without user confirmation
chcp 65001 >nul
echo Starting ToDesk with admin privileges...

powershell -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\ToDesk\ToDesk.exe' -Verb RunAs -WindowStyle Hidden -ErrorAction SilentlyContinue; if ($?) { Write-Host 'ToDesk started successfully' } else { Write-Host 'Failed to start ToDesk (may not be installed in default location)' }"

echo Done
