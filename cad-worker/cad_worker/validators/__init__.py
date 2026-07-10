"""OpenCad Validators — 幾何驗證器。

LLM 和預覽圖片不能作為模型正確性的唯一依據。
OpenCad 必須以幾何資料驗證。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationReport:
    """幾何驗證報告。"""
    is_valid: bool = True
    solid_count: int = 0
    bounding_box: dict[str, list[float]] = field(default_factory=lambda: {"min": [0, 0, 0], "max": [0, 0, 0]})
    size_x: float = 0.0
    size_y: float = 0.0
    size_z: float = 0.0
    volume: float = 0.0
    surface_area: float = 0.0
    hole_count: int = 0
    minimum_wall_thickness: float = 0.0
    is_closed_solid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "solid_count": self.solid_count,
            "bounding_box": self.bounding_box,
            "size_x": round(self.size_x, 4),
            "size_y": round(self.size_y, 4),
            "size_z": round(self.size_z, 4),
            "volume": round(self.volume, 4),
            "surface_area": round(self.surface_area, 4),
            "hole_count": self.hole_count,
            "minimum_wall_thickness": round(self.minimum_wall_thickness, 4),
            "is_closed_solid": self.is_closed_solid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class GeometryValidator:
    """幾何驗證器——以 BREP 和參數驗證模型正確性。"""

    def validate(self, part: Any, expected: dict[str, Any] | None = None) -> ValidationReport:
        """驗證建構結果。

        Args:
            part: build123d Part 或 trimesh 物件
            expected: 預期條件（來自 Feature Graph validation 欄位）

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        if part is None:
            report.is_valid = False
            report.errors.append("模型為空（None）")
            return report

        # 基本檢查
        self._check_brep_validity(part, report)
        self._check_solid_count(part, report)
        self._check_bounding_box(part, report)
        self._check_volume(part, report)
        self._check_hole_count(part, report)

        # 預期條件檢查
        if expected:
            self._check_expected(part, report, expected)

        return report

    def _check_brep_validity(self, part: Any, report: ValidationReport) -> None:
        """BREP 是否有效。"""
        try:
            is_valid = part.is_valid() if hasattr(part, "is_valid") else True
            if not is_valid:
                report.is_valid = False
                report.errors.append("BREP 無效")
        except Exception:
            report.warnings.append("無法檢查 BREP 有效性")

    def _check_solid_count(self, part: Any, report: ValidationReport) -> None:
        """實體數量是否符合預期。"""
        try:
            if hasattr(part, "solids"):
                solids = part.solids()
                report.solid_count = len(solids)
                report.is_closed_solid = report.solid_count > 0
            else:
                report.solid_count = 1
                report.is_closed_solid = True
        except Exception:
            report.warnings.append("無法檢查實體數量")

    def _check_bounding_box(self, part: Any, report: ValidationReport) -> None:
        """Bounding Box 是否符合外形尺寸。"""
        try:
            bb = part.bounding_box()
            min_pt = [bb.min.X, bb.min.Y, bb.min.Z]
            max_pt = [bb.max.X, bb.max.Y, bb.max.Z]
            report.bounding_box = {"min": min_pt, "max": max_pt}
            report.size_x = max_pt[0] - min_pt[0]
            report.size_y = max_pt[1] - min_pt[1]
            report.size_z = max_pt[2] - min_pt[2]
        except Exception:
            report.warnings.append("無法取得 Bounding Box")

    def _check_volume(self, part: Any, report: ValidationReport) -> None:
        """零體積或重複面檢查。"""
        try:
            if hasattr(part, "volume"):
                report.volume = part.volume
                if report.volume < 1e-6:
                    report.is_valid = False
                    report.errors.append("零體積實體")
            if hasattr(part, "area"):
                report.surface_area = part.area
        except Exception:
            report.warnings.append("無法取得體積／表面積")

    def _check_hole_count(self, part: Any, report: ValidationReport) -> None:
        """計算圓柱孔數量——偵測完整圓柱面（孔壁）。

        完整孔壁圓柱面最多 3 條邊（上下兩圓＋縫合線）；
        fillet 的部分圓柱面有 4 條邊（2 弧＋2 直線），藉此排除。
        """
        try:
            holes = 0
            if hasattr(part, "faces"):
                for face in part.faces():
                    try:
                        if "CYLINDER" not in str(getattr(face, "geom_type", "")):
                            continue
                        if len(face.edges()) <= 3:
                            holes += 1
                    except Exception:
                        pass
            report.hole_count = holes
        except Exception:
            report.warnings.append("無法計算孔數")

    def _check_expected(self, part: Any, report: ValidationReport, expected: dict[str, Any]) -> None:
        """檢查預期條件。"""
        # 預期實體數量
        if "expected_solid_count" in expected:
            if report.solid_count != expected["expected_solid_count"]:
                report.is_valid = False
                report.errors.append(
                    f"實體數量不符：預期 {expected['expected_solid_count']}，"
                    f"實際 {report.solid_count}"
                )

        # 預期 Bounding Box——X/Y/Z 三軸皆比對
        if "expected_bounding_box" in expected:
            bb_exp = expected["expected_bounding_box"]
            if "max" in bb_exp and bb_exp["max"]:
                actual = [report.size_x, report.size_y, report.size_z]
                for axis, name in enumerate(("X", "Y", "Z")):
                    exp_v = bb_exp["max"][axis] - (bb_exp["min"][axis] if "min" in bb_exp and bb_exp["min"] else 0)
                    if abs(actual[axis] - exp_v) > 0.05:
                        report.is_valid = False
                        report.errors.append(
                            f"{name} 尺寸不符：預期 {exp_v}，實際 {actual[axis]:.4f}"
                        )

        # 預期孔數
        if "expected_hole_count" in expected:
            actual_holes = report.hole_count
            if actual_holes != expected["expected_hole_count"]:
                report.is_valid = False
                report.errors.append(
                    f"孔數不符：預期 {expected['expected_hole_count']}，"
                    f"實際 {actual_holes}"
                )

        # 最小壁厚
        if "min_thickness_mm" in expected and expected["min_thickness_mm"]:
            if report.minimum_wall_thickness < expected["min_thickness_mm"]:
                # 壁厚檢查尚未完整實作，回報為警告而非錯誤
                report.warnings.append(
                    f"最小壁厚檢查尚未實作——無法確認是否 ≥ {expected['min_thickness_mm']} mm"
                )

        # 必須為單一實體
        if expected.get("must_be_single_solid"):
            if report.solid_count != 1:
                report.is_valid = False
                report.errors.append(
                    f"必須為單一實體，實際有 {report.solid_count} 個實體"
                )