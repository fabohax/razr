@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "VENV_PYTHON=%ROOT_DIR%.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found at %ROOT_DIR%.venv
    echo Create it first with: py -m venv .venv
    exit /b 1
)

cd /d "%ROOT_DIR%"

echo Building razr-gui.exe with PyInstaller...
"%VENV_PYTHON%" -m PyInstaller --noconfirm "%ROOT_DIR%razr-gui.spec"
if errorlevel 1 exit /b 1

echo.
echo Build complete: %ROOT_DIR%dist\razr-gui.exe
