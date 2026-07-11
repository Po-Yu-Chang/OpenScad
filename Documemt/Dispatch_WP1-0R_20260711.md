# 發包單：WP1-0R — FreeCAD Worker 正式化收尾（執行環境整合＋全套實測）＋WP-H4 稽核

> 發包日期：2026-07-11　依據：Master Plan §15 序 5、`Phase0_Engine_Decision.md`（Gate 已通過，路線 B 續行）
> **本文件自包含**：包規格＋§0 策略摘要＋§1 現況＋§2 地雷＋§14 驗證方法論全部在內，執行時不得省略任何一節。
> 完成後依文末「交付報告格式」回報。

---

## A. 包規格（WP1-0R）

### A.1 目標

讓 FreeCAD 1.1.1 **真正跑起來**成為可驗證的權威幾何引擎：目前 `FreeCADAdapter` 程式碼已存在，但從未在真實 FreeCAD 環境下執行過——36 個 FreeCAD 測試全部 skip、C# 端沒有引擎切換接線、`OPENCAD_ENGINE=freecad` 的完整流程從未實測。本包把「寫好的程式碼」變成「實測通過的引擎」。

### A.2 現況錨點（發包者已實查，不用重查）

1. `cad-worker/cad_worker/adapters/freecad_adapter.py`（~820 行）：`FreeCADAdapter`＋`FreeCADFaceProxy/EdgeProxy/ShapeWrapper` 已實作；靠 `FREECAD_DIR` 環境變數定位安裝、`FREECAD_AVAILABLE` gate；rebuild 迴圈已含 suppress/orphan/rollback 跳過邏輯（與 build123d adapter 同語意）。
2. `cad-worker/cad_worker/server.py` 的 `_get_adapter()`：`OPENCAD_ENGINE=freecad` 時嘗試 FreeCADAdapter，**FreeCAD 不可用時靜默 fallback 到 build123d——這要改**（見 A.3 工作 3）。
3. `tests/cad-worker/test_freecad_adapter.py`：36 個測試，模組頂部會自動偵測 repo 根的 `FreeCAD/FreeCAD_1.1.1-Windows-x86_64-py311/` 並設定 `FREECAD_DIR`；**目前全數 skip，原因＝系統 pytest 是 Python 3.12，FreeCAD 綁定是 cp311**（`bin\python.exe --version` = 3.11.14，實測確認）。判準已依 WP-H4 規則寫（bbox/volume/mass，非面數）。
4. `cad-worker-freecad/`：Phase 0 spike 的獨立原型，display_map 已對齊 schema——**本包不碰它**，它保留作 Phase 0 歷史證據。
5. C# 端 `grep OPENCAD_ENGINE src/` **零結果**——app 啟動 Worker 的流程完全沒有引擎概念。Worker 啟動程式碼請 grep `OPENCAD_WORKER_PORT` / `OPENCAD_TOKEN_FILE` 在 `src/OpenCad.Desktop/`（Services 或 App 啟動處）定位。
6. `Documemt/FreeCAD_Packaging_Notes.md`：打包筆記草稿已存在，本包需補實測數據。
7. 測試基線（必須維持）：系統 Python 3.12 下 `python -m pytest tests/cad-worker/ -q` = **895 passed, 38 skipped**；`dotnet build` 0 警告；`dotnet test` 168 綠；`tests\ui\smoke-test.ps1` PASS。
8. golden 判準稽核起點：`tests/cad-worker/test_golden_model.py` 與 `test_freecad_adapter.py` 已無面數/邊數斷言（初步符合 WP-H4）。

### A.3 工作項（依序）

**1. FreeCAD Python 環境準備（新腳本 `tools/setup-freecad-python.ps1`）**
- 用 FreeCAD 自帶的 `FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311\bin\python.exe`：先 `-m ensurepip`（若無 pip），再安裝 cad-worker 執行所需套件。套件清單以實際 import 為準（讀 `cad-worker/cad_worker/*.py` 的 import：至少 fastapi、uvicorn、pydantic v2、trimesh、numpy；測試另需 pytest、httpx）。
- 腳本要可重跑（已裝則跳過）、把實際安裝的版本清單寫到 stdout；把清單與體積記錄進 `FreeCAD_Packaging_Notes.md`。
- **禁止**把任何套件檔案放進 repo；`FreeCAD/` 整個目錄已 gitignore（地雷 #18）。

