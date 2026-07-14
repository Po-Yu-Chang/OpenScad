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
from ..sketch_solver import Constraint as _SketchConstraint, solve as _solve_sketch_constraints


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
        """回傳體積（mm³），與 build123d Part.volume 相容。

        WP1-0R2 修復（地雷 #19）：先前遇例外回傳 0.0，會把「算不出體積」
        掩蓋成「體積確實是 0」——兩者對呼叫端（validators._check_volume 等）
        意義完全不同，前者該是警告、後者才是「零體積實體」錯誤。改為讓例外
        往上浮現，由呼叫端自行決定如何處理（現有呼叫端多半已有 try/except，
        會正確分流成警告或結構化 500，不會再靜默回報錯誤的 0.0）。
        """
        return float(self._shape.Volume)

    @property
    def area(self) -> float:
        """回傳表面積（mm²），與 build123d Part.area 相容。同上，例外不再吞掉。"""
        return float(self._shape.Area)

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
        
        # WP1-3: datum: 引用——從 graph.reference_geometry 取得 derived_geometry
        if isinstance(plane_base, str) and plane_base.startswith("datum:"):
            datum_id = plane_base[6:]
            datum_found = False
            for rg in graph.reference_geometry:
                if rg.get("id") == datum_id and rg.get("kind") == "plane":
                    # 對於 FreeCAD，我們將使用座標變換來處理 datum 平面
                    # 這裡先記錄 datum 平面資訊，後續在 _sketch_entity_to_edges 中使用
                    datum_found = True
                    break
            if not datum_found:
                raise ValueError(f"找不到 datum 平面: {datum_id}")

        has_closed = self._has_closed_profile(feature)
        if not has_closed:
            return None

        # WP1-2R 紅線修復：FreeCAD 引擎有真正的座標求解能力（cp311 路徑），
        # 若草圖帶 constraints，rebuild 前必須重新求解——不得沿用可能已過期
        # 的座標。求解衝突（互斥約束）時中止 rebuild，而非靜默忽略約束。
        entities_to_build = feature.sketch_entities
        if feature.constraints:
            solved = _solve_sketch_constraints(
                feature.sketch_entities,
                [_SketchConstraint.from_dict(c) for c in feature.constraints],
            )
            if solved["solver_status"]["state"] == "over":
                raise ValueError(
                    f"草圖 {feature.feature_id} 約束衝突"
                    f"（衝突: {solved['solver_status']['conflicts']}）——"
                    f"rebuild 中止，不使用未收斂座標。請刪除衝突約束後重試。"
                )
            entities_to_build = solved["entities"]

        # 收集草圖實體的幾何
        edges = []
        for entity in entities_to_build:
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
            # 處理 datum 平面
            if isinstance(plane_base, str) and plane_base.startswith("datum:"):
                # 對於 datum 平面，暫時使用預設的 XY 平面處理
                # 未來可以從 reference_geometry 取得更精確的變換矩陣
                return FreeCAD.Vector(x, y, offset)
            elif plane_base == "XZ":
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

        elif etype == "arc":
            # WP1-2R：與 build123d adapter 對齊——freecad 先前缺這個分支
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            r = self._raw_mm(params.get("radius", params.get("r", 5)))
            start_angle = float(params.get("start_angle", 0))
            end_angle = float(params.get("end_angle", 90))
            center = to_3d(cx, cy)
            if plane_base == "XZ":
                normal = FreeCAD.Vector(0, 1, 0)
            elif plane_base == "YZ":
                normal = FreeCAD.Vector(1, 0, 0)
            else:
                normal = FreeCAD.Vector(0, 0, 1)
            try:
                edges = [Part.makeCircle(r, center, normal, start_angle, end_angle)]
            except Exception:
                pass

        return edges

    def _line_arc_endpoints(self, entity: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """算出 line/arc 實體的兩端點座標，供閉合輪廓偵測用（與 build123d
        adapter 對齊）。"""
        etype = entity.get("entity_type") or entity.get("type")
        params = entity.get("parameters", entity)
        if etype == "line":
            x1 = self._raw_mm(params.get("x1", 0))
            y1 = self._raw_mm(params.get("y1", 0))
            x2 = self._raw_mm(params.get("x2", 10))
            y2 = self._raw_mm(params.get("y2", 0))
            return (x1, y1), (x2, y2)
        if etype == "arc":
            cx = self._raw_mm(params.get("center_x", params.get("x", 0)))
            cy = self._raw_mm(params.get("center_y", params.get("y", 0)))
            r = self._raw_mm(params.get("radius", params.get("r", 5)))
            start_rad = math.radians(float(params.get("start_angle", 0)))
            end_rad = math.radians(float(params.get("end_angle", 90)))
            p1 = (cx + math.cos(start_rad) * r, cy + math.sin(start_rad) * r)
            p2 = (cx + math.cos(end_rad) * r, cy + math.sin(end_rad) * r)
            return p1, p2
        return None

    @staticmethod
    def _segments_form_closed_loop(segments: list[tuple[tuple[float, float], tuple[float, float]]], tol: float = 1e-4) -> bool:
        """端點兩兩配對即視為封閉迴圈（與 build123d adapter 對齊，理由見該處）。"""
        endpoints = [p for seg in segments for p in seg]
        used = [False] * len(endpoints)
        for i, p in enumerate(endpoints):
            if used[i]:
                continue
            match = None
            for j in range(i + 1, len(endpoints)):
                if used[j]:
                    continue
                q = endpoints[j]
                if abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol:
                    match = j
                    break
            if match is None:
                return False
            used[i] = True
            used[match] = True
        return True

    def _has_closed_profile(self, sketch_feature: Feature) -> bool:
        """檢查草圖是否包含至少一個閉合輪廓（含 line/arc 端點兩兩相接的情況，
        見 build123d adapter 對應方法的說明）。"""
        line_arc_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entity in sketch_feature.sketch_entities:
            etype = entity.get("entity_type") or entity.get("type")
            params = entity.get("parameters", entity)
            if etype in ("rectangle", "circle", "polygon", "slot"):
                return True
            if etype in ("line", "arc"):
                ep = self._line_arc_endpoints(entity)
                if ep:
                    line_arc_segments.append(ep)
                continue
            if etype == "polyline" and params.get("closed", False):
                return True
        if line_arc_segments and self._segments_form_closed_loop(line_arc_segments):
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

    def _select_edges(self, base_shape: Any, edge_selector: str) -> list:
        """依 edge_selector 選邊——fillet/chamfer 共用（WP1-0R2 修復：
        chamfer 原本 all/else 兩分支完全相同，edge_selector 參數被忽略是死碼）。"""
        if edge_selector == "all":
            return list(base_shape.Edges)
        elif edge_selector == "top":
            # 頂邊：Z 值最大的邊
            max_z = max(e.Vertexes[0].Point.z for e in base_shape.Edges if e.Vertexes)
            return [e for e in base_shape.Edges if
                    all(abs(v.Point.z - max_z) < 0.01 for v in e.Vertexes)]
        elif edge_selector == "vertical":
            # 垂直邊：方向接近 Z 軸
            edges = []
            for e in base_shape.Edges:
                try:
                    t = e.tangentAt(0)
                    if abs(t.z) > 0.9:
                        edges.append(e)
                except Exception:
                    pass
            return edges
        return list(base_shape.Edges)

    def _build_fillet(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """圓角。

        WP1-0R2 修復：邊選擇器參數鍵原本讀 `edge_selector`，但 build123d
        adapter／範例專案／schema 實際用的鍵是 `edges`（見
        `needle-box-5x10` 的 `fillet_corners`：`{"edges": "top"}`）——鍵名
        對不上導致 freecad 引擎永遠悄悄退回 "all"，對複雜幾何（如 cell
        grid）用小半徑對所有邊導圓角就會失敗。改讀 `edges`，`edge_selector`
        仍保留為相容 fallback（避免任何既有呼叫端因此壞掉）。
        """
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        radius = self._get_param(feature, "radius", 2.0)
        edge_selector = feature.parameters.get("edges", feature.parameters.get("edge_selector", "all"))
        edges_to_fillet = self._select_edges(base_shape, edge_selector)

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
        """倒角。

        WP1-0R2 修復：邊選擇器鍵同 fillet 改讀 `edges`（fallback
        `edge_selector`）；倒角距離鍵原本讀 `distance`，但 build123d
        adapter 讀的是 `length`——同一份 JSON 餵給兩個引擎會取到不同大小
        的倒角。改讀 `length`，`distance` 保留為相容 fallback。
        """
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        size_key = "length" if "length" in feature.parameters else "distance"
        distance = self._get_param(feature, size_key, 1.0)
        edge_selector = feature.parameters.get("edges", feature.parameters.get("edge_selector", "all"))
        edges_to_chamfer = self._select_edges(base_shape, edge_selector)

        if not edges_to_chamfer:
            raise ValueError(f"找不到符合條件的邊: {edge_selector}")

        try:
            result = base_shape.makeChamfer(distance, edges_to_chamfer)
            return result
        except Exception as e:
            raise ValueError(f"倒角失敗: {e}")

    def _build_revolve(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """旋轉。

        WP1-0R2 修復：舊碼旋轉軸預設 "Z"，與草圖平面完全無關——若草圖在 XY
        平面（法向即 Z），繞 Z 軸旋轉等於繞著垂直於草圖平面的軸旋轉，輪廓
        根本沒有掃出體積，OCC 靜默回傳零體積實體（"零體積已知限制"其實是
        這個 axis 參數設計錯誤，不是 FreeCAD headless 的固有限制——同一組
        資料餵給 build123d 用 axis=X 也會因為輪廓中心恰好落在旋轉軸上而
        raise，兩引擎在退化幾何下都不該裝作成功）。

        改為比照 build123d：旋轉軸一律從輸入草圖的 plane 推導（XY/XZ 平面
        用 X 軸、YZ 平面用 Y 軸——這兩者都落在草圖平面內，才是合法的旋轉
        軸），不再吃自由格式的 "axis" 參數。旋轉後驗證體積，退化（~0）就
        raise，不得靜默回傳零體積「成功」。
        """
        sketch_shape = shapes.get(feature.input) if feature.input else None
        if sketch_shape is None:
            raise ValueError(f"找不到輸入草圖: {feature.input}")

        angle = self._get_param(feature, "angle", 360.0)

        input_feat = graph.get_feature(feature.input) if feature.input else None
        plane_base = "XY"
        if input_feat and input_feat.type == FeatureType.SKETCH:
            plane_base = input_feat.plane.get("base", "XY")
        axis_vec = FreeCAD.Vector(0, 1, 0) if plane_base == "YZ" else FreeCAD.Vector(1, 0, 0)

        try:
            revolved = sketch_shape.revolve(FreeCAD.Vector(0, 0, 0), axis_vec, angle)
        except Exception as e:
            raise ValueError(
                f"旋轉失敗：輪廓可能與旋轉軸相交或形狀退化（{e}）"
            )
        if abs(revolved.Volume) < 1e-6:
            raise ValueError(
                "旋轉產生零體積實體——輪廓可能與旋轉軸相交（例如輪廓中心恰好"
                "落在旋轉軸上），須調整草圖位置使輪廓完全偏離旋轉軸。"
            )
        return revolved

    def _build_shell(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """薄殼。

        WP1-0R2 新增。與 build123d adapter 對齊：目前 schema 的 `shell`
        特徵只有 `thickness` 參數，**沒有「選面開口」參數**——build123d 端
        呼叫 `offset(part, amount=-thickness)`、不指定 openings，實測結果
        其實是整個實體均勻向內收縮（erosion），不是真正挖空、留有開口的
        中空殼（沒有內壁、沒有開口）。這裡用 FreeCAD 的 `makeOffsetShape`
        （同為「不挑面的 3D offset」）複製一致的行為以維持雙引擎 parity，
        數值上與 build123d 的結果一致（同一個 32×45×7.5 盒子、thickness=2
        兩邊都得到 4018mm³）。

        **已知限制（誠實記錄，非本次修復範圍）**：這代表 `shell` 目前在
        兩個引擎都不是「真正的中空殼」，schema 需要新增可選的開口面
        選擇器才能做出有實際內部空腔、可用的殼件——這是設計層面的擴充
        （新參數＋LLM catalog＋schema），不是單純的 FreeCAD 對齊工作，
        故不在本次範圍內處理，留待後續討論。
        """
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到基礎實體: {feature.input}")

        thickness = self._get_param(feature, "thickness", 1.0)
        try:
            result = base_shape.makeOffsetShape(-thickness, 1e-3)
        except Exception as e:
            raise ValueError(f"薄殼失敗（厚度 {thickness}mm 可能過大）: {e}")
        if abs(result.Volume) < 1e-6:
            raise ValueError(f"薄殼產生零體積實體——厚度 {thickness}mm 可能過大")
        return result

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

    # ── WP1-0R2：FreeCAD 特徵 parity 補完 ──

    def _build_mirror(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """鏡像。與 build123d adapter 對齊：固定鏡射面為 XZ 平面（法向 Y），
        結果與來源 fuse。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到來源: {feature.input}")
        mirrored = base_shape.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))
        return mirrored.fuse(base_shape)

    def _build_boolean_union(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        a = shapes.get(feature.references[0]) if len(feature.references) > 0 else None
        b = shapes.get(feature.references[1]) if len(feature.references) > 1 else None
        if a is not None and b is not None:
            return a.fuse(b)
        return a if a is not None else b

    def _build_boolean_difference(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        a = shapes.get(feature.references[0]) if len(feature.references) > 0 else None
        b = shapes.get(feature.references[1]) if len(feature.references) > 1 else None
        if a is not None and b is not None:
            return a.cut(b)
        return a

    def _build_boolean_intersection(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        a = shapes.get(feature.references[0]) if len(feature.references) > 0 else None
        b = shapes.get(feature.references[1]) if len(feature.references) > 1 else None
        if a is not None and b is not None:
            # FreeCAD Part.Shape 的交集方法叫 common（不是 intersect）
            return a.common(b)
        return a

    def _build_sweep(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """掃描：輪廓草圖沿路徑草圖掃描成實體（與 build123d adapter 對齊的
        input/references 慣例：input=輪廓草圖，references[0]=路徑草圖）。

        路徑草圖通常是開放輪廓（不會被 `_build_sketch` 收進 shapes——見
        `_has_closed_profile`），所以路徑改用
        `_sketch_entity_to_edges()` 直接從路徑草圖的 sketch_entities 重建，
        跟 `_build_sketch` 建立一般草圖用的是同一套 2D→3D 轉換。
        """
        profile_shape = shapes.get(feature.input) if feature.input else None
        if profile_shape is None:
            raise ValueError(f"找不到輪廓草圖: {feature.input}")

        path_fid = feature.references[0] if feature.references else None
        if not path_fid:
            raise ValueError("sweep 需要 references 指定路徑草圖")
        path_feat = graph.get_feature(path_fid)
        if path_feat is None:
            raise ValueError(f"找不到路徑草圖: {path_fid}")

        path_plane = path_feat.plane.get("base", "XY")
        path_edges = []
        for entity in path_feat.sketch_entities:
            path_edges.extend(self._sketch_entity_to_edges(entity, path_plane, 0))
        if not path_edges:
            raise ValueError("路徑草圖沒有可用的線段")
        path_wire = Part.Wire(path_edges)

        # makePipeShell 需要輪廓的 Wire（外框），profile_shape 若是 Face 取
        # OuterWire；若本身已是 Wire 就直接用。
        profile_wire = getattr(profile_shape, "OuterWire", profile_shape)
        try:
            result = path_wire.makePipeShell([profile_wire], True, False)
        except Exception as e:
            raise ValueError(f"掃描失敗: {e}")
        return result

    def _build_loft(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """放樣：在多個輪廓草圖之間建立漸變實體（input=第一輪廓、
        references=後續輪廓，與 build123d adapter 對齊）。"""
        profile_ids = ([feature.input] if feature.input else []) + list(feature.references)
        if len(profile_ids) < 2:
            raise ValueError("loft 需要至少兩個輪廓草圖")

        wires = []
        for fid in profile_ids:
            shape = shapes.get(fid)
            if shape is None:
                raise ValueError(f"找不到輪廓草圖: {fid}")
            wires.append(getattr(shape, "OuterWire", shape))

        try:
            result = Part.makeLoft(wires, True)
        except Exception as e:
            raise ValueError(f"放樣失敗: {e}")
        return result

    # ── WP1-6 六型（FreeCAD 對齊 build123d，含其現有簡化行為）──

    def _build_draft(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """拔模——與 build123d adapter 對齊：目前簡化為 no-op（不改變幾何）。

        完整拔模需要面選取＋拔模方向向量，超出目前 display_map 選面能力，
        兩引擎現況一致地待後續補強（不是 FreeCAD 特有落後）。
        """
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到來源特徵: {feature.input}")
        return base_shape

    def _build_rib(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """加強肋——輪廓拉伸＋fuse 到現有實體（與 build123d adapter 對齊）。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        thickness = self._get_param(feature, "thickness", 5.0)
        direction = feature.parameters.get("direction", "symmetric")

        sketch_id = feature.parameters.get("sketch_id") or feature.input
        sketch_feat = graph.get_feature(sketch_id) if sketch_id else None
        if sketch_feat is None or sketch_feat.type != FeatureType.SKETCH:
            return base_shape

        sketch_shape = shapes.get(sketch_id)
        if sketch_shape is None:
            sketch_shape = self._build_sketch(sketch_feat, shapes, graph, trace)
        if sketch_shape is None:
            return base_shape
        if isinstance(sketch_shape, Part.Wire) or (hasattr(sketch_shape, "ShapeType") and sketch_shape.ShapeType == "Wire"):
            try:
                sketch_shape = Part.Face(sketch_shape)
            except Exception:
                pass

        dir_vec = self._extrude_direction(sketch_feat.plane.get("base", "XY"))
        if direction == "symmetric":
            rib1 = sketch_shape.extrude(dir_vec.multiply(thickness / 2))
            rib2 = sketch_shape.extrude(dir_vec.multiply(-thickness / 2))
            rib = rib1.fuse(rib2)
        elif direction == "reverse":
            rib = sketch_shape.extrude(dir_vec.multiply(-thickness))
        else:
            rib = sketch_shape.extrude(dir_vec.multiply(thickness))

        if base_shape is not None:
            return base_shape.fuse(rib)
        return rib

    def _build_thin(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """薄件拉伸——拉伸時同時薄殼（與 build123d adapter 對齊；薄殼行為
        同 `_build_shell`，是均勻內縮，非真正開口中空殼，見該處說明）。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        length = self._get_param(feature, "length", 10.0)
        thickness = self._get_param(feature, "thickness", 2.0)

        sketch_feat = graph.get_feature(feature.input) if feature.input else None
        if sketch_feat is None or sketch_feat.type != FeatureType.SKETCH:
            return base_shape

        sketch_shape = shapes.get(feature.input)
        if sketch_shape is None:
            sketch_shape = self._build_sketch(sketch_feat, shapes, graph, trace)
        if sketch_shape is None:
            return base_shape
        if isinstance(sketch_shape, Part.Wire) or (hasattr(sketch_shape, "ShapeType") and sketch_shape.ShapeType == "Wire"):
            try:
                sketch_shape = Part.Face(sketch_shape)
            except Exception:
                pass

        dir_vec = self._extrude_direction(sketch_feat.plane.get("base", "XY"))
        extruded = sketch_shape.extrude(dir_vec.multiply(length))
        try:
            return extruded.makeOffsetShape(-thickness, 1e-3)
        except Exception:
            return extruded

    def _extrude_direction(self, plane_base: str):
        if plane_base == "XZ":
            return FreeCAD.Vector(0, 1, 0)
        elif plane_base == "YZ":
            return FreeCAD.Vector(1, 0, 0)
        return FreeCAD.Vector(0, 0, 1)

    def _build_variable_fillet(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """變化圓角——與 build123d adapter 對齊：目前簡化為單一半徑（取
        radii[0]），不是逐點真正變化的圓角（兩引擎現況一致的已知簡化）。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到來源特徵: {feature.input}")

        radii = feature.parameters.get("radii", [])
        if isinstance(radii, list) and len(radii) >= 1:
            radius = float(radii[0])
        else:
            radius = self._get_param(feature, "radius", 2.0)

        edges = base_shape.Edges
        if not edges:
            return base_shape
        try:
            return base_shape.makeFillet(radius, edges)
        except Exception as e:
            raise ValueError(f"變化圓角失敗（半徑 {radius}mm 可能過大）: {e}")

    def _build_countersink(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """沉頭孔——與 build123d adapter 對齊：沉頭部分用直筒圓柱模擬（非
        真正的錐形沉頭），是 build123d 參考實作本身的簡化，非 FreeCAD 特有
        落後（誠實記錄於 LIMITATIONS.md，兩引擎待後續一起補真錐形）。"""
        base_shape = shapes.get(feature.input) if feature.input else None
        if base_shape is None:
            raise ValueError(f"找不到來源特徵: {feature.input}")

        diameter = self._get_param(feature, "diameter", 5.0)
        countersink_diameter = self._get_param(feature, "countersink_diameter", 10.0)
        countersink_angle = self._get_param(feature, "countersink_angle_deg", 90.0)
        positions = feature.parameters.get("positions", [[0, 0]])

        result = base_shape
        for pos in positions:
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                x, y = float(pos[0]), float(pos[1])
                hole_cyl = Part.makeCylinder(diameter / 2, 10000, FreeCAD.Vector(x, y, -5000), FreeCAD.Vector(0, 0, 1))
                result = result.cut(hole_cyl)
                cs_radius = countersink_diameter / 2
                cs_depth = (countersink_diameter - diameter) / 2 / math.tan(math.radians(countersink_angle / 2))
                cs_cyl = Part.makeCylinder(cs_radius, cs_depth, FreeCAD.Vector(x, y, 0), FreeCAD.Vector(0, 0, 1))
                result = result.cut(cs_cyl)
        return result

    def _build_cosmetic_thread(
        self, feature: Feature, shapes: dict[str, Any], graph: FeatureGraph,
        trace: TopologyTrace,
    ) -> Any:
        """裝飾牙線——不改變幾何，僅供顯示／標記用途（與 build123d adapter
        對齊）。回傳 None，rebuild 沿用上一個特徵的結果。"""
        return None