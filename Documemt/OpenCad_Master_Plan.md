# OpenCad 總計畫（Master Plan）

> 最後更新：2026-07-10（commit `efba613` 之後）
> 定位：**唯一的活文件**——現況、待辦、地雷、驗證方法都在這裡。
> 架構原理見 `OpenCad_Local_AI_CAD_Architecture.md`（不常變動的基礎文件）。
> 歷史規格與審查報告已刪除，需要時從 git 歷史挖（`git log --oneline -- Documemt/`）。

---

## 1. 現況：已完成且驗證通過

以下全部經過實測（UIAutomation 實際點擊／引擎層 HTTP 重演／截圖目視），**不要重做**：

### 基礎設施
- Worker 生命週期：隨機埠、token 檔交接、父程序監看（app 死掉 3 秒內自我終止，無殭屍）、健康檢查啟動判定
- 同源 viewer：Worker 在 `/viewer` 伺服 viewer.html＋本地 Three.js（勿改回 file://，CORS 會擋 ES module）
- 專案持久化：`~/.opencad/worker/`，重啟自動載回（含 `_current_rev` 還原）
- LLM 可設定：`~/.opencad/settings.json`（provider: auto/openai/ollama/none）；`OpenAiCompatibleLlmProvider` 支援 LiteLLM Gateway；檔案選單「LLM 設定…」「重新偵測 LLM」

### 建模與驗證
- Feature Graph：拓撲排序、循環防護、鏈式重建（current_solid）、snake_case enum 契約（C#↔Python）
- 特徵：sketch(rect/circle/polygon/slot)、pad、pocket、hole(含 ISO 273 查表)、fillet/chamfer(邊選擇器)、shell、pattern、mirror、revolve、boolean
- 驗證器：實體數、bbox(XYZ)、體積、孔數(圓柱面邊數判別)、壁厚(warning)
- 版本控制：revisions 快照、undo/redo(含 redo 分支捨棄)、Ctrl+Z/Y

### UI（Zoo 式版面＋SolidWorks 慣例）
- 三欄可調(GridSplitter)、特徵樹(型別圖示＋右鍵選單)、參數面板(可編輯＋✓套用)、主題資源集中
- 對話輸入在右欄底部(airspace 安全區)、viewer 內 HTML 抬頭工具列(視角＋縮放至適合)
- 草圖模式：正交編輯、確認角、PropertyManager 式數值對話框、尺寸標籤、提交走 update_feature(sketch_entities)
- LLM 流程：計畫卡片、修改差異卡片(before/after、一次性按鈕)、「把四個孔改成 M5」已用真實 LiteLLM 驗證

### 測試
- 58 Python(含 13 golden-model、7 revisions、4 sketch_entities)＋17 .NET
- `tests/ui/smoke-test.ps1`：UIAutomation 垂直切片冒煙測試(啟動→點載入範例→rebuild 200→GLB 200→無殘留)

---

## 2. 地雷清單（改壞任何一條都會回歸——歷次實測踩過的坑）

1. `SnakeCaseEnumConverter`（`OpenCad.Domain/Enums.cs`）——C#↔Python enum 契約，動了所有命令 500。
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

---

## 3. P0：草圖基準面（下一包，可直接實作）

**問題**：真實 CAD 開草圖第一步是選平面（SolidWorks 的 Front/Top/Right Plane），OpenCad 草圖隱含 XY——做不出側向特徵（L 型架、側面開孔）。

### 3.1 資料模型
`feature.schema.json` 的 sketch 特徵加 `plane` 欄位：
```json
"plane": { "base": "XY|XZ|YZ", "offset": <mm, 預設 0> }
```
- Python `Feature` dataclass＋C# `Feature` 同步加欄位。
- **向下相容**：缺 plane 視為 XY（三個範例與既有專案不得壞）。
- 繁中對照：XY=上基準面、XZ=前基準面、YZ=右基準面。

### 3.2 Adapter
```python
plane_map = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}
work = plane_map[base].offset(offset_mm) if offset_mm else plane_map[base]
with BuildSketch(work) as sketch: ...
```
pad 的 extrude 沿草圖法向（build123d 自動）。

### 3.3 UI
1. 特徵樹頂端**常駐**三基準面節點＋原點（SolidWorks FeatureManager 慣例；非 Feature、不進 graph、不可刪）。
2. 「✏ 草圖」流程：已選基準面節點 → 直接開；否則彈平面選擇（上/前/右＋偏移值）。
3. `enterSketchMode(featureId, entities, plane)` 加 plane 參數：相機 normal-to、網格畫在該平面。
4. sketch 樹節點顯示「(sketch@XZ)」。
5. LLM prompt 規則補「sketch 必須指定 plane.base」。

### 3.4 驗收
1. 選「前基準面」→ 草圖 → viewer 前視、XZ 網格；畫 60×40 → pad 5 → bbox 60×5×40。
2. NEMA17（無 plane 舊資料）照常運作。
3. pytest：XZ/YZ 草圖 bbox golden 測試 ≥2；smoke-test PASS。

**保留介面**：plane.base 未來可為 `face:{feature_id}:{selector}`（模型面上開草圖＝Phase 2 persistent reference 課題）。

---

