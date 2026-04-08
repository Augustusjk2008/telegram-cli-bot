REM Codex换源
@echo off
setlocal enabledelayedexpansion

set CODEX_DIR=C:\Users\JiangKai\.codex
set BACKUP_DIR=%CODEX_DIR%\backup

REM 检查目录是否存在
if not exist "%CODEX_DIR%" (
    echo 错误：Codex目录不存在。
    pause
    exit /b 1
)
if not exist "%BACKUP_DIR%" (
    echo 错误：备份目录不存在。
    pause
    exit /b 1
)

REM 交换auth.json文件
if exist "%CODEX_DIR%\auth.json" (
    if exist "%BACKUP_DIR%\auth.json" (
        set TEMP_FILE=%TEMP%\auth_temp.json
        copy "%CODEX_DIR%\auth.json" "%TEMP_FILE%"
        copy "%BACKUP_DIR%\auth.json" "%CODEX_DIR%\auth.json"
        copy "%TEMP_FILE%" "%BACKUP_DIR%\auth.json"
        del "%TEMP_FILE%"
    ) else (
        echo 警告：备份目录中未找到auth.json文件。
    )
) else (
    echo 警告：Codex目录中未找到auth.json文件。
)

REM 交换config.toml文件
if exist "%CODEX_DIR%\config.toml" (
    if exist "%BACKUP_DIR%\config.toml" (
        set TEMP_FILE=%TEMP%\config_temp.toml
        copy "%CODEX_DIR%\config.toml" "%TEMP_FILE%"
        copy "%BACKUP_DIR%\config.toml" "%CODEX_DIR%\config.toml"
        copy "%TEMP_FILE%" "%BACKUP_DIR%\config.toml"
        del "%TEMP_FILE%"
    ) else (
        echo 警告：备份目录中未找到config.toml文件。
    )
) else (
    echo 警告：Codex目录中未找到config.toml文件。
)

echo 交换完成。
pause
exit /b 0