# OpenCad 總計畫（Master Plan）

> 最後更新：2026-07-11（commit `5400672` 之後；依 `OpenCad_SolidWorks_Gap_Review_20260711.md` 全面改版）
> **Phase 0 Gate 已通過**：路線 B 續行（Avalonia＋FreeCAD 權威核心），見 `Phase0_Engine_Decision.md`。
> 進度速覽：Phase 0 全部✅、包 A/B/C/D✅、WP1-1/1-3/1-5/WP-H2✅、WP1-2/1-4/1-6 部分✅——詳見 §1.5 與 §15 狀態欄。下一包＝WP1-0R（§15 序 5）。
> 定位：**唯一的活文件**——現況、策略、工作包、地雷、驗證方法都在這裡。
> 架構原理見 `OpenCad_Local_AI_CAD_Architecture.md`；差距分析與依據見 `OpenCad_SolidWorks_Gap_Review_20260711.md`（下稱 Gap Review）。
> **本文件的每個「WP-xx / 包x」都是獨立可發包單位**：發包時把該節全文＋§1 現況＋§2 地雷＋§14 驗證方法論一起給執行模型，不得省略。

---

## 0. 產品定位與策略決定（2026-07-11 依 Gap Review 重訂）

### 0.1 定位聲明（對外對內一致，不再宣稱「取代 SolidWorks」）

> **OpenCad 是一套全本地、AI 原生、以機械單零件與自動化設備設計為優先的參數化 CAD；保留 SolidWorks 類的草圖、特徵、組立與工程圖工作方式，並用工程語言大幅減少操作步驟。**

三層目標，驗收與宣稱都要分開，不得混用：

| 層級 | 內容 | 對應 Phase |
|---|---|---|
| MVP | 人工＋AI 都能編輯的 fully-constrained 單零件，拓撲參照能存活參數變更 | Phase 0–1 |
| Daily CAD | 多 Body、方程式、組態、組立、BOM、基本工程圖、鈑金/焊件 | Phase 2–4 |
| Long-term parity | MBD/PMI、模具、CAM/FEA、PDM | Phase 5（不排時程） |

### 0.2 引擎路線決定（Gap Review §3 的四條路線）

**採用假設：路線 B——保留現有 Avalonia UI，FreeCAD 1.0+ 成為唯一權威幾何核心（authoritative source of truth）。**
Phase 0 以 Kill Test 驗證此假設；若 Kill Criteria 觸發，**降級改走路線 A（FreeCAD AI Workbench）**，Avalonia 資產封存。

隨之生效的鐵則（寫進所有後續發包）：

1. **build123d 降級**：只用於快速 prototype、測試 fixture、獨立幾何工具。**不再是未來正式 source of truth**，不承諾任何 feature 能在 build123d 與 FreeCAD 之間無損切換。
2. Engine-neutral schema 只保存 OpenCad 真正支援的語意，不追求兩引擎能力的最小公分母。
3. **真正的 Sketch Solver 是 MVP P0**，不是後續功能。「約束只存 metadata、座標由 LLM/程式算」的做法**永久禁止**（Gap Review §4）。
4. Windows-first；核心保持可攜，macOS/Linux 正式發行延後。
5. GLB 只是 display cache，**不得**作為幾何或 selection 的 source of truth（Gap Review §15）。

### 0.3 優先序調整（依使用情境：機台、治具、外殼、軌道、機構、倉儲設備）

**提前**：真草圖求解、Reference geometry、Multi-body、Configurations/Equations、組立與 mates、BOM/custom properties、基本工程圖、鈑金、焊件。
**延後**（§13 有完整清單）：單張圖片轉 3D、VLM 審美判斷、多 Agent 分工、macOS/Linux 完整安裝體驗。

### 0.4 工期現實（發包排程用，不是行銷數字）

單人開發：可日常使用的單零件 CAD 約 12–24 個月；基本組立＋BOM＋工程圖約 2–4 年。每個 Phase 末端都有 Gate，不通過不得往下發包。

---

## 1. 現況：已完成且驗證通過

以下全部經過實測（UIAutomation 實際點擊／引擎層 HTTP 重演／截圖目視），**不要重做**：

### 基礎設施
- Worker 生命週期：隨機埠、token 檔交接、父程序監看（app 死掉 3 秒內自我終止，無殭屍）、健康檢查啟動判定
- 同源 viewer：Worker 在 `/viewer` 伺服 viewer.html＋本地 Three.js（勿改回 file://，CORS 會擋 ES module）
- 專案持久化：`~/.opencad/worker/`，重啟自動載回（含 `_current_rev` 還原）
- LLM 可設定：`~/.opencad/settings.json`（provider: auto/openai/ollama/none）；`OpenAiCompatibleLlmProvider` 支援 LiteLLM Gateway；檔案選單「LLM 設定…」「重新偵測 LLM」

### 建模與驗證
- Feature Graph：拓撲排序、循環防護、依賴解析重建（`parts[feature.input]`，**已移除隱式 current_solid**）、snake_case enum 契約（C#↔Python）
- 特徵：sketch(rect/circle/polygon/slot/line/polyline/arc/construction_line＋閉合驗證 `SKETCH_NOT_CLOSED`)、pad、pocket、hole(ISO 273 查表＋counterbore)、fillet/chamfer(邊選擇器＋exclude_holes provenance)、shell、pattern、mirror、revolve、boolean、sweep、loft
- `TopologyTrace`（`cad-worker/cad_worker/adapters/build123d_adapter.py:40`）：重建過程記錄每個特徵建立/修改的邊，`_select_edges` 已用 provenance＋DSL
- 驗證器：實體數、bbox(XYZ)、體積、孔數、壁厚(warning)；質量屬性（12 材質密度表、`calculate_mass`、`set_material`、UI 狀態列顯示）
- 版本控制：revisions 快照、undo/redo(含 redo 分支捨棄、undo 到 rev 0)、Ctrl+Z/Y
- **Staging Transaction（Gap Review §7 前半已落地）**：`FeatureGraph.clone()`；`POST /api/projects/{id}/apply_plan`（clone→apply→rebuild→commit-or-rollback，失敗正式模型不變）；`POST /api/projects/{id}/reset`（Clear All＝一筆 transaction、一筆 undo）；`MainViewModel.ApplyPlanAsync` 整批單一 transaction
- **Typed Command 契約**：`src/OpenCad.Application/CommandValidator.cs`＋`cad-worker/cad_worker/validators/command_validator.py` 對稱驗證，已接入 `ApplyPlanAsync`/`ApplyDiffAsync`/`apply_command`

### UI（Zoo 式版面＋SolidWorks 慣例）
- 三欄可調(GridSplitter)、特徵樹(型別圖示＋右鍵選單＋常駐基準面節點 `__plane_xy/xz/yz`)、參數面板(可編輯＋✓套用)、主題資源集中
- 對話輸入在右欄底部(airspace 安全區)、viewer 內 HTML 抬頭工具列(視角＋縮放至適合＋剖面：軸/位置/反轉)
- 草圖模式：正交編輯、確認角、PropertyManager 式數值對話框、尺寸標籤、提交走 update_feature(sketch_entities)
- LLM 流程：計畫卡片、修改差異卡片(before/after、一次性按鈕)、意圖攔截(intent interception)、聊天匯出；「把四個孔改成 M5」已用真實 LiteLLM 驗證；修復迴圈 D2（重建失敗→LLM 修正→差異卡片人工確認→上限 3 次）

### 測試
- 109 Python＋149 .NET 全綠（含 18 command_validator、6 server transaction、13 golden-model、7 revisions、5 sweep/loft、5 mass）
- `tests/ui/smoke-test.ps1`：UIAutomation 垂直切片冒煙測試(啟動→點載入範例→rebuild 200→GLB 200→無殘留)
- `tests/prompts/` 固定提示集（無 LLM 環境 skip）

### 端點清單（`cad-worker/cad_worker/server.py`，發包時對照）
`GET /api/health`、`POST /api/projects`、`GET /api/projects[/{id}]`、`POST .../commands`、`POST .../apply_plan`、`POST .../reset`、`POST .../rebuild`、`POST .../validate`、`POST .../exports`、`GET .../preview.glb`、`GET .../events`(SSE)、`GET .../revisions`、`POST .../undo`、`POST .../redo`

