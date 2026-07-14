# OpenCad Master Plan 歸檔（已完成工作包規格）

> 2026-07-13 自 `OpenCad_Master_Plan.md` 移出。這些包**已完成並驗收**（含打折註記），規格原文保留於此供追溯；**不再發包**。
> 現況與殘缺一律以 Master Plan §1 現況總表為準；本檔不更新。

---

## Phase 0：引擎決策閘門（全部 ✅，2026-07-11）

**目的**：回答「Avalonia UI＋FreeCAD 權威核心」可不可行。
**Kill Criteria**：5 週內若無法同時達成 (a) 穩定 face/edge 選取、(b) headless 草圖建立＋求解＋DOF 診斷、(c) 存檔重開 round-trip 參照不變 → 停止路線 B 改走路線 A。
**結果**：三項全過，路線 B 續行（`Phase0_Engine_Decision.md`）。

### WP0-1：FreeCAD Headless Worker Spike ✅
FreeCAD 1.1.1 headless HTTP worker prototype（`cad-worker-freecad/`，獨立、不接主 app）：隨機埠＋token＋health；projects/commands（sketch/pad/hole/fillet）/rebuild/exports（STEP＋GLB）；Sketcher addGeometry/addConstraint/setDatum；逐面 tessellate 帶 triangle_range 輸出 display_map；.FCStd 存檔重開 rebuild；效能量測。驗收：HTTP 重演 60×40 矩形→pad 10→hole Ø6→fillet R2、STEP 讀回 bbox 驗證、修改 pad 60→80 fillet 不漂移、存檔重開一致。報告：`Phase0_FreeCAD_Spike_Report.md`。

### WP0-2：Sketch Solver Kill Test ✅
FreeCAD Sketcher 逐約束 pytest（水平/鉛直/平行/垂直/相切/同心/重合/等長/對稱/中點/距離/半徑/角度）、DOF 診斷、過約束衝突集、拖曳模擬（<50ms/100 entities 量測）、setDatum 尺寸驅動、100/500 entity 規模曲線。測試在 `cad-worker-freecad/tests/`（19 個，僅 cp311 可跑——後續接線歸 WP1-2R）。

### WP0-3：Display Topology Map＋精確 Picking ✅
契約 `schemas/display_map.schema.json`（faces：face_id/brep_face_ref/source_feature_id/surface_type/triangle_range/area/centroid；edges：polyline）。Worker：GlbExporter 逐面 tessellation＋triangle_range（與 GLB 同一段程式產生）；`GET .../display_map`；rebuild 先寫檔再 bump mesh_revision 再 SSE。Viewer：raycast→二分搜 triangle_range→face；hover 高亮；click 發 `FaceSelected`；mesh_revision 不符丟棄；不干擾 OrbitControls。C#：ViewerBridge `FaceSelected`→特徵樹選取。

### WP0-4：Persistent Reference 語意化＋Parameter Sweep ✅
v2 語意參照（ref_version/source_feature_id/topology_type/query.intent/filters/disambiguation），舊 DSL fallback；`resolve_reference` 在 `cad-worker/cad_worker/topology.py`；`REFERENCE_LOST`/`REFERENCE_AMBIGUOUS` 雙端錯誤碼。L 型支架 ≥60 組參數 sweep＋破壞案例＋對稱陷阱（`tests/cad-worker/test_topology_sweep.py`，569 組）。
⚠ 打折：解析器僅測試使用未接 adapter；edge disambiguation by centroid 未實作以 skip 迴避（歸 WP-S1 之後）。

### WP0-5：決策報告與 Gate ✅
`Documemt/Phase0_Engine_Decision.md`：Kill Criteria 逐條判定→路線 B 續行；遷移清單；發包順序更新。

---

## 引擎無關包 A–D（全部 ✅）

### 包 A：聊天輸入 Enter 重複修正 ✅（⚠中文 IME 驗收 2 待人工實測）
根因候選：IME 選字衝突／事件雙重掛載。已升 Avalonia 11.3.18＋掛載防禦。驗收含英文 Enter 一次、IME 選字不送出、Shift+Enter 換行、交錯操作不重複。

### 包 B：LLM 對話上下文記憶 ✅
不引入 LangChain；`ChatTurn` history 塞 messages 陣列；卡片以一行摘要進歷史；保留 10 輪/單輪 2000 字/總量 8000 字；切專案清空。驗收：真 gateway 兩輪/三輪指涉實測＋.NET 單元測試。

### 包 C：3D 視窗座標系與可點選基準面 ✅
Triad（第二 Scene＋正交相機疊繪角落，紅X綠Y藍Z）；三基準面半透明網格 hover/點選；樹↔視窗雙向聯動（`DatumPlaneClicked`；選取單一來源＝C# SelectedFeature）；與模型面 picking 共用 mousedown 分派器。

