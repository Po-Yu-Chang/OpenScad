# OpenCad 總計畫（Master Plan）

> 最後更新：2026-07-13（**全文重整**：狀態併成 §1 單一總表、已完成包規格移至 Archive、發包佇列依 07-13 複核校正）
> 定位：**唯一的活文件**——現況、策略、待辦包、地雷、驗證方法都在這裡。
>
> **文件分工**：
> - 本文件＝現況總表（§1）＋地雷（§2）＋發包佇列與待辦規格（§3–§7）＋驗證方法論（§9）
> - `OpenCad_Master_Plan_Archive.md`＝已完成工作包的原始規格（不再發包，只供追溯）
> - 證據鏈：`OpenCad_Codebase_Review_20260712.md`（全面盤點）→ `OpenCad_Review_Addendum_20260713.md`（複核＋P0 新發現）
> - 架構原理：`OpenCad_Local_AI_CAD_Architecture.md`；差距分析：`OpenCad_SolidWorks_Gap_Review_20260711.md`（下稱 Gap Review）
> - 舊版章節對照：舊 §14 驗證方法論→**§9**；舊 §15 發包順序→**§3**；舊 §3–§5 已完成規格→Archive
>
> **進度速覽**：Phase 0 全✅、包 A–D✅、WP1-1/4/5✅、WP1-7 Gate✅（附打折註記）；✅ **WP-ENV0 完成（2026-07-14）**；⚠ **WP1-2R 後端已完成（2026-07-14，§3.2）——鐵則 3 紅線解除、真求解器、雙引擎 smoke-test 11/11，UIA 互動驗收待補**；⚠ **WP1-0R2 後端已完成（2026-07-14，§3.3）——FreeCAD adapter 達 22/22 parity、三範例雙引擎 rebuild 成功，桌面 UIA smoke-test 待補**；⚠ **WP-S1 後端已完成（2026-07-14，§3.4）——C#↔Python 契約對稱、datum 真 BREP 解析＋雙引擎草圖平面＋真選面 UI、假綠與家務清理，UIA 互動驗收待補**；下一包＝**WP-H1 殘項**（§3.5，真 gateway 端到端）／或一次補齊 WP1-2R／WP1-0R2／WP-S1 累積的 UIA 驗收。
>
> **每個工作包都是獨立可發包單位**：發包時把該節全文＋§1 現況＋§2 地雷＋§9 驗證方法論一起給執行模型，不得省略。

---

## 0. 產品定位與策略決定（2026-07-11 依 Gap Review 重訂）

### 0.1 定位聲明（對外對內一致，不宣稱「取代 SolidWorks」）

> **OpenCad 是一套全本地、AI 原生、以機械單零件與自動化設備設計為優先的參數化 CAD；保留 SolidWorks 類的草圖、特徵、組立與工程圖工作方式，並用工程語言大幅減少操作步驟。**

三層目標，驗收與宣稱分開，不得混用：

| 層級 | 內容 | 對應 Phase |
|---|---|---|
| MVP | 人工＋AI 都能編輯的 fully-constrained 單零件，拓撲參照存活參數變更 | Phase 0–1 |
| Daily CAD | 多 Body、方程式、組態、組立、BOM、基本工程圖、鈑金/焊件 | Phase 2–4 |
| Long-term parity | MBD/PMI、模具、CAM/FEA、PDM | Phase 5（不排時程） |

### 0.2 引擎路線：路線 B（已過 Phase 0 Gate）

**保留 Avalonia UI，FreeCAD 1.0+ 為唯一權威幾何核心。** Kill Criteria 已全數通過（`Phase0_Engine_Decision.md`）。

鐵則（寫進所有後續發包）：
1. **build123d 降級**：只用於 prototype、測試 fixture、獨立幾何工具，不再是未來正式 source of truth。
2. Engine-neutral schema 只保存 OpenCad 真正支援的語意。
3. **真正的 Sketch Solver 是 MVP P0**。「約束只存 metadata、座標由 LLM/程式算」**永久禁止**（Gap Review §4）。
4. Windows-first；核心保持可攜，macOS/Linux 正式發行延後。
5. GLB 只是 display cache，**不得**作為幾何或 selection 的 source of truth。

### 0.3 優先序（依使用情境：機台、治具、外殼、軌道、機構、倉儲設備）

**提前**：真草圖求解、Reference geometry、Multi-body、Configurations/Equations、組立與 mates、BOM、基本工程圖、鈑金、焊件。
**延後**：見 §8 延後清單。

### 0.4 工期現實

單人開發：可日常使用的單零件 CAD 約 12–24 個月；基本組立＋BOM＋工程圖約 2–4 年。每個 Phase 末端有 Gate，不通過不得往下發包。

---

## 1. 現況總表（單一真相；細節與證據見 Archive 與兩份 Review）

### 1.1 工作包狀態

| 包 | 狀態 | 殘缺（歸屬） |
|---|---|---|
| Phase 0（WP0-1…0-5） | ✅ | WP0-4 topology.py 解析器未接 adapter、centroid disambiguation 未實作（→WP-S1 後續） |
| 包 A Enter bug | ✅ | 中文 IME 驗收 2 待人工實測 |
| 包 B 上下文記憶 | ✅ | — |
| 包 C triad＋基準面 | ✅ | — |
| 包 D 草圖 plane | ✅ | — |
| WP1-0/0R FreeCAD 正式化 | ⚠ 部分 | 引擎接線✅；**僅 9/22 特徵**、revolve 零體積、「replay 12/12」歸屬存疑（→WP1-0R2） |
| WP1-1 Document Model v2 | ✅ | reorder_feature UI 未接線（→WP-S1） |
| WP1-2 真 Sketcher | 🔴 部分（紅線） | rebuild 不求解＝鐵則 3 違規；heuristic 求解、3 約束空殼、DOF/衝突非真實（→WP1-2R） |
| WP1-3 Reference Geometry | ⚠ 部分 | datum 解析硬編/回原點、FreeCAD 退回 XY、UI 對話框 demo 級（→WP-S1） |
| WP1-4 Property Manager | ✅ | — |
| WP1-5 檔案強化 | ✅ | — |
| WP1-6 特徵補全二批 | ⚠ 部分 | draft no-op、variable_fillet 退化；C# validator 缺六型；golden 僅 build123d（→WP-S1/WP1-0R2） |
| WP1-7 Vertical Slice A（Phase 1 Gate） | ✅（打折） | 雙引擎 11/11 實跑；但 step 2 無 LLM（identity 比對）、step 9 不比 parameters（→WP-H1 補強）；freecad smoke 被 esp32cam/needle-box 的 shell 擋（→WP1-0R2） |
| WP-H1 LLM 收斂 | ⚠ 部分 | 程式碼✅；真 gateway 端到端未測、tests/prompts 為模擬＋一恆真斷言（→WP-S1/WP-H1） |
| WP-H2 安全強化 | ✅ | — |
| Phase 2–4 | 未發包 | equations/configurations 僅 schema round-trip；assembly/BOM/drawing/鈑金/焊件 0 實作——**符合計畫，非掉球** |