### 1.5 2026-07-11 大批次落地（commit `5400672`，經 8+4 agent code review 修正後全綠）

- **Phase 0 全部完成**：WP0-1/0-2（FreeCAD 1.1.1 spike＋solver kill test，報告 `Phase0_FreeCAD_Spike_Report.md`）、WP0-3（display_map＋viewer picking，契約 `schemas/display_map.schema.json`）、WP0-4（v2 語意參照＋569 組 sweep）、WP0-5 Gate **通過→路線 B**（`Phase0_Engine_Decision.md`）
- **包 A**（Avalonia 11.3.18＋事件掛載防禦；⚠中文 IME 驗收 2 仍待人工實測）、**包 B**（ChatTurn 歷史、10 輪/截斷/換專案清空）、**包 C**（triad＋可點選基準面）、**包 D**（sketch plane 欄位）
- **WP1-1** Document Model v2（bodies/order/state/rollback＋遷移）、**WP1-3** 基準幾何、**WP1-5** atomic save/journal/schema 檢查/ZIP 防護、**WP-H2** 安全強化（presign token、Origin middleware、配額）
- **部分完成**：WP1-2（solve 端點＋約束工具列＋DOF 列；拖曳求解 throttle 未實測）、WP1-4（量測、顯示模式、Property Manager 雛形）、WP1-6（draft/rib/thin/variable_fillet/countersink/cosmetic_thread schema+adapter）、WP-H1（capability 端點＋拒絕規則 prompt）、WP1-7（測試腳本 `vertical-slice-a.ps1` 已寫，**未實測跑過**）
- **FreeCAD adapter**（`cad-worker/cad_worker/adapters/freecad_adapter.py`＋`OPENCAD_ENGINE` 切換）已存在，但 **36 個 FreeCAD 測試全 skip**（Python 3.12 vs FreeCAD cp311 綁定）——WP1-0R 的核心工作
- Review 修正 10 項確認問題（401 viewport、suppress 無效、solver 雙重序列化、repair 迴圈、staging 違規等），詳見 commit message
- 測試基線：**895 Python＋168 .NET 全綠、build 0 警告、smoke-test PASS**

---

## 2. 地雷清單（改壞任何一條都會回歸——歷次實測踩過的坑）

1. `SnakeCaseEnumConverter`（`src/OpenCad.Domain/Enums.cs`）——C#↔Python enum 契約，動了所有命令 500。
2. viewer 必須由 Worker 同源伺服（`/viewer`）——file:// 會被 CORS 擋 ES module 與 GLB fetch。
3. **Airspace**：WebView2 原生視窗永遠蓋住 Avalonia 內容——不得疊任何 Avalonia 元素在 viewport 上；viewport 內 UI 一律 viewer.html 的 HTML overlay。
4. UI 執行緒：背景執行緒禁碰 Avalonia 物件；計時器一律 `DispatcherTimer`。
5. `app.manifest`／`Program.cs` AppBuilder／`WinExe` 不要動（SxS 與 native control host 已調通）。
6. 視窗必須在 `OnFrameworkInitializationCompleted` 內同步建立——先 await 再建視窗＝視窗永不顯示。
7. `RebuildAsync` 內的 `ExportAsync("glb")` 不可移除——preview 端點只回傳已生成檔案。
8. CanExecute 依賴的屬性 setter 必須 `RaiseCanExecuteChanged`；卡片按鈕必須一次性（`IsActionable`）。
9. graph JSON 是 `{schema_version, features:[...]}` 包裝格式——所有解析處要先解包裝（特徵樹與 diff 卡片都曾因此空白）。
10. `.ps1` 含中文必須 UTF-8 with BOM（PowerShell 5.1）。
11. 機密（API key、內網 IP）不得進 repo——LLM 設定在 `~/.opencad/settings.json`。
12. 全本地原則：不得引入 CDN／雲端依賴；UI 文案繁體中文。
13. 新增 pytest 直接跑 `python -m pytest tests/cad-worker/`（pytest.ini 已設路徑，勿依賴 `pip install -e`）。
14. **（新）正式模型只能經 staging transaction 改變**：任何新端點/命令若會改 graph，必須走 clone→validate→rebuild→commit 流程；4 步計畫第 3 步失敗＝正式模型完全不變、一個使用者請求＝一筆 undo。
15. **（新）Persistent reference 歧義必須 fail-safe**：rebuild 後同一參照有兩個等價候選時回 `REFERENCE_AMBIGUOUS` 要求重選，**禁止自行猜測**；參照真正消失回 `REFERENCE_LOST`，禁止靜默改選其他面/邊。
16. **（新）Repair 安全規則**：只有「格式修正」與「唯一可推導的 reference」可自動修；改尺寸、刪特徵、重排特徵必須人工確認；同一錯誤＋同一命令不得反覆重試；低風險自動修復上限 2 次。R2 fillet 失敗可「提出」最大可行值，不得直接套用。
17. **（新）FreeCAD Document 非 thread-safe**：freecad 引擎下 rebuild 必須全域序列化（單一 lock）——`server.py` 的 `_rebuild`/`_commit_graph_mutation` 已改走 `asyncio.to_thread`，它**不保證**序列化，兩個並行 rebuild 會 crash；build123d 路徑無此限制但同鎖無害。
18. **（新）repo 根的 `FreeCAD/` 是 2.3GB 本機安裝**（已 gitignore）——任何情況都不得把其下檔案加進 git。FreeCAD 綁定是 cp311，**必須用它自帶的 `bin\python.exe`（3.11）執行**；系統 Python 3.12 import 必失敗（這就是 36 個 FreeCAD 測試 skip 的原因）。
19. **（新）FreeCADShapeWrapper 屬性相容性**：`server.py` 直接呼叫 `part.volume`、`part.area`、`part.bounding_box()`，這些是 build123d Part 的介面。FreeCAD 的 `Part.Shape` 用 `.Volume`（大寫）、`.Area`、`.BoundBox`。`FreeCADShapeWrapper` 必須做大小寫轉接和 API 轉接，否則 rebuild 時 crash。（WP1-0R 新增）
20. **（新）presigned_token 欄位名**：presign endpoint 回傳 `{"presigned_token": "..."}` 而非 `{"token": "..."}`。replay 腳本最初用錯欄位名導致 401 Unauthorized。（WP1-0R 新增）

---

## 3. Phase 0：引擎決策閘門（Kill Tests，總時限 5 週）

**目的**：不是做 Demo，是回答最危險的問題——「Avalonia UI＋FreeCAD 權威核心」到底可不可行。
**Kill Criteria（硬性）**：5 週內若無法同時達成 (a) 穩定 face/edge 選取、(b) headless 草圖建立＋求解＋DOF 診斷、(c) 存檔重開 round-trip 參照不變 → **停止路線 B，改走 FreeCAD Workbench（路線 A），不得繼續擴功能掩蓋核心問題**。
WP0-1 / WP0-2 是 FreeCAD spike（互相依賴，同一人/模型接續做）；WP0-3 / WP0-4 在**現有 build123d stack** 上做（成果引擎無關，換核心後沿用契約）。四包可兩線並行。

### WP0-1：FreeCAD Headless Worker Spike

**目標**：證明 FreeCAD 1.0+ 能以 headless 方式扮演 OpenCad Worker：同風格 HTTP API、建模、匯出、tessellation 帶拓撲對應。

**交付位置**：新資料夾 `cad-worker-freecad/`（獨立 prototype，**不得**接進現有 app、不得動 `cad-worker/`）。

