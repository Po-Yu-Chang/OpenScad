# OpenCad Phase 1 剩餘工作規格書（交付實作用）

> 日期：2026-07-10
> 目的：自足的實作規格，交給任何工程師或 AI 模型即可獨立完成，不需要其他對話上下文。
> 基準 commit：`8d0acbf`（main，https://github.com/Po-Yu-Chang/OpenScad）
> 上位文件：`OpenCad_Local_AI_CAD_Architecture.md`（架構）、`OpenCad_Code_Review_2026-07-10.md`（歷次審查）、`OpenCad_UI_Fix_Spec_2026-07-10.md`（前次規格）

---

## 0. 現況：已完成、不要重做

以下功能**已實作且經 UI Automation 實測**（真實視窗點擊驗證），直接使用：

- ✅ Worker 生命週期：隨機埠、token 檔交接、父程序監看（無殭屍）、健康檢查啟動判定
- ✅ 「載入範例」端到端：選單 → 5 特徵 → 重建 → 驗證 → GLB 匯出 → 3D 顯示（全 200）
- ✅ 同源 viewer：Worker 在 `/viewer` 伺服 viewer.html＋Three.js assets（勿改回 file://）
- ✅ 鏈式重建（current_solid）、snake_case enum 序列化、標準件查表（ISO 273／NEMA）
- ✅ 幾何驗證：實體數、bbox（X 軸）、體積、孔數（圓柱面邊數判別）；壁厚為 warning
- ✅ 計畫卡片（[套用][取消]）、Ollama 偵測與離線降級、匯出 STEP/STL/GLB
- ✅ 特徵樹（唯讀選取）、參數面板（唯讀顯示 positions/diameter/standard_parts）
- ✅ 測試：47 Python（含 13 golden-model）＋17 .NET；三平台 CI workflow

### 絕對不要改壞的地雷（歷次審查踩過的坑）

1. `SnakeCaseEnumConverter`（`src/OpenCad.Domain/Enums.cs`）——C#↔Python enum 契約，改掉會讓所有命令 500。
2. viewer 必須由 Worker 同源伺服——改回 `file://` 會被 CORS 擋掉 ES module 與 GLB fetch。
3. UI 執行緒規則——背景執行緒禁碰 Avalonia 物件；計時器一律 `DispatcherTimer`。
4. `app.manifest`／`Program.cs` AppBuilder／`WinExe`——不要動。
5. 視窗必須在 `OnFrameworkInitializationCompleted` 內**同步**建立——先 await 再建視窗會導致視窗永不顯示。
6. `RebuildAsync` 內的 `ExportAsync("glb")` 不可移除——preview 端點只回傳已生成的檔案。
7. CanExecute 依賴的屬性 setter 必須觸發 `RaiseCanExecuteChanged`（送出按鈕曾因此永久停用）。
8. 全本地原則：不得引入任何 CDN／雲端依賴；UI 文案繁體中文。

---

## 1. Phase 1 目標與缺口總覽

架構文件 §16 MVP 驗收條件中，**尚未達成**的是：

| MVP 條件 | 狀態 | 對應工作項 |
|---|---|---|
| 可說「把這四個孔改成 M5」 | ❌ | A1 |
| 只修改目標特徵，不重寫整個模型 | ❌（端點有，UI／LLM 未接） | A1、A2 |
| 修改後自動重建和驗證 | 🔶（僅 create 路徑） | A1 |
| 尺寸可由表格直接人工修改 | ❌（參數面板唯讀） | A3 |
| 修改確認與 Undo／Redo | ❌（介面存在、零實作） | A2、A4 |
| 關閉後重新開啟仍能繼續修改 | ❌（Worker 有持久化，App 無開啟 UI） | B1 |
| 能建立矩形、圓、孔、拉伸、切除、陣列、圓角及薄殼 | 🔶（草圖實體只有 3 種） | C1 |
| 以繁中描述建立零件（LLM 全流程） | 🔶（計畫→特徵映射過於簡陋） | A5 |

---

## 2. 工作項規格（按優先序）

### A 組：修改閉環（Phase 1 的核心價值）

#### A1. 語意修改流程——「把這四個孔改成 M5」

這是整個產品的招牌動作，最高優先。

