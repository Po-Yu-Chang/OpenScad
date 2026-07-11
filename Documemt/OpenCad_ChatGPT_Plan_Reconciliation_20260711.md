# OpenCad — ChatGPT 技術彙編 × Codebase 對接與行動方案

> 產出日期：2026-07-11
> 來源：`OpenCad_Conversation_Technical_Planning_20260711.pdf`（ChatGPT 對話彙編，58 頁三部）
> 對接對象：`OpenCad_Master_Plan.md`（唯一活文件）＋現行 codebase（commit `013be55` 之後，WP1-0R 已完成未提交）
> 本文定位：**不是取代 Master Plan**，而是把 ChatGPT 彙編與現況對帳，指出「已落地／有缺口／真正新增」三類，並把新增項轉成可發包工作。

---

## 0. 一句話結論

ChatGPT 那份彙編 = 三份文件：

| 部 | 內容 | 與 repo 的關係 |
|---|---|---|
| 第一部 | 完整解法與測試計畫（LLM CAD 硬化） | **已是現行地基**，多數已落地；但**測試矩陣與 Intent Parser 有實質缺口** |
| 第二部 | 對標 SolidWorks 缺口審閱 | **就是** `OpenCad_SolidWorks_Gap_Review_20260711.md`，Master Plan 的依據 |
| 第三部 | GitHub 相似專案調查與參考策略 | **真正的新輸入**——repo 完全沒有對應，未收割 |

所以本方案聚焦三件事：
1. **對帳第一部**，補齊兩個真缺口：**Intent Parser 單一結果重寫（含已確認 bug）** 與 **測試矩陣落地**。
2. **收割第三部**：把 5 個標竿開源專案轉成「模式來源」，加速現行路線 B，而非重起爐灶。
3. **正面回應一個策略張力**：ChatGPT 強推「路線 A（FreeCAD Workbench，Fork freecad-ai）」，但 repo 已過 WP0-5 Gate 走路線 B——本文給出「維持 B、收割 A 的模式」的具體理由與做法。

---

## 1. 三部逐項對帳

### 1.1 第一部（完整解法／測試計畫）→ 多數已落地

| ChatGPT 建議 | repo 現況 | 判定 |
|---|---|---|
| 移除 `current_solid` 覆蓋 `feature.input` | 已移除隱式 current_solid（Master Plan §1「已移除隱式 current_solid」） | ✅ 已落地 |
| 多步改「暫存→驗證→重建→驗收→一次提交」 | `apply_plan` clone→apply→rebuild→commit-or-rollback（§1 Staging Transaction、地雷 #14） | ✅ 已落地 |
| `exclude_holes` 改語意化 Edge Selector＋provenance | `TopologyTrace`＋`_select_edges` provenance DSL（§1） | ✅ 已落地 |
| Repair 不得靜默改尺寸；風險分級＋確認 | 修復迴圈 D2、低風險自動修復上限 2、地雷 #16 | ✅ 已落地 |
| 型別化錯誤碼（不靠中英文字串分類） | `ErrorCodes.cs`＋Python 對稱、`REFERENCE_LOST/AMBIGUOUS` | ✅ 大致落地 |
| 交易式 Clear All（原子 reset、一筆 undo） | `POST /reset`＝一筆 transaction（§1） | ✅ 已落地 |
| **Intent Parser 單一結果（Undo\|Redo\|ClearAll\|Ambiguous）** | **`IntentMatcher.cs` 仍是分散 `IsUndo/IsRedo/IsClearAll`** | ❌ **未落地，有 bug（見 §3）** |
| **完整測試矩陣**（CT/IN/GR/TX/G/RP/E2E＋120 golden＋1000 fuzz） | 部分：command_validator 18、transaction 6、golden 13、`tests/prompts/` | ⚠️ **部分缺口（見 WP-R2）** |
| Debug Export（correlation id＋各階段紀錄） | 有聊天匯出，但非「normalized command＋validation 各階段」完整 bundle | ⚠️ 部分 |

### 1.2 第二部（SolidWorks 缺口）→ 已是 Master Plan 骨幹

第二部 = Gap Review 原文，Master Plan 的 §0.2 路線、§5 Phase 1（真 Sketcher / Document Model v2 / reference geometry / Property Manager）、§6–8 Phase 2–4 全數源自此。**無新增動作**，只需確認 Master Plan 仍與之一致（已一致）。

### 1.3 第三部（GitHub 參考專案）→ **完全未收割（新輸入）**

repo 內沒有任何文件引用這 5 個標竿專案，也沒有 benchmark 套件、參考策略、授權盤點。這是本方案最主要的新增價值 → §4 的 WP-R1/R2/R3。

