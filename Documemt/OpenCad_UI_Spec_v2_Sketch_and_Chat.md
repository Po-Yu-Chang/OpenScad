# OpenCad UI 規格 v2：對話輸入修復＋草圖設計工具（交付實作用）

> 日期：2026-07-10
> 目的:自足的實作規格,交給任何工程師或 AI 模型即可獨立完成。
> 基準 commit：`3861bbd`(main,https://github.com/Po-Yu-Chang/OpenScad)
> 前置文件:`OpenCad_Phase1_Remaining_Spec.md`(其中的地雷清單依然全部適用)

---

## 0. 問題與根因(先讀懂,不要對症下錯藥)

實際執行截圖顯示兩個問題:

### 問題一:對話輸入框看不到(使用者無法輸入任何文字)

**根本原因是 airspace,不是 XAML 寫錯。** `MainWindow.axaml` 中確實有懸浮提示輸入列、視角按鈕組、忙碌指示器,它們作為 WebView 的 sibling 疊在 viewport 上。但 **WebView2 是原生 HWND 子視窗,永遠渲染在 Avalonia 合成層之上**——任何疊在 WebView 區域上的 Avalonia 元素都會被遮住,調 z-order、ZIndex、Panel 順序全部無效。

**因此絕對不要**嘗試用 ZIndex/Popup hack 修這個問題(透明 Popup 視窗方案在拖曳視窗時會脫節)。正確做法是把 UI 元素移出 WebView 的矩形範圍,或移進 viewer.html 內部(HTML overlay 在同一個原生層內,z-index 有效)。

### 問題二:沒有草圖平面設計工具

目前草圖(sketch_entities)只能由 LLM 或範例 JSON 產生,使用者無法看到草圖形狀、無法手動畫圖或改尺寸。需要一個 2D 草圖檢視／編輯模式。

---

## 1. 工作一:對話輸入與被遮元素的重新安置

### 1.1 提示輸入框 → 右欄(對話面板)底部

右欄改為經典聊天版面(全部是純 Avalonia 區域,不受 airspace 影響):

```
┌─ 右欄 300px ────────────┐
│ 對話歷史(ScrollViewer)  │  ← Grid Row 0: *
│   …訊息氣泡…            │
├─────────────────────────┤
│ LLM:coding-cloud 已連線 │  ← Row 1: Auto(狀態,已存在)
├─────────────────────────┤
│ ┌─────────────────┐┌──┐ │  ← Row 2: Auto(新增)
│ │ 描述設計需求…    ││送出│ │
│ └─────────────────┘└──┘ │
└─────────────────────────┘
```

- 把現有懸浮輸入列的 TextBox(`PART_PromptInput`)＋送出按鈕整組搬到右欄 Row 2,刪除 viewport 上的懸浮 Border。
- Enter 送出／Shift+Enter 換行的 handler 已掛在 `PART_PromptInput` 上(`MainWindow.axaml.cs` 的 `OnPromptKeyDown`),搬移後確認 `FindControl` 仍找得到。
- 右欄收合(⚙ 鈕)時輸入框跟著收合——可接受;但收合時工具列⚙鈕 tooltip 改為「開啟對話窗格」提示使用者輸入框在裡面。

### 1.2 視角按鈕 → viewer.html 內部 HTML overlay

- 刪除 XAML 中的視角懸浮按鈕組(等角/正視/俯視/右視)。
- 在 `viewer.html` 加 HTML overlay(絕對定位右上角),四顆按鈕直接呼叫既有的 `window.setView('iso'|'front'|'top'|'right')`,不需經過 C#。
- 樣式對齊主題:背景 `rgba(30,30,46,.8)`、文字 `#cdd6f4`、hover `#45475a`、圓角 8px、字體 13px。
- `MainViewModel.SetViewCommand` 與 `ViewerBridge.BuildSetViewScript` 保留(LLM 或程式仍可切視角),只是 UI 按鈕改由 HTML 承載。

### 1.3 忙碌指示器與載入提示

- XAML 的忙碌指示器(重建中…)移到底部狀態列(純 Avalonia 區域):`IsBusy` 時顯示「⏳ 重建中…」文字。
- 「3D 視窗載入中…」TextBlock 同樣被 WebView 遮住——刪除,改用 viewer.html 既有的 `#loading` 元素(載入 GLB 時已會顯示)。

### 1.4 驗收(工作一)

1. 啟動 app:右欄底部有輸入框,可打字、Enter 送出、按鈕隨輸入啟用。
2. viewport 右上有四顆視角鈕(HTML),點擊切換相機。
3. 載入範例期間狀態列出現「重建中…」。
4. `tests/ui/smoke-test.ps1` 照常 PASS。

---

## 2. 工作二:草圖設計工具(Sketch Mode)

### 2.1 設計原則

- 草圖編輯器實作在 **viewer.html 內**(Three.js 正交相機＋HTML 工具列)。原因:渲染設施都在那裡、HTML overlay 不受 airspace 限制、與 3D 檢視共用同一畫布。
- C# 只負責:進入/離開草圖模式的指令、接收編輯結果、組 `update_feature` 命令。**幾何真相永遠在 Feature Graph**,viewer 的草圖只是暫存編輯緩衝。
- 第一版支援的實體:rectangle、circle、polygon、slot(與 schema 的 entity_type 對齊;line/arc 留待下一輪)。
- **不做**拖曳handles、不做約束求解——尺寸一律用數值輸入(這是參數化 CAD,不是自由繪圖)。

### 2.2 進入草圖模式

兩個入口:

1. **編輯既有草圖**:特徵樹選取 sketch 類型特徵 → 參數面板頂部出現「✏ 編輯草圖」按鈕 → `EditSketchCommand`。
2. **新建草圖**:工具列新增「草圖」按鈕 → 若無專案先建專案 → `create_feature` 一個空 sketch(feature_id 自動編號 `sketch_N`)→ 進入編輯。

C# → viewer:

```csharp
// ViewerBridge 新增
public static string BuildEnterSketchScript(string featureId, string entitiesJson) =>
    $"enterSketchMode('{featureId}', {entitiesJson});";
```

`entitiesJson` = 該特徵的 `sketch_entities` 陣列原文(從 GetProjectAsync 的 graph 取)。

### 2.3 viewer.html 草圖模式行為

進入 `enterSketchMode(featureId, entities)` 時:

- 相機切換:`OrthographicCamera` 俯視 XY 平面,`OrbitControls` 停用旋轉(`enableRotate=false`),保留平移與縮放。
- 隱藏 3D 模型(`currentModel.visible=false`),顯示加強網格(10mm 間距)＋X/Y 軸線(紅/綠)。
- 以 2D 線框(`THREE.LineLoop`/`LineSegments`,顏色 `#89b4fa`)渲染傳入的 entities;選取中的實體 `#f9e2af`。
- 每個實體旁顯示尺寸標籤(HTML overlay,如「67×67」「Ø22」)。
- HTML 草圖工具列(頂部置中 overlay):
  `[選取] [▭ 矩形] [○ 圓] [⬭ 長圓孔] [⬡ 多邊形] | [🗑 刪除] | [✔ 完成] [✖ 取消]`

新增實體流程(以矩形為例):

1. 點「▭ 矩形」→ 游標變十字,點擊畫布任意點作為中心。
2. 彈出 HTML 數值對話框:中心 X/Y(預填點擊座標,吸附 1mm)、寬、高 → [確定] [取消]。
3. 確定後加入本地 entities 暫存並立即渲染。
- 圓:中心＋半徑;長圓孔(slot):中心＋長＋寬＋角度;多邊形:中心＋邊數＋外接圓半徑。
- 「選取」模式:點實體高亮,顯示其數值可再編輯(同一個對話框預填現值),或按刪除移除。

完成/取消:

```js
// 完成:把暫存 entities 送回 C#(走既有訊息佇列)
window.opencadPostMessage({ type: 'sketch_committed', feature_id: featureId, entities: entitiesBuffer });
// 取消:
window.opencadPostMessage({ type: 'sketch_cancelled' });
// 兩者皆呼叫 exitSketchMode():還原透視相機、恢復模型顯示、移除草圖 overlay
```

注意:訊息佇列機制已存在(`opencadDrainMessages` 輪詢),只要把訊息 push 進同一個佇列。`ViewerBridge.ParseMessage` 需新增 `SketchCommitted`(含 entities JSON)與 `SketchCancelled` 型別。

### 2.4 C# 端提交

`MainWindow.OnMessagePoll` 收到 `sketch_committed`:

1. 轉交 `MainViewModel.CommitSketchAsync(featureId, entitiesJson)`。
2. 組命令:`update_feature`,target = featureId,**新欄位承載** `sketch_entities`(見 2.5)。
3. `ApplyCommandAsync` → 成功 → `RebuildAsync`(既有流程:重建＋驗證＋GLB＋特徵樹)。
4. 失敗 → 錯誤訊息卡片,**不離開**草圖模式讓使用者修正?第一版簡化:已離開就顯示錯誤,使用者可再進入編輯。

### 2.5 Worker 端:update_feature 支援 sketch_entities

目前 `FeatureGraph.update_feature` 只接受 `parameters` 與 `standard_parts`——**需擴充**:

- `ApplyCommandRequest` 新增欄位 `sketch_entities: list[dict] | None`。
- `update_feature(fid, parameters, standard_parts, sketch_entities)`:非 None 時**整組取代** `feature.sketch_entities`(不做合併),並照常標記下游 pending、寫 revision 快照(undo 因此自動支援草圖編輯)。
- C# `CadCommand` 加 `SketchEntities` 屬性(`List<Dictionary<string, object>>?`,JsonPropertyName "sketch_entities")。
- pytest 新增:update sketch_entities 後 GET 取回一致、undo 還原舊 entities(至少 2 個測試)。

### 2.6 驗收(工作二)

1. 載入 NEMA17 → 特徵樹選 Base Sketch → 參數面板出現「✏ 編輯草圖」→ 點擊後 viewport 切為俯視 2D,顯示 67×67 矩形線框與尺寸標籤,右上角出現確認角 ✓✗。
2. **雙擊尺寸標籤**「67×67」→ PropertyManager 式對話框(viewer 左上)→ 改為 80×80 → 確認角 ✓ → 自動重建,狀態列尺寸顯示 80×80×5,孔仍在。
3. Ctrl+Z → 尺寸回到 67×67(revision 覆蓋草圖編輯)。
4. 工具列「草圖」→ 新專案自動建立空草圖 → 畫一個圓 Ø30 → ✓ → 特徵樹出現新 sketch;(選配)自動追加一個 pad 讓它可見。
5. 特徵樹右鍵 sketch 特徵 → 「編輯草圖」同樣可進入編輯模式。
6. 抬頭工具列「縮放至適合」讓模型充滿視窗。
7. 取消編輯(✗)不改變模型;`pytest` 與 `smoke-test.ps1` 全綠。

---

## 2.7 SolidWorks 設計模式對照(實作時遵循的 UX 慣例)

草圖模式的互動細節依 SolidWorks 的成熟慣例設計,降低機械工程使用者的學習成本:

| SolidWorks 慣例 | OpenCad 對應實作 |
|---|---|
| **Confirmation Corner**:草圖模式時繪圖區**右上角**出現 ✓(完成)與 ✗(取消)大圖示,是關閉草圖的主要手段 | 草圖模式的 ✔完成/✖取消不放工具列,做成 viewer 右上角的大號確認角(HTML overlay,約 40px 圖示);視角鈕在草圖模式中隱藏,讓出該角落 |
| **Smart Dimension**:點選實體即可標尺寸;圓預設標直徑;尺寸標籤可雙擊改值 | 每個實體旁常駐尺寸標籤(矩形「67×67」、圓「Ø22」、slot「30×8」);**雙擊標籤**直接彈出數值編輯(等同選取後編輯,少一步) |
| **定義狀態**:狀態列顯示「完全定義/欠定義」,欠定義的實體可拖曳 | 我們無求解器,實體天生由參數完全定義——草圖模式狀態列顯示「N 個實體,參數化定義」;此為與 SolidWorks 的刻意差異,註明即可 |
| **PropertyManager**:啟動命令時左欄變成參數面板,分成可折疊群組框(Selections/Direction/Options) | 新增/編輯實體的數值對話框仿 PropertyManager 樣式:標題列(實體類型)＋群組框(位置:X/Y;尺寸:寬/高 或 半徑)＋✓✗ 按鈕;放在 viewer 左上角而非螢幕中央(不遮圖) |
| **FeatureManager 樹**:特徵有型別圖示;點特徵出現 context toolbar(Edit Feature/Edit Sketch) | 特徵樹節點加型別小圖示(▭ sketch/⬒ pad/○ hole/◠ fillet 等 Unicode 即可);**右鍵選單**:「編輯草圖」(sketch 類)/「編輯參數」(捲動至參數面板)/「刪除」 |
| **Heads-up View Toolbar**:繪圖區頂部懸浮工具列(視角/縮放/顯示切換) | §1.2 的視角鈕擴充成 viewer 頂部置中的抬頭工具列:等角/正視/俯視/右視/**縮放至適合**(zoom fit,新增 `window.zoomFit()`:依 bounding box 調整相機) |
| **Rollback Bar**:特徵樹上的回溯桿,可暫時回到較早狀態 | 對應我們的 revisions/undo;**拖曳式回溯桿留待 Phase 2**,本輪不做 |
| **Slot 兩型**:直槽(straight)與弧槽(arc slot) | v1 只做直槽(straight slot),對齊 schema 的 slot 參數(center/length/width/angle) |
| 進入草圖自動轉正(Normal To) | `enterSketchMode` 切正交俯視即此慣例(§2.3 已含) |

參考來源:SolidWorks 官方文件的 [FeatureManager Design Tree](https://help.solidworks.com/2024/english/solidworks/sldworks/c_featuremanager_design_tree.htm) 與 [UI 主要元件介紹](https://openwa.pressbooks.pub/testmhrtc/chapter/major-user-interface-components/)(Confirmation Corner/PropertyManager/Heads-up Toolbar)、[Smart Dimension 教學](https://solidworkstutorialsforbeginners.com/how-to-use-smart-dimension/)、[Slot 工具教學](https://solidworkstutorialsforbeginners.com/how-to-use-slot-sketching/)、[PropertyManager 群組框說明](https://mechanitec.ca/how-to-use-property-manager-in-solidworks/)。

## 3. 明確的「不要做」清單(v2 增補)

- 不要用 ZIndex/Popup/透明視窗 hack 去疊 Avalonia 元素在 WebView 上(airspace,見 §0)。
- 不要在草圖模式做拖曳調尺寸、約束求解、自由曲線——數值輸入為唯一改尺寸手段。
- 不要把草圖幾何真相存在 viewer 端——完成時一次性提交,Feature Graph 是唯一事實來源。
- 不要動 `SnakeCaseEnumConverter`、同源 viewer 伺服、DispatcherTimer、app.manifest、視窗同步建立、`RebuildAsync` 內的 GLB 匯出。
- viewer.html 一律本地資源,不得引入 CDN。
- `.ps1` 檔案必須 UTF-8 with BOM(PowerShell 5.1 中文相容)。
- API key 等機密不得出現在 repo(設定一律在 `~/.opencad/settings.json`)。

## 4. 建議實作順序

1. §1(輸入框搬家＋視角鈕進 viewer)——半天內可完成,立刻恢復可用性
2. §2.5(Worker sketch_entities 支援＋測試)——地基
3. §2.2–2.4(草圖模式主體)
4. 驗收清單逐條過,smoke-test 保持綠燈