**流程**：使用者輸入修改需求 → LLM 讀取**目前 Feature Graph 摘要**產生 `update_feature` 命令 → UI 顯示差異確認卡片（A2）→ 使用者按〔套用〕→ `ApplyCommandAsync` → 自動重建＋驗證＋刷新 3D 與特徵樹。

**實作點**：

1. `OllamaLlmProvider`（`src/OpenCad.Llm/OllamaLlmProvider.cs`）新增方法：
   ```csharp
   Task<CadCommand> CreateUpdateCommandAsync(string userRequest, string featureGraphJson);
   ```
   - Prompt 必須包含：目前所有特徵的 `feature_id`／`type`／`name`／`parameters`／`standard_parts`（從 `GetProjectAsync` 取得的 JSON 直接嵌入）。
   - 結構化輸出 schema：`action` 限定 `update_feature`，必填 `target_feature_id`、`parameters`（或 `standard_parts`），並要求 `preserve` 列出不得變動的特徵。
   - System prompt 加入規則：「只修改使用者指定的目標，其他特徵一律列入 preserve」「標準件只選標準與等級（如 M5＋normal_clearance），不要給數值」。
2. `MainViewModel.SendAsync` 分流：**已有專案且有特徵**時走修改流程（CreateUpdateCommandAsync），否則走現有的建模計畫流程。
3. Worker 端 `update_feature` 已存在（`server.py`），但只更新 `parameters`——需擴充同時接受 `standard_parts`（M3→M5 改的是 standard_parts.fastener.standard）。同步更新 `ApplyCommandRequest` 已有的欄位處理與 `FeatureGraph.update_feature`。
4. 套用後自動 `RebuildAsync`（含驗證＋GLB＋特徵樹刷新，皆已存在）。

**驗收**：有 Ollama 環境下，載入 NEMA17 範例後輸入「把四個固定孔改成 M5 一般間隙孔」→ 差異卡片顯示 `mount_holes: M3 → M5` → 套用 → 重建後驗證通過、體積變小（M5 孔徑 5.5 > M3 的 3.4）、其他特徵參數不變。無 Ollama 時此路徑顯示引導訊息。

#### A2. 修改差異確認卡片

- `MessageKind` 新增 `Diff`；`ChatMessage` 增加 `ModificationDiff? Diff`（Domain 已有 `ModificationDiff` 類別）。
- 卡片內容：目標特徵名稱、逐參數 `before → after` 表格、preserve 清單、〔套用〕〔取消〕按鈕。
- before 值從目前 graph 取（`GetProjectAsync`），after 值從 LLM 命令取——**在套用前就要算好並顯示**，不是套用後才比。
- 架構文件 §11「修改確認範例」是視覺參考。

#### A3. 參數面板可編輯

- `ParameterItem` 增加 `IsEditable`（feature_id/type/input 不可編輯，數值參數可）。
- 參數面板的 Value 欄改為可編輯（`TextBox`，失焦或 Enter 提交）。
- 提交時組 `update_feature` 命令走 **與 LLM 完全相同的** `ApplyCommandAsync` 路徑（架構原則：「LLM 與人工操作使用相同的命令系統」），成功後自動重建。
- 數值驗證：非數字、負值（長度類）在 UI 端先擋，顯示紅框＋提示。
- 注意：positions 這類陣列參數第一版可維持唯讀（顯示但不可編輯），只開放純量數值。

#### A4. Undo／Redo 與版本紀錄

Worker 端（`cad-worker/cad_worker/server.py`＋`feature_graph.py`）：

1. 每次成功的 `create_feature`／`update_feature`／`delete_feature` 後，把**整份 graph 快照**存入 `{project_dir}/revisions/NNNN.json`（4 位數遞增），內容至少含：graph dict、命令原文、時間戳（ISO 8601）、修改前後參數。
2. 新端點：
   - `GET /api/projects/{id}/revisions` — 版本列表（編號＋時間＋命令摘要）
   - `POST /api/projects/{id}/undo` — 回到上一版（載入快照取代目前 graph，回傳新的目前版本號）
   - `POST /api/projects/{id}/redo` — 前進一版
   - undo 之後有新命令時，捨棄 redo 分支（標準線性歷史）。
3. 快照上限 50 份，超過刪最舊。

App 端：

