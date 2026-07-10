# OpenCad Phase 0 程式碼審查報告

> 日期：2026-07-10（第一輪）／2026-07-10（第二輪覆審，見文末）
> 範圍：`src/`（C# .NET 8／Avalonia）、`cad-worker/`（Python FastAPI／build123d）、`schemas/`、`examples/`、`.github/workflows/`
> 方法：讀取原始碼＋實際執行測試／建置／驗證腳本重現問題（非僅靜態閱讀），可重現的發現皆標註驗證方式。

---

## 一、整體結論

- `dotnet build OpenCad.slnx` 建置成功（0 錯誤／2 警告）。
- `dotnet test`：**17/17 通過**。
- `pytest tests/cad-worker/`：**30/30 通過**。
- 但測試覆蓋不到跨程序整合路徑（C# ↔ Python HTTP）、`build123d_adapter.py` 的實際建模邏輯、以及三個範例模型的載入——問題都出在這些沒被測試覆蓋到的地方。

---

## 二、後端／整合問題

### 🔴 Critical

**1. Worker 工作階段 Token 交握機制無法成功**

- `src/OpenCad.Infrastructure/CadWorkerClient.cs:138-153`（`GetSessionTokenAsync`）預期從 `GET /api/health` 讀到 `"token"` 欄位。
- `cad-worker/cad_worker/server.py:87-94`（`health()`）實際回傳 `{"status", "version", "build123d_available"}`，**沒有 token 欄位**；`SESSION_TOKEN` 只印在 Worker 的 stdout。
- 驗證方式：直接呼叫 `TestClient(app).get("/api/health")`，回傳內容確認無 `token` 鍵。
- 影響：C# 端永遠無法取得正確 Token，所有需要驗證的端點（建立專案、套用命令、重建、驗證、匯出）都會收到 `403`。這是目前阻斷整條垂直切片的問題。

**2. CI 的 schema-validation job 對著簽入的三個範例全部會失敗**

- 直接執行 `.github/workflows/ci.yml` 中 `schema-validation` job 用的同一段 `jsonschema.validate()` 邏輯，對 `examples/*/features.json` 與 `examples/*/project.json`（共 6 個檔案）逐一驗證：**全部失敗**。
  ```
  FAIL examples\esp32cam-enclosure\features.json - 'feature_id' is a required property
  FAIL examples\needle-box-5x10\features.json - 'feature_id' is a required property
  FAIL examples\nema17-mount\features.json - 'feature_id' is a required property
  FAIL examples\esp32cam-enclosure\project.json - 'schema_version' is a required property
  FAIL examples\needle-box-5x10\project.json - 'schema_version' is a required property
  FAIL examples\nema17-mount\project.json - 'schema_version' is a required property
  ```
- 根因：`examples/` 底下用的是一套完全不同的資料模型（`id`／`depends_on`／`feature_template`／公式字串如 `"width": "flange_width + 20"`），跟 `schemas/feature.schema.json`（`feature_id`／`input`+`references`／扁平 `sketch_entities`）以及 `Feature.from_dict()` 實際解析的結構不相容。
- 額外問題：即使修好 schema 對應，程式碼中也**沒有任何公式／運算式求值器**，`"flange_width + 20"` 這種字串永遠無法被解析成數值。
- 影響：三個 MVP 展示模型（NEMA17 馬達座、5×10 針盒、ESP32-CAM 外殼）目前**都無法被系統實際載入**；CI 一旦跑到這個 job 就會紅燈。

### 🟠 High

**3. 循環依賴會讓 Worker 在正常編輯路徑上當機**

- `cad-worker/cad_worker/feature_graph.py:229-244`（`_get_downstream`，被 `update_feature`／`delete_feature` 呼叫）沒有循環保護，與 `topological_sort`（有 `temp_marked` 保護）不同。
- 已直接重現：建立 `a.input = "b"`、`b.input = "a"` 兩個特徵後呼叫 `update_feature("a", ...)` → `RecursionError`。
- `add_feature` 只檢查 `feature_id` 是否重複，不檢查是否會形成循環，因此這個當機路徑可由單一錯誤命令觸發，並非純假設情境。

**4. 結構化錯誤分類器實際上從未正確分類**

- `cad-worker/cad_worker/server.py:309-322`（`_classify_error`）用英文關鍵字（`"fillet"`、`"cycle"`、`"circular"`、`"not found"`）比對例外訊息。
- 但 `feature_graph.py`／`standard_parts.py`／`build123d_adapter.py` 內所有 `ValueError` 訊息都是**繁體中文**。
- 已重現：把 4 個代表性中文錯誤訊息餵給 `_classify_error()`，全部落回泛用的 `GEOMETRY_ERROR`。
- 影響：架構文件中「Repair Agent 只消費結構化錯誤」的設計原則實際上不成立——Fillet 失敗、參照遺失、循環依賴會拿到同一個籠統錯誤碼，Repair Agent 無法區分。

