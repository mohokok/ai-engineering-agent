@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if not defined BACKEND_HOST set "BACKEND_HOST=127.0.0.1"
if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined FRONTEND_HOST set "FRONTEND_HOST=127.0.0.1"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"

if exist "%REPO_ROOT%\.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%REPO_ROOT%\.env") do (
        set "KEY=%%A"
        if not "!KEY!"=="" if not "!KEY:~0,1!"=="#" (
            if /i "!KEY!"=="BACKEND_HOST" if not "%%B"=="" set "BACKEND_HOST=%%B"
            if /i "!KEY!"=="BACKEND_PORT" if not "%%B"=="" set "BACKEND_PORT=%%B"
            if /i "!KEY!"=="FRONTEND_HOST" if not "%%B"=="" set "FRONTEND_HOST=%%B"
            if /i "!KEY!"=="FRONTEND_PORT" if not "%%B"=="" set "FRONTEND_PORT=%%B"
        )
    )
)

if not exist "%REPO_ROOT%\workspaces" mkdir "%REPO_ROOT%\workspaces"

set "PYTHON_EXE="
if exist "%REPO_ROOT%\backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%REPO_ROOT%\backend\.venv\Scripts\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python 3.11+ was not found. Create backend\.venv or install Python 3.12 first.
    exit /b 1
)

if not exist "%REPO_ROOT%\frontend\node_modules" (
    echo [ERROR] frontend\node_modules not found. Run: cd frontend ^&^& npm.cmd install
    exit /b 1
)

echo Starting Backend on http://%BACKEND_HOST%:%BACKEND_PORT% ...
start "AI Engineering Agent - Backend" /D "%REPO_ROOT%\backend" "%PYTHON_EXE%" -m uvicorn app.main:app --host %BACKEND_HOST% --port %BACKEND_PORT% --reload

echo Starting Frontend on http://%FRONTEND_HOST%:%FRONTEND_PORT% ...
start "AI Engineering Agent - Frontend" /D "%REPO_ROOT%\frontend" cmd /c "npm.cmd run dev -- --host %FRONTEND_HOST% --port %FRONTEND_PORT%"

echo Waiting for backend and frontend to listen...
"%PYTHON_EXE%" "%REPO_ROOT%\scripts\wait_for_servers.py" "http://%BACKEND_HOST%:%BACKEND_PORT%/api/health" "http://%FRONTEND_HOST%:%FRONTEND_PORT%/"
if errorlevel 1 (
    echo [WARN] Backend or frontend did not respond within 20 seconds.
) else (
    echo Both backend and frontend are responding.
)

if not "%NO_BROWSER%"=="1" (
    start "" "http://%FRONTEND_HOST%:%FRONTEND_PORT%"
)

echo Launched backend (http://%BACKEND_HOST%:%BACKEND_PORT%/api/health) and frontend (http://%FRONTEND_HOST%:%FRONTEND_PORT%).
endlocal
