# OpenCad Codebase 全面盤點審查（2026-07-12）

> 目的：回答「草圖約束、組件 BOM……很多都沒有」的疑問——逐項對照 Master Plan 宣稱與 codebase 實際狀態。
> 方法：4 條並行盤點（草圖約束／Phase 2-4 功能／特徵覆蓋與引擎接線／測試與驗收），每項附檔案:行號證據。
> 結論已回寫 `OpenCad_Master_Plan.md` §1.6 與 §15 狀態欄。
> **後記（同日）**：§5 序 1 的 WP1-7-UI 已於 2026-07-12 完成——vertical-slice-a.ps1 重寫後雙引擎實跑 11/11、smoke-test（build123d）PASS、UX 修補入庫；freecad smoke 被 shell 缺口擋下（歸 WP1-0R2）。詳見 Master Plan §15 序 10。

---

## 0. 一句話總結論

**單零件 Phase 1 的骨架（交易、undo、picking、語意參照、文件模型 v2、UI 接線）是真的；但「草圖約束」有一條紅線違規（rebuild 不求解），FreeCAD 引擎只有 9/22 特徵，Phase 1 Gate（WP1-7）只過了引擎層沒過 UI 層；組立／BOM／工程圖／組態／方程式等屬 Phase 2-4，本來就尚未發包，codebase 裡沒有是「符合計畫」而不是「掉球」。**

---

## 1. 草圖約束（使用者疑問 1）——有 UI、有端點，但求解是 heuristic 且 rebuild 不求解

### 實際架構
- 求解器是**自寫的純 Python 投影式 heuristic**（`cad-worker/cad_worker/sketch_solver.py`）：for-loop 逐一套用約束（`solve()` :233-234），無聯立求解、無迭代收斂、無殘差檢查。不是 FreeCAD Sketcher。
- 只在**互動預覽端點**生效：`POST .../sketch/{feature_id}/solve`（`server.py:1253-1288`，不進歷史）。
- **rebuild 時約束完全被忽略**：兩個 adapter 的 `_build_sketch` 都只讀 `sketch_entities` 座標，從不讀 `feature.constraints`（build123d_adapter.py grep constraint = 0；freecad_adapter.py 0 個 `addConstraint`）。約束在 rebuild pipeline 是**死 metadata**。
- ⚠ **這違反 Master Plan §0.2 鐵則 3**：「約束只存 metadata、座標由程式算」被明訂永久禁止——目前的實作正是這個形態（座標由互動 solve 寫回後凍結）。

### 約束覆蓋（計畫要求 13 種）
| 狀態 | 約束 |
|---|---|
| ✅ 有幾何求解（11 種） | coincident、horizontal、vertical、distance、radius、diameter、equal、parallel、perpendicular、concentric、midpoint |
| ❌ 只登錄 DOF、無幾何實作（3 種） | **angle、symmetric、tangent**（`_apply_constraint` 無對應分支）；測試只驗「型別存在」（`test_sketch_solver.py:234-248`）＝假綠 |

### 診斷品質
- DOF＝固定成本表相減（`sketch_solver.py:44-59, 187-211`），非 Jacobian rank——重複耦合的約束會算錯。
- 過約束「衝突集」＝把最後 N 個約束標為 conflict（:206-209），不是真實冗餘分析。

### UI 端（這部分是完整的）
- viewer.html：9 顆約束鈕、DOF 狀態列三色、衝突可點刪、拖曳 50ms throttle 求解（`SOLVE_THROTTLE_MS=50` :1274）皆有。尺寸驅動用 `window.prompt` 對話框（非 in-canvas）。
- C# 接線（ViewerBridge/MainViewModel/CadWorkerClient）完整，是薄轉發。
- 缺：多實體選取（2-target 約束用「當前＋前一個」硬湊，viewer.html:1317-1321）；工具列沒有 angle/tangent/symmetric/midpoint 鈕。

### 真 FreeCAD Sketcher 在哪裡
- 只在獨立 spike `cad-worker-freecad/`（`addConstraint`＋`sketch.solve()`＋`sketch.DoF`），僅 5 種約束，**與 UI／主端點零接線**。
- 它的 18 個真 solver 測試（拖曳、setDatum、100/500 entity 效能、真衝突）**在本 repo 任何自動化路徑都不會執行**：CI 用 Python 3.12（import FreeCAD 必失敗）、pytest.ini testpaths 不含該目錄、`run_freecad_tests.bat` 只跑 `test_freecad_adapter.py`。

---

## 2. 組件／組立／BOM（使用者疑問 2）——完全沒有，但這符合計畫（Phase 3）