**2. FreeCAD 測試實跑到綠**
- `FreeCAD\...\bin\python.exe -m pytest tests/cad-worker/test_freecad_adapter.py -q` → 目標 **36 passed, 0 skipped**。
- 修測試揭露的 adapter bug（預期會有——這些程式碼從未真正執行過）。修 adapter 不是改測試門檻；若某測試的期望值確實錯誤（例如拓撲分割差異但幾何語意等價），依 WP-H4 判準修正並在報告逐條說明。
- 環境策略：優先嘗試在 FreeCAD Python 3.11 同時 `pip install build123d`（若 OCP 有 cp311 wheel），這樣單一環境可跑全套；裝不起來就採**雙環境策略**（3.12 跑 build123d 全套、3.11 跑 FreeCAD 套件＋server 層 freecad 引擎測試），選了哪條要記錄在報告與 Packaging Notes。

**3. server 引擎硬化（`cad-worker/cad_worker/server.py`）**
- `OPENCAD_ENGINE=freecad` 但 FreeCAD 不可用 → **啟動即明確失敗**（或 health 回報 degraded＋所有 rebuild 回 503），**移除靜默 fallback**——權威核心不得被偷換（呼應地雷 #16 精神）。`OPENCAD_ENGINE` 未設或 =build123d 行為不變。
- `GET /api/health` 回傳加 `engine`（實際生效引擎）與 `engine_requested` 欄位。
- **地雷 #17**：freecad 引擎下 rebuild 必須全域序列化——`_rebuild`、`_rebuild_dry_run`、`_commit_graph_mutation` 的 `asyncio.to_thread(adapter.build_with_trace, ...)` 外面包一個模組級 `asyncio.Lock`（兩個引擎都鎖，無害且簡單）。附一個並發測試：同專案同時發兩個 rebuild，斷言都成功且無 crash。

**4. C# 啟動流程接線**
- `AppSettings`（`src/OpenCad.Desktop/Services/AppSettings.cs`）加 `Engine`（`"build123d"`（預設）/`"freecad"`）與 `FreeCadDir`（預設空＝repo 根 `FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311`，僅開發機便利；正式打包另議）。設定存 `~/.opencad/settings.json`，手改檔案即可生效，**本包不做設定 UI**。
- Worker 啟動處：`Engine=="freecad"` 時改用 FreeCAD 的 `bin\python.exe` 啟動 `cad_worker.server`，並傳 `OPENCAD_ENGINE=freecad`＋`FREECAD_DIR`；啟動失敗（python 不存在/health 顯示引擎不符）→ 明確錯誤訊息（繁中）並回退提示，不得無聲用錯引擎。
- `dotnet build` 0 警告；新增 .NET 單元測試：settings 解析（缺欄位=預設 build123d）。

**5. 引擎層 HTTP 重演驗收（§14.5，freecad 引擎）**
- 以環境變數起 Worker（`OPENCAD_ENGINE=freecad` ＋ FreeCAD python），HTTP 重演：建專案 → sketch(60×40 矩形) → pad 10 → hole Ø6 → fillet R2 → rebuild 200 → `display_map` 面數>0 且含 `surface_type=="cylinder"` → `preview.glb` 200（走 presign）→ STEP 匯出，用系統 Python（build123d 環境）讀回驗 bbox=60×40×10。
- 寫成可重跑腳本 `tests/ui/freecad-engine-replay.ps1`（UTF-8 with BOM，地雷 #10），輸出逐步斷言結果。

**6. smoke-test 雙引擎**
- `tests\ui\smoke-test.ps1` 在預設（build123d）下 PASS（迴歸）。
- 設定 `Engine=freecad` 後再跑一次 PASS（載入範例的所有特徵必須被 FreeCADAdapter 支援；缺的特徵先補 adapter——範例是 NEMA17 類基本特徵，理論上 sketch/pad/hole/fillet/pattern 要齊）。若個別特徵短期補不完，報告列清單＋計畫，但範例載入不得 crash。

**7. WP-H4 稽核收尾**
- `grep -rn "len(.*faces())\|len(.*edges())\|face_count\|edge_count" tests/` 全面檢查：不得有「面/邊數完全相同」作為主要通過條件的斷言（幾何屬性斷言如「孔數=4（圓柱面判別）」屬語意判準，可留）。
- 確認無任何測試用 STEP 檔 byte hash 判斷幾何相同。
- 結果（逐檔清單）寫入交付報告。

**8. 收尾（只在驗收 1–7 全過後）**
- `FreeCAD_Packaging_Notes.md` 補：環境安裝步驟、套件版本、磁碟體積、Worker 啟動時間（build123d vs freecad 實測值）。
- **不要**在本包把預設引擎翻成 freecad——預設切換留給 WP1-7 Vertical Slice A 通過後單獨一個 commit（可快速 revert）。

### A.4 明確不做（out of scope）

