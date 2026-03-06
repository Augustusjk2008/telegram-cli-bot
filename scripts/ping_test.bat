@echo off
:: 网络测试
:: Tests network latency to common sites
chcp 65001 >nul
echo ===== Ping Test =====
echo.
echo Testing network latency...
echo.

echo Testing www.baidu.com...
echo.

ping -n 2 -w 2000 www.baidu.com | findstr /V "^$" | findstr /V /C:"正在 Ping" | findstr /V /C:"Ping "

echo.
echo ===== Done =====
