@echo off
REM Build script for Gofile Drag & Drop Uploader

echo ================================================
echo Building Gofile Drag ^& Drop Uploader...
echo ================================================
echo.

REM Find Python and PyInstaller from virtual environment
set PYTHON_EXE=python
set PYINSTALLER_EXE=pyinstaller

if exist ".venv\Scripts\python.exe" (
    echo Using Python from .venv virtual environment
    set PYTHON_EXE=.venv\Scripts\python.exe
    set PYINSTALLER_EXE=.venv\Scripts\pyinstaller.exe
) else if exist "venv\Scripts\python.exe" (
    echo Using Python from venv virtual environment
    set PYTHON_EXE=venv\Scripts\python.exe
    set PYINSTALLER_EXE=venv\Scripts\pyinstaller.exe
) else (
    echo Warning: Virtual environment not found
    echo Using system Python...
)
echo.

REM Build the executable
"%PYINSTALLER_EXE%" GofileUploader.spec

echo.
echo ================================================
echo Build complete!
echo ================================================
echo.
echo Executable location: dist\GofileUploader.exe
echo.
echo You can now double-click GofileUploader.exe to run!
echo.
