@echo off
:: 清理临时文件
:: Deletes contents of Windows temp folders to free disk space
chcp 65001 >nul
echo ===== Cleaning Temp Files =====
echo.

echo [1/2] Cleaning user temp files...
powershell -NoProfile -Command "$env:TEMP | Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Host 'User temp files cleaned'"

echo.
echo [2/2] Cleaning Windows temp files...
powershell -NoProfile -Command "'C:\Windows\Temp' | Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Host 'Windows temp files cleaned'"

echo.
echo ===== Done =====
