"""Tests for FeatureGraph topological sort and dependency tracking."""
import pytest
from cad_worker.feature_graph import (
    FeatureGraph,
    Feature,
    FeatureType,
    FeatureSource,
    RebuildStatus,
)


def _make_feature(fid, name, ftype, references=None, input=None):
    return Feature(
        feature_id=fid,
        name=name,
        type=FeatureType(ftype),
        references=references or [],
        input=input,
    )


class TestTopologicalSort:
    def test_empty_graph(self):
        fg = FeatureGraph()
        assert fg.topological_sort() == []

    def test_single_feature(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        assert fg.topological_sort() == ["base"]

    def test_chained_dependencies_via_references(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        fg.add_feature(_make_feature("pocket", "Pocket", "pocket", references=["pad"]))
        order = fg.topological_sort()
        assert order.index("base") < order.index("pad") < order.index("pocket")

    def test_chained_dependencies_via_input(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", input="base"))
        order = fg.topological_sort()
        assert order.index("base") < order.index("pad")

    def test_circular_dependency_raises(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("a", "A", "sketch", references=["b"]))
        fg.add_feature(_make_feature("b", "B", "pad", references=["a"]))
        with pytest.raises(ValueError, match="循環依賴"):
            fg.topological_sort()


class TestDeleteFeature:
    def test_delete_leaf_returns_empty(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        downstream = fg.delete_feature("pad")
        assert downstream == []
        assert fg.get_feature("pad") is None

    def test_delete_with_dependents_returns_downstream(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        downstream = fg.delete_feature("base")
        assert "pad" in downstream
        assert fg.get_feature("base") is not None

    def test_delete_recursive_removes_all(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        fg.add_feature(_make_feature("fillet", "Fillet", "fillet", references=["pad"]))
        deleted = fg.delete_feature_recursive("base")
        assert "base" in deleted
        assert "pad" in deleted
        assert "fillet" in deleted
        assert fg.get_feature("base") is None


class TestUpdateFeature:
    def test_update_marks_downstream_pending(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        fg.get_feature("pad").rebuild_status = RebuildStatus.SUCCESS
        fg.update_feature("base", {"width": 60.0})
        assert fg.get_feature("base").rebuild_status == RebuildStatus.PENDING
        assert fg.get_feature("pad").rebuild_status == RebuildStatus.PENDING

    def test_update_nonexistent_raises(self):
        fg = FeatureGraph()
        with pytest.raises(ValueError, match="不存在"):
            fg.update_feature("nope", {"x": 1})


class TestSketchEntities:
    def test_update_sketch_entities_round_trip(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("sk1", "Sketch1", "sketch"))
        entities = [
            {"type": "rectangle", "x": 0, "y": 0, "width": 40, "height": 20},
            {"type": "circle", "cx": 10, "cy": 10, "radius": 5},
        ]
        fg.update_feature("sk1", sketch_entities=entities)
        feat = fg.get_feature("sk1")
        assert feat.sketch_entities == entities
        # to_dict / from_dict round-trip
        d = fg.to_dict()
        fg2 = FeatureGraph.from_dict(d)
        assert fg2.get_feature("sk1").sketch_entities == entities

    def test_update_sketch_entities_full_replace_not_merge(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("sk1", "Sketch1", "sketch"))
        old = [{"type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10}]
        fg.update_feature("sk1", sketch_entities=old)
        assert fg.get_feature("sk1").sketch_entities == old
        new = [{"type": "circle", "cx": 0, "cy": 0, "radius": 3}]
        fg.update_feature("sk1", sketch_entities=new)
        assert fg.get_feature("sk1").sketch_entities == new
        assert old not in fg.get_feature("sk1").sketch_entities

    def test_update_sketch_entities_none_does_not_clear(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("sk1", "Sketch1", "sketch"))
        entities = [{"type": "circle", "cx": 0, "cy": 0, "radius": 5}]
        fg.update_feature("sk1", sketch_entities=entities)
        # Passing None should NOT wipe existing entities
        fg.update_feature("sk1", parameters={"foo": 1})
        assert fg.get_feature("sk1").sketch_entities == entities

    def test_update_sketch_entities_marks_downstream_pending(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("sk1", "Sketch1", "sketch"))
        fg.add_feature(_make_feature("pad1", "Pad1", "pad", references=["sk1"]))
        fg.get_feature("pad1").rebuild_status = RebuildStatus.SUCCESS
        fg.update_feature("sk1", sketch_entities=[{"type": "rectangle"}])
        assert fg.get_feature("sk1").rebuild_status == RebuildStatus.PENDING
        assert fg.get_feature("pad1").rebuild_status == RebuildStatus.PENDING


class TestSerialization:
    def test_round_trip(self):
        fg = FeatureGraph()
        fg.add_feature(_make_feature("base", "Base", "sketch"))
        fg.add_feature(_make_feature("pad", "Pad", "pad", references=["base"]))
        d = fg.to_dict()
        fg2 = FeatureGraph.from_dict(d)
        assert fg2.get_feature("base") is not None
        assert fg2.get_feature("pad") is not None
        assert fg2.topological_sort() == ["base", "pad"]