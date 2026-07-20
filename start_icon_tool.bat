@echo off
setlocal

cd /d "%~dp0"
python app.py

if errorlevel 1 (
    echo.
    echo Failed to start Icon Conversion Tool.
    pause
)

endlocal