---

## 2. 策略張力：路線 A vs 路線 B（正面回應）

**ChatGPT 第二／三部最強建議**：先做「FreeCAD-based AI Workbench（路線 A）」、直接 Fork `ghbalf/freecad-ai`，因為能免去重做 Sketcher/PartDesign/Assembly/TechDraw/精確選取。

**但 repo 現況**：
- WP0-5 Gate **已通過 → 路線 B**（Avalonia UI＋FreeCAD 權威核心），`Phase0_Engine_Decision.md` 三項 Kill Criteria 全過。
- **WP1-0R 剛把 FreeCAD 變成可用權威核心**：36 個 adapter 測試全綠（3.11 bundled python）、雙引擎 smoke-test PASS、`freecad-engine-replay.ps1` 12/12 PASS、STEP bbox 60×40×10 驗證。單一環境策略（FreeCAD 的 python 同跑 build123d）已證實可行。

**建議：維持路線 B，把 freecad-ai 當「模式來源」而非 fork 底座。** 理由：
1. Gate 已決且有證據；FreeCAD 已是權威核心，ChatGPT「避免重做 Sketcher」的最大痛點，正是 Phase 1 WP1-2 用 FreeCAD Sketcher 後端解掉（WP0-2 solver kill test 已通過）。
2. 品牌／繁中／全本地 AI UX 是差異化來源，Avalonia 殼是資產，不宜丟。
3. Fork LGPL-2.1 的 freecad-ai 進商業產品有授權義務（§6）；當「模式參考」風險低很多。

**⚠️ 例外觸發條件（寫死，避免自我安慰）**：若 WP1-2（真 Sketcher 前端）或 WP1-7 Vertical Slice A 在 FreeCAD 引擎上**連續 2 個發包週期無法達成拖曳求解＋DOF 診斷的可用體驗**，則重新評估「Avalonia 殼 + 嵌入 FreeCAD GUI 元件」或降級路線 A。此條等同 Phase 0 Kill Criteria 的延伸。

---

## 3. 【已確認 bug】Intent Parser 關鍵字衝突

ChatGPT 第一部 §2.3-A 與 §7.1 明確預測的 bug，**在現行 `src/OpenCad.Application/IntentMatcher.cs` 真實存在**：

```csharp
// 第 12 行：IsUndo 含「還原」
public static bool IsUndo(string s) => ... || s.Contains("還原") || ...
// 第 17 行：IsRedo 含「取消還原」
public static bool IsRedo(string s) => ... || s.Contains("取消還原") || ...
// 第 55 行：Classify 先檢查 IsUndo
if (IsUndo(s)) return "undo";
if (IsRedo(s)) return "redo";
```

**失效情境**：
- 輸入「**取消還原**」→ `IsUndo` 先命中（含「還原」）→ 回 `undo`，**應為 redo**。使用者要「重做」卻被「復原」，破壞性。
- 輸入「**不要還原**」「**先不要清空**」→ 命中 Undo/ClearAll，**應為不執行**（無否定詞處理）。
- 「**清空孔位後重新排列**」→ `IsClearAll` 命中「清空」→ 誤觸整份清空。

Master Plan 現行 §15 發包表**沒有**涵蓋此項（WP-H1 只談 LLM 收斂，不含本地 parser 重寫）。→ 新增 **WP-H0**（§4）。

---

## 4. 新增／補齊工作包（接入 Master Plan §9 橫向包與 §15 發包表）

> 下列包沿用 Master Plan 發包格式：發包時附 §0 策略＋§1 現況＋§2 地雷＋§14 驗證方法論。

### WP-H0　本地 Intent Parser 單一結果重寫（**最優先，修已確認 bug**）

**目標**：把分散 `IsUndo/IsRedo/IsClearAll` 換成 ChatGPT §7 的單一 `Parse(text) → LocalIntentKind`（`None|Undo|Redo|ClearAll|Rebuild|ZoomFit|SetView|ToggleDatumPlanes|Ambiguous`）。

**實作要點**：
1. NFKC 正規化＋trim＋標點空白正規化（全半形統一）。
2. **先長後短、否定詞優先**：先匹配「取消還原／取消復原」→ Redo；否定詞（不要、先不要、別、剛剛說的）→ None，不執行。
3. ClearAll 需整體語境（避免「清空孔位」「重新開始畫一個圓」誤觸）；破壞性操作不得用 embedding／模糊相似度。
4. 多意圖或衝突 → `Ambiguous` → 反問，不直接執行。
5. `MainViewModel` 呼叫點改用單一結果；ClearAll 一律走確認卡片。

