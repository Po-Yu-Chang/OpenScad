# FreeCAD Adapter 誠實矩陣

> 2026-07-14（WP1-0R2）全文重寫。舊版宣稱「largely feature-complete」且
> Loft/Sweep 標「✅ Complete」——但這兩型當時根本不存在（freecad adapter
> 只有 9/22 型），是誤導性文件。本版逐特徵列出實測狀態＋證據，不再用
> 籠統的「Complete/Limited」字樣。

## 特徵矩陣（22 型全部）

| # | 特徵型別 | 狀態 | 說明／已知簡化 | 證據 |
|---|---|---|---|---|
| 1 | sketch | ✅ implemented | rectangle/circle/polygon/slot/polyline/line/arc 全支援；含 constraints 求解（WP1-2R） | `freecad_adapter.py:_build_sketch` |
| 2 | pad | ✅ implemented | | `_build_pad` |
| 3 | pocket | ✅ implemented | | `_build_pocket` |
| 4 | hole | ✅ implemented | | `_build_hole` |
| 5 | revolve | ✅ implemented | WP1-0R2 修復：旋轉軸原本讀自由格式 "axis" 參數（預設 Z），與草圖平面無關，輪廓在該軸上不掃體積，OCC 靜默回傳零體積——改為軸一律從草圖 plane 推導（同 build123d：XY/XZ→X 軸，YZ→Y 軸），且退化（零體積）時 raise，不再靜默「成功」 | `_build_revolve`；`test_revolve_circle_360`／`test_revolve_degenerate_profile_raises` |
| 6 | sweep | ✅ implemented（WP1-0R2 新增） | 路徑草圖用 `_sketch_entity_to_edges` 直接重建（開放輪廓不會進 shapes dict） | `_build_sweep`；`TestFreeCADAdapterSweep` |
| 7 | loft | ✅ implemented（WP1-0R2 新增） | 用 `Part.makeLoft`，輪廓取 `OuterWire` | `_build_loft`；`TestFreeCADAdapterLoft` |
| 8 | linear_pattern | ✅ implemented | | `_build_linear_pattern` |
| 9 | circular_pattern | ✅ implemented | | `_build_circular_pattern` |
| 10 | mirror | ✅ implemented（WP1-0R2 新增） | 固定鏡射面 XZ（法向 Y），與 build123d adapter 對齊；結果 fuse 回原體 | `_build_mirror`；`TestFreeCADAdapterMirror` |
| 11 | fillet | ✅ implemented | WP1-0R2 修復：邊選擇器參數鍵原本讀 `edge_selector`，但範例專案／build123d 實際用 `edges`——鍵名對不上，freecad 引擎悄悄退回 "all"，對複雜幾何用小半徑對所有邊導圓角會失敗（`needle-box-5x10` 的 `fillet_corners` 曾因此失敗）。已改讀 `edges`（`edge_selector` 留作相容 fallback） | `_build_fillet`／`_select_edges` |
| 12 | chamfer | ✅ implemented | WP1-0R2 修復兩處：(a) 同 fillet 的 `edges`/`edge_selector` 鍵名問題；(b) 倒角距離鍵原本讀 `distance`，build123d 讀 `length`，同一份 JSON 餵兩引擎會取到不同大小——改讀 `length`（`distance` 留作相容 fallback）；(c) `edge_selector` 原本 all/else 兩分支完全相同（死碼），已修 | `_build_chamfer`；`test_chamfer_edge_selector_actually_selects` |
| 13 | shell | ⚠️ partial（WP1-0R2 新增，與 build123d 同等簡化，非 FreeCAD 特有落後） | **兩引擎目前都只是整個實體均勻向內收縮（3D offset/erosion），不是真正挖空、有開口的中空殼**——schema 的 `shell` 只有 `thickness` 參數，沒有「選面開口」參數，makeThickness/offset 這類 API 若不指定要移除的面，就只能做均勻收縮，無法產生有內壁、有開口的實用殼件。build123d 端 `offset(part, amount=-thickness)` 現況就是這樣（實測：32×45×7.5 盒子 thickness=2 兩引擎都得到 4018mm³，等同 (28)(41)(3.5) 的縮小實心塊，不是中空殼）。要做出真正的殼，需要新增開口面選擇器參數（schema＋LLM catalog＋兩引擎都要改），這是設計層級的擴充，本次僅完成 FreeCAD 與 build123d 現狀對齊，未新增開口面能力 | `_build_shell`；`TestFreeCADAdapterShell` |
| 14 | boolean_union | ✅ implemented（WP1-0R2 新增） | `shape.fuse()` | `_build_boolean_union` |
| 15 | boolean_difference | ✅ implemented（WP1-0R2 新增） | `shape.cut()` | `_build_boolean_difference` |
| 16 | boolean_intersection | ✅ implemented（WP1-0R2 新增） | FreeCAD 的交集方法叫 `common()`（不是 `intersect`），已對應 | `_build_boolean_intersection` |
| 17 | draft | ⚠️ partial（WP1-0R2 新增，與 build123d 同等簡化） | **no-op passthrough**——不改變幾何。完整拔模需要面選取＋拔模方向向量，超出目前 display_map 選面能力；build123d adapter 自己也是同樣的 no-op（含 `# TODO: 完整拔模實作待 WP2 補強`），FreeCAD 對齊現狀而非落後 | `_build_draft`；`test_draft_is_noop_passthrough` |
| 18 | rib | ✅ implemented（WP1-0R2 新增） | 輪廓拉伸＋fuse，支援 symmetric/reverse/normal 三種 direction，與 build123d 對齊 | `_build_rib`；`test_rib_symmetric_adds_volume` |
| 19 | thin | ⚠️ partial（WP1-0R2 新增，繼承 shell 的已知限制） | 拉伸後呼叫與 `shell` 相同的均勻收縮邏輯，因此也不是「真正薄殼」，限制同上表第 13 項 | `_build_thin`；`test_thin_extrudes_then_shells` |
| 20 | variable_fillet | ⚠️ partial（WP1-0R2 新增，與 build123d 同等簡化） | **實際上是單一半徑**（取 `radii[0]`），不是逐點真正變化的圓角——build123d adapter 自己也只用 `radii[0]`（`r1 = radii[-1]` 算出來但從未使用），FreeCAD 對齊現狀 | `_build_variable_fillet`；`test_variable_fillet_uses_first_radius` |
| 21 | countersink | ⚠️ partial（WP1-0R2 新增，與 build123d 同等簡化） | **沉頭部分用直筒圓柱模擬，不是真正的錐形**——build123d adapter 雖然算了 `countersink_angle_deg` 對應的深度，但建幾何時仍用 `Cylinder`（不是 Cone），FreeCAD 對齊同一套簡化。兩引擎都需要之後補真錐形（`Part.makeCone`／build123d 的圓錐 API） | `_build_countersink`；`test_countersink_removes_material` |
| 22 | cosmetic_thread | ⚠️ partial（WP1-0R2 新增，與 build123d 同等簡化） | 不改變幾何，回傳 `None`——僅供顯示／標記用途，與 build123d adapter 完全一致 | `_build_cosmetic_thread`；`test_cosmetic_thread_returns_none_keeps_upstream` |

