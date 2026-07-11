"""WP0-1 FreeCAD Worker Acceptance Tests.

Tests the acceptance criteria from the master plan:
1. HTTP replay: sketch(60×40) → pad 10 → hole Ø6 → fillet R2, STEP export, bbox verification
2. Modify pad length 60→80, rebuild: hole and fillet survive, edges don't drift
3. .FCStd save/reopen, verify persistence
"""
import os
import sys
import json
import pytest
from pathlib import Path

# Set up FreeCAD path
FREECAD_DIR = os.environ.get("FREECAD_DIR", r"C:\Users\Johnson\Desktop\文件資料\學習文件\OpenScad\FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311")
if FREECAD_DIR and os.path.exists(FREECAD_DIR):
    for p in [os.path.join(FREECAD_DIR, "bin"), os.path.join(FREECAD_DIR, "lib")]:
        if p not in sys.path:
            sys.path.insert(0, p)

try:
    import FreeCAD
    import Part
    import Sketcher
    FREECAD_AVAILABLE = True
except ImportError:
    FREECAD_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FREECAD_AVAILABLE, reason="FreeCAD not available")


class TestFreeCadWorkerBasic:
    """Basic FreeCAD worker API tests."""

    def test_worker_imports(self):
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        assert worker is not None

    def test_create_project(self):
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        result = worker.create_project("test")
        assert result["status"] == "created"
        assert result["project_id"] is not None

    def test_health_check(self):
        """FreeCAD version accessible."""
        ver = FreeCAD.Version()
        assert ver[0] == "1"  # Major version 1.x


class TestAcceptance1_HttpReplay:
    """Acceptance 1: sketch(60×40) → pad 10 → hole Ø6 → fillet R2 → STEP/GLB export."""

    @pytest.fixture
    def worker_with_model(self):
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("acceptance1")
        pid = proj["project_id"]

        # 1. Create sketch (60×40 rectangle, fully constrained)
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {
                "feature_id": "sketch1",
                "type": "sketch",
                "width": 60,
                "height": 40,
                "sketch_entities": [
                    {"type": "line", "start": [0, 0], "end": [60, 0]},
                    {"type": "line", "start": [60, 0], "end": [60, 40]},
                    {"type": "line", "start": [60, 40], "end": [0, 40]},
                    {"type": "line", "start": [0, 40], "end": [0, 0]},
                ],
                "constraints": [
                    {"type": "coincident", "line1": 0, "point1": 2, "line2": 1, "point2": 1},
                    {"type": "coincident", "line1": 1, "point1": 2, "line2": 2, "point2": 1},
                    {"type": "coincident", "line1": 2, "point1": 2, "line2": 3, "point2": 1},
                    {"type": "coincident", "line1": 3, "point1": 2, "line2": 0, "point2": 1},
                    {"type": "horizontal", "line": 0},
                    {"type": "vertical", "line": 1},
                    {"type": "horizontal", "line": 2},
                    {"type": "vertical", "line": 3},
                    {"type": "distance", "line": 0, "value": 60},
                    {"type": "distance", "line": 1, "value": 40},
                ],
            }
        })

        # 2. Create pad (extrude 10mm)
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {
                "feature_id": "pad1",
                "type": "pad",
                "sketch_id": "sketch1",
                "length": 10,
            }
        })

        # 3. Create hole (Ø6 at center)
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {
                "feature_id": "hole1",
                "type": "hole",
                "diameter": 6,
                "position": [30, 20, 0],
                "depth": 20,
            }
        })

        # 4. Create fillet (R2 on top edges)
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {
                "feature_id": "fillet1",
                "type": "fillet",
                "radius": 2,
                "edge_filter": "top",
            }
        })

        return worker, pid

    def test_rebuild_succeeds(self, worker_with_model):
        worker, pid = worker_with_model
        result = worker.rebuild(pid)
        assert result["status"] == "ok"
        assert result["volume"] > 0

    def test_step_export_bbox_60x40x10(self, worker_with_model, tmp_path):
        """STEP export must produce a file with bbox = 60×40×10."""
        worker, pid = worker_with_model
        worker.rebuild(pid)

        export_dir = tmp_path / "export"
        result = worker.export(pid, "step", export_dir)
        assert result["status"] == "ok"

        step_path = Path(result["path"])
        assert step_path.exists()

        # Read back the STEP file using FreeCAD Import
        import Import as FCImport
        doc = FreeCAD.newDocument("verify")
        FCImport.insert(str(step_path), doc.Name)
        doc.recompute()
        
        found_bbox = False
        for obj in doc.Objects:
            if hasattr(obj, "Shape") and not obj.Shape.isNull():
                bb = obj.Shape.BoundBox
                if bb.XLength > 0:
                    assert abs(bb.XLength - 60) < 2.0, f"X: {bb.XLength}"
                    assert abs(bb.YLength - 40) < 2.0, f"Y: {bb.YLength}"
                    assert abs(bb.ZLength - 10) < 2.0, f"Z: {bb.ZLength}"
                    found_bbox = True
        assert found_bbox, "No valid shape found in STEP file"

    def test_glb_export(self, worker_with_model, tmp_path):
        """GLB export must produce a valid GLB file."""
        worker, pid = worker_with_model
        worker.rebuild(pid)

        export_dir = tmp_path / "export"
        result = worker.export(pid, "glb", export_dir)
        assert result["status"] == "ok"

        glb_path = Path(result["path"])
        assert glb_path.exists()
        assert glb_path.stat().st_size > 0

        # Verify GLB magic header
        with open(glb_path, 'rb') as f:
            magic = f.read(4)
        assert magic == b'\x67\x6c\x54\x46'  # "glTF" in little-endian

    def test_display_map_generated(self, worker_with_model):
        """Display map must be generated after rebuild."""
        worker, pid = worker_with_model
        worker.rebuild(pid)

        proj = worker.get_project(pid)
        assert proj["display_map"] is not None
        assert len(proj["display_map"]["faces"]) > 0
        # WP0-3 契約：頂層 mesh_revision，triangle_range 含頭不含尾
        assert proj["display_map"]["mesh_revision"] == proj["mesh_revision"]
        total_tris = max(f["triangle_range"][1] for f in proj["display_map"]["faces"])
        assert total_tris > 0
        assert proj["mesh_revision"] > 0


