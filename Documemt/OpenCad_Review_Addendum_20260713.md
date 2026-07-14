# OpenCad Review 補充報告（2026-07-13）

> 目的：複核 `OpenCad_Codebase_Review_20260712.md` 的宣稱是否屬實，並實跑測試基線。
> 方法：4 條並行複核（求解器紅線／FreeCAD 覆蓋率／契約同步／Gate 腳本品質）＋實跑 pytest 與 dotnet build/test。
> 結論已回寫 `OpenCad_Master_Plan.md`（2026-07-13 重整版）。

---

## 0. 一句話總結論

**07-12 盤點報告本身高度可信（絕大多數宣稱複核成立，且多處實情比報告更嚴重）；但今天實測發現一個 P0 環境阻斷——Windows 應用程式控制原則封鎖 OCP DLL，build123d 全滅，Python 測試基線目前無法重現「916 全綠」。**

---

## 1. P0 新發現（07-12 盤點未涵蓋）

### 1.1 Python 測試基線被系統政策阻斷 🔴
- `import OCP` 失敗：「**應用程式控制原則已封鎖此檔案**」（Smart App Control / WDAC 類政策封鎖未簽章 DLL）。
- 套件 2026-07-10 安裝、07-12 測試還能全綠 → 是**系統政策在 07-12 之後變更**，非程式碼問題。
- 實跑 `python -m pytest tests/cad-worker/ tests/prompts/`（Python 3.12，2026-07-13）：
  - 直接跑：**收集中斷**（見 1.2）。
  - 排除壞檔後：**31 failed / 244 passed / 76 skipped / 37 errors**。
- 影響：任何工作包的 §14 驗收目前都跑不動 Python 基線。**必須先解除封鎖**（使用者操作）。

### 1.2 `test_topology_sweep.py` 收集防護失效
- `tests/cad-worker/test_topology_sweep.py:41` 的 `-> Part` 是模組層函式註記，Python 3.12 在 def 時求值；build123d import 失敗時 `Part` 未定義 → **NameError 讓整包 pytest 收集中斷**，`skipif(BUILD123D_AVAILABLE)` 防護救不了。
- 修法：檔頭加 `from __future__ import annotations`（一行）。

### 1.3 `tests/ui/freecad-engine-replay.ps1` 從未可執行 🔴
- 第 1 行 `<#` 沒有對應的 `#>`（全檔零個），PowerShell parser 實測：`The terminator '#>' is missing`。
- 該檔只有一個 commit（6516217）——**自建立起就 parse error，任何時候都跑不起來**。
- 影響：Master Plan 舊 §15 序 5 的「replay 12/12」宣稱需重新歸屬（可能實為 `tests/cad-worker/test_wp1_7_vertical_slice.py` 的引擎層 pytest 12/12）。

### 1.4 .NET 基線 ✅（07-13 實測）
- `dotnet build OpenCad.slnx`：0 錯誤 0 警告。
- `dotnet test`：**138/138 全過**。與宣稱一致。

---

## 2. 07-12 盤點宣稱複核結果

### 2.1 草圖求解紅線（→WP1-2R）——全部成立，且更嚴重
| 宣稱 | 複核 | 證據 |
|---|---|---|
| heuristic 投影求解、無聯立/迭代/殘差 | 成立 | `sketch_solver.py:233-234` for-loop 逐約束；docstring :26 宣稱「非線性迭代」與實作不符 |
| rebuild 不讀 constraints | 成立 | 兩個 adapter grep constraint＝0；`build123d_adapter.py:328-329`、`freecad_adapter.py:462` 只讀 sketch_entities |
| angle/symmetric/tangent 空殼＋測試假綠 | 成立 | `_apply_constraint`（:244-395）無此三分支；`test_sketch_solver.py:234-248` 只驗型別 |
| DOF 成本表相減、衝突集切最後 N 個 | 成立 | `sketch_solver.py:194,197,206-209` |
| 真 Sketcher 只在 spike、測試不在自動化路徑 | 成立（測試數實為 **19** 非 18） | pytest.ini testpaths 不含；run_freecad_tests.bat 只跑 adapter 測試 |

**加碼發現**：
- **solve 與實體建立幾乎脫節**：`_build_sketch` 只用 rectangle/circle 等閉合圖元參數建面，`line/arc/construction_line` 被當輔助線丟棄（`build123d_adapter.py:369-375,399-419`）——solver 主要作用的 line 幾何根本不參與實體。
- `calculate_dof` 只查成本表不看座標——約束套用前後 DOF 恆等，對實際幾何零敏感度。
- freecad `_build_sketch` 連 `arc` 圖元都沒支援（`freecad_adapter.py:482-610` 無 arc 分支）。

### 2.2 FreeCAD 覆蓋率（→WP1-0R2）——成立，一處歸因錯誤
| 宣稱 | 複核 | 證據 |
|---|---|---|
| freecad 9/22 特徵、缺型 ValueError | 成立 | `freecad_adapter.py` 9 個 `_build_*`；ValueError 在 :411 |
| build123d 22/22、差集 13 型 | 成立 | 差集正名：shell/sweep/loft/mirror/boolean_union/boolean_difference/boolean_intersection/draft/rib/thin/variable_fillet/countersink/cosmetic_thread |
| LIMITATIONS.md 宣稱不實未改 | 成立 | :86 "largely feature-complete"、:66-67 Loft/Sweep=✅ |
| datum 佔位 | 成立 | `_resolve_face:210-220` 硬編、`_resolve_vertex:233` 回原點、freecad :491-494 退回 XY |
| 預設引擎 build123d | 成立 | `server.py:42` |
| **NEMA17 含 shell 擋 freecad smoke-test** | **不成立（歸因錯誤）** | NEMA17 只有 sketch/pad/hole×2/fillet（全在 freecad 支援內）；**shell 在 `esp32cam-enclosure` 與 `needle-box-5x10`** 兩個範例 |

