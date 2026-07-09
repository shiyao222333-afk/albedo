@echo off
setlocal

REM === Albedo (Lian Zhen) launcher ===
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

cd /d "%PROJECT_DIR%"

where python >nul 2>nul
if not errorlevel 1 goto check_streamlit
echo [ERROR] Python not found. Install Python 3.13 and add it to PATH.
pause
exit /b 1

:check_streamlit
python -c "import streamlit" >nul 2>nul
if not errorlevel 1 goto launch
echo [INFO] streamlit missing. Installing dependencies from requirements.txt ...
python -m pip install -r "%PROJECT_DIR%\requirements.txt"
if not errorlevel 1 goto launch
echo [ERROR] Dependency install failed. Check your network and Python install.
pause
exit /b 1

:launch
echo [INFO] Starting Albedo on http://localhost:8501
python -m streamlit run "%PROJECT_DIR%\app.py" --server.port 8501
if not errorlevel 1 goto end
echo [ERROR] Launch failed. Make sure app.py exists in the project root.
pause

:end
endlocal
