"""G-002 / G-003：圓角保護中心孔、圓柱外緣不被當孔誤排除。

對應 ChatGPT §12.6 Definition of Done 的核心幾何回歸：
- 圓角 selector 以 topology provenance 排除 hole 建立的邊，孔不受影響、半徑不被靜默降級。
- CIRCLE 邊 != 一定是孔：圓柱外緣（圓形邊）仍可被圓角選中，只有 hole 建立的邊被排除。

直接用 Build123dAdapter.build_with_trace（非 HTTP），才能取得 TopologyTrace 斷言邊歸屬。
"""

from cad_worker.adapters.build123d_adapter import Build123dAdapter
from cad_worker.feature_graph import Feature, FeatureGraph, FeatureType


def _feat(fid: str, ftype: FeatureType, name: str, **kw) -> Feature:
    return Feature(feature_id=fid, type=ftype, name=name, **kw)


def _rebuild(features):
    graph = FeatureGraph()
    for f in features:
        graph.add_feature(f)
    result = Build123dAdapter().build_with_trace(graph)
    return graph, result


def test_outer_fillet_r2_preserves_center_hole():
    """G-002：10×5×5 方塊 + 中心 Ø3 貫穿孔 + 外邊 R2 圓角（排除孔邊）。"""
    features = [
        _feat("sketch1", FeatureType.SKETCH, "base rect",
              sketch_entities=[{"type": "rectangle", "width": 10, "height": 5}]),
        _feat("pad1", FeatureType.PAD, "pad", input="sketch1",
              parameters={"length": 5}),
        _feat("hole1", FeatureType.HOLE, "center hole", input="pad1",
              parameters={"diameter": 3, "through_all": True}),
        _feat("fillet1", FeatureType.FILLET, "outer fillet", input="hole1",
              parameters={
                  "radius": 2.0,
                  "edges": {
                      "include": [{"kind": "all_edges"}],
                      "exclude": [{"kind": "created_by", "feature_id": "hole1"}],
                  },
              }),
    ]
    graph, result = _rebuild(features)
    assert result.part is not None

    hole_edges = result.trace.created_by("hole1")
    fillet_edges = result.trace.selected_by("fillet1")
    assert hole_edges, "hole 應記錄至少一條建立的邊"
    assert fillet_edges, "fillet 應選到至少一條邊"
    # 核心：圓角選到的邊與孔建立的邊完全不相交
    assert hole_edges.isdisjoint(fillet_edges), "圓角選邊不得含孔建立的邊"

    # 外形尺寸不變
    bb = result.part.bounding_box()
    assert abs(bb.size.X - 10) < 0.1
    assert abs(bb.size.Y - 5) < 0.1
    assert abs(bb.size.Z - 5) < 0.1

    # 孔仍在：體積 < 完整方塊（10*5*5=250）且 > 0
    assert 0 < result.part.volume < 250

    # 半徑未被靜默降級
    assert graph.get_feature("fillet1").parameters["radius"] == 2.0


def test_cylinder_outer_edge_not_treated_as_hole():
    """G-003：圓柱（Ø10）+ 中心 Ø3 貫穿孔，對外緣圓角。

    圓柱外緣是 CIRCLE 邊，仍應可被圓角選中；只有 hole 建立的邊被排除。
    直接打臉「GeomType.CIRCLE == 孔」的誤判。
    """
    features = [
        _feat("sketch1", FeatureType.SKETCH, "base circle",
              sketch_entities=[{"type": "circle", "radius": 5}]),
        _feat("pad1", FeatureType.PAD, "cylinder", input="sketch1",
              parameters={"length": 5}),
        _feat("hole1", FeatureType.HOLE, "center hole", input="pad1",
              parameters={"diameter": 3, "through_all": True}),
        _feat("fillet1", FeatureType.FILLET, "outer edge fillet", input="hole1",
              parameters={
                  "radius": 1.0,
                  "edges": {
                      "include": [{"kind": "all_edges"}],
                      "exclude": [{"kind": "created_by", "feature_id": "hole1"}],
                  },
              }),
    ]
    graph, result = _rebuild(features)
    assert result.part is not None

    hole_edges = result.trace.created_by("hole1")
    fillet_edges = result.trace.selected_by("fillet1")
    # 圓柱外緣（CIRCLE 邊）可被選中
    assert fillet_edges, "圓柱外緣（含 CIRCLE 邊）應可被圓角選中"
    # 孔建立的邊不得被選中
    assert hole_edges.isdisjoint(fillet_edges), "孔建立的邊不得被圓角選中"
