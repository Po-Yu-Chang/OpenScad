"""FreeCAD Adapter — 將 Feature Graph 轉譯為 FreeCAD Part API 建模命令。

此 Adapter 實作與 Build123dAdapter 相同的 build_with_trace() 契約，
但使用 FreeCAD Part workbench API（非 PartDesign，headless 不可用）。

引擎切換：OPENCAD_ENGINE=freecad 時使用此 Adapter。
FreeCAD 不可用時，import 會失敗，_get_adapter() 回退到 build123d。

返回的 part 是 FreeCADShapeWrapper，包裝 FreeCAD shape，
提供與 build123d Part 相容的 faces()/edges() 介面，
讓 exporters/__init__.py 的 build_display_map / GlbExporter 不需改。
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, NamedTuple

_FREECAD_IMPORT_ERROR: str | None = None
FREECAD_AVAILABLE = False

try:
    _freecad_dir = os.environ.get("FREECAD_DIR", "")
    if _freecad_dir and os.path.isdir(_freecad_dir):
        for _p in [os.path.join(_freecad_dir, "bin"), os.path.join(_freecad_dir, "lib")]:
            if _p not in sys.path:
                sys.path.insert(0, _p)
    import FreeCAD
    import Part
    import Sketcher
    FREECAD_AVAILABLE = True
except ImportError as _e:
    FREECAD_AVAILABLE = False
    _FREECAD_IMPORT_ERROR = str(_e)

from ..feature_graph import FeatureGraph, Feature, FeatureState, FeatureType, ParameterValue


class BuildResult(NamedTuple):
    """build() 的回傳值——包含最終實體與拓撲追蹤。"""
    part: Any
    trace: "TopologyTrace | None"


class FreeCADFaceProxy:
    """包裝 FreeCAD Face，提供與 build123d Face 相容的介面。

    exporters/__init__.py 使用：
    - face.tessellate(tolerance) → (verts, tris)
    - face.geom_type → GeomType-like（用 _geom_type_to_surface_type 轉換）
    - face.center() → Vector(.X, .Y, .Z)
    - face.area → float
    """

    def __init__(self, fc_face: Any, index: int, feature_id: str = ""):
        self._face = fc_face
        self._index = index
        self._feature_id = feature_id

    def tessellate(self, tolerance: float = 0.1):
        """三角化，回傳 (list[VectorProxy], list[tuple])。

        FreeCAD face.tessellate(tolerance) 回傳 (vertices, triangles)。
        vertices 是 list of FreeCAD.Vector，triangles 是 list of tuple(int, int, int)。
        """
        verts_fc, tris = self._face.tessellate(tolerance)
        verts = [FreeCADVectorProxy(v) for v in verts_fc]
        return verts, tris

    @property
    def geom_type(self):
        """回傳 surface type 字串，模擬 build123d GeomType。"""
        type_id = self._face.Surface.TypeId
        type_map = {
            "Part::GeomPlane": "PLANE",
            "Part::GeomCylinder": "CYLINDER",
            "Part::GeomCone": "CONE",
            "Part::GeomSphere": "SPHERE",
            "Part::GeomToroid": "TORUS",
        }
        return type_map.get(type_id, "OTHER")

    def center(self):
        """回傳面質心，模擬 build123d face.center()。"""
        return FreeCADVectorProxy(self._face.CenterOfMass)

    @property
    def area(self):
        """回傳面積。"""
        return float(self._face.Area)

    def is_equal(self, other: "FreeCADFaceProxy") -> bool:
        """比較兩面是否指向同一拓撲元素。"""
        if not isinstance(other, FreeCADFaceProxy):
            return False
        try:
            return self._face.isEqual(other._face)
        except Exception:
            return self._index == other._index

    @property
    def radius(self):
        """回傳圓柱/球面/錐面半徑（若有）。"""
        try:
            surf = self._face.Surface
            if hasattr(surf, "Radius"):
                return float(surf.Radius)
        except Exception:
            pass
        return None

    def normal_at(self):
        """回傳面法向量。"""
        try:
            n = self._face.normalAt(0, 0)
            return FreeCADVectorProxy(n)
        except Exception:
            return FreeCADVectorProxy(FreeCAD.Vector(0, 0, 1))


class FreeCADEdgeProxy:
    """包裝 FreeCAD Edge，提供與 build123d Edge 相容的介面。"""

    def __init__(self, fc_edge: Any, index: int, feature_id: str = ""):
        self._edge = fc_edge
        self._index = index
        self._feature_id = feature_id

    @property
    def length(self):
        """回傳邊長度。"""
        return float(self._edge.Length)

    def positions(self, params: list[float]):
        """回傳邊上多個參數位置的點。"""
        pts = []
        for t in params:
            try:
                pt = self._edge.valueAt(t * self._edge.Length)
                pts.append(FreeCADVectorProxy(pt))
            except Exception:
                pass
        if not pts:
            # Fallback: use Vertexes
            for v in self._edge.Vertexes:
                pts.append(FreeCADVectorProxy(v.Point))
        return pts

    def start_point(self):
        """回傳起點。"""
        try:
            return FreeCADVectorProxy(self._edge.Vertexes[0].Point)
        except Exception:
            return FreeCADVectorProxy(FreeCAD.Vector(0, 0, 0))

    def end_point(self):
        """回傳終點。"""
        try:
            return FreeCADVectorProxy(self._edge.Vertexes[-1].Point)
        except Exception:
            return FreeCADVectorProxy(FreeCAD.Vector(0, 0, 0))

    @property
    def direction(self):
        """回傳邊方向向量。"""
        try:
            d = self._edge.tangentAt(0)
            return FreeCADVectorProxy(d)
        except Exception:
            return FreeCADVectorProxy(FreeCAD.Vector(0, 0, 1))


class FreeCADVectorProxy:
    """包裝 FreeCAD.Vector，提供 .X/.Y/.Z 屬性（build123d 風格大寫）。"""

    def __init__(self, vec: Any):
        self._vec = vec

    @property
    def X(self):
        return float(self._vec.x)

    @property
    def Y(self):
        return float(self._vec.y)

    @property
    def Z(self):
        return float(self._vec.z)

    def round(self, ndigits: int = 2) -> list[float]:
        """四捨五入到指定小數位數，回傳 [x, y, z]。"""
        return [round(self.X, ndigits), round(self.Y, ndigits), round(self.Z, ndigits)]

    def __iter__(self):
        return iter([self.X, self.Y, self.Z])


class FreeCADShapeWrapper:
    """包裝 FreeCAD shape，提供與 build123d Part 相容的 faces()/edges() 介面。

    讓 exporters/__init__.py 的 build_display_map / GlbExporter.export_per_face
    可以用同一套程式碼處理 build123d Part 或 FreeCAD shape。
    """

    def __init__(self, shape: Any, trace: "TopologyTrace | None" = None):
        self._shape = shape
        self._freecad_shape = shape  # 供 exporters 偵測 FreeCAD 引擎
        self._trace = trace
        self._face_list: list[FreeCADFaceProxy] | None = None
        self._edge_list: list[FreeCADEdgeProxy] | None = None

    def faces(self):
        """回傳面列表（FreeCADFaceProxy）。"""
        if self._face_list is None:
            self._face_list = []
            for i, f in enumerate(self._shape.Faces):
                fid = ""
                if self._trace is not None:
                    fid = self._trace.resolve_face_index(i)
                self._face_list.append(FreeCADFaceProxy(f, i, fid))
        return self._face_list

    def edges(self):
        """回傳邊列表（FreeCADEdgeProxy）。"""
        if self._edge_list is None:
            self._edge_list = []
            for i, e in enumerate(self._shape.Edges):
                fid = ""
                if self._trace is not None:
                    fid = self._trace.resolve_edge_index(i)
                self._edge_list.append(FreeCADEdgeProxy(e, i, fid))
        return self._edge_list

    @property
    def wrapped(self):
        """回傳原始 FreeCAD shape（供 STEP 匯出用）。"""
        return self._shape

    @property
    def BoundBox(self):
        """回傳包圍盒。"""
        return self._shape.BoundBox

    @property
    def volume(self) -> float:
        """回傳體積（mm³），與 build123d Part.volume 相容。"""
        try:
            return float(self._shape.Volume)
        except Exception:
            return 0.0

    @property
    def area(self) -> float:
        """回傳表面積（mm²），與 build123d Part.area 相容。"""
        try:
            return float(self._shape.Area)
        except Exception:
            return 0.0

    def bounding_box(self):
        """回傳與 build123d 相容的 bounding box 物件。

        build123d 的 bounding_box() 回傳含 .min/.max/.size 的物件，
        每個分量有 .X/.Y/.Z。
        FreeCAD 的 BoundBox 有 .XMin/.XMax/.YMin/.YMax/.ZMin/.ZMax。
        """
        bb = self._shape.BoundBox

        class _Vec:
            def __init__(self, x, y, z):
                self.X = x
                self.Y = y
                self.Z = z

        class _BBox:
            def __init__(self, bb):
                self.min = _Vec(bb.XMin, bb.YMin, bb.ZMin)
                self.max = _Vec(bb.XMax, bb.YMax, bb.ZMax)
                self.size = _Vec(bb.XLength, bb.YLength, bb.ZLength)

        return _BBox(bb)


class TopologyTrace:
    """記錄重建期間每個特徵建立或修改了哪些面與邊。

    用於 display_map 的 source_feature_id（feature→face provenance）。
    """

    def __init__(self) -> None:
        self._faces_by_feature: dict[str, list[int]] = {}
        self._edges_by_feature: dict[str, list[int]] = {}
        self._face_to_feature: dict[int, str] = {}
        self._edge_to_feature: dict[int, str] = {}

    def record_faces(self, feature_id: str, face_indices: list[int]) -> None:
        """記錄某特徵產生的面索引。"""
        if feature_id not in self._faces_by_feature:
            self._faces_by_feature[feature_id] = []
        self._faces_by_feature[feature_id].extend(face_indices)
        for idx in face_indices:
            self._face_to_feature[idx] = feature_id

    def record_edges(self, feature_id: str, edge_indices: list[int]) -> None:
        """記錄某特徵產生的邊索引。"""
        if feature_id not in self._edges_by_feature:
            self._edges_by_feature[feature_id] = []
        self._edges_by_feature[feature_id].extend(edge_indices)
        for idx in edge_indices:
            self._edge_to_feature[idx] = feature_id

    def resolve_face_index(self, face_index: int) -> str:
        """由面索引反查特徵 ID。"""
        return self._face_to_feature.get(face_index, "")

    def resolve_edge_index(self, edge_index: int) -> str:
        """由邊索引反查特徵 ID。"""
        return self._edge_to_feature.get(edge_index, "")

    def resolve_face_feature(self, face: Any) -> str:
        """由 face 物件反查特徵 ID（相容 build123d TopologyTrace 介面）。"""
        if isinstance(face, FreeCADFaceProxy):
            return self.resolve_face_index(face._index)
        return ""

    def resolve_edge_feature(self, edge: Any) -> str:
        """由 edge 物件反查特徵 ID（相容 build123d TopologyTrace 介面）。"""
        if isinstance(edge, FreeCADEdgeProxy):
            return self.resolve_edge_index(edge._index)
        return ""

    def faces_created_by(self, feature_id: str) -> list:
        """取得某特徵建立的面索引列表。"""
        return self._faces_by_feature.get(feature_id, [])


class FreeCADAdapter:
    """將 Feature Graph 轉譯成 FreeCAD Part API 建模命令的 Adapter。"""

    def __init__(self) -> None:
        if not FREECAD_AVAILABLE:
            raise ImportError(
                f"FreeCAD 匯入失敗: {_FREECAD_IMPORT_ERROR or '未知原因'}。"
                f"請設定 FREECAD_DIR 環境變數指向 FreeCAD 安裝目錄。"
            )

    def build(self, graph: FeatureGraph) -> Any:
        """依拓撲排序重建整個 Feature Graph，回傳最終實體。"""
        return self.build_with_trace(graph).part

    def build_with_trace(self, graph: FeatureGraph) -> BuildResult:
        """依拓撲排序重建整個 Feature Graph，回傳 BuildResult（含 trace）。"""
        order = graph.topological_sort()
        shapes: dict[str, Any] = {}
        trace = TopologyTrace()

        for fid in order:
            feature = graph.get_feature(fid)
            if feature is None:
                continue
            # v2 狀態機：suppressed/orphan 跳過重建；rollback 之後的特徵跳過
            # （與 build123d adapter 相同語意）
            if feature.state in (FeatureState.SUPPRESSED, FeatureState.ORPHAN):
                continue
            if graph.rollback_position is not None and (feature.order or 0) > graph.rollback_position:
                continue
            feature.rebuild_status = "building"
            try:
                result = self._build_feature(feature, shapes, graph, trace)
                if result is not None:
                    shapes[fid] = result
                feature.rebuild_status = "success"
                feature.error_message = ""

                # 記錄面 provenance
                if result is not None and hasattr(result, "Faces"):
                    face_indices = list(range(len(result.Faces)))
                    trace.record_faces(fid, face_indices)
                    edge_indices = list(range(len(result.Edges)))
                    trace.record_edges(fid, edge_indices)
            except Exception as e:
                feature.rebuild_status = "failed"
                feature.error_message = str(e)
                raise

        # 回傳最後一個產生實體的特徵結果
        final_shape = None
        for fid in reversed(order):
            if fid in shapes:
                final_shape = shapes[fid]
                break

        if final_shape is not None:
            wrapper = FreeCADShapeWrapper(final_shape, trace)
            return BuildResult(part=wrapper, trace=trace)
        return BuildResult(part=None, trace=trace)

    def _build_feature(
        self,
        feature: Feature,
        shapes: dict[str, Any],
        graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """根據特徵類型分派到對應的建構方法。"""
        method = getattr(self, f"_build_{feature.type.value}", None)
        if method is None:
            raise ValueError(f"不支援的特徵類型: {feature.type}")
        return method(feature, shapes, graph, trace)

    def _get_param(self, feature: Feature, key: str, default: float = 0.0) -> float:
        """從特徵參數取得數值，自動換算為 mm。"""
        val = feature.parameters.get(key, default)
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _raw_mm(self, val: Any) -> float:
        if isinstance(val, dict):
            return ParameterValue.from_dict(val).to_mm()
        return float(val)

    def _get_plane_vectors(self, plane_base: str) -> tuple:
        """將 plane base 字串轉為 FreeCAD 法向量和原點。"""
        if plane_base == "XZ":
            return FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(0, 0, 0)  # 法向 Y
        elif plane_base == "YZ":
            return FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 0, 0)  # 法向 X
        else:  # XY
            return FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(0, 0, 0)  # 法向 Z

    def _build_sketch(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """建立草圖，回傳 FreeCAD Wire（或 Face 如果閉合）。"""
        plane_base = feature.plane.get("base", "XY")
        plane_offset = self._raw_mm(feature.plane.get("offset", 0))

        has_closed = self._has_closed_profile(feature)
        if not has_closed:
            return None

        # 收集草圖實體的幾何
        edges = []
        for entity in feature.sketch_entities:
            entity_edges = self._sketch_entity_to_edges(entity, plane_base, plane_offset)
            edges.extend(entity_edges)

        if not edges:
            return None

        # 嘗試建立 face（需要閉合輪廓）
        try:
            wire = Part.Wire(edges)
            face = Part.Face(wire)
            return face
        except Exception:
            # 若無法建立 face，回傳 wire
            try:
                wire = Part.Wire(edges)
                return wire
            except Exception:
                return None

    def _sketch_entity_to_edges(self, entity: dict, plane_base: str, offset: float = 0) -> list:
        """將草圖實體轉為 FreeCAD Edge 列表。"""
        etype = entity.get("entity_type") or entity.get("type")
        params = entity.get("parameters", entity)
        edges = []

        # 座標轉換：草圖座標 → 3D 座標（依 plane_base）
        def to_3d(x: float, y: float) -> FreeCAD.Vector:
            if plane_base == "XZ":
                return FreeCAD.Vector(x, offset, y)
            elif plane_base == "YZ":
                return FreeCAD.Vector(offset, x, y)
            else:  # XY
                return FreeCAD.Vector(x, y, offset)

        if etype == "rectangle":
            w = self._raw_mm(params.get("width", params.get("w", 10)))
            h = self._raw_mm(params.get("height", params.get("h", 10)))
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            x0, y0 = cx - w / 2, cy - h / 2
            x1, y1 = cx + w / 2, cy + h / 2
            p1 = to_3d(x0, y0)
            p2 = to_3d(x1, y0)
            p3 = to_3d(x1, y1)
            p4 = to_3d(x0, y1)
            edges = [
                Part.makeLine(p1, p2),
                Part.makeLine(p2, p3),
                Part.makeLine(p3, p4),
                Part.makeLine(p4, p1),
            ]

        elif etype == "circle":
            r = self._raw_mm(params.get("radius", params.get("r", 5)))
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            center = to_3d(cx, cy)
            # 法向量依 plane_base
            if plane_base == "XZ":
                normal = FreeCAD.Vector(0, 1, 0)
            elif plane_base == "YZ":
                normal = FreeCAD.Vector(1, 0, 0)
            else:
                normal = FreeCAD.Vector(0, 0, 1)
            try:
                edge = Part.makeCircle(r, center, normal)
                edges = [edge]
            except Exception:
                pass

        elif etype == "polygon":
            n = int(params.get("sides", 6))
            r = self._raw_mm(params.get("circumscribed_radius", params.get("radius", 5)))
            cx = self._raw_mm(params.get("center_x", 0))
            cy = self._raw_mm(params.get("center_y", 0))
            pts = []
            for i in range(n):
                angle = 2 * math.pi * i / n
                px = cx + r * math.cos(angle)
                py = cy + r * math.sin(angle)
                pts.append(to_3d(px, py))
            edges = []
            for i in range(n):
                edges.append(Part.makeLine(pts[i], pts[(i + 1) % n]))

        elif etype == "slot":
            w = self._raw_mm(params.get("width", 20))
            h = self._raw_mm(params.get("height", 8))
            cx = self._raw_mm(params.get("center_x", 0))
            cy = self._raw_mm(params.get("center_y", 0))
            # 簡化：用矩形 + 兩端半圓
            x0, y0 = cx - w / 2, cy - h / 2
            x1, y1 = cx + w / 2, cy + h / 2
            r = h / 2
            # 矩形邊
            p1 = to_3d(x0, y0)
            p2 = to_3d(x1 - r, y0)
            p3 = to_3d(x1 - r, y1)
            p4 = to_3d(x0, y1)
            edges = [
                Part.makeLine(p1, p2),
                Part.makeLine(to_3d(x1 - r, y0), to_3d(x1 - r, y1)),
                Part.makeLine(p3, p4),
                Part.makeLine(p4, p1),
            ]
            # 兩端半圓
            if plane_base == "XZ":
                normal = FreeCAD.Vector(0, 1, 0)
            elif plane_base == "YZ":
                normal = FreeCAD.Vector(1, 0, 0)
            else:
                normal = FreeCAD.Vector(0, 0, 1)
            try:
                # 右端半圓
                c_right = to_3d(x1 - r, cy)
                arc_right = Part.makeCircle(r, c_right, normal, -90, 90)
                edges.append(arc_right)
                # 左端半圓
                c_left = to_3d(x0, cy)
                arc_left = Part.makeCircle(r, c_left, normal, 90, 270)
                edges.append(arc_left)
            except Exception:
                pass

        elif etype == "polyline":
            points = params.get("points", [])
            closed = params.get("closed", False)
            if len(points) < 2:
                return []
            pts = [to_3d(self._raw_mm(p[0]), self._raw_mm(p[1])) for p in points]
            edges = []
            n = len(pts) if closed else len(pts) - 1
            for i in range(n):
                edges.append(Part.makeLine(pts[i], pts[(i + 1) % len(pts)]))

        elif etype == "line":
            x1 = self._raw_mm(params.get("x1", 0))
            y1 = self._raw_mm(params.get("y1", 0))
            x2 = self._raw_mm(params.get("x2", 10))
            y2 = self._raw_mm(params.get("y2", 0))
            edges = [Part.makeLine(to_3d(x1, y1), to_3d(x2, y2))]

        return edges

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

    def _build_pad(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """拉伸草圖成實體。"""
        sketch_shape = shapes.get(feature.input) if feature.input else None
        length = self._get_param(feature, "length", 5.0)

        if sketch_shape is None:
            input_feat = graph.get_feature(feature.input) if feature.input else None
            if input_feat and input_feat.type == FeatureType.SKETCH:
                if not self._has_closed_profile(input_feat):
                    raise ValueError("草圖未閉合：需要至少一個閉合輪廓才能拉伸")
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        # 確保是 Face（Wire 需先建面）
        if isinstance(sketch_shape, Part.Wire) or (hasattr(sketch_shape, "ShapeType") and sketch_shape.ShapeType == "Wire"):
            try:
                sketch_shape = Part.Face(sketch_shape)
            except Exception:
                pass

        # 取得草圖法向量
        input_feat = graph.get_feature(feature.input) if feature.input else None
        plane_base = "XY"
        if input_feat and input_feat.type == FeatureType.SKETCH:
            plane_base = input_feat.plane.get("base", "XY")

        if plane_base == "XZ":
            dir_vec = FreeCAD.Vector(0, 1, 0)
        elif plane_base == "YZ":
            dir_vec = FreeCAD.Vector(1, 0, 0)
        else:
            dir_vec = FreeCAD.Vector(0, 0, 1)

        # 拉伸
        extruded = sketch_shape.extrude(dir_vec.multiply(length))
        return extruded

    def _build_pocket(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """切除材料。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        depth = self._get_param(feature, "depth", 0)
        through_all = feature.parameters.get("through_all", False)
        diameter = self._get_param(feature, "diameter", 0)

        # 位置列表模式
        positions = feature.parameters.get("positions", [])
        if positions and diameter > 0:
            result = base_shape
            for pos_xy in positions:
                px = self._raw_mm(pos_xy[0]) if isinstance(pos_xy, list) else float(pos_xy)
                py = self._raw_mm(pos_xy[1]) if isinstance(pos_xy, list) else 0.0
                h = 10000 if through_all else depth
                cyl = Part.makeCylinder(diameter / 2, h, FreeCAD.Vector(px, py, -h / 2), FreeCAD.Vector(0, 0, 1))
                result = result.cut(cyl)
            return result

        # 草圖參照模式
        sketch_shape = None
        for ref in feature.references:
            if ref in shapes:
                sketch_shape = shapes[ref]
                break

        if sketch_shape is not None:
            if isinstance(sketch_shape, Part.Wire) or (hasattr(sketch_shape, "ShapeType") and sketch_shape.ShapeType == "Wire"):
                try:
                    sketch_shape = Part.Face(sketch_shape)
                except Exception:
                    pass

            h = 10000 if through_all else depth
            cut_shape = sketch_shape.extrude(FreeCAD.Vector(0, 0, h))
            if through_all:
                # 双向切除
                cut_shape2 = sketch_shape.extrude(FreeCAD.Vector(0, 0, -h))
                cut_shape = cut_shape.fuse(cut_shape2)
            return base_shape.cut(cut_shape)

        raise ValueError("pocket 需要草圖參照或位置列表")

    def _build_hole(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """建立孔。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        diameter = self._get_param(feature, "diameter", 5)
        depth = self._get_param(feature, "depth", 0)
        through_all = feature.parameters.get("through_all", False)
        positions = feature.parameters.get("positions", [])

        if not positions:
            # 單一位置
            cx = self._get_param(feature, "center_x", 0)
            cy = self._get_param(feature, "center_y", 0)
            positions = [[cx, cy]]

        result = base_shape
        for pos_xy in positions:
            px = self._raw_mm(pos_xy[0]) if isinstance(pos_xy, list) else float(pos_xy)
            py = self._raw_mm(pos_xy[1]) if isinstance(pos_xy, list) else 0.0
            h = 10000 if through_all else depth
            cyl = Part.makeCylinder(diameter / 2, h, FreeCAD.Vector(px, py, -1), FreeCAD.Vector(0, 0, 1))
            result = result.cut(cyl)

        return result

    def _build_fillet(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """圓角。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        radius = self._get_param(feature, "radius", 2.0)
        edge_selector = feature.parameters.get("edge_selector", "all")

        # 選邊
        if edge_selector == "all":
            edges_to_fillet = base_shape.Edges
        elif edge_selector == "top":
            # 頂邊：Z 值最大的邊
            max_z = max(e.Vertexes[0].Point.z for e in base_shape.Edges if e.Vertexes)
            edges_to_fillet = [e for e in base_shape.Edges if
                             all(abs(v.Point.z - max_z) < 0.01 for v in e.Vertexes)]
        elif edge_selector == "vertical":
            # 垂直邊：方向接近 Z 軸
            edges_to_fillet = []
            for e in base_shape.Edges:
                try:
                    t = e.tangentAt(0)
                    if abs(t.z) > 0.9:
                        edges_to_fillet.append(e)
                except Exception:
                    pass
        else:
            edges_to_fillet = base_shape.Edges

        if not edges_to_fillet:
            raise ValueError(f"找不到符合條件的邊: {edge_selector}")

        try:
            result = base_shape.makeFillet(radius, edges_to_fillet)
            return result
        except Exception as e:
            raise ValueError(f"圓角失敗（半徑 {radius}mm 可能過大）: {e}")

    def _build_chamfer(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """倒角。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        distance = self._get_param(feature, "distance", 1.0)
        edge_selector = feature.parameters.get("edge_selector", "all")

        if edge_selector == "all":
            edges_to_chamfer = base_shape.Edges
        else:
            edges_to_chamfer = base_shape.Edges

        try:
            result = base_shape.makeChamfer(distance, edges_to_chamfer)
            return result
        except Exception as e:
            raise ValueError(f"倒角失敗: {e}")

    def _build_revolve(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """旋轉（headless FreeCAD 可能產生零體積實體——已知限制）。"""
        sketch_shape = shapes.get(feature.input) if feature.input else None
        if sketch_shape is None:
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        angle = self._get_param(feature, "angle", 360.0)
        axis_str = feature.parameters.get("axis", "Z")

        axis_map = {
            "X": FreeCAD.Vector(1, 0, 0),
            "Y": FreeCAD.Vector(0, 1, 0),
            "Z": FreeCAD.Vector(0, 0, 1),
        }
        axis_vec = axis_map.get(axis_str, FreeCAD.Vector(0, 0, 1))

        revolved = sketch_shape.revolve(FreeCAD.Vector(0, 0, 0), axis_vec, angle)
        # FreeCAD headless revolve from Face may produce zero-volume Solid.
        # This is a known limitation — the resulting shape is geometrically
        # correct (has faces/edges) but lacks internal volume computation.
        return revolved

    def _build_linear_pattern(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """線性陣列。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        count = int(feature.parameters.get("count", 2))
        spacing = self._get_param(feature, "spacing", 10.0)
        axis_str = feature.parameters.get("axis", "X")

        axis_map = {
            "X": FreeCAD.Vector(1, 0, 0),
            "Y": FreeCAD.Vector(0, 1, 0),
            "Z": FreeCAD.Vector(0, 0, 1),
        }
        axis_vec = axis_map.get(axis_str, FreeCAD.Vector(1, 0, 0))

        result = base_shape
        for i in range(1, count):
            offset = axis_vec.multiply(spacing * i)
            copy = base_shape.copy()
            copy.translate(offset)
            result = result.fuse(copy)
        return result

    def _build_circular_pattern(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """圓周陣列。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        count = int(feature.parameters.get("count", 6))
        radius = self._get_param(feature, "radius", 20.0)

        result = base_shape
        for i in range(1, count):
            angle = 2 * math.pi * i / count
            offset = FreeCAD.Vector(radius * math.cos(angle), radius * math.sin(angle), 0)
            copy = base_shape.copy()
            copy.translate(offset)
            result = result.fuse(copy)
        return result