## 4. P1：單零件能力補全（依 SolidWorks 課綱優先序）

1. **line/arc 閉合輪廓**（最優先，配 P0 才能畫異形板）＋sketch mirror／offset entities；不閉合回 `SKETCH_NOT_CLOSED` 錯誤碼。
2. **Sweep／Loft**：build123d 有 `sweep()`/`loft()`；需「路徑草圖＋輪廓草圖」雙輸入（references 已支援）。
3. **Hole Wizard 補全**：counterbore（資料在 standard_parts.schema.json，adapter 未接）、countersink（ISO 10642 新增資料表）、攻牙底孔查表；UI 做 PropertyManager 式孔型選擇。
4. **質量屬性**：專案材質欄位（PLA/ABS/鋁/鋼密度查表）→ 質量顯示於狀態列與驗證報告。
5. **剖面視圖**：viewer 端 Three.js clipping plane＋抬頭工具列切換（純顯示）。
6. **量測工具**：viewer 點兩點顯示距離。
7. Rib（輪廓拉伸＋fuse）；Draft 視 build123d 支援度再評估。

### Phase 1 殘留小項（併入本級）
- A5 計畫→特徵映射強化：CreatePlanAsync schema 收緊（sketch 步驟必須輸出 sketch_entities；hole 必須 positions＋standard）；`tests/prompts/` 固定提示集（無 LLM 時 skip）。
- C3 增量重建：`rebuild_status=="success"` 且上游未變的特徵重用快取 Part（先寫 build 次數計數測試再改）。
- D1 SSE 進度接 UI：Worker 寫「目前重建中的特徵」，app 於 IsBusy 期間顯示「重建中：底板（2/5）」。
- D2 修復迴圈：重建失敗→LLM 產生修正 update_feature→差異卡片（仍需人工確認）→上限 3 次。
- B2 專案重新命名/刪除（PATCH/DELETE 端點＋UI）。

---

## 5. P2：組合件與標準件庫（大工程，先寫細規格再發包）

- **文件模型**：assembly 文件型別＝part instances（引用 part 專案＋變換矩陣）；Assembly Graph 疊在 Feature Graph 之上。
- **配合 Mates**（SolidWorks 分級）：標準（coincident/concentric/distance/parallel/angle）→ 進階（width/path/limit）→ 機械（gear/screw/cam/hinge）。第一版順序求解（fix 首件、逐配合定位），不做完整 DOF 求解器。
- **干涉檢查**：兩兩 intersect 體積>0 即報。
- **爆炸圖**：每 instance 爆炸位移向量，viewer 插值動畫。
- **Connector／Toolbox**：標準件庫生成參數化幾何（ISO 4762/4014 螺絲、螺帽、墊圈、608 類軸承），插入時自動與孔同心配合；沿用「LLM 選型、引擎查表」原則。

## 6. P3：動畫、工程圖、組態

- **Motion Study 簡化版**：時間軸 UI（viewer）、關鍵影格＝instance 變換、旋轉馬達＝繞配合軸角速度、爆炸/收合動畫、輸出 GIF/MP4（逐幀截圖）。物理模擬（重力/接觸）不做——CAE 串外部工具。
- **工程圖**（架構 Phase 5）：三視圖＋等角、自動尺寸建議、PDF/DXF（build123d `section()`＋DXF 匯出為地基）。
- **組態/設計表**：parameters.json 陣列化＋UI 下拉切換——低成本高價值，可插隊。

## 7. 跨平台與發行（架構文件既定，尚未動工)

- macOS/Linux 實測（WebView 宿主與訊息輪詢）；CI 三平台矩陣已有，Worker 打包（conda-pack）未做。
- 三平台一鍵安裝包（.exe/.dmg/.AppImage）＋Velopack 自動更新——release.yml 骨架已在。

---

## 8. 驗證方法論（每一包交付都照此驗收）

1. `dotnet build OpenCad.slnx` → 0 錯誤 0 警告。
2. `python -m pytest tests/cad-worker/ -q` 與 `dotnet test` → 全綠（新功能必附新測試）。
3. `powershell -ExecutionPolicy Bypass -File tests\ui\smoke-test.ps1` → PASS。
4. **UI 必須實際驅動驗證**：UIAutomation 點擊（Avalonia 控制項）＋截圖目視（airspace 類問題）＋WebView2 無障礙樹（HTML 按鈕）。
5. 引擎層驗收：起 Worker（`OPENCAD_WORKER_PORT`/`OPENCAD_TOKEN_FILE`/`OPENCAD_WORK_DIR` 環境變數）直接 HTTP 重演使用者流程，斷言幾何數值。
6. LLM 相關：用真實 gateway（設定見 `~/.opencad/settings.json`）實測語意正確性。
7. 全程斷網可完成 1–5（LLM 除外）。

## 9. 建議發包順序

1. **P0 草圖基準面**（§3）
2. P1-1 line/arc＋P1-3 Hole Wizard
3. P1-2 Sweep/Loft＋P1-4 質量屬性＋P1-5 剖面
4. P3 組態/設計表（低成本可插隊）
5. Phase 1 殘留（A5/C3/D1/D2/B2）
6. P2 組合件（先寫細規格）
7. P3 動畫/工程圖、跨平台發行
