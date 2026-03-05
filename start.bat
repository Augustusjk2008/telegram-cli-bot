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

:: 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [警告] 未找到虚拟环境，正在创建...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败！请确保已安装 Python 3.8+
        pause
        exit /b 1
    )
    echo [成功] 虚拟环境创建完成
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 检查依赖是否需要安装
if not exist "venv\.dependencies_installed" (
    echo [信息] 正在安装依赖...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 安装依赖失败！
        pause
        exit /b 1
    )
    echo. > venv\.dependencies_installed
    echo [成功] 依赖安装完成
)

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
