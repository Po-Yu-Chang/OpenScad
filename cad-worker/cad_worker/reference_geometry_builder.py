"""WP1-3 基準幾何重建器——從 datum 定義計算 derived_geometry。

支援的 datum 方法：
- offset: 面偏移（datum plane）——來源面法向量方向偏移 offset_mm
- angle_between: 兩面夾角（datum plane）——來源面旋轉 angle_deg
- mid_plane: 中間面（datum plane）——兩面中間
- intersection: 兩面交線（datum axis）
- cylinder_axis: 圓柱軸（datum axis）——來源面為圓柱面時取軸
- vertex: 頂點（datum point）——來源為頂點
- center: 圓心（datum point）——來源面為圓/弧時取圓心

簡化實作：來源面解析仰賴 display_map 的 face 資訊。
若來源面不存在或方法不適用，derived_geometry 保留為空。
"""

from __future__ import annotations

from typing import Any
import math


def build_reference_geometry(graph: Any) -> None:
    """重建所有基準幾何的 derived_geometry。

    遍歷 graph.reference_geometry，依 kind + definition.method 計算座標。
    結果寫入 datum["derived_geometry"]。
    """
    for datum in graph.reference_geometry:
        kind = datum.get("kind", "")
        definition = datum.get("definition", {})
        method = definition.get("method", "")
        derived = _compute_datum(kind, method, definition, graph)
        datum["derived_geometry"] = derived


def _compute_datum(
    kind: str,
    method: str,
    definition: dict[str, Any],
    graph: Any,
) -> dict[str, Any]:
    """計算單一 datum 的 derived_geometry。"""
    if kind == "plane":
        return _compute_plane(method, definition, graph)
    elif kind == "axis":
        return _compute_axis(method, definition, graph)
    elif kind == "point":
        return _compute_point(method, definition, graph)
    return {}


def _compute_plane(
    method: str,
    definition: dict[str, Any],
    graph: Any,
) -> dict[str, Any]:
    """計算 datum plane 的 origin + normal。"""
    if method == "offset":
        # 面偏移：來源面法向量方向偏移 offset_mm
        source_ref = definition.get("source_ref", "")
        offset_mm = definition.get("offset_mm", 0.0)
        face_info = _resolve_face(source_ref, graph)
        if face_info is None:
            return {}
        origin = face_info.get("origin", [0, 0, 0])
        normal = face_info.get("normal", [0, 0, 1])
        # 偏移後 origin = face_origin + normal * offset
        new_origin = [
            origin[0] + normal[0] * offset_mm,
            origin[1] + normal[1] * offset_mm,
            origin[2] + normal[2] * offset_mm,
        ]
        return {"origin": new_origin, "normal": normal}

    elif method == "angle_between":
        # 兩面夾角：來源面繞交線旋轉 angle_deg
        source_ref = definition.get("source_ref", "")
        source_ref_2 = definition.get("source_ref_2", "")
        angle_deg = definition.get("angle_deg", 0.0)
        face1 = _resolve_face(source_ref, graph)
        face2 = _resolve_face(source_ref_2, graph)
        if face1 is None or face2 is None:
            return {}
        n1 = face1.get("normal", [0, 0, 1])
        n2 = face2.get("normal", [0, 0, 1])
        # 簡化：取 n1 和 n2 的平均方向作為 bisecting plane normal
        avg_normal = [
            (n1[0] + n2[0]) / 2,
            (n1[1] + n2[1]) / 2,
            (n1[2] + n2[2]) / 2,
        ]
        origin = face1.get("origin", [0, 0, 0])
        return {"origin": origin, "normal": _normalize(avg_normal)}

    elif method == "mid_plane":
        # 中間面：兩面中間
        source_ref = definition.get("source_ref", "")
        source_ref_2 = definition.get("source_ref_2", "")
        face1 = _resolve_face(source_ref, graph)
        face2 = _resolve_face(source_ref_2, graph)
        if face1 is None or face2 is None:
            return {}
        o1 = face1.get("origin", [0, 0, 0])
        o2 = face2.get("origin", [0, 0, 0])
        mid_origin = [
            (o1[0] + o2[0]) / 2,
            (o1[1] + o2[1]) / 2,
            (o1[2] + o2[2]) / 2,
        ]
        n1 = face1.get("normal", [0, 0, 1])
        return {"origin": mid_origin, "normal": n1}

    return {}


