@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1 || (
    echo Failed to enter project directory: "%SCRIPT_DIR%"
    exit /b 1
)

set "ROOT_DIR=%CD%"
set "VENV_PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"
set "SPEC_FILE=%ROOT_DIR%\razr-gui.spec"

if not exist "%SPEC_FILE%" (
    echo Spec file not found: "%SPEC_FILE%"
    echo Make sure build-windows.bat and razr-gui.spec are in the same project folder.
    popd
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found at %ROOT_DIR%\.venv
    echo Create it first with: py -m venv .venv
    popd
    exit /b 1
)

echo Building razr-gui.exe with PyInstaller...
"%VENV_PYTHON%" -m PyInstaller --noconfirm "%SPEC_FILE%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    popd
    exit /b %EXIT_CODE%
)

echo.
echo Build complete: %ROOT_DIR%\dist\razr-gui.exe
popd