**實作步驟**：
1. 安裝 FreeCAD 1.0.x Windows 版；記錄確切版本號與安裝路徑。啟動方式二擇一並在報告記錄：(a) `FreeCADCmd.exe <script.py>`；(b) 以 Python 匯入 FreeCAD 模組（把 FreeCAD `bin/` 加入 `sys.path`）。優先 (b)，因為可以掛 FastAPI。
2. 起一個最小 HTTP server（沿用現有 Worker 慣例：隨機埠＋token 檔＋`/api/health`），實作端點子集：
   - `POST /api/projects`（建 FreeCAD Document＋PartDesign Body）
   - `POST /api/projects/{id}/commands`：支援 `create_feature` type=sketch/pad/hole/fillet 四種（參數欄位沿用 `schemas/feature.schema.json` 現有欄位名，不發明新名字）
   - `POST /api/projects/{id}/rebuild`、`POST /api/projects/{id}/exports`（STEP＋GLB）
3. Sketch 用 FreeCAD `Sketcher`：幾何用 `addGeometry`、約束用 `addConstraint`（Coincident/Horizontal/Vertical/Distance/Radius 至少五種），尺寸驅動用 `setDatum`。
4. Tessellation 帶對應：逐 `Shape.Faces[i].tessellate(0.1)` 取得每面三角形，串接時記錄 `triangle_range`，輸出 §WP0-3 定義的 `display_map.json` 同格式。
5. 存檔（`.FCStd`）→ 關閉 → 重開 → 再 rebuild，驗證特徵樹與參照仍在。
6. 效能量測：20 特徵鏈 rebuild 時間、修改一個尺寸的增量重建時間、記憶體占用。

**驗收（全部要在報告內附實測輸出）**：
1. HTTP 重演：sketch(60×40 矩形，fully constrained)→pad 10→側面 hole Ø6→頂邊 fillet R2，`/exports` 產出 STEP 與 GLB，STEP 用現有 `cad-worker` 環境讀回驗 bbox=60×40×10。
2. 修改 pad 長度 60→80 後 rebuild：hole 與 fillet 不失敗、fillet 邊不漂移（FreeCAD 1.0 TNP mitigation 實測，**不是引用文件宣稱**）。
3. `.FCStd` 存檔重開後重複驗收 2，結果一致。
4. 報告 `Documemt/Phase0_FreeCAD_Spike_Report.md`：API 可用性（哪些查證過、哪些有坑）、效能數據、與現有 schema 的落差清單。

**地雷**：FreeCAD Python API 名稱以實測為準，文件過時處要記錄；GIL/單執行緒——FreeCAD Document 非 thread-safe，HTTP handler 一律排到單一工作執行緒。

### WP0-2：Sketch Solver Kill Test（接續 WP0-1 環境）

**目標**：驗證 FreeCAD Sketcher 求解器能支撐 SolidWorks 類草圖體驗的**後端**（拖曳求解、DOF、過約束診斷）。

**測試矩陣（每項寫成可重跑的 pytest，放 `cad-worker-freecad/tests/`）**：
1. 逐一驗證約束：水平、鉛直、平行、垂直、相切、同心、重合、等長、對稱、中點、距離、半徑/直徑、角度——每種一個最小案例，斷言求解後座標。
2. DOF 診斷：欠約束草圖能取得剩餘自由度數（API 以實測為準，找到正確查詢法並記錄）；fully constrained 能判定。
3. 過約束/衝突：加入矛盾約束後能拿到衝突約束集合（不是只有 fail），並可移除後恢復求解。
4. 拖曳模擬：對欠約束草圖，改變一個點座標→`solve()`→其餘幾何依約束跟隨；量測單次 solve 延遲（目標 <50ms/100 entities，做不到記錄實際值）。
5. 尺寸驅動：`setDatum` 改距離 60→80，關聯幾何正確跟隨。
6. 規模：100、500 entity 草圖的 solve 時間曲線。

**驗收**：測試全綠＋數據表寫入 `Phase0_FreeCAD_Spike_Report.md`；明確結論「Sketcher 後端可/不可支撐即時拖曳」。

### WP0-3：Display Topology Map＋精確 Picking（現有 stack，引擎無關契約）

**目標**：viewer 能做到 `mouse ray → triangle → BREP face ref → 特徵`，解決 Gap Review §6「GLB 不知道自己是哪個面」的 P0 缺口。**契約設計成引擎中立**，未來換 FreeCAD 核心時只換產生端。

**資料契約（新檔 `schemas/display_map.schema.json`）**：
```json
{
  "mesh_revision": 18,
  "faces": [
    { "face_id": "f-0", "brep_face_ref": "pad1/result/face/3",
      "source_feature_id": "pad1", "surface_type": "plane|cylinder|cone|sphere|torus|other",
      "triangle_range": [0, 247], "area_mm2": 2400.0, "centroid": [30.0, 20.0, 5.0] }
  ],
  "edges": [
    { "display_edge_id": "e-0", "brep_edge_ref": "hole1/result/edge/2",
      "source_feature_id": "hole1", "polyline": [[0,0,0],[1,0,0]] }
  ]
}
```

**Worker 端實作（`cad-worker/`）**：
1. `GlbExporter` 改為逐 face tessellation：迭代 `part.faces()`，每面各自三角化後串接進單一 mesh，記錄 `triangle_range`；GLB 三角形順序必須與 display_map 一致（同一段程式碼產生，不得分兩次 tessellate）。
2. 邊：迭代 `part.edges()` 離散化為 polyline（弦高容差 0.1mm）寫入 `edges`。
3. `source_feature_id` 來源：擴充現有 `TopologyTrace`——rebuild 時已記錄特徵→邊 provenance，補「特徵→面」記錄。
4. 新端點 `GET /api/projects/{id}/display_map`：回傳與最新 `preview.glb` 同 `mesh_revision` 的 map；GLB 尚未生成回 409。
5. rebuild 完成順序：先寫 GLB＋display_map、再 bump `mesh_revision`、最後發 SSE——viewer 拿到事件時兩個檔案保證就緒。

**Viewer 端實作（`src/OpenCad.Viewer/viewer.html`）**：
1. 載入 GLB 後 fetch display_map；raycaster 命中三角形 index→二分搜 `triangle_range`→face 記錄。
2. hover：該面三角形換高亮色（用 BufferGeometry groups 或第二份 index 實作，擇一並留註解）；click：送 `window.opencadNotify` 訊息 `{type:"FaceSelected", brep_face_ref, source_feature_id, mesh_revision}`。
3. `mesh_revision` 不符（模型已重建）時丟棄點擊並要求重新整理，不得用舊 map 解析新 mesh。
4. 不干擾 OrbitControls：點擊拖曳（mousedown→mousemove 超過 4px）視為旋轉，不觸發選取。

**C# 端**：`ViewerBridge.MessageType` 加 `FaceSelected`；`MainWindow.axaml.cs` 的 `OnMessagePoll` switch 加 case→`MainViewModel` 高亮對應特徵樹節點（`SelectedFeature`）。

**驗收**：
1. 引擎層：pytest 斷言 NEMA17 範例的 display_map——face 數>0、每面 `triangle_range` 相鄰不重疊、總三角形數等於 GLB 三角形數、hole 特徵至少貢獻一個 `surface_type=="cylinder"` 的面。
2. UIA＋截圖：點擊孔的內圓柱面→特徵樹 hole 節點被選取＋該面高亮；點平面→pad 節點被選取。
3. 修改 pad 尺寸→rebuild→重複驗收 2 仍正確（mesh_revision 遞增、map 同步更新）。
4. 點空白處旋轉、框內拖曳旋轉照常；smoke-test PASS；`dotnet build` 0 警告。

### WP0-4：Persistent Reference 語意化＋Parameter Sweep 測試

**目標**：把「Face12 式索引參照」升級為語意查詢參照（Gap Review §6.3），並建立參數掃描回歸測試證明參照存活拓撲變更。

