@echo off
setlocal
cd /d "%~dp0"
set "PORT=8765"

where py >nul 2>nul
if not errorlevel 1 (
    start "EV Charging Map Server" /min cmd /k "cd /d ""%~dp0"" && py -3 -m http.server %PORT% --bind 127.0.0.1"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        start "EV Charging Map Server" /min cmd /k "cd /d ""%~dp0"" && python -m http.server %PORT% --bind 127.0.0.1"
    ) else (
        echo Python 3 was not found. Install Python 3 or add it to PATH, then run this file again.
        pause
        exit /b 1
    )
)
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%PORT%/EV_Charging_M1_M2_Interactive_Map.html"
echo.
echo The map is running locally. Keep the minimized "EV Charging Map Server" window open.
echo Close that server window when you finish using the map.
