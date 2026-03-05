@echo off
:: 清空回收站
:: Permanently deletes all files in Recycle Bin
chcp 65001 >nul
echo Emptying Recycle Bin...

powershell -NoProfile -Command "Clear-RecycleBin -Confirm:$false -ErrorAction SilentlyContinue; Write-Host 'Recycle Bin emptied'"

echo Done