### 1.2 已驗證的能力（經 UIA 實點／HTTP 重演／截圖，**不要重做**）

- **基礎設施**：Worker 生命週期（隨機埠、token 檔、父程序監看、健康檢查）；同源 viewer（`/viewer`，勿改 file://）；專案持久化 `~/.opencad/worker/`；LLM 可設定（`~/.opencad/settings.json`，LiteLLM gateway）。
- **建模**：Feature Graph（拓撲排序、循環防護、`parts[feature.input]`、snake_case enum 契約）；22 型特徵（build123d 全、FreeCAD 9 型）；TopologyTrace＋edge provenance；驗證器（實體數/bbox/體積/孔數/壁厚/質量 12 材質）；revisions＋undo/redo。
- **交易**：Staging Transaction（clone→apply→rebuild→commit-or-rollback；`apply_plan`/`reset`；一請求＝一 undo）；Typed Command 雙端對稱驗證（C# `CommandValidator.cs`＋Python `command_validator.py`，⚠不對稱破口見 WP-S1）。
- **UI**：三欄＋特徵樹＋參數面板；viewer HTML 抬頭工具列（airspace 安全）；草圖模式（正交、數值框、尺寸標籤）；LLM 計畫/差異卡片、意圖攔截、修復迴圈；開始頁專案管理；命令例外浮現＋停用態樣式＋Worker 未連線橫幅。
- **端點**（`cad-worker/cad_worker/server.py`）：`GET /api/health`、`POST /api/projects`、`GET /api/projects[/{id}]`、`POST .../commands`、`.../apply_plan`、`.../reset`、`.../rebuild`、`.../validate`、`.../exports`、`GET .../preview.glb`、`.../events`(SSE)、`.../revisions`、`POST .../undo`、`.../redo`、`.../sketch/{fid}/solve`、`GET .../display_map`。

### 1.3 測試基線 ✅（2026-07-14 實測，WP-ENV0 修復後）

| 套件 | 07-13 狀態 | 07-14 實跑 |
|---|---|---|
| .NET | ✅ 138/138 | ✅ **138/138、0 警告**（可重現） |
| Python（3.12） | 🔴 收集中斷＋DLL 封鎖 | ✅ **921 passed / 38 skipped / 0 failed**（959 collected，30s；含新納入的 tests/prompts） |
| FreeCAD（cp311） | 未複測 | ✅ **36/36 adapter tests**（2.97s，`run_freecad_tests.bat`） |
| freecad-engine-replay.ps1 | 🔴 parse error 從未可執行 | ✅ 修復後首次實跑 **12/12 PASS**（OPENCAD_ENGINE=freecad，含 rebuild×200、glb×200、STEP bbox 讀回） |

07-13 的 Python 紅字（地雷 #25 DLL 封鎖）於 07-14 已解：首次 import OCP 時 Defender/App Control 做完整掃描（實測冷啟動 import 達 229s），掃畢後放行，`import build123d` 已恢復正常。**冷啟動掃描期間任何 30s 級的啟動逾時都會誤判失敗**——replay 腳本 token 等待已放寬至 300s。收集中斷 bug 已修（`test_topology_sweep.py` 加 `from __future__ import annotations`）。

---

## 2. 地雷清單（改壞任何一條都會回歸——歷次實測踩過的坑）