**驗收（ChatGPT §12.3 測試表落地）**：IN-001..IN-008 正向、IN-101..IN-107 否定與誤判防止全綠（尤其 **IN-106「取消還原」只命中 Redo**、IN-101「不要還原」不執行）；再加 property-based fuzz ≥1000 變形（標點／空白／全形／簡繁／語助詞）。既有 `IntentMatcherTests.cs` 併入改寫。

### WP-R1　參考專案收割（橫向包，模式來源，非 fork）

**目標**：把 5 個標竿專案的**可借用模式**萃取成 repo 內的設計筆記與選擇性移植，加速現行 WP，並完成授權盤點。

| 來源 repo | 授權 | 收割目標 → 對接現行 WP |
|---|---|---|
| `ghbalf/freecad-ai` | LGPL-2.1 | Provider 抽象、tool reranking、document/selection context 收集、session resume/context compacting → **WP-H1**（LLM 收斂）｜FreeCAD 使用者目錄/設定 migration → WP1-5 |
| `armpro24-blip/cad-cae-copilot` | MIT | topology map／`@face:*` 語意 pointer、每次修改前後 regression/critique diff、approval surface、`require(...)` design-rule、provenance 封裝 → **WP0-4／WP1-4／WP-H4** |
| `jzjzzzzzzz/IntentForge` | Apache-2.0 | Pydantic Typed IR、named parameter table、constraint graph、feature plan＋reason、edit-intent（不重生成整份）→ **命令合約／WP-H1** |
| `zqf3229294/Text23D` | MIT | FastAPI＋runner 程序拆分、WebSocket event stream、artifact storage、FreeCAD persistent worker → 對照現行 Worker（多為已有，取其 event/artifact 模式）|
| `earthtojake/text-to-cad` | MIT | SKILL.md 教學法、**10 個難度分級 CAD benchmark**、viewer、STEP 標準件 sourcing、製造交付（DXF/G-code）→ **WP-R3** |

**產出**：`Documemt/OpenCad_Reference_Harvest_Notes.md`（逐 repo：可借用 / 不照搬 / 對接 WP）＋`Documemt/OpenCad_License_Inventory.md`（LGPL/MIT/Apache 義務、`contextform/freecad-mcp` 無 LICENSE 不複製）。
**鐵則**：不 fork、不複製原始碼進 repo；只移植「設計模式」並重寫；任何直接取用 LGPL 程式碼須先過授權盤點。**與全本地／機密不入 repo 原則（地雷 #11、#12）一致。**

### WP-R2　測試矩陣對帳補齊（把第一部 §12 落地）

**目標**：逐一比對 ChatGPT §12 測試矩陣（CT/IN/GR/TX/G/RP/E2E）與 repo 現有測試，缺口補齊；建立 golden corpus 與 fuzz。

**盤點清單（發包時逐條標「已有／缺／待補」）**：
- Contract：CT-001..010（缺欄位、空陣列、負值、型別不符、未知欄位 `diamter` 拒絕、schema 版本、round-trip）。
- Graph：GR-001..008（**GR-002：fillet.input=pad 時不得取全域 current solid** — 對應已移除的 current_solid，補回歸測試）。
- Transaction：TX-001..009（第 3 步失敗正式 graph 不變、一次 Undo 撤整份、Redo 不呼叫 LLM、`GRAPH_VERSION_CONFLICT`）。
- Geometry：G-001..011（**G-003 圓柱外緣不可當孔**、G-009 selector 空集合不 fallback all、G-011 build123d 升級回歸）。
- Repair：RP-001..007（R2 靜默改值防止、同修復不重試）。
- E2E：E2E-001..004（原始 10×5×5＋Ø3＋R2 孔不動 全流程、靜默改值防止）。
- **LLM Golden Corpus**：≥120 條繁中工程語句（30 建模／20 孔徑單位／20 修改 preserve／15 本地意圖／15 歧義追問／10 不支援／10 越權無效），版本控制、離線／排程跑，**不進 PR gate**（機率性）。

**驗收門檻（ChatGPT §12.10）**：已接受 transaction schema validity 100%、破壞性本地意圖 false positive **0**、受保護尺寸被靜默修改 **0**、核心幾何 benchmark 100%、Undo/Redo deterministic replay 100%、unknown error 導致 UI crash **0**。
**綁定**：與 Master Plan §9 WP-H3 測試套件擴充合併管理（solver/topology/config/assembly/drawing/recovery）。

### WP-R3　Benchmark 套件（採 text-to-cad 的分級 benchmark）

