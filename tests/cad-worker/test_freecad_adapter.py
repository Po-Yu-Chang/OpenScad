"""FreeCAD Adapter integration tests.

Validates FreeCAD engine rebuild with bbox/volume/mass checks
(per WP-H4 rules, not face/edge counts -- different engines have different topology subdivisions).
"""

import os
import sys
import math
import pytest

# Set FreeCAD path
_FREECAD_DIR = os.environ.get("FREECAD_DIR", "")
if not _FREECAD_DIR:
    _FREECAD_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "FreeCAD", "FreeCAD_1.1.1-Windows-x86_64-py311",
    )
    os.environ["FREECAD_DIR"] = _FREECAD_DIR

if os.path.isdir(_FREECAD_DIR):
    for _p in [os.path.join(_FREECAD_DIR, "bin"), os.path.join(_FREECAD_DIR, "lib")]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

# Try importing FreeCAD
try:
    import FreeCAD
    import Part
    FREECAD_AVAILABLE = True
except ImportError:
    FREECAD_AVAILABLE = False

# Import Adapter
_cad_worker_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cad-worker")
if _cad_worker_path not in sys.path:
    sys.path.insert(0, _cad_worker_path)

from cad_worker.adapters.freecad_adapter import (
    FreeCADAdapter,
    FreeCADShapeWrapper,
    FreeCADFaceProxy,
    FreeCADEdgeProxy,
    FreeCADVectorProxy,
    BuildResult,
    TopologyTrace,
    FREECAD_AVAILABLE as ADAPTER_AVAILABLE,
)
from cad_worker.feature_graph import FeatureGraph, Feature, FeatureType


# -- Fixtures --

@pytest.fixture
def adapter():
    if not FREECAD_AVAILABLE:
        pytest.skip("FreeCAD not available")
    return FreeCADAdapter()


def _make_rect_sketch(fid, w=20, h=15, base="XY"):
    return Feature(
        feature_id=fid,
        name=fid,
        type=FeatureType.SKETCH,
        plane={"base": base, "offset": 0},
        sketch_entities=[
            {"entity_type": "rectangle", "parameters": {"width": w, "height": h, "center_x": 0, "center_y": 0}},
        ],
    )


def _make_circle_sketch(fid, r=5, base="XY"):
    return Feature(
        feature_id=fid,
        name=fid,
        type=FeatureType.SKETCH,
        plane={"base": base, "offset": 0},
        sketch_entities=[
            {"entity_type": "circle", "parameters": {"radius": r, "center_x": 0, "center_y": 0}},
        ],
    )


# -- Wrapper tests --

