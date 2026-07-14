"""Persistent Reference 語意化解析器（WP0-4）。

將 v2 語意查詢參照解析為 build123d Face/Edge 物件。
向下相容舊 edge selector DSL（字串或 dict 格式）。

v2 參照格式：
{
  "ref_version": 2,
  "source_feature_id": "pad1",
  "body": "body1",
  "topology_type": "face" | "edge",
  "query": {
    "intent": "top_planar_face | hole_cylindrical_face | outer_vertical_edges | ...",
    "filters": {
      "surface_type": "plane" | "cylinder" | "cone" | "sphere" | "torus" | "other",
      "normal": [0, 0, 1],
      "radius_mm": null,
      "area_mm2_range": [100, 5000]
    }
  },
  "disambiguation": {
    "centroid_hint": [30, 20, 10],
    "adjacency_signature": "sha1-..."
  }
}

解析結果：
- 命中 1 個 → 回傳該 Face/Edge
- 命中 0 個 → 擲出 ReferenceLostError
- 命中 ≥2 個且 disambiguation 無法收斂 → 擲出 ReferenceAmbiguousError（含候選清單）
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters.build123d_adapter import TopologyTrace
    from .feature_graph import FeatureGraph


class ReferenceLostError(Exception):
    """參照目標不存在（面/邊已消失）。"""

    def __init__(self, ref: dict, message: str = ""):
        self.ref = ref
        self.error_code = "REFERENCE_LOST"
        super().__init__(message or f"參照目標不存在: {ref.get('source_feature_id', '?')}")


class ReferenceAmbiguousError(Exception):
    """參照目標有兩個以上等價候選，無法自動收斂。"""

    def __init__(self, ref: dict, candidates: list, message: str = ""):
        self.ref = ref
        self.candidates = candidates
        self.error_code = "REFERENCE_AMBIGUOUS"
        super().__init__(
            message or f"參照歧義: {len(candidates)} 個候選，無法收斂 (source={ref.get('source_feature_id', '?')})"
        )


# GeomType → surface_type 字串——與 exporters 共用同一張表
# （exporters 版含 FreeCAD 字串路徑，避免兩份表漂移導致 FreeCAD 面全被判成 other）
from .exporters import _geom_type_to_surface_type as _geom_type_to_str


def _normal_to_list(normal: Any) -> list[float]:
    """將 build123d Vector 轉為 [x, y, z] list。"""
    try:
        return [round(normal.X, 4), round(normal.Y, 4), round(normal.Z, 4)]
    except Exception:
        return [0.0, 0.0, 0.0]


def _vectors_equal(a: list[float], b: list[float], tol: float = 0.01) -> bool:
    """比較兩個 [x,y,z] 是否在容差內相等。"""
    return all(abs(a[i] - b[i]) < tol for i in range(min(len(a), len(b))))


def _centroid_distance(a: list[float], b: list[float]) -> float:
    """計算兩個 centroid 的歐氏距離。"""
    return sum((a[i] - b[i]) ** 2 for i in range(min(len(a), len(b)))) ** 0.5


# ── Intent 名稱 → 預設 filter 對應表 ──
_INTENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "top_planar_face": {
        "surface_type": "plane",
        "normal": [0, 0, 1],
    },
    "bottom_planar_face": {
        "surface_type": "plane",
        "normal": [0, 0, -1],
    },
    "front_planar_face": {
        "surface_type": "plane",
        "normal": [0, -1, 0],
    },
    "back_planar_face": {
        "surface_type": "plane",
        "normal": [0, 1, 0],
    },
    "right_planar_face": {
        "surface_type": "plane",
        "normal": [1, 0, 0],
    },
    "left_planar_face": {
        "surface_type": "plane",
        "normal": [-1, 0, 0],
    },
    "hole_cylindrical_face": {
        "surface_type": "cylinder",
    },
    "outer_vertical_edges": {
        "axis": "vertical",
    },
    "top_edges": {
        "location": "top",
    },
    "bottom_edges": {
        "location": "bottom",
    },
}


def resolve_reference(
    part: Any,
    trace: "TopologyTrace | None",
    ref: Any,
    graph: "FeatureGraph | None" = None,
) -> Any:
    """解析語意化參照，回傳 build123d Face 或 Edge（或 list[Face/Edge]）。

    支援兩種格式：
    1. v2 語意查詢（dict with ref_version=2）
    2. 舊 edge selector DSL（字串或 dict）——fallback

    Args:
        part: build123d Part
        trace: TopologyTrace（含 feature→face/edge provenance）
        ref: v2 參照 dict 或舊 selector
        graph: FeatureGraph（用於 provenance 查詢）

    Returns:
        Face / Edge / list[Face/Edge]

    Raises:
        ReferenceLostError: 命中 0 個
        ReferenceAmbiguousError: 命中 ≥2 且無法收斂
    """
    if part is None:
        raise ReferenceLostError(ref if isinstance(ref, dict) else {}, "模型為空")

    # v2 語意查詢
    if isinstance(ref, dict) and ref.get("ref_version") == 2:
        return _resolve_v2_reference(part, trace, ref, graph)

    # 舊 selector（字串或 dict）——直接回傳，由呼叫端處理
    # 這裡不做解析，因為舊 selector 的解析已在 _select_edges / _resolve_edge_selector 中
    return ref


def _resolve_v2_reference(
    part: Any,
    trace: "TopologyTrace | None",
    ref: dict[str, Any],
    graph: "FeatureGraph | None",
) -> Any:
    """解析 v2 語意查詢參照。"""
    topology_type = ref.get("topology_type", "face")
    query = ref.get("query", {})
    filters = dict(query.get("filters", {}))

    # Intent → 預設 filter 補充（使用者 filter 優先）
    intent = query.get("intent", "")
    if intent in _INTENT_DEFAULTS:
        for k, v in _INTENT_DEFAULTS[intent].items():
            if k not in filters:
                filters[k] = v

    if topology_type == "face":
        return _resolve_face_reference(part, trace, ref, filters)
    elif topology_type == "edge":
        return _resolve_edge_reference(part, trace, ref, filters)
    else:
        raise ReferenceLostError(ref, f"未知的 topology_type: {topology_type}")


def _resolve_face_reference(
    part: Any,
    trace: "TopologyTrace | None",
    ref: dict[str, Any],
    filters: dict[str, Any],
) -> Any:
    """解析面參照。"""
    try:
        faces = list(part.faces())
    except Exception:
        raise ReferenceLostError(ref, "無法取得面列表")

    # source_feature_id 篩選——只查詢由該特徵產生的面
    #
    # WP-S1 修復：build123d 的 TopologyTrace.faces_created_by() 回傳的是
    # 「Face 物件清單」，freecad 的卻是「面索引（int）清單」——兩邊格式
    # 不一樣，原本這裡一律用 `_faces_equal(f, tf)`（Face vs Face 比較）
    # 去比對，對 freecad 來說等於拿 Face 物件跟整數比較，`is_equal()` 內部
    # 出例外被 `except Exception: return False` 吞掉，篩選結果永遠是空
    # 集合——freecad 引擎下任何帶 source_feature_id 的語意查詢（包含 datum
    # 平面 offset 解析）都會直接判定「參照不存在」。改為先偵測
    # trace_faces 裡裝的是索引還是物件，兩種都能正確比對。
    source_fid = ref.get("source_feature_id", "")
    if source_fid and trace is not None:
        trace_faces = trace.faces_created_by(source_fid)
        if trace_faces:
            if all(isinstance(tf, int) for tf in trace_faces):
                # freecad：索引比對（FreeCADFaceProxy 有 _index 屬性）
                idx_set = set(trace_faces)
                faces = [f for f in faces if getattr(f, "_index", None) in idx_set]
            else:
                # build123d：Face 物件比對
                faces = [f for f in faces if any(_faces_equal(f, tf) for tf in trace_faces)]

    # surface_type 篩選
    st = filters.get("surface_type")
    if st:
        faces = [f for f in faces if _geom_type_to_str(f.geom_type) == st]

    # normal 篩選（只適用 plane 面）
    normal = filters.get("normal")
    if normal:
        faces = [
            f for f in faces
            if _face_normal_matches(f, normal)
        ]

    # radius_mm 篩選（cylinder/cone/sphere/torus）
    radius = filters.get("radius_mm")
    if radius is not None and radius > 0:
        faces = [f for f in faces if _face_radius_matches(f, radius)]

    # area_mm2_range 篩選
    area_range = filters.get("area_mm2_range")
    if area_range and len(area_range) == 2:
        lo, hi = area_range
        faces = [f for f in faces if lo <= float(f.area) <= hi]

    # 命中 0 個
    if not faces:
        raise ReferenceLostError(ref)

    # 命中 1 個
    if len(faces) == 1:
        return faces[0]

    # 命中 ≥2 個——嘗試 disambiguation
    disambig = ref.get("disambiguation", {})

    # centroid_hint 收斂
    hint = disambig.get("centroid_hint")
    if hint:
        best = None
        best_dist = float("inf")
        for f in faces:
            try:
                c = f.center()
                d = _centroid_distance([c.X, c.Y, c.Z], hint)
                if d < best_dist:
                    best_dist = d
                    best = f
            except Exception:
                continue
        if best is not None and best_dist < 50.0:
            # 收斂成功——centroid 在 50mm 內
            return best

    # 無法收斂——歧義
    candidate_info = []
    for f in faces:
        try:
            c = f.center()
            candidate_info.append({
                "surface_type": _geom_type_to_str(f.geom_type),
                "area_mm2": round(float(f.area), 2),
                "centroid": [round(c.X, 2), round(c.Y, 2), round(c.Z, 2)],
            })
        except Exception:
            candidate_info.append({"surface_type": _geom_type_to_str(f.geom_type)})
    raise ReferenceAmbiguousError(ref, candidate_info)


def _resolve_edge_reference(
    part: Any,
    trace: "TopologyTrace | None",
    ref: dict[str, Any],
    filters: dict[str, Any],
) -> Any:
    """解析邊參照。"""
    try:
        from build123d import Axis
    except ImportError:
        raise ReferenceLostError(ref, "build123d 未安裝")

    try:
        edges = list(part.edges())
    except Exception:
        raise ReferenceLostError(ref, "無法取得邊列表")

    # source_feature_id 篩選
    source_fid = ref.get("source_feature_id", "")
    if source_fid and trace is not None:
        trace_edges = trace.created_by(source_fid)
        if trace_edges:
            edges = [e for e in edges if e in trace_edges]

    # axis 篩選
    axis = filters.get("axis")
    if axis == "vertical":
        edges = list(filter_by_axis(edges, Axis.Z))
    elif axis == "horizontal":
        edges = (list(filter_by_axis(edges, Axis.X)) +
                 list(filter_by_axis(edges, Axis.Y)))

    # location 篩選
    location = filters.get("location")
    if location == "top":
        bb = part.bounding_box()
        top_z = bb.max.Z
        edges = [e for e in edges if all(abs(v.Z - top_z) < 0.01 for v in e.vertices())]
    elif location == "bottom":
        bb = part.bounding_box()
        bot_z = bb.min.Z
        edges = [e for e in edges if all(abs(v.Z - bot_z) < 0.01 for v in e.vertices())]

    # surface_type 篩選（圓邊 vs 直邊）
    st = filters.get("surface_type")
    if st:
        from build123d import GeomType
        if st == "cylinder":
            edges = [e for e in edges if e.geom_type == GeomType.CIRCLE]
        elif st == "plane":
            edges = [e for e in edges if e.geom_type == GeomType.LINE]

    if not edges:
        raise ReferenceLostError(ref)

    if len(edges) == 1:
        return edges[0]

    # 歧義
    raise ReferenceAmbiguousError(ref, [{"edge_count": len(edges)}])


# ── 輔助函式 ──

# 與 adapter 共用同一份實作，避免兩份比對語意漂移
from .adapters.build123d_adapter import _faces_equal  # noqa: E402


def _face_normal_matches(face: Any, expected_normal: list[float]) -> bool:
    """檢查平面面的法向量是否匹配。

    WP-S1 修復：原本直接拿 `face.geom_type` 跟 build123d 的 `GeomType.PLANE`
    enum 比較——FreeCADFaceProxy.geom_type 回傳的是字串（"PLANE"），永遠不等於
    這個 enum，導致帶 normal filter 的語意查詢（如 datum 的 top_planar_face
    intent）在 freecad 引擎下一律判定不是平面、篩選結果永遠是空集合。改用
    `_geom_type_to_str` 統一轉換（與 exporters/display_map 同一張對照表），
    兩引擎都能正確判斷。
    """
    try:
        if _geom_type_to_str(face.geom_type) != "plane":
            return False
        # 取面法向量
        normal = face.normal_at()
        actual = _normal_to_list(normal)
        return _vectors_equal(actual, expected_normal, tol=0.05)
    except Exception:
        return False


def _face_radius_matches(face: Any, expected_radius: float, tol: float = 0.1) -> bool:
    """檢查圓柱/球面/圓錐面的半徑是否匹配。"""
    try:
        from build123d import GeomType
        gt = face.geom_type
        if gt == GeomType.CYLINDER:
            r = face.radius
            return abs(float(r) - expected_radius) < tol
        elif gt == GeomType.SPHERE:
            r = face.radius
            return abs(float(r) - expected_radius) < tol
        elif gt == GeomType.CONE:
            r = face.radius  # 圓錐在 build123d 中 radius 可能為底半徑
            return abs(float(r) - expected_radius) < tol
        return False
    except Exception:
        return False


def filter_by_axis(edges: list, axis: Any) -> list:
    """篩選平行於指定軸的邊。"""
    try:
        from build123d import Edge
        # 取得軸方向向量
        axis_dir = axis.direction if hasattr(axis, "direction") else None
        if axis_dir is None:
            return []
        ax, ay, az = axis_dir.X, axis_dir.Y, axis_dir.Z

        result = []
        for e in edges:
            if not isinstance(e, Edge):
                continue
            try:
                tangent = e.tangent_at(0.5)
                if tangent is None:
                    continue
                dx, dy, dz = tangent.X, tangent.Y, tangent.Z
                if abs(ax) > 0.5:
                    # X 軸平行：dy, dz 接近零
                    if abs(dy) < 0.01 and abs(dz) < 0.01:
                        result.append(e)
                elif abs(ay) > 0.5:
                    if abs(dx) < 0.01 and abs(dz) < 0.01:
                        result.append(e)
                elif abs(az) > 0.5:
                    if abs(dx) < 0.01 and abs(dy) < 0.01:
                        result.append(e)
            except Exception:
                continue
        return result
    except Exception:
        return []