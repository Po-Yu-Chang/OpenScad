"""Golden-model integration tests — builds the 3 example projects end-to-end.

These tests catch:
- R2/R3: adapter import failures (relative import, missing symbols)
- R4: chain-build structural issues (holes not subtracting)
- R5: fillet/chamfer signature issues
- R6: missing top-level imports
- R7: hole count validation
- General regressions in the Feature Graph → build123d pipeline
"""
import json
import os

import pytest

from cad_worker.feature_graph import FeatureGraph
from cad_worker.adapters import Build123dAdapter


# Skip all tests if build123d is not available
pytestmark = pytest.mark.skipif(
    not Build123dAdapter.__init__.__doc__ or False,  # placeholder
    reason="build123d not available",
)

try:
    from build123d import BuildPart, Box  # noqa: F401
    BUILD123D_AVAILABLE = True
except ImportError:
    BUILD123D_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not BUILD123D_AVAILABLE,
    reason="build123d not installed",
)

EXAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples"
)


def _load_example(name: str) -> FeatureGraph:
    path = os.path.join(EXAMPLES_DIR, name, "features.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return FeatureGraph.from_dict(data)


# ── WP1-0R2：雙引擎黃金模型測試 ──
# 三個範例專案（NEMA17/needle-box/esp32cam-enclosure）現在兩個引擎都要能
# rebuild 成功。FreeCAD 只在 cp311（FreeCAD 綁定的 Python 3.11）下可用，
# 系統 Python 跑這個檔案時 freecad 參數會 skip（不是 fail）。
import sys as _sys

_FREECAD_DIR = os.environ.get("FREECAD_DIR", "")
if not _FREECAD_DIR:
    _FREECAD_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "FreeCAD", "FreeCAD_1.1.1-Windows-x86_64-py311",
    )
    os.environ.setdefault("FREECAD_DIR", _FREECAD_DIR)
if os.path.isdir(_FREECAD_DIR):
    for _p in [os.path.join(_FREECAD_DIR, "bin"), os.path.join(_FREECAD_DIR, "lib")]:
        if _p not in _sys.path:
            _sys.path.insert(0, _p)

try:
    from cad_worker.adapters.freecad_adapter import FreeCADAdapter, FREECAD_AVAILABLE
except ImportError:
    FREECAD_AVAILABLE = False


@pytest.fixture(params=["build123d", "freecad"])
def golden_adapter(request):
    """依 §9.8 判準參數化雙引擎——同一份 golden test 對兩個引擎都跑一次。"""
    if request.param == "build123d":
        return Build123dAdapter()
    if not FREECAD_AVAILABLE:
        pytest.skip("FreeCAD not available（需 cp311 環境，見 FREECAD_DIR）")
    return FreeCADAdapter()


class TestAdapterImport:
    """R2/R3: adapter must import without errors."""

    def test_adapter_imports(self):
        """Importing the adapter module should not fail."""
        from cad_worker.adapters import Build123dAdapter
        adapter = Build123dAdapter()
        assert adapter is not None

    def test_build123d_symbols_available(self):
        """All required build123d symbols must be importable."""
        from build123d import (
            BuildPart, BuildSketch, Part, Plane,
            Pos, Mode, Axis,
            extrude, revolve, offset, add,
            Cylinder, Box, Rectangle, Circle,
            Locations, GridLocations,
        )
        assert BuildPart is not None


