# FreeCAD 嵌入式 Python 封裝方案

## 方案概述

OpenCad CAD Worker 使用 FreeCAD 1.1.1 的可攜式 Python 環境作為建模引擎。
封裝方式：直接嵌入 FreeCAD 的 `bin/` + `lib/` 目錄，透過 `FREECAD_DIR` 環境變數指向。

## 安裝體積

| 項目 | 大小 |
|------|------|
| FreeCAD 1.1.1 portable .7z | 399 MB（下載後可刪） |
| 解壓後 FreeCAD 目錄 | ~1.2 GB |
| cad-worker Python 依賴 | ~50 MB（pydantic, uvicorn 等） |

## 啟動時間

| 操作 | 時間 |
|------|------|
| Python 啟動 + FreeCAD import | ~3-5 秒 |
| Part/Sketcher import | ~1 秒 |
| 首次建模（10 特徵以下） | <50 ms |
| 100-entity 草圖求解 | <200 ms |
| 500-entity 草圖求解 | ~7 秒 |

## 封裝步驟

### 1. 下載 FreeCAD

```powershell
# 下載 FreeCAD 1.1.1 Windows x86_64 portable
$url = "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/FreeCAD-1.1.1-Windows-x86_64-py311.7z"
Invoke-WebRequest -Uri $url -OutFile "FreeCAD_1.1.1.7z"
# 解壓
7z x FreeCAD_1.1.1.7z -o"FreeCAD"
```

### 2. 環境設定

Worker 啟動時需要：
```python
import os, sys
freecad_dir = os.environ.get("FREECAD_DIR", "")
if freecad_dir:
    sys.path.insert(0, os.path.join(freecad_dir, "bin"))
    sys.path.insert(0, os.path.join(freecad_dir, "lib"))
import FreeCAD, Part, Sketcher
```

### 3. 打包建議

- **Velopack**（Windows .exe installer）：將 FreeCAD 目錄打包進安裝包
- **conda-pack**（跨平台）：建立獨立 conda 環境含 FreeCAD
- 啟動腳本設定 `FREECAD_DIR=<install_dir>/FreeCAD/FreeCAD_1.1.1-Windows-x86_64-py311/`

## 引擎切換

```bash
# 預設 build123d
OPENCAD_ENGINE=build123d python -m cad_worker.server

# 切換 FreeCAD
OPENCAD_ENGINE=freecad FREECAD_DIR=/path/to/FreeCAD python -m cad_worker.server
```

## 已知限制

1. **FreeCAD headless revolve**：Face profile 旋轉產生零體積實體（退化幾何）。Phase 1 需改用 PartDesign 或 OCC 直接 API。
2. **PartDesign 不可用**：headless 模式下 PartDesign Workbench 的 SketchObject.Support 不存在，必須用 Part workbench。
3. **Step export**：`Part.export()` 讀回失敗，須用 `Import.export()` + `Import.insert()`。
4. **Lock constraint crash**：Sketcher 的 Lock 約束在 headless 模式 crash，須用 `DistanceX` + `DistanceY` 替代。
5. **GIL 安全**：FreeCAD Document 非線程安全，須用 `threading.Lock` 序列化所有操作。
6. **moveGeometry**：`movePoint` 不存在，須用 `moveGeometry(geoId, posId, newPoint)`（3 參數）。
7. **Part.Point**：使用 `.X/.Y/.Z`（大寫），無 `StartPoint` 屬性。
8. **Coincident posId**：1=start point, 2=end point。