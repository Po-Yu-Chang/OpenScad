"""WP1-3 基準幾何重建器——從 datum 定義計算 derived_geometry。

支援的 datum 方法：
- offset: 面偏移（datum plane）——來源面法向量方向偏移 offset_mm
- angle_between: 兩面夾角（datum plane）——來源面旋轉 angle_deg
- mid_plane: 中間面（datum plane）——兩面中間
- intersection: 兩面交線（datum axis）
- cylinder_axis: 圓柱軸（datum axis）——來源面為圓柱面時取軸
- vertex: 頂點（datum point）——來源為頂點
- center: 圓心（datum point）——來源面為圓/弧時取圓心

WP-S1 修復：原本 `_resolve_face` 完全是硬編數字（不管實際模型多大，
"top" 永遠回傳 origin=[0,0,10]），`_resolve_vertex` 永遠回傳原點——
與模型真正的幾何毫無關係。現在改為透過 `topology.resolve_reference()`
（WP0-4 已有的語意化參照引擎）查詢上一輪 rebuild 產生的真實 BREP
（`part`/`trace`），取得面的真實 center()/normal_at()。

已知限制（誠實記錄，非本次完全解決）：
1. **一輪落後**：本函式在本輪 rebuild 的 `adapter.build_with_trace()` 之前
   呼叫（sketch 若引用 datum 平面，需要在自己被建構前就知道該平面的座標），
   所以只能用「上一輪 rebuild 已完成」的 part/trace 來解析來源面，而不是
   本輪正在建構中的幾何。專案第一次 rebuild（尚無上一輪結果）時，
   來源面若屬於本輪才會建立的特徵，會解析不到——這是需要把 datum 解析
   交錯進 adapter 逐特徵建構迴圈才能根治的架構問題，不在本次範圍內。
2. **vertex 解析仍是簡化版**：`topology.resolve_reference()` 目前只支援
   `topology_type="face"/"edge"`，沒有 `"vertex"`——真正的頂點級 BREP
   查詢需要新增對應的解析器，本次未做，`_resolve_vertex` 暫時仍回傳
   None（不解析），不再假裝回傳原點。
"""

from __future__ import annotations

from typing import Any
import math

from .topology import resolve_reference, ReferenceLostError, ReferenceAmbiguousError


def build_reference_geometry(graph: Any, part: Any = None, trace: Any = None) -> None:
    """重建所有基準幾何的 derived_geometry。

    遍歷 graph.reference_geometry，依 kind + definition.method 計算座標。
    結果寫入 datum["derived_geometry"]。

    Args:
        graph: FeatureGraph。
        part: 上一輪 rebuild 產生的實體（供真實面/邊查詢；見模組限制 1）。
        trace: 對應的 TopologyTrace（feature→face provenance）。
    """
    for datum in graph.reference_geometry:
        kind = datum.get("kind", "")
        definition = datum.get("definition", {})
        method = definition.get("method", "")
        derived = _compute_datum(kind, method, definition, graph, part, trace)
        datum["derived_geometry"] = derived


def _compute_datum(
    kind: str,
    method: str,
    definition: dict[str, Any],
    graph: Any,
    part: Any,
    trace: Any,
) -> dict[str, Any]:
    """計算單一 datum 的 derived_geometry。"""
    if kind == "plane":
        return _compute_plane(method, definition, graph, part, trace)
    elif kind == "axis":
        return _compute_axis(method, definition, graph, part, trace)
    elif kind == "point":
        return _compute_point(method, definition, graph, part, trace)
    return {}


def _compute_plane(
    method: str,
    definition: dict[str, Any],
    graph: Any,
    part: Any,
    trace: Any,
) -> dict[str, Any]:
    """計算 datum plane 的 origin + normal。"""
    if method == "offset":
        # 面偏移：來源面法向量方向偏移 offset_mm
        source_ref = definition.get("source_ref", "")
        offset_mm = definition.get("offset_mm", 0.0)
        face_info = _resolve_face(source_ref, graph, part, trace)
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
        face1 = _resolve_face(source_ref, graph, part, trace)
        face2 = _resolve_face(source_ref_2, graph, part, trace)
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
        face1 = _resolve_face(source_ref, graph, part, trace)
        face2 = _resolve_face(source_ref_2, graph, part, trace)
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
    part: Any,
    trace: Any,
) -> dict[str, Any]:
    """計算 datum axis 的 origin + direction。"""
    if method == "intersection":
        # 兩面交線
        source_ref = definition.get("source_ref", "")
        source_ref_2 = definition.get("source_ref_2", "")
        face1 = _resolve_face(source_ref, graph, part, trace)
        face2 = _resolve_face(source_ref_2, graph, part, trace)
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
        face_info = _resolve_face(source_ref, graph, part, trace)
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
    part: Any,
    trace: Any,
) -> dict[str, Any]:
    """計算 datum point 的 point 座標。"""
    if method == "vertex":
        # 頂點——見模組限制 2：topology.resolve_reference 尚無 vertex 解析器
        source_ref = definition.get("source_ref", "")
        vertex_info = _resolve_vertex(source_ref, graph, part, trace)
        if vertex_info is None:
            return {}
        point = vertex_info.get("point", [0, 0, 0])
        return {"point": point}

    elif method == "center":
        # 圓心
        source_ref = definition.get("source_ref", "")
        face_info = _resolve_face(source_ref, graph, part, trace)
        if face_info is None:
            return {}
        point = face_info.get("origin", [0, 0, 0])
        return {"point": point}

    return {}


