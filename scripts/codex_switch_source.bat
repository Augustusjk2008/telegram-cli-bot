:: Switch codex source
@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "CODEX_DIR=%USERPROFILE%\.codex"
set "BACKUP_DIR=%CODEX_DIR%\backup"
set "STATE_FILE=%CODEX_DIR%\.switch_state"

if not exist "%CODEX_DIR%" (
    echo Error: Codex directory does not exist.
    exit /b 1
)

if /i "%~1"=="clear" (
    call :clear_files
    exit /b %errorlevel%
)

if not exist "%BACKUP_DIR%" (
    echo Error: Backup directory does not exist.
    exit /b 1
)

set "FOLDER_COUNT=0"
for /f "delims=" %%D in ('dir /b /ad /on "%BACKUP_DIR%"') do (
    set /a FOLDER_COUNT+=1
    set "FOLDER_!FOLDER_COUNT!=%%D"
)

if %FOLDER_COUNT% equ 0 (
    echo Error: No subfolders found in backup directory.
    exit /b 1
)

set "CURRENT_INDEX=0"
if exist "%STATE_FILE%" (
    for /f "usebackq delims=" %%A in ("%STATE_FILE%") do (
        set "CURRENT_INDEX=%%A"
    )
)

set /a NEXT_INDEX=CURRENT_INDEX + 1
if %NEXT_INDEX% gtr %FOLDER_COUNT% set /a NEXT_INDEX=1
if %NEXT_INDEX% lss 1 set /a NEXT_INDEX=1

set "TARGET_FOLDER=!FOLDER_%NEXT_INDEX%!"
set "TARGET_DIR=%BACKUP_DIR%\%TARGET_FOLDER%"

echo Backup folders found: %FOLDER_COUNT%
echo Current index: %CURRENT_INDEX%
echo Switching to folder %NEXT_INDEX%: %TARGET_FOLDER%

set "COPY_OK=1"

set "SRC_FILE=%TARGET_DIR%\auth.json"
set "DST_FILE=%CODEX_DIR%\auth.json"
if exist "%SRC_FILE%" (
    copy /y "%SRC_FILE%" "%DST_FILE%" >nul
    if errorlevel 1 (
        echo Error: Failed to copy auth.json
        set "COPY_OK=0"
    ) else (
        echo Copied auth.json from %TARGET_FOLDER%
    )
) else (
    echo Warning: auth.json not found in %TARGET_FOLDER%
)

set "SRC_FILE=%TARGET_DIR%\config.toml"
set "DST_FILE=%CODEX_DIR%\config.toml"
if exist "%SRC_FILE%" (
    copy /y "%SRC_FILE%" "%DST_FILE%" >nul
    if errorlevel 1 (
        echo Error: Failed to copy config.toml
        set "COPY_OK=0"
    ) else (
        echo Copied config.toml from %TARGET_FOLDER%
    )
) else (
    echo Warning: config.toml not found in %TARGET_FOLDER%
)

if %COPY_OK% equ 0 (
    echo Switch aborted due to copy errors.
    exit /b 1
)

echo %NEXT_INDEX% > "%STATE_FILE%"
echo Switch complete. Active folder: %TARGET_FOLDER%
exit /b 0

:clear_files
set "DEL_OK=1"

if exist "%CODEX_DIR%\auth.json" (
    del /q "%CODEX_DIR%\auth.json" >nul 2>&1
    if errorlevel 1 (
        echo Error: Failed to delete auth.json
        set "DEL_OK=0"
    ) else (
        echo Deleted auth.json
    )
) else (
    echo auth.json not found, skipped
)

if exist "%CODEX_DIR%\config.toml" (
    del /q "%CODEX_DIR%\config.toml" >nul 2>&1
    if errorlevel 1 (
        echo Error: Failed to delete config.toml
        set "DEL_OK=0"
    ) else (
        echo Deleted config.toml
    )
) else (
    echo config.toml not found, skipped
)

if exist "%STATE_FILE%" (
    del /q "%STATE_FILE%" >nul 2>&1
)

if %DEL_OK% equ 0 (
    echo Clear aborted due to errors.
    exit /b 1
)

echo Clear complete.
exit /b 0
