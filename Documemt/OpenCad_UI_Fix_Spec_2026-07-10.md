# OpenCad Desktop UI 修復規格書（交付實作用）

> 日期：2026-07-10
> 目的：本文件是**自足的實作規格**，交給任何工程師或 AI 模型即可獨立完成，不需要其他對話上下文。
> 範圍：`src/OpenCad.Desktop/`（Avalonia UI）＋少量 `cad-worker/cad_worker/server.py` 配合修改。
> 基準 commit：`2838c7b`（main 分支，https://github.com/Po-Yu-Chang/OpenScad）

---

## 0. 兩句話總結問題

1. **按鈕幾乎都不能用**：`MainViewModel` 的 Send／Export／Rebuild／OpenProject／SaveProject 全是印出「Phase 1 實作」文字的佔位，沒有接上已經存在且可運作的 `CadWorkerClient`／`CadWorkerProcess`。
2. **設計醜**：版面優先順序錯誤（AI 對話佔固定 320px 右欄、3D 視窗不是主角）、色彩硬編碼灑滿 XAML、無 GridSplitter、工具列是檔案編輯器思維而非 CAD 思維。目標是仿 Zoo Design Studio 的版面。

---

## 1. 現況盤點（已存在且可用的元件）

以下元件**已實作且經過驗證**，實作時直接使用，不要重寫：

| 元件 | 位置 | 狀態 |
|---|---|---|
| `CadWorkerProcess` | `src/OpenCad.Infrastructure/CadWorkerProcess.cs` | ✅ 可啟動 Python Worker 子程序，透過 `OPENCAD_TOKEN_FILE` 環境變數＋檔案交接取得 `SessionToken`，`StartAsync()`／`Stop()`／`IsRunning` 都可用 |
| `CadWorkerClient : ICadWorker` | `src/OpenCad.Infrastructure/CadWorkerClient.cs` | ✅ `CreateProjectAsync`／`ApplyCommandAsync`／`RebuildAsync`／`ValidateAsync`／`ExportAsync`／`GetPreviewUrl`／`CheckHealthAsync` 全部可用，建構子接 `(baseUrl, sessionToken)` |
| Python CAD Worker | `cad-worker/`（`python run_worker.py`，監聽 `127.0.0.1:8765`） | ✅ 43 個測試全過，NEMA17 端到端建模＋驗證通過 |
| WebView 3D 檢視器 | `MainWindow.axaml` 的 `<WebView x:Name="PART_Viewer">`＋`viewer.html`（本地 Three.js，離線可用） | ✅ 應用程式可啟動，`viewer.html` 提供 JS API：`loadModel(url)`／`setView('iso'|'front'|'top'|'right')`／`clearHighlight()`／`window.opencadDrainMessages()` |
| 訊息輪詢 | `MainWindow.axaml.cs` 的 `DispatcherTimer`（200ms）拉取 `opencadDrainMessages()` | ✅ 跨平台，勿改回 `System.Timers.Timer`（會 Call from invalid thread 崩潰，已踩過坑） |
| `ViewerScriptRequested` 事件 | `MainViewModel` → `MainWindow` 訂閱 → `webView.ExecuteScriptAsync` | ✅ SetView 按鈕已透過此管道運作 |
| `OllamaLlmProvider : ILlmProvider` | `src/OpenCad.Llm/OllamaLlmProvider.cs` | ✅ 已寫好（結構化輸出），但從未被 UI 呼叫 |
| 範例模型 | `examples/nema17-mount/features.json`（另兩個：needle-box-5x10、esp32cam-enclosure） | ✅ 通過 schema 驗證，可直接餵給 Worker |

### 已知的坑（前三輪 review 踩過，不要回歸）

- **不要**動 `app.manifest`——現在的內容是修好的（SxS 結構＋dpiAware 命名空間都對了）。
- **不要**用 `System.Timers.Timer` 或任何背景執行緒直接觸碰 Avalonia UI 物件；一律 `DispatcherTimer` 或 `Dispatcher.UIThread.InvokeAsync`。
- **不要**在 `viewer.html` 引入任何 CDN 資源（全本地原則）；Three.js 已 vendor 在 `src/OpenCad.Viewer/assets/three/`。
- **不要**用 `window.chrome.webview.postMessage` 作為主要通訊（WebView2 專屬）；主通道是 `opencadDrainMessages()` 輪詢。
- `RelayCommand` 在 `src/OpenCad.Desktop/MVVM/RelayCommand.cs`，已有 `RaiseCanExecuteChanged()`。

---

## 2. 工作一：把按鈕接上真實功能

### 2.1 Worker 生命週期（App 啟動時）