### 包 D：草圖基準面 plane 欄位 ✅
sketch 特徵加 `plane: {base: XY|XZ|YZ, offset}`；缺 plane 視為 XY 向下相容；adapter plane_map＋offset；UI 平面選擇＋enterSketchMode plane 參數＋樹顯示 (sketch@XZ)；保留 `face:`/`datum:` 介面。

---

## Phase 1 已完成/已驗收工作包

### WP1-0／WP1-0R：FreeCAD Worker 正式化 ✅（引擎接線層面）
`cad-worker/cad_worker/adapters/freecad_adapter.py`＋`OPENCAD_ENGINE` 切換（預設 build123d）；golden tests 依 §14.8 判準在 freecad 重跑（36 adapter tests，cp311）；專案 JSON 引擎透明；staging transaction 行為對齊；打包方案（FREECAD_DIR）記錄於 Phase0 報告。
⚠ 打折：**僅 9/22 特徵**（→WP1-0R2）；headless revolve 產零體積；「replay 12/12」宣稱經 07-13 複核需重新歸屬（replay 腳本從未可執行，見 Addendum §1.3）。

### WP1-1：Document Model v2 ✅
schema v2（document_type/reference_geometry/bodies/features order+state/rollback_position/global_variables/configurations/custom_properties）；有序歷史＋`REORDER_DEPENDENCY_VIOLATION`；狀態機 active/suppressed/failed/orphan；v1→v2 migration＋測試；新命令 suppress_feature/reorder_feature/set_rollback 走 staging；UI 狀態圖示＋抑制選單＋回溯。
⚠ 打折：reorder_feature UI 未接線（→WP-S1）。

### WP1-2：真 Sketcher 前端 — **部分完成，紅線違規**（→WP1-2R，規格見 Master Plan §5）
已落地：constraints/solver_status 契約、`POST .../sketch/{id}/solve` 互動端點、UI 約束工具列＋DOF 列＋拖曳 throttle＋尺寸驅動、C# 接線。
未落地（紅線）：rebuild 不求解、heuristic 求解器、angle/symmetric/tangent 空殼、DOF/衝突非真實分析。原驗收條目移入 WP1-2R。

### WP1-3：Reference Geometry — **部分完成**（收尾歸 WP-S1）
datum plane/axis/point 七種 method、schema、樹資料夾、新增對話框、LLM catalog。
⚠ 打折：`_resolve_face` 硬編方位、`_resolve_vertex` 回原點、FreeCAD 下 datum 草圖面退回 XY、UI 對話框硬編 demo 級。

### WP1-4：Property Manager 與人工編輯補全 ✅
特徵參數表單（型別化控件＋✓套用走 staging）、量測工具、選取過濾器、顯示模式（shaded with edges/wireframe/transparent/isolate）。

### WP1-5：檔案格式與復原強化 ✅
Atomic save（temp→fsync→rename）＋crash 測試；autosave journal（20 筆）；schema migration 框架＋future version 唯讀；content checksum；ZIP 匯入防護。B2（專案改名/刪除/複製/縮圖）併入完成。

### WP1-6：單零件特徵補全（第二批）— 程式碼 ✅ 有瑕疵
draft/rib/thin/variable_fillet/countersink/cosmetic_thread：schema→adapter→validator→LLM catalog→golden test。
⚠ 打折：build123d `_build_draft` 是 no-op、`_build_variable_fillet` 退化單半徑；golden test 僅 build123d；C# validator 未覆蓋六型（→WP-S1）。

### WP1-7：Vertical Slice A（Phase 1 Gate）✅（2026-07-12，附打折註記）
11 步腳本 `tests/ui/vertical-slice-a.ps1`＋pytest 對應：①人工 fully-constrained L 型支架草圖 ②LLM plan 語意等價 ③pad ④兩面各開孔 ⑤選邊 fillet ⑥改長度參照存活 ⑦DOF=0/特徵樹/named dims ⑧一次 undo 撤整筆 AI transaction ⑨存關重開一致 ⑩STEP 外部驗證 ⑪剖面截圖代 drawing。
實跑：build123d 11/11＋freecad 11/11；smoke-test build123d PASS。
⚠ 打折（07-13 複核）：step 2 無 LLM、是 apply_plan identity 比對；step 9 只比特徵身份不比 parameters（補強歸 WP-H1）；freecad smoke-test 被 esp32cam/needle-box 範例的 shell 特徵擋下（→WP1-0R2）。

---

## 橫向已完成

### WP-H1：LLM 收斂 — 程式碼 ✅、真 gateway 端到端待補（殘項見 Master Plan §9）
單 Orchestrator＋deterministic tools；capability payload（schema 生成 catalog）；拒絕規則雙層；repair 迴圈低風險 2 次白名單。
⚠ 打折：`tests/prompts` 為模擬 plan 自我斷言（含一個恆真斷言），非真實 gateway 端到端。

### WP-H2：安全與 IPC 強化 ✅
token 進 header＋session 重生；Origin 驗證；path canonicalization；匯入上限；Worker 配額（超時 kill＋staging rollback）；temp 清理。