class TestFreeCADVectorProxy:
    def test_vector_xyz(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        v = FreeCAD.Vector(1.5, 2.5, 3.5)
        proxy = FreeCADVectorProxy(v)
        assert proxy.X == 1.5
        assert proxy.Y == 2.5
        assert proxy.Z == 3.5

    def test_vector_round(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        v = FreeCAD.Vector(1.123456, 2.123456, 3.123456)
        proxy = FreeCADVectorProxy(v)
        r = proxy.round(3)
        assert r == [1.123, 2.123, 3.123]


class TestFreeCADShapeWrapper:
    def test_box_wrapper_faces_edges(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        faces = wrapper.faces()
        edges = wrapper.edges()
        assert len(faces) == 6
        assert len(edges) == 12

    def test_box_wrapper_bbox(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 20, 30)
        wrapper = FreeCADShapeWrapper(box)
        bb = wrapper.BoundBox
        assert bb.XLength == 10
        assert bb.YLength == 20
        assert bb.ZLength == 30

    def test_face_proxy_geom_type(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        face = wrapper.faces()[0]
        assert face.geom_type == "PLANE"

    def test_face_proxy_area(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        face = wrapper.faces()[0]
        assert abs(face.area - 100.0) < 0.01

    def test_face_proxy_tessellate(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        face = wrapper.faces()[0]
        verts, tris = face.tessellate(0.1)
        assert len(verts) >= 4
        assert len(tris) >= 2

    def test_face_proxy_center(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        face = wrapper.faces()[0]
        c = face.center()
        assert isinstance(c, FreeCADVectorProxy)
        assert c.X is not None
        assert c.Y is not None
        assert c.Z is not None

    def test_edge_proxy_length(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        edge = wrapper.edges()[0]
        assert edge.length > 0
        assert abs(edge.length - 10.0) < 0.01

    def test_edge_proxy_positions(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        box = Part.makeBox(10, 10, 10)
        wrapper = FreeCADShapeWrapper(box)
        edge = wrapper.edges()[0]
        pts = edge.positions([0.0, 0.5, 1.0])
        assert len(pts) == 3
        assert isinstance(pts[0], FreeCADVectorProxy)

    def test_cylinder_face_geom_type(self):
        if not FREECAD_AVAILABLE:
            pytest.skip("FreeCAD not available")
        cyl = Part.makeCylinder(5, 10, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1))
        wrapper = FreeCADShapeWrapper(cyl)
        faces = wrapper.faces()
        types = {f.geom_type for f in faces}
        assert "CYLINDER" in types
        assert "PLANE" in types


# -- Adapter modeling tests --

class TestFreeCADAdapterSketch:
    def test_rectangle_sketch(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bb = result.part.BoundBox
        assert abs(bb.XLength - 20) < 0.01
        assert abs(bb.YLength - 15) < 0.01

    def test_circle_sketch(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_circle_sketch("s1", 5))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bb = result.part.BoundBox
        assert abs(bb.XLength - 10) < 0.01
        assert abs(bb.YLength - 10) < 0.01

    def test_empty_graph(self, adapter):
        graph = FeatureGraph()
        result = adapter.build_with_trace(graph)
        assert result.part is None


class TestFreeCADAdapterPad:
    def test_pad_box(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bb = result.part.BoundBox
        assert abs(bb.XLength - 20) < 0.01
        assert abs(bb.YLength - 15) < 0.01
        assert abs(bb.ZLength - 10) < 0.01

    def test_pad_cylinder(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_circle_sketch("s1", 5))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 8},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bb = result.part.BoundBox
        assert abs(bb.XLength - 10) < 0.01
        assert abs(bb.ZLength - 8) < 0.01

    def test_pad_volume(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert abs(vol - 3000.0) < 1.0


class TestFreeCADAdapterPocket:
    def test_pocket_through_all(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="pk1", name="pk1", type=FeatureType.POCKET, input="p1",
            parameters={"diameter": 5, "through_all": True, "positions": [[0, 0]]},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 4000.0
        assert vol > 3700.0

    def test_pocket_positions(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 30, 30))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="pk1", name="pk1", type=FeatureType.POCKET, input="p1",
            parameters={"diameter": 4, "depth": 5, "positions": [[5, 5], [-5, -5]]},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 9000.0
        assert vol > 8800.0


class TestFreeCADAdapterHole:
    def test_hole_through_all(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="h1", name="h1", type=FeatureType.HOLE, input="p1",
            parameters={"diameter": 6, "through_all": True},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 4000.0
        assert vol > 3600.0

    def test_hole_multiple_positions(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 40, 40))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="h1", name="h1", type=FeatureType.HOLE, input="p1",
            parameters={"diameter": 5, "depth": 5, "positions": [[10, 10], [-10, 10], [10, -10], [-10, -10]]},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 16000.0
        assert vol > 14000.0


class TestFreeCADAdapterFillet:
    def test_fillet_all(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="f1", name="f1", type=FeatureType.FILLET, input="p1",
            parameters={"radius": 2, "edge_selector": "all"},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 4000.0
        assert vol > 3500.0


class TestFreeCADAdapterChamfer:
    def test_chamfer_all(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="c1", name="c1", type=FeatureType.CHAMFER, input="p1",
            parameters={"distance": 1, "edge_selector": "all"},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 4000.0
        assert vol > 3800.0

    def test_chamfer_edge_selector_actually_selects(self, adapter):
        """WP1-0R2 修復核心案例：edge_selector 原本 all/else 兩分支完全相同、
        參數被忽略是死碼。"top"（4 條邊）跟 "all"（12 條邊）切掉的體積必須
        不同，才能證明 edge_selector 真的有作用。"""
        def _chamfered_volume(selector):
            graph = FeatureGraph()
            graph.add_feature(_make_rect_sketch("s1", 20, 20))
            graph.add_feature(Feature(
                feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
            ))
            graph.add_feature(Feature(
                feature_id="c1", name="c1", type=FeatureType.CHAMFER, input="p1",
                parameters={"distance": 1, "edge_selector": selector},
            ))
            return adapter.build_with_trace(graph).part._freecad_shape.Volume

        vol_top = _chamfered_volume("top")
        vol_all = _chamfered_volume("all")
        assert vol_top != vol_all
        assert vol_top > vol_all  # 只切 4 條邊，留下的體積應比切 12 條邊多


class TestFreeCADAdapterShell:
    def test_shell_reduces_volume_matching_build123d(self, adapter):
        """WP1-0R2 新增：shell 目前雙引擎都只是均勻內縮（無開口面選擇器，
        見 adapter 內文件字串的已知限制說明），數值上要跟 build123d 一致：
        32×45×7.5 盒子、thickness=2 → (28)(41)(3.5)=4018mm³。"""
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 32, 45))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 7.5},
        ))
        graph.add_feature(Feature(
            feature_id="sh1", name="sh1", type=FeatureType.SHELL, input="p1",
            parameters={"thickness": 2.0},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        assert abs(result.part.volume - 4018.0) < 0.5

    def test_shell_too_thick_raises(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 10, 10))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        graph.add_feature(Feature(
            feature_id="sh1", name="sh1", type=FeatureType.SHELL, input="p1",
            parameters={"thickness": 20.0},
        ))
        with pytest.raises(ValueError):
            adapter.build_with_trace(graph)


class TestFreeCADAdapterRevolve:
    def test_revolve_circle_360(self, adapter):
        """WP1-0R2 修復：旋轉軸改由草圖 plane 推導（XY→X 軸），輪廓必須
        偏離該軸才是合法幾何——圓心用 center_y=10（偏離 X 軸），不能像舊
        測試那樣用 center_x=10/center_y=0（正好落在推導出的 X 軸上，兩個
        引擎對這種退化資料都會失敗，不是「已知限制」，是資料本身無效）。
        修復後應能算出正確體積（環面 volume = 2π²Rr²）。
        """
        import math
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="s1", name="s1", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 3, "center_x": 0, "center_y": 10}},
            ],
        ))
        graph.add_feature(Feature(
            feature_id="r1", name="r1", type=FeatureType.REVOLVE, input="s1",
            parameters={"angle": 360},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        expected_volume = 2 * math.pi ** 2 * 10 * 3 ** 2
        assert abs(result.part.volume - expected_volume) < 1.0

    def test_revolve_degenerate_profile_raises(self, adapter):
        """輪廓中心恰好落在推導出的旋轉軸上——必須 raise，不得靜默回傳
        零體積「成功」（WP1-0R2 修復核心案例）。"""
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="s1", name="s1", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[
                {"entity_type": "circle", "parameters": {"radius": 3, "center_x": 10, "center_y": 0}},
            ],
        ))
        graph.add_feature(Feature(
            feature_id="r1", name="r1", type=FeatureType.REVOLVE, input="s1",
            parameters={"angle": 360},
        ))
        with pytest.raises(ValueError):
            adapter.build_with_trace(graph)


class TestFreeCADAdapterMirror:
    def test_mirror_across_xz_doubles_volume_no_overlap(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="s1", name="s1", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[
                {"entity_type": "rectangle", "parameters": {"width": 10, "height": 10, "center_x": 0, "center_y": 10}},
            ],
        ))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        graph.add_feature(Feature(
            feature_id="m1", name="m1", type=FeatureType.MIRROR, input="p1",
        ))
        result = adapter.build_with_trace(graph)
        assert abs(result.part.volume - 1000.0) < 0.5


class TestFreeCADAdapterBoolean:
    def _two_boxes(self):
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="s1", name="s1", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": 10, "height": 10, "center_x": 0, "center_y": 0}}],
        ))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10}))
        graph.add_feature(Feature(
            feature_id="s2", name="s2", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": 10, "height": 10, "center_x": 5, "center_y": 5}}],
        ))
        graph.add_feature(Feature(feature_id="p2", name="p2", type=FeatureType.PAD, input="s2", parameters={"length": 10}))
        return graph

    def test_boolean_union(self, adapter):
        graph = self._two_boxes()
        graph.add_feature(Feature(
            feature_id="u1", name="u1", type=FeatureType.BOOLEAN_UNION, references=["p1", "p2"],
        ))
        result = adapter.build_with_trace(graph)
        # 兩個 10x10x10 立方體重疊 5x5x10=250 → union = 1000+1000-250=1750
        assert abs(result.part.volume - 1750.0) < 0.5

    def test_boolean_difference(self, adapter):
        graph = self._two_boxes()
        graph.add_feature(Feature(
            feature_id="d1", name="d1", type=FeatureType.BOOLEAN_DIFFERENCE, references=["p1", "p2"],
        ))
        result = adapter.build_with_trace(graph)
        # p1(1000) 減去重疊 250 = 750
        assert abs(result.part.volume - 750.0) < 0.5

    def test_boolean_intersection(self, adapter):
        graph = self._two_boxes()
        graph.add_feature(Feature(
            feature_id="i1", name="i1", type=FeatureType.BOOLEAN_INTERSECTION, references=["p1", "p2"],
        ))
        result = adapter.build_with_trace(graph)
        assert abs(result.part.volume - 250.0) < 0.5


