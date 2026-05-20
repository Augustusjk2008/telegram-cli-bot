:: Sync current codex source back to active backup folder
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

if not exist "%BACKUP_DIR%" (
    echo Error: Backup directory does not exist.
    exit /b 1
)

if not exist "%STATE_FILE%" (
    echo Error: Switch state does not exist. Run codex_switch_source.bat first.
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

set "CURRENT_INDEX="
for /f "usebackq delims=" %%A in ("%STATE_FILE%") do (
    if not defined CURRENT_INDEX set "CURRENT_INDEX=%%A"
)

if not defined CURRENT_INDEX (
    echo Error: Switch state is empty.
    exit /b 1
)

for /f "tokens=1" %%A in ("%CURRENT_INDEX%") do set "CURRENT_INDEX=%%A"
set "INVALID_STATE="
for /f "delims=0123456789" %%A in ("%CURRENT_INDEX%") do set "INVALID_STATE=1"

if defined INVALID_STATE (
    echo Error: Invalid switch state: %CURRENT_INDEX%
    exit /b 1
)

set /a CURRENT_INDEX_NUM=CURRENT_INDEX

if %CURRENT_INDEX_NUM% lss 1 (
    echo Error: Invalid switch state: %CURRENT_INDEX%
    exit /b 1
)

if %CURRENT_INDEX_NUM% gtr %FOLDER_COUNT% (
    echo Error: Switch state out of range: %CURRENT_INDEX% / %FOLDER_COUNT%
    exit /b 1
)

set "TARGET_FOLDER=!FOLDER_%CURRENT_INDEX_NUM%!"
set "TARGET_DIR=%BACKUP_DIR%\%TARGET_FOLDER%"

if not exist "%TARGET_DIR%" (
    echo Error: Active backup folder does not exist: %TARGET_FOLDER%
    exit /b 1
)

echo Backup folders found: %FOLDER_COUNT%
echo Current index: %CURRENT_INDEX_NUM%
echo Syncing current source to folder %CURRENT_INDEX_NUM%: %TARGET_FOLDER%

set "COPY_OK=1"
set "COPIED_COUNT=0"

set "SRC_FILE=%CODEX_DIR%\auth.json"
set "DST_FILE=%TARGET_DIR%\auth.json"
if exist "%SRC_FILE%" (
    copy /y "%SRC_FILE%" "%DST_FILE%" >nul
    if errorlevel 1 (
        echo Error: Failed to copy auth.json
        set "COPY_OK=0"
    ) else (
        set /a COPIED_COUNT+=1
        echo Updated auth.json in %TARGET_FOLDER%
    )
) else (
    echo Warning: auth.json not found in current Codex directory
)

set "SRC_FILE=%CODEX_DIR%\config.toml"
set "DST_FILE=%TARGET_DIR%\config.toml"
if exist "%SRC_FILE%" (
    copy /y "%SRC_FILE%" "%DST_FILE%" >nul
    if errorlevel 1 (
        echo Error: Failed to copy config.toml
        set "COPY_OK=0"
    ) else (
        set /a COPIED_COUNT+=1
        echo Updated config.toml in %TARGET_FOLDER%
    )
) else (
    echo Warning: config.toml not found in current Codex directory
)

if %COPY_OK% equ 0 (
    echo Sync aborted due to copy errors.
    exit /b 1
)

if %COPIED_COUNT% equ 0 (
    echo Error: No current Codex source files found to sync.
    exit /b 1
)

echo Sync complete. Active folder updated: %TARGET_FOLDER%
exit /b 0
