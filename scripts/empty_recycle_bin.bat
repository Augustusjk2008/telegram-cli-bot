@echo off
:: 清空回收站
:: Permanently deletes all files in Recycle Bin
chcp 65001 >nul
echo Emptying Recycle Bin...

powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; try { Clear-RecycleBin -Confirm:$false -ErrorAction Stop; Write-Host 'Recycle Bin emptied'; exit 0 } catch { [Console]::Error.WriteLine(('Failed to empty Recycle Bin: ' + $_.Exception.Message)); exit 1 }"
if errorlevel 1 (
    echo Failed to empty Recycle Bin. >&2
    exit /b 1
)

echo Done
exit /b 0
