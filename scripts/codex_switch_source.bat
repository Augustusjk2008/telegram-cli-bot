:: Codex 换源
:: 切换 Codex 当前配置与备份配置
@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "CODEX_DIR=%USERPROFILE%\.codex"
set "BACKUP_DIR=%CODEX_DIR%\backup"

if not exist "%CODEX_DIR%" (
    echo 错误：Codex目录不存在。
    exit /b 1
)

if not exist "%BACKUP_DIR%" (
    echo 错误：备份目录不存在。
    exit /b 1
)

call :swap_file "auth.json" "auth_temp.json"
if errorlevel 1 exit /b 1

call :swap_file "config.toml" "config_temp.toml"
if errorlevel 1 exit /b 1

echo 交换完成。
exit /b 0

:swap_file
set "FILE_NAME=%~1"
set "TEMP_NAME=%~2"
set "LIVE_FILE=%CODEX_DIR%\%FILE_NAME%"
set "BACKUP_FILE=%BACKUP_DIR%\%FILE_NAME%"
set "TEMP_FILE=%TEMP%\%TEMP_NAME%"

if not exist "%LIVE_FILE%" (
    echo 警告：Codex目录中未找到%FILE_NAME%文件。
    exit /b 0
)

if not exist "%BACKUP_FILE%" (
    echo 警告：备份目录中未找到%FILE_NAME%文件。
    exit /b 0
)

copy /y "%LIVE_FILE%" "!TEMP_FILE!" >nul || (
    echo 错误：无法创建临时备份文件 %FILE_NAME%。
    exit /b 1
)

copy /y "%BACKUP_FILE%" "%LIVE_FILE%" >nul || (
    del /q "!TEMP_FILE!" >nul 2>&1
    echo 错误：无法写入当前文件 %FILE_NAME%。
    exit /b 1
)

copy /y "!TEMP_FILE!" "%BACKUP_FILE%" >nul || (
    del /q "!TEMP_FILE!" >nul 2>&1
    echo 错误：无法写回备份文件 %FILE_NAME%。
    exit /b 1
)

del /q "!TEMP_FILE!" >nul 2>&1
exit /b 0