**5. Pattern 特徵無法正確對 Hole／Pocket 這類切除特徵做陣列**

- `_build_linear_pattern`／`_build_circular_pattern`（`build123d_adapter.py:243-265, 356-375`）是把 `feature.input` 已建好的 `Part` 複製後 `.fuse()`（聯集）。
- 但 NEMA17 範例（`examples/nema17-mount/features.json` 的 `mount_holes`）把「四個固定孔」設計成 `circular_pattern` 包一個挖孔的 `feature_template`；架構文件的 Feature Graph 示意圖也畫 `Hole Sketch → Hole Pattern`。
- 對一個「切除（SUBTRACT）」的結果做聯集不會讓孔變多，只會把多份「整塊底板＋一個孔」的實體疊在一起——這在幾何上是錯的。目前 `_build_hole` 是靠自己內建的 `positions` 陣列繞開這個問題，但這是另一套沒有寫進文件的機制。
- 建議：Phase 1 前要做設計決策——Pattern 只作用於實體特徵（並修正範例與文件用語），或是實作真正的「陣列切除工具」邏輯。

### 🟡 Medium

**6.** 沒有 `INVALID_STANDARD_PART` 錯誤碼。架構文件邊界測試章節明確要求「不存在的標準：『M3.7 螺絲孔』→ 查表失敗必須回報，不得編造孔徑」，`standard_parts.py` 確實會拋出對應錯誤，但 `ErrorCodes.cs` 與 `_classify_error` 都沒有對應分類（會落入 #4 的泛用桶子）。

**7.** `_build_pocket` 的參照挑選邏輯是死代碼（`build123d_adapter.py:170-178`）：`if hasattr(p, "faces"): sketch_part = p else: sketch_part = p` 兩個分支做一樣的事，`hasattr` 判斷完全沒有作用。若 Pocket 同時參照多個特徵，會直接採用清單中最後一個，不論型別是否正確。

### 🟢 Low

**8.** 專案資料存在 `tempfile.gettempdir()/opencad_worker`（`server.py:39`），`projects` 是純記憶體字典。Worker 程序重啟即遺失所有開啟中的專案，牴觸 MVP 驗收條件「關閉後重新開啟仍能繼續修改」與第 13 節的持久化專案資料夾設計。

**9.** `RelayCommand`／`RelayCommand<T>.CanExecuteChanged` 從未被觸發（編譯器已警告 CS0067）。目前無害（尚無 ViewModel 傳入 `canExecute`），但未來一旦有條件式命令，按鈕的啟用／停用狀態不會自動刷新。

**10.** `CadWorkerClient.ApplyCommandAsync`／`RebuildAsync`（`CadWorkerClient.cs:56-71, 73-86`）在解析 JSON 前不檢查回應狀態碼。目前搭配 Worker 回傳的結構化錯誤 JSON還算能動，但任何傳輸層失敗（含發現 1 的 403）都會拋出未處理的 `JsonException` 而非乾淨錯誤訊息。

---

## 三、OpenCad.Desktop UI 設計問題

### 🔴 Critical

**11. 3D 視窗完全沒有實作——只是佔位文字**

- `MainWindow.axaml:53-61` 中間欄（Grid.Column="1"）只有：
  ```xml
  <Border Grid.Column="1" Background="#1e1e2e">
      <Grid RowDefinitions="*,Auto">
          <TextBlock Text="3D 視窗" .../>
          <TextBlock Text="{Binding ModelInfoText}" .../>
      </Grid>
  </Border>
  ```
  沒有任何 WebView 控制項。
- `OpenCad.Viewer.csproj` 完全沒有引用任何 WebView 套件（無 `Avalonia.WebView`、無平台 WebView 綁定），確認方式：直接讀取該 `.csproj`，只有 `TargetFramework`／`Nullable` 設定，無 `PackageReference`。
- `ViewerBridge.cs` 只是純訊息解析／JS 呼叫字串產生器，沒有任何地方把它接到一個真正的 WebView 控制項上。
- 影響：架構文件整章討論的「跨平台 WebView＋Three.js」——這個產品的核心賣點之一——目前在 UI 層**完全不存在**。`viewer.html`／`ViewerBridge.cs` 是孤兒檔案，寫好了但沒有被使用。

**12. `viewer.html` 從 CDN 載入 Three.js，直接牴觸「全本地運行」的核心原則**

- `src/OpenCad.Viewer/viewer.html:35-42`：
  ```html
  <script type="importmap">
  { "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"
  }}
  </script>
  ```
