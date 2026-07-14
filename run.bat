@echo off
chcp 437 >nul
title Albedo v0.2.0 - Knowledge Refiner (Watcher+UI)
setlocal enabledelayedexpansion
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

echo **************************************************
echo   * Albedo v0.2.0 (Knowledge Refiner)  * Opus Magnum Front-Half
echo   Port: 8501   *   One-click launcher
echo **************************************************
echo.

REM --- Python: prefer project venv; create if missing; fallback to system python ---
if exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
    set "PY=%PROJECT_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        echo [SETUP] First run: creating venv and installing dependencies...
        python -m venv "%PROJECT_DIR%\venv" && "%PROJECT_DIR%\venv\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%\requirements.txt"
        if exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
            set "PY=%PROJECT_DIR%\venv\Scripts\python.exe"
        ) else (
            set "PY=python"
        )
    ) else (
        set "PY=python"
    )
)

REM --- Dependency check ---
%PY% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [INSTALL] Installing dependencies...
    %PY% -m pip install -r "%PROJECT_DIR%\requirements.txt"
)

REM --- Cleanup stale instances (restart force-kill, mirror Citrinitas port_cleanup) ---
echo [CLEAN] Cleaning stale Albedo instances...
if exist "%PROJECT_DIR%\.watcher.pid" (
    for /f %%p in (%PROJECT_DIR%\.watcher.pid) do (
        taskkill /PID %%p /F >nul 2>&1
    )
    del /q "%PROJECT_DIR%\.watcher.pid" >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    taskkill /PID %%p /F >nul 2>&1
)

REM --- Launch watcher (independent background process) ---
echo [START] Albedo transit watcher (independent process)...
start "" /B %PY% -m watcher.run

REM --- Launch UI ---
echo [START] Albedo UI on http://127.0.0.1:8501
start "" http://127.0.0.1:8501
%PY% -m streamlit run app.py --server.port 8501
set EXIT_CODE=%errorlevel%

goto cleanup

:cleanup
echo.
echo [STOP] Shutting down Albedo transit watcher (UI closed -^> monitor closed)...
if exist "%PROJECT_DIR%\.watcher.pid" (
    for /f %%p in (%PROJECT_DIR%\.watcher.pid) do (
        taskkill /PID %%p /F >nul 2>&1
    )
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo [STOP] All Albedo services stopped.
if "%EXIT_CODE%"=="0" goto normal_exit
goto error_exit

:error_exit
echo.
echo ==================================================
echo   App exited abnormally (exit code %EXIT_CODE%)
echo   Check error messages above
echo ==================================================
pause
cmd /k

:normal_exit
echo.
echo [STOP] App stopped.
pause