1. `RevisionManager : IVersionManager`（`OpenCad.Infrastructure`）呼叫上述端點。
2. 工具列加〔復原〕〔重做〕按鈕＋`Ctrl+Z`／`Ctrl+Y` KeyBinding（掛在 Window 層級可以，但要避開輸入框焦點——輸入框內的 Ctrl+Z 交給 TextBox 原生行為）。
3. undo/redo 後自動重建＋刷新（走現有 RebuildAsync）。
4. CanExecute：無可復原版本時停用。

**驗收**：載入範例 → 用參數面板把 `base_pad.length` 改成 8 → 重建後 bbox Z=8 → Ctrl+Z → 重建後 Z=5 → Ctrl+Y → Z=8。pytest 加 revisions/undo/redo 端點測試（至少 4 個案例：快照建立、undo、redo、undo 後新命令捨棄 redo）。

#### A5. 強化計畫→特徵映射（LLM 建模品質）

目前 `ApplyPlanAsync` 的 step→feature 映射過於簡陋（sketch 步驟不會產生 `sketch_entities`，LLM 的自由格式 parameters 大多無法直接建模）。改法：

1. `CreatePlanAsync` 的結構化輸出 schema 收緊：每個 step 的 `parameters` 按 `feature_type` 給明確欄位——sketch 必須輸出 `sketch_entities` 陣列（entity_type 限 rectangle/circle/polygon/slot/line/arc）、pad 必須有 `length`、hole 必須有 `positions`＋（`diameter` 或 `standard`＋`fit`）、fillet 必須有 `radius`＋`edges`。schema 直接從 `schemas/feature.schema.json` 的定義裁剪。
2. `ApplyPlanAsync` 把 step.parameters 中的 `sketch_entities`／`standard_parts` 搬到 Feature 對應欄位（不是全部塞進 `Parameters`）。
3. LLM 測試提示集（架構文件 §19）落地：`tests/prompts/` 放固定繁中提示＋預期命令形狀的 JSON，寫一個需要 Ollama 的 pytest（`@pytest.mark.skipif` 無 Ollama 時跳過）。

**驗收**：有 Ollama 時輸入架構文件 §2 的 NEMA17 例句，套用計畫後能重建出單一實體、含中心孔與 4 孔（體積落在合理範圍）；無 Ollama 時所有現有功能不受影響。

### B 組：專案持久化

#### B1. 專案列表與開啟

- Worker 新端點 `GET /api/projects`（需 token）：回傳已載入專案清單（`project_id`／`name`／`modified_at`／特徵數）。Worker 啟動時已會從磁碟載回專案（`_load_existing_projects`），只缺列表端點。
- App：`OpenProjectCommand` 啟用，點擊顯示專案選擇（簡單做法：對話流中顯示可點選的專案卡片清單，或 Avalonia `Window` 對話框）。選定後 `GetProjectAsync` → 重建 → 顯示。
- `modified_at` 在每次成功命令後更新到 manifest。

**驗收**：載入範例 → 關閉 app → 重開 → 開啟專案 → 看到同一個模型與特徵樹（MVP 條件「關閉後重新開啟仍能繼續修改」）。

#### B2. 專案重新命名與刪除

- `PATCH /api/projects/{id}`（name）、`DELETE /api/projects/{id}`（連同目錄，需確認）。
- UI：專案列表項目的右鍵或按鈕。低優先，時間不夠可延後。

### C 組：建模能力補全

#### C1. 草圖實體補全：slot／line／arc／construction_line

- `schemas/feature.schema.json` 的 `sketch_entity.entity_type` enum 已定義 8 種；adapter（`_add_sketch_entity`）只實作 3 種。
- 補上：
  - `slot`（長圓孔）：`SlotCenterToCenter`（build123d）；參數 `center_x/center_y/length/width/angle`
  - `line`＋`arc`：組合成 wire 再 `make_face`（多段輪廓）；第一版可要求「line/arc 序列必須閉合」，不閉合回結構化錯誤 `SKETCH_NOT_CLOSED`（新錯誤碼，同步加進 `ErrorCodes.cs` 與 `_classify_error`）
  - `construction_line`：不產生幾何，僅保存（供約束中繼資料引用）
- 每種新實體加 golden-model 測試（建一個含 slot 的板、驗證體積範圍）。

#### C2. 沉頭孔（CounterBore）