class TestFreeCADAdapterSweep:
    def test_sweep_circle_along_line(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="profile", name="profile", type=FeatureType.SKETCH,
            plane={"base": "YZ", "offset": 0},
            sketch_entities=[{"entity_type": "circle", "parameters": {"radius": 3, "center_x": 0, "center_y": 0}}],
        ))
        graph.add_feature(Feature(
            feature_id="path", name="path", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[{"entity_type": "line", "parameters": {"x1": 0, "y1": 0, "x2": 20, "y2": 0}}],
        ))
        graph.add_feature(Feature(
            feature_id="sw1", name="sw1", type=FeatureType.SWEEP, input="profile", references=["path"],
        ))
        result = adapter.build_with_trace(graph)
        expected_volume = math.pi * 3 ** 2 * 20
        assert abs(result.part.volume - expected_volume) < 5.0


class TestFreeCADAdapterLoft:
    def test_loft_between_two_circles(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="s1", name="s1", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[{"entity_type": "circle", "parameters": {"radius": 5, "center_x": 0, "center_y": 0}}],
        ))
        graph.add_feature(Feature(
            feature_id="s2", name="s2", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 20},
            sketch_entities=[{"entity_type": "circle", "parameters": {"radius": 3, "center_x": 0, "center_y": 0}}],
        ))
        graph.add_feature(Feature(
            feature_id="lo1", name="lo1", type=FeatureType.LOFT, input="s1", references=["s2"],
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        assert result.part.volume > 0


class TestFreeCADAdapterWP16Features:
    """WP1-6 六型：draft/rib/thin/variable_fillet/countersink/cosmetic_thread。"""

    def test_draft_is_noop_passthrough(self, adapter):
        """與 build123d adapter 對齊：目前簡化為不改變幾何。"""
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 10, 10))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5}))
        graph.add_feature(Feature(feature_id="d1", name="d1", type=FeatureType.DRAFT, input="p1", parameters={"angle_deg": 2}))
        result = adapter.build_with_trace(graph)
        assert abs(result.part.volume - 500.0) < 0.5

    def test_rib_symmetric_adds_volume(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5}))
        graph.add_feature(Feature(
            feature_id="rib_sketch", name="rib_sketch", type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 0},
            sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": 4, "height": 20, "center_x": 0, "center_y": 0}}],
        ))
        graph.add_feature(Feature(
            feature_id="rib1", name="rib1", type=FeatureType.RIB, input="p1",
            parameters={"thickness": 2, "direction": "symmetric", "sketch_id": "rib_sketch"},
        ))
        result = adapter.build_with_trace(graph)
        # base 2000 + rib 4x20x2(symmetric two halves of total thickness 2)=160 → > base
        assert result.part.volume > 2000.0

    def test_thin_extrudes_then_shells(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="th1", name="th1", type=FeatureType.THIN, input="s1",
            parameters={"length": 10, "thickness": 2},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        assert result.part.volume > 0
        assert result.part.volume < 20 * 20 * 10  # 薄殼後體積應小於實心拉伸

    def test_variable_fillet_uses_first_radius(self, adapter):
        """與 build123d adapter 對齊：目前簡化為單一半徑（取 radii[0]）。"""
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10}))
        graph.add_feature(Feature(
            feature_id="vf1", name="vf1", type=FeatureType.VARIABLE_FILLET, input="p1",
            parameters={"radii": [1, 3]},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        assert result.part.volume < 4000.0

    def test_countersink_removes_material(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10}))
        graph.add_feature(Feature(
            feature_id="cs1", name="cs1", type=FeatureType.COUNTERSINK, input="p1",
            parameters={"diameter": 3, "countersink_diameter": 6, "countersink_angle_deg": 90, "positions": [[0, 0]]},
        ))
        result = adapter.build_with_trace(graph)
        assert result.part.volume < 4000.0

    def test_cosmetic_thread_returns_none_keeps_upstream(self, adapter):
        """與 build123d adapter 對齊：不改變幾何，rebuild 沿用上一個特徵結果。"""
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10}))
        graph.add_feature(Feature(
            feature_id="ct1", name="ct1", type=FeatureType.COSMETIC_THREAD, input="p1",
            parameters={"diameter": 6, "pitch": 1, "positions": [[0, 0]]},
        ))
        result = adapter.build_with_trace(graph)
        assert abs(result.part.volume - 4000.0) < 0.5
        assert result.part.volume > 0