class TestNema17Mount:
    """Golden model: NEMA17 stepper motor mount（雙引擎，見 golden_adapter）。"""

    def test_builds_without_error(self, golden_adapter):
        graph = _load_example("nema17-mount")
        result = golden_adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self, golden_adapter):
        graph = _load_example("nema17-mount")
        golden_adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self, golden_adapter):
        """Volume should be ~19000-21000 mm³（雙引擎實測：build123d≈20346，
        FreeCAD≈19434——差異來自兩引擎 fillet 邊選取/拓樸細節不同，非錯誤，
        見檔案開頭 WP-H4 判準說明：不比對面/邊數，只比對體積範圍）。

        Base: 67×67×5 = 22445 mm³
        Center bore (Ø22, through): -π×11²×5 ≈ -1900 mm³
        4× M3 holes (Ø3.4, through): -4×π×1.7²×5 ≈ -181 mm³
        Fillet: small adjustment
        """
        graph = _load_example("nema17-mount")
        result = golden_adapter.build(graph)
        assert 19000 < result.volume < 21000, (
            f"Volume {result.volume:.1f} outside expected range"
        )

    def test_has_center_bore(self, golden_adapter):
        """The center bore must actually reduce volume (R4 regression check)."""
        graph = _load_example("nema17-mount")
        result = golden_adapter.build(graph)
        # Base is 67×67×5 = 22445, so result must be significantly less
        assert result.volume < 21000, "Center bore not subtracted"

    def test_has_mount_holes(self, golden_adapter):
        """The 4 mount holes must actually reduce volume (R4 regression check)."""
        graph = _load_example("nema17-mount")
        result = golden_adapter.build(graph)
        # Without mount holes, volume would be ~20544 (base - center bore)
        assert result.volume < 20500, "Mount holes not subtracted"


class TestNeedleBox:
    """Golden model: 5×10 needle box organizer（雙引擎，見 golden_adapter）。"""

    def test_builds_without_error(self, golden_adapter):
        graph = _load_example("needle-box-5x10")
        result = golden_adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self, golden_adapter):
        graph = _load_example("needle-box-5x10")
        golden_adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self, golden_adapter):
        """Outer box: 96.5×51.5×30 ≈ 149107 mm³.
        Shell removes interior, 50 cell holes remove more.
        Final volume should be well under 100000.
        """
        graph = _load_example("needle-box-5x10")
        result = golden_adapter.build(graph)
        assert result.volume < 100000, (
            f"Volume {result.volume:.1f} too high — shell or pockets not working"
        )


class TestEsp32CamEnclosure:
    """Golden model: ESP32-CAM camera enclosure（雙引擎，見 golden_adapter）。"""

    def test_builds_without_error(self, golden_adapter):
        graph = _load_example("esp32cam-enclosure")
        result = golden_adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self, golden_adapter):
        graph = _load_example("esp32cam-enclosure")
        golden_adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self, golden_adapter):
        """Bottom plate: 32×45×7.5 = 10800 mm³.
        Shell + holes should reduce it significantly.
        """
        graph = _load_example("esp32cam-enclosure")
        result = golden_adapter.build(graph)
        assert result.volume < 8000, (
            f"Volume {result.volume:.1f} too high — shell or holes not working"
        )