- `standard_parts.py` 的 `get_counterbore_dimensions` 已有資料但 adapter 未用。
- `_build_hole` 支援 `hole_type: "counterbore"`：先切間隙孔、再切沉頭圓柱（直徑／深度查表）。
- 測試：M3 沉頭孔的體積差 = 間隙孔 + 沉頭部分。

#### C3. 增量重建

- `update_feature` 已把下游標記 `pending`，但 `Build123dAdapter.build()` 每次全量重建。
- 改法：`build()` 增加 `dirty_only` 模式——`rebuild_status == "success"` 且上游無變動的特徵直接重用快取的 `Part`（graph 內或 adapter 持有的 `parts` dict 需在專案生命週期內保留，掛在 `projects[pid]["parts_cache"]`）。
- 注意鏈式重建的語意：current_solid 鏈上任何一節 dirty，其後全部要重建（拓撲順序決定）。
- **先寫測試再改**：同一 graph 改一個 fillet 半徑，斷言 sketch/pad 的 build 次數不增加（可用 adapter 上的計數器）。單零件規模下效能收益有限，此項是為 Phase 2 鋪路——時間不夠可最後做。

### D 組：回饋與品質

#### D1. 重建進度接上 UI

- SSE 端點 `GET /api/projects/{id}/events` 已存在但 UI 未消費，且目前它只是走一遍拓撲排序（假進度）。
- 改法（務實版）：重建期間 Worker 把「目前正在建的 feature_id」寫進 `projects[pid]["progress"]`，SSE 每 200ms 推送；App 在 IsBusy 期間開 SSE 連線，把「重建中…」文字換成「重建中：馬達座底板（2/5）」。
- 單零件重建 <1s，此項視覺價值大於功能價值——排在 A、B 之後。

#### D2. 修復迴圈（Repair Agent，上限 3 次）

- 架構文件 §12 的要求。`ReviewResultAsync` 已定義未使用。
- 流程：重建失敗（結構化錯誤）→ 若有 Ollama，把 `error_code`＋`engine_message`＋失敗特徵參數餵給 LLM 產生修正的 `update_feature` → 顯示為差異卡片（**仍需使用者確認**，不自動套用）→ 重試上限 3 次後停止並提示人工處理。
- 無 Ollama：只顯示結構化錯誤與 `GetSuggestionScope` 的建議方向。

#### D3. 驗證器補全

- bbox 檢查目前只比 X 軸（`validators/__init__.py` `_check_expected`）——補 Y/Z。
- `ValidationReport` 增加 `surface_area` 已有；UI 狀態列補顯示表面積（MVP 條件）。

### E 組：測試與工具

#### E1. UI 自動化冒煙測試腳本

- 把已驗證可行的 UIAutomation 點擊流程（啟動 → 點載入範例 → 等待 → 驗證 log 中 `POST rebuild 200`＋`GET preview.glb 200` → 關閉 → 確認無殘留 python）固化成 `tests/ui/smoke-test.ps1`。
- 不進 CI（CI runner 無桌面），但成為本機驗收的標準工具；README 開發者章節註明用法。

#### E2. 新功能測試覆蓋

- 每個 A–C 工作項的驗收條件都要有對應自動化測試（pytest 或 xUnit）。
- undo/redo、update_feature with standard_parts、slot golden model、counterbore golden model 為最低要求。

---

## 3. 建議實作順序

1. **A1＋A2**（語意修改＋差異卡片）——產品核心，其餘都是圍繞它
2. **A4**（Undo/Redo）——修改閉環的安全網
3. **A3**（參數面板編輯）——與 A1 共用命令路徑，順手完成
4. **B1**（專案開啟）——MVP 驗收條件
5. **C1＋C2**（草圖實體＋沉頭孔）
6. **A5**（LLM 建模品質）
7. **D2、D3、E1、E2**
8. **C3、D1、B2**（時間不夠可延後）

## 4. 完成定義（整體驗收）

1. `dotnet build` 0 錯誤 0 警告；pytest 與 xUnit 全綠（含新增測試）。
2. `tests/ui/smoke-test.ps1` 通過。
3. MVP 條件逐條打勾：載入範例 → 表格改參數 → 重建 → Ctrl+Z 復原 → 關 app → 重開 → 開啟專案繼續改。
4. 有 Ollama 環境：「把這四個孔改成 M5」端到端成功且其他特徵不變。
5. 全程斷網可完成 1–3。
