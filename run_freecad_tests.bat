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
    if errorlevel 1 exit /b 1

    REM WP1-2R: Phase 0 spike 的 19 個原生 FreeCAD Sketcher kill-test（cad-worker-freecad/tests/
    REM test_sketch_solver.py）——驗證 FreeCAD Sketcher 本身的求解/DOF/衝突/拖曳能力，
    REM 非本專案 JSON 求解器（cad_worker/sketch_solver.py，另有 tests/cad-worker/test_sketch_solver.py）。
    REM 注意：含 100/500-entity 規模測試，實測約 5-6 分鐘。
    echo.
    echo Running Phase 0 FreeCAD Sketcher spike tests (~5-6 min, includes 100/500-entity scale tests)...
    echo.
    "FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe" -m pytest cad-worker-freecad/tests/test_sketch_solver.py -v
) else (
    echo Error: FreeCAD Python environment not found!
    echo Please ensure FreeCAD is installed in the expected directory.
    exit /b 1
)

echo.
echo Test execution completed.