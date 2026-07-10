"""build123d Adapter — 將 Feature Graph 轉譯為 build123d 建模命令。

此 Adapter 是引擎中立架構的一部份：
  - 特徵只描述意圖與參數（Feature Graph）
  - Adapter 負責轉譯（build123d）
  - 同一組 Feature Graph 可由不同 Adapter 轉譯（如 freecad_adapter）

注意：build123d 沒有草圖約束求解器。
約束以宣告式中繼資料保存在 Feature Graph，幾何由參數直接計算。
約束僅用於「重建後驗證是否仍成立」。
"""

from __future__ import annotations

import math
from typing import Any

_BUILD123D_IMPORT_ERROR: str | None = None

try:
    from build123d import (
        BuildPart, BuildSketch, Compound, Part, Sketch,
        Plane, Polyline, Rectangle, Circle, RegularPolygon, SlotOverall,
        Pos, Mode, Axis, Vector, Edge, Wire,
        extrude, revolve, sweep, loft, fillet, chamfer, mirror,
        Cylinder, Box, Hole, CounterBoreHole,
        Locations, GridLocations,
        offset, make_face, add,
    )
    BUILD123D_AVAILABLE = True
except ImportError as _e:
    BUILD123D_AVAILABLE = False
    Part = None  # type: ignore
    _BUILD123D_IMPORT_ERROR = str(_e)

from ..feature_graph import FeatureGraph, Feature, FeatureType, ParameterValue
from ..standard_parts import get_clearance_hole_diameter, get_counterbore_dimensions, get_nema_mounting


class TopologyTrace:
    """記錄重建期間每個特徵建立或修改了哪些邊。

    用於語意化選邊——例如 fillet 可以排除「由 hole 建立的邊」。
    topology handle 只在同一次 rebuild 中有效，不跨版本持久化。
    """

    def __init__(self) -> None:
        # feature_id -> set of edge 物件（build123d Edge）
        self._created_by: dict[str, set] = {}
        # feature_id -> set of edge 物件（fillet/chamfer 選中的邊）
        self._selected_by: dict[str, set] = {}

    def record_created(self, feature_id: str, before_edges: set, after_edges: set) -> None:
        """記錄某特徵新增或修改的邊（after - before）。"""
        new_edges = after_edges - before_edges
        if feature_id not in self._created_by:
            self._created_by[feature_id] = set()
        self._created_by[feature_id].update(new_edges)

    def record_selected(self, feature_id: str, edges: list) -> None:
        """記錄 fillet/chamfer 選中的邊。"""
        self._selected_by[feature_id] = set(edges)

    def created_by(self, feature_id: str) -> set:
        """取得某特徵建立的邊集合。"""
        return self._created_by.get(feature_id, set())

    def selected_by(self, feature_id: str) -> set:
        """取得某特徵選中的邊集合。"""
        return self._selected_by.get(feature_id, set())

    def get_all_created_edges(self) -> set:
        """取得所有特徵建立的邊集合（聯集）。"""
        all_edges: set = set()
        for edges in self._created_by.values():
            all_edges.update(edges)
        return all_edges

    def to_summary(self) -> dict[str, Any]:
        """產生可序列化的摘要（不含 edge 物件）。"""
        return {
            "created_by": {fid: len(edges) for fid, edges in self._created_by.items()},
            "selected_by": {fid: len(edges) for fid, edges in self._selected_by.items()},
        }


def _snapshot_edges(part: Any) -> set:
    """取得 part 的所有邊的快照（用於 before/after diff）。"""
    try:
        return set(part.edges())
    except Exception:
        return set()


def filter_by_axis(edges: list, axis: Any) -> list:
    """篩選平行於指定軸的邊。"""
    try:
        from build123d import Edge
        result = []
        for e in edges:
            try:
                # 檢查邊的方向是否平行於指定軸
                if hasattr(e, "direction"):
                    d = e.direction
                    if (abs(d.X - axis.direction.X) < 0.01 and
                            abs(d.Y - axis.direction.Y) < 0.01 and
                            abs(d.Z - axis.direction.Z) < 0.01):
                        result.append(e)
            except Exception:
                pass
        return result
    except Exception:
        return edges