- 架構文件與 MVP 驗收條件明確要求「網路完全中斷時仍能操作」；目前只要斷網，3D 視窗會直接載入失敗（連 Three.js 本身都下載不到），不僅是模型顯示失敗。
- 建議：Three.js 應打包進 `OpenCad.Viewer` 專案資源中隨應用程式一起發行，而非透過 CDN 動態載入。

### 🟠 High

**13. `viewer.html` 的回呼機制寫死 WebView2 專屬 API，其他兩個平台會靜默失效**

- `viewer.html:112-115`、`165-168`、`175`：三處都用 `window.chrome?.webview?.postMessage({...})`。
- `window.chrome.webview` 是 **Windows WebView2（Edge Chromium）專屬**的 API。macOS 的 WKWebView 對應的是 `window.webkit.messageHandlers.<name>.postMessage(...)`；Linux 的 WebKitGTK 又是另一套注入機制。
- 因為呼叫鏈用了 `?.` 可選鏈結，在非 Windows 平台上會**靜默不做任何事**，不會報錯，只是選取回報、載入完成通知、錯誤通知全部消失。這直接牴觸文件裡「前端 Three.js 程式碼三平台共用」的承諾——程式碼共用了，但橋接呼叫並沒有真的跨平台。
- 建議：抽出一個 `postToHost(type, payload)` 小函式，依 `navigator.userAgent` 或建置時注入的旗標分派到對應平台 API，或統一改用 Avalonia WebView 套件提供的跨平台訊息通道。

**14. 特徵樹的 `TreeDataTemplate` 沒有指定 `ItemsSource`，巢狀特徵不會展開**

- `MainWindow.axaml:43-47`：
  ```xml
  <TreeView.ItemTemplate>
      <TreeDataTemplate>
          <TextBlock Text="{Binding DisplayName}" Foreground="#cdd6f4" />
      </TreeDataTemplate>
  </TreeView.ItemTemplate>
  ```
- `FeatureNode.Children`（`ViewModels/Models.cs:37`）是 `ObservableCollection<FeatureNode>`，但 `TreeDataTemplate` 沒有設定 `ItemsSource="{Binding Children}"`。Avalonia（與 WPF 的 `HierarchicalDataTemplate` 相同）需要明確告知樹狀節點的子項來源，否則 `TreeView` 只會顯示扁平的頂層項目，不會出現展開箭頭或巢狀子節點。
- 影響：特徵樹如果之後真的做出巢狀結構（例如 Sketch 底下掛多個約束、Pattern 底下掛被陣列的特徵），UI 上完全看不出階層關係。

**15. 完全沒有「修改計畫確認」UI，但這是架構文件第 11 節的核心互動模式**

- 架構文件明確要求：「執行前顯示修改計畫」「[套用] [修改計畫] [取消]」，且「LLM 與人工操作使用相同的命令系統」。
- `MainWindow.axaml` 裡沒有任何計畫預覽／確認的區塊；`MainViewModel.Send()`（`ViewModels/MainViewModel.cs:80-93`）目前只是把使用者輸入原樣丟回聊天視窗，附上一句「Phase 0 階段」提示。
- 這不只是「還沒接上 LLM」的問題——**UI 上連放這個功能的位置都還沒設計**，之後要嘛在對話串裡插入一種新的訊息型別（帶按鈕的計畫卡片），要嘛開一個獨立面板，這是需要提前規劃的 UI 結構問題，不是後補的小修正。

### 🟡 Medium

**16. 三欄式版面完全沒有 `GridSplitter`，使用者無法調整欄寬**

- `MainWindow.axaml:37`：`<Grid Grid.Row="1" ColumnDefinitions="260,*,320">` 是寫死的欄寬，左側特徵樹 260px、右側對話 320px，中間 3D 視窗吃剩下空間，全程無法拖曳調整。
- 對 CAD 軟體而言，特徵樹（特別是深層特徵）和 AI 對話（長篇繁中說明）都很容易需要更寬的顯示空間，寫死寬度在真實使用情境下會很快變得不夠用。
- 建議：三個分隔處都加上 `GridSplitter`，並將偏好寬度存進使用者設定。

**17. 色彩全部用硬編碼 Hex 字串灑在 XAML 各處，沒有集中成主題資源**

- 統計：`#1e1e2e`／`#181825`／`#cdd6f4`／`#313244`／`#a6adc8`／`#45475a`／`#6c7086`／`#11111b` 等色碼直接寫在 `MainWindow.axaml` 十餘處屬性值裡，`ChatMessage.cs` 裡也重複硬編碼了 `#313244`／`#45475a`。
- `App.axaml` 設了 `RequestedThemeVariant="Dark"`，但因為顏色都是字面值而非 `DynamicResource`／`ThemeVariant` 資源，未來若要支援淺色主題或使用者自訂主題，需要逐一修改每個 XAML 屬性，且 `ChatMessage` 這種 ViewModel 裡的顏色常數會需要另外處理。
- 建議：把這組 Catppuccin 風格色票整理進 `App.axaml` 的 `<Application.Resources>`，用 `DynamicResource` 綁定，顏色只需改一處。

