# OpenCad 功能路線圖：SolidWorks 課綱對照缺口分析（交付實作用）

> 日期：2026-07-10
> 目的:以 SolidWorks 標準教學課綱為基準,系統性盤點 OpenCad 缺少的 CAD 能力,避免零散補洞。P0 章節為可直接實作的完整規格;P1–P3 為分級路線,屆時再展開成細規格。
> 基準 commit：`1c583d6`
> 課綱來源:SolidWorks 官方[入門指南](https://my.solidworks.com/solidworks/guide/SOLIDWORKS_Introduction_EN.pdf)與[學生教材](https://www.solidworks.com/sw/docs/Student_WB_2011_ENG.pdf)、官方[特徵總覽](https://help.solidworks.com/2012/english/solidworks/sldworks/Features_Overview.htm)、[Hole Wizard 文件](https://help.solidworks.com/2023/English/solidworks/sldworks/c_Hole_Wizard_Overview.htm)、[組合件教學](https://solidworkstutorialsforbeginners.com/solidworks-assembly-tutorials/)(標準/進階/機械配合)、[Assembly 入門](https://tutorial45.com/solidworks-assembly-tutorial/)。

---

## 0. 課綱對照總表

SolidWorks 初學課綱的標準模組 vs OpenCad 現況:

| SolidWorks 課綱模組 | OpenCad 現況 | 缺口等級 |
|---|---|---|
| 草圖**基準面**(Front/Top/Right、面上開草圖、偏移面) | ❌ 只有隱含 XY | **P0(阻斷)** |
| 草圖工具(line/arc/spline/trim/offset/mirror/sketch pattern) | 🔶 只有 rect/circle/polygon/slot | P1 |
| 基礎特徵(Extrude/Cut/Revolve/Fillet/Chamfer/Shell/Pattern) | ✅ 已有 | — |
| 進階特徵(**Sweep/Loft**/Rib/Draft/Dome) | ❌ | P1 |
| **Hole Wizard**(標準孔:間隙/沉頭/錐坑/螺紋) | 🔶 間隙孔查表已有;沉頭有資料未接;錐坑/螺紋無 | P1 |
| 量測/質量屬性/剖面視圖/材質外觀 | 🔶 體積/表面積有;質量/剖面/材質無 | P1 |
| **組合件**(插入零件、標準/進階/機械配合、干涉、爆炸圖、BOM) | ❌ | P2(=架構文件 Phase 4) |
| **Connector/標準件庫**(Toolbox:螺絲/螺帽/軸承) | 🔶 ISO 273/NEMA 資料表是雛形 | P2 |
| **動畫/運動模擬**(Motion Study、馬達、爆炸動畫) | ❌ | P3 |
| 工程圖(視圖/尺寸標註/DXF-PDF) | ❌ | P3(=架構文件 Phase 5) |
| 組態/設計表(configurations/design tables) | ❌ | P3 |
| 鈑金/焊件/曲面 | ❌(架構文件明列第一版不做) | P4+ |

---

## 1. P0:草圖基準面(立即實作,完整規格)

### 1.1 問題

真實 CAD 開草圖的第一步是**選平面**——SolidWorks 的 FeatureManager 樹頂端永遠有 Front Plane/Top Plane/Right Plane 與 Origin,新草圖必須指定放在哪個基準面(或模型的平面)上。OpenCad 目前草圖隱含畫在 XY,無法做出任何非單向拉伸的零件(例如側面開孔的盒子、L 型支架)。

### 1.2 資料模型(schema＋Feature Graph)

`schemas/feature.schema.json` 的 feature 定義新增 `plane` 欄位(sketch 類型使用):

```json
"plane": {
  "type": "object",
  "properties": {
    "base": { "type": "string", "enum": ["XY", "XZ", "YZ"],
              "description": "XY=上(Top)、XZ=前(Front)、YZ=右(Right)" },
    "offset": { "$ref": "#/definitions/parameter_value",
                "description": "沿法向偏移量(mm),預設 0" }
  },
  "required": ["base"]
}
```

- Python `Feature` dataclass＋C# `Feature` 類別同步加 `plane` 欄位(預設 `{"base": "XY", "offset": 0}`,舊專案不帶 plane 視為 XY——向下相容)。
- 命名對照(繁中 UI):XY=上基準面、XZ=前基準面、YZ=右基準面(與 SolidWorks Top/Front/Right 一致)。

### 1.3 Adapter(build123d)

`_build_sketch` 依 plane 建立:

```python
plane_map = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}
base = plane_map[feature.plane.get("base", "XY")]
offset = _raw_mm(feature.plane.get("offset", 0))
work_plane = base.offset(offset) if offset else base
with BuildSketch(work_plane) as sketch:
    ...
```

注意:`_build_pad` 的 extrude 方向自然沿草圖法向,build123d 已處理;golden test 需涵蓋「XZ 面草圖+拉伸」的 bbox 驗證(例如 XZ 上 60×5 矩形拉 40 → bbox 60×40×5)。

### 1.4 UI:特徵樹基準面節點＋新草圖平面選擇

1. **特徵樹頂端常駐三個基準面節點**(SolidWorks 慣例):「上基準面 (XY)」「前基準面 (XZ)」「右基準面 (YZ)」+「原點」。非特徵,不可刪除;圖示用 ▱。
2. **新草圖流程改為**:點「✏ 草圖」→
   - 若特徵樹目前選中某基準面節點 → 直接在該面開草圖(SolidWorks 的「先選面再點草圖」慣例);
   - 否則彈出簡單選擇(對話流卡片或 Flyout):上/前/右 三鈕＋偏移數值(預設 0)。
3. **viewer 草圖模式**:`enterSketchMode(featureId, entities, plane)` 增加 plane 參數,相機 normal-to 該平面(XY→俯視、XZ→前視、YZ→右視),網格畫在該平面上。
4. 特徵樹的 sketch 節點顯示平面資訊:「Base Sketch (sketch@XY)」。
5. LLM prompt 更新:`CreatePlanAsync`/`CreateUpdateCommandAsync` 的規則加一條「sketch 特徵必須指定 plane.base(XY/XZ/YZ),依零件方位選擇」。

### 1.5 選取模型平面開草圖(本輪先不做)

「點模型的某個面開草圖」需要 persistent face reference(架構文件 Phase 2 的 Topological Naming 課題),本輪只做三基準面＋偏移;規格中明確保留介面(plane.base 未來可為 `face:{feature_id}:{selector}`)。

### 1.6 驗收

1. 特徵樹頂端顯示三基準面+原點;選「前基準面」→ 點「草圖」→ viewer 切前視圖、網格在 XZ 面。
2. 在 XZ 面畫 60×40 矩形 → 完成 → 自動接 pad(深度 5)→ 模型是直立的板(bbox 60×5×40)。
3. 載入 NEMA17(無 plane 欄位的舊資料)→ 一切照舊(向下相容)。
4. pytest 新增:XZ/YZ 草圖 build 的 bbox golden 測試≥2 個;`smoke-test.ps1` 照常 PASS。

---

## 2. P1:單零件能力補全(下一輪展開細規格)

依 SolidWorks 課綱優先序:

1. **草圖工具**:line/arc 閉合輪廓(P1 最優先,搭配 §1 才能畫 L 形/異形板)、sketch mirror、offset entities、trim(trim 需要曲線求交,可最後)。
2. **Sweep(掃掠)＋Loft(疊層)**:build123d 有 `sweep()`/`loft()`;Feature Graph 需要「路徑草圖+輪廓草圖」雙輸入(references 已支援多參照)。
3. **Hole Wizard 補全**:counterbore(資料已在 standard_parts.schema.json,adapter 未接)、countersink(ISO 10642 資料表新增)、螺紋孔先做「攻牙底孔直徑」查表(不建螺紋幾何)。UI 做成 PropertyManager 式孔類型選擇。
4. **Rib/Draft**:build123d 對 draft 支援有限——先做 Rib(輪廓草圖拉伸+fuse),Draft 留待評估。
5. **質量屬性**:材質欄位(專案層級,密度查表:PLA/ABS/鋁/鋼)→ 質量=體積×密度,顯示在狀態列與驗證報告。
6. **剖面視圖**:viewer 端 Three.js clipping plane(`renderer.localClippingEnabled`),抬頭工具列加「剖面」切換+拖桿——純顯示,不動幾何。
7. **量測工具**:viewer 點兩點顯示距離(raycast 已有基礎)。

## 3. P2:組合件與標準件庫(對應架構文件 Phase 4)

- **文件模型**:assembly 是新的文件型別,含 part instances(引用 part 專案+變換矩陣)。Feature Graph 之上加 Assembly Graph。
- **配合(Mates)**:依 SolidWorks 分級實作——標準配合先做 coincident/concentric/distance/parallel/angle(架構文件 Phase 4 清單);進階(width/path/limit)與機械配合(gear/screw/cam/hinge)後續。求解:第一版可用順序求解(fix 第一零件,逐配合定位),不必完整 DOF 求解器。
- **干涉檢查**:兩兩 intersect 體積>0 即報(validator 已有 boolean 基礎)。
- **爆炸圖**:每 instance 一個爆炸位移向量,viewer 動畫插值。
- **Connector/Toolbox**:標準件庫擴充——螺絲(ISO 4762/4014)、螺帽、墊圈、軸承(6xxx 系列)生成參數化幾何;插入時自動與孔同心配合(SolidWorks Smart Fasteners 的簡化版)。資料表沿用「LLM 選型、引擎查表」原則。

## 4. P3:動畫與工程圖

- **Motion Study(簡化)**:時間軸 UI(viewer 端)、關鍵影格=各 instance 變換、旋轉馬達=繞配合軸的角速度、爆炸/收合動畫自動生成。輸出 GIF/MP4(viewer 逐幀截圖)。真實物理模擬(重力/接觸)不做——那是 CAE 範疇,架構文件明訂串接外部工具。
- **工程圖**(架構文件 Phase 5):標準三視圖+等角、自動尺寸建議、PDF/DXF。build123d 有 `section()`+DXF 匯出可作地基。
- **組態/設計表**:同一 Feature Graph 多組參數集(parameters.json 陣列化),UI 下拉切換——參數化架構天然支援,成本低價值高,可提前。

## 5. 實作順序建議

1. **P0 草圖基準面**(§1,本輪)——沒有它,草圖功能是殘缺的
2. P1-1 line/arc 輪廓+P1-3 Hole Wizard(常用度最高)
3. P1-2 Sweep/Loft+P1-5 質量屬性+P1-6 剖面
4. P3 組態/設計表(低成本高價值,可插隊)
5. P2 組合件(大工程,獨立立項,先寫細規格)
6. P3 動畫/工程圖

## 6. 地雷清單(沿用)

`OpenCad_Phase1_Remaining_Spec.md` 與 `OpenCad_UI_Spec_v2` 的全部地雷仍適用:SnakeCaseEnumConverter/同源 viewer/DispatcherTimer/airspace/app.manifest/視窗同步建立/GLB 匯出/UTF-8 BOM/機密不進 repo。新增:

- plane 欄位必須向下相容(缺省=XY),否則三個範例與所有既有專案會壞。
- 基準面節點不是 Feature,不得進 Feature Graph(它們是 UI 常駐項)。