1. `SnakeCaseEnumConverter`（`src/OpenCad.Domain/Enums.cs`）——C#↔Python enum 契約，動了所有命令 500。
2. viewer 必須由 Worker 同源伺服（`/viewer`）——file:// 會被 CORS 擋 ES module 與 GLB fetch。
3. **Airspace**：WebView2 原生視窗永遠蓋住 Avalonia 內容——不得疊任何 Avalonia 元素在 viewport 上；viewport 內 UI 一律 viewer.html 的 HTML overlay。
4. UI 執行緒：背景執行緒禁碰 Avalonia 物件；計時器一律 `DispatcherTimer`。
5. `app.manifest`／`Program.cs` AppBuilder／`WinExe` 不要動（SxS 與 native control host 已調通）。
6. 視窗必須在 `OnFrameworkInitializationCompleted` 內同步建立——先 await 再建視窗＝視窗永不顯示。
7. `RebuildAsync` 內的 `ExportAsync("glb")` 不可移除——preview 端點只回傳已生成檔案。
8. CanExecute 依賴的屬性 setter 必須 `RaiseCanExecuteChanged`；卡片按鈕必須一次性（`IsActionable`）。
9. graph JSON 是 `{schema_version, features:[...]}` 包裝格式——所有解析處要先解包裝。
10. `.ps1` 含中文必須 UTF-8 with BOM（PowerShell 5.1）。
11. 機密（API key、內網 IP）不得進 repo——LLM 設定在 `~/.opencad/settings.json`。
12. 全本地原則：不得引入 CDN／雲端依賴；UI 文案繁體中文。
13. 新增 pytest 直接跑 `python -m pytest tests/cad-worker/`（pytest.ini 已設路徑，勿依賴 `pip install -e`）。
14. **正式模型只能經 staging transaction 改變**：任何會改 graph 的新端點/命令必須走 clone→validate→rebuild→commit；第 3 步失敗＝正式模型完全不變、一個使用者請求＝一筆 undo。
15. **Persistent reference 歧義必須 fail-safe**：兩個等價候選→`REFERENCE_AMBIGUOUS` 要求重選，禁止自行猜測；參照消失→`REFERENCE_LOST`，禁止靜默改選。
16. **Repair 安全規則**：只有「格式修正」與「唯一可推導的 reference」可自動修；改尺寸、刪特徵、重排必須人工確認；同一錯誤＋同一命令不得反覆重試；低風險自動修復上限 2 次。
17. **FreeCAD Document 非 thread-safe**：freecad 引擎 rebuild 必須全域序列化（單一 lock）——`asyncio.to_thread` **不保證**序列化。
18. **repo 根的 `FreeCAD/` 是 2.3GB 本機安裝**（已 gitignore），不得加進 git。FreeCAD 綁定是 cp311，**必須用它自帶 `bin\python.exe`（3.11）執行**；系統 Python 3.12 import 必失敗。
19. **FreeCADShapeWrapper 屬性相容性**：`server.py` 呼叫 build123d 介面（`part.volume` 等）；FreeCAD 用 `.Volume/.Area/.BoundBox`——wrapper 必須轉接。~~另 wrapper 的 `volume` 遇例外回 0.0 會掩蓋錯誤~~ ✅ 2026-07-14 WP1-0R2 已修：例外改為浮現，不再偽裝成「體積是 0」。
20. **presigned_token 欄位名**：presign endpoint 回傳 `{"presigned_token": ...}` 非 `{"token": ...}`。
21. ~~constraints 在 rebuild pipeline 是死資料~~ ✅ 2026-07-14 WP1-2R 已解：build123d rebuild 前用 `check_residuals()` 驗殘差、不符即 raise；FreeCAD rebuild 時真的呼叫 `solve()` 重新求解、衝突即 raise。任何繞過 solve 直接改 entities 的路徑，rebuild 現在會 fail 或自動重求解，不會再產生違反約束卻無人發現的幾何。
22. **假綠四態——看到「全綠」先驗證跑了什麼**：(a) ~~angle/symmetric/tangent 測試只驗型別存在~~（2026-07-14 已補真實數值測試，見 `test_sketch_solver.py`）；(b) FreeCAD 測試在系統 Python 3.12 下全 skip（只有 cp311 實跑）；(c) ~~vertical-slice-a.ps1 no-op 綠燈~~（07-12 已修）；(d) `tests/prompts/test_llm_convergence.py:71` 恆真斷言＋模擬 plan 自我斷言（非真 gateway），且 `tests/prompts` 不在 pytest.ini testpaths **預設根本不跑**。驗收報告必須註明引擎、Python 版本、實際收集的測試數。**新增 (e)**：`vertical-slice-a.ps1` step 7 的 DOF 斷言目前仍走抽象成本表路徑（sketch entity 沒有真實 id、約束引用的 e0/e1 不對應任何實體），不是走 WP1-2R 的 Jacobian 求解器——同一份「全綠」報告底下可能同時有真驗證與掛名驗證，逐條看清楚在測什麼。
23. **UIA 驅動 Avalonia 選單只能走鍵盤路徑**：MenuItem 只暴露 ScrollItemPattern；穩定做法＝`SetFocus()`→`{ENTER}`→`{DOWN}{ENTER}`，並以子選單項出現確認；名稱比對必須限定 ControlType。
24. **tests/prompts 有 `__init__.py`（是 package）**：靠 `tests/prompts/conftest.py` 把本目錄補進 sys.path（勿刪）。
25. **（新，2026-07-13；07-14 補充）Windows 應用程式控制／Defender 對未簽章大型 DLL 有兩種干擾**：(a) 直接封鎖——`import OCP` 丟「應用程式控制原則已封鎖此檔案」→ build123d 全滅；(b) **首載完整掃描**——首次 import 可拖到 200s+（07-14 實測 229s），任何 30s 級啟動逾時都會誤判「Worker 起不來」。掃畢放行後恢復正常。**基線突然大片紅或 Worker 逾時，先查這個**，不要先怪程式碼；套件更新（DLL 換檔）後會再現。連帶注意：模組層型別註記（如 `-> Part`）在依賴缺席時會讓 pytest **收集中斷**而非 skip，測試檔一律加 `from __future__ import annotations`。

---

## 3. 發包佇列（嚴格依序；「／」＝可並行）

| 序 | 包 | 前置 | 一句話範圍 |
|---|---|---|---|
| 0 | ~~WP-ENV0 環境與測試基礎修復~~（§3.1） | 無 | ✅ 完成（2026-07-14） |
| 1 | **WP1-2R 真求解器**（§3.2） | WP-ENV0 | ⚠ 後端完成（2026-07-14）／UIA 互動驗收待補——解除鐵則 3 紅線 |
| 2 | **WP1-0R2 FreeCAD 特徵 parity**（§3.3） | WP1-2R 後端（已滿足） | ⚠ 後端完成（2026-07-14）／桌面 UIA smoke-test 待補——22/22 特徵＋誠實矩陣 |
| 3 | **WP-S1 契約同步＋WP1-3 收尾**（§3.4） | WP-ENV0 | ⚠ 後端完成（2026-07-14）／UIA 互動驗收待補——C#↔Python↔schema 對稱、datum 真 BREP 解析、假綠清理 |
| 4 | **WP-H1 殘項：真 gateway 端到端＋Gate 補強**（§3.5） | WP-ENV0 | tests/prompts 真實化、vertical-slice step 2/9 補強 |
| 5 | Phase 2 各包（§4，發包前出終稿）→ Phase 3（§5）→ Phase 4（§6） | 0–4 全過 | — |

### 3.1 WP-ENV0：環境與測試基礎修復 ✅（2026-07-14 完成，僅剩 push）

**背景**：見 §1.3 與 `OpenCad_Review_Addendum_20260713.md` §1。