**檔案**：`App.axaml.cs`＋新檔 `Services/WorkerService.cs`（或直接寫在 App）

1. `OnFrameworkInitializationCompleted` 時非同步啟動 Worker：
   - 尋找 `cad-worker` 目錄：從 `AppContext.BaseDirectory` 逐層往上走，直到找到含 `cad-worker/run_worker.py` 的目錄（開發時是 repo 根目錄，離 bin 五層）；支援 `OPENCAD_WORKER_DIR` 環境變數覆寫。
   - `new CadWorkerProcess(workerDir, "python")` → `await StartAsync()` → 用 `SessionToken` 建 `CadWorkerClient`。
   - 啟動失敗（找不到目錄／Python 不存在／逾時）不得讓 App 崩潰——狀態列顯示「Worker 未連線」，相關按鈕停用。
2. App 關閉（`desktop.ShutdownRequested` 或 `Exit`）時呼叫 `CadWorkerProcess.Dispose()`（會 Kill 子程序樹）。
3. 把 `ICadWorker`（可為 null）注入 `MainViewModel` 建構子。

### 2.2 各命令的具體行為

**檔案**：`ViewModels/MainViewModel.cs`（大改）

| 命令 | 行為 | 停用條件 |
|---|---|---|
| `NewProjectCommand` | `await worker.CreateProjectAsync(name)` → 記住 `_projectId` → 清空特徵樹＋viewer（`ViewerScriptRequested("clearHighlight();")`）→ 狀態列更新 | Worker 未連線 |
| `LoadExampleCommand`（**新增**，參數＝範例名） | 讀 `examples/{name}/features.json` → `CreateProjectAsync` → 逐特徵發 `ApplyCommandAsync(action="create_feature", feature=...)` → 呼叫 `RebuildCommand` 的流程 | Worker 未連線 |
| `RebuildCommand` | `await worker.RebuildAsync(_projectId)` → 成功則 `ValidateAsync` → `ExportAsync(_projectId, "glb")` → `ViewerScriptRequested(BuildLoadScript(previewUrl))` → 更新特徵樹（`GET /api/projects/{id}` 取回 graph）→ 驗證結果寫入狀態列；失敗則把 `ErrorCode`＋`EngineMessage` 顯示為錯誤卡片 | 無專案 |
| `ExportCommand("step"/"stl")` | `await worker.ExportAsync(_projectId, fmt)` → 對話流顯示輸出檔完整路徑（可點擊或可複製） | 無模型 |
| `SetViewCommand` | 保持現狀（已可用），但按鈕移到 viewport 懸浮層（見工作二） | 無模型 |
| `SendCommand` | 見 2.4 | 輸入為空 |
| `OpenProjectCommand`／`SaveProjectCommand` | 本次**移出工具列**（收進「檔案」選單並停用，tooltip「Phase 1」），不要再佔一級位置 | 恆停用 |

實作要求：

- 所有 Worker 呼叫都是 async——`RelayCommand` 是同步的，新增 `AsyncRelayCommand`（執行中自動停用、例外捕捉後顯示為錯誤訊息卡片，**不得**讓例外逃逸成未處理例外）。
- 每個命令執行前後呼叫相關命令的 `RaiseCanExecuteChanged()`。
- 新增屬性：`IsWorkerConnected`（bool）、`HasProject`（bool）、`IsBusy`（bool，執行中顯示忙碌指示）。

### 2.3 preview.glb 的 Token 問題（**必須配合修改 server**）

`GET /api/projects/{id}/preview.glb` 目前要求 `X-Session-Token` header，但 WebView 內的 `loadModel(url)` 用 GLTFLoader fetch，**無法帶自訂 header**。

**修改** `cad-worker/cad_worker/server.py` 的 preview 端點：接受 query string token 作為替代：

```python
@app.get("/api/projects/{project_id}/preview.glb")
async def get_preview(project_id: str, token: str = "") -> Any:
    if token != SESSION_TOKEN:
        raise HTTPException(status_code=403, detail="無效的工作階段 Token")
    ...
```

C# 端 `GetPreviewUrl` 對應改為 `...preview.glb?token={_sessionToken}`，並在 URL 加上 cache-busting 參數（如 `&t={rebuild_count}`），否則 WebView 快取會讓重建後畫面不更新。

### 2.4 SendCommand：LLM 整合（優雅降級）

1. App 啟動時 `GET http://127.0.0.1:11434/api/tags`（timeout 2s）偵測 Ollama：
   - 可用 → `LlmStatus = "LLM：{model} 已連線"`；不可用 → `"LLM：未偵測到 Ollama（僅手動模式）"`。