class TestSketchDatumPlanes:
    """P0: Sketch datum plane tests — verifies that sketches on XZ and YZ
    planes extrude along the correct axis (Y and X respectively, not Z)."""

    def _make_graph_with_sketch(self, plane_base: str) -> FeatureGraph:
        """Build a minimal FeatureGraph: one sketch + one pad on the given plane."""
        from cad_worker.feature_graph import Feature, FeatureGraph, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sketch_1",
            type=FeatureType.SKETCH,
            name="test sketch",
            parameters={},
            sketch_entities=[
                {"type": "rectangle", "x": -25, "y": -20, "w": 50, "h": 40},
            ],
            plane={"base": plane_base, "offset": 0},
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad_1",
            type=FeatureType.PAD,
            name="test pad",
            parameters={"length": 5},
            input="sketch_1",
        )
        graph.add_feature(pad)
        return graph

    def test_xy_sketch_extrudes_along_z(self):
        """XY plane sketch + pad → bbox Z should be 5 (extrude along Z)."""
        graph = self._make_graph_with_sketch("XY")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        # XY sketch 50×40, pad 5mm → X=50, Y=40, Z=5
        assert abs((bb.max.X - bb.min.X) - 50) < 1, f"X dim wrong: {bb.max.X - bb.min.X}"
        assert abs((bb.max.Y - bb.min.Y) - 40) < 1, f"Y dim wrong: {bb.max.Y - bb.min.Y}"
        assert abs((bb.max.Z - bb.min.Z) - 5) < 1, f"Z dim wrong: {bb.max.Z - bb.min.Z}"

    def test_xz_sketch_extrudes_along_y(self):
        """XZ plane sketch + pad → bbox Y should be 5 (extrude along Y, not Z)."""
        graph = self._make_graph_with_sketch("XZ")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        # XZ sketch: X=50, Z=40, extrude along Y=5
        assert abs((bb.max.X - bb.min.X) - 50) < 1, f"X dim wrong: {bb.max.X - bb.min.X}"
        assert abs((bb.max.Y - bb.min.Y) - 5) < 1, f"Y dim wrong: {bb.max.Y - bb.min.Y}"
        assert abs((bb.max.Z - bb.min.Z) - 40) < 1, f"Z dim wrong: {bb.max.Z - bb.min.Z}"

    def test_yz_sketch_extrudes_along_x(self):
        """YZ plane sketch + pad → bbox X should be 5 (extrude along X, not Z)."""
        graph = self._make_graph_with_sketch("YZ")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        # YZ sketch: Y=50, Z=40, extrude along X=5
        assert abs((bb.max.X - bb.min.X) - 5) < 1, f"X dim wrong: {bb.max.X - bb.min.X}"
        assert abs((bb.max.Y - bb.min.Y) - 50) < 1, f"Y dim wrong: {bb.max.Y - bb.min.Y}"
        assert abs((bb.max.Z - bb.min.Z) - 40) < 1, f"Z dim wrong: {bb.max.Z - bb.min.Z}"

    def test_plane_backward_compat(self):
        """Feature with no plane field defaults to XY."""
        from cad_worker.feature_graph import Feature, FeatureGraph, FeatureType
        graph = FeatureGraph()
        # Simulate an old project's dict (no "plane" key) going through from_dict,
        # exercising the deserialization default rather than the dataclass default.
        old_sketch_dict = Feature(
            feature_id="sketch_1",
            type=FeatureType.SKETCH,
            name="old sketch",
            parameters={},
            sketch_entities=[
                {"type": "rectangle", "x": -10, "y": -10, "w": 20, "h": 20},
            ],
        ).to_dict()
        del old_sketch_dict["plane"]
        sketch = Feature.from_dict(old_sketch_dict)
        assert sketch.plane == {"base": "XY", "offset": 0}
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad_1",
            type=FeatureType.PAD,
            name="old pad",
            parameters={"length": 3},
            input="sketch_1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        # Default XY → extrude along Z = 3
        bb = result.bounding_box()
        assert abs((bb.max.Z - bb.min.Z) - 3) < 1, f"Z dim wrong: {bb.max.Z - bb.min.Z}"

    def test_plane_offset(self):
        """Plane offset shifts the sketch along the plane normal."""
        from cad_worker.feature_graph import Feature, FeatureGraph, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sketch_1",
            type=FeatureType.SKETCH,
            name="offset sketch",
            parameters={},
            sketch_entities=[
                {"type": "rectangle", "x": -10, "y": -10, "w": 20, "h": 20},
            ],
            plane={"base": "XY", "offset": 10},
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad_1",
            type=FeatureType.PAD,
            name="offset pad",
            parameters={"length": 5},
            input="sketch_1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        # XY plane offset 10 → Z starts at 10, goes to 15
        assert bb.min.Z >= 9, f"Z min should be ~10, got {bb.min.Z}"
        assert bb.max.Z <= 16, f"Z max should be ~15, got {bb.max.Z}"

    def test_plane_round_trip(self):
        """Plane field survives to_dict / from_dict round-trip."""
        from cad_worker.feature_graph import Feature, FeatureType
        f = Feature(
            feature_id="s1", type=FeatureType.SKETCH, name="test",
            parameters={}, sketch_entities=[],
            plane={"base": "XZ", "offset": 5},
        )
        d = f.to_dict()
        assert d["plane"] == {"base": "XZ", "offset": 5}
        f2 = Feature.from_dict(d)
        assert f2.plane == {"base": "XZ", "offset": 5}

