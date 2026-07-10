"""標準件資料表。

LLM 只選擇「標準與等級」，數值一律查表。
資料表與 Command Schema 一起版本控管。
"""

import json
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"

# 載入標準件資料
with open(_SCHEMA_DIR / "standard_parts.schema.json", "r", encoding="utf-8") as f:
    _data: dict[str, Any] = json.load(f)

# ISO 273 間隙孔
_CLEARANCE_HOLES = _data["iso_273_clearance_holes"]
_COUNTERBORE = _data["counterbore_dimensions"]
_NEMA = _data["nema_mounting"]


def get_clearance_hole_diameter(standard: str, fit: str) -> float:
    """查 ISO 273 間隙孔直徑。

    Args:
        standard: 螺絲標準，如 "M5"
        fit: 配合等級：close / normal_clearance / loose_clearance

    Returns:
        孔直徑（mm）

    Raises:
        ValueError: 標準或等級不存在
    """
    fit_table = _CLEARANCE_HOLES.get(fit)
    if fit_table is None:
        valid = ", ".join(_CLEARANCE_HOLES.keys())
        raise ValueError(f"未知的配合等級 '{fit}'，有效值：{valid}")
    diameter = fit_table.get(standard)
    if diameter is None:
        valid = ", ".join(fit_table.keys())
        raise ValueError(f"未知的螺絲標準 '{standard}'，有效值：{valid}")
    return float(diameter)


def get_counterbore_dimensions(standard: str) -> dict[str, float]:
    """查 ISO 4762 內六角螺絲沉頭孔尺寸。

    Returns:
        {"diameter": float, "depth": float, "clearance": float}（mm）
    """
    dims = _COUNTERBORE.get(standard)
    if dims is None:
        valid = ", ".join(_COUNTERBORE.keys())
        raise ValueError(f"未知的螺絲標準 '{standard}'，有效值：{valid}")
    return dict(dims)


def get_nema_mounting(size: str) -> dict[str, float]:
    """查 NEMA 馬達安裝尺寸。

    Returns:
        {"bolt_hole_spacing_x": float, "bolt_hole_spacing_y": float,
         "bolt_hole_diameter": float, "pilot_diameter": float, "frame_size": float}（mm）
    """
    dims = _NEMA.get(size)
    if dims is None:
        valid = ", ".join(_NEMA.keys())
        raise ValueError(f"未知的 NEMA 尺寸 '{size}'，有效值：{valid}")
    return dict(dims)