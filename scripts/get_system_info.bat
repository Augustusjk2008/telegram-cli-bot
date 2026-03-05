@echo off
:: 系统信息
:: Shows computer name, username, current time and OS info
chcp 65001 >nul
echo ===== System Info =====
echo Computer: %COMPUTERNAME%
echo Username: %USERNAME%
echo Date/Time: %DATE% %TIME%
echo OS: %OS%
echo Architecture: %PROCESSOR_ARCHITECTURE%
echo ===================
