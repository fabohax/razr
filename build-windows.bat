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
set "GUI_ENTRY=%ROOT_DIR%\gui.py"
set "BUILD_TARGET=%SPEC_FILE%"
set "PYINSTALLER_ARGS="

if not exist "%SPEC_FILE%" (
    if not exist "%GUI_ENTRY%" (
        echo Spec file not found: "%SPEC_FILE%"
        echo GUI entry point not found either: "%GUI_ENTRY%"
        echo Make sure the project files are in the same folder.
        popd
        exit /b 1
    )

    echo Spec file not found. Falling back to gui.py...
    set "BUILD_TARGET=%GUI_ENTRY%"
    set "PYINSTALLER_ARGS=--onefile --name razr-gui"
)

if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found at %ROOT_DIR%\.venv
    echo Create it first with: py -m venv .venv
    popd
    exit /b 1
)

echo Building razr-gui.exe with PyInstaller...
"%VENV_PYTHON%" -m PyInstaller --noconfirm %PYINSTALLER_ARGS% "%BUILD_TARGET%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    popd
    exit /b %EXIT_CODE%
)

echo.
echo Build complete: %ROOT_DIR%\dist\razr-gui.exe
popd