2. Ollama 可用時：`OllamaLlmProvider.CreatePlanAsync` → 把 `DesignPlan` 渲染成**計畫卡片**（見工作二 3.4）→ 使用者按〔套用〕才逐步 `CreateCommandAsync` → `ApplyCommandAsync` → rebuild 流程。
3. Ollama 不可用時：回覆訊息引導使用者用「載入範例」按鈕，**不要**輸出「Phase 1 實作」這種字樣。
4. LLM 呼叫要有 timeout（120s）與取消；執行中對話區顯示打字中指示。

---

## 3. 工作二：版面與視覺重設計（仿 Zoo Design Studio）

### 3.1 目標版面

```
┌──────────────────────────────────────────────────────────────────┐
│ 檔案▾ │ 載入範例▾  重建  ✓驗證 │ 匯出 STEP  匯出 STL │      ⚙    │  ← 工具列(48px)
├─────────┬──╢──────────────────────────────────────────┬──╢──────┤
│ 特徵樹   │GridSplitter                        ┌──────┐ │GS│ AI   │
│ Body    │  │        3D Viewport（主角）       │等角  │ │  │ 對話  │
│ ├Sketch │  │                                 │正視  │ │  │ 歷史  │
│ ├Pad    │  │                                 │俯視  │ │  │(可收合)│
│ ├Holes  │  │                                 │右視  │ │  │      │
│ └Fillet │  │  ┌────────────────────────────┐ └──────┘ │  │      │
│─────────│  │  │ 💬 描述設計需求…      [送出]│          │  │      │
│ 參數面板 │  │  └────────────────────────────┘          │  │      │
├─────────┴──╨──────────────────────────────────────────┴──╨──────┤
│ ● Worker 已連線 │ ● LLM 未偵測 │ 60×60×5 mm │ 體積 20363 │ 孔 5  │  ← 狀態列(28px)
└──────────────────────────────────────────────────────────────────┘
```

要點：

1. **中央 viewport 是主角**；提示輸入列是**懸浮在 viewport 底部**的圓角膠囊（半透明背景 `#cc1e1e2e`，寬度約 60%、水平置中、距底 24px），不是右欄的一部分。
2. **視角按鈕**懸浮在 viewport 右上角（垂直排列的小按鈕組，同樣半透明底）。
3. **右欄=對話歷史**，預設寬 300，可用 GridSplitter 調整、可完全收合（工具列右側 ⚙ 旁放切換鈕）；收合時 viewport 吃滿。
4. **左欄**上半特徵樹、下半參數面板（選取特徵後顯示 key-value 表格；本次先唯讀即可），中間水平 GridSplitter。左欄也可收合。
5. **狀態列**：Worker 連線狀態（●綠/紅）、LLM 狀態、模型尺寸／體積／孔數（來自最近一次 ValidationReport）。
6. 欄寬用 `ColumnDefinitions="{可調}"`＋`GridSplitter`（寬 4px、`Background="{DynamicResource BorderBrush}"`）。

### 3.2 主題資源（消滅硬編碼色彩）

**檔案**：`App.axaml`

把 Catppuccin Mocha 色票定義為資源，全部 XAML 改用 `{DynamicResource}`：

```xml
<Application.Resources>
  <SolidColorBrush x:Key="BaseBrush"        Color="#1e1e2e"/>
  <SolidColorBrush x:Key="MantleBrush"      Color="#181825"/>
  <SolidColorBrush x:Key="CrustBrush"       Color="#11111b"/>
  <SolidColorBrush x:Key="SurfaceBrush"     Color="#313244"/>
  <SolidColorBrush x:Key="Surface1Brush"    Color="#45475a"/>
  <SolidColorBrush x:Key="TextBrush"        Color="#cdd6f4"/>
  <SolidColorBrush x:Key="SubtextBrush"     Color="#a6adc8"/>
  <SolidColorBrush x:Key="OverlayBrush"     Color="#6c7086"/>
  <SolidColorBrush x:Key="AccentBrush"      Color="#89b4fa"/>  <!-- blue -->
  <SolidColorBrush x:Key="SuccessBrush"     Color="#a6e3a1"/>  <!-- green -->
  <SolidColorBrush x:Key="WarningBrush"     Color="#f9e2af"/>  <!-- yellow -->
  <SolidColorBrush x:Key="ErrorBrush"       Color="#f38ba8"/>  <!-- red -->
  <SolidColorBrush x:Key="BorderBrush"      Color="#313244"/>
</Application.Resources>
```

並加 `Application.Styles` 統一按鈕外觀：工具列按鈕（透明底、hover `SurfaceBrush`、CornerRadius 6、Padding 10,6）、主要動作按鈕（`AccentBrush` 底、深色字）。