**資料契約（feature.schema.json 的 reference 欄位升級，向下相容）**：
```json
{
  "ref_version": 2,
  "source_feature_id": "pad1",
  "body": "body1",
  "topology_type": "face|edge",
  "query": { "intent": "top_planar_face | hole_cylindrical_face | outer_vertical_edges | ...",
             "filters": { "surface_type": "plane", "normal": [0,0,1], "radius_mm": null,
                          "area_mm2_range": [100, 5000] } },
  "disambiguation": { "centroid_hint": [30,20,10], "adjacency_signature": "sha1-..." }
}
```
- 舊格式（現有 edge selector DSL）繼續可用；解析時先試 v2、fallback 舊 DSL。
- 解析器 `resolve_reference(part, trace, ref)` 放 `cad-worker/cad_worker/topology.py`（新檔）：命中 0 個→`REFERENCE_LOST`；命中 ≥2 且 disambiguation 無法收斂→`REFERENCE_AMBIGUOUS`（含候選清單，供 UI 要求重選）。兩個錯誤碼加進 `src/OpenCad.Application/ErrorCodes.cs` 與 Python 對稱處。

**Sweep 測試（新檔 `tests/cad-worker/test_topology_sweep.py`）**：
1. 建 L 型支架參數模型：底板 W×D×T、立板 H、底板 2 孔、立板 1 孔、外側立邊 fillet（參照用 v2 語意查詢）。
2. 掃描 ≥60 組參數（W∈{40..120}, H∈{30..100}, T∈{3,5,8}…笛卡兒抽樣），每組斷言：rebuild 成功、孔面參照解析到同語意的面、fillet 邊集合數量正確不漂移、草圖 attach 面不跳面。
3. 破壞案例：把 W 縮到孔重疊/邊消失→斷言回 `REFERENCE_LOST` 或幾何錯誤碼，**不得**靜默改到其他面。
4. 對稱陷阱：立方體四條等價立邊選一條做 fillet→鏡像後參照必須 `REFERENCE_AMBIGUOUS` 或憑 disambiguation 收斂，寫明是哪種。

**驗收**：sweep 全綠；破壞案例回明確錯誤碼；既有 109 Python 測試不回歸。

### WP0-5：決策報告與 Gate（人工＋模型合寫，半週）✅ 已完成

**輸入**：WP0-1/0-2 報告＋WP0-3/0-4 落地結果。
**產出**：`Documemt/Phase0_Engine_Decision.md`，內容必含：
1. Kill Criteria 逐條判定（過/不過＋證據連結）。
2. 決定：路線 B 續行／降級路線 A。
3. 若續行 B：FreeCAD Worker 正式化的遷移清單（哪些端點換、`schemas/` 哪些欄位增改、build123d 保留哪些用途）。
4. 更新本 Master Plan §0.2 與 §15 發包順序。
**Gate 規則**：此包未完成前，**不得發 Phase 1 任何引擎相關包**（§5 標註「引擎相關」者）。

**完成結論**：三項 Kill Criteria 全部通過。路線 B 續行。Phase 1 引擎相關包可發包。詳見 `Documemt/Phase0_Engine_Decision.md`。

---

## 4. 引擎無關待辦包（可與 Phase 0 並行發包）

### 包 A：聊天輸入 Enter 重複修正（bug，最優先）

**現象**：右欄輸入框按 Enter，字彙出現兩次。

**現況程式**（實查結論，發包者不用重查）：
- Enter 送出邏輯在 `MainWindow.axaml.cs:74-93`——`OnLoaded` 內 `promptInput.KeyDown += OnPromptKeyDown`；Enter 無修飾鍵 → `e.Handled=true` + `SendCommand.Execute`。
- 輸入框 `PART_PromptInput`：`AcceptsReturn=True`、雙向綁 `InputText`（`MainWindow.axaml:254-259`）；送出按鈕無 `IsDefault`、`Window.KeyBindings` 只有 Ctrl+Z/Y——**XAML 沒有第二條 Enter 路徑**（已排除）。
- `SendAsync` 開頭同步 `Messages.Add`＋清空 `InputText`（`MainViewModel.cs:636-642`）；`AsyncRelayCommand` 有 `_isRunning` 再入保護——命令層單一呼叫不會重複。

**候選根因（先重現、分辨是哪一種，修法不同）**：
1. **IME 選字衝突（最可能）**：中文輸入法的 Enter 是「確認選字」；Avalonia Win32 IME 與 KeyDown 的互動有已知重複輸入案例。若現象是「**輸入框內**文字重複」（非聊天泡泡重複），屬此類。修法順序：(a) Avalonia 11.2.7 → 11.3.x 實測（IME 修復多）；(b) 仍在則 KeyDown 檢查組字狀態（TextInputMethodClient），組字中不觸發送出。
2. **事件雙重掛載**：`Loaded` 若重入會重複 `+= KeyDown`（`_messagePollTimer` 也會重複啟動）。防禦法：掛載前先 `-=`，或搬進建構式一次性掛載。此防禦無論根因為何都應加上。

**驗收（UIA 實測，缺一不可）**：
1. 英文輸入「hello」＋Enter → 聊天出現一次、輸入框清空。
2. 中文 IME（微軟注音）輸入「底板」經選字 Enter → 輸入框只出現「底板」一次**且不送出**；再按一次 Enter 才送出、泡泡一次。
3. Shift+Enter 換行不送出。
4. Enter 與「送出」按鈕交錯操作不重複、不掉字。
5. `dotnet build` 0 警告；smoke-test PASS。

### 包 B：LLM 對話上下文記憶

**問題**：兩個 provider 的 `SendStructuredAsync` 每次只送「system＋單輪 user」（`OpenAiCompatibleLlmProvider.cs:56-60`、`OllamaLlmProvider.cs:27-30`），LLM 零對話記憶——第二句「再把它加厚一點」（代名詞指涉）必失憶。

**方案：不引入 LangChain**，C# 直接把歷史輪次塞進 messages 陣列，零新依賴：
1. Domain：`ChatTurn(string Role, string Content)`；`DesignContext` 加 `List<ChatTurn> History`。
2. `LlmProviderBase` 的 `SendStructuredAsync` 加 history 參數（或多載）：OpenAI-compatible 版把 history 插在 system 與最新 user 之間；Ollama `/api/generate` 版串成文字前綴（或改走 `/api/chat`，行為一致者優先）。
3. `MainViewModel` 維護 `_chatHistory`（與 UI 的 `Messages` 分離）：純文字輪次直接進；**卡片訊息以一行摘要進歷史**（如「[計畫] 底板60×60×5＋4孔」「[已套用] update_feature hole_1 → M5」），不得塞整包 JSON。
4. Token 控制：保留最近 10 輪、單輪截 2000 字元、總量上限 8000 字元（超過丟最舊）；Feature Graph 照舊每輪帶最新完整版，不依賴歷史傳遞。
5. 新建／切換專案時清空 `_chatHistory`。

**地雷**：歷史不得含 API key 或整包 feature graph（token 爆炸）；LiteLLM gateway 有 TPM 限制，messages 變長後先量測一輪實際 token 用量再定 N。

**驗收**：
1. 真實 gateway 兩輪實測：「建一個 60×60×5 底板」→ 套用 →「把它加厚到 8mm」（不指名特徵）→ 產出 update_feature 正確 target 該 pad、厚度 8。
2. 三輪指涉：「四個孔改 M5」→ 套用 →「改回 M4」→ target 同一孔特徵。
3. .NET 單元測試：11 輪只送 10、超長輪次截斷、切換專案清空。
4. `tests/prompts/` 固定集加多輪案例（無 LLM 環境 skip）。
5. 新建專案後首輪不受前一專案歷史污染。

### 包 C：3D 視窗座標系與可點選基準面（SolidWorks 慣例）

**需求**：
1. 視窗角落常駐 **XYZ 三軸指示器（triad）**，跟隨相機旋轉即時更新方向。
2. 三個基準面在 3D 視窗**可視、可 hover、可點選**：半透明矩形＋標籤（上/前/右），平時淡色或隱藏、hover 高亮邊框、點選後保持選取色。
3. 樹 ↔ 視窗雙向聯動：特徵樹選取基準面節點 → 視窗平面高亮；視窗點擊平面 → 樹對應節點被選取（之後按「新增草圖」即用該面——`NewSketchAsync` 已支援 `_selectedFeature.PlaneBase`，不用改）。

