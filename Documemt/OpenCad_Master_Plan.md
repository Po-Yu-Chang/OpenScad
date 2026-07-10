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

## 3.5 下一包：聊天輸入 Enter 修正＋LLM 對話上下文記憶

### 包 A：Enter 重複輸入修正（bug，先做）

**現象**：右欄輸入框按 Enter，字彙出現兩次。

**現況程式**（實查結論，發包者不用重查）：
- Enter 送出邏輯在 `MainWindow.axaml.cs:74-93`——`OnLoaded` 內 `promptInput.KeyDown += OnPromptKeyDown`；Enter 無修飾鍵 → `e.Handled=true` + `SendCommand.Execute`。
- 輸入框 `PART_PromptInput`：`AcceptsReturn=True`、雙向綁 `InputText`（`MainWindow.axaml:254-259`）；送出按鈕無 `IsDefault`、`Window.KeyBindings` 只有 Ctrl+Z/Y——**XAML 沒有第二條 Enter 路徑**（已排除）。
- `SendAsync` 開頭同步 `Messages.Add`＋清空 `InputText`（`MainViewModel.cs:636-642`）；`AsyncRelayCommand` 有 `_isRunning` 再入保護——命令層單一呼叫不會重複。

**候選根因（先重現、分辨是哪一種，修法不同）**：
1. **IME 選字衝突（最可能）**：中文輸入法（注音/拼音）的 Enter 是「確認選字」；Avalonia Win32 IME 與 KeyDown 的互動有已知重複輸入案例。若現象是「**輸入框內**文字重複」（非聊天泡泡重複），屬此類。修法順序：(a) Avalonia 11.2.7 → 11.3.x 實測（IME 修復多）；(b) 仍在則 KeyDown 檢查組字狀態（TextInputMethodClient），組字中不觸發送出。
2. **事件雙重掛載**：`Loaded` 若重入會重複 `+= KeyDown`（`_messagePollTimer` 也會重複啟動）。防禦法：掛載前先 `-=`，或搬進建構式一次性掛載。此防禦無論根因為何都應加上。

**驗收（UIA 實測，缺一不可）**：
1. 英文輸入「hello」＋Enter → 聊天出現一次、輸入框清空。
2. 中文 IME（微軟注音）輸入「底板」經選字 Enter → 輸入框只出現「底板」一次**且不送出**；再按一次 Enter 才送出、泡泡一次。
3. Shift+Enter 換行不送出。
4. Enter 與「送出」按鈕交錯操作不重複、不掉字。
5. `dotnet build` 0 警告；smoke-test PASS。

### 包 B：LLM 對話上下文記憶

**問題**：兩個 provider 的 `SendStructuredAsync` 每次只送「system＋單輪 user」（`OpenAiCompatibleLlmProvider.cs:56-60`、`OllamaLlmProvider.cs:27-30`），LLM 零對話記憶——第二句「再把它加厚一點」（代名詞指涉）必失憶。Feature Graph JSON 只代表模型現況，補不了「上一輪說過什麼」。

**方案：不引入 LangChain**。LangChain 是 Python/JS 編排框架；這裡只需要「把歷史輪次塞進 messages 陣列」，C# 直接做、零新依賴：
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

**需求**（參照 SolidWorks/Onshape 行為）：
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

**驗收**：
1. 截圖目視：triad 常駐右下（或右上）角；旋轉相機至前視 → triad 的 X 朝右、Z 朝上，方向正確；進出草圖模式 triad 不消失、不重複。
2. UIA＋WebView 無障礙樹實測：視窗點擊「前基準面」→ 特徵樹 Front 節點被選取 → 按「新增草圖」→ 進入 XZ 草圖模式（相機前視）。
3. 樹選取「右基準面」→ 截圖比對視窗 YZ 平面高亮；取消選取 → 高亮消失。
4. 基準面點擊不干擾既有模型面選取與 OrbitControls 拖曳（點空白處旋轉照常）。
5. `dotnet build` 0 警告；smoke-test PASS；三平台 CI 綠（純 viewer.html＋訊息通道，無平台特定碼）。

---

## 4. P1：單零件能力補全（依 SolidWorks 課綱優先序）

1. ~~**line/arc 閉合輪廓**（最優先，配 P0 才能畫異形板）＋sketch mirror／offset entities；不閉合回 `SKETCH_NOT_CLOSED` 錯誤碼。~~ ✅已完成（line/polyline/arc/construction_line 實體支援，viewer 工具列按鈕，閉合驗證，SKETCH_NOT_CLOSED 錯誤碼）
2. ~~**Sweep／Loft**：build123d 有 `sweep()`/`loft()`；需「路徑草圖＋輪廓草圖」雙輸入（references 已支援）。~~ ✅已完成（`_build_sweep` 輪廓沿路徑掃描，2D→3D 座標映射；`_build_loft` 多輪廓漸變實體；schema/enum/LLM prompt/5 golden tests）
3. ~~**Hole Wizard 補全**：counterbore（資料在 standard_parts.schema.json，adapter 未接）、countersink（ISO 10642 新增資料表）、攻牙底孔查表；UI 做 PropertyManager 式孔型選擇。~~ ✅counterbore 已完成（adapter `_build_hole` 支援 hole_type=counterbore，查表取得沉頭尺寸，兩段式切除）；countersink/攻牙底孔待補
4. ~~**質量屬性**：專案材質欄位（PLA/ABS/鋁/鋼密度查表）→ 質量顯示於狀態列與驗證報告。~~ ✅已完成（standard_parts 密度表 12 材質、calculate_mass、server.py rebuild 回傳 mass_properties、C# MassProperties/BoundingBoxMm 類別、MainViewModel MassInfoText 顯示、set_material 命令、5 golden tests）
5. ~~**剖面視圖**：viewer 端 Three.js clipping plane＋抬頭工具列切換（純顯示）。~~ ✅已完成（viewer.html 剖面按鈕、軸/位置/反轉控制、renderer.localClippingEnabled、ClipPlane 套用至 mesh material）
6. **量測工具**：viewer 點兩點顯示距離。
7. Rib（輪廓拉伸＋fuse）；Draft 視 build123d 支援度再評估。

### Phase 1 殘留小項（併入本級）
- ✅ A5 計畫→特徵映射強化：CreatePlanAsync schema 收緊（sketch 步驟必須輸出 sketch_entities；hole 必須 positions＋standard）；`tests/prompts/` 固定提示集（無 LLM 時 skip）。
- C3 增量重建：`rebuild_status=="success"` 且上游未變的特徵重用快取 Part（先寫 build 次數計數測試再改）。
- D1 SSE 進度接 UI：Worker 寫「目前重建中的特徵」，app 於 IsBusy 期間顯示「重建中：底板（2/5）」。
- ✅ D2 修復迴圈：重建失敗→LLM 產生修正 update_feature→差異卡片（仍需人工確認）→上限 3 次。
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

0. **聊天輸入 Enter 修正＋上下文記憶＋座標系/可點選基準面**（§3.5 包 A/B/C——包 A 是現行 bug，優先）
1. **P0 草圖基準面**（§3）
2. P1-1 line/arc＋P1-3 Hole Wizard
3. P1-2 Sweep/Loft＋P1-4 質量屬性＋P1-5 剖面
4. P3 組態/設計表（低成本可插隊）
5. Phase 1 殘留（A5/C3/D1/D2/B2）
6. P2 組合件（先寫細規格）
7. P3 動畫/工程圖、跨平台發行