## 已知限制（非 FreeCAD 特有——兩引擎共通，本次一併發現並誠實記錄）

以下三項原本被記錄成「build123d 完整、FreeCAD 落後」，但實測發現 build123d 自己也是同等簡化，本次只是把 FreeCAD 對齊到相同（有限）水準，不是把 FreeCAD 拉到落後於 build123d：

1. **shell/thin 不是真正的中空殼**（只是均勻收縮）——schema 缺開口面選擇器，兩引擎皆然。
2. **variable_fillet 不是真正變化圓角**（只用第一個半徑）——兩引擎皆然。
3. **countersink 的沉頭是直筒不是錐形**——兩引擎皆然。
4. **draft 是 no-op**——兩引擎皆然，build123d 原碼自己標了 TODO。

這四項都是「兩引擎目前功能一致地簡化」，不是 parity 落差，但仍是對使用者/LLM 的誠實度問題（功能名稱暗示的能力比實際做到的多）。建議後續獨立立項（非本次 WP1-0R2 範圍）：
- 幫 `shell`/`thin` 加開口面選擇器參數，做出真正可用的殼件。
- `variable_fillet` 改成逐點真正變化半徑（FreeCAD `makeFillet` 原生支援 per-edge 多點半徑；build123d 端需要另尋 API 或用多次 fillet 疊代逼近）。
- `countersink` 改用真正的圓錐（`Part.makeCone`／build123d `Cone`）取代直筒圓柱。

## 三個範例專案驗證（2026-07-14 實測，雙引擎）

| 範例 | build123d 體積 | FreeCAD 體積 | 差異 | 說明 |
|---|---|---|---|---|
| `nema17-mount` | 20345.58 mm³ | 19434.45 mm³ | ~4.5% | 差異來自兩引擎 fillet 邊選取／拓樸細節不同，非錯誤（WP-H4 判準：只比對體積範圍，不比對面/邊數） |
| `needle-box-5x10` | <100000 mm³（golden test 範圍） | 91473.28 mm³ | — | shell（均勻收縮，見上）＋pocket cell grid＋fillet，全 5 個特徵皆成功 |
| `esp32cam-enclosure` | <8000 mm³（golden test 範圍） | 3537.68 mm³ | — | shell＋3 組 hole，全 6 個特徵皆成功 |

三個範例在兩個引擎下所有特徵 `rebuild_status == "success"`，體積落在對應 golden test 判準範圍內。測試見 `tests/cad-worker/test_golden_model.py`（`golden_adapter` fixture，`params=["build123d","freecad"]`）。

## 測試策略（現況）

- `tests/cad-worker/test_freecad_adapter.py`：cp311 專屬單元測試，52 個（含本次新增 22 型全覆蓋）。
- `tests/cad-worker/test_golden_model.py`：雙引擎參數化（`golden_adapter` fixture），系統 Python 下 freecad 參數自動 skip（非 fail）。
- `run_freecad_tests.bat`：一鍵跑 cp311 adapter 測試＋Phase 0 spike 的 19 個原生 FreeCAD Sketcher 測試。
