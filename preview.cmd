@echo off
setlocal
chcp 65001 >nul

py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.14 "%~dp0scripts\preview.py" %*
    goto preview_finished
)
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.13 "%~dp0scripts\preview.py" %*
    goto preview_finished
)
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.12 "%~dp0scripts\preview.py" %*
    goto preview_finished
)
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.11 "%~dp0scripts\preview.py" %*
    goto preview_finished
)
py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.10 "%~dp0scripts\preview.py" %*
    goto preview_finished
)
python -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>&1
if not errorlevel 1 (
    python "%~dp0scripts\preview.py" %*
    goto preview_finished
)
python3 -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>&1
if not errorlevel 1 (
    python3 "%~dp0scripts\preview.py" %*
    goto preview_finished
)

echo Python was not found. Install CPython 3.10 through 3.14, then run preview.cmd again.
set "preview_exit_code=1"
goto preview_result

:preview_finished
set "preview_exit_code=%ERRORLEVEL%"

:preview_result
if not "%preview_exit_code%"=="0" (
    echo.
    echo Local preview failed. Press any key to close this window.
    pause >nul
)
exit /b %preview_exit_code%
