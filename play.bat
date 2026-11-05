@echo off
rem Brawl Arena launcher for Windows.  Usage:  play.bat SERVER_IP [PORT]
rem First run installs pygame for Python 3.13 (pygame has no Python 3.14 build yet).
cd /d "%~dp0"
if "%~1"=="" (
    set /p SERVER=Server IP or hostname:
) else (
    set SERVER=%~1
)
set PORT=%~2
if "%PORT%"=="" set PORT=5000

py -3.13 -c "import pygame" >nul 2>&1
if errorlevel 1 (
    echo Installing pygame for Python 3.13 ...
    py -3.13 -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Could not install pygame. Install Python 3.13 from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" / "py launcher" during setup, then run this again.
        pause
        exit /b 1
    )
)
py -3.13 -m client.run_client --transport tcp --host %SERVER% --port %PORT%
if errorlevel 1 pause