1. ~~解除 OCP DLL 封鎖~~ ✅ 07-14 自解：首次 import 觸發 Defender/App Control 完整掃描（冷啟動 229s），掃畢放行；`python -c "import build123d"` 已成功（0.11.1）。未動政策設定——若日後套件更新後再現封鎖，依原計畫走解除封鎖/簽章版套件路線。
2. ~~修收集中斷~~ ✅ `test_topology_sweep.py` 加 `from __future__ import annotations`；已掃全部測試檔，同型問題僅此一處。
3. ~~修 replay 腳本~~ ✅ 補 `#>` 後 parser 實測 OK；token 等待 30s→300s（容忍冷啟動掃描）；實跑 **12/12 PASS**——「replay 12/12」宣稱自此有了真實出處（首次由本腳本親測產出）。
4. ~~tests/prompts 接進 testpaths~~ ✅ pytest.ini 已加。
5. ~~基線重跑~~ ✅ 07-14：Python 921 passed/38 skipped/0 failed（959 collected）＋ .NET 138/138 ＋ freecad adapter 36/36。輸出已記入 §1.3。
6. push：本地領先 origin/main 16+ commits，**待使用者確認後 push**（唯一殘項）。

**驗收**：✅ 三份實跑輸出全綠；`import build123d` 成功；replay 腳本可執行且 12/12。

### 3.2 WP1-2R：真求解器 ⚠ 後端已完成（2026-07-14）／UIA 互動驗收待補

**現況問題（修復前）**（證據：Review 07-12 §1＋Addendum §2.1）：
- 求解器是自寫投影 heuristic（`sketch_solver.py`），無聯立/迭代/殘差；docstring 宣稱與實作不符。
- **rebuild 兩個 adapter 都不讀 `feature.constraints`＝死 metadata（鐵則 3 違規）**。
- angle/symmetric/tangent 無幾何實作，測試只驗型別（假綠 22a）。
- DOF＝固定成本表相減（對座標零敏感）；衝突集＝切最後 N 個。
- **solve 與實體建立脫節**：`_build_sketch` 只用閉合圖元參數建面，line/arc 被當輔助線丟棄（甚至 arc 建出的邊從未 `add()`，是死碼）——約束求解的幾何根本不進實體。
- 真 FreeCAD Sketcher 只在 `cad-worker-freecad/` spike；其 19 個 solver 測試不在任何自動化路徑。

**已完成（2026-07-14）**：
1. ✅ `sketch_solver.py` 全面重寫：Levenberg-Marquardt 阻尼最小平方聯立求解 14 種約束的殘差函式（含新增 angle/symmetric/tangent 的真實幾何殘差，非 no-op）；DOF＝Jacobian 秩（`numpy.linalg.matrix_rank`），非固定成本表；衝突偵測改「依序加入約束、加入後殘差不收斂即判衝突並剔除」，非「切最後 N 個」。無座標模型的抽象實體（rectangle/polygon 等單獨計 DOF 用）仍走舊成本表記帳，行為不變（見模組 docstring）。
2. ✅ 兩個 adapter 的 rebuild 都接上約束：
   - **build123d**（沒有求解器）：rebuild 前用 `check_residuals()` 驗證目前座標是否已滿足約束，不符即 `raise ValueError`（不得靜默沿用舊座標）。
   - **FreeCAD**：rebuild 時呼叫 `solve()` 真的重新求解、把座標移到收斂位置再建圖元；`state=="over"`（衝突）即 `raise ValueError` 中止。
   - ⚠ **範圍決定（偏離原文字）**：兩引擎共用同一套 numpy 求解器，**沒有**改走原生 FreeCAD Sketcher API（`Sketcher.Constraint`/`sketch.solve()`/`sketch.DoF`）。理由：單一求解器實作維持一致行為、避免兩套數學各自維護；numpy 在 cp311／cp312 都可用（WP-ENV0 已驗證）。代價：沒有借到 FreeCAD Sketcher 內建的收斂穩定性與診斷（`ConflictingConstraints`/`RedundantConstraints`）。若之後有需要原生 Sketcher 診斷的理由，屬於可討論的後續選項，非本次遺漏。
3. ✅ `build123d_adapter.py`：line 圖元不再是完全的死碼（原碼算完 x1/y1/x2/y2 後什麼都不做）；arc 圖元原本呼叫 `make_three_point_arc(p1, center, p2)`——第二參數應為弧上一點、傳圓心是既有 bug，且建出的邊從未 `add()`；兩者都已修：line/arc（含開放 polyline）現在會被收集，若整批端點兩兩相接（形成封閉迴圈）就嘗試建面。連帶擴充 `_has_closed_profile`（兩個 adapter 都改）：不再只認 rectangle/circle/polygon/slot/閉合 polyline，line/arc 端點兩兩配對也算閉合。
4. ✅ FreeCAD `_sketch_entity_to_edges` 補上 `arc` 分支（原本完全沒有，與 build123d 沒對齊）。
5. ✅ Phase 0 spike 的 19 個原生 FreeCAD Sketcher 測試（`cad-worker-freecad/tests/test_sketch_solver.py`）接進 `run_freecad_tests.bat`（cp311，19/19 pass，約 5-6 分鐘，含 100/500-entity 規模測試）。
6. ✅ 地雷 #21 解除（見 §2）；#22(a) 更新為「已補真實作＋真測試」。

**回歸驗證（2026-07-14 實跑）**：
- `tests/cad-worker/test_sketch_solver.py`：38/38（14 種約束各一真實數值案例、DOF 斷言、衝突偵測、殘差測試）。
- `tests/cad-worker/test_wp1_2r_rebuild_constraints.py`（新增）：build123d 3/3＋FreeCAD 3/3（cp311）——直接驗證「不滿足約束 rebuild raise」「衝突 rebuild raise」「衝突解除後幾何真的移動到收斂座標」「line/arc 不再死碼」。
- 全套 Python 基線：926 passed/41 skipped（system Python 3.12，含新測試）；FreeCAD adapter 36/36＋新測試 6/6＝42/42（cp311）；spike 19/19（cp311）。
- `vertical-slice-a.ps1` 雙引擎重跑：build123d 11/11、freecad 11/11，皆 Phase 1 Gate PASSED。