class TestFreeCADAdapterPattern:
    def test_pattern_linear_2(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 10, 10))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        graph.add_feature(Feature(
            feature_id="pat1", name="pat1", type=FeatureType.LINEAR_PATTERN, input="p1",
            parameters={"count": 2, "spacing": 20, "axis": "X"},
        ))
        result = adapter.build_with_trace(graph)
        bb = result.part.BoundBox
        assert bb.XLength > 25

    def test_pattern_circular_4(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 5, 5))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        graph.add_feature(Feature(
            feature_id="pat1", name="pat1", type=FeatureType.CIRCULAR_PATTERN, input="p1",
            parameters={"count": 4, "radius": 15},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol > 400.0
        assert vol < 600.0


class TestFreeCADAdapterTrace:
    def test_trace_has_face_records(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        assert result.trace is not None
        faces_created = result.trace.faces_created_by("p1")
        assert len(faces_created) > 0

    def test_trace_resolve_face_feature(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        faces = result.part.faces()
        found = any(result.trace.resolve_face_feature(f) for f in faces)
        assert found

    def test_trace_resolve_edge_feature(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 15))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        edges = result.part.edges()
        found = any(result.trace.resolve_edge_feature(e) for e in edges)
        assert found


class TestFreeCADAdapterMultiFeature:
    def test_box_with_hole_and_fillet(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 30, 30))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 15},
        ))
        graph.add_feature(Feature(
            feature_id="h1", name="h1", type=FeatureType.HOLE, input="p1",
            parameters={"diameter": 8, "through_all": True},
        ))
        graph.add_feature(Feature(
            feature_id="f1", name="f1", type=FeatureType.FILLET, input="h1",
            parameters={"radius": 1, "edge_selector": "all"},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 13500.0
        assert vol > 12000.0

    def test_two_pads_chained(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        graph.add_feature(Feature(
            feature_id="h1", name="h1", type=FeatureType.HOLE, input="p1",
            parameters={"diameter": 6, "depth": 5},
        ))
        result = adapter.build_with_trace(graph)
        shape = result.part._freecad_shape
        vol = shape.Volume
        assert vol < 4000.0
        assert vol > 3800.0


class TestFreeCADAdapterExportCompat:
    def test_display_map_from_freecad(self, adapter):
        from cad_worker.exporters import build_display_map
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        dm = build_display_map(result.part, result.trace)
        assert "faces" in dm
        assert "edges" in dm
        assert len(dm["faces"]) >= 6
        for f in dm["faces"]:
            assert f["surface_type"] == "plane"

    def test_step_export_from_freecad(self, adapter, tmp_path):
        from cad_worker.exporters import StepExporter
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        step_path = tmp_path / "test.step"
        StepExporter.export(result.part, step_path)
        assert step_path.exists()
        assert step_path.stat().st_size > 0

    def test_stl_export_from_freecad(self, adapter, tmp_path):
        from cad_worker.exporters import StlExporter
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 20))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 10},
        ))
        result = adapter.build_with_trace(graph)
        stl_path = tmp_path / "test.stl"
        StlExporter.export(result.part, stl_path)
        assert stl_path.exists()
        assert stl_path.stat().st_size > 0


class TestFreeCADAdapterPlanes:
    def test_pad_xz_plane(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 20, 10, base="XZ"))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        result = adapter.build_with_trace(graph)
        bb = result.part.BoundBox
        assert abs(bb.XLength - 20) < 0.01
        assert abs(bb.ZLength - 10) < 0.01
        assert abs(bb.YLength - 5) < 0.01

    def test_pad_yz_plane(self, adapter):
        graph = FeatureGraph()
        graph.add_feature(_make_rect_sketch("s1", 15, 10, base="YZ"))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        result = adapter.build_with_trace(graph)
        bb = result.part.BoundBox
        assert abs(bb.YLength - 15) < 0.01
        assert abs(bb.ZLength - 10) < 0.01
        assert abs(bb.XLength - 5) < 0.01