class TestSketchLineArc:
    """P1-1: Line and arc sketch entity support."""

    def test_line_entity_builds(self):
        """A line entity in a sketch is accepted by the adapter."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        # Use a rectangle (closed) + a line entity (auxiliary)
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="rect+line",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 20, "height": 10, "center_x": 0, "center_y": 0}},
                {"entity_type": "line", "parameters": {"x1": -15, "y1": 0, "x2": 15, "y2": 0}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        assert bb.max.X - bb.min.X >= 19, f"Width should be ~20, got {bb.max.X - bb.min.X}"
        assert bb.max.Y - bb.min.Y >= 9, f"Height should be ~10, got {bb.max.Y - bb.min.Y}"

    def test_arc_entity_builds(self):
        """An arc entity in a sketch is accepted by the adapter."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="rect+arc",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 20, "height": 10, "center_x": 0, "center_y": 0}},
                {"entity_type": "arc", "parameters": {"center_x": 0, "center_y": 0, "radius": 3, "start_angle": 0, "end_angle": 90}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None

    def test_open_polyline_rejected_for_pad(self):
        """An open polyline without any closed entity raises SKETCH_NOT_CLOSED."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="open-polyline",
            parameters={}, sketch_entities=[
                {"entity_type": "polyline", "parameters": {"points": [[0, 0], [10, 0], [10, 5]], "closed": False}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        with pytest.raises(ValueError, match="未閉合"):
            adapter.build(graph)

    def test_closed_polyline_pad(self):
        """A closed polyline can be padded into a solid."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="closed-polyline",
            parameters={}, sketch_entities=[
                {"entity_type": "polyline", "parameters": {"points": [[0, 0], [20, 0], [20, 10], [0, 10]], "closed": True}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        bb = result.bounding_box()
        assert bb.max.X - bb.min.X >= 19, f"Width should be ~20, got {bb.max.X - bb.min.X}"
        assert bb.max.Y - bb.min.Y >= 9, f"Height should be ~10, got {bb.max.Y - bb.min.Y}"

    def test_construction_line_ignored(self):
        """Construction lines are auxiliary and don't break the sketch."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="rect+cline",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 20, "height": 10, "center_x": 0, "center_y": 0}},
                {"entity_type": "construction_line", "parameters": {"x1": -15, "y1": 0, "x2": 15, "y2": 0}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None


class TestCounterboreHole:
    """P1-3: Counterbore hole support."""

    def test_counterbore_hole_builds(self):
        """A counterbore hole feature creates a two-stage hole."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        # Base box
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        )
        box = Feature(
            feature_id="box1", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk1",
        )
        graph.add_feature(sketch)
        graph.add_feature(box)
        # Counterbore hole for M3
        hole = Feature(
            feature_id="hole1", type=FeatureType.HOLE, name="cb-hole",
            parameters={
                "hole_type": "counterbore",
                "depth": 8,
                "positions": [[0, 0]],
            },
            standard_parts={"fastener": {"standard": "M3", "fit": "normal_clearance"}},
            input="box1",
        )
        graph.add_feature(hole)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        # Verify volume is less than the solid box (material was removed)
        box_only_graph = FeatureGraph()
        box_only_graph.add_feature(Feature(
            feature_id="sk0", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        ))
        box_only_graph.add_feature(Feature(
            feature_id="box0", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk0",
        ))
        solid_box = adapter.build(box_only_graph)
        assert result.volume < solid_box.volume, "Counterbore hole should remove material"

    def test_simple_hole_still_works(self):
        """Simple holes (without counterbore) still work."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        )
        box = Feature(
            feature_id="box1", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk1",
        )
        graph.add_feature(sketch)
        graph.add_feature(box)
        hole = Feature(
            feature_id="hole1", type=FeatureType.HOLE, name="simple-hole",
            parameters={"diameter": 5, "depth": 5, "positions": [[0, 0]]},
            input="box1",
        )
        graph.add_feature(hole)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        box_only_graph = FeatureGraph()
        box_only_graph.add_feature(Feature(
            feature_id="sk0", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        ))
        box_only_graph.add_feature(Feature(
            feature_id="box0", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk0",
        ))
        solid_box = adapter.build(box_only_graph)
        assert result.volume < solid_box.volume, "Hole should remove material"

    def test_counterbore_larger_diameter(self):
        """Counterbore hole removes more material than a simple hole."""
        from cad_worker.feature_graph import Feature, FeatureType
        # Simple hole
        graph_simple = FeatureGraph()
        graph_simple.add_feature(Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        ))
        graph_simple.add_feature(Feature(
            feature_id="box1", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk1",
        ))
        graph_simple.add_feature(Feature(
            feature_id="hole1", type=FeatureType.HOLE, name="simple",
            parameters={"diameter": 3, "depth": 10, "through_all": True, "positions": [[0, 0]]},
            input="box1",
        ))
        adapter = Build123dAdapter()
        simple_result = adapter.build(graph_simple)

        # Counterbore hole
        graph_cb = FeatureGraph()
        graph_cb.add_feature(Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="base sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 30, "height": 30, "center_x": 0, "center_y": 0}},
            ],
        ))
        graph_cb.add_feature(Feature(
            feature_id="box1", type=FeatureType.PAD, name="base",
            parameters={"length": 10}, input="sk1",
        ))
        graph_cb.add_feature(Feature(
            feature_id="hole1", type=FeatureType.HOLE, name="cb",
            parameters={
                "hole_type": "counterbore", "depth": 10, "through_all": True,
                "positions": [[0, 0]],
            },
            standard_parts={"fastener": {"standard": "M3", "fit": "normal_clearance"}},
            input="box1",
        ))
        cb_result = adapter.build(graph_cb)

        # Counterbore removes more material (larger top hole)
        assert cb_result.volume < simple_result.volume, \
            "Counterbore should remove more material than simple hole"


class TestSweepLoft:
    """P1-2: Sweep and Loft feature support."""

    def test_sweep_circle_along_line(self):
        """Sweep a circle profile along a straight path."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        # Profile: circle sketch on XY
        profile = Feature(
            feature_id="prof1", type=FeatureType.SKETCH, name="circle profile",
            parameters={}, sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 5, "center_x": 0, "center_y": 0}},
            ],
        )
        graph.add_feature(profile)
        # Path: line sketch on XZ (perpendicular to XY profile) — sweep along Z
        path = Feature(
            feature_id="path1", type=FeatureType.SKETCH, name="path",
            parameters={}, sketch_entities=[
                {"entity_type": "line", "parameters": {"x1": 0, "y1": 0, "x2": 0, "y2": 20}},
            ],
            plane={"base": "XZ", "offset": 0},
        )
        graph.add_feature(path)
        # Sweep
        sweep_feat = Feature(
            feature_id="sweep1", type=FeatureType.SWEEP, name="swept tube",
            parameters={}, input="prof1", references=["path1"],
        )
        graph.add_feature(sweep_feat)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        assert result.volume > 0, "Sweep should produce a solid with volume"

    def test_sweep_rectangle_along_line(self):
        """Sweep a rectangle profile along a path."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        # Profile: rectangle on XY
        profile = Feature(
            feature_id="prof1", type=FeatureType.SKETCH, name="rect profile",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 10, "height": 5, "center_x": 0, "center_y": 0}},
            ],
        )
        graph.add_feature(profile)
        # Path: line on XZ (sweep along Z, perpendicular to XY profile)
        path = Feature(
            feature_id="path1", type=FeatureType.SKETCH, name="path",
            parameters={}, sketch_entities=[
                {"entity_type": "line", "parameters": {"x1": 0, "y1": 0, "x2": 0, "y2": 30}},
            ],
            plane={"base": "XZ", "offset": 0},
        )
        graph.add_feature(path)
        sweep_feat = Feature(
            feature_id="sweep1", type=FeatureType.SWEEP, name="swept bar",
            parameters={}, input="prof1", references=["path1"],
        )
        graph.add_feature(sweep_feat)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        assert result.volume > 0, "Sweep should produce a solid"

    def test_sweep_no_path_raises(self):
        """Sweep without a path reference raises an error."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        profile = Feature(
            feature_id="prof1", type=FeatureType.SKETCH, name="profile",
            parameters={}, sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 5, "center_x": 0, "center_y": 0}},
            ],
        )
        graph.add_feature(profile)
        sweep_feat = Feature(
            feature_id="sweep1", type=FeatureType.SWEEP, name="no-path",
            parameters={}, input="prof1", references=[],
        )
        graph.add_feature(sweep_feat)
        adapter = Build123dAdapter()
        with pytest.raises(ValueError, match="路徑"):
            adapter.build(graph)

    def test_loft_two_circles(self):
        """Loft between two circle profiles on different planes."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        # Bottom circle on XY
        prof1 = Feature(
            feature_id="prof1", type=FeatureType.SKETCH, name="bottom circle",
            parameters={}, sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 5, "center_x": 0, "center_y": 0}},
            ],
        )
        graph.add_feature(prof1)
        # Top circle on XY offset 20
        prof2 = Feature(
            feature_id="prof2", type=FeatureType.SKETCH, name="top circle",
            parameters={}, sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 10, "center_x": 0, "center_y": 0}},
            ],
            plane={"base": "XY", "offset": 20},
        )
        graph.add_feature(prof2)
        # Loft
        loft_feat = Feature(
            feature_id="loft1", type=FeatureType.LOFT, name="lofted shape",
            parameters={}, input="prof1", references=["prof2"],
        )
        graph.add_feature(loft_feat)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        assert result.volume > 0, "Loft should produce a solid with volume"

    def test_loft_too_few_profiles_raises(self):
        """Loft with only one profile raises an error."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        prof1 = Feature(
            feature_id="prof1", type=FeatureType.SKETCH, name="only profile",
            parameters={}, sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 5, "center_x": 0, "center_y": 0}},
            ],
        )
        graph.add_feature(prof1)
        loft_feat = Feature(
            feature_id="loft1", type=FeatureType.LOFT, name="too few",
            parameters={}, input="prof1", references=[],
        )
        graph.add_feature(loft_feat)
        adapter = Build123dAdapter()
        with pytest.raises(ValueError, match="兩個輪廓"):
            adapter.build(graph)


