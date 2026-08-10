@echo off
:: 以管理员权限提交 ToDesk 启动请求；可能会显示 UAC 确认。
setlocal EnableExtensions
chcp 65001 >nul
set "ERRORLEVEL="

echo 正在提交 ToDesk 管理员启动请求，可能会显示 UAC 确认...
powershell.exe -NoProfile -Command "$candidates = @($env:ProgramFiles, [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'), $env:LOCALAPPDATA) | Where-Object { $_ } | ForEach-Object { Join-Path -Path $_ -ChildPath 'ToDesk\ToDesk.exe' }; $toDesk = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1; if (-not $toDesk) { Write-Host '未找到 ToDesk 可执行文件。'; exit 1 }; try { Start-Process -FilePath $toDesk -Verb RunAs -WindowStyle Hidden -ErrorAction Stop; Write-Host '管理员启动请求已提交。'; exit 0 } catch { Write-Host '管理员启动请求失败，可能已取消 UAC 确认。'; exit 1 }"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" exit /b %EXIT_CODE%
exit /b 0