class Build123dAdapter:
    """將 Feature Graph 轉譯成 build123d 建模命令的 Adapter。"""

    def __init__(self) -> None:
        if not BUILD123D_AVAILABLE:
            raise ImportError(
                f"build123d 匯入失敗: {_BUILD123D_IMPORT_ERROR or '未知原因'}。"
                f"請執行: pip install build123d"
            )

    def build(self, graph: FeatureGraph) -> "Part":
        """依拓撲排序重建整個 Feature Graph，回傳最終實體。

        每個特徵從自己宣告的 input 取得精確輸入，不使用全域 current_solid。
        這確保 Feature Graph 的依賴關係與實際執行順序一致。

        回傳 BuildResult，包含 shape 與 topology trace（用於語意化選邊）。
        """
        order = graph.topological_sort()
        parts: dict[str, Part] = {}
        trace = TopologyTrace()  # 記錄每個特徵建立/修改了哪些邊

        for fid in order:
            feature = graph.get_feature(fid)
            if feature is None:
                continue
            feature.rebuild_status = "building"
            try:
                result = self._build_feature(feature, parts, graph, trace)
                if result is not None:
                    parts[fid] = result
                feature.rebuild_status = "success"
                feature.error_message = ""
            except Exception as e:
                feature.rebuild_status = "failed"
                feature.error_message = str(e)
                raise

        # 回傳最後一個產生實體的特徵結果（以拓撲排序最後者為準）
        final_part = None
        for fid in reversed(order):
            if fid in parts:
                final_part = parts[fid]
                break
        return final_part

    def _build_feature(
        self,
        feature: Feature,
        parts: dict[str, "Part"],
        graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """根據特徵類型分派到對應的建構方法。"""
        method = getattr(self, f"_build_{feature.type.value}", None)
        if method is None:
            raise ValueError(f"不支援的特徵類型: {feature.type}")
        return method(feature, parts, graph, trace)

    def _get_param(self, feature: Feature, key: str, default: float = 0.0) -> float:
        """從特徵參數取得數值，自動換算為 mm。"""
        val = feature.parameters.get(key, default)
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _build_sketch(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """建立草圖。build123d 的草圖由參數直接計算位置。

        依 plane 欄位選擇基準面（XY/XZ/YZ）與偏移量。
        若草圖沒有閉合輪廓（僅線段/弧），回傳 None 而非崩潰。
        """
        plane_base = feature.plane.get("base", "XY")
        plane_offset = self._raw_mm(feature.plane.get("offset", 0))

        plane_map = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}
        base = plane_map.get(plane_base, Plane.XY)
        work_plane = base.offset(plane_offset) if plane_offset else base

        # 檢查是否有閉合輪廓；若無，回傳 None（不報錯，讓下游 pad 決定）
        has_closed = self._has_closed_profile(feature)
        if not has_closed:
            return None

        with BuildSketch(work_plane) as sketch:
            for entity in feature.sketch_entities:
                self._add_sketch_entity(entity, feature)
        return sketch.sketch

    def _add_sketch_entity(self, entity: dict[str, Any], feature: Feature) -> None:
        # 支援兩種格式：
        # 1. viewer 格式: {"type": "rectangle", "x": 0, "y": 0, "width": 40, "height": 20}
        # 2. 舊 adapter 格式: {"entity_type": "rectangle", "parameters": {...}}
        etype = entity.get("entity_type") or entity.get("type")
        params = entity.get("parameters", entity)  # 若無 parameters 子物件，entity 本身就是參數

        if etype == "rectangle":
            w = self._raw_mm(params.get("width", params.get("w", 10)))
            h = self._raw_mm(params.get("height", params.get("h", 10)))
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            with Locations(Pos(cx, cy)):
                Rectangle(w, h)

        elif etype == "circle":
            r = self._raw_mm(params.get("radius", params.get("r", 5)))
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            with Locations(Pos(cx, cy)):
                Circle(r)

        elif etype == "polygon":
            n = int(params.get("sides", 6))
            r = self._raw_mm(params.get("circumscribed_radius", params.get("radius", 5)))
            with Locations(Pos(0, 0)):
                RegularPolygon(r, n)

        elif etype == "slot":
            w = self._raw_mm(params.get("width", 20))
            h = self._raw_mm(params.get("height", 8))
            cx = self._raw_mm(params.get("center_x", 0))
            cy = self._raw_mm(params.get("center_y", 0))
            with Locations(Pos(cx, cy)):
                SlotOverall(w, h)

        elif etype == "line":
            # 線段——由兩端點定義。在 BuildSketch 中只作為輔助邊界。
            x1 = self._raw_mm(params.get("x1", 0))
            y1 = self._raw_mm(params.get("y1", 0))
            x2 = self._raw_mm(params.get("x2", 10))
            y2 = self._raw_mm(params.get("y2", 0))
            # 線段在 sketch 中只作為輔助，不直接產生面

        elif etype == "polyline":
            # 多段線——由頂點列表定義，可閉合或開放
            points = params.get("points", [])
            closed = params.get("closed", False)
            if len(points) < 2:
                return
            pts = [(self._raw_mm(p[0]), self._raw_mm(p[1])) for p in points]
            if closed:
                # 閉合多段線在 BuildSketch 中用 Edge + Wire + make_face 建立面
                edges = []
                for i in range(len(pts)):
                    p1 = Vector(pts[i][0], pts[i][1], 0)
                    p2 = Vector(pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1], 0)
                    edges.append(Edge.make_line(p1, p2))
                wire = Wire(edges)
                try:
                    face = make_face(wire)
                    add(face)
                except Exception:
                    pass  # 若建面失敗，不影響其他實體
            # 開放多段線在 BuildSketch 中不產生面，跳過

        elif etype == "arc":
            # 圓弧——由圓心、半徑、起角、終角定義
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            r = self._raw_mm(params.get("radius", params.get("r", 5)))
            start_angle = float(params.get("start_angle", 0))
            end_angle = float(params.get("end_angle", 90))
            start_rad = math.radians(start_angle)
            end_rad = math.radians(end_angle)
            # 弧在 BuildSketch 中只作為輔助邊界
            p1 = Vector(cx + math.cos(start_rad) * r, cy + math.sin(start_rad) * r, 0)
            p2 = Vector(cx + math.cos(end_rad) * r, cy + math.sin(end_rad) * r, 0)
            center = Vector(cx, cy, 0)
            try:
                Edge.make_three_point_arc(p1, center, p2)
            except Exception:
                pass  # 若建弧失敗，不影響其他實體

        elif etype == "construction_line":
            # 建構線——只用於輔助，不參與實體建立
            pass

    def _raw_mm(self, val: Any) -> float:
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _has_closed_profile(self, sketch_feature: Feature) -> bool:
        """檢查草圖是否包含至少一個閉合輪廓。"""
        for entity in sketch_feature.sketch_entities:
            etype = entity.get("entity_type") or entity.get("type")
            params = entity.get("parameters", entity)
            if etype in ("rectangle", "circle", "polygon", "slot"):
                return True
            if etype == "polyline" and params.get("closed", False):
                return True
        return False

    def _validate_sketch_closed(self, sketch_feature: Feature) -> None:
        """驗證草圖是否形成閉合輪廓（pad/pocket 需要）。

        rectangle/circle/polygon/slot 本身是閉合的。
        閉合 polyline (closed=True) 也是閉合的。
        只要有任一閉合實體即可；線段/弧/建構線/開放 polyline 為輔助。
        """
        if not sketch_feature.sketch_entities:
            raise ValueError("草圖未閉合：沒有任何草圖實體")
        if not self._has_closed_profile(sketch_feature):
            raise ValueError("草圖未閉合：需要至少一個閉合輪廓（矩形、圓、閉合多段線等）才能拉伸")

    def _build_pad(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """拉伸草圖成實體。

        依輸入草圖的 plane 決定拉伸方向：
        - XY：BuildPart 預設（沿 Z 軸）
        - XZ/YZ：直接 extrude(sketch, amount) 跟隨草圖法線
        """
        sketch_part = parts.get(feature.input) if feature.input else None
        length = self._get_param(feature, "length", 5.0)

        if sketch_part is None:
            # 草圖可能因沒有閉合輪廓而回傳 None
            input_feat = graph.get_feature(feature.input) if feature.input else None
            if input_feat and input_feat.type == FeatureType.SKETCH:
                self._validate_sketch_closed(input_feat)
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        # 驗證草圖閉合（pad 需要閉合輪廓）
        input_feat = graph.get_feature(feature.input) if feature.input else None
        if input_feat and input_feat.type == FeatureType.SKETCH:
            self._validate_sketch_closed(input_feat)

        plane_base = "XY"
        if input_feat and input_feat.type == FeatureType.SKETCH:
            plane_base = input_feat.plane.get("base", "XY")

        if plane_base == "XY":
            # XY 草圖：用 BuildPart + add + extrude（沿 Z 軸）
            with BuildPart() as bp:
                add(sketch_part)
                extrude(amount=length)
            result = bp.part
        else:
            # 非 XY 草圖：直接 extrude 跟隨草圖法線方向
            result = extrude(sketch_part, amount=length)

        return result

    def _add_sketch_to_part(self, bp, sketch_part) -> None:
        """將草圖加入 BuildPart。"""
        add(sketch_part)

    def _build_pocket(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """切除材料。支援草圖參照與位置列表。"""
        # 從宣告的 input 取得基礎實體——不再使用 current_solid fallback
        base_part = parts.get(feature.input) if feature.input else None
        sketch_part = None
        # 尋找草圖參照——從 graph 查特徵類型，只取 sketch 類型的參照
        for ref in feature.references:
            ref_feature = graph.get_feature(ref)
            if ref_feature and ref_feature.type == FeatureType.SKETCH and ref in parts:
                sketch_part = parts[ref]
                break

        depth = self._get_param(feature, "depth", 0)
        through_all = feature.parameters.get("through_all", False)
        diameter = self._get_param(feature, "diameter", 0)

        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        # 位置列表模式（類似 _build_hole）：多個圓孔切除
        positions = feature.parameters.get("positions", [])
        if positions and diameter > 0:
            result = base_part
            for pos_xy in positions:
                px = self._raw_mm(pos_xy[0]) if isinstance(pos_xy, list) else float(pos_xy)
                py = self._raw_mm(pos_xy[1]) if isinstance(pos_xy, list) else 0.0
                h = 1000 if through_all else depth
                with BuildPart() as bp_hole:
                    with Locations(Pos(px, py)):
                        Cylinder(diameter / 2, h)
                result = result.cut(bp_hole.part)
            return result

        if sketch_part is not None:
            # 驗證草圖閉合（pocket 需要閉合輪廓）
            for ref in feature.references:
                ref_feature = graph.get_feature(ref)
                if ref_feature and ref_feature.type == FeatureType.SKETCH:
                    self._validate_sketch_closed(ref_feature)
                    break
            # 查詢輸入草圖的基準面（與 _build_pad 相同邏輯：非 XY 需沿草圖法線拉伸切除）
            ref_plane_base = "XY"
            for ref in feature.references:
                ref_feature = graph.get_feature(ref)
                if ref_feature and ref_feature.type == FeatureType.SKETCH:
                    ref_plane_base = ref_feature.plane.get("base", "XY")
                    break

            if not through_all and depth <= 0:
                raise ValueError(
                    "pocket 深度無效：depth 必須大於 0，或設定 through_all=true 貫穿切除"
                )

            cut_amount = 1000 if through_all else depth
            if ref_plane_base == "XY":
                with BuildPart() as bp_cut:
                    add(sketch_part)
                    extrude(amount=cut_amount, both=through_all)
                cut_shape = bp_cut.part
            else:
                # 非 XY 草圖：直接沿草圖法線拉伸切除，避免 BuildPart 預設 XY 工作面誤判方向
                cut_shape = extrude(sketch_part, amount=cut_amount, both=through_all)
            return base_part.cut(cut_shape)

        # 走到這裡代表 pocket 既沒有草圖參照也沒有 positions——
        # 靜默回傳原實體會讓「挖孔沒發生」無聲失敗，必須報結構化錯誤
        raise ValueError(
            "pocket 缺少切除輪廓：references 必須包含一個草圖特徵，"
            "或在 parameters 提供 positions＋diameter"
        )

    def _build_hole(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """建立孔特徵。支援標準件查表與沉頭孔（counterbore）。"""
        # 從宣告的 input 取得基礎實體——不再使用 current_solid fallback
        base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        # 記錄切除前邊快照（用於 topology trace）
        before_edges = _snapshot_edges(base_part)

        # 查表取得孔徑
        sp = feature.standard_parts or {}
        fastener = sp.get("fastener", {})
        standard = fastener.get("standard", "")
        fit = fastener.get("fit", "normal_clearance")

        if standard:
            diameter = get_clearance_hole_diameter(standard, fit)
        else:
            diameter = self._get_param(feature, "diameter", 5.0)

        depth = self._get_param(feature, "depth", 0)
        through_all = feature.parameters.get("through_all", False)
        hole_type = feature.parameters.get("hole_type", "simple")

        # 沉頭孔尺寸
        counterbore_diameter = 0.0
        counterbore_depth = 0.0
        if hole_type == "counterbore":
            cb_dims = get_counterbore_dimensions(standard) if standard else {}
            if not cb_dims:
                # 手動指定沉頭尺寸
                counterbore_diameter = self._get_param(feature, "counterbore_diameter", 0)
                counterbore_depth = self._get_param(feature, "counterbore_depth", 0)
            else:
                counterbore_diameter = float(cb_dims.get("diameter", 0))
                counterbore_depth = float(cb_dims.get("depth", 0))

        # 孔位置
        positions = feature.parameters.get("positions", [])
        if not positions:
            cx = self._get_param(feature, "center_x", 0)
            cy = self._get_param(feature, "center_y", 0)
            positions = [[cx, cy]]

        # 用 Part.cut() 依序切除每個孔
        result = base_part
        for pos_xy in positions:
            px = self._raw_mm(pos_xy[0]) if isinstance(pos_xy, list) else float(pos_xy)
            py = self._raw_mm(pos_xy[1]) if isinstance(pos_xy, list) else 0.0
            h = 1000 if through_all else depth

            # 主孔
            with BuildPart() as bp_hole:
                with Locations(Pos(px, py)):
                    Cylinder(diameter / 2, h)
            result = result.cut(bp_hole.part)

            # 沉頭孔（從表面切除較大的圓柱）
            if counterbore_diameter > 0 and counterbore_depth > 0:
                with BuildPart() as bp_cb:
                    with Locations(Pos(px, py)):
                        Cylinder(counterbore_diameter / 2, counterbore_depth)
                result = result.cut(bp_cb.part)

        # 記錄 topology trace——hole 新增了哪些邊
        if trace is not None:
            after_edges = _snapshot_edges(result)
            trace.record_created(feature.feature_id, before_edges, after_edges)

        return result

    def _build_linear_pattern(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """線性陣列。

        設計決策：Pattern 為實體（solid）專用——透過 fuse 合併副本。
        若來源為 hole/pocket（切除特徵），應改用該特徵的 positions 參數列表，
        而非 Pattern，因為 fuse 無法正確倍增切除結果。
        """
        source_part = parts.get(feature.input) if feature.input else None
        if source_part is None:
            raise ValueError(f"找不到來源特徵: {feature.input}")

        # 檢查來源是否為切除特徵——Pattern 不支援切除，應使用 positions
        if feature.input:
            src_feat = graph.get_feature(feature.input)
            if src_feat and src_feat.type in (FeatureType.HOLE, FeatureType.POCKET):
                raise ValueError(
                    f"Pattern 不支援切除特徵（{src_feat.type.value}）——"
                    f"請改用 {src_feat.feature_id} 的 positions 參數列表"
                )

        count_x = int(feature.parameters.get("count_x", 2))
        count_y = int(feature.parameters.get("count_y", 1))
        spacing_x = self._get_param(feature, "spacing_x", 10.0)
        spacing_y = self._get_param(feature, "spacing_y", 0.0)

        result = source_part
        for i in range(count_x):
            for j in range(count_y):
                if i == 0 and j == 0:
                    continue
                offset_part = source_part.moved(Pos(i * spacing_x, j * spacing_y, 0))
                result = result.fuse(offset_part)
        return result

    def _select_edges(
        self,
        part: "Part",
        selector: str,
        exclude_holes: bool = False,
        trace: "TopologyTrace | None" = None,
        graph: "FeatureGraph | None" = None,
        feature: "Feature | None" = None,
    ) -> list:
        """根據選擇器字串挑選邊。

        支援的選擇器：
        - "all": 所有邊
        - "all_vertical": 平行 Z 軸的邊
        - "all_horizontal": 垂直 Z 軸的邊（X 或 Y 方向）
        - "top": 頂面邊
        - "bottom": 底面邊

        exclude_holes=True 時，使用 topology provenance 排除由 hole/pocket
        特徵建立的邊（需要 trace 參數）。若無 trace，fallback 到 GeomType.CIRCLE。

        也支援 edge_selector DSL（dict 格式）：
        {"include": [{"kind": "all_edges"}],
         "exclude": [{"kind": "created_by", "feature_id": "hole_center"}]}
        """
        # 支援 edge_selector DSL（dict 格式）
        if isinstance(selector, dict):
            return self._resolve_edge_selector(part, selector, trace, graph)

        if selector == "all":
            result = list(part.edges())
        elif selector == "all_vertical":
            result = list(part.edges().filter_by(Axis.Z))
        elif selector == "all_horizontal":
            edges_x = part.edges().filter_by(Axis.X)
            edges_y = part.edges().filter_by(Axis.Y)
            result = list(edges_x) + list(edges_y)
        elif selector == "top":
            bb = part.bounding_box()
            top_z = bb.max.Z
            result = [e for e in part.edges()
                      if all(abs(v.Z - top_z) < 0.01 for v in e.vertices())]
        elif selector == "bottom":
            bb = part.bounding_box()
            bot_z = bb.min.Z
            result = [e for e in part.edges()
                      if all(abs(v.Z - bot_z) < 0.01 for v in e.vertices())]
        else:
            result = list(part.edges())

        # 排除孔的邊——優先使用 topology provenance，fallback 到 GeomType.CIRCLE
        if exclude_holes and result:
            if trace is not None and graph is not None and feature is not None:
                # 語意化方式：排除所有 hole/pocket 特徵建立的邊
                hole_edge_set: set = set()
                for fid, feat in graph.features.items():
                    if feat.type in (FeatureType.HOLE, FeatureType.POCKET) and fid != feature.feature_id:
                        hole_edge_set.update(trace.created_by(fid))
                if hole_edge_set:
                    result = [e for e in result if e not in hole_edge_set]
                else:
                    # trace 中沒有記錄——fallback 到幾何方式
                    from build123d import GeomType
                    result = [e for e in result if e.geom_type != GeomType.CIRCLE]
            else:
                # 無 trace——使用幾何 fallback
                from build123d import GeomType
                result = [e for e in result if e.geom_type != GeomType.CIRCLE]

        return result

    def _resolve_edge_selector(
        self,
        part: "Part",
        selector: dict[str, Any],
        trace: "TopologyTrace | None" = None,
        graph: "FeatureGraph | None" = None,
    ) -> list:
        """解析 edge_selector DSL。

        格式：
        {"include": [{"kind": "all_edges"|"top"|"bottom"|...}],
         "exclude": [{"kind": "created_by", "feature_id": "hole_1"}],
         "filters": [{"kind": "vertical"|"horizontal", ...}]}
        """
        all_edges = list(part.edges())
        result = all_edges

        # include 限制
        include_rules = selector.get("include", [{"kind": "all_edges"}])
        if include_rules:
            included: list = []
            for rule in include_rules:
                kind = rule.get("kind", "all_edges")
                if kind == "all_edges":
                    included.extend(all_edges)
                elif kind == "top":
                    bb = part.bounding_box()
                    top_z = bb.max.Z
                    included.extend([e for e in all_edges
                                     if all(abs(v.Z - top_z) < 0.01 for v in e.vertices())])
                elif kind == "bottom":
                    bb = part.bounding_box()
                    bot_z = bb.min.Z
                    included.extend([e for e in all_edges
                                     if all(abs(v.Z - bot_z) < 0.01 for v in e.vertices())])
                elif kind == "all_vertical":
                    included.extend(list(part.edges().filter_by(Axis.Z)))
                elif kind == "all_horizontal":
                    included.extend(list(part.edges().filter_by(Axis.X)))
                    included.extend(list(part.edges().filter_by(Axis.Y)))
            # 去重
            seen = set()
            result = []
            for e in included:
                if id(e) not in seen:
                    seen.add(id(e))
                    result.append(e)

        # exclude 排除
        exclude_rules = selector.get("exclude", [])
        for rule in exclude_rules:
            kind = rule.get("kind", "")
            if kind == "created_by" and trace is not None:
                fid = rule.get("feature_id", "")
                exclude_set = trace.created_by(fid)
                result = [e for e in result if e not in exclude_set]
            elif kind == "geom_circle":
                from build123d import GeomType
                result = [e for e in result if e.geom_type != GeomType.CIRCLE]

        # filters 進一步篩選
        filter_rules = selector.get("filters", [])
        for rule in filter_rules:
            kind = rule.get("kind", "")
            if kind == "vertical":
                result = list(filter_by_axis(result, Axis.Z))
            elif kind == "horizontal":
                result = (list(filter_by_axis(result, Axis.X)) +
                          list(filter_by_axis(result, Axis.Y)))

        return result

    def _build_fillet(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """圓角。需要指定要導圓角的邊。"""
        # 從宣告的 input 取得基礎實體——不再使用 current_solid fallback
        base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        radius = self._get_param(feature, "radius", 1.0)
        edge_selector = feature.parameters.get("edges", "all")
        exclude_holes = feature.parameters.get("exclude_holes", False)

        edges = self._select_edges(base_part, edge_selector, exclude_holes, trace, graph, feature)
        if not edges:
            raise ValueError(f"找不到符合條件的邊來導圓角: {edge_selector}")

        # 記錄選中的邊到 trace
        if trace is not None:
            trace.record_selected(feature.feature_id, edges)

        result = base_part.fillet(radius, edges)
        return result

    def _build_chamfer(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """倒角。需要指定要倒角的邊。"""
        # 從宣告的 input 取得基礎實體——不再使用 current_solid fallback
        base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        length = self._get_param(feature, "length", 1.0)
        edge_selector = feature.parameters.get("edges", "all")
        exclude_holes = feature.parameters.get("exclude_holes", False)

        edges = self._select_edges(base_part, edge_selector, exclude_holes, trace, graph, feature)
        if not edges:
            raise ValueError(f"找不到符合條件的邊來倒角: {edge_selector}")

        # 記錄選中的邊到 trace
        if trace is not None:
            trace.record_selected(feature.feature_id, edges)

        result = base_part.chamfer(length, None, edges)
        return result

    def _build_shell(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """薄殼。使用 offset(amount=-thickness) 建立內部空腔。"""
        # 從宣告的 input 取得基礎實體——不再使用 current_solid fallback
        base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        thickness = self._get_param(feature, "thickness", 1.0)
        result = offset(base_part, amount=-thickness)
        return result

    def _build_revolve(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """迴轉。迴轉軸須落在草圖平面內，依草圖 plane 決定：XY/XZ 用 X 軸，YZ 用 Y 軸。"""
        sketch_part = parts.get(feature.input) if feature.input else None
        angle = self._get_param(feature, "angle", 360.0)

        if sketch_part is None:
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        input_feat = graph.get_feature(feature.input) if feature.input else None
        plane_base = "XY"
        if input_feat and input_feat.type == FeatureType.SKETCH:
            plane_base = input_feat.plane.get("base", "XY")
        axis = Axis.Y if plane_base == "YZ" else Axis.X

        with BuildPart() as bp:
            self._add_sketch_to_part(bp, sketch_part)
            revolve(axis=axis, revolution_arc=angle)
        return bp.part

    def _build_sweep(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """掃描：將輪廓草圖沿路徑草圖掃描成實體。

        input = 輪廓草圖 feature_id
        references[0] = 路徑草圖 feature_id（其 sketch_entities 定義路徑線段）
        路徑草圖的 2D 座標依其 plane 轉換為 3D 世界座標。
        """
        profile = parts.get(feature.input) if feature.input else None
        if profile is None:
            raise ValueError(f"找不到輪廓草圖: {feature.input}")

        path_fid = feature.references[0] if feature.references else None
        if not path_fid:
            raise ValueError("sweep 需要 references 指定路徑草圖")

        path_feat = graph.get_feature(path_fid)
        if path_feat is None:
            raise ValueError(f"找不到路徑草圖: {path_fid}")

        # 路徑草圖的基準面決定 2D→3D 座標映射
        path_plane = path_feat.plane.get("base", "XY")

        def to_3d(x: float, y: float) -> Vector:
            """依路徑草圖的 plane 將 2D sketch 座標轉為 3D 世界座標。"""
            if path_plane == "XY":
                return Vector(x, y, 0)
            elif path_plane == "XZ":
                return Vector(x, 0, y)
            elif path_plane == "YZ":
                return Vector(0, x, y)
            return Vector(x, y, 0)

        # 從路徑草圖的 sketch_entities 建立 Wire
        path_edges: list[Edge] = []
        for entity in path_feat.sketch_entities:
            etype = entity.get("entity_type") or entity.get("type")
            params = entity.get("parameters", entity)
            if etype == "line":
                x1 = self._raw_mm(params.get("x1", 0))
                y1 = self._raw_mm(params.get("y1", 0))
                x2 = self._raw_mm(params.get("x2", 0))
                y2 = self._raw_mm(params.get("y2", 0))
                path_edges.append(Edge.make_line(to_3d(x1, y1), to_3d(x2, y2)))
            elif etype == "polyline":
                pts = params.get("points", [])
                closed = params.get("closed", False)
                coords = [(self._raw_mm(p[0]), self._raw_mm(p[1])) for p in pts]
                for i in range(len(coords) - 1):
                    path_edges.append(Edge.make_line(
                        to_3d(coords[i][0], coords[i][1]),
                        to_3d(coords[i+1][0], coords[i+1][1]),
                    ))
                if closed and len(coords) > 1:
                    path_edges.append(Edge.make_line(
                        to_3d(coords[-1][0], coords[-1][1]),
                        to_3d(coords[0][0], coords[0][1]),
                    ))
            elif etype == "arc":
                import math
                cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
                cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
                r = self._raw_mm(params.get("radius", params.get("r", 5)))
                sa = math.radians(float(params.get("start_angle", 0)))
                ea = math.radians(float(params.get("end_angle", 90)))
                p1 = to_3d(cx + math.cos(sa) * r, cy + math.sin(sa) * r)
                pc = to_3d(cx, cy)
                p2 = to_3d(cx + math.cos(ea) * r, cy + math.sin(ea) * r)
                try:
                    path_edges.append(Edge.make_three_point_arc(p1, pc, p2))
                except Exception:
                    pass

        if not path_edges:
            raise ValueError("路徑草圖沒有可用的線段")

        path_wire = Wire(path_edges)
        result = sweep(profile, path=path_wire)
        return result

    def _build_loft(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """放樣：在多個輪廓草圖之間建立漸變實體。

        input = 第一個輪廓草圖 feature_id
        references = 後續輪廓草圖 feature_id 列表
        """
        # 收集所有輪廓
        profile_ids = [feature.input] + list(feature.references) if feature.input else list(feature.references)
        if len(profile_ids) < 2:
            raise ValueError("loft 需要至少兩個輪廓草圖")

        profiles = []
        for fid in profile_ids:
            p = parts.get(fid)
            if p is None:
                raise ValueError(f"找不到輪廓草圖: {fid}")
            profiles.append(p)

        with BuildPart() as bp:
            for p in profiles:
                add(p)
            loft()
        return bp.part

    def _build_mirror(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """鏡像。"""
        base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到來源: {feature.input}")
        result = base_part.mirror(Plane.XZ)
        result = result.fuse(base_part)
        return result

    def _build_boolean_union(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.fuse(b)
        return a or b

    def _build_boolean_difference(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.cut(b)
        return a

    def _build_boolean_intersection(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.intersect(b)
        return a

    def _build_circular_pattern(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        trace: "TopologyTrace | None" = None,
    ) -> "Part | None":
        """圓周陣列。

        設計決策：Pattern 為實體（solid）專用——透過 fuse 合併副本。
        若來源為 hole/pocket（切除特徵），應改用該特徵的 positions 參數列表。
        """
        source_part = parts.get(feature.input) if feature.input else None
        if source_part is None:
            raise ValueError(f"找不到來源特徵: {feature.input}")

        # 檢查來源是否為切除特徵——Pattern 不支援切除，應使用 positions
        if feature.input:
            src_feat = graph.get_feature(feature.input)
            if src_feat and src_feat.type in (FeatureType.HOLE, FeatureType.POCKET):
                raise ValueError(
                    f"Pattern 不支援切除特徵（{src_feat.type.value}）——"
                    f"請改用 {src_feat.feature_id} 的 positions 參數列表"
                )

        count = int(feature.parameters.get("count", 6))
        radius = self._get_param(feature, "radius", 20.0)

        result = source_part
        for i in range(1, count):
            angle = 2 * math.pi * i / count
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            offset_part = source_part.moved(Pos(x, y, 0))
            result = result.fuse(offset_part)
        return result