@echo off
:: Requests administrator privileges to start ToDesk; a UAC prompt may appear.
setlocal EnableExtensions
chcp 65001 >nul
set "ERRORLEVEL="

echo Requesting administrator privileges to start ToDesk. A UAC prompt may appear...
powershell.exe -NoProfile -Command "$candidates = @($env:ProgramFiles, [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'), $env:LOCALAPPDATA) | Where-Object { $_ } | ForEach-Object { Join-Path -Path $_ -ChildPath 'ToDesk\ToDesk.exe' }; $toDesk = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1; if (-not $toDesk) { Write-Host 'ToDesk executable was not found.'; exit 1 }; try { Start-Process -FilePath $toDesk -Verb RunAs -WindowStyle Hidden -ErrorAction Stop; Write-Host 'Administrator launch request submitted.'; exit 0 } catch { Write-Host 'Administrator launch request failed. The UAC prompt may have been canceled.'; exit 1 }"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" exit /b %EXIT_CODE%
exit /b 0