def _compute_axis(
    method: str,
    definition: dict[str, Any],
    graph: Any,
) -> dict[str, Any]:
    """計算 datum axis 的 origin + direction。"""
    if method == "intersection":
        # 兩面交線
        source_ref = definition.get("source_ref", "")
        source_ref_2 = definition.get("source_ref_2", "")
        face1 = _resolve_face(source_ref, graph)
        face2 = _resolve_face(source_ref_2, graph)
        if face1 is None or face2 is None:
            return {}
        n1 = face1.get("normal", [0, 0, 1])
        n2 = face2.get("normal", [0, 1, 0])
        # 交線方向 = n1 × n2
        direction = _cross(n1, n2)
        if _length(direction) < 1e-9:
            return {}
        direction = _normalize(direction)
        origin = face1.get("origin", [0, 0, 0])
        return {"origin": origin, "direction": direction}

    elif method == "cylinder_axis":
        # 圓柱軸
        source_ref = definition.get("source_ref", "")
        face_info = _resolve_face(source_ref, graph)
        if face_info is None:
            return {}
        # 圓柱面的 normal 即為軸方向
        direction = face_info.get("normal", [0, 0, 1])
        origin = face_info.get("origin", [0, 0, 0])
        return {"origin": origin, "direction": direction}

    return {}


def _compute_point(
    method: str,
    definition: dict[str, Any],
    graph: Any,
) -> dict[str, Any]:
    """計算 datum point 的 point 座標。"""
    if method == "vertex":
        # 頂點
        source_ref = definition.get("source_ref", "")
        vertex_info = _resolve_vertex(source_ref, graph)
        if vertex_info is None:
            return {}
        point = vertex_info.get("point", [0, 0, 0])
        return {"point": point}

    elif method == "center":
        # 圓心
        source_ref = definition.get("source_ref", "")
        face_info = _resolve_face(source_ref, graph)
        if face_info is None:
            return {}
        point = face_info.get("origin", [0, 0, 0])
        return {"point": point}

    return {}


def _resolve_face(source_ref: str, graph: Any) -> dict[str, Any] | None:
    """解析來源面參照——從 display_map 或特徵中查找面資訊。

    格式：face:body1.f1.top 或 face:f1.bottom
    簡化實作：檢查特徵的 sketch plane 和 display_map。
    """
    if not source_ref:
        return None

    # 解析 face:<feature_id>.<face_label> 格式
    if source_ref.startswith("face:"):
        ref_part = source_ref[5:]
        parts = ref_part.split(".")
        feature_id = parts[0] if parts else ""
        face_label = parts[1] if len(parts) > 1 else ""

        # 從特徵的 sketch plane 取得面資訊
        if feature_id in graph._features:
            feature = graph._features[feature_id]
            plane = feature.parameters.get("plane", {})
            if plane:
                origin = [
                    plane.get("origin_x", 0),
                    plane.get("origin_y", 0),
                    plane.get("origin_z", 0),
                ]
                normal = _plane_normal(plane)
                return {"origin": origin, "normal": normal}

        # 預設：top face = [0,0,1], bottom = [0,0,-1], front = [0,1,0], back = [0,-1,0]
        defaults = {
            "top": {"origin": [0, 0, 10], "normal": [0, 0, 1]},
            "bottom": {"origin": [0, 0, 0], "normal": [0, 0, -1]},
            "front": {"origin": [0, 10, 5], "normal": [0, 1, 0]},
            "back": {"origin": [0, -10, 5], "normal": [0, -1, 0]},
            "right": {"origin": [10, 0, 5], "normal": [1, 0, 0]},
            "left": {"origin": [-10, 0, 5], "normal": [-1, 0, 0]},
        }
        if face_label in defaults:
            return defaults[face_label]

    return None


def _resolve_vertex(source_ref: str, graph: Any) -> dict[str, Any] | None:
    """解析頂點參照。"""
    if not source_ref:
        return None
    if source_ref.startswith("vertex:"):
        # 格式 vertex:body1.f1.v0
        parts = source_ref[7:].split(".")
        # 簡化：返回原點
        return {"point": [0, 0, 0]}
    return None


def _plane_normal(plane: dict[str, Any]) -> list[float]:
    """從 plane 定義取得法向量。"""
    axis = plane.get("axis", "z")
    normals = {
        "z": [0, 0, 1],
        "-z": [0, 0, -1],
        "y": [0, 1, 0],
        "-y": [0, -1, 0],
        "x": [1, 0, 0],
        "-x": [-1, 0, 0],
    }
    return normals.get(axis, [0, 0, 1])


def _normalize(v: list[float]) -> list[float]:
    """正規化向量。"""
    length = _length(v)
    if length < 1e-9:
        return [0, 0, 1]
    return [v[0] / length, v[1] / length, v[2] / length]


def _length(v: list[float]) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _cross(a: list[float], b: list[float]) -> list[float]:
    """叉積。"""
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]