# ── 舊 "face:<feature_id>.<label>" 字串 → v2 語意查詢轉換 ──

_LABEL_TO_INTENT = {
    "top": "top_planar_face",
    "bottom": "bottom_planar_face",
    "front": "front_planar_face",
    "back": "back_planar_face",
    "right": "right_planar_face",
    "left": "left_planar_face",
}


def _resolve_face(source_ref: str, graph: Any, part: Any, trace: Any) -> dict[str, Any] | None:
    """解析來源面參照——查詢上一輪 rebuild 的真實 BREP（見模組限制 1）。

    支援兩種格式：
    1. face:<feature_id>.<label>（label ∈ top/bottom/front/back/right/left）
       ——LLM/程式化建立 datum 時用的語意標籤。
    2. face_centroid:<feature_id>:<x>,<y>,<z>（WP-S1 新增）——桌面 UI
       「真選面」建立 datum 時用：使用者在 3D 視窗點了哪個面，就把該面
       display_map 記錄的 centroid 原樣傳回來，靠 centroid 就近比對選中
       正確的面，不需要猜測它是不是恰好在「top/bottom」這種標準方位。

    兩者都轉成 v2 語意查詢，交給 `topology.resolve_reference()`
    （WP0-4 既有的真實面查詢引擎）解析，取得的 Face 物件用
    `.center()`/`.normal_at()` 取得真實座標——不再是與模型尺寸無關的
    硬編數字。

    找不到（沒有 part、面已消失、參照歧義）一律回傳 None，讓上層
    derived_geometry 留空——不得用假數字掩蓋「解析不到」。
    """
    if not source_ref or part is None:
        return None

    if source_ref.startswith("face_centroid:"):
        rest = source_ref[len("face_centroid:"):]
        try:
            feature_id, coords = rest.split(":", 1)
            centroid = [float(v) for v in coords.split(",")]
            if len(centroid) != 3:
                return None
        except (ValueError, IndexError):
            return None
        v2_ref = {
            "ref_version": 2,
            "source_feature_id": feature_id,
            "topology_type": "face",
            "query": {},
            "disambiguation": {"centroid_hint": centroid},
        }
    elif source_ref.startswith("face:"):
        ref_part = source_ref[5:]
        parts = ref_part.split(".")
        feature_id = parts[0] if parts else ""
        label = parts[1] if len(parts) > 1 else ""
        intent = _LABEL_TO_INTENT.get(label)
        if not intent:
            return None
        v2_ref = {
            "ref_version": 2,
            "source_feature_id": feature_id,
            "topology_type": "face",
            "query": {"intent": intent},
        }
    else:
        return None

    try:
        face = resolve_reference(part, trace, v2_ref, graph)
    except (ReferenceLostError, ReferenceAmbiguousError):
        return None
    if face is None or isinstance(face, list):
        return None

    try:
        center = face.center()
        normal = face.normal_at()
        return {
            "origin": [float(center.X), float(center.Y), float(center.Z)],
            "normal": [float(normal.X), float(normal.Y), float(normal.Z)],
        }
    except Exception:
        return None


def _resolve_vertex(source_ref: str, graph: Any, part: Any, trace: Any) -> dict[str, Any] | None:
    """解析頂點參照。

    WP-S1：`topology.resolve_reference()` 目前只支援 face/edge，沒有
    vertex 級查詢——真正的頂點 BREP 解析器是獨立的後續工作（模組限制 2）。
    本次先誠實回傳 None（未解析），不再假裝永遠是原點。
    """
    return None


def _plane_normal(plane: dict[str, Any]) -> list[float]:
    """從 plane 定義取得法向量（供未走 face: 參照的舊資料相容）。"""
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
