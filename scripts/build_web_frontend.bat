:: 重建 Web 前端
:: 在 front 目录执行 npm run build
@echo off
setlocal

cd /d "%~dp0..\front" || exit /b 1
call npm run build
if errorlevel 1 exit /b %errorlevel%

echo Web 前端构建完成