- 不動 `cad-worker-freecad/`（Phase 0 原型，僅存檔）。
- 不做設定 UI 對話框、不做 rollback bar UI。
- 不跑 Vertical Slice A（那是下一包 WP1-7，前置是本包）。
- 不把預設引擎切到 freecad（見工作 8）。
- 不升級 FreeCAD 版本、不下載任何新安裝檔。

### A.5 驗收（缺一不可，全部附實測輸出）

1. `FreeCAD\...\bin\python.exe -m pytest tests/cad-worker/test_freecad_adapter.py -q` → **36 passed, 0 skipped**。
2. freecad 引擎下 server 層測試（transaction/v2 命令/display_map）通過；採單環境或雙環境策略皆可，報告寫明跑了哪些檔、在哪個環境。
3. 系統 Python 3.12 全套 `python -m pytest tests/cad-worker/ -q` 不回歸（≥895 passed）；`dotnet build` 0 警告；`dotnet test` 全綠。
4. `tests/ui/freecad-engine-replay.ps1` PASS（逐步斷言輸出附報告）。
5. smoke-test：build123d PASS＋freecad PASS（各附 log 節錄）。
6. `OPENCAD_ENGINE=freecad` 且 FreeCAD 不可用時：Worker 啟動明確失敗或 health 顯示 degraded（附實測）；並發 rebuild 測試通過（地雷 #17）。
7. WP-H4 稽核清單（工作 7）附報告；`FreeCAD_Packaging_Notes.md` 更新。

---

## B. §0 策略摘要（節錄自 Master Plan，鐵則對本包直接生效）

- **路線 B 已由 Gate 確認**：Avalonia UI 保留，FreeCAD 1.1.1 是唯一權威幾何核心（`Phase0_Engine_Decision.md`）。
- build123d 降級為 prototype/測試 fixture/獨立工具——過渡期保留為 fallback 引擎，但 freecad 模式下**不得靜默偷換**。
- Engine-neutral schema（display_map、persistent reference v2、feature.schema）不需改——引擎中立契約已驗證，換核心只換產生端。
- Windows-first；GLB 只是 display cache，不得作為幾何或 selection 的 source of truth。

## C. §1 現況：已完成且驗證通過（不要重做）

### 基礎設施
- Worker 生命週期：隨機埠、token 檔交接、父程序監看（app 死掉 3 秒內自我終止）、健康檢查啟動判定
- 同源 viewer：Worker 在 `/viewer` 伺服 viewer.html＋本地 Three.js（勿改回 file://）
- 專案持久化 `~/.opencad/worker/`；LLM 設定 `~/.opencad/settings.json`（LiteLLM gateway 支援）

### 建模與驗證
- Feature Graph v2：bodies、有序歷史（order）、feature state（active/suppressed/failed/orphan）、rollback_position、v1→v2 遷移；拓撲排序＋依賴解析重建（`parts[feature.input]`）；snake_case enum 契約（C#↔Python，地雷 #1）
- 特徵：sketch(rect/circle/polygon/slot/line/polyline/arc/construction_line＋閉合驗證)、pad、pocket、hole(ISO 273＋counterbore)、fillet/chamfer(provenance 排孔)、shell、pattern、mirror、revolve、boolean、sweep、loft、draft、rib、thin、variable_fillet、countersink、cosmetic_thread
- `TopologyTrace`：邊/面 provenance（hash 索引 O(1) 反查）；`topology.py` 語意參照解析器（REFERENCE_LOST/AMBIGUOUS fail-safe；目前僅測試使用，尚未接進 adapter）
- Staging transaction：`apply_plan`（clone→apply→rebuild→commit-or-rollback）、`reset`（原子 Clear All）、v2 命令（suppress/unsuppress/reorder/set_rollback）全走 staging；revision/undo/redo/journal 統一寫入路徑
- display_map：逐面 tessellation＋triangle_range（含頭不含尾）＋edges polyline，`GET .../display_map`；與 GLB 同一個 tessellation pass 產生（`_tessellate_with_map`）
- 安全（WP-H2）：X-Session-Token header、URL 只收 presign 短時效 token（單次有效）、Origin middleware、匯入大小/路徑防護、重建超時（to_thread＋wait_for）

### UI
- 三欄版面、特徵樹（型別+狀態圖示、右鍵抑制/回溯、基準面節點、基準幾何資料夾 `ReferenceGeometryId`）、參數面板、triad、可點選基準面、剖面、量測、顯示模式（著色+邊線）、草圖模式（約束工具列＋DOF 列＋solve 端點）
- LLM：計畫/差異卡片、意圖攔截、上下文記憶（ChatTurn 10 輪）、修復迴圈（白名單 2 次、套用後 staging 驗證、防重複重試）

