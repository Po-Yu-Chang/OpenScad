# Phase 0 Engine Decision (WP0-5)

> 決策報告與 Gate
>
> 產出日期：2025-01-24
> 依據：WP0-1/0-2 報告（`Phase0_FreeCAD_Spike_Report.md`）+ WP0-3/0-4 落地結果

---

## 1. Kill Criteria 逐條判定

Master Plan §3 Kill Criteria（硬性）：

> 5 週內若無法同時達成 (a) 穩定 face/edge 選取、(b) headless 草圖建立＋求解＋DOF 診斷、(c) 存檔重開 round-trip 參照不變 → **停止路線 B**。

### (a) 穩定 face/edge 選取

| 判定 | 證據 |
|------|------|
| ✅ **通過** | WP0-3 已落地於現有 build123d stack：`display_map.schema.json` 定義引擎中立契約；`GlbExporter.export_per_face()` 逐面三角化 + `triangle_range` 對應；viewer `findFaceByTriangleIndex()` 二分搜 + 面級 picking；`GET /api/projects/{id}/display_map` 端點。9 個 pytest 驗收全綠。FreeCAD worker（WP0-1）也產出同格式 display_map，證明契約可跨引擎。 |

### (b) Headless 草圖建立＋求解＋DOF 診斷

| 判定 | 證據 |
|------|------|
| ✅ **通過** | WP0-1：FreeCAD headless HTTP worker 完整實作 sketch（含約束）/pad/hole/fillet，13 tests 全綠。WP0-2：Sketcher 求解器 19 tests 全綠——8 種約束逐一驗證、DOF 診斷（欠/全約束/遞減）、過約束衝突偵測+恢復、拖曳模擬（moveGeometry→solve→幾何跟隨）、尺寸驅動（setDatum 60→80 正確）、100/500 entity 規模測試。 |

### (c) 存檔重開 round-trip 參照不變

| 判定 | 證據 |
|------|------|
| ✅ **通過** | WP0-1 驗收 3：`.FCStd` 存檔→關閉→重開→rebuild，特徵樹與參照仍在，結果一致。WP0-4：persistent reference v2 語意化 + 569 tests 參數 sweep（W×D×T×H×hole_r×fillet_r），參數變更後參照存活。引擎中立契約（`persistent_reference` v2 schema）已定義，FreeCAD 可適配。 |

### 總判定

| Kill Criteria | 結果 |
|---------------|------|
| (a) 穩定 face/edge 選取 | ✅ 通過 |
| (b) Headless 草圖+求解+DOF | ✅ 通過 |
| (c) 存檔重開 round-trip | ✅ 通過 |
| **全部達成** | **✅ 路線 B 續行** |

---

## 2. 決定：路線 B 續行

**決定：路線 B 續行——保留現有 Avalonia UI，FreeCAD 1.1.1 成為唯一權威幾何核心。**

理由：
1. 三項 Kill Criteria 全部通過，無任何一項觸發降級。
2. FreeCAD headless 模式可行：Part workbench API 穩定、Sketcher 求解器可用、存檔 round-trip 可靠。
3. 引擎中立契約（display_map, persistent_reference v2）已在 build123d stack 驗證，FreeCAD worker 也產出同格式，換核心時只換產生端。
4. build123d 依 §0.2 鐵則 1 降級為 prototype/測試用途，不承諾跨引擎無損切換。

**不降級路線 A**。Avalonia 資產保留。

---

## 3. FreeCAD Worker 正式化遷移清單

### 3.1 端點遷移

| 現有端點（cad-worker） | 遷移目標（cad-worker-freecad） | 變更 |
|------------------------|-------------------------------|------|
| `POST /api/projects` | 已實作 | 改用 FreeCAD Document |
| `POST /api/projects/{id}/commands` | 已實作（sketch/pad/hole/fillet） | 擴充更多 feature type |
| `POST /api/projects/{id}/rebuild` | 已實作 | 加 DOF 回傳 |
| `POST /api/projects/{id}/exports` | 已實作（STEP via Import.export, GLB） | 確認 STEP 與 build123d 版互通 |
| `GET /api/projects/{id}/display_map` | 已實作 | 同格式，契約一致 |
| `POST /api/projects/{id}/save` | 已實作（.FCStd） | — |
| `POST /api/projects/{id}/load` | 已實作（openDocument） | — |

