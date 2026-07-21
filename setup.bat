@echo off
REM ============================================================
REM Albedo (Lian Zhen) - one-click isolated environment setup
REM Creates venv with managed Python 3.13.12 and installs deps.
REM Pure ASCII on purpose (GBK/CP936 safe; no UTF-8 Chinese).
REM ============================================================
setlocal
set "PROJECT_DIR=%~dp0"
set "VENV=%PROJECT_DIR%venv"
set "MANAGED_PY=C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"

if exist "%MANAGED_PY%" (
    set "PY=%MANAGED_PY%"
) else (
    set "PY=python"
)

if not exist "%VENV%\Scripts\python.exe" (
    echo [setup] Creating virtualenv with %PY% ...
    "%PY%" -m venv "%VENV%"
) else (
    echo [setup] venv already exists, skipping create
)

echo [setup] Upgrading pip ...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip

echo [setup] Installing torch (CUDA cu126 build for RTX 3080 GPU) ...
"%VENV%\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cu126

echo [setup] Installing requirements.txt ...
"%VENV%\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%requirements.txt"

echo [setup] Done. Albedo venv ready at %VENV%
echo [setup] Run watcher : %VENV%\Scripts\python.exe -m watcher
echo [setup] Run UI      : %VENV%\Scripts\python.exe -m streamlit run app.py
endlocal
