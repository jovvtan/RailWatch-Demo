@echo off
echo ========================================
echo   RailWatch DEMO - Starting Up
echo ========================================
echo.
echo   DEMO MODE - Sample data only
echo.
cd /d "%~dp0backend"
echo Starting RailWatch Demo server...
echo.
echo   Access Demo at: http://localhost:8082
echo   To stop: close this window or press Ctrl+C
echo ========================================
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8082
echo.
echo Server stopped. If it crashed, check the error above.
pause
