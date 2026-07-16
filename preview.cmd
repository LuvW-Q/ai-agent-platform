@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preview.ps1" %*
set "preview_exit_code=%ERRORLEVEL%"
if not "%preview_exit_code%"=="0" (
    echo.
    echo Local preview failed. Press any key to close this window.
    pause >nul
)
exit /b %preview_exit_code%
