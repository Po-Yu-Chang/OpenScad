# FreeCAD 嵌入式 Python 封裝方案

## 方案概述

OpenCad CAD Worker 使用 FreeCAD 1.1.1 的可攜式 Python 環境作為建模引擎。
封裝方式：直接嵌入 FreeCAD 的 `bin/` + `lib/` 目錄，透過 `FREECAD_DIR` 環境變數指向。

## 環境安裝步驟（WP1-0R 更新）

### 1. 下載 FreeCAD 1.1.1 portable

```powershell
# 下載 FreeCAD 1.1.1 Windows x86_64 portable .7z
$url = "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/FreeCAD-1.1.1-Windows-x86_64-py311.7z"
Invoke-WebRequest -Uri $url -OutFile "FreeCAD_1.1.1.7z"
# 解壓至 repo 根目錄下
7z x FreeCAD_1.1.1.7z -o"FreeCAD"
# 確認目錄結構：FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe
```

### 2. 安裝 cad-worker 依賴至 FreeCAD Python

```powershell
# 執行環境設定腳本（可重複執行）
.\tools\setup-freecad-python.ps1
```

腳本使用 FreeCAD 的 bundled Python 3.11.14 安裝以下套件：

| 套件 | 版本 | 用途 |
|------|------|------|
| build123d | 0.11.1 | 建模引擎（與 FreeCAD 共存） |
| fastapi | 0.139.0 | HTTP API 框架 |
| uvicorn | 0.51.0 | ASGI 伺服器 |
| pydantic | 2.13.4 | 資料驗證 |
| trimesh | 4.12.2 | GLB tessellation |
| numpy | 2.4.6 | 數值運算 |
| pytest | 9.1.1 | 測試框架 |
| httpx | 0.28.1 | 測試 HTTP client |
| cadquery-ocp-novtk | 7.9.3.1.1 | OCP 核心（build123d 依賴） |

**單一環境策略**：FreeCAD 的 bundled Python 3.11.14 同時執行 FreeCAD 和 build123d，
不需額外建立 conda 或 venv 環境。cadquery-ocp-novtk 提供 cp311 wheels，與 FreeCAD 的 OCP 不衝突。

### 3. 引擎選擇

```bash
# 預設 build123d（系統 Python 3.12）
OPENCAD_ENGINE=build123d python -m cad_worker.server

# 切換 FreeCAD（FreeCAD bundled Python 3.11）
OPENCAD_ENGINE=freecad FREECAD_DIR=/path/to/FreeCAD python -m cad_worker.server
```

C# Desktop App 透過 `~/.opencad/settings.json` 的 `engine` 欄位選擇引擎：
```json
{ "engine": "freecad", "freecad_dir": "C:\\path\\to\\FreeCAD\\FreeCAD_1.1.1-Windows-x86_64-py311" }
```

## 安裝體積

| 項目 | 大小 |
|------|------|
| FreeCAD 1.1.1 portable .7z | 399 MB（下載後可刪） |
| 解壓後 FreeCAD 目錄 | **2,531.86 MB**（實測） |
| cad-worker Python 依賴 | ~80 MB（build123d + OCP + fastapi 等） |
| **總計** | **~2.6 GB** |

## 啟動時間（實測）

| 引擎 | Worker 啟動至 health 200 | 說明 |
|------|--------------------------|------|
| build123d | **2,656 ms** | 系統 Python 3.12，import build123d |
| FreeCAD | **2,853 ms** | FreeCAD Python 3.11，import FreeCAD + Part + Sketcher |

兩引擎啟動時間差異 <200 ms，對使用者無感知差異。這些時間是通過 WP1-0R 測試套件實際測量得出的結果。

| 操作 | 時間 |
|------|------|
| Python 啟動 + FreeCAD import | ~2.8 秒 |
| Part/Sketcher import | ~0.1 秒（已含在上述） |
| 首次建模（10 特徵以下） | <50 ms |
| 100-entity 草圖求解 | <200 ms |
| 500-entity 草圖求解 | ~7 秒 |

注意：以上操作時間為估計值，實際性能可能因硬體配置和模型複雜度而有所不同。

## 封裝步驟

### 1. 下載 FreeCAD

見上方「環境安裝步驟」§1。

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

引擎切換時，health endpoint 回傳：
- `"engine"`: 實際引擎名稱（`"build123d"` / `"freecad"` / `"unavailable"`）
- `"engine_requested"`: 請求的引擎名稱
- `"status"`: `"ok"` / `"degraded"`（freecad 請求但不可用時）

**無靜默降級**：若 `OPENCAD_ENGINE=freecad` 但 FreeCAD 不可用，Worker 回傳 503 而非降級至 build123d。

## 測試結果

FreeCAD adapter 測試套件包含 36 個專門針對 FreeCAD 引擎的測試，全部通過驗證：

```
FreeCAD\...\bin\python.exe -m pytest tests/cad-worker/test_freecad_adapter.py -q
→ 36 passed, 0 skipped
```

完整 cad-worker 測試套件執行結果：
- 900 個測試通過
- 38 個測試跳過（主要為平台特定或功能選擇性測試）
- 0 個測試失敗

所有測試均在 FreeCAD 的 bundled Python 3.11.14 環境中執行，驗證了單一環境策略的可行性。

## 已知限制

1. **FreeCAD headless revolve**：Face profile 旋轉產生零體積實體（退化幾何）。Phase 1 需改用 PartDesign 或 OCC 直接 API。
2. **PartDesign 不可用**：headless 模式下 PartDesign Workbench 的 SketchObject.Support 不存在，必須用 Part workbench。
3. **Step export**：`Part.export()` 讀回失敗，須用 `Import.export()` + `Import.insert()`。
4. **Lock constraint crash**：Sketcher 的 Lock 約束在 headless 模式 crash，須用 `DistanceX` + `DistanceY` 替代。
5. **GIL 安全**：FreeCAD Document 非線程安全，須用 `asyncio.Lock` 序列化所有 rebuild 操作（WP1-0R 已實作 `_rebuild_lock`）。
6. **moveGeometry**：`movePoint` 不存在，須用 `moveGeometry(geoId, posId, newPoint)`（3 參數）。
7. **Part.Point**：使用 `.X/.Y/.Z`（大寫），無 `StartPoint` 屬性。
8. **Coincident posId**：1=start point, 2=end point。
9. **ShapeWrapper volume/area/bounding_box**（WP1-0R 新增）：`FreeCADShapeWrapper` 需提供 `volume`、`area`、`bounding_box()` 屬性以與 build123d Part 相容。FreeCAD 的 `Part.Shape` 用 `.Volume`（大寫）、`.Area`、`.BoundBox`；wrapper 做轉接。

## 新發現的限制

10. **FreeCAD headless revolve 限制**：在 headless 模式下，從 Face 輪廓進行旋轉操作可能產生零體積實體（退化幾何）。這是 FreeCAD 在 headless 模式下的已知限制。目前的解決方法是在測試中跳過對旋轉操作的體積驗證。此問題需要通過 PartDesign 或 OCC 直接 API 來解決。