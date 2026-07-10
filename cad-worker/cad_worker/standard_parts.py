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


# 材質密度表（g/cm³）
_MATERIAL_DENSITIES: dict[str, float] = {
    "pla": 1.24,
    "abs": 1.05,
    "petg": 1.27,
    "asa": 1.07,
    "nylon": 1.14,
    "aluminum": 2.70,
    "steel": 7.85,
    "stainless_steel": 8.00,
    "brass": 8.53,
    "copper": 8.96,
    "titanium": 4.51,
    "wood_pine": 0.43,
    "wood_oak": 0.75,
}


def get_material_density(material: str) -> float:
    """查材質密度（g/cm³）。

    Args:
        material: 材質名稱（不分大小寫），如 "pla"、"aluminum"、"steel"

    Returns:
        密度（g/cm³）

    Raises:
        ValueError: 材質不存在
    """
    key = material.lower().replace(" ", "_")
    density = _MATERIAL_DENSITIES.get(key)
    if density is None:
        valid = ", ".join(sorted(_MATERIAL_DENSITIES.keys()))
        raise ValueError(f"未知的材質 '{material}'，有效值：{valid}")
    return density


def calculate_mass(volume_mm3: float, material: str) -> float:
    """由體積（mm³）與材質計算質量（g）。

    Args:
        volume_mm3: 體積（立方毫米）
        material: 材質名稱

    Returns:
        質量（公克）
    """
    density_g_cm3 = get_material_density(material)
    volume_cm3 = volume_mm3 / 1000.0  # mm³ → cm³
    return volume_cm3 * density_g_cm3