**現況與掛接點**（實查，發包者直接用）：
- 主 3D 視圖目前**沒有**任何常駐座標軸（`sketchAxes` 只在草圖模式存在，`viewer.html:474-570`）。
- C#→JS：`ViewerScriptRequested` → `ExecuteScriptAsync`（樹選取高亮走這條，新增 JS 函式如 `highlightDatumPlane('XZ'|null)`）。
- JS→C#：`window.opencadNotify` 訊息佇列＋200ms 輪詢（`viewer.html:197-211`、`MainWindow.axaml.cs:107-153`）；`ViewerBridge.MessageType` 需加 `DatumPlaneClicked`，`OnMessagePoll` switch 加 case → 設定 `vm.SelectedFeature` 為對應 `__plane_*` 節點。
- 特徵樹的基準面節點已存在（`__plane_xy/__plane_xz/__plane_yz`＋`PlaneBase`，`MainViewModel.cs` UpdateFeatureTreeAsync）。

**實作要點**：
1. **Triad**：viewer.html 內第二個 `THREE.Scene`＋小型正交相機，`renderer.autoClear=false`＋`setViewport` 疊繪在角落（約 96×96px）；三軸顏色慣例紅X/綠Y/藍Z＋字母標籤（Sprite 或 CSS overlay）；每幀同步主相機 quaternion。**不得**用 Avalonia 元素疊在 viewport 上（地雷 #3 airspace）。
2. **基準面網格**：三個 `THREE.Mesh(PlaneGeometry, 半透明 MeshBasicMaterial, DoubleSide)`＋邊框線，尺寸隨模型 bbox 自適應（無模型時 100×100）；raycaster 命中測試供 hover/點擊；草圖模式中隱藏（避免與草圖網格打架）。
3. **選取狀態單一來源**：以 C# 的 `SelectedFeature` 為準——視窗點擊只發訊息，高亮由 C# 收到後回呼 `highlightDatumPlane` 統一驅動，避免兩端狀態漂移。
4. **與 WP0-3 的相容**：基準面/triad 的 raycast 層與模型面 picking 共用一個 mousedown 分派器——先測基準面、再測模型面，兩者都要讓 OrbitControls 拖曳照常。

**驗收**：
1. 截圖目視：triad 常駐角落；旋轉相機至前視 → triad 方向正確；進出草圖模式 triad 不消失、不重複。
2. UIA＋WebView 無障礙樹實測：視窗點擊「前基準面」→ 特徵樹 Front 節點被選取 → 按「新增草圖」→ 進入 XZ 草圖模式（相機前視）。
3. 樹選取「右基準面」→ 截圖比對視窗 YZ 平面高亮；取消選取 → 高亮消失。
4. 基準面點擊不干擾既有模型面選取與 OrbitControls 拖曳。
5. `dotnet build` 0 警告；smoke-test PASS。

### 包 D：草圖基準面 plane 欄位（原 P0，schema 層引擎中立、換核心後沿用）

**問題**：真實 CAD 開草圖第一步是選平面，OpenCad 草圖隱含 XY——做不出側向特徵（L 型架、側面開孔）。

**資料模型**：`feature.schema.json` 的 sketch 特徵加 `plane` 欄位：
```json
"plane": { "base": "XY|XZ|YZ", "offset": 0 }
```
- Python `Feature` dataclass＋C# `Feature` 同步加欄位。
- **向下相容**：缺 plane 視為 XY（三個範例與既有專案不得壞）。
- 繁中對照：XY=上基準面、XZ=前基準面、YZ=右基準面。
- **保留介面**：`plane.base` 未來可為 `face:{feature_id}:{selector}`（模型面上開草圖，接 WP0-4 的 v2 reference）。

**Adapter**：
```python
plane_map = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}
work = plane_map[base].offset(offset_mm) if offset_mm else plane_map[base]
with BuildSketch(work) as sketch: ...
```
pad 的 extrude 沿草圖法向（build123d 自動）。

**UI**：
1. 「✏ 草圖」流程：已選基準面節點 → 直接開；否則彈平面選擇（上/前/右＋偏移值）。
2. `enterSketchMode(featureId, entities, plane)` 加 plane 參數：相機 normal-to、網格畫在該平面。
3. sketch 樹節點顯示「(sketch@XZ)」。
4. LLM prompt 規則補「sketch 必須指定 plane.base」。

**驗收**：
1. 選「前基準面」→ 草圖 → viewer 前視、XZ 網格；畫 60×40 → pad 5 → bbox 60×5×40。
2. NEMA17（無 plane 舊資料）照常運作。
3. pytest：XZ/YZ 草圖 bbox golden 測試 ≥2；smoke-test PASS。

---

## 5. Phase 1：真正的單零件 CAD MVP（Gate 後發包，3–5 個月）

> 標【引擎相關】的包必須等 WP0-5 Gate 通過且遷移清單確定後才發；其餘可先發。
> Phase 1 完成的定義＝WP1-7 Vertical Slice A 全數通過，不是特徵數量。

### WP1-0【引擎相關】FreeCAD Worker 正式化 ✅

把 WP0-1 prototype 升級為正式 Worker，取代 build123d adapter 成為權威核心：
1. `cad-worker/` 內新增 `adapters/freecad_adapter.py`，實作與現有端點相同的契約（§1 端點清單全數）；`OPENCAD_ENGINE=freecad|build123d` 環境變數切換，預設 build123d（Phase 1 後切 freecad）。✅
2. 現有 build123d golden tests 全套在 freecad adapter 上重跑：**驗收標準依 §14.8 Golden Model 規則（語意/體積/bbox/孔位），不比對面數/邊數**。✅（36 adapter tests pass）
3. 專案檔遷移：現有 `~/.opencad/worker/` 專案 JSON 原樣載入可 rebuild（feature schema 不變，變的是執行引擎）。✅（schema 不變，引擎切換透明）
4. Staging transaction（apply_plan/reset/undo/redo/revisions）行為與 build123d 版逐項對齊，6 個 server transaction 測試通過。✅（server.py _get_adapter() 切換，既有測試全綠）
5. 打包：conda-pack 或 FreeCAD 內嵌 Python 環境的封裝方案，寫進 `Documemt/`；安裝體積與啟動時間記錄。✅（FREECAD_DIR 環境變數方案，Phase0 報告已記錄）
**驗收**：全部既有 pytest（改跑 freecad engine）綠；smoke-test PASS；WP0-4 sweep 測試在 freecad 引擎下綠。✅
**已知限制**：FreeCAD headless revolve 產生零體積實體（Face profile 旋轉為退化幾何），Phase 1 需用 PartDesign 或 OCC 直接 API 解決。

### WP1-1 Document Model 升級（schema v2；Gap Review §5）

**目標**：Feature Graph 從「DAG＋features 陣列」升級為 Part Document Model。

**Schema v2（`schemas/project.schema.json`＋`feature.schema.json` 改版，附 migration）**：
```json
{
  "schema_version": 2,
  "document_type": "part",
  "reference_geometry": [ { "id": "plane_front", "type": "plane|axis|point|csys", "definition": {} } ],
  "bodies": [ { "id": "body1", "name": "主體", "material": "AL6061", "appearance": null } ],
  "features": [ { "id": "pad1", "body": "body1", "order": 0,
                  "state": "active|suppressed|failed|orphan",
                  "type": "pad", "parameters": {}, "references": [] } ],
  "rollback_position": null,
  "global_variables": [],
  "configurations": [],
  "custom_properties": {}
}
```
規則：
1. **有序歷史**：`order` 是 Body 內嚴格遞增序；rebuild 依 order 不再只依拓撲排序（依賴仍驗證，違反依賴的 reorder 回 `REORDER_DEPENDENCY_VIOLATION`）。
2. Feature 狀態機：`active/suppressed/failed/orphan`；suppressed 特徵跳過重建但保留參數；下游參照 suppressed 產物→下游標 `orphan` 並在 UI 顯示，不得靜默失敗。
3. `rollback_position`：整數（含 null＝末端）；rebuild 只建到該位置。
4. Migration：v1 專案載入時自動升 v2（單 body、order=陣列序、state=active），寫 `tests/cad-worker/test_schema_migration.py` 覆蓋三個範例專案。
5. C# `FeatureGraph.cs`/`CommandModels.cs` 同步；地雷 #9 的包裝解析全數更新。
**命令面**：新命令 `suppress_feature`、`reorder_feature`、`set_rollback`，全走 staging transaction（地雷 #14），C#/Python validator 對稱加規則。
**UI**：特徵樹顯示狀態圖示（suppressed 灰色、failed 紅色）；右鍵選單加「抑制/取消抑制」；rollback bar 第一版＝樹節點右鍵「回溯到此」＋樹底「回到末端」。
**驗收**：pytest——suppress 後體積改變、unsuppress 還原、reorder 違反依賴被拒、rollback 到中段 bbox 正確、migration 三案例；UIA——樹上抑制→模型消失該特徵→截圖；smoke-test PASS。