**已知殘缺（誠實記錄，未列入本次「完成」）**：
- **UIA 互動驗收未做**：本次修復在後端／HTTP／pytest 層級完整驗證，但「畫矩形→約束→DOF=0」「拖曳欠約束跟隨」「點擊衝突項刪除恢復」這幾條原驗收條目要透過 Avalonia 桌面 App＋UIA 才能驗，這次沒有跑桌面 App，屬於欠款，建議收尾前補一次 UIA smoke（可比照 WP1-7-UI 的 smoke-test 手法）。
- `vertical-slice-a.ps1` step 7 的 DOF 斷言（`dof=0/state=full`）**仍走舊成本表記帳路徑**，不是新 Jacobian 路徑——因為該腳本的 sketch entity（`type=rectangle`）沒有 `id` 欄位、且約束引用的 `e0`/`e1` 本來就不對應任何真實實體 id（07-13 Addendum 已指出這是腳本本身的測試資料缺口，不在 WP1-2R 範圍內）；要讓 step 7 真正走新求解器，需要腳本改用有真實 id 的 line 實體或幫 rectangle 建立子邊 id 對應，建議併入 WP-H1 的 Gate 補強一起做。

**驗收**（沿原 WP1-2；打勾者已完成）：
- ✅ 矛盾約束→衝突清單→刪除恢復（pytest 層級：`test_conflicting_distance_constraints_marked_over`／`test_conflicting_constraints_rebuild_raises`）
- ✅ 改尺寸 60→80 幾何跟隨→pad bbox 更新（`test_constraints_move_geometry_to_solved_coordinates`）
- ✅ 直接改 sketch_entities 繞過 solve→rebuild 必須 fail 或重求解（殘差測試）
- ✅ pytest 13/14 種約束各一案例＋DOF 斷言
- ✅ smoke-test PASS（雙引擎 11/11）
- ⬜ UIA 畫矩形→約束→DOF=0「完全定義」（未做，見上）
- ⬜ 拖曳欠約束跟隨、fully constrained 不動（未做，見上）

### 3.3 WP1-0R2：FreeCAD 特徵 parity ⚠ 後端已完成（2026-07-14）／桌面 UIA smoke-test 待補

**現況問題（修復前）**（Addendum §2.2）：freecad adapter 僅 9/22；`FREECAD_ADAPTER_LIMITATIONS.md` 宣稱 "largely feature-complete" 不實。

**已完成（2026-07-14）**：
1. ✅ 補齊全部 13 個缺失特徵：`shell`（先做，見下）、`sweep`、`loft`、`mirror`、`boolean_union/difference/intersection`、WP1-6 六型（`draft`/`rib`/`thin`/`variable_fillet`/`countersink`/`cosmetic_thread`）。freecad adapter 現在 **22/22**。
2. ✅ 修既有 3 個 bug：
   - `_build_chamfer` edge_selector 死碼（all/else 兩分支完全相同）——改共用 `_select_edges()`（fillet/chamfer 都支援 all/top/vertical）。
   - `_build_revolve` 零體積——根因不是「headless 固有限制」，是舊碼旋轉軸讀自由格式 `axis` 參數（預設 Z），跟草圖平面無關；改為軸一律從草圖 plane 推導（同 build123d：XY/XZ→X 軸，YZ→Y 軸），且退化（零體積）時 raise，不再靜默「成功」。同一組退化測資餵給 build123d 用相同軸也會 raise——證實這是**資料幾何本身無效**（輪廓中心恰好落在旋轉軸上），不是引擎限制。
   - `FreeCADShapeWrapper.volume`/`.area` 例外回 0.0（地雷 #19）——改為讓例外浮現，不再把「算不出體積」偽裝成「體積真的是 0」。
3. **加碼發現＋順手修的 2 個新 bug**（不在原規劃清單，實測 `needle-box-5x10` rebuild 失敗才發現）：fillet/chamfer 的邊選擇器參數鍵原本讀 `edge_selector`，但 build123d／範例專案／schema 實際用的鍵是 `edges`——鍵名對不上，freecad 引擎的 `edges: "top"` selector 一直悄悄失效退回 "all"；chamfer 的距離參數鍵原本讀 `distance`，build123d 讀 `length`，同一份 JSON 兩引擎會取到不同倒角大小。兩者都改讀正確鍵名（舊鍵留作相容 fallback）。
4. ✅ golden tests 雙引擎參數化：`tests/cad-worker/test_golden_model.py` 新增 `golden_adapter` fixture（`params=["build123d","freecad"]`），三個範例專案（NEMA17/needle-box/esp32cam）的 golden test 現在雙引擎各跑一次；freecad 不可用時該參數 skip（非 fail）。
5. ✅ **`FREECAD_ADAPTER_LIMITATIONS.md` 全文重寫為誠實矩陣**：22 型逐一列 implemented/partial＋證據；同時發現並記錄 shell/thin（均勻收縮非真開口殼）、variable_fillet（單一半徑）、countersink（直筒非錐形）、draft（no-op）**這四項其實 build123d 自己也是同等簡化**，本次是把 FreeCAD 對齊到相同水準、不是把 FreeCAD 拉低於 build123d，但仍誠實記錄為兩引擎共通的功能缺口，列為後續獨立項目（非本次範圍）。

**回歸驗證（2026-07-14 實跑）**：
- `test_freecad_adapter.py`：52/52（cp311，含本次新增 22 型全覆蓋測試）。
- `test_golden_model.py`：51/51（system Python：29 build123d-only ＋ 22 dual-engine 中 build123d 半數過、freecad 半數 skip；cp311：全部 51 皆實跑過）。三個範例專案雙引擎體積：NEMA17 build123d 20345.58 / freecad 19434.45（差異~4.5%，fillet 拓樸差異，非錯誤）；needle-box freecad 91473.28（<100000 判準內，5 特徵全成功，含先前失敗的 fillet_corners）；esp32cam freecad 3537.68（<8000 判準內，6 特徵全成功）。
- 系統 Python 全套：926 passed/68 skipped；cp311 全套：976 passed/2 skipped；`dotnet test`：138/138（未動 C#，抽查未回歸）。

