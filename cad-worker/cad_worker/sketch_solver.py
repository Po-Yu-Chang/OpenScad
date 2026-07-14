"""Sketch constraint solver——2D 約束求解器。

WP1-2R：真求解器。以 Gauss-Newton／Levenberg-Marquardt 最小平方法聯立求解，
取代原本逐約束獨立計算的 heuristic。

支援的約束類型：
- coincident: 兩點重合
- horizontal: 線段水平
- vertical: 線段鉛直
- parallel: 兩線段平行
- perpendicular: 兩線段垂直
- equal: 兩線段等長
- distance: 兩點距離=value_mm
- radius: 圓弧/圓半徑=value_mm
- diameter: 圓弧/圓直徑=value_mm
- midpoint: 點在線段中點
- symmetric: 兩點關於一條線對稱（targets=[point_a, point_b, ref_line]）
- angle: 兩線段夾角=value_deg
- concentric: 兩圓同心
- tangent: 線段與圓相切（targets=[line, circle.center]）

求解策略（座標型實體：line/circle/arc，各自帶有 x1,y1,x2,y2 或 center_x,center_y,radius）：
1. 把所有座標型實體的自由參數攤平成一個向量 θ。
2. 每個約束對應一或多個殘差函式 r(θ)，滿足時為 0。
3. 用數值 Jacobian（中央差分）＋Levenberg-Marquardt 疊代，聯立最小化 Σr²。
4. 依序把約束加入求解集合；若加入後殘差無法收斂到容差內，判定該約束衝突，
   從求解集合中剔除並記入 conflicts（非「切最後 N 個」的猜測）。
5. DOF = 自由參數數 − Jacobian 在解點的秩（非固定成本表相減）。

沒有座標模型的「抽象」實體型別（rectangle/polygon/slot/polyline 等，只在少數
純 DOF 記帳情境使用、沒有可解座標）維持原本的成本表記帳方式，行為不變。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ── 約束類型列舉 ──

CONSTRAINT_TYPES = {
    "coincident", "horizontal", "vertical", "parallel", "perpendicular",
    "equal", "distance", "radius", "diameter", "midpoint", "symmetric",
    "angle", "concentric", "tangent",
}

# 每種約束消耗的自由度——僅用於無座標模型的抽象實體記帳（見模組 docstring）。
CONSTRAINT_DOF_COST = {
    "coincident": 2,
    "horizontal": 1,
    "vertical": 1,
    "parallel": 1,
    "perpendicular": 1,
    "equal": 1,
    "distance": 2,
    "radius": 1,
    "diameter": 1,
    "midpoint": 2,
    "symmetric": 2,
    "angle": 1,
    "concentric": 2,
    "tangent": 1,
}

# 求解殘差收斂容差（mm / 無因次）。低於此值視為約束已滿足。
_RESIDUAL_TOL = 1e-3


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


# ── 實體型別 ──

_COORD_TYPES = {"line", "circle", "arc"}

# 座標型實體的自由參數（arc 的 start_angle/end_angle 不參與求解——目前沒有
# 任何約束型別會調整弧的掃掠角度，維持固定）。
_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "line": ("x1", "y1", "x2", "y2"),
    "circle": ("center_x", "center_y", "radius"),
    "arc": ("center_x", "center_y", "radius"),
}


def _entity_type(entity: dict[str, Any]) -> str:
    return entity.get("type") or entity.get("entity_type", "")


def _entity_params(entity: dict[str, Any]) -> dict[str, Any]:
    return entity.get("parameters", entity)


def _is_coord_entity(entity: dict[str, Any]) -> bool:
    return _entity_type(entity) in _COORD_TYPES and entity.get("id") is not None


def _get_entity(entity_id: str, entities: list[dict[str, Any]]) -> dict[str, Any] | None:
    """取得指定 ID 的實體。"""
    for e in entities:
        if e.get("id") == entity_id:
            return e
    return None


def _entity_dof(entity: dict[str, Any]) -> int:
    """計算單一實體的自由度（無座標模型的抽象記帳，見模組 docstring）。"""
    etype = _entity_type(entity)
    params = _entity_params(entity)

    if etype == "rectangle":
        return 4
    elif etype == "circle":
        return 3
    elif etype == "line":
        return 4
    elif etype == "polyline":
        pts = params.get("points", [])
        return len(pts) * 2
    elif etype == "arc":
        return 5
    elif etype == "slot":
        return 4
    elif etype == "polygon":
        return 3
    return 0


# ── 參數向量打包／解包 ──

def _pack(entities: list[dict[str, Any]]) -> tuple[np.ndarray, list[tuple[str, str]]]:
    """把所有座標型實體的自由參數攤平成向量，回傳 (向量, [(entity_id, key), ...])。"""
    keys: list[tuple[str, str]] = []
    values: list[float] = []
    for e in entities:
        if not _is_coord_entity(e):
            continue
        eid = e["id"]
        etype = _entity_type(e)
        params = _entity_params(e)
        for k in _PARAM_KEYS[etype]:
            keys.append((eid, k))
            values.append(float(params.get(k, 0.0)))
    return np.array(values, dtype=float), keys


def _unpack(vec: np.ndarray, keys: list[tuple[str, str]], entities: list[dict[str, Any]]) -> None:
    """把求解後的向量寫回 entities（就地修改）。"""
    by_id = {e["id"]: e for e in entities if e.get("id") is not None}
    for val, (eid, k) in zip(vec, keys):
        e = by_id.get(eid)
        if e is None:
            continue
        _entity_params(e)[k] = float(val)


def _idx(keys: list[tuple[str, str]], eid: str, key: str) -> int | None:
    for i, (kid, kk) in enumerate(keys):
        if kid == eid and kk == key:
            return i
    return None


def _target_point(
    vec: np.ndarray, keys: list[tuple[str, str]], target: str, entities: list[dict[str, Any]],
) -> tuple[float, float] | None:
    """解析目標參照（如 "e1.start"）在目前向量下的座標。"""
    eid, _, point = target.partition(".")
    e = _get_entity(eid, entities)
    if e is None:
        return None
    etype = _entity_type(e)
    if etype == "line":
        if point == "start":
            ix, iy = _idx(keys, eid, "x1"), _idx(keys, eid, "y1")
        elif point == "end":
            ix, iy = _idx(keys, eid, "x2"), _idx(keys, eid, "y2")
        else:
            return None
    elif etype in ("circle", "arc"):
        if point == "center":
            ix, iy = _idx(keys, eid, "center_x"), _idx(keys, eid, "center_y")
        else:
            return None
    else:
        return None
    if ix is None or iy is None:
        return None
    return (float(vec[ix]), float(vec[iy]))


def _line_dir(vec: np.ndarray, keys: list[tuple[str, str]], eid: str) -> tuple[float, float] | None:
    ix1, iy1 = _idx(keys, eid, "x1"), _idx(keys, eid, "y1")
    ix2, iy2 = _idx(keys, eid, "x2"), _idx(keys, eid, "y2")
    if None in (ix1, iy1, ix2, iy2):
        return None
    return (float(vec[ix2] - vec[ix1]), float(vec[iy2] - vec[iy1]))


# ── 約束殘差函式（滿足時為 0） ──

def _constraint_residuals(
    c: Constraint, vec: np.ndarray, keys: list[tuple[str, str]], entities: list[dict[str, Any]],
) -> list[float]:
    t = c.targets
    ctype = c.type

    if ctype == "horizontal":
        if not t:
            return []
        eid = t[0].split(".")[0]
        iy1, iy2 = _idx(keys, eid, "y1"), _idx(keys, eid, "y2")
        if iy1 is None or iy2 is None:
            return []
        return [float(vec[iy2] - vec[iy1])]

    if ctype == "vertical":
        if not t:
            return []
        eid = t[0].split(".")[0]
        ix1, ix2 = _idx(keys, eid, "x1"), _idx(keys, eid, "x2")
        if ix1 is None or ix2 is None:
            return []
        return [float(vec[ix2] - vec[ix1])]

    if ctype == "coincident":
        if len(t) < 2:
            return []
        p1, p2 = _target_point(vec, keys, t[0], entities), _target_point(vec, keys, t[1], entities)
        if p1 is None or p2 is None:
            return []
        return [p2[0] - p1[0], p2[1] - p1[1]]

    if ctype == "distance":
        if len(t) < 2 or c.value_mm is None:
            return []
        p1, p2 = _target_point(vec, keys, t[0], entities), _target_point(vec, keys, t[1], entities)
        if p1 is None or p2 is None:
            return []
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        return [d - c.value_mm]

    if ctype in ("radius", "diameter"):
        if not t or c.value_mm is None:
            return []
        eid = t[0].split(".")[0]
        ir = _idx(keys, eid, "radius")
        if ir is None:
            return []
        target_r = c.value_mm if ctype == "radius" else c.value_mm / 2.0
        return [float(vec[ir]) - target_r]

    if ctype == "equal":
        if len(t) < 2:
            return []
        e1, e2 = t[0].split(".")[0], t[1].split(".")[0]
        d1, d2 = _line_dir(vec, keys, e1), _line_dir(vec, keys, e2)
        if d1 is None or d2 is None:
            return []
        return [math.hypot(*d2) - math.hypot(*d1)]

    if ctype == "parallel":
        if len(t) < 2:
            return []
        e1, e2 = t[0].split(".")[0], t[1].split(".")[0]
        d1, d2 = _line_dir(vec, keys, e1), _line_dir(vec, keys, e2)
        if d1 is None or d2 is None:
            return []
        len1, len2 = math.hypot(*d1), math.hypot(*d2)
        if len1 < 1e-9 or len2 < 1e-9:
            return [0.0]
        cross = (d1[0] * d2[1] - d1[1] * d2[0]) / (len1 * len2)
        return [cross]

    if ctype == "perpendicular":
        if len(t) < 2:
            return []
        e1, e2 = t[0].split(".")[0], t[1].split(".")[0]
        d1, d2 = _line_dir(vec, keys, e1), _line_dir(vec, keys, e2)
        if d1 is None or d2 is None:
            return []
        len1, len2 = math.hypot(*d1), math.hypot(*d2)
        if len1 < 1e-9 or len2 < 1e-9:
            return [0.0]
        dot = (d1[0] * d2[0] + d1[1] * d2[1]) / (len1 * len2)
        return [dot]

    if ctype == "concentric":
        if len(t) < 2:
            return []
        p1, p2 = _target_point(vec, keys, t[0], entities), _target_point(vec, keys, t[1], entities)
        if p1 is None or p2 is None:
            return []
        return [p2[0] - p1[0], p2[1] - p1[1]]

    if ctype == "midpoint":
        # targets = [line_id, point_target]
        if len(t) < 2:
            return []
        eid = t[0].split(".")[0]
        ix1, iy1 = _idx(keys, eid, "x1"), _idx(keys, eid, "y1")
        ix2, iy2 = _idx(keys, eid, "x2"), _idx(keys, eid, "y2")
        if None in (ix1, iy1, ix2, iy2):
            return []
        mx = (float(vec[ix1]) + float(vec[ix2])) / 2
        my = (float(vec[iy1]) + float(vec[iy2])) / 2
        p2 = _target_point(vec, keys, t[1], entities)
        if p2 is None:
            return []
        return [p2[0] - mx, p2[1] - my]

    if ctype == "angle":
        if len(t) < 2 or c.value_deg is None:
            return []
        e1, e2 = t[0].split(".")[0], t[1].split(".")[0]
        d1, d2 = _line_dir(vec, keys, e1), _line_dir(vec, keys, e2)
        if d1 is None or d2 is None:
            return []
        a1, a2 = math.atan2(d1[1], d1[0]), math.atan2(d2[1], d2[0])
        diff = a2 - a1
        diff = (diff + math.pi) % (2 * math.pi) - math.pi
        target = math.radians(c.value_deg)
        return [diff - target]

    if ctype == "symmetric":
        # targets = [point_a, point_b, ref_line]——ref_line 為對稱軸線 entity id
        if len(t) < 3:
            return []
        pa, pb = _target_point(vec, keys, t[0], entities), _target_point(vec, keys, t[1], entities)
        ref_eid = t[2].split(".")[0]
        d = _line_dir(vec, keys, ref_eid)
        p0 = _target_point(vec, keys, ref_eid + ".start", entities)
        if pa is None or pb is None or d is None or p0 is None:
            return []
        dx, dy = d
        norm = dx * dx + dy * dy
        if norm < 1e-9:
            return [0.0, 0.0]
        vx, vy = pa[0] - p0[0], pa[1] - p0[1]
        proj = (vx * dx + vy * dy) / norm
        proj_x, proj_y = p0[0] + proj * dx, p0[1] + proj * dy
        refl_x, refl_y = 2 * proj_x - pa[0], 2 * proj_y - pa[1]
        return [refl_x - pb[0], refl_y - pb[1]]

    if ctype == "tangent":
        # targets = [line_id, "circle_id.center"]
        if len(t) < 2:
            return []
        line_id = t[0].split(".")[0]
        circle_eid = t[1].split(".")[0]
        d = _line_dir(vec, keys, line_id)
        p0 = _target_point(vec, keys, line_id + ".start", entities)
        center = _target_point(vec, keys, circle_eid + ".center", entities)
        ir = _idx(keys, circle_eid, "radius")
        if d is None or p0 is None or center is None or ir is None:
            return []
        dx, dy = d
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return [0.0]
        cross = (center[0] - p0[0]) * dy - (center[1] - p0[1]) * dx
        dist = abs(cross) / length
        return [dist - float(vec[ir])]

    return []


def _residual_vector(
    constraints: list[Constraint], vec: np.ndarray, keys: list[tuple[str, str]], entities: list[dict[str, Any]],
) -> np.ndarray:
    out: list[float] = []
    for c in constraints:
        out.extend(_constraint_residuals(c, vec, keys, entities))
    return np.array(out, dtype=float)


def _jacobian(
    constraints: list[Constraint], vec: np.ndarray, keys: list[tuple[str, str]],
    entities: list[dict[str, Any]], eps: float = 1e-6,
) -> np.ndarray:
    n = len(vec)
    r0 = _residual_vector(constraints, vec, keys, entities)
    m = len(r0)
    jac = np.zeros((m, n))
    for j in range(n):
        v2 = vec.copy()
        v2[j] += eps
        r2 = _residual_vector(constraints, v2, keys, entities)
        jac[:, j] = (r2 - r0) / eps
    return jac


def _gauss_newton(
    constraints: list[Constraint], entities: list[dict[str, Any]], keys: list[tuple[str, str]],
    vec0: np.ndarray, max_iter: int = 60,
) -> tuple[np.ndarray, float]:
    """Levenberg-Marquardt 阻尼最小平方，回傳 (解向量, 最終殘差範數)。"""
    if not constraints or len(vec0) == 0:
        r = _residual_vector(constraints, vec0, keys, entities)
        return vec0.copy(), float(np.sqrt(np.dot(r, r))) if len(r) else 0.0

    # 部分約束殘差（如 perpendicular 的 cos 夾角）在起始座標恰好對稱／degenerate
    # 時梯度恰為 0（鞍點），純梯度法無法脫離。加入極小的固定擾動打破對稱性，
    # 屬常見數值處理手法，不影響收斂後的精度（擾動遠小於容差）。
    n0 = len(vec0)
    nudge = 1e-6 * np.sin(np.arange(1, n0 + 1) * 0.7)
    vec = vec0.copy() + nudge
    lam = 1e-3
    prev_norm: float | None = None
    for _ in range(max_iter):
        r = _residual_vector(constraints, vec, keys, entities)
        norm = float(np.dot(r, r))
        if norm < 1e-16:
            break
        jac = _jacobian(constraints, vec, keys, entities)
        jtj = jac.T @ jac
        jtr = jac.T @ r
        n = jtj.shape[0]
        improved = False
        for _attempt in range(8):
            try:
                delta = np.linalg.solve(jtj + lam * np.eye(n), -jtr)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            vec_new = vec + delta
            r_new = _residual_vector(constraints, vec_new, keys, entities)
            norm_new = float(np.dot(r_new, r_new))
            if norm_new < norm:
                vec = vec_new
                lam = max(lam / 3, 1e-12)
                improved = True
                break
            lam *= 4
        if not improved:
            break
        if prev_norm is not None and abs(prev_norm - norm) < 1e-14:
            break
        prev_norm = norm

    r_final = _residual_vector(constraints, vec, keys, entities)
    return vec, float(np.sqrt(np.dot(r_final, r_final))) if len(r_final) else 0.0


def _find_conflicts(
    constraints: list[Constraint], entities: list[dict[str, Any]], keys: list[tuple[str, str]], vec0: np.ndarray,
) -> tuple[list[Constraint], np.ndarray, list[str]]:
    """依序將約束加入求解集合；若加入後殘差無法收斂，判定衝突並剔除。

    回傳 (實際生效的約束, 對應解向量, 衝突約束 ID 列表)。
    """
    active: list[Constraint] = []
    conflicts: list[str] = []
    vec = vec0.copy()
    for c in constraints:
        trial = active + [c]
        solved_vec, resid = _gauss_newton(trial, entities, keys, vec)
        if resid > _RESIDUAL_TOL:
            conflicts.append(c.id)
            continue
        active = trial
        vec = solved_vec
    return active, vec, conflicts


def _numeric_dof(
    active: list[Constraint], entities: list[dict[str, Any]], keys: list[tuple[str, str]], vec: np.ndarray,
) -> int:
    if not keys:
        return 0
    if not active:
        return len(keys)
    jac = _jacobian(active, vec, keys, entities)
    rank = int(np.linalg.matrix_rank(jac, tol=1e-6)) if jac.size else 0
    return max(0, len(keys) - rank)


def _classify_constraints(
    constraints: list[Constraint], coord_ids: set[str],
) -> tuple[list[Constraint], list[Constraint]]:
    """把約束分成「可用座標 Jacobian 求解」與「只能用抽象成本表記帳」兩組。"""
    numeric: list[Constraint] = []
    legacy: list[Constraint] = []
    for c in constraints:
        ref_ids = {t.split(".")[0] for t in c.targets if t}
        if ref_ids and ref_ids.issubset(coord_ids):
            numeric.append(c)
        else:
            legacy.append(c)
    return numeric, legacy


def _analyze(entities: list[dict[str, Any]], constraints: list[Constraint], apply_solution: bool) -> SolverStatus:
    vec0, keys = _pack(entities)
    coord_ids = {eid for eid, _ in keys}
    numeric_constraints, legacy_constraints = _classify_constraints(constraints, coord_ids)

    if keys:
        active, vec, conflicts = _find_conflicts(numeric_constraints, entities, keys, vec0)
        if apply_solution:
            _unpack(vec, keys, entities)
        num_dof = _numeric_dof(active, entities, keys, vec)
    else:
        conflicts, num_dof = [], 0

    # 抽象實體（無座標模型）維持成本表記帳，行為與舊版一致。
    opaque_entities = [e for e in entities if not _is_coord_entity(e)]
    opaque_dof = sum(_entity_dof(e) for e in opaque_entities)
    opaque_consumed = sum(CONSTRAINT_DOF_COST.get(c.type, 0) for c in legacy_constraints)
    opaque_remaining = opaque_dof - opaque_consumed

    all_conflicts = list(conflicts)
    if opaque_remaining < 0:
        over = -opaque_remaining
        all_conflicts += [c.id for c in legacy_constraints[-over:]]
        opaque_remaining = 0

    total_dof = num_dof + opaque_remaining
    state = "over" if all_conflicts else ("full" if total_dof == 0 else "under")
    return SolverStatus(dof=total_dof, state=state, conflicts=all_conflicts)


# ── 對外 API ──

def calculate_dof(entities: list[dict[str, Any]], constraints: list[Constraint]) -> SolverStatus:
    """計算自由度與約束狀態（在目前給定座標下評估，不移動幾何）。"""
    import copy
    snapshot = copy.deepcopy(entities)
    return _analyze(snapshot, constraints, apply_solution=False)


def solve(
    entities: list[dict[str, Any]],
    constraints: list[Constraint],
) -> dict[str, Any]:
    """聯立求解草圖約束，回傳更新後的 entities + solver_status。

    回傳格式：
    {
        "entities": [...],  # 更新後的實體（含解算後座標）
        "solver_status": {"dof": 0, "state": "full", "conflicts": []},
    }
    """
    import copy
    solved_entities = copy.deepcopy(entities)
    status = _analyze(solved_entities, constraints, apply_solution=True)
    return {
        "entities": solved_entities,
        "solver_status": status.to_dict(),
    }


def check_residuals(
    entities: list[dict[str, Any]], constraints: list[Constraint], tol: float = 1e-2,
) -> dict[str, Any]:
    """在目前（未求解）座標下直接驗證約束殘差，不移動幾何。

    供 build123d 引擎 rebuild 前驗證用：build123d 沒有草圖求解器，幾何由
    參數直接計算，因此只驗證「目前座標是否已滿足約束」，不滿足即應中止
    rebuild（不得靜默沿用舊座標）。
    """
    vec, keys = _pack(entities)
    coord_ids = {eid for eid, _ in keys}
    numeric_constraints, _ = _classify_constraints(constraints, coord_ids)

    violations: list[str] = []
    max_residual = 0.0
    for c in numeric_constraints:
        residuals = _constraint_residuals(c, vec, keys, entities)
        if not residuals:
            continue
        r = max(abs(x) for x in residuals)
        max_residual = max(max_residual, r)
        if r > tol:
            violations.append(c.id)

    return {
        "satisfied": not violations,
        "violations": violations,
        "max_residual": max_residual,
    }