class TestSlotFeature:
    """E2: Slot (長圓孔) golden model tests."""

    def test_slot_sketch_builds(self):
        """A slot sketch entity produces a valid sketch."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="slot sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "slot", "parameters": {"width": 20, "height": 8, "center_x": 0, "center_y": 0}},
            ],
        )
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 5}, input="sk1",
        )
        graph.add_feature(sketch)
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        assert result.volume > 0, "Slot pad should produce a solid"

    def test_slot_pad_volume(self):
        """Slot pad volume matches expected dimensions."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="slot sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "slot", "parameters": {"width": 20, "height": 8, "center_x": 0, "center_y": 0}},
            ],
        )
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 10}, input="sk1",
        )
        graph.add_feature(sketch)
        graph.add_feature(pad)
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        # SlotOverall(20, 8) area = (20-8)*8 + pi*16 = 96 + 50.27 = ~146.27
        # Volume = area * 10 = ~1462.7
        assert result.volume == pytest.approx(1462.7, rel=0.05), \
            f"Expected ~1462.7 mm³, got {result.volume}"

    def test_slot_in_pocket(self):
        """A slot-shaped pocket removes material correctly."""
        from cad_worker.feature_graph import Feature, FeatureType
        # Base box
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="base",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 40, "height": 40, "center_x": 0, "center_y": 0}},
            ],
        ))
        graph.add_feature(Feature(
            feature_id="pad1", type=FeatureType.PAD, name="base pad",
            parameters={"length": 10}, input="sk1",
        ))
        # Slot pocket
        graph.add_feature(Feature(
            feature_id="sk2", type=FeatureType.SKETCH, name="slot sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "slot", "parameters": {"width": 20, "height": 8, "center_x": 0, "center_y": 0}},
            ],
        ))
        graph.add_feature(Feature(
            feature_id="pocket1", type=FeatureType.POCKET, name="slot pocket",
            parameters={"depth": 3}, input="pad1", references=["sk2"],
        ))
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None
        # Base box volume = 40*40*10 = 16000, pocket removes ~146.27*3 = ~438.8
        assert result.volume < 16000, "Pocket should remove material"
        assert result.volume > 15500, "Pocket shouldn't remove too much material"