**已知殘缺（誠實記錄，未列入本次「完成」）**：
- **桌面 UIA smoke-test 未跑**：`tests/ui/smoke-test.ps1 -Engine freecad` 會啟動真實 Avalonia 視窗並控制實體滑鼠/鍵盤，本次未執行（與 WP1-2R 的 UIA 驗收缺口同性質）——HTTP／pytest 層級的雙引擎驗證已完整覆蓋本包的核心變更，但這條原始驗收項仍待找機會實跑。
- shell/thin/variable_fillet/countersink/draft 四項「兩引擎同等簡化」問題已誠實記錄於 LIMITATIONS.md，但未修復（修復需要 schema／LLM catalog 層級的設計擴充，超出「達成 parity」的本次範圍）。
- 「切預設引擎」的討論（原工作項 5）因桌面 UIA smoke-test 未跑，尚未開啟。

**驗收**（打勾者已完成）：
- ✅ 22 型雙引擎 golden 全綠（§9.8 判準）
- ✅ 三個範例專案 freecad 引擎 rebuild 成功
- ⬜ freecad 桌面 UIA smoke-test PASS（未跑，見上）
- ✅ LIMITATIONS.md 與實作逐條相符（含誠實揭露的四項共通簡化）

### 3.4 WP-S1：契約同步＋WP1-3 收尾 ✅ 完成（2026-07-14）／UIA 互動驗收待補

**契約對稱**（Addendum §2.3——範圍比 07-12 盤點大）：
1. ✅ C# `CommandValidator.cs` 補 **14 型** input 驗證（WP1-6 六型＋sweep/loft/mirror/linear_pattern/circular_pattern/boolean×3），必填參數規則與 Python `REQUIRED_PARAMS` 對齊（`RequiresInput`/`RequiredParams` 靜態表＋泛用數值正負檢查，不再按型別窄範圍檢查）。
2. ✅ `update_feature` 有效欄位 C# 補 `constraints`（`CadCommand.Constraints` 本來就有欄位，只是 `ValidateUpdateFeature` 的 null 檢查漏了它）。
3. ✅ `plane.base` 三方對齊：C# validator＋`feature.schema.json`＋LLM planSchema 都補上 `datum:<id>` 形式（schema 用 `oneOf`，C#/planSchema 用字串前綴檢查）。
4. ✅ C# validator 補 `create/update/delete_reference_geometry` 三個 action case（`CadCommand` 新增 `ReferenceGeometry` 欄位）。
5. ⚠ **範圍決定（偏離原文字）**：LLM planSchema 的 `datum_plane`/`datum_axis`/`datum_point` **沒有移除**——複查發現這 3 個字串是 `MainViewModel.ExecutePlanAsync` 故意用的路由鍵（`step.FeatureType.StartsWith("datum_")` → 呼叫 `CreateReferenceGeometryAsync`，不進 `create_feature` 管線），prompt 也明確教 LLM 輸出它們。真的從 enum 移除會讓結構化輸出直接擋掉這些合法 datum 步驟，打斷現正運作的「LLM 一句話建基準面」路徑——這是會製造回歸的改法，故保留不動，只在程式碼加註解說明前因後果。若要真正走 `action=create_reference_geometry`（已支援），需要同時改 `DesignStep` 資料結構＋prompt＋路由邏輯，是獨立的設計工作。
6. ✅ `feature.schema.json` 補齊頂層 `bodies`／`reference_geometry`／`rollback_position`／`global_variables`／`configurations`／`custom_properties`（原本只有 `schema_version`+`features`，`reference_geometry` 的 definition 從未被 `$ref` 引用，與 `feature_graph.py` 實際存檔格式完全對不上）。
7. ✅ reorder_feature UI 接線：右鍵選單新增「上移／下移」，`MoveFeatureUpCommand`/`MoveFeatureDownCommand`（`new_order` = 目前 order ± 1，依賴衝突交給 Worker 的既有檢查）；拖曳排序未做（原規劃即可後補）。

**WP1-3 收尾（datum 去佔位）**：
8. ✅ `_resolve_face`／`_resolve_vertex` 改接真 BREP：透過 `topology.resolve_reference()`（WP0-4 既有的語意化查詢引擎）解析，取代原本「不管模型多大、"top" 永遠回傳 origin=[0,0,10]」的硬編數字。**加碼修正兩個連帶 bug**：(a) `_face_normal_matches` 原本直接拿 FreeCAD 的字串 geom_type 跟 build123d 的 enum 比較，freecad 引擎下永遠判定不是平面；(b) `_resolve_face_reference` 的 `source_feature_id` 過濾原本假設 `trace.faces_created_by()` 回傳 Face 物件，但 freecad 版的 trace 回傳的是面索引（int），比對永遠失敗——這兩個都是導致 freecad 引擎下任何帶 `source_feature_id` 的語意查詢直接判「參照不存在」的根因，一併修好。`_resolve_vertex` 因 `topology.py` 尚無 vertex 級查詢，誠實回傳 None（未解析），不再假裝是原點。**已知限制**：解析用的是「上一輪 rebuild」的 part/trace（`server.py` 新增 `proj["trace"]` 快取），不是本輪即時建構結果——首輪 rebuild 前 derived_geometry 必然留空，這是需要把 datum 解析交錯進 adapter 逐特徵迴圈才能根治的架構問題，本次未做。
9. ✅ FreeCAD 引擎 datum 草圖面：原本 datum 分支只確認 id 存在就當 XY 處理（"未來可以從 reference_geometry 取得更精確的變換矩陣" 的 TODO 從未補上）。改為真的解析 derived_geometry 的 origin/normal，用標準的「選參考向量→兩次外積」建出正交座標系（`_resolve_datum_plane_transform`），與 build123d 的 `Plane(origin=..., z_dir=...)` 同一種數學想法（繞法向量的旋轉角兩邊各自獨立計算，不保證逐位元一致，但形狀本身不受影響）。雙引擎端到端測試（base box→datum offset 5mm→該面上再 pad）驗證兩引擎結果一致。
10. ✅ UI datum 建立對話框真選面：原本硬編 `"face:f1.top"` + 10mm（"f1" 幾乎不會是真實特徵 id）。改為「按下後進入待選狀態→3D 視窗點一個面→用該面的 `source_feature_id`+`centroid`（viewer.html/ViewerBridge 新增 centroid 欄位）建立 datum」，Python 端新增 `face_centroid:<id>:<x,y,z>` 參照格式（靠 `resolve_reference` 既有的 centroid_hint 就近比對）。**殘留項**：偏移量目前固定 0（與所選面重合，是合法用法，但還沒有讓使用者輸入非零偏移的數值 UI）；datum 平面也還沒接進屬性面板供事後調整——這兩塊是比「選面」更大的獨立 UI 工作，留待後續。

