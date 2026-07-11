@echo off
REM Script to run FreeCAD tests with the correct Python environment
REM This ensures compatibility between FreeCAD and Python versions

echo Running FreeCAD tests with Python 3.11...
echo.

cd /d "%~dp0"

if exist "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" (
    echo Using FreeCAD's Python 3.11 environment
    echo.
    "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m pytest tests/cad-worker/test_freecad_adapter.py -v
) else (
    echo Error: FreeCAD Python environment not found!
    echo Please ensure FreeCAD is installed in the expected directory.
    exit /b 1
)

echo.
echo Test execution completed.