**18. `Title`／`Width`／`Height` 在 XAML 與程式碼裡重複設定**

- `MainWindow.axaml:5-7` 已經設了 `Title`／`Width="1280"`／`Height="800"`／`MinWidth`／`MinHeight`。
- `App.axaml.cs:18-23` 又在建構 `MainWindow` 後立刻重新指定一次 `Title`／`Width`／`Height`（`MinWidth`／`MinHeight` 沒有跟著複製，但因為是分開設定不影響，只是維護上容易顧此失彼）。
- 建議：只在 XAML 或只在程式碼其中一處設定，避免兩處改了其中一處忘記同步。

### 🟢 Low

**19.** `TreeView` 選取狀態下的對比度沒有驗證：`TextBlock` 的 `Foreground="#cdd6f4"`（淺色）是寫死的，不會隨 FluentTheme 預設的選取反白背景色而自動切換文字顏色，若選取背景也偏淺色系可能造成可讀性問題（需要實際執行 UI 才能確認，此處列為風險提示）。

**20.** 頂部工具列按鈕（新增／開啟／儲存專案、匯出 STEP／STL、重建）目前全部只會在聊天視窗印出一行「Phase 1 實作」文字（`MainViewModel.cs:95-129`），這在程式碼裡有清楚的 `// TODO: Phase 1` 標註，屬於已知、有追蹤的範圍內事項，不算設計缺陷，但列出以確保與其他項目的優先順序區分開來。

---

## 四、建議優先順序

1. **先修 #1（Token 交握）與 #11（接上真正的 WebView 控制項）**——這兩項卡住了整條「LLM 對話 → 命令 → 建模 → 3D 顯示」垂直切片，其他功能再完整也展示不出來。
2. **接著修 #2（範例／Schema 對不上）**，否則 CI 永遠是紅的，且三個 MVP 展示模型無法驗證。
3. **#12（CDN 依賴）與 #13（WebView2 專屬 API）** 一起處理，因為都在 `viewer.html`，且都直接牴觸「全本地」「跨平台」兩項核心產品原則。
4. #3～#10、#14～#18 可在後續迭代排入 Phase 1 待辦清單。

---
---

# 第二輪覆審（修復驗證＋新發現）

> 覆審範圍：16:23–16:28 修改的檔案批次。所有結論皆經實際執行驗證。

## 五、第一輪問題修復驗證

| # | 問題 | 狀態 | 驗證方式 |
|---|------|------|---------|
| 1 | Token 交握無法成功 | ✅ 已修復 | 改用 `OPENCAD_TOKEN_FILE` 檔案交接：`CadWorkerProcess` 設環境變數並輪詢等待、`server.py` 啟動時寫入。設計合理，`Stop()` 會清理檔案 |
| 2 | 範例／Schema 不相容 | ✅ 已修復 | 6 個範例檔全部重寫為正式資料模型，`jsonschema.validate()` 實測 **6/6 通過**；公式字串已移除改為數值 |
| 3 | 循環依賴無限遞迴 | ✅ 已修復 | `_get_downstream` 加入 `_visiting` 防護，實測互依特徵 `update_feature` 不再 `RecursionError` |
| 4 | 錯誤分類器對不上中文訊息 | ✅ 已修復 | 加入中文關鍵字比對，實測 5 個代表性訊息全部正確分類 |
| 5 | Pattern 無法陣列切除特徵 | ✅ 已決策 | `_build_linear_pattern` 明確拒絕 hole/pocket 來源並引導改用 `positions`；範例已改用 positions 模式 |
| 6 | 缺 INVALID_STANDARD_PART | ✅ 已修復 | `ErrorCodes.cs` 與 `_classify_error` 皆已加入（含 TRANSPORT_ERROR） |
| 7 | `_build_pocket` 死代碼 | ✅ 已修復 | 改為從 graph 查特徵類型，只挑 `FeatureType.SKETCH` 的參照 |
| 8 | 專案存 temp 目錄不持久 | ✅ 已修復 | `WORK_DIR` 改為 `~/.opencad/worker`（可用環境變數覆寫），啟動時 `_load_existing_projects()` 載回 |
| 9 | `CanExecuteChanged` 未觸發 | ✅ 已修復 | 兩個 RelayCommand 都加了 `RaiseCanExecuteChanged()` |
| 10 | Client 不檢查 HTTP 狀態碼 | ✅ 已修復 | `ApplyCommandAsync`／`RebuildAsync` 加入狀態碼檢查與 `TryParseStructuredError`，傳輸失敗回 `TRANSPORT_ERROR` |
| 12/13 | viewer.html CDN／WebView2 專屬 API | ❌ 未修改 | `viewer.html` 內容未變，兩個問題原封不動 |
| 11 | 3D 視窗未實作 | ⚠️ 修一半且弄壞建置 | csproj 加了 `WebView.Avalonia` 套件，但 XAML 仍是佔位 TextBlock，且 Program.cs 引用錯誤命名空間（見新發現 R1） |

