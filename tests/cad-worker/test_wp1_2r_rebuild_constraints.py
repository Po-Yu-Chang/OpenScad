"""WP1-2R 驗收——rebuild 不得再靜默忽略 constraints（鐵則 3 紅線修復）。

- build123d 引擎：沒有求解器，rebuild 前驗證目前座標是否已滿足約束；
  不符即 raise（不得沿用過期座標）。
- FreeCAD 引擎：rebuild 時真的重新求解；衝突約束 raise（不得使用未收斂座標）。
- 同時驗證 line/arc 圖元不再是死碼（build123d）、freecad sketch 補上 arc 分支。
"""
import os
import sys
import pytest

from cad_worker.adapters.build123d_adapter import Build123dAdapter, BUILD123D_AVAILABLE
from cad_worker.feature_graph import FeatureGraph, Feature, FeatureType

_FREECAD_DIR = os.environ.get("FREECAD_DIR", "")
if not _FREECAD_DIR:
    _FREECAD_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "FreeCAD", "FreeCAD_1.1.1-Windows-x86_64-py311",
    )
    os.environ.setdefault("FREECAD_DIR", _FREECAD_DIR)
if os.path.isdir(_FREECAD_DIR):
    for _p in [os.path.join(_FREECAD_DIR, "bin"), os.path.join(_FREECAD_DIR, "lib")]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

from cad_worker.adapters.freecad_adapter import FreeCADAdapter, FREECAD_AVAILABLE


pytestmark_b123d = pytest.mark.skipif(not BUILD123D_AVAILABLE, reason="build123d not installed")
pytestmark_fc = pytest.mark.skipif(not FREECAD_AVAILABLE, reason="FreeCAD not available")


def _line_sketch(fid, lines, constraints=None, base="XY"):
    return Feature(
        feature_id=fid, name=fid, type=FeatureType.SKETCH,
        plane={"base": base, "offset": 0},
        sketch_entities=lines,
        constraints=constraints or [],
    )


@pytestmark_b123d
class TestBuild123dRebuildValidatesConstraints:
    def test_satisfied_constraints_build_succeeds(self):
        """座標已滿足約束——rebuild 正常，line 圖元組成的封閉輪廓能實際拉伸成形
        （驗證 line 不再是死碼：舊碼完全不 add() 任何線段邊）。"""
        lines = [
            {"id": "e0", "type": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0},
            {"id": "e1", "type": "line", "x1": 20, "y1": 0, "x2": 20, "y2": 10},
            {"id": "e2", "type": "line", "x1": 20, "y1": 10, "x2": 0, "y2": 10},
            {"id": "e3", "type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 0},
        ]
        constraints = [
            {"id": "c1", "type": "horizontal", "targets": ["e0"]},
        ]
        graph = FeatureGraph()
        graph.add_feature(_line_sketch("s1", lines, constraints))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        adapter = Build123dAdapter()
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bbox = result.part.bounding_box()
        assert abs(bbox.size.X - 20) < 0.5
        assert abs(bbox.size.Y - 10) < 0.5
        assert abs(bbox.size.Z - 5) < 0.01

    def test_unsatisfied_constraints_rebuild_raises(self):
        """紅線修復核心案例：座標明顯違反 distance 約束——rebuild 必須 raise，
        不得靜默沿用不滿足約束的舊座標。"""
        lines = [
            {"id": "e0", "type": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0},
        ]
        constraints = [
            # 目前長度是 20，約束要求 60——嚴重不滿足
            {"id": "c1", "type": "distance", "targets": ["e0.start", "e0.end"], "value_mm": 60},
        ]
        graph = FeatureGraph()
        graph.add_feature(_line_sketch("s1", lines, constraints))
        adapter = Build123dAdapter()
        with pytest.raises(ValueError, match="不滿足約束|constraints"):
            adapter.build_with_trace(graph)

    def test_arc_edge_is_added_not_dead_code(self):
        """WP1-2R 修正前，arc 產生的邊從未 add()，等同死碼。用一個由 4 段
        arc 組成的完整圓（近似）驗證 arc 現在真的貢獻到面。"""
        arcs = [
            {"id": "a0", "type": "arc", "center_x": 0, "center_y": 0, "radius": 10, "start_angle": 0, "end_angle": 90},
            {"id": "a1", "type": "arc", "center_x": 0, "center_y": 0, "radius": 10, "start_angle": 90, "end_angle": 180},
            {"id": "a2", "type": "arc", "center_x": 0, "center_y": 0, "radius": 10, "start_angle": 180, "end_angle": 270},
            {"id": "a3", "type": "arc", "center_x": 0, "center_y": 0, "radius": 10, "start_angle": 270, "end_angle": 360},
        ]
        graph = FeatureGraph()
        graph.add_feature(_line_sketch("s1", arcs))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 3},
        ))
        adapter = Build123dAdapter()
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bbox = result.part.bounding_box()
        # 四段 90 度弧组成的圆，直径应约为 20mm
        assert abs(bbox.size.X - 20) < 1.0
        assert abs(bbox.size.Y - 20) < 1.0