| 功能 | 判定 | 證據 |
|---|---|---|
| Assembly／components／mates／mate solver／干涉／爆炸 | **完全沒有** | 僅 `project.schema.json:26-31` 的 document_type enum 有 "assembly" 字串；全 repo .py/.cs 0 命中 |
| BOM／cut list／CSV 輸出 | **完全沒有** | 匯出器只有 step/stl/glb/png（`exporters/__init__.py:361-397`） |
| 工程圖（drawing/TechDraw） | **完全沒有** | document_type enum 連 "drawing" 都沒有 |
| Configurations（組態） | **只有 schema＋序列化 round-trip** | `feature_graph.py:198/332/355`；rebuild 完全不套 overrides |
| Equations／global_variables | **只有 schema＋儲存，無求值器** | grep eval/ast = 0；expression 字串從未被求值 |
| Multi-body | **只有 metadata** | bodies[] 可存取，但 `build123d_adapter.py` grep body = 0——建構不分 body、無 split/combine/scope |
| Surface（knit/trim/thicken/delete_face） | **完全沒有＋顯式 unsupported** | `server.py:830` unsupported 清單 |
| 鈑金／焊件 | **完全沒有** | 全 code 0 命中 |

這些都在 Master Plan §6-8（Phase 2-4，Gate 後才發包）。**「沒有」是預期狀態**；真正的問題在 Phase 1 尚未真正過 Gate（見 §4）。

---

## 3. 特徵覆蓋與引擎 parity——FreeCAD adapter 落後 13 型，文件宣稱不實

### 22 型特徵五處比對
- schema（`feature.schema.json:105-131`）＝build123d adapter（22/22 個 `_build_*`）＝C# `Enums.cs` ＝ C# LLM 靜態清單：**一致**。
- **FreeCAD adapter 只有 9/22**（sketch/pad/pocket/hole/fillet/chamfer/revolve/linear_pattern/circular_pattern）；缺 sweep、loft、mirror、shell、boolean×3、draft、rib、thin、variable_fillet、countersink、cosmetic_thread——缺型別會丟 `ValueError`（`freecad_adapter.py:409-411`）。
- ⚠ `FREECAD_ADAPTER_LIMITATIONS.md:60-68` 能力矩陣宣稱 "largely feature-complete"、甚至標 Loft/Sweep=✅——**與實情不符，須改寫**。

### build123d 端的品質瑕疵
- `_build_draft`（:1102-1124）是 **no-op**（回傳原 part，TODO WP2）；`_build_variable_fillet`（:1191）退化為單一半徑；cosmetic_thread 不改幾何（設計如此）。

### 契約同步破口（新發現，Master Plan 未記）
1. C# `CommandValidator.cs:66-174` 對 WP1-6 六型**無任何必填驗證**——與 Python 端不對稱。
2. C# LLM prompt（`LlmProviderBase.cs:124`）的 feature_type enum **混入 datum_plane/axis/point**（屬 reference_geometry，非 feature）。
3. `feature.schema.json:224-259` 的 `reference_geometry` 定義**孤立**（頂層無 $ref），實際存檔格式與 feature.schema 不同步。
4. `reorder_feature`：server／validator／domain 齊全，**UI 完全未接線**（無選單、無拖曳）。

### Datum（WP1-3 標✅，實為部分）
- `reference_geometry_builder.py` 七種 method 有實作，但 `_resolve_face:181-222` 靠硬編預設方位、`_resolve_vertex:225-234` 直接回原點——**非真正從 BREP 解析**。
- FreeCAD 引擎下 datum 當草圖面**退回 XY**（`freecad_adapter.py:444-454`，佔位）。
- UI 建立對話框硬編 `face:f1.top`＋10mm（`MainViewModel.cs:2303-2306`）——demo 級。

---

## 4. 驗收可信度——Phase 1 Gate 尚未真正通過

