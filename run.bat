@echo off
title BridgeSkill Platform - Full Stack with AI Features
cd /d "%~dp0"

:: Enforce UTF-8 console output for Python and AI emoji support
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul

echo ======================================================================
echo          BridgeSkill - Industry Micro-Projects Platform
echo             (Full Stack SPA + FastAPI + Groq AI Engine)
echo ======================================================================
echo.

:: Detect Python environment
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

:: Verify dependencies and initialize database tables
echo [*] Initializing database and verifying tables...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '.'); from backend.app.db import init_db; init_db()"
if errorlevel 1 (
    echo [!] Warning: Database check encountered an issue. Proceeding with startup...
) else (
    echo [OK] Database verified.
)

:: Automatically open default browser after 2 seconds
echo [*] Launching BridgeSkill in your default browser...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

echo.
echo ======================================================================
echo  Server is active at: http://127.0.0.1:8000
echo  API Documentation:   http://127.0.0.1:8000/docs
echo  AI Consultant:       Available via Floating Widget & Navigation
echo ======================================================================
echo.
echo Press Ctrl+C anytime to stop the server.
echo.

:: Run FastAPI & Static SPA with auto-reload
"%PYTHON_EXE%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

pause