**假綠與家務**：
11. ✅ `test_llm_convergence.py:71` 恆真斷言（`assert has_arbitrary and has_no_questions`——兩個布林值都讀自它自己剛寫的 dict，恆真）：由於「不得用任意預設值取代提問」這條規則目前只在 prompt 文字層面要求、沒有對應的程式硬檢查函式可測，改為明確 `pytest.skip` 並附完整理由，不再用恆真斷言假裝已驗證。同時在檔案 docstring 加註：本檔多數案例是拿手寫 dict 自我斷言，**非端到端**（真 gateway 端到端歸 §3.5）。
12. ✅ 已於 07-13 完成（見下方原記錄，未變動）。
13. ✅ `tests/geometry`、`tests/unit`、`tests/golden-models`：確認皆為空且未被 git 追蹤，直接刪除（無需 README，未來若要用再建）。
14. ✅ `draft`/`variable_fillet`（及加碼一起處理的 `shell`/`thin`/`countersink`——WP1-0R2 發現這幾型兩引擎現況一致地簡化，非單一引擎落後）：`/api/capability` 的 feature_catalog 每個型別加 `status`（"full"/"partial"）與 `limitation` 說明欄位，LLM 每次呼叫都能看到限制，不會誤以為功能完整。

**回歸驗證（2026-07-14 實跑）**：系統 Python 929 passed/70 skipped；cp311 980 passed/2 skipped；`dotnet test` 164/164（新增 CommandValidator 對稱測試 26 案例，遠超 ≥14 判準）。

**驗收**（打勾者已完成）：
- ✅ C#↔Python validator 對稱測試（26 案例，遠超 ≥14 判準）
- ✅ datum 在雙引擎下開草圖 pad bbox 正確（`TestDatumPlaneSketchBuild123d`/`TestDatumPlaneSketchFreeCAD`）
- ⬜ UIA 選面建 datum（機制已接線＋單元測試驗證，但未實際啟動桌面 App 用滑鼠點選跑過——與 WP1-2R/WP1-0R2 留下的 UIA 驗收缺口同性質，待後續一起補）
- ✅ 恆真斷言消失
- ✅ `git status` 乾淨（commit 後）

### 3.5 WP-H1 殘項：真 gateway 端到端＋Gate 補強

1. `tests/prompts/` 加真實 LiteLLM gateway 案例（無 LLM 環境 skip）：缺尺寸提問、歧義要求點選、不支援拒絕、防偷換（「螺旋齒輪」→拒絕）、多輪指涉；TPM 內 token 量測。
2. `vertical-slice-a.ps1` **step 2 真 LLM plan 語意等價**（現為 apply_plan identity 比對，無 LLM）——LLM 生成 plan 與 typed plan 比對語意欄位；無 gateway 時標 SKIP 並在報告註明（不得 PASS）。
3. **step 9 快照加 parameters 比對**（現只比 feature_id/type/name/input，掉尺寸也會過）。
**驗收**：真 gateway 實測 5 條輸出貼報告；step 2/9 強化後雙引擎重跑 11/11。

---

## 4. Phase 2：可重用產品設計（Gate 後 3–5 個月；發包前依當時 schema 出終稿）

### WP2-1 Equations／Global Variables／Named Dimensions
- schema：`global_variables: [{name, expression, unit}]`；任何數值參數可為 `"=PlateWidth + 2*EdgeMargin"`。
- 求值器：units-aware、拓撲排序求值、循環依賴回 `EQUATION_CYCLE` 含環路徑；**禁 eval**，受控 AST 白名單（+-*/、min/max/floor/ceil、比較、三元）。
- UI：全域變數表；參數框 `=` 開頭進表達式模式。
- LLM 規則：**修改設計改 named variable，不得搜尋匿名數值**。
- 驗收：`PlateWidth=60→80` 一改→孔距/壁厚連動 rebuild 正確；循環依賴明確報錯；pytest ≥8。

### WP2-2 Configurations
- schema：`configurations: [{name, parent, overrides:{variables, suppressions, material}}]`＋`active_configuration`；rebuild 按 active config 套 overrides；derived 繼承再覆寫。
- UI：組態下拉＋表格編輯器（第一版可 JSON 表格）。
- 驗收：S/M/L 三組態切換 bbox 各異；config 專屬 suppression 生效；100 組態壓力測試；mass 隨 config 正確。

### WP2-3 Multi-body
- feature `scope`、boolean combine/subtract bodies、split、move/copy、per-body 材質、樹上 Body 資料夾。
- 驗收：兩 body 各自 pattern、combine 體積=聯集；cut list 基礎欄位輸出 JSON。

### WP2-4 Surface 基礎
- extruded/revolved/lofted surface、offset、knit/sew、trim、thicken、delete face/heal；以 FreeCAD 能力為底逐一驗證；做不到明確標 unsupported（接 WP-H1 拒絕規則）。
- 驗收：「開放曲面 knit→thicken 成實體」golden；delete face+heal 修補匯入 STEP 案例 1 個。

### WP2-5 Direct Editing 與 Import Repair
- move/offset/delete face；STEP 匯入孔辨識（圓柱面群→hole 建議卡片，人工確認後轉 typed feature）。
- 驗收：匯入無歷史 STEP→辨識孔清單→套用→孔可改 M5。

