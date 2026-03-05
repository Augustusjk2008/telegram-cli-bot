@echo off
:: 网络测试
:: Tests network latency to common sites
chcp 65001 >nul
echo ===== Ping Test =====
echo.
echo Testing network latency...
echo.

echo Testing baidu.com...
ping -n 1 -w 2000 baidu.com | findstr "time=" >nul && echo [OK] baidu.com reachable || echo [Timeout] baidu.com unreachable

echo.
echo Testing 8.8.8.8...
ping -n 1 -w 2000 8.8.8.8 | findstr "time=" >nul && echo [OK] 8.8.8.8 reachable || echo [Timeout] 8.8.8.8 unreachable

echo.
echo ===== Done =====
