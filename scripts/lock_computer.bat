@echo off
:: 锁定电脑
:: Locks the workstation immediately
chcp 65001 >nul
echo Locking computer...
rundll32.exe user32.dll,LockWorkStation
echo Computer locked
