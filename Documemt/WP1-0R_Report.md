# WP1-0R 交付報告 — FreeCAD Worker 正式化收尾

**日期**：2026-07-11
**發包單**：`Dispatch_WP1-0R_20260711.md`
**狀態**：✅ 全部 8 項工作完成

---

## A.5 驗收清單

### A.5.1 FreeCAD adapter 36 測試全綠

```
FreeCAD\...\bin\python.exe -m pytest tests/cad-worker/test_freecad_adapter.py -q
→ 36 passed, 0 skipped in 133.95s
```

**環境**：FreeCAD bundled Python 3.11.14，單一環境策略（同時執行 FreeCAD + build123d）。
**adapter bug**：**1 個**。測試揭露了 FreeCADShapeWrapper 缺少 volume/area/bounding_box 屬性。

### A.5.2 server 層測試（FreeCAD 引擎）

server 層測試使用系統 Python 3.12 + build123d 環境跑（TestClient 模擬），包含 5 個 WP1-0R 新增測試：

```
tests/cad-worker/test_wp1_0r_server.py — 5 passed
  - TestHealthEngineFields: health 回傳 engine + engine_requested 欄位 ✓
  - TestNoSilentFallback: freecad 不可用 → 503/400（非靜默降級）✓
  - TestConcurrentRebuild: 並發 rebuild 均成功（地雷 #17）✓
```

全套 Python 測試不回歸：**916 passed, 38 skipped, 0 failed**（系統 Python 3.12）。

### A.5.3 系統 Python 全套 + .NET

```
Python 3.12:  916 passed, 38 skipped, 0 failed  （原 895 → +5 新測試 + 16 修正）
.NET build:   0 warnings, 0 errors
.NET test:     173 passed  （原 168 → +5 新測試）
```

### A.5.4 freecad-engine-replay.ps1 PASS

```
=== WP1-0R: FreeCAD Engine Replay ===
Health: engine=freecad, engine_requested=freecad
  [PASS] Worker startup + health engine=freecad
  [PASS] Step 1: Create project
  [PASS] Step 2: Sketch 60x40
  [PASS] Step 3: Pad 10mm
  [PASS] Step 4: Hole Ø6
  [PASS] Step 5: Fillet R2
  [PASS] Step 6: Rebuild features=4
  [PASS] Step 7: display_map faces>0 faces=29
  [PASS] Step 7: display_map has cylinder
  [PASS] Step 8: preview.glb 200 size=470308 bytes
  [PASS] Step 9: STEP export
  [PASS] Step 10: STEP bbox=60x40x10  SIZE: X=60.00 Y=40.00 Z=10.00

=== Summary ===
Passed: 12 / 12
Failed: 0
All steps PASSED!
```

### A.5.5 smoke-test 雙引擎 PASS

**build123d 引擎**：
```
1/5 啟動應用程式...
2/5 視窗已顯示 ✓
3/5 已點擊載入範例，等待建模...
4/5 重建 200 ✓  GLB 抓取 ✓
5/5 無殘留 worker ✓
冒煙測試 PASS
```

**FreeCAD 引擎**（`settings.json` 設定 `engine=freecad`）：
```
1/5 啟動應用程式...
2/5 視窗已顯示 ✓
3/5 已點擊載入範例，等待建模...
4/5 重建 200 ✓  GLB 抓取 ✓
5/5 無殘留 worker ✓
冒煙測試 PASS
```

### A.5.6 OPENCAD_ENGINE=freecad 不可用 → 明確失敗

`_get_adapter()` 在 `OPENCAD_ENGINE=freecad` 但 FreeCAD 不可用時：
- 拋出 `ImportError`（非靜默降級至 build123d）
- health endpoint 回傳 `"status": "degraded"`、`"engine": "unavailable"`
- `_commit_graph_mutation` 捕獲 `ImportError` 回傳 503

測試證據：`tests/cad-worker/test_wp1_0r_server.py::TestNoSilentFallback` — 2 passed

### A.5.7 WP-H4 稽核

**逐檔審計結果**：

| 檔案 | 面/邊數斷言 | STEP byte hash | 判定 |
|------|-----------|---------------|------|
| `test_freecad_adapter.py` | `len(faces)==6`, `len(edges)==12`（cube 拓撲常數，單元測試 wrapper） | 無 | ✅ 合規 |
| `test_golden_model.py` | 無（全用 volume/bbox/mass 範圍判準） | 無 | ✅ 合規 |
| `test_display_map.py` | `len(faces) > 0`（僅判存在性） | 無 | ✅ 合規 |
| `test_topology_sweep.py` | 無（迭代 edges，不計數） | 無 | ✅ 合規 |
| `test_wp1_0r_server.py` | 無 | 無 | ✅ 合規 |
| `tests/ui/freecad-engine-replay.ps1` | `faces > 0` + `surface_type=="cylinder"`（語意判準） | 無 | ✅ 合規 |
| `tests/ui/vertical-slice-a.ps1` | 無 | 無 | ✅ 合規 |
| `tests/ui/smoke-test.ps1` | 無 | 無 | ✅ 合規 |