## 六、第二輪新發現（全部經實測重現）

### 🔴 Critical

**R1. .NET 建置目前是壞的**

- `src/OpenCad.Desktop/Program.cs:4`：`using Avalonia.WebView.DesktopX;` —— `WebView.Avalonia 11.0.0.1` 套件中不存在此命名空間。
- 實測：`dotnet build OpenCad.slnx` → `error CS0234`，**整個方案無法建置**。
- 修法：`UseDesktopWebView()` 擴充方法來自 **`WebView.Avalonia.Desktop`** 套件（命名空間 `Avalonia.WebView.Desktop`），csproj 需要加這個套件、using 改名。

**R2. Adapter 的相對匯入錯誤——rebuild 永遠回 503**

- `cad_worker/adapters/build123d_adapter.py:32-33`：`from .feature_graph import ...`、`from .standard_parts import ...` —— 這兩個模組在上層 `cad_worker` 套件，同層匯入必失敗，應為 `from ..feature_graph`。
- 實測：`from cad_worker.adapters import Build123dAdapter` → `ModuleNotFoundError`。
- 影響鏈：`ModuleNotFoundError` 是 `ImportError` 子類 → `server._rebuild` 捕捉後回 **503「CAD 引擎未安裝」**——即使 build123d 明明裝了，錯誤訊息完全誤導。

**R3. `shell` 在 build123d 0.11.1 不存在——整批匯入被拖垮且被靜默吞掉**

- adapter 頂部一次 `from build123d import (28 個名稱)`，實測其中 `shell` 不存在（0.11.1 薄殼要用 `offset()`）。
- 一個名稱失敗 → 整批匯入失敗 → 被 `except ImportError: BUILD123D_AVAILABLE = False` 吞掉 → 建構子誤報「build123d 未安裝。請執行: pip install build123d」。
- 「大批匯入＋靜默降級」讓真正的錯誤（API 名稱不符）偽裝成環境問題。建議：匯入失敗時保留原始例外訊息。

**R4. NEMA17 範例建出來的最終零件一個孔都沒有（特徵卻全報 success）**

- 實測（繞過 R2/R3 後實際執行 adapter）：最終實體體積 = **22445.0 mm³ = 67×67×5 完整實心板**，中心孔 Ø22 與四個 M3 孔全部消失，但兩個 hole 特徵的 `rebuild_status` 都是 `success`。
- 兩個成因疊加：
  1. `build()` 的最終實體候選型別清單（`build123d_adapter.py:70-77`）**不含 `FeatureType.HOLE`**——孔特徵的結果永遠不會被選為最終零件；
  2. 範例的依賴結構是**分支**而非**鏈**：`center_bore` 與 `mount_holes` 的 `input` 都是 `base_pad`，各自從「無孔的原始底板」切孔，彼此不知道對方的存在。即使把 HOLE 加進候選清單，最終也只會拿到「只有其中一組孔」的零件。
- 根本修法：重建時把「目前實體」串成鏈——每個修改實體的特徵以**上一個特徵的結果**為輸入（`base_pad → center_bore → mount_holes → fillet`），或在 `build()` 內維護單一 current-solid 狀態逐特徵套用。這是 Phase 1 前必須做的架構決策。

**R5. `fillet`／`chamfer` 呼叫簽名錯誤——真實引擎上必炸**

- `_build_fillet` 呼叫 `base_part.fillet(radius)`；實測 → `TypeError: Mixin3D.fillet() missing 1 required positional argument: 'edge_list'`。`_build_chamfer` 的 `part.chamfer(length)` 同樣缺 `edge_list`。
- build123d 的 fillet/chamfer 需要邊清單，例如 `part.fillet(radius, part.edges().filter_by(Axis.Z))`。目前參數也沒有「選哪些邊」的欄位，需要 schema 一起補（第一版範例其實有 `"edges": "all_vertical"` 概念，改寫時遺失了）。

**R6. `add` 未匯入——hole／pocket 的 positions 模式全部 `NameError`**

- `_build_hole`（`build123d_adapter.py:245`）與 `_build_pocket` 直接呼叫 `add(base_part)`，但 `add` 只在 `_add_sketch_to_part` 內部區域匯入，頂部批次匯入清單沒有它。
- 實測：執行到 `_build_hole` → `NameError: name 'add' is not defined`。
- **這證明 hole 特徵這條路徑從未被任何測試執行過**——pytest 30/30 全綠但核心建模程式一跑就炸。