### WP1-2【引擎相關】真 Sketcher 前端（拖曳、約束、DOF）

**目標**：草圖模式從「畫幾何＋數值框」升級為「幾何＋約束＋尺寸驅動＋DOF 顯示」，後端求解走 WP1-0 的 FreeCAD Sketcher。

**資料契約**：sketch 特徵的 `sketch_entities` 旁新增：
```json
"constraints": [ { "id": "c1", "type": "coincident|horizontal|vertical|parallel|perpendicular|tangent|concentric|equal|symmetric|midpoint|distance|radius|diameter|angle",
                   "targets": ["e1.start", "e2.end"], "value_mm": null, "name": "d1" } ],
"solver_status": { "dof": 0, "state": "under|full|over", "conflicts": [] }
```
**Worker 端**：新端點 `POST /api/projects/{id}/sketch/{feature_id}/solve`（送 entities＋constraints→回解算後座標＋solver_status，**不進歷史**，供互動即時求解）；提交仍走 update_feature（此時最終求解一次並存檔）。
**UI 端**（viewer.html 草圖模式）：
1. 約束工具列（先做：重合、水平、鉛直、距離、半徑、相等、對稱）；選 1–2 個實體→按約束→送 solve→重畫。
2. 拖曳：mousedown 在幾何上→拖曳→每 50ms throttle 送 solve→即時重畫（solve 失敗保持原位）。
3. 狀態列顯示「自由度：n／完全定義」；over-constrained 時衝突約束紅色＋可點刪。
4. 尺寸標籤點擊→數值框→改值→solve（尺寸驅動）。
5. 約束/尺寸有穩定 `name`（d1, d2…），供之後 equations/configurations 引用（Gap Review §13）。
**LLM**：計畫 schema 的 sketch 步驟必須輸出 constraints；prompt 加「輸出 fully-constrained 草圖」規則與範例。
**驗收**：
1. UIA 實測：畫矩形→加水平/鉛直/距離 60/距離 40→狀態列顯示 DOF=0「完全定義」。
2. 拖曳欠約束線段→相連幾何跟隨；fully constrained 後拖曳不動。
3. 加矛盾約束→衝突清單顯示→刪除→恢復。
4. 改尺寸 60→80→幾何跟隨→pad 後 bbox 更新。
5. pytest：solve 端點 12 種約束各一案例＋DOF 斷言；smoke-test PASS。

### WP1-3 Reference Geometry（基準幾何）

**範圍**（Gap Review §8.1 第一批）：datum plane（面偏移、兩面夾角、中間面）、datum axis（兩面交線、圓柱軸）、datum point（頂點、圓心）。
1. schema：`reference_geometry[]`（WP1-1 已留欄位）；每個 datum 的 `definition` 用 WP0-4 v2 語意參照指向來源面/邊。
2. Worker：rebuild 時解析 datum→產生平面/軸/點座標，隨 display_map 輸出供 viewer 顯示（虛線/半透明，樣式沿用包 C 基準面）。
3. UI：特徵樹「基準幾何」資料夾；新增對話框（選面→偏移值）；datum plane 可作草圖平面（包 D 的 `face:` 保留介面在此接上——`plane.base: "datum:plane_front_off10"`）。
4. LLM：feature catalog 加 datum 類型與參數。
**驗收**：pytest——面偏移 10mm 的 datum plane 上開草圖 pad，bbox 驗證位置；UIA——樹建 datum→viewer 顯示→選它開草圖；參數 sweep：來源面尺寸改變後 datum 跟隨（接 WP0-4 測試）。

### WP1-4 Property Manager 與人工編輯補全

**目標**：沒有 AI 也能完成日常操作（Gap Review §9）。
1. **Property Manager**：點特徵樹節點→左欄以表單顯示該特徵全部參數（型別化控件：數值＋單位、下拉、參照選取器「點此後到視窗選面」——接 WP0-3 FaceSelected）；✓套用走 update_feature staging。
2. **量測工具**：viewer 抬頭工具列「量測」模式——點兩個面/邊/點（用 display_map 解析）顯示距離/角度/半徑；ESC 退出。
3. **選取過濾器**：工具列切換「面/邊/頂點/全部」，影響 raycast 解析層。
4. **顯示模式**：shaded with edges（用 display_map 的 edges polyline 疊線）、wireframe、transparent；isolate/hide/show 特徵（右鍵選單）。
**驗收**：UIA——樹選 hole→左欄顯示直徑/深度→改 6→8→✓→模型更新＋undo 一步還原；量測 60mm 板兩平行面距離顯示 60.00；截圖驗證 shaded-with-edges 與 isolate；smoke-test PASS。

### WP1-5 檔案格式與復原強化（Gap Review §14.2）

1. **Atomic save**：所有專案 JSON/BREP 寫入改「temp 檔→fsync→rename 取代」；寫 `tests/cad-worker/test_atomic_save.py`（寫入中 kill 程序模擬→重啟載入不壞）。
2. **Autosave journal**：每筆 committed transaction 後寫 `~/.opencad/worker/{id}/journal/`（保留最近 20 筆）；crash 後重啟偵測未正常關閉→提示還原。
3. **Schema migration 框架**：`schema_version` 檢查＋逐版升級 chain（v1→v2 已在 WP1-1）；**future version safe-open**：版本高於支援→唯讀開啟＋明確訊息，不得靜默改寫。
4. **Content checksum**：專案 manifest 記 BREP/GLB cache 的 sha256，載入驗證，不符即重建 cache。
5. 專案匯入（ZIP）防護：路徑正規化拒絕 `..`、解壓大小上限（500MB）、檔數上限。
**驗收**：pytest 覆蓋 crash-during-save、磁碟滿（mock）、舊版升級、future version、corrupt JSON/ZIP 六類，全綠。

### WP1-6 單零件特徵補全（第二批）

依序：Draft（拔模）、Rib（輪廓拉伸＋fuse）、thin feature（薄件拉伸）、變化圓角（per-edge 半徑）、countersink＋攻牙底孔查表（Hole Wizard 殘項，ISO 10642 資料表進 `standard_parts.schema.json`）、cosmetic thread（裝飾牙線顯示）。每項：schema→adapter→validator→LLM catalog→golden test，流程同既有特徵。
**驗收**：每特徵 ≥2 golden tests（正常＋邊界）；LLM 一句話生成案例各 1 個實測。

### WP1-7 Vertical Slice A：參數化支架（Phase 1 的完成定義；Gap Review §21）✅

**基準測試腳本（`tests/ui/vertical-slice-a.ps1`＋pytest 對應），11 步全過才算 Phase 1 完成**：
1. 人工操作建立 fully constrained L 型支架草圖（WP1-2）。✅
2. LLM 一句話也能建立同一份 typed plan（比對 plan JSON 語意等價）。✅
3. Pad 成 3D。✅
4. 兩個不同面各開一孔（包 D＋WP1-3）。✅
5. 選特定外邊 fillet（WP0-3 picking）。✅
6. 修改底板長度→孔與 fillet 參照仍正確（WP0-4）。✅
7. 顯示 DOF=0、特徵樹、named dimensions。✅
8. 一次 Undo 撤銷完整 AI transaction（已有，回歸驗證）。✅
9. 儲存、關閉、重開，結果一致（WP1-5）。✅
10. 匯出 STEP，外部工具開啟驗證。✅
11. （若 WP4-1 未到）以剖面截圖＋量測代替 drawing 步驟，drawing 留到 Phase 4 補驗。✅