### 3.3 ChatMessage 去色碼化

**檔案**：`ViewModels/Models.cs`＋`MainWindow.axaml`

- 刪除 `ChatMessage.BackgroundColor` 屬性（ViewModel 不該藏 UI 色碼）。
- 增加 `MessageKind Kind`（enum：`User`／`Assistant`／`Error`／`Plan`）。
- XAML 用 DataTemplate＋Classes 樣式選擇：User 靠右、`Surface1Brush` 底；Assistant 靠左、`SurfaceBrush` 底；Error 用 `ErrorBrush` 左邊框 3px；訊息最大寬度 85%、CornerRadius 10。

### 3.4 計畫卡片（Plan Card）

`ChatMessage.Kind == Plan` 時的 DataTemplate：

- 標題「建模計畫」＋摘要
- 步驟清單（`ItemsControl`，每行「1. 建立底板草圖 60×60（sketch）」）
- `missing_info` 非空時以 `WarningBrush` 顯示「缺少資訊：…」
- 底部按鈕列：〔套用〕（`AccentBrush`，觸發 `ApplyPlanCommand`）〔取消〕
- `ChatMessage` 需新增 `DesignPlan? Plan` 屬性與 `ApplyPlanCommand` 綁定路徑

### 3.5 互動細節

- 提示輸入框：`KeyBindings`——Enter 送出、Shift+Enter 換行。
- 對話新訊息自動捲到底（`ScrollViewer.ScrollToEnd()`，訂閱 `Messages.CollectionChanged`，記得在 UI 執行緒）。
- 特徵樹選取 → `SelectedItem` 綁定 → 參數面板顯示該特徵 `parameters`；同時 `ViewerScriptRequested` 發送高亮（viewer.html 需新增 `highlightByName(name)`，用 mesh 名稱比對，找不到就靜默）。
- `IsBusy` 時：viewport 右下顯示轉圈＋「重建中…」，工具列動作按鈕停用。
- 視窗標題／尺寸只在 XAML 設定，刪除 `App.axaml.cs` 中重複的 `Title`/`Width`/`Height` 指定。

---

## 4. 驗收條件（實作完成的定義）

依序驗證，全部通過才算完成：

1. `dotnet build OpenCad.slnx` → 0 錯誤 0 警告。
2. `python -m pytest tests/cad-worker/` → 43+ 全過（含為 preview token 修改新增的測試）。
3. 啟動 `OpenCad.Desktop.exe`（Python 環境有 build123d）：
   - 狀態列 5 秒內顯示「● Worker 已連線」。
   - 點「載入範例 → NEMA17 馬達座」：特徵樹出現 5 個特徵節點，3D 視窗顯示帶孔帶圓角的方板（**不是**實心板），狀態列顯示體積約 20363 mm³、孔數 5、驗證 ✓。
   - 點視角懸浮鈕「俯視」：相機切換，可見 5 個孔的配置。
   - 點「匯出 STEP」：對話區顯示輸出路徑，該路徑檔案實際存在且非空。
   - 點特徵樹的 `mount_holes`：參數面板顯示 positions 等參數。
   - 拖曳左右 GridSplitter 可調整欄寬；收合右欄後 viewport 變寬。
4. 停掉 Python／改壞 worker 路徑再啟動 App：不崩潰，狀態列顯示「● Worker 未連線」，重建／匯出／載入範例按鈕呈停用態。
5. 無 Ollama 時：送出文字得到引導訊息（不出現「Phase 1」字樣）；有 Ollama 時：得到計畫卡片，〔套用〕後模型出現在視窗。
6. 全程斷網可完成 1–4（全本地原則）。
7. `grep -rn "#1e1e2e\|#313244\|#cdd6f4" src/OpenCad.Desktop/*.axaml src/OpenCad.Desktop/ViewModels/` 只在 `App.axaml` 資源字典命中（色碼集中化完成）。

## 5. 明確的「不要做」清單

- 不要引入 ReactiveUI／CommunityToolkit.Mvvm 等新 MVVM 框架（現有手寫 MVVM 已夠用，避免大改）。
- 不要動 `cad-worker/` 的建模邏輯（adapter/validator）——只允許本文 2.3 的 preview token 修改。
- 不要動 `app.manifest`、`Program.cs` 的 AppBuilder 設定。
- 不要把任何資源改回 CDN 載入。
- 不要在非 UI 執行緒觸碰 Avalonia 物件。
- 不要刪除或改寫既有測試；新行為要加測試（至少：preview token query param 的 server 測試）。
- UI 文案一律繁體中文。