### 🟠 High

**R7. 驗證器不檢查 `expected_hole_count`——孔全消失也驗不出來**

- `server._validate` 收集了 `expected["expected_hole_count"]`，但 `GeometryValidator._check_expected` **沒有對應的檢查分支**；`report.hole_count` 也從未被計算（永遠 0）。
- 實測：拿無孔實心板配 `expected_hole_count: 5` 驗證 → 錯誤清單中**沒有任何關於孔數的錯誤**。R4 的「孔全消失」正是驗證器該攔下的場景，現在攔不住。

**R8. `minimum_wall_thickness` 永遠 0.0——設了 `min_thickness_mm` 的模型驗證必失敗**

- `report.minimum_wall_thickness` 沒有任何計算邏輯，恆為 0.0；與 `min_thickness_mm: 3` 比較 → **永遠報「最小壁厚不足」**。
- 實測：正確的實心板也驗證失敗，唯一錯誤是「最小壁厚不足：預期 ≥ 3 mm，實際 0.0000 mm」。
- 影響：驗證器變成「狼來了」——所有帶壁厚條件的模型都紅燈，使用者會學會忽略驗證結果，比沒有驗證更糟。短期修法：未實作的檢查回報 `warnings`（「壁厚檢查尚未實作」）而非 `errors`。

### 🟡 Medium

**R9.** 重複的舊目錄樹：`cad-worker/adapters/`、`cad-worker/validators/`、`cad-worker/exporters/`（頂層）與 `cad-worker/cad_worker/` 內的正式版本並存，內容已分歧（頂層 adapter 還是舊版）。極易改錯檔案，建議刪除頂層三個目錄。

**R10.** 測試覆蓋盲區被第二輪證實：pytest 30/30、dotnet test 17/17 全綠，但 adapter 連匯入都失敗（R2）、建模一跑就炸（R5/R6）、建出來的幾何是錯的（R4）。**測試全綠給了虛假的安全感**。建議優先補：(a) `test_adapter_import`（一行就能抓到 R2/R3）；(b) 一個最小 golden-model 幾何測試（建 NEMA17 → 斷言體積在預期範圍），一個測試同時抓 R4/R5/R6。

## 七、UI 重設計建議（參考 Zoo Design Studio）

現有 UI 的根本問題不只是「3D 視窗沒接」，而是**版面優先順序錯了**：AI 對話佔掉固定 320px 右欄、3D 視窗反而是夾在中間的空白區。Zoo Design Studio（開源 `KittyCAD/modeling-app`）的版面值得直接借鏡：

### Zoo 的版面結構

```
┌─────────────────────────────────────────────────────────────┐
│ 頂部工具列：建模動作（Sketch│Extrude│Revolve│Fillet…）        │
├────────┬──────────────────────────────────────┬─────────────┤
│ 左側欄  │                                      │ 程式碼編輯器 │
│(可收合) │        3D Viewport（主角，最大）      │ (可收合)     │
│ 檔案樹  │                          ┌──┐        │ KCL ↔ 3D    │
│ 特徵樹  │              view gizmo → └──┘        │ 雙向同步     │
│ 變數    │                                      │             │
├────────┴──────────────────────────────────────┴─────────────┤
│ 底部：Zookeeper 提示輸入列（text-to-CAD，浮動命令列風格）      │
└─────────────────────────────────────────────────────────────┘
＋ Cmd/Ctrl+K 命令面板：所有操作可鍵盤觸發
```

### 對 OpenCad 的具體改法（按優先序）