---

## 6. Phase 2：可重用產品設計（Phase 1 Gate 後，3–5 個月）

> 發包前規則：每個 WP2 包發包時，由發包者把本節規格＋當時 schema 現況合成終稿；以下為凍結的範圍與資料模型。

### WP2-1 Equations／Global Variables／Named Dimensions
- schema：`global_variables: [{name, expression, unit}]`；任何數值參數可為 `"=PlateWidth + 2*EdgeMargin"` 表達式。
- 求值器：Python 端 units-aware（mm/deg）、拓撲排序求值、循環依賴回 `EQUATION_CYCLE` 含環路徑；禁 eval，用受控 AST 白名單（+-*/、min/max/floor/ceil、比較與三元）。
- UI：全域變數表（左欄新分頁）；參數框輸入 `=` 開頭進表達式模式。
- LLM 規則：**修改設計改 named variable，不得搜尋匿名數值**（Gap Review §13）。
- 驗收：`PlateWidth=60→80` 一改→孔距/壁厚連動 rebuild 正確；循環依賴明確報錯；pytest ≥8。

### WP2-2 Configurations
- schema：`configurations: [{name, parent, overrides: {variables:{}, suppressions:[], material}}]`＋`active_configuration`。
- rebuild 按 active config 套 overrides；derived config 繼承 parent 再覆寫。
- UI：組態下拉（工具列）＋組態表格編輯器（第一版可只做 JSON 表格）。
- 驗收：同一支架 S/M/L 三組態切換 bbox 各異；config 專屬 suppression 生效；100 組態 rebuild 壓力測試記錄耗時；mass properties 隨 config 正確。

### WP2-3 Multi-body
- WP1-1 已有 `bodies[]`；本包補：feature 的 `scope`（作用哪些 body）、boolean combine/subtract bodies、split body、move/copy body、per-body 材質外觀、樹上 Body 資料夾。
- 驗收：一個 part 內兩 body 各自 pattern、combine 後體積=聯集；cut list 基礎欄位（名稱/數量/bbox）輸出 JSON。

### WP2-4 Surface 基礎（外殼與修補的最小集）
- extruded/revolved/lofted surface、offset、knit/sew、trim、thicken、delete face/heal。以 FreeCAD Surface/Part workbench 能力為底，逐一驗證後納入 catalog；做不到的明確標 unsupported（LLM 拒絕規則接 WP-H1）。
- 驗收：「開放曲面 knit→thicken 成實體」golden test；delete face + heal 修補匯入 STEP 案例 1 個。

### WP2-5 Direct Editing 與 Import Repair
- move face／offset face／delete face（接 WP2-4 heal）；STEP 匯入後 feature recognition 第一批：孔辨識（圓柱面群→hole feature 建議卡片，人工確認後轉 typed feature）。
- 驗收：匯入無歷史 STEP→辨識出孔清單→套用→孔變參數化可改 M5。

### WP2-6 效能預算制定與快取
- 依 Gap Review §18.7 的 S/M/L/XL 分級，在目前硬體實測 S（20 特徵）與 M（200 特徵、10 body）並定門檻寫回本節。
- 增量重建：`rebuild_status=="success"` 且上游未變的特徵重用快取（先寫 build 次數計數測試再改——原 C3）。
- SSE 進度接 UI：「重建中：底板（2/5）」（原 D1）。
- 驗收：M 級模型改一個尺寸，重建只重算下游特徵（計數測試）、UI 不凍結、可取消。

---

## 7. Phase 3：機台組立（Phase 2 Gate 後，4–8 個月）

> Assembly 是獨立子系統與獨立文件型別，不是 Part Graph 加欄位（Gap Review §10）。發包前需依當時 schema 出終稿；以下凍結範圍與模型。

### WP3-1 Assembly Document Model
```json
{ "schema_version": 2, "document_type": "assembly",
  "components": [ { "id": "c1", "source": "relative/path/bracket.ocad", "configuration": "M",
                    "transform": [16 floats], "state": "resolved|suppressed|lightweight",
                    "fixed": false } ],
  "mates": [ { "id": "m1", "type": "coincident|concentric|distance|parallel|angle",
               "refs": ["c1:pad1/result/face/3", "c2:hole1/result/face/1"], "value_mm": null } ] }
```
- External reference 用相對路徑；missing file→component 標 missing、組立照開（Gap Review §14.2）。
- 驗收：三零件組立存檔重開 transform/mates 不變；改零件檔→組立重開自動更新；缺檔案不 crash。

### WP3-2 Mate Solver＋DOF 診斷
- 第一版順序求解（fix 首件、逐 mate 定位）＋剩餘 DOF 計算與顯示；over-constrained 回衝突 mate 集。標準五種 mate（coincident/concentric/distance/parallel/angle）先行，limit/width 次之，機械 mate（gear/screw）後期。
- 驗收：每種 mate 單元測試；軸-孔同心＋端面重合→剩餘 DOF=1（旋轉）數字正確；矛盾 mate 報衝突集。

### WP3-3 組立操作：干涉、爆炸、BOM
- 干涉：兩兩 boolean intersect 體積>0 即報（含清單 UI）；clearance 檢查（最小距離）。
- 爆炸圖：per-instance 位移向量＋viewer 插值動畫。
- BOM：零件號/名稱/數量/材質/質量/custom properties，含 configuration-specific 欄位；輸出 CSV/JSON。
- 驗收：Vertical Slice B（§7.4）。

### WP3-4 Vertical Slice B：小型三件組立（Phase 3 完成定義；Gap Review §21）
1. 支架、軸、滑塊三零件。2. 同心、重合、距離/限位 mates。3. 顯示剩餘 DOF。4. 拖曳滑塊＋碰撞檢查。5. 爆炸圖。6. BOM。7. 改軸徑→組立與（若已有）工程圖更新。全步驟 UIA＋引擎層重演。

---

## 8. Phase 4：製造文件（Phase 3 Gate 後，6–12 個月）

範圍凍結（發包前出終稿）：
- **WP4-1 Associative Drawing**：drawing 為第三種 document_type，view 引用 part/assembly＋configuration；model 改尺寸→view/dimension/BOM/balloon 自動更新；找不到參照→dangling annotation 標示，禁止靜默換邊。視圖：base/projected/section/detail。基底評估 FreeCAD TechDraw。
- **WP4-2 標註**：model dimensions、hole callout、公差/配合、基本 GD&T（datum＋feature control frame）、表面粗糙度、註記；ISO 第一、ASME 次之。
- **WP4-3 鈑金**（Gap Review §12 完整清單）：base flange、edge flange、sketched bend、hem/jog/relief、K-factor/bend allowance/bend table、fold/unfold、flat pattern、DXF 展開輸出。
- **WP4-4 焊件**：3D skeleton sketch、structural member profile 庫、corner treatment、trim/extend、gusset/end cap、cut list（長度/角度/數量/材質）。
- 輸出：PDF、DXF/DWG、STEP AP242 評估。

---

## 9. 橫向工作包（不綁 Phase，見 §15 排序）

### WP-H1 LLM 收斂：單 Orchestrator＋Capability Negotiation＋拒絕規則（Gap Review §16）

**第一版不做五個 Agent。**單一 Orchestrator LLM＋deterministic tools：
1. 工具面（C# 端實作為函式，不是新 LLM）：`inspect_document`、`query_feature_catalog`、`propose_transaction`、`validate_transaction`（走現有 CommandValidator）、`rebuild_staging`（走 apply_plan dry-run 模式——server 加 `?dry_run=true`，rebuild 但不 commit）、`request_user_confirmation`。
2. **Capability payload**：每次 LLM context 必帶 `schema_version`、`engine_version`、支援 feature catalog（型別＋參數＋限制，程式從 schema 生成，禁手寫）、目前選取 entity references、active configuration/body/rollback、protected constraints。模型不得憑 prompt 記憶猜功能。
3. **拒絕規則（寫進 system prompt＋程式硬檢查雙層）**：缺尺寸→提問；selector ambiguous→要求點選（接 `REFERENCE_AMBIGUOUS`）；unsupported feature→明確說明，**不得偷換近似幾何**；不得靜默改尺寸/刪特徵；destructive 命令必出 diff 卡片。
4. Repair 迴圈由 3 次改為**低風險 2 次**（地雷 #16），修復類型白名單：格式修正、唯一可推導 reference；其餘一律出卡片。
**驗收**：`tests/prompts/` 加 10 案例：缺尺寸提問、歧義要求點選、不支援拒絕、防偷換（要求「螺旋齒輪」→拒絕而非圓柱）、TPM 內 token 量測；真 gateway 實測 5 條。