class TestMassProperties:
    """P1-4: 質量屬性測試。"""

    def test_material_density_lookup(self):
        """Standard parts table returns correct densities."""
        from cad_worker.standard_parts import get_material_density
        assert get_material_density("pla") == pytest.approx(1.24)
        assert get_material_density("aluminum") == pytest.approx(2.70)
        assert get_material_density("steel") == pytest.approx(7.85)
        # Case-insensitive
        assert get_material_density("PLA") == pytest.approx(1.24)
        assert get_material_density("Aluminum") == pytest.approx(2.70)

    def test_invalid_material_raises(self):
        """Invalid material name raises ValueError."""
        from cad_worker.standard_parts import get_material_density
        with pytest.raises(ValueError, match="未知的材質"):
            get_material_density("unobtainium")

    def test_calculate_mass(self):
        """Mass = volume * density."""
        from cad_worker.standard_parts import calculate_mass
        # 1000 mm³ = 1 cm³, PLA density 1.24 g/cm³ → 1.24 g
        mass = calculate_mass(1000.0, "pla")
        assert mass == pytest.approx(1.24, rel=0.01)
        # Steel: 1000 mm³ → 7.85 g
        mass_steel = calculate_mass(1000.0, "steel")
        assert mass_steel == pytest.approx(7.85, rel=0.01)

    def test_rebuild_returns_mass_properties(self):
        """Rebuild response includes mass properties."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="box sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 10, "height": 10}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 10}, input="sk1",
        )
        graph.add_feature(pad)

        adapter = Build123dAdapter()
        part = adapter.build(graph)
        assert part is not None

        volume_mm3 = float(part.volume)
        from cad_worker.standard_parts import calculate_mass
        mass_g = calculate_mass(volume_mm3, "pla")
        assert volume_mm3 == pytest.approx(1000.0, rel=0.01), f"Expected 1000 mm³, got {volume_mm3}"
        assert mass_g == pytest.approx(1.24, rel=0.01), f"Expected 1.24 g, got {mass_g}"

    def test_bounding_box(self):
        """Part bounding box matches expected dimensions."""
        from cad_worker.feature_graph import Feature, FeatureType
        graph = FeatureGraph()
        sketch = Feature(
            feature_id="sk1", type=FeatureType.SKETCH, name="box sketch",
            parameters={}, sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 20, "height": 15}},
            ],
        )
        graph.add_feature(sketch)
        pad = Feature(
            feature_id="pad1", type=FeatureType.PAD, name="pad",
            parameters={"length": 10}, input="sk1",
        )
        graph.add_feature(pad)

        adapter = Build123dAdapter()
        part = adapter.build(graph)
        bb = part.bounding_box()
        assert bb.size.X == pytest.approx(20, abs=0.1)
        assert bb.size.Y == pytest.approx(15, abs=0.1)
        assert bb.size.Z == pytest.approx(10, abs=0.1)