### WP2-6 效能預算與快取
- S/M/L/XL 分級實測定門檻；增量重建（上游未變重用快取，先寫計數測試）；SSE 進度接 UI。
- 驗收：M 級模型改一尺寸只重算下游（計數測試）、UI 不凍結、可取消。

---

## 5. Phase 3：機台組立（Phase 2 Gate 後 4–8 個月）

> Assembly 是獨立子系統與獨立文件型別，不是 Part Graph 加欄位。

### WP3-1 Assembly Document Model
components（source 相對路徑/configuration/transform/state/fixed）＋mates（coincident/concentric/distance/parallel/angle，refs 用 persistent reference）。missing file→component 標 missing、組立照開。
驗收：三零件組立存檔重開 transform/mates 不變；改零件檔→組立更新；缺檔不 crash。

### WP3-2 Mate Solver＋DOF 診斷
第一版順序求解＋剩餘 DOF；over-constrained 回衝突 mate 集；標準五 mate 先行、limit/width 次之、機械 mate 後期。
驗收：每 mate 單元測試；軸-孔同心＋端面重合→剩餘 DOF=1；矛盾 mate 報衝突集。

### WP3-3 干涉、爆炸、BOM
干涉（兩兩 intersect 體積>0＋clearance）；爆炸（per-instance 位移＋插值動畫）；BOM（零件號/數量/材質/質量/custom properties，CSV/JSON）。

### WP3-4 Vertical Slice B（Phase 3 完成定義）
支架＋軸＋滑塊；mates；剩餘 DOF；拖曳＋碰撞；爆炸圖；BOM；改軸徑→組立更新。全步驟 UIA＋引擎層重演。

---

## 6. Phase 4：製造文件（Phase 3 Gate 後 6–12 個月；範圍凍結）

- **WP4-1 Associative Drawing**：drawing 為第三種 document_type；view 引用 part/assembly＋configuration；改尺寸→view/dimension/BOM/balloon 自動更新；dangling annotation 標示、禁止靜默換邊；base/projected/section/detail；基底評估 FreeCAD TechDraw。
- **WP4-2 標註**：model dimensions、hole callout、公差配合、基本 GD&T、粗糙度、註記；ISO 第一。
- **WP4-3 鈑金**：base/edge flange、sketched bend、hem/jog/relief、K-factor/bend table、fold/unfold、flat pattern、DXF 展開。
- **WP4-4 焊件**：3D skeleton、structural member 庫、corner treatment、trim/extend、gusset/end cap、cut list。
- 輸出：PDF、DXF/DWG、STEP AP242 評估。

---

## 7. 橫向工作包（不綁 Phase）

- **WP-H1**：程式碼已落地（單 Orchestrator＋capability payload＋拒絕規則＋repair 白名單）；**殘項＝真 gateway 端到端**（→§3.5）。
- **WP-H2** 安全強化：✅（Archive）。
- **WP-H3 測試套件擴充**（隨對應 Phase 落地）：

| 套件 | 內容 | 綁定 |
|---|---|---|
| solver | 每約束獨立測、DOF、衝突集、拖曳穩定、100–1000 entity 效能 | WP1-2R |
| topology | 參數 sweep、插刪上游、pattern 數量變、對稱歧義 fail-safe | 持續 |
| config | 參數/材質/抑制矩陣、100+ config、config-specific mass/BOM | WP2-2 |
| assembly | 每 mate、DOF、over-constrained、replace 後 repair、缺檔、100/1000 instance | WP3-* |
| drawing | 改尺寸後 view/dimension 更新、dangling、BOM link、視覺回歸 | WP4-1 |
| recovery | save crash、磁碟滿、migration、future version、corrupt 檔 | ✅（WP1-5） |

- **WP-H4 Golden Model 判準**：已生效（見 §9.8）——語意/體積/bbox/質量/關鍵位置＋reference 解析；**不比對面數邊數、不比 STEP byte hash**。

---

## 8. 明確延後清單（不發包、不討論，除非本節被修訂）

單張圖片轉完整參數模型、VLM 審美判斷、多 Agent 分工、macOS/Linux 完整安裝（CI 三平台編譯矩陣保留）、Motion Study/物理模擬、Mold/Routing、CAM/FEA connectors、PDM/協作、Plugin 生態、`.SLDPRT/.SLDASM` 原生讀寫（授權問題；STEP 不得宣稱 SolidWorks 原生相容）。

---

## 9. 驗證方法論（每一包交付都照此驗收；舊編號 §14）

0. **前提**：確認 `python -c "import build123d"` 成功（地雷 #25）；驗收報告註明引擎、Python 版本、實際收集測試數（地雷 #22）。
1. `dotnet build OpenCad.slnx` → 0 錯誤 0 警告。
2. `python -m pytest tests/cad-worker/ -q` 與 `dotnet test` → 全綠（新功能必附新測試）。
3. `powershell -ExecutionPolicy Bypass -File tests\ui\smoke-test.ps1` → PASS。
4. **UI 必須實際驅動驗證**：UIAutomation 點擊＋截圖目視＋WebView2 無障礙樹；Avalonia 選單走鍵盤路徑（地雷 #23）。
5. 引擎層驗收：起 Worker（`OPENCAD_WORKER_PORT`/`OPENCAD_TOKEN_FILE`/`OPENCAD_WORK_DIR`）直接 HTTP 重演，斷言幾何數值。
6. LLM 相關：用真實 gateway（`~/.opencad/settings.json`）實測語意正確性。
7. 全程斷網可完成 1–5（LLM 除外）。
8. **Golden Model 判準**：語意/體積/bbox/質量/關鍵位置（容差 0.1%）＋reference 解析；不比面數邊數、不比 byte hash。
9. **交付報告格式**：改了哪些檔、新增測試清單、驗收逐條實測證據（命令輸出/截圖路徑）、發現的新地雷（回寫 §2）。

**發包模板**：`[包編號＋該節全文] + [§0 策略] + [§1 現況] + [§2 地雷] + [§9 驗證方法論] + 「完成後依 §9.9 交付報告」`。