**目標**：把「固定 NEMA17」升級為**會破壞拓撲的參數化 benchmark 集**（呼應 ChatGPT「第一 benchmark 改參數支架＋拓撲變更」與 Gap Review §21）。
1. 引入 L-bracket、mounting plate、針盒、外殼 4 型參數模型（參 text-to-cad 10 benchmark 難度分級）。
2. 每型：自然語言建立 → 只改指定孔徑不影響其他 → 主要尺寸 sweep 拓撲參照存活或安全失敗 → save/reopen 一致 → STEP 可在外部工具重開。
3. 對接現有 `tests/cad-worker/test_topology_sweep.py`（已有 569 組 sweep）與 `vertical-slice-a.ps1`。

---

## 5. 立即動作序列（依**真實 code 狀態**校正，非 §15 表面）

> **更正（2026-07-11）**：WP1-0R **早已 commit**（`b606c1c` Finalize WP1-0R，含 freecad_adapter/server.py/AppSettings/報告/測試）。先前誤判「已完成未 commit」——git status 看到 `server.py`/`freecad_adapter.py` 髒，其實是 b606c1c **之後**的新 WIP（專案管理端點、草圖 plane/datum、FreeCAD 測試文件、UI），非 WP1-0R。WP-H0（Intent Parser）已於 `9896273` commit。

1. ✅ **WP-H0 已 commit（`9896273`）**：Intent Parser 分散式改單一 `Parse`，40 測試綠、build 0 警告。WP1-0R 已在 `b606c1c`。剩餘 b606c1c 之後的 WIP 正逐一分組提交（見下）。
2. **WP-H0（Intent Parser 重寫）**：修 §3 已確認 bug，最小改動、高價值、無引擎相依，可立即發。
3. ✅ **WP1-7 Vertical Slice A（Phase 1 Gate，引擎層）已在 freecad 通過**（2026-07-12）：`test_wp1_7_vertical_slice.py` 用 FreeCAD 1.1.1 bundled python 3.11＋`OPENCAD_ENGINE=freecad` 跑，**12/12 全綠**（11 步＋full slice）。路線 B 假設在引擎層獲驗證。**尚待**：(a) UI 層 UIA 實跑 `vertical-slice-a.ps1`（驅動 Avalonia app）；(b) 依 WP1-0R §H 決定是否把預設引擎切 freecad（deliberate 決策，非自動）。
4. **WP-R1 收割筆記＋授權盤點**：與 2/3 並行，產出兩份 `Documemt/` 文件，為 WP-H1／WP1-4 供模式。
5. **WP-R2 測試對帳**：隨 WP1-7 一起把 E2E-001（10×5×5＋R2 孔不動）與 golden corpus 起頭建立。
6. 之後回到 Master Plan §15 序 6 起（WP1-1 rollback bar UI 殘留 → WP1-2 拖曳求解 UIA 實測 → …）。

---

## 6. 授權治理（ChatGPT 第三部 §9，repo 目前缺）

全本地／可商業化產品必須有授權盤點，現行 repo 無此文件：
- `ghbalf/freecad-ai`＝**LGPL-2.1**：可 fork 但須履行義務；本方案改為「模式參考」以降風險。
- FreeCAD 本體＝**LGPL**、OCCT＝**LGPL＋例外**：打包散布須保留 notice、動態連結、提供替換能力。
- `cad-cae-copilot`/`Text23D`/`text-to-cad`＝**MIT**、`IntentForge`＝**Apache-2.0**：適合抽取，保留 copyright/notice。
- `contextform/freecad-mcp`＝**無 LICENSE**：不得複製程式碼，且其 custom Python execution 不可作安全命令邊界。

→ 併入 WP-R1 產出 `Documemt/OpenCad_License_Inventory.md`。

---

## 7. 對 Master Plan 的具體修改建議（發包者回寫）

1. §15 發包表：序 5 WP1-0R 改 ✅；插入 **WP-H0（Intent Parser 重寫）** 於序 5–6 之間（無前置、最優先修 bug）。
2. §9 橫向包：新增 **WP-R1／R2／R3**，並把 WP-R2 與現有 WP-H3 測試套件表合併管理。
3. §2 地雷清單：新增「**分散式意圖關鍵字會關鍵字衝突**——`取消還原` 含 `還原`、否定詞未處理；本地意圖一律走單一 `Parse` 且否定詞優先」。
4. §0.2：在路線 B 鐵則後補一條「**freecad-ai 等參考專案採模式移植、不 fork**；直接取用 LGPL 程式碼須先過授權盤點」。
5. §13 延後清單：確認 ChatGPT 第三部的研究型專案（Text2CAD/CAD-Recode/cadrille 等圖片／點雲反推）對應現行「單張圖片轉 3D 延後」，一致。