@pytestmark_fc
class TestFreeCADRebuildSolvesConstraints:
    @staticmethod
    def _rect_lines(w=20, h=10):
        return [
            {"id": "e0", "type": "line", "x1": 0, "y1": 0, "x2": w, "y2": 0},
            {"id": "e1", "type": "line", "x1": w, "y1": 0, "x2": w, "y2": h},
            {"id": "e2", "type": "line", "x1": w, "y1": h, "x2": 0, "y2": h},
            {"id": "e3", "type": "line", "x1": 0, "y1": h, "x2": 0, "y2": 0},
        ]

    def test_constraints_move_geometry_to_solved_coordinates(self):
        """FreeCAD 引擎：rebuild 時真的重新求解——座標會被移動到滿足約束，
        而非直接沿用宣告時的（可能不滿足約束的）舊座標。四段線本身已拓樸
        閉合（端點兩兩相接），只是 e0 宣告長度（20）不滿足 distance 約束
        （60）——驗證 rebuild 後 bbox 反映求解後的座標。

        除了 distance 約束本身，還需要 coincident 把四個角釘住、
        horizontal/vertical 保持矩形形狀——否則求解器只會用最小範數移動
        e0 一段，導致四邊斷開（這是求解器忠實反映約束系統的正確行為，
        不是 bug：沒有 coincident 約束，系統本來就沒有理由維持角點連接）。
        """
        constraints = [
            {"id": "c1", "type": "distance", "targets": ["e0.start", "e0.end"], "value_mm": 60},
            {"id": "co1", "type": "coincident", "targets": ["e0.end", "e1.start"]},
            {"id": "co2", "type": "coincident", "targets": ["e1.end", "e2.start"]},
            {"id": "co3", "type": "coincident", "targets": ["e2.end", "e3.start"]},
            {"id": "co4", "type": "coincident", "targets": ["e3.end", "e0.start"]},
            {"id": "h0", "type": "horizontal", "targets": ["e0"]},
            {"id": "v1", "type": "vertical", "targets": ["e1"]},
            {"id": "h2", "type": "horizontal", "targets": ["e2"]},
            {"id": "v3", "type": "vertical", "targets": ["e3"]},
        ]
        graph = FeatureGraph()
        graph.add_feature(_line_sketch("s1", self._rect_lines(w=20, h=10), constraints))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        adapter = FreeCADAdapter()
        result = adapter.build_with_trace(graph)
        assert result.part is not None
        bb = result.part.BoundBox
        # e0 被拉到 60mm 長，X 方向 bbox 應反映求解後的座標，而非原本宣告的 20
        assert abs(bb.XLength - 60) < 1.0

    def test_conflicting_constraints_rebuild_raises(self):
        """衝突約束——rebuild 必須中止，不得使用未收斂座標建模（用拓樸已閉合
        的四段線矩形，只是 e0 加了兩個互斥的 distance 約束）。"""
        constraints = [
            {"id": "c1", "type": "distance", "targets": ["e0.start", "e0.end"], "value_mm": 60},
            {"id": "c2", "type": "distance", "targets": ["e0.start", "e0.end"], "value_mm": 80},
        ]
        graph = FeatureGraph()
        graph.add_feature(_line_sketch("s1", self._rect_lines(w=20, h=10), constraints))
        graph.add_feature(Feature(
            feature_id="p1", name="p1", type=FeatureType.PAD, input="s1", parameters={"length": 5},
        ))
        adapter = FreeCADAdapter()
        with pytest.raises(ValueError, match="衝突|conflict"):
            adapter.build_with_trace(graph)

    def test_arc_sketch_entity_produces_geometry(self):
        """WP1-2R 新增：freecad `_sketch_entity_to_edges` 先前完全沒有 arc 分支。"""
        adapter = FreeCADAdapter()
        edges = adapter._sketch_entity_to_edges(
            {"type": "arc", "center_x": 0, "center_y": 0, "radius": 5, "start_angle": 0, "end_angle": 90},
            "XY", 0,
        )
        assert len(edges) == 1