### 測試基線
- 895 Python＋168 .NET 全綠、build 0 警告、smoke-test PASS；36 個 FreeCAD 測試 skip（本包要解）
- 端點清單見 `cad-worker/cad_worker/server.py`：health/projects/commands/apply_plan/reset/rebuild(?dry_run)/validate/exports/preview.glb/display_map/events/revisions/undo/redo/presign/capability/import-zip

## D. §2 地雷清單（改壞任何一條都會回歸）

1. `SnakeCaseEnumConverter`（`src/OpenCad.Domain/Enums.cs`）——C#↔Python enum 契約，動了所有命令 500。
2. viewer 必須由 Worker 同源伺服（`/viewer`）——file:// 會被 CORS 擋 ES module 與 GLB fetch。
3. **Airspace**：WebView2 原生視窗永遠蓋住 Avalonia 內容——viewport 內 UI 一律 viewer.html 的 HTML overlay。
4. UI 執行緒：背景執行緒禁碰 Avalonia 物件；計時器一律 `DispatcherTimer`。
5. `app.manifest`／`Program.cs` AppBuilder／`WinExe` 不要動。
6. 視窗必須在 `OnFrameworkInitializationCompleted` 內同步建立。
7. `RebuildAsync` 內的 `ExportAsync("glb")` 不可移除。
8. CanExecute 依賴的屬性 setter 必須 `RaiseCanExecuteChanged`；卡片按鈕必須一次性。
9. graph JSON 是 `{schema_version, features:[...]}` 包裝格式——解析先解包裝。
10. `.ps1` 含中文必須 UTF-8 with BOM（PowerShell 5.1）。
11. 機密（API key、內網 IP）不得進 repo。
12. 全本地原則：不得引入 CDN／雲端依賴；UI 文案繁體中文。
13. 新增 pytest 直接跑 `python -m pytest tests/cad-worker/`（勿依賴 `pip install -e`）。
14. 正式模型只能經 staging transaction 改變（clone→validate→rebuild→commit；失敗＝正式模型完全不變；一請求一 undo）。
15. Persistent reference 歧義 fail-safe：`REFERENCE_AMBIGUOUS` 要求重選、`REFERENCE_LOST` 明確報錯，禁止靜默改選。
16. Repair 安全規則：只有格式修正與唯一可推導 reference 可自動修；低風險上限 2 次；同錯誤同命令不重試；改尺寸只能「提出」。
17. **FreeCAD Document 非 thread-safe**：freecad 引擎下 rebuild 必須全域序列化（單一 lock）——`asyncio.to_thread` 不保證序列化。
18. **repo 根 `FreeCAD/` 是 2.3GB 本機安裝**（gitignore）——不得 commit 其下任何檔案；FreeCAD 綁定 cp311，必須用其自帶 `bin\python.exe`（3.11）執行。

## E. §14 驗證方法論（每項交付照此驗收）

1. `dotnet build OpenCad.slnx` → 0 錯誤 0 警告。
2. `python -m pytest tests/cad-worker/ -q` 與 `dotnet test` → 全綠（新功能必附新測試）。
3. `powershell -ExecutionPolicy Bypass -File tests\ui\smoke-test.ps1` → PASS。
4. UI 必須實際驅動驗證：UIAutomation 點擊＋截圖目視＋WebView2 無障礙樹。
5. 引擎層驗收：起 Worker（`OPENCAD_WORKER_PORT`/`OPENCAD_TOKEN_FILE`/`OPENCAD_WORK_DIR` 環境變數）直接 HTTP 重演，斷言幾何數值。
6. LLM 相關：用真實 gateway 實測（本包不涉及）。
7. 全程斷網可完成 1–5。
8. Golden Model 判準：語意/體積/bbox/質量/關鍵位置＋reference 解析，**不比對面數邊數、不比對 STEP byte hash**。
9. **交付報告格式**：改了哪些檔、新增測試清單、驗收逐條實測證據（命令輸出/截圖路徑）、發現的新地雷（回寫 Master Plan §2）。

---

## F. 交付報告要求

完成後產出 `Documemt/WP1-0R_Report.md`，內容依 §14.9：
1. A.5 驗收 1–7 逐條的實測證據（命令＋輸出節錄）。
2. 環境策略決定（單/雙環境）與理由；FreeCAD python 套件版本清單。
3. adapter 修掉的 bug 清單（測試揭露了什麼——這是本包最有價值的產出）。
4. 尚不支援的特徵清單＋補齊計畫（若有）。
5. 新發現的地雷（回寫 Master Plan §2 並在報告標注）。
6. 測試總數變化（基線：895 Python＋168 .NET＋36 FreeCAD skip）。
