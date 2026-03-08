@echo off
chcp 65001 >nul
title Telegram CLI Bridge Bot

echo ==========================================
echo    Telegram CLI Bridge Bot 启动脚本
echo ==========================================
echo.

:: 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: 检查 .env 文件
if not exist ".env" (
    echo [警告] 未找到 .env 文件，请配置环境变量！
    pause
)

echo.
echo ==========================================
echo    正在启动 Bot...
echo ==========================================
echo.

:: 启动 Bot
python -m bot

:: 如果 Bot 异常退出
echo.
echo [错误] Bot 已停止运行！
pause