1. **3D Viewport 是主角**：中央最大區域，先把 WebView 控制項真正放進 `MainWindow.axaml`（修 R1 後用 `WebView.Avalonia.Desktop`）。視角切換（等角／正視／俯視／右視）改為 viewport 角落的懸浮按鈕組或 gizmo，不佔頂部工具列。
2. **AI 對話改成底部提示列＋可展開歷史**：仿 Zookeeper——常態只顯示一行輸入框浮在 viewport 底部，送出後訊息以卡片浮出或展開側欄。CAD 使用者 90% 注意力在模型上，固定 320px 對話欄是錯的空間分配。
3. **修改計畫確認卡片**（架構文件 §11 的核心互動）：LLM 回覆的建模計畫渲染為結構化卡片——步驟清單＋`[套用][修改計畫][取消]` 按鈕，不是純文字。需要 `ChatMessage` 增加訊息型別（text / plan / diff / error）。
4. **特徵樹 ↔ 3D 雙向連動**：點特徵樹節點 → 3D 高亮該特徵；點 3D 模型 → 特徵樹選中對應節點（`ViewerBridge` 的 `selection` 訊息已定義）。同時修掉 `TreeDataTemplate` 缺 `ItemsSource="{Binding Children}"` 的問題。
5. **選取特徵後顯示參數面板**：左欄下半或右側顯示可編輯參數表格——文件要求「尺寸可由表格直接人工修改」，且表格編輯與 LLM 走同一個 `update_feature` 命令系統。
6. **頂部工具列改建模動作導向**：草圖／拉伸／挖孔／圓角／陣列等動作按鈕（Phase 0 可先 disabled），新增／開啟／儲存專案收進「檔案」選單。現在的工具列全是檔案操作＋匯出——這是文件編輯器的思維，不是 CAD 的。
7. **三欄加 `GridSplitter`、側欄可收合**（Zoo 的左右欄都可完全收起，讓 viewport 全螢幕）。
8. **色彩集中成主題資源**：Catppuccin 色票整理進 `App.axaml` 資源字典；`ChatMessage.BackgroundColor` 這種 ViewModel 藏色碼的做法移除（改用 `IsUser` 綁定樣式選擇器）。
9. **長期**：Ctrl+K 命令面板——Zoo 所有建模操作都可從命令面板觸發，這與「LLM 與人工用同一命令系統」的架構天然契合。

### 建議的 OpenCad 版面（融合架構文件 §11 與 Zoo）

```
┌─────────────────────────────────────────────────────────────┐
│ 檔案▾  草圖 拉伸 挖孔 圓角 陣列 薄殼 │ 重建 ✓驗證 │ 匯出▾      │
├────────┬────────────────────────────────────────────────────┤
│ 特徵樹  │                                    ┌────┐          │
│ Body   │         3D Viewport                │gizmo│          │
│ ├Sketch│                                    └────┘          │
│ ├Pad   │                                                    │
│ ├Holes │    ┌──────────────────────────────────────┐        │
│ └Fillet│    │ 💬 描述設計需求…（Enter 送出）  [歷史⌃] │        │
│────────│    └──────────────────────────────────────┘        │
│ 參數面板│                                                    │
│ (選取後)│                                                    │
├────────┴────────────────────────────────────────────────────┤
│ 狀態列：驗證結果摘要 │ 尺寸 60×60×5 │ 體積 │ 孔數 │ Worker ●  │
└─────────────────────────────────────────────────────────────┘
```

## 八、第二輪修復優先順序

1. **R1（建置壞了）**——一行修復，否則什麼都動不了。
2. **R2＋R3＋R6（adapter 匯入鏈）**——三個都是小修，修完 rebuild 端點才真的能動。
3. **R4（孔消失）＋R5（fillet 簽名）**——需要設計決策（current-solid 鏈式重建＋邊選取參數），建議一起做。
4. **R7＋R8（驗證器）**——R4 修好後立刻補，否則沒有安全網。
5. **R10（golden-model 測試）**——用一個測試鎖住以上所有修復不再回歸。
6. **UI 重設計**——按第七節優先序，先接 WebView（配合 R1），再做底部提示列與計畫卡片。

---
---

# 第三輪覆審（修復驗證＋啟動除錯）

> 覆審範圍：16:33–16:58 修改批次。結論皆經實際執行驗證，含實際啟動桌面應用程式。

## 九、第二輪問題修復驗證

| # | 問題 | 狀態 | 驗證方式 |
|---|------|------|---------|
| R1 | 建置壞掉（DesktopX） | ✅ 已修復 | `WebView.Avalonia.Desktop` 套件已加入，`dotnet build` 0 錯誤 |
| R2 | Adapter 相對匯入 | ✅ 已修復 | 改為 `from ..feature_graph`，匯入正常 |
| R3 | `shell` 批次匯入失敗 | ✅ 已修復 | 匯入清單移除 `shell`（薄殼改用 `offset(amount=-t)`），且匯入失敗時保留原始錯誤訊息 `_BUILD123D_IMPORT_ERROR` |
| R4 | 孔全部消失 | ✅ 已修復 | 重寫為 **current_solid 鏈式重建**；實測 NEMA17 體積 20363 mm³（落在預期 20000–21000），中心孔＋4 固定孔全部存在 |
| R5 | fillet/chamfer 缺 edge_list | ✅ 已修復 | 新增 `_select_edges` 邊選擇器（all／all_vertical／all_horizontal／top／bottom），範例補上 `"edges"` 參數 |
| R6 | `add` 未匯入 | ✅ 已修復 | `add` 加入頂部匯入清單 |
| R7 | 不檢查 expected_hole_count | ⚠️ 修了但演算法錯（見 F3） | 檢查分支加了，但孔數偵測邏輯錯誤 |
| R8 | 壁厚檢查永遠失敗 | ✅ 已修復 | 依建議降級為 warning「壁厚檢查尚未實作」 |
| R9 | 重複舊目錄樹 | ✅ 已修復 | 頂層 adapters／validators／exporters 已刪除 |
| R10 | 測試盲區 | ✅ 已修復 | 新增 `test_golden_model.py`（13 個測試）：adapter 匯入、三個範例端到端建模、體積範圍斷言 |
| 12 | Three.js CDN 依賴 | ✅ 已修復 | Three.js／OrbitControls／GLTFLoader 已 vendor 到 `assets/three/`，csproj `CopyToOutputDirectory` 確認會複製到輸出目錄 |
| 13 | WebView2 專屬回呼 | ✅ 已修復（改架構） | 改為訊息佇列＋`opencadDrainMessages()` 輪詢——C# 端用 `ExecuteScriptAsync` 拉取，跨平台通用；`chrome.webview` 降為 opportunistic 推送 |
| 11 | 3D 視窗未實作 | ✅ 已修復 | `MainWindow.axaml` 已放入 `<WebView x:Name="PART_Viewer">`，載入本地 viewer.html |

