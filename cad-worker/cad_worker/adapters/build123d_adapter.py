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
        Plane, Polyline, Rectangle, Circle, RegularPolygon,
        Pos, Mode, Axis, Vector,
        extrude, revolve, fillet, chamfer, mirror,
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
from ..standard_parts import get_clearance_hole_diameter, get_nema_mounting


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

        鏈式重建：每個修改實體的特徵（hole/pocket/fillet/chamfer/shell）
        以前一個特徵的結果為輸入，而非只看自己宣告的 input。
        """
        order = graph.topological_sort()
        parts: dict[str, Part] = {}
        current_solid: Part | None = None  # 鏈式重建的目前實體

        # 會修改實體的特徵類型——這些會以 current_solid 為輸入
        MODIFYING_TYPES = {
            FeatureType.HOLE, FeatureType.POCKET,
            FeatureType.FILLET, FeatureType.CHAMFER,
            FeatureType.SHELL,
            FeatureType.BOOLEAN_UNION,
            FeatureType.BOOLEAN_DIFFERENCE,
            FeatureType.BOOLEAN_INTERSECTION,
        }

        for fid in order:
            feature = graph.get_feature(fid)
            if feature is None:
                continue
            feature.rebuild_status = "building"
            try:
                # 對修改型特徵，注入 current_solid 作為 input 的 fallback
                result = self._build_feature(feature, parts, graph, current_solid)
                if result is not None:
                    parts[fid] = result
                    # 更新鏈：只有產生實體的特徵才推進 current_solid
                    if feature.type in MODIFYING_TYPES or feature.type in (
                        FeatureType.PAD, FeatureType.REVOLVE,
                    ):
                        current_solid = result
                feature.rebuild_status = "success"
                feature.error_message = ""
            except Exception as e:
                feature.rebuild_status = "failed"
                feature.error_message = str(e)
                raise

        return current_solid

    def _build_feature(
        self,
        feature: Feature,
        parts: dict[str, "Part"],
        graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """根據特徵類型分派到對應的建構方法。"""
        method = getattr(self, f"_build_{feature.type.value}", None)
        if method is None:
            raise ValueError(f"不支援的特徵類型: {feature.type}")
        return method(feature, parts, graph, current_solid)

    def _get_param(self, feature: Feature, key: str, default: float = 0.0) -> float:
        """從特徵參數取得數值，自動換算為 mm。"""
        val = feature.parameters.get(key, default)
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _build_sketch(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """建立草圖。build123d 的草圖由參數直接計算位置。"""
        with BuildSketch() as sketch:
            for entity in feature.sketch_entities:
                self._add_sketch_entity(entity, feature)
        return sketch.sketch

    def _add_sketch_entity(self, entity: dict[str, Any], feature: Feature) -> None:
        etype = entity.get("entity_type")
        params = entity.get("parameters", {})

        if etype == "rectangle":
            w = self._raw_mm(params.get("width", 10))
            h = self._raw_mm(params.get("height", 10))
            cx = self._raw_mm(params.get("center_x", 0))
            cy = self._raw_mm(params.get("center_y", 0))
            with Locations(Pos(cx, cy)):
                Rectangle(w, h)

        elif etype == "circle":
            r = self._raw_mm(params.get("radius", 5))
            cx = self._raw_mm(params.get("center_x", 0))
            cy = self._raw_mm(params.get("center_y", 0))
            with Locations(Pos(cx, cy)):
                Circle(r)

        elif etype == "polygon":
            n = int(params.get("sides", 6))
            r = self._raw_mm(params.get("circumscribed_radius", 5))
            with Locations(Pos(0, 0)):
                RegularPolygon(r, n)

    def _raw_mm(self, val: Any) -> float:
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _build_pad(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """拉伸草圖成實體。"""
        sketch_part = parts.get(feature.input) if feature.input else None
        length = self._get_param(feature, "length", 5.0)

        if sketch_part is None:
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        with BuildPart() as bp:
            add_result = self._add_sketch_to_part(bp, sketch_part)
            extrude(amount=length)

        result = bp.part

        # 處理下游 pattern
        return result

    def _add_sketch_to_part(self, bp, sketch_part) -> None:
        """將草圖加入 BuildPart。"""
        add(sketch_part)

    def _build_pocket(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """切除材料。支援草圖參照與位置列表。"""
        # 鏈式重建：優先使用 current_solid（上一個特徵的結果）
        base_part = current_solid
        if base_part is None:
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
            # 用 cut 方法切除草圖拉伸的形狀
            with BuildPart() as bp_cut:
                add(sketch_part)
                if through_all:
                    extrude(amount=1000, both=True)
                else:
                    extrude(amount=depth)
            return base_part.cut(bp_cut.part)

        return base_part

    def _build_hole(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """建立孔特徵。支援標準件查表。"""
        # 鏈式重建：優先使用 current_solid
        base_part = current_solid
        if base_part is None:
            base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

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

        # 孔位置
        positions = feature.parameters.get("positions", [])
        if not positions:
            cx = self._get_param(feature, "center_x", 0)
            cy = self._get_param(feature, "center_y", 0)
            positions = [[cx, cy]]

        # 用 Part.cut() 依序切除每個圓柱孔
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

    def _build_linear_pattern(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
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

    def _select_edges(self, part: "Part", selector: str) -> list:
        """根據選擇器字串挑選邊。

        支援的選擇器：
        - "all": 所有邊
        - "all_vertical": 平行 Z 軸的邊
        - "all_horizontal": 垂直 Z 軸的邊（X 或 Y 方向）
        - "top": 頂面邊
        - "bottom": 底面邊
        """
        if selector == "all":
            return list(part.edges())
        elif selector == "all_vertical":
            return list(part.edges().filter_by(Axis.Z))
        elif selector == "all_horizontal":
            edges_x = part.edges().filter_by(Axis.X)
            edges_y = part.edges().filter_by(Axis.Y)
            return list(edges_x) + list(edges_y)
        elif selector == "top":
            bb = part.bounding_box()
            top_z = bb.max.Z
            return [e for e in part.edges()
                    if all(abs(v.Z - top_z) < 0.01 for v in e.vertices())]
        elif selector == "bottom":
            bb = part.bounding_box()
            bot_z = bb.min.Z
            return [e for e in part.edges()
                    if all(abs(v.Z - bot_z) < 0.01 for v in e.vertices())]
        else:
            return list(part.edges())

    def _build_fillet(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """圓角。需要指定要導圓角的邊。"""
        # 鏈式重建：優先使用 current_solid
        base_part = current_solid
        if base_part is None:
            base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        radius = self._get_param(feature, "radius", 1.0)
        edge_selector = feature.parameters.get("edges", "all")

        edges = self._select_edges(base_part, edge_selector)
        if not edges:
            raise ValueError(f"找不到符合條件的邊來導圓角: {edge_selector}")
        result = base_part.fillet(radius, edges)
        return result

    def _build_chamfer(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """倒角。需要指定要倒角的邊。"""
        # 鏈式重建：優先使用 current_solid
        base_part = current_solid
        if base_part is None:
            base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        length = self._get_param(feature, "length", 1.0)
        edge_selector = feature.parameters.get("edges", "all")

        edges = self._select_edges(base_part, edge_selector)
        if not edges:
            raise ValueError(f"找不到符合條件的邊來倒角: {edge_selector}")
        result = base_part.chamfer(length, None, edges)
        return result

    def _build_shell(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """薄殼。使用 offset(amount=-thickness) 建立內部空腔。"""
        # 鏈式重建：優先使用 current_solid
        base_part = current_solid
        if base_part is None:
            base_part = parts.get(feature.input) if feature.input else None
        if base_part is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        thickness = self._get_param(feature, "thickness", 1.0)
        result = offset(base_part, amount=-thickness)
        return result

    def _build_revolve(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        """迴轉。"""
        sketch_part = parts.get(feature.input) if feature.input else None
        angle = self._get_param(feature, "angle", 360.0)

        if sketch_part is None:
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        with BuildPart() as bp:
            self._add_sketch_to_part(bp, sketch_part)
            revolve(axis=Axis.X, angle=angle)
        return bp.part

    def _build_mirror(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
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
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.fuse(b)
        return a or b

    def _build_boolean_difference(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.cut(b)
        return a

    def _build_boolean_intersection(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
    ) -> "Part | None":
        a = parts.get(feature.references[0]) if len(feature.references) > 0 else None
        b = parts.get(feature.references[1]) if len(feature.references) > 1 else None
        if a and b:
            return a.intersect(b)
        return a

    def _build_circular_pattern(
        self, feature: Feature, parts: dict[str, "Part"], graph: FeatureGraph,
        current_solid: "Part | None" = None,
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