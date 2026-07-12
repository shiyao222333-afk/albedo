@echo off
chcp 437 >nul
title Albedo v0.2.0 - Knowledge Refiner
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

REM --- Launch ---
echo [START] Albedo on http://127.0.0.1:8501
start "" http://127.0.0.1:8501
%PY% -m streamlit run app.py --server.port 8501
set EXIT_CODE=%errorlevel%
if %EXIT_CODE% NEQ 0 goto error_exit
goto normal_exit

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
