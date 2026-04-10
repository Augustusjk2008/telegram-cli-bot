@echo off
setlocal
REM Rebuild web frontend in the front directory.

cd /d "%~dp0..\front" || exit /b 1
call npm run build
if errorlevel 1 exit /b %errorlevel%

echo Web frontend build finished