### 3.2 Schema 變更

| Schema 檔 | 變更 |
|-----------|------|
| `feature.schema.json` | 加約束類型 enum、加 `storage_format: "FCStd"`、加 `dof: int` 欄位、加 `conflicting_constraints` 欄位 |
| `display_map.schema.json` | 不需改（引擎中立） |
| `feature.schema.json` persistent_reference v2 | 不需改（引擎中立） |

### 3.3 build123d 保留用途

| 用途 | 說明 |
|------|------|
| 測試 fixture | WP0-3/0-4 的 687 tests 仍用 build123d |
| 快速 prototype | 開發期幾何驗證 |
| 獨立工具 | 不依賴 FreeCAD 的輕量幾何工具 |

### 3.4 遷移順序（併入 §15 序 5）

1. WP1-0：FreeCAD Worker 正式化——將 `cad-worker-freecad/` 從 prototype 提升為生產 worker，整合進 app 啟動流程
2. 同步：schema 變更（§3.2）
3. 同步：現有 `cad-worker/` 的 build123d 路徑保留為 fallback（過渡期）

---

## 4. 更新 §0.2 與 §15

### §0.2 更新

路線 B 假設已驗證。以下鐵則生效：
1. ✅ build123d 降級（測試/prototype 用）
2. ✅ Engine-neutral schema 保存 OpenCad 語意
3. ✅ Sketcher 後端為 MVP P0（已驗證可支撐即時拖曳）
4. ✅ Windows-first
5. ✅ GLB 為 display cache

### §15 發包順序更新

| 序 | 包 | 前置 | 狀態 |
|---|---|---|---|
| 0 | 包 A（Enter bug） | 無 | ✅ 已完成 |
| 1 | WP0-3（display map＋picking）／WP0-1（FreeCAD spike） | 無 | ✅ 已完成 |
| 2 | WP0-4（語意參照＋sweep）／WP0-2（solver kill test） | WP0-3／WP0-1 | ✅ 已完成 |
| 3 | 包 B（上下文記憶）／包 D（草圖平面） | 無 | ✅ 已完成 |
| 4 | **WP0-5 決策 Gate** | WP0-1..4 | ✅ **通過（本文件）** |
| 5 | 包 C（triad＋基準面）／WP1-0（FreeCAD 正式化＋WP-H4） | Gate 過 | ⬅️ **可發包** |
| 6+ | Phase 1 各包 | 各自前置 | 待發包 |

**Gate 結論**：路線 B 續行。Phase 1 引擎相關包（§5 標註「引擎相關」者）可開始發包，第一個為 WP1-0（FreeCAD 正式化）。

---

## 5. 風險與後續

### 已識別風險

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| PartDesign headless 不可用 | 高 | WP1-0 改用 Part workbench API（已在 WP0-1 驗證） |
| `Part.export()` STEP 讀不回 | 高 | 改用 `Import.export()`（已驗證） |
| 500 entity 建立成本高 | 中 | WP1-2 需增量建立策略 |
| 未測約束類型（Tangent/Equal/Symmetric 等） | 中 | WP1-2 補測 |
| FreeCAD 版本鎖定 1.1.1 | 低 | 正式化時追蹤 1.1.x 更新 |

### 後續行動

1. **WP1-0**（FreeCAD 正式化）：將 `cad-worker-freecad/` 整合進 app、處理 Worker 生命週期、schema 變更
2. **包 C**（triad + 基準面）：3D 視窗座標系可視化
3. **WP1-1**（Document Model v2）：文件模型重構
4. **WP1-2**（真 Sketcher）：基於 WP0-2 驗證的 Sketcher 能力，實作完整草圖編輯器