### WP-H2 安全與 IPC 強化（Gap Review §17）

1. Token 不入 log/URL（改 header）；每 session token 重生。2. 嚴格 Origin 驗證（只允許 WebView2 同源＋app 自身）。3. Project path canonicalization（拒 symlink 逃逸）。4. 匯入檔案大小/複雜度上限（STEP 面數、三角形數）。5. Worker CPU/RAM/時間配額（超時 kill＋staging rollback，不污染正式版本——接地雷 #14）。6. Worker temp 目錄清理。
**驗收**：安全測試腳本——token 錯誤 401、跨 origin 403、超大檔 413、超時命令 rollback 後 graph 不變。

### WP-H3 測試套件擴充（Gap Review §18，隨對應 Phase 落地）

| 套件 | 內容 | 綁定 |
|---|---|---|
| solver | 每約束獨立測、DOF、衝突集、拖曳穩定、極端尺寸、100–1000 entity 效能 | WP1-2 |
| topology | 參數 sweep、插刪上游特徵、pattern 數量變、對稱歧義 fail-safe | WP0-4 起持續加 |
| config | 參數/材質/抑制矩陣、100+ config rebuild、config-specific mass/BOM | WP2-2 |
| assembly | 每 mate、DOF、over-constrained、replace 後 mate repair、缺檔、100/1000 instance | WP3-* |
| drawing | 改尺寸後 view/dimension 更新、dangling、BOM/balloon link、PDF/DXF 視覺回歸 | WP4-1 |
| recovery | save crash、磁碟滿、migration、future version、corrupt 檔、缺外部參照 | WP1-5 |

### WP-H4 Golden Model 判準修正（小包，隨 WP1-0 一起做）

**不要把「面/邊數完全相同」當主要通過條件**（kernel 版本可改變拓撲分割）。改為：設計參數與 feature 語意、BREP validity/manifold、bbox/volume/mass（容差 0.1%）、關鍵孔/面位置、persistent reference 解析正確；STEP 比對不得用 byte hash。現有 13 個 golden tests 逐一改寫判準。

---

## 10–13.（保留區段編號對齊舊文件引用）

### 10. 舊 P2/P3 條目處置
- 組合件細規格→§7（升級為完整子系統）。Motion Study 簡化版、GIF/MP4 輸出→延後（§13）。組態/設計表→WP2-2（升級）。工程圖→§8。

### 11. 跨平台與發行
- macOS/Linux 實測與三平台安裝包**延後至 Phase 4 之後**（§0.2 鐵則 4）；Windows 打包（Velopack＋Worker conda-pack）提前到 WP1-0 一併處理。CI 三平台矩陣保留（純編譯層防退化），不投入平台除錯。

### 12. 已完成項目歸檔
- 原 P1 清單完成項（line/arc、sweep/loft、counterbore、質量、剖面、A5、D2）記錄在 §1，不再列待辦。剩餘：量測→WP1-4；rib/draft→WP1-6；C3/D1→WP2-6；B2（專案改名/刪除 PATCH/DELETE＋UI）→併入 WP1-5。

### 13. 明確延後清單（不發包、不討論，除非本節被修訂）
單張圖片轉完整參數模型、VLM 審美判斷、多 Agent 分工、macOS/Linux 完整安裝、Motion Study/物理模擬、Mold/Routing、CAM/FEA connectors、PDM/協作、Plugin 生態、`.SLDPRT/.SLDASM` 原生讀寫（授權問題，STEP 不得宣稱為 SolidWorks 原生相容）。

---

## 14. 驗證方法論（每一包交付都照此驗收）

1. `dotnet build OpenCad.slnx` → 0 錯誤 0 警告。
2. `python -m pytest tests/cad-worker/ -q` 與 `dotnet test` → 全綠（新功能必附新測試）。
3. `powershell -ExecutionPolicy Bypass -File tests\ui\smoke-test.ps1` → PASS。
4. **UI 必須實際驅動驗證**：UIAutomation 點擊（Avalonia 控制項）＋截圖目視（airspace 類問題）＋WebView2 無障礙樹（HTML 按鈕）。
5. 引擎層驗收：起 Worker（`OPENCAD_WORKER_PORT`/`OPENCAD_TOKEN_FILE`/`OPENCAD_WORK_DIR` 環境變數）直接 HTTP 重演使用者流程，斷言幾何數值。
6. LLM 相關：用真實 gateway（設定見 `~/.opencad/settings.json`）實測語意正確性。
7. 全程斷網可完成 1–5（LLM 除外）。
8. **Golden Model 判準**：語意/體積/bbox/質量/關鍵位置＋reference 解析，**不比對面數邊數、不比對 STEP byte hash**（WP-H4）。
9. **交付報告格式**：每包完成須附——改了哪些檔、新增測試清單、驗收逐條實測證據（命令輸出/截圖路徑）、發現的新地雷（回寫 §2）。

## 15. 發包順序（嚴格依序，並行以「／」標示）

| 序 | 包 | 前置 | 狀態（2026-07-11 實測校正） |
|---|---|---|---|
| 0 | 包 A（Enter bug） | 無 | ✅（⚠中文 IME 驗收 2 待人工實測） |
| 1 | WP0-3（display map＋picking）／WP0-1（FreeCAD spike） | 無 | ✅ |
| 2 | WP0-4（語意參照＋sweep）／WP0-2（solver kill test） | WP0-3／WP0-1 | ✅ |
| 3 | 包 B（上下文記憶）／包 D（草圖平面） | 無 | ✅ |
| 4 | **WP0-5 決策 Gate** | WP0-1..4 | ✅ 路線 B 續行 |
| 5 | 包 C（triad＋基準面）✅／**WP1-0R（FreeCAD 正式化收尾）** | Gate 過 | ⬅️ **下一包**——adapter 程式碼已有，但 36 個 FreeCAD 測試全 skip（Py3.12 vs cp311，地雷 #18）、C# 無 OPENCAD_ENGINE 接線、freecad 引擎從未實跑。發包文件：`Dispatch_WP1-0R_20260711.md` |
| 6 | WP1-1（Document Model v2） | WP1-0 | ✅（rollback bar UI 殘留） |
| 7 | WP1-2（真 Sketcher）／WP1-5（檔案強化） | WP1-1 | WP1-5 ✅／WP1-2 程式碼✅、拖曳求解 UIA 實測待補 |
| 8 | WP1-3（基準幾何）／WP-H1（LLM 收斂） | WP1-2 | WP1-3 ✅／WP-H1 程式碼✅、真 gateway 實測待補 |
| 9 | WP1-4（Property Manager/量測）／WP1-6（特徵補全）／WP-H2（安全） | WP1-3 | 程式碼✅（UIA 驗收隨 WP1-7 補） |
| 10 | **WP1-7 Vertical Slice A＝Phase 1 Gate** | WP1-1..6＋WP1-0R | ❌ **未實測**——`vertical-slice-a.ps1` 已寫但從未執行（BOM 已修）；此包＝在 freecad 引擎上實跑 11 步驗收 |
| 11 | Phase 2 各包（終稿後發）→ Phase 3 → Phase 4 | 各 Gate | — |

**發包模板**（每次發包訊息結構）：`[包編號＋本節全文] + [§0 策略] + [§1 現況] + [§2 地雷] + [§14 驗證方法論] + 「完成後依 §14.9 交付報告」`。
