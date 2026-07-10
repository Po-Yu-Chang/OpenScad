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
    """Golden model: NEMA17 stepper motor mount."""

    def test_builds_without_error(self):
        graph = _load_example("nema17-mount")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self):
        graph = _load_example("nema17-mount")
        adapter = Build123dAdapter()
        adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self):
        """Volume should be ~20300-20500 mm³.

        Base: 67×67×5 = 22445 mm³
        Center bore (Ø22, through): -π×11²×5 ≈ -1900 mm³
        4× M3 holes (Ø3.4, through): -4×π×1.7²×5 ≈ -181 mm³
        Fillet: small adjustment
        Expected: ~20360 ± fillet
        """
        graph = _load_example("nema17-mount")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert 20000 < result.volume < 21000, (
            f"Volume {result.volume:.1f} outside expected range"
        )

    def test_has_center_bore(self):
        """The center bore must actually reduce volume (R4 regression check)."""
        graph = _load_example("nema17-mount")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        # Base is 67×67×5 = 22445, so result must be significantly less
        assert result.volume < 21000, "Center bore not subtracted"

    def test_has_mount_holes(self):
        """The 4 mount holes must actually reduce volume (R4 regression check)."""
        graph = _load_example("nema17-mount")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        # Without mount holes, volume would be ~20544 (base - center bore)
        # With mount holes, should be ~20363
        assert result.volume < 20500, "Mount holes not subtracted"


class TestNeedleBox:
    """Golden model: 5×10 needle box organizer."""

    def test_builds_without_error(self):
        graph = _load_example("needle-box-5x10")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self):
        graph = _load_example("needle-box-5x10")
        adapter = Build123dAdapter()
        adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self):
        """Outer box: 96.5×51.5×30 ≈ 149107 mm³.
        Shell removes interior, 50 cell holes remove more.
        Final volume should be well under 100000.
        """
        graph = _load_example("needle-box-5x10")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result.volume < 100000, (
            f"Volume {result.volume:.1f} too high — shell or pockets not working"
        )


class TestEsp32CamEnclosure:
    """Golden model: ESP32-CAM camera enclosure."""

    def test_builds_without_error(self):
        graph = _load_example("esp32cam-enclosure")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result is not None

    def test_all_features_succeed(self):
        graph = _load_example("esp32cam-enclosure")
        adapter = Build123dAdapter()
        adapter.build(graph)
        for fid in graph.topological_sort():
            feat = graph.get_feature(fid)
            assert feat.rebuild_status == "success", (
                f"Feature {fid} failed: {feat.error_message}"
            )

    def test_volume_in_expected_range(self):
        """Bottom plate: 32×45×7.5 = 10800 mm³.
        Shell + holes should reduce it significantly.
        """
        graph = _load_example("esp32cam-enclosure")
        adapter = Build123dAdapter()
        result = adapter.build(graph)
        assert result.volume < 8000, (
            f"Volume {result.volume:.1f} too high — shell or holes not working"
        )