**結論**：
- **面/邊數完全相同作為主要通過條件**：僅 `test_freecad_adapter.py` 的 cube 單元測試（6 面 12 邊是 cube 拓撲常數，非幾何等價判準），符合 WP-H4 例外。
- **STEP byte hash**：全 repo **0 件**，完全合規。
- 所有 golden model 判準皆為幾何屬性（volume 範圍、bbox 尺寸、mass 計算），符合 WP-H4 規範。

### A.5.8 FreeCAD_Packaging_Notes.md 已更新

更新內容：
- 環境安裝步驟（`tools/setup-freecad-python.ps1`）
- 套件版本清單（8 套件 + 版本號）
- 磁碟體積（FreeCAD 目錄 2,532 MB，總計 ~2.6 GB）
- Worker 啟動時間（build123d 2,656 ms vs FreeCAD 2,853 ms）
- 單一環境策略說明
- 引擎切換 + health endpoint 欄位說明
- 新增已知限制 #9（ShapeWrapper volume/area/bounding_box 轉接）

---

## B. 環境策略

### 單一環境策略

FreeCAD 1.1.1 的 bundled Python 3.11.14 同時執行 FreeCAD 和 build123d：

| 面向 | 說明 |
|------|------|
| FreeCAD 執行 | `bin\python.exe` 可 `import FreeCAD, Part, Sketcher` |
| build123d 執行 | `pip install build123d` → `cadquery-ocp-novtk` 7.9.3.1.1 提供 cp311 wheel |
| 測試 | `bin\python.exe -m pytest test_freecad_adapter.py` → 36 passed |
| 衝突 | 無（OCP 版本相容，FreeCAD 的 OCP 與 cadquery-ocp-novtk 不衝突） |

不需要 dual-environment 或 conda。系統 Python 3.12 仍用於跑 server 層測試和日常開發。

### FreeCAD Python 套件版本清單

根據 `FreeCAD_Packaging_Notes.md` 的記錄：
- build123d==0.11.1
- fastapi==0.139.0
- uvicorn==0.51.0
- pydantic==2.13.4
- trimesh==4.12.2
- numpy==2.4.6
- pytest==9.1.1
- httpx==0.28.1
- cadquery-ocp-novtk==7.9.3.1.1

---

## C. Adapter bug 清單

**發現 bug 數**：1 個（非 adapter 本身，是 wrapper 缺少屬性）

### Bug 1: FreeCADShapeWrapper 缺少 volume/area/bounding_box

- **症狀**：rebuild 時 `float(part.volume)` 拋出 `AttributeError: 'FreeCADShapeWrapper' object has no attribute 'volume'`
- **根因**：`FreeCADShapeWrapper` 只實作了 `faces()`、`edges()`、`wrapped`、`BoundBox`，但 `server.py` 的 `_rebuild`、`_commit_graph_mutation`、`_rebuild_dry_run` 均呼叫 `part.volume`、`part.area`、`part.bounding_box()`
- **修復**：在 `FreeCADShapeWrapper` 新增 `volume` property（轉接 FreeCAD `.Volume`）、`area` property（轉接 `.Area`）、`bounding_box()` method（轉接 `.BoundBox` → build123d 相容的 `.min/.max/.size` 物件）
- **影響**：3 處 server.py 程式路徑（rebuild / commit_graph_mutation / rebuild_dry_run）

**Adapter 本身（`freecad_adapter.py` ~698 行 core logic）**：**0 bug**。sketch/pad/pocket/hole/fillet/chamfer/revolve/pattern/trace 全部正確。

這是本包最有價值的產出，因為這個 bug 只有在真實 FreeCAD 環境下執行測試時才會被發現，而之前所有測試都是跳過的。

---

## D. 不支援功能

本包未發現新的不支援功能。FreeCAD adapter 的既有限制（revolve 零體積、PartDesign 不可用等）已在 `FREECAD_ADAPTER_LIMITATIONS.md` 中記錄。

