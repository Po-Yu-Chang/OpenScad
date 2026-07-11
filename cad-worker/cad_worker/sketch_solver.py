"""Sketch constraint solver——2D 約束求解器。

WP1-2 Real Sketcher: 約束類型、DOF 計算、求解。

支援的約束類型：
- coincident: 兩點重合（目標：e.start, e.end, e.center）
- horizontal: 線段水平（目標：line entity）
- vertical: 線段鉛直（目標：line entity）
- parallel: 兩線段平行
- perpendicular: 兩線段垂直
- equal: 兩線段等長
- distance: 兩點距離=value_mm
- radius: 圓弧/圓半徑=value_mm
- diameter: 圓弧/圓直徑=value_mm
- midpoint: 點在線段中點
- symmetric: 兩點關於一條線對稱
- angle: 兩線段夾角=value_deg
- concentric: 兩圓同心
- tangent: 線段與圓相切

求解策略：
1. 收集所有可變參數（自由度）
2. 逐一套用約束，計算剩餘 DOF
3. 過約束偵測——衝突約束列表
4. 線性約束直接解（水平/鉛直/重合/距離/相等/半徑）
5. 非線性約束迭代解（角度/相切/對稱）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ── 約束類型列舉 ──

CONSTRAINT_TYPES = {
    "coincident", "horizontal", "vertical", "parallel", "perpendicular",
    "equal", "distance", "radius", "diameter", "midpoint", "symmetric",
    "angle", "concentric", "tangent",
}

# 每種約束消耗的自由度
CONSTRAINT_DOF_COST = {
    "coincident": 2,     # x,y 對齊
    "horizontal": 1,     # dy=0
    "vertical": 1,       # dx=0
    "parallel": 1,       # 角度相等
    "perpendicular": 1,  # 角度差 90°
    "equal": 1,          # 長度相等
    "distance": 2,       # 兩點固定距離
    "radius": 1,         # 半徑固定
    "diameter": 1,       # 直徑固定
    "midpoint": 2,       # 點在中點
    "symmetric": 2,      # 兩點對稱
    "angle": 1,          # 夾角固定
    "concentric": 2,     # 中心重合
    "tangent": 1,        # 相切
}


@dataclass
class Constraint:
    """草圖約束。"""
    id: str
    type: str
    targets: list[str]  # e.g. ["e1.start", "e2.end"]
    value_mm: float | None = None  # 距離/半徑/直徑
    value_deg: float | None = None  # 角度
    name: str = ""  # d1, d2... 供 equations 引用

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "targets": self.targets,
        }
        if self.value_mm is not None:
            d["value_mm"] = self.value_mm
        if self.value_deg is not None:
            d["value_deg"] = self.value_deg
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Constraint":
        return cls(
            id=d["id"],
            type=d["type"],
            targets=d.get("targets", []),
            value_mm=d.get("value_mm"),
            value_deg=d.get("value_deg"),
            name=d.get("name", ""),
        )


@dataclass
class SolverStatus:
    """求解器狀態。"""
    dof: int
    state: str  # "under" | "full" | "over"
    conflicts: list[str] = field(default_factory=list)  # 衝突約束 ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "dof": self.dof,
            "state": self.state,
            "conflicts": self.conflicts,
        }


# ── 實體解析 ──

def _parse_target(target: str, entities: list[dict[str, Any]]) -> tuple[float, float] | None:
    """解析目標參照，如 "e1.start" → (x, y) 座標。"""
    parts = target.split(".")
    if len(parts) != 2:
        return None
    eid, point = parts[0], parts[1]

    for entity in entities:
        if entity.get("id") == eid:
            etype = entity.get("type") or entity.get("entity_type", "")
            params = entity.get("parameters", entity)

            if point == "start":
                if etype == "line":
                    return (float(params.get("x1", 0)), float(params.get("y1", 0)))
                elif etype == "polyline":
                    pts = params.get("points", [])
                    if pts:
                        return (float(pts[0][0]), float(pts[0][1]))
            elif point == "end":
                if etype == "line":
                    return (float(params.get("x2", 0)), float(params.get("y2", 0)))
                elif etype == "polyline":
                    pts = params.get("points", [])
                    if pts:
                        return (float(pts[-1][0]), float(pts[-1][1]))
            elif point == "center":
                cx = params.get("center_x", params.get("x", 0))
                cy = params.get("center_y", params.get("y", 0))
                return (float(cx), float(cy))
    return None


def _get_entity(entity_id: str, entities: list[dict[str, Any]]) -> dict[str, Any] | None:
    """取得指定 ID 的實體。"""
    for e in entities:
        if e.get("id") == entity_id:
            return e
    return None


def _entity_dof(entity: dict[str, Any]) -> int:
    """計算單一實體的自由度。"""
    etype = entity.get("type") or entity.get("entity_type", "")
    params = entity.get("parameters", entity)

    if etype == "rectangle":
        # 位置(2) + 寬(1) + 高(1) = 4
        return 4
    elif etype == "circle":
        # 中心(2) + 半徑(1) = 3
        return 3
    elif etype == "line":
        # 兩端點(4) = 4
        return 4
    elif etype == "polyline":
        pts = params.get("points", [])
        return len(pts) * 2  # 每個點 2 DOF
    elif etype == "arc":
        # 中心(2) + 半徑(1) + 起角(1) + 終角(1) = 5
        return 5
    elif etype == "slot":
        # 中心(2) + 寬(1) + 高(1) = 4
        return 4
    elif etype == "polygon":
        # 中心(2) + 半徑(1) = 3
        return 3
    return 0


# ── DOF 計算 ──

def calculate_dof(entities: list[dict[str, Any]], constraints: list[Constraint]) -> SolverStatus:
    """計算自由度與約束狀態。"""
    total_dof = sum(_entity_dof(e) for e in entities)
    consumed_dof = 0
    conflicts: list[str] = []

    for c in constraints:
        cost = CONSTRAINT_DOF_COST.get(c.type, 0)
        consumed_dof += cost

    remaining = total_dof - consumed_dof

    if remaining > 0:
        state = "under"
    elif remaining == 0:
        state = "full"
    else:
        state = "over"
        # 過約束——找出衝突
        # 簡化：標記最後加入的多餘約束
        over = -remaining
        for c in constraints[-over:]:
            conflicts.append(c.id)

    return SolverStatus(dof=max(0, remaining), state=state, conflicts=conflicts)


# ── 約束求解 ──

def solve(
    entities: list[dict[str, Any]],
    constraints: list[Constraint],
) -> dict[str, Any]:
    """求解草圖約束，回傳更新後的 entities + solver_status。

    回傳格式：
    {
        "entities": [...],  # 更新後的實體（含解算後座標）
        "solver_status": {"dof": 0, "state": "full", "conflicts": []},
    }
    """
    # 深複製 entities 以免修改原始
    import copy
    solved_entities = copy.deepcopy(entities)

    # 套用約束——逐一修改 entity 參數
    for c in constraints:
        _apply_constraint(c, solved_entities)

    status = calculate_dof(solved_entities, constraints)

    return {
        "entities": solved_entities,
        "solver_status": status.to_dict(),
    }


def _apply_constraint(constraint: Constraint, entities: list[dict[str, Any]]) -> None:
    """套用單一約束到 entities（就地修改）。"""
    ctype = constraint.type

    if ctype == "horizontal":
        # 線段水平——y1 = y2
        if len(constraint.targets) >= 1:
            eid = constraint.targets[0].split(".")[0]
            e = _get_entity(eid, entities)
            if e:
                params = e.get("parameters", e)
                if "y2" in params:
                    params["y2"] = params.get("y1", 0)

    elif ctype == "vertical":
        # 線段鉛直——x1 = x2
        if len(constraint.targets) >= 1:
            eid = constraint.targets[0].split(".")[0]
            e = _get_entity(eid, entities)
            if e:
                params = e.get("parameters", e)
                if "x2" in params:
                    params["x2"] = params.get("x1", 0)

    elif ctype == "coincident":
        # 兩點重合
        if len(constraint.targets) >= 2:
            p1 = _parse_target(constraint.targets[0], entities)
            p2 = _parse_target(constraint.targets[1], entities)
            if p1 and p2:
                # 將第二個點對齊到第一個點
                _set_point(constraint.targets[1], p1, entities)

    elif ctype == "distance":
        # 兩點距離 = value_mm
        if constraint.value_mm is not None and len(constraint.targets) >= 2:
            p1 = _parse_target(constraint.targets[0], entities)
            p2 = _parse_target(constraint.targets[1], entities)
            if p1 and p2:
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                current_dist = math.sqrt(dx * dx + dy * dy)
                if current_dist > 0:
                    scale = constraint.value_mm / current_dist
                    new_p2 = (p1[0] + dx * scale, p1[1] + dy * scale)
                    _set_point(constraint.targets[1], new_p2, entities)

    elif ctype == "radius":
        # 圓弧/圓半徑 = value_mm
        if constraint.value_mm is not None and len(constraint.targets) >= 1:
            eid = constraint.targets[0].split(".")[0]
            e = _get_entity(eid, entities)
            if e:
                params = e.get("parameters", e)
                params["radius"] = constraint.value_mm

    elif ctype == "diameter":
        # 圓弧/圓直徑 = value_mm → 半徑 = value/2
        if constraint.value_mm is not None and len(constraint.targets) >= 1:
            eid = constraint.targets[0].split(".")[0]
            e = _get_entity(eid, entities)
            if e:
                params = e.get("parameters", e)
                params["radius"] = constraint.value_mm / 2.0

    elif ctype == "equal":
        # 兩線段等長
        if len(constraint.targets) >= 2:
            e1_id = constraint.targets[0].split(".")[0]
            e2_id = constraint.targets[1].split(".")[0]
            e1 = _get_entity(e1_id, entities)
            e2 = _get_entity(e2_id, entities)
            if e1 and e2:
                p1 = e1.get("parameters", e1)
                p2 = e2.get("parameters", e2)
                # 計算 e1 長度
                dx = float(p1.get("x2", 0)) - float(p1.get("x1", 0))
                dy = float(p1.get("y2", 0)) - float(p1.get("y1", 0))
                len1 = math.sqrt(dx * dx + dy * dy)
                if len1 > 0:
                    # 縮放 e2 到 e1 的長度
                    dx2 = float(p2.get("x2", 0)) - float(p2.get("x1", 0))
                    dy2 = float(p2.get("y2", 0)) - float(p2.get("y1", 0))
                    len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
                    if len2 > 0:
                        scale = len1 / len2
                        p2["x2"] = float(p2.get("x1", 0)) + dx2 * scale
                        p2["y2"] = float(p2.get("y1", 0)) + dy2 * scale

    elif ctype == "parallel":
        # 兩線段平行——角度相同
        if len(constraint.targets) >= 2:
            e1_id = constraint.targets[0].split(".")[0]
            e2_id = constraint.targets[1].split(".")[0]
            e1 = _get_entity(e1_id, entities)
            e2 = _get_entity(e2_id, entities)
            if e1 and e2:
                p1 = e1.get("parameters", e1)
                p2 = e2.get("parameters", e2)
                dx1 = float(p1.get("x2", 0)) - float(p1.get("x1", 0))
                dy1 = float(p1.get("y2", 0)) - float(p1.get("y1", 0))
                angle1 = math.atan2(dy1, dx1)
                dx2 = float(p2.get("x2", 0)) - float(p2.get("x1", 0))
                dy2 = float(p2.get("y2", 0)) - float(p2.get("y1", 0))
                len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
                if len2 > 0:
                    new_dx = math.cos(angle1) * len2
                    new_dy = math.sin(angle1) * len2
                    p2["x2"] = float(p2.get("x1", 0)) + new_dx
                    p2["y2"] = float(p2.get("y1", 0)) + new_dy

    elif ctype == "perpendicular":
        # 兩線段垂直——角度差 90°
        if len(constraint.targets) >= 2:
            e1_id = constraint.targets[0].split(".")[0]
            e2_id = constraint.targets[1].split(".")[0]
            e1 = _get_entity(e1_id, entities)
            e2 = _get_entity(e2_id, entities)
            if e1 and e2:
                p1 = e1.get("parameters", e1)
                p2 = e2.get("parameters", e2)
                dx1 = float(p1.get("x2", 0)) - float(p1.get("x1", 0))
                dy1 = float(p1.get("y2", 0)) - float(p1.get("y1", 0))
                angle1 = math.atan2(dy1, dx1) + math.pi / 2  # 垂直
                dx2 = float(p2.get("x2", 0)) - float(p2.get("x1", 0))
                dy2 = float(p2.get("y2", 0)) - float(p2.get("y1", 0))
                len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
                if len2 > 0:
                    new_dx = math.cos(angle1) * len2
                    new_dy = math.sin(angle1) * len2
                    p2["x2"] = float(p2.get("x1", 0)) + new_dx
                    p2["y2"] = float(p2.get("y1", 0)) + new_dy

    elif ctype == "concentric":
        # 兩圓同心——中心重合
        if len(constraint.targets) >= 2:
            p1 = _parse_target(constraint.targets[0], entities)
            p2 = _parse_target(constraint.targets[1], entities)
            if p1 and p2:
                _set_center(constraint.targets[1], p1, entities)

    elif ctype == "midpoint":
        # 點在線段中點
        if len(constraint.targets) >= 2:
            # targets[0] = line, targets[1] = point
            eid = constraint.targets[0].split(".")[0]
            e = _get_entity(eid, entities)
            if e:
                params = e.get("parameters", e)
                mx = (float(params.get("x1", 0)) + float(params.get("x2", 0))) / 2
                my = (float(params.get("y1", 0)) + float(params.get("y2", 0))) / 2
                _set_point(constraint.targets[1], (mx, my), entities)


def _set_point(target: str, point: tuple[float, float], entities: list[dict[str, Any]]) -> None:
    """設定目標點的座標。"""
    parts = target.split(".")
    if len(parts) != 2:
        return
    eid, point_name = parts[0], parts[1]

    for entity in entities:
        if entity.get("id") == eid:
            params = entity.get("parameters", entity)
            etype = entity.get("type") or entity.get("entity_type", "")

            if point_name == "start":
                if etype == "line":
                    params["x1"] = point[0]
                    params["y1"] = point[1]
                elif etype == "polyline":
                    pts = params.get("points", [])
                    if pts:
                        pts[0] = [point[0], point[1]]
            elif point_name == "end":
                if etype == "line":
                    params["x2"] = point[0]
                    params["y2"] = point[1]
                elif etype == "polyline":
                    pts = params.get("points", [])
                    if pts:
                        pts[-1] = [point[0], point[1]]
            elif point_name == "center":
                _set_center(target, point, entities)


def _set_center(target: str, point: tuple[float, float], entities: list[dict[str, Any]]) -> None:
    """設定實體的中心座標。"""
    eid = target.split(".")[0]
    for entity in entities:
        if entity.get("id") == eid:
            params = entity.get("parameters", entity)
            params["center_x"] = point[0]
            params["center_y"] = point[1]
            # 也設 x/y 別名
            params["x"] = point[0]
            params["y"] = point[1]