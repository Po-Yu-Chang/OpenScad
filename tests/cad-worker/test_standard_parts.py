"""Tests for standard parts lookup (ISO 273, NEMA)."""
import pytest
from cad_worker.standard_parts import (
    get_clearance_hole_diameter,
    get_counterbore_dimensions,
    get_nema_mounting,
)


class TestIso273Clearance:
    def test_m3_normal(self):
        d = get_clearance_hole_diameter("M3", "normal_clearance")
        assert 3.3 <= d <= 3.5

    def test_m3_close(self):
        d = get_clearance_hole_diameter("M3", "close")
        assert d == 3.20

    def test_m3_loose(self):
        d = get_clearance_hole_diameter("M3", "loose_clearance")
        assert d == 3.60

    def test_m6_normal(self):
        d = get_clearance_hole_diameter("M6", "normal_clearance")
        assert 6.5 <= d <= 6.7

    def test_m12_close(self):
        d = get_clearance_hole_diameter("M12", "close")
        assert d == 13.0

    def test_invalid_screw_size(self):
        with pytest.raises(ValueError, match="未知的螺絲標準"):
            get_clearance_hole_diameter("M99", "normal_clearance")

    def test_invalid_grade(self):
        with pytest.raises(ValueError, match="未知的配合等級"):
            get_clearance_hole_diameter("M3", "invalid_grade")


class TestNemaMounting:
    def test_nema17_bolt_spacing(self):
        data = get_nema_mounting("NEMA17")
        assert data["bolt_hole_spacing_x"] == 31.0
        assert data["bolt_hole_spacing_y"] == 31.0

    def test_nema17_pilot_diameter(self):
        data = get_nema_mounting("NEMA17")
        assert data["pilot_diameter"] == 22.0

    def test_nema23_bolt_spacing(self):
        data = get_nema_mounting("NEMA23")
        assert data["bolt_hole_spacing_x"] == 47.14

    def test_nema8_bolt_circle(self):
        data = get_nema_mounting("NEMA8")
        assert data["bolt_circle_diameter"] == 12.0

    def test_invalid_nema_size(self):
        with pytest.raises(ValueError, match="未知的 NEMA 尺寸"):
            get_nema_mounting("NEMA99")


class TestCounterbore:
    def test_m3_counterbore(self):
        cb = get_counterbore_dimensions("M3")
        assert cb["diameter"] == 6.0
        assert cb["depth"] == 3.0

    def test_m6_counterbore(self):
        cb = get_counterbore_dimensions("M6")
        assert cb["diameter"] == 11.0
        assert cb["depth"] == 6.0

    def test_invalid_screw(self):
        with pytest.raises(ValueError, match="未知的螺絲標準"):
            get_counterbore_dimensions("M99")