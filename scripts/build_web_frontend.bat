@echo off
setlocal
chcp 65001 >nul
set "ERRORLEVEL="
REM Rebuild web frontend in the front directory.

cd /d "%~dp0..\front" || exit /b 1

call npm run build
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if "%BUILD_EXIT_CODE%"=="0" goto :build_succeeded

echo 首次前端构建失败，正在安装依赖后重试...
call npm install
set "INSTALL_EXIT_CODE=%ERRORLEVEL%"
if not "%INSTALL_EXIT_CODE%"=="0" exit /b %INSTALL_EXIT_CODE%

call npm run build
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if not "%BUILD_EXIT_CODE%"=="0" exit /b %BUILD_EXIT_CODE%

:build_succeeded
echo 前端构建完成
exit /b 0