| 宣稱 | 實際 |
|---|---|
| WP1-7 Vertical Slice A 已通過（§15 註✅） | 僅**引擎層** pytest 12/12 在 freecad 通過（2026-07-12）；**UI 層 `vertical-slice-a.ps1` 從未實跑**（reconciliation 文件 L156 自承） |
| `vertical-slice-a.ps1` 是 Gate 腳本 | 三缺陷：無 token 時 `exit 0` **no-op 綠燈**；缺 step 2（LLM plan 等價）；step 9「存/重開」是同一 live 專案連 GET 兩次（恆真） |
| WP1-0R smoke-test 雙引擎 PASS（07-11 報告） | 其後兩個 commit（4f5ccd9、3b76dfe）才修 smoke-test，自標「部分修復」——**PASS 宣稱早於腳本修復** |
| `FREECAD_TEST_RESULTS.md`：36/36、0 bug | 與 `WP1-0R_Report.md` §C（發現並修 1 個 ShapeWrapper bug）矛盾；耗時 2.93s vs 133.95s 顯非同輪 |
| 測試基線 916 Python／173 .NET | 獨立測試函式約 410／82（其餘為 parametrize/Theory 展開）；`tests/geometry`、`tests/unit`、`tests/golden-models` **三目錄皆空** |
| topology 語意參照完成 | `topology.py` 解析器「僅測試使用，尚未接進 adapter」；edge disambiguation by centroid **未實作、以 skip 迴避**（`test_topology_sweep.py:391`） |
| WP-H1 LLM 收斂已測 | `tests/prompts` 用手寫模擬 plan 斷言，**非真實 gateway 端到端** |

### 假綠三態（納入地雷 #21/#22）
1. angle/symmetric/tangent 測試只驗型別存在。
2. FreeCAD 測試在系統 Python 3.12 下 36 個全 skip（只有 cp311 python 實跑）。
3. vertical-slice-a.ps1 無 token 直接 exit 0。

### 工作區家務
- **未提交**：5 個 `src/OpenCad.Desktop/` 檔（+142/-52）——命令例外浮現（RelayCommand/AsyncRelayCommand onError）、`:disabled` 樣式、「後端未連線」橫幅＋重連鈕。是好修補，但**無對應測試、未 commit**。
- 本地領先 origin/main **13 個 commit 未 push**。
- 根目錄 `FreeCAD_Packaging_Notes.md` 與 `Documemt/FreeCAD_Packaging_Notes.md` 重複（未追蹤）。

---

## 5. 校正後的下一步順序（已回寫 Master Plan §15）

| 序 | 包 | 內容 | 為什麼在這個位置 |
|---|---|---|---|
| 1 | **WP1-7-UI**（Phase 1 Gate 收尾） | 先 commit 那 5 個 Desktop UX 修補（補測試）→ 修 `vertical-slice-a.ps1` 三缺陷（no-token 改 FAIL、補 step 2、step 9 真存檔重開）→ UIA 實跑 11 步 | Gate 是一切後續發包的前提；未提交變更正是為此準備的 |
| 2 | **WP1-2R 真求解器** | rebuild 時對含 constraints 的 sketch 重新求解（FreeCAD Sketcher 為權威；或至少 rebuild 前驗證約束殘差、不符即 fail）；補 angle/symmetric/tangent；真 DOF/衝突集；把 spike 的 18 個真 solver 測試接進可執行路徑（cp311 跑法） | 解除 §0.2 鐵則 3 紅線違規——這是 MVP P0，不能帶進 Phase 2 |
| 3 | **WP1-0R2 FreeCAD 特徵 parity** | 補 13 個缺失特徵（至少 sweep/loft/mirror/shell/boolean×3）；WP1-6 六型 golden test 參數化雙引擎；改寫 `FREECAD_ADAPTER_LIMITATIONS.md` 為誠實矩陣；然後才能討論切預設引擎 | 「FreeCAD 是權威核心」的宣稱目前只有 41% 特徵覆蓋支撐 |
| 4 | **WP-S1 契約同步小包** | C# CommandValidator 補 WP1-6 驗證；LLM prompt 移除 datum 三型；feature.schema reference_geometry 接線或移除；reorder UI；draft no-op／variable_fillet 退化標註或實作；刪根目錄重複檔；清空目錄或建 README | 全是小刀，但每個都是未來 500 錯誤或 LLM 幻覺的來源 |
| 5 | WP1-3 收尾（datum 去佔位） | `_resolve_face`/`_resolve_vertex` 接真 BREP＋display_map；FreeCAD datum 草圖面；UI 對話框真選面 | WP1-3 的 ✅ 降級為部分完成 |
| 之後 | Phase 2（WP2-1 Equations 起） | 依原計畫 | Gate 過後才發 |

---

## 6. 給使用者的直接回答

- **「草圖約束沒有？」**——有一半：UI 與互動求解存在且能用，但求解器是 heuristic、3 種約束是空殼、**rebuild 不求解（紅線）**。需要 WP1-2R。
- **「組件 BOM 沒有？」**——對，完全沒有，但這是 Phase 3 的範圍，計畫本來就排在單零件 MVP（Phase 1）與可重用設計（Phase 2）之後。真正的行動點不是提前做組立，而是**先把 Phase 1 Gate 真正過完**。
