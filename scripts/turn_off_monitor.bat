@echo off
:: 关闭显示器
:: Uses SendMessageTimeout for non-blocking call with timeout
:: Works on all Windows systems
chcp 65001 >nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0turn_off_monitor.ps1"