## 十、第三輪新發現與修復（啟動除錯）

使用者回報 Visual Studio 啟動 exe 出現「應用程式組態不正確」。實際除錯後發現三個連鎖問題，**已全部修復並驗證應用程式可穩定啟動**：

**F1（🔴，已修復）：`app.manifest` XML 結構錯誤 → SxS 啟動失敗**

- 背景：WebView 原生控制項啟動時要求 manifest（記錄檔 16:40 顯示原始錯誤「Unable to create child window for native control host. Application manifest with supported OS list might be required.」），因此手寫了 `app.manifest`——但寫錯了。
- 錯誤一：`<supportedOS>` 巢狀包住 `<supportedOS Id=.../>`（多一層無效包裝）。
- 錯誤二：`<dpiAware>` 放在 SMI/**2016** 命名空間——它屬於 SMI/**2005**；SxS 對 windowsSettings 做嚴格命名空間驗證，錯放元素導致整個啟用內容生成失敗。
- 修復：拆掉巢狀包裝＋更正 dpiAware 命名空間。實測 SxS 錯誤消失。

**F2（🔴，已修復）：`System.Timers.Timer` 在背景執行緒觸碰 UI → 程序崩潰**

- `MainWindow.OnMessagePoll` 由 `System.Timers.Timer.Elapsed`（執行緒池執行緒）觸發，第 59 行 `FindControl`（UI 存取）**位於 try 區塊之外** → `InvalidOperationException: Call from invalid thread` 成為未處理例外，exit code 0xE0434352。
- 修復：改用 Avalonia `DispatcherTimer`（UI 執行緒觸發），WebView 參照改為 `OnLoaded` 時快取的欄位，並移除因此不再需要的內層 `Dispatcher.InvokeAsync`。
- 驗證：應用程式啟動後穩定運行 10 秒以上（PID 存活確認），視窗正常顯示。

**F3（🟠，已修復）：孔數偵測演算法錯誤——正確模型也驗證失敗**

- `_check_hole_count` 用 `face.geom_type == "CIRCLE"` 判斷——build123d 中 CIRCLE 是**邊**的幾何型別，孔壁的面是 `GeomType.CYLINDER`，因此孔數永遠是 0。實測正確的 NEMA17 模型驗證失敗：「孔數不符：預期 5，實際 0」。
- 修復採實測驗證的判別式：**完整孔壁圓柱面 ≤3 條邊**（上下兩圓＋縫合線），fillet 的部分圓柱面有 4 條邊（2 弧＋2 直線）。實測 NEMA17 面分佈 `{3邊: 5個, 4邊: 4個}`，偵測孔數 = 5 ✓。
- 修復後完整驗證通過：`hole_count: 5`、`is_valid: True`、`errors: []`。

## 十一、第三輪結束狀態

- `dotnet build OpenCad.slnx`：**0 警告 0 錯誤**
- `pytest tests/cad-worker/`：**43/43 通過**（含 13 個新 golden-model 測試）
- `OpenCad.Desktop.exe`：**可啟動並穩定運行**（Windows 實測）
- NEMA17 端到端：Feature Graph → 鏈式重建 → 幾何正確（體積 20363 mm³、5 孔偵測到）→ 驗證通過

尚未完成（列入 Phase 1 待辦）：
- macOS／Linux 上的 WebView 與訊息輪詢實測（目前僅 Windows 驗證過）
- UI 版面仍是三固定欄——第七節的 Zoo 式重設計尚未動工（GridSplitter、底部提示列、計畫卡片、參數面板）
- `_check_expected` 的 bounding box 檢查只比 X 軸
- 原始碼尚未 commit——目前 repo 只有文件，src/ 與 cad-worker/ 全部 untracked