**加碼發現**：
- freecad `_build_chamfer` 的 edge_selector 是**死碼**（:795-798，if/else 分支相同，選邊參數無效）。
- freecad `_build_revolve` 已知產零體積（:826-829 註解自承），且 `FreeCADShapeWrapper.volume` 遇例外**回 0.0**（:248-253）——錯誤被掩蓋成「體積 0」。
- `server.py:1378` 註解自承 build123d 的 reference_geometry derived_geometry 也未完整接線（佔位不只 freecad）。
- 正向：`_get_adapter()` 已改 fail-fast（freecad 不可用時 raise 不回退）；FreeCAD Face/Edge proxy 層完整，補 13 特徵不用重寫基礎設施。

### 2.3 契約同步（→WP-S1）——成立，且**範圍被低估**
| 宣稱 | 複核 |
|---|---|
| C# CommandValidator 缺 WP1-6 六型驗證 | 成立，**且低估**：C# 只對 7 型強制 input，Python 有 21 型——除六型外還漏 sweep/loft/mirror/linear_pattern/circular_pattern/boolean×3 共 **14 型不對稱** |
| LLM planSchema 混入 datum 三型 | 成立（`LlmProviderBase.cs:124`；唯一污染點，`EngineSupportedFeatureTypes` 與 commandSchema 乾淨） |
| feature.schema reference_geometry 孤立 | 成立（:224-259 無任何 $ref 引用） |
| reorder_feature UI 未接線 | 成立（Desktop grep 零命中） |
| 五處特徵清單一致 | 部分：四處一致（22 型），只有 planSchema 多 3 個 datum |
| SnakeCaseEnumConverter／clarification 破口 | 不成立（兩者契約正常） |

**新發現的破口（07-12 未列）**：
- `update_feature` 有效欄位：Python 接受 `constraints`（`command_validator.py:161-165`），C# 不含（`CommandValidator.cs:181-183`）——只帶 constraints 的更新 C# 擋、Python 放行。
- `plane.base` 三方不一致：Python 接受 `datum:<id>`（:154）、C# 只接受 XY/XZ/YZ（:170）、schema enum 也只有 XY/XZ/YZ——而 LLM prompt（`LlmProviderBase.cs:111`）明確教模型輸出 `datum:<id>`。
- `create/update/delete_reference_geometry` action：Python validator＋server 齊全，C# validator switch 無 case（落 default「未知的 action」）。

### 2.4 WP1-7-UI Gate 腳本（宣稱 07-12 已修）——大多屬實，兩處要打折
**確實修好**：`$pid` 賦值已除、缺 token 一律 exit 1（無 exit 0 路徑）、step 9 真 Stop-Process＋重啟重開、11 步全有實質斷言、smoke-test 無假綠路徑（PASS 靠 rebuild 200＋glb 200 的 log 證據）。

**名不副實（非假綠，但驗證力被誇大）**：
- Step 2「LLM plan 語意等價」：**沒有 LLM**——把同一個硬編碼 `$sketchFeature` 送 apply_plan 再與常數 60/40/XY 比（vertical-slice-a.ps1:156-172），是 identity 比對，只證明 apply_plan 端點能跑。
- Step 9 快照只比 `feature_id,type,name,input`（:270,287），**不含 parameters**——重啟後掉尺寸/孔位仍會 PASS。

**其他**：
- `tests/prompts/test_llm_convergence.py:71` 有**恆真斷言**（手工造的壞 plan 斷言自己是壞的）；案例 1/1b/2/4 皆模擬 plan 自我斷言，非真實 gateway。
- `pytest.ini` testpaths 只含 `tests/cad-worker`——`tests/prompts` **預設不會跑**。
- `tests/geometry`、`tests/unit`、`tests/golden-models` 三目錄仍空。

---

## 3. 檔案家務更正

- 根目錄 `FreeCAD_Packaging_Notes.md`（550 bytes，套件版本清單）與 `Documemt/FreeCAD_Packaging_Notes.md`（6.5KB，封裝方案）**不是重複檔，是撞名**——處置應為改名（如 `PACKAGE_VERSIONS.md`）或併入 Documemt 版，非直接刪除。
- 本地領先 origin/main **16 個 commit 未 push**。

---

## 4. 對 Master Plan 的校正清單（已落實於 2026-07-13 重整版）

1. 新增 **WP-ENV0**（環境修復）插在佇列最前——基線跑不動，一切驗收都是空談。
2. WP-S1 範圍擴大（C# input 14 型、constraints 欄位、plane.base datum、reference_geometry action、恆真斷言、replay 腳本 parse、prompts 入 testpaths）。
3. WP1-0R2 加入 chamfer 死碼、revolve 零體積＋volume 掩蓋、freecad sketch arc。
4. freecad smoke-test 阻塞歸因改為 esp32cam-enclosure／needle-box（非 NEMA17）。
5. 地雷 #22 假綠三態擴為四態；新增地雷 #25（App Control 封鎖 DLL）。
6. 「916 Python 全綠」基線宣稱加上環境前提註記。
7. WP1-7 Gate 註記 step 2／step 9 弱斷言，補強項歸入 WP-H1 真 gateway 實測。