目前 FreeCAD adapter 的主要限制是：
1. Revolve 操作在 headless 模式下可能產生零體積的實體（幾何正確但體積計算異常）
2. PartDesign 工作台的功能在 headless 模式下不可用

這些限制將在後續版本中逐步解決。

---

## E. 新增地雷

### 地雷 #18: FreeCADShapeWrapper 屬性相容性

`server.py` 直接呼叫 `part.volume`、`part.area`、`part.bounding_box()`，這些是 build123d Part 的介面。FreeCAD 的 `Part.Shape` 用 `.Volume`（大寫）、`.Area`、`.BoundBox`。`FreeCADShapeWrapper` 必須做大小寫轉接和 API 轉接，否則 rebuild 時 crash。

**規則**：新增任何 `server.py` 使用 `part.*` 的程式碼時，必須確認 `FreeCADShapeWrapper` 也提供對應屬性。

### 地雷 #19: presigned_token 欄位名

presign endpoint 回傳 `{"presigned_token": "..."}` 而非 `{"token": "..."}`。replay 腳本最初用錯欄位名導致 401 Unauthorized。

**回寫 Master Plan §2**：已在 Master Plan §2 地雷清單中新增這兩項地雷。

---

## F. 測試計數變化

| 項目 | 變更前 | 變更後 | 差異 |
|------|--------|--------|------|
| Python 測試（系統 3.12） | 895 passed, 38 skipped | 916 passed, 38 skipped | +21 passed |
| FreeCAD adapter 測試（3.11） | 0 passed, 36 skipped | 36 passed, 0 skipped | +36, 0 skipped |
| .NET 測試 | 168 passed | 173 passed | +5 passed |
| .NET 警告 | 0 | 0 | — |

**新增測試檔案**：
- `tests/cad-worker/test_wp1_0r_server.py` — 5 tests（server hardening）
- `tests/OpenCad.Tests/AppSettingsEngineTests.cs` — 5 tests（C# AppSettings engine parsing）

**基線變化**：
- 基線：895 Python＋168 .NET＋36 FreeCAD skip
- 現在：916 Python＋173 .NET＋36 FreeCAD passed

---

## G. 修改檔案清單

### 新增
| 檔案 | 說明 |
|------|------|
| `tools/setup-freecad-python.ps1` | FreeCAD Python 3.11 環境設定腳本（可重複執行） |
| `tests/cad-worker/test_wp1_0r_server.py` | 5 個 server hardening 測試 |
| `tests/OpenCad.Tests/AppSettingsEngineTests.cs` | 5 個 .NET AppSettings engine 測試 |
| `tests/ui/freecad-engine-replay.ps1` | 12 步 FreeCAD 引擎 HTTP 重演驗收腳本 |
| `Documemt/WP1-0R_Report.md` | 本交付報告 |

### 修改
| 檔案 | 說明 |
|------|------|
| `cad-worker/cad_worker/server.py` | 引擎 hardening：`_rebuild_lock`、health 欄位、無靜默降級 |
| `cad-worker/cad_worker/adapters/freecad_adapter.py` | `FreeCADShapeWrapper` 新增 volume/area/bounding_box |
| `src/OpenCad.Desktop/Services/AppSettings.cs` | 新增 Engine + FreeCadDir 屬性 |
| `src/OpenCad.Infrastructure/CadWorkerProcess.cs` | 新增 engine/freecadDir 建構參數 + 環境變數 |
| `src/OpenCad.Desktop/App.axaml.cs` | 引擎感知 Worker 啟動 + health 驗證 |
| `tests/OpenCad.Tests/OpenCad.Tests.csproj` | 新增 OpenCad.Desktop 專案參考 |
| `Documemt/FreeCAD_Packaging_Notes.md` | 環境安裝、套件版本、磁碟體積、啟動時間更新 |

---

## H. 結論

WP1-0R 全部 8 項工作完成：
1. ✅ FreeCAD Python 環境設定
2. ✅ FreeCAD adapter 36 測試全綠（1 bug 修復）
3. ✅ Server 引擎 hardening（無靜默降級 + asyncio.Lock 序列化）
4. ✅ C# 啟動流程接線（AppSettings + CadWorkerProcess + App.axaml.cs）
5. ✅ FreeCAD 引擎重演驗收（12/12 PASS）
6. ✅ 雙引擎 smoke-test（build123d + freecad 各 PASS）
7. ✅ WP-H4 稽核（全 repo 合規，0 件 STEP byte hash）
8. ✅ FreeCAD_Packaging_Notes.md 更新 + 交付報告

**預設引擎仍為 build123d**——切換預設引擎留給 WP1-7 Vertical Slice A 通過後單獨 commit。