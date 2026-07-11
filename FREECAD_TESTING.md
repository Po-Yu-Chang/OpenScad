# FreeCAD Testing Guide

## Overview

This document explains how to properly run the FreeCAD adapter tests, which require a specific Python environment to function correctly.

## Environment Requirements

- FreeCAD 1.1.1 with Python 3.11 (included in the installation)
- The tests must be run with FreeCAD's Python, not the system Python

## Why FreeCAD's Python is Required

FreeCAD was compiled with Python 3.11. If you try to run the tests with a different Python version (e.g., Python 3.12), you will encounter DLL conflicts and the tests will be skipped.

## Running the Tests

### Method 1: Using the Batch Script (Recommended)

A convenience script has been provided to automatically use the correct Python environment:

```cmd
run_freecad_tests.bat
```

### Method 2: Manual Execution

You can manually run the tests with FreeCAD's Python:

```cmd
.\FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe -m pytest tests/cad-worker/test_freecad_adapter.py -v
```

### Method 3: Using py.exe with Python 3.11

If you have Python 3.11 installed separately on your system:

```cmd
py -3.11 -m pytest tests/cad-worker/test_freecad_adapter.py -v
```

## Test Results

When run correctly, all 36 tests should pass:

- 36 passed
- 0 failed
- 0 skipped

## Troubleshooting

### Tests are Skipped

If all tests are being skipped, it means FreeCAD is not available in the current Python environment. Ensure you're using FreeCAD's Python 3.11.

### DLL Conflicts

If you see errors about Python DLL conflicts, you're likely trying to use FreeCAD with an incompatible Python version.

### FreeCAD Not Found

If the script reports that FreeCAD is not found, ensure that:
1. FreeCAD is installed in the expected directory (`.\FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\`)
2. The path in the script matches your installation