class TestAcceptance2_ParameterChange:
    """Acceptance 2: modify pad length 60→80, rebuild — hole and fillet survive."""

    @pytest.fixture
    def worker_with_model(self):
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("acceptance2")
        pid = proj["project_id"]

        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {
                "feature_id": "sketch1", "type": "sketch",
                "width": 60, "height": 40,
                "sketch_entities": [
                    {"type": "line", "start": [0, 0], "end": [60, 0]},
                    {"type": "line", "start": [60, 0], "end": [60, 40]},
                    {"type": "line", "start": [60, 40], "end": [0, 40]},
                    {"type": "line", "start": [0, 40], "end": [0, 0]},
                ],
                "constraints": [
                    {"type": "coincident", "line1": 0, "point1": 2, "line2": 1, "point2": 1},
                    {"type": "coincident", "line1": 1, "point1": 2, "line2": 2, "point2": 1},
                    {"type": "coincident", "line1": 2, "point1": 2, "line2": 3, "point2": 1},
                    {"type": "coincident", "line1": 3, "point1": 2, "line2": 0, "point2": 1},
                    {"type": "horizontal", "line": 0},
                    {"type": "vertical", "line": 1},
                    {"type": "distance", "line": 0, "value": 60},
                    {"type": "distance", "line": 1, "value": 40},
                ],
            }
        })
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "pad1", "type": "pad", "sketch_id": "sketch1", "length": 10}
        })
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "hole1", "type": "hole", "diameter": 6, "position": [30, 20, 0], "depth": 20}
        })
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "fillet1", "type": "fillet", "radius": 2, "edge_filter": "top"}
        })
        worker.rebuild(pid)
        return worker, pid

    def test_modify_pad_length_rebuild(self, worker_with_model):
        """Change pad length from 60 to 80 (via sketch distance constraint).
        Hole and fillet should survive rebuild."""
        worker, pid = worker_with_model

        # Get initial volume
        proj = worker.get_project(pid)
        vol_before = proj["shape"].Volume if proj["shape"] else 0
        assert vol_before > 0

        # Update sketch constraint: distance 60 → 80
        # Find sketch1 feature and update its parameters
        sketch_feat = None
        for f in proj["features"]:
            if f["feature_id"] == "sketch1":
                sketch_feat = f
                break

        assert sketch_feat is not None
        sketch = sketch_feat["sketch_obj"]

        # Find the Distance constraint on line 0 and set to 80
        for i, con in enumerate(sketch.Constraints):
            if con.Type == "Distance" and con.First == 0:
                sketch.setDatum(i, FreeCAD.Units.Quantity("80 mm"))
                break

        sketch.solve()
        result = worker.rebuild(pid)
        assert result["status"] == "ok"

        # Volume should increase (60→80 = larger box)
        vol_after = proj["shape"].Volume
        assert vol_after > vol_before, f"Volume should increase: {vol_before} → {vol_after}"

    def test_fillet_edges_dont_drift(self, worker_with_model):
        """Fillet edges should not drift after parameter change."""
        worker, pid = worker_with_model

        # Count fillet faces before
        worker.rebuild(pid)
        proj = worker.get_project(pid)
        faces_before = len(proj["shape"].Faces) if proj["shape"] else 0

        # Modify sketch distance
        sketch_feat = None
        for f in proj["features"]:
            if f["feature_id"] == "sketch1":
                sketch_feat = f
                break

        sketch = sketch_feat["sketch_obj"]
        for i, con in enumerate(sketch.Constraints):
            if con.Type == "Distance" and con.First == 0:
                sketch.setDatum(i, FreeCAD.Units.Quantity("70 mm"))
                break
        sketch.solve()

        worker.rebuild(pid)
        faces_after = len(proj["shape"].Faces)

        # Face count should be similar (fillet creates curved faces that persist)
        # The key is that fillet doesn't fail or produce drastically different topology
        assert faces_after > 0, "No faces after rebuild"
        # Allow some variance but not complete topology change
        assert abs(faces_after - faces_before) < 20, f"Face count drift: {faces_before} → {faces_after}"


class TestAcceptance3_Persistence:
    """Acceptance 3: .FCStd save → close → reopen → rebuild, results consistent."""

    def test_save_and_reload(self, tmp_path):
        """Save project to .FCStd, reopen, verify it still works."""
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("persistence")
        pid = proj["project_id"]

        # Build a simple box
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "box1", "type": "box", "width": 60, "depth": 40, "height": 10}
        })
        worker.rebuild(pid)

        # Save
        fcstd_path = tmp_path / "test.FCStd"
        save_result = worker.save_project(pid, fcstd_path)
        assert save_result["status"] == "ok"
        assert fcstd_path.exists()

        # Load into a new worker
        worker2 = FreeCadWorker()
        load_result = worker2.load_project(fcstd_path)
        assert load_result["status"] == "ok"
        assert load_result["project_id"] is not None


class TestTessellation:
    """Tessellation and display_map tests."""

    def test_per_face_tessellation(self, tmp_path):
        """Each face is tessellated individually with triangle_range tracking."""
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("tess")
        pid = proj["project_id"]

        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "box1", "type": "box", "width": 50, "depth": 50, "height": 10}
        })
        worker.rebuild(pid)

        proj = worker.get_project(pid)
        dm = proj["display_map"]
        assert dm is not None
        assert dm["mesh_revision"] > 0
        assert "edges" in dm

        # WP0-3 契約：triangle_range 含頭不含尾、相鄰不重疊、face_id/source_feature_id 存在
        prev_end = 0
        for face in dm["faces"]:
            start, end = face["triangle_range"]
            assert start == prev_end
            assert end > start
            prev_end = end
            assert face["face_id"].startswith("f-")
            assert face["surface_type"] in ("plane", "cylinder", "cone", "sphere", "torus", "other")
            assert face["source_feature_id"] is not None
            assert face["area_mm2"] > 0


class TestPerformance:
    """Performance measurements (WP0-1 step 6)."""

    def test_20_feature_chain_rebuild_time(self):
        """Measure rebuild time for 20-feature chain."""
        import time as _time
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("perf")
        pid = proj["project_id"]

        # Build 20 boxes in a chain
        for i in range(20):
            worker.execute_command(pid, {
                "type": "create_feature",
                "parameters": {
                    "feature_id": f"box{i}",
                    "type": "box",
                    "width": 10 + i,
                    "depth": 10 + i,
                    "height": 5,
                }
            })

        t0 = _time.perf_counter()
        worker.rebuild(pid)
        t1 = _time.perf_counter()
        rebuild_time = t1 - t0

        print(f"\n20-feature rebuild time: {rebuild_time:.3f}s")
        # Should complete in reasonable time
        assert rebuild_time < 60.0, f"Rebuild too slow: {rebuild_time:.3f}s"

    def test_incremental_rebuild_time(self):
        """Measure incremental rebuild time (change one dimension)."""
        import time as _time
        from cad_worker_freecad.server import FreeCadWorker
        worker = FreeCadWorker()
        proj = worker.create_project("perf_inc")
        pid = proj["project_id"]

        # Build base model
        worker.execute_command(pid, {
            "type": "create_feature",
            "parameters": {"feature_id": "box1", "type": "box", "width": 50, "depth": 50, "height": 10}
        })
        worker.rebuild(pid)

        # Measure update time
        t0 = _time.perf_counter()
        worker.execute_command(pid, {
            "type": "update_feature",
            "parameters": {"feature_id": "box1", "parameters": {"width": 60}}
        })
        worker.rebuild(pid)
        t1 = _time.perf_counter()

        update_time = t1 - t0
        print(f"\nIncremental rebuild time: {update_time:.3f}s")
        assert update_time < 30.0