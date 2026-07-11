"""Tests for schema v1→v2 migration and new Document Model v2 features.

Covers:
- Migration from v1 to v2 (3 example projects)
- suppress_feature / unsuppress_feature
- reorder_feature (dependency violation rejected)
- set_rollback (mid-point rebuild)
- Feature state machine (active/suppressed/failed/orphan)
- Body / order fields
- Round-trip v2 serialization
"""
import json
import os
import pytest

from cad_worker.feature_graph import (
    FeatureGraph,
    Feature,
    FeatureType,
    FeatureState,
    RebuildStatus,
    FeatureSource,
    ReorderDependencyViolationError,
)


EXAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples"
)


def _load_example(name: str) -> dict:
    path = os.path.join(EXAMPLES_DIR, name, "features.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_feature(fid, name, ftype, references=None, input=None, body="body1"):
    return Feature(
        feature_id=fid,
        name=name,
        type=FeatureType(ftype),
        references=references or [],
        input=input,
        body=body,
    )


# ── Migration tests ──

class TestSchemaMigration:
    """v1 → v2 migration: 單 body、order=陣列序、state=active。"""

    def test_migrate_nema17_mount(self):
        """範例專案 1：NEMA17 mount。"""
        data = _load_example("nema17-mount")
        assert data["schema_version"] == "1.0"
        graph = FeatureGraph.from_dict(data)
        # All features should have v2 fields
        for feature in graph.features.values():
            assert feature.body == "body1"
            assert feature.order is not None
            assert feature.state == FeatureState.ACTIVE
        # Order should match array order
        ordered = graph.get_ordered_features()
        assert len(ordered) > 0
        for i, f in enumerate(ordered):
            assert f.order == i

    def test_migrate_needle_box(self):
        """範例專案 2：Needle box。"""
        data = _load_example("needle-box-5x10")
        assert data["schema_version"] == "1.0"
        graph = FeatureGraph.from_dict(data)
        for feature in graph.features.values():
            assert feature.body == "body1"
            assert feature.order is not None
            assert feature.state == FeatureState.ACTIVE

    def test_migrate_esp32cam_enclosure(self):
        """範例專案 3：ESP32-CAM enclosure。"""
        data = _load_example("esp32cam-enclosure")
        assert data["schema_version"] == "1.0"
        graph = FeatureGraph.from_dict(data)
        for feature in graph.features.values():
            assert feature.body == "body1"
            assert feature.order is not None
            assert feature.state == FeatureState.ACTIVE

    def test_v2_round_trip_preserves_v2_fields(self):
        """v2 data round-trips without losing body/order/state."""
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "Sketch1", "sketch"))
        graph.add_feature(_make_feature("pad1", "Pad1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        d = graph.to_dict()
        assert d["schema_version"] == "2.0"
        assert "bodies" in d
        assert "rollback_position" in d
        graph2 = FeatureGraph.from_dict(d)
        assert graph2.get_feature("sk1").body == "body1"
        assert graph2.get_feature("sk1").state == FeatureState.ACTIVE
        assert graph2.get_feature("pad1").order is not None

    def test_v1_dict_format_migrates(self):
        """Direct v1 dict (old key-value format) also migrates."""
        v1_data = {
            "schema_version": "1.0",
            "sk1": {
                "feature_id": "sk1",
                "type": "sketch",
                "name": "S",
                "sketch_entities": [],
                "parameters": {},
            },
            "pad1": {
                "feature_id": "pad1",
                "type": "pad",
                "name": "P",
                "input": "sk1",
                "references": ["sk1"],
                "parameters": {"length": 5},
            },
        }
        graph = FeatureGraph.from_dict(v1_data)
        assert graph.get_feature("sk1") is not None
        assert graph.get_feature("pad1").body == "body1"
        assert graph.get_feature("sk1").state == FeatureState.ACTIVE


# ── Suppress / Unsuppress tests ──

class TestSuppressFeature:
    def test_suppress_marks_feature_suppressed(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph.add_feature(_make_feature("pad1", "P", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        graph.suppress_feature("sk1")
        assert graph.get_feature("sk1").state == FeatureState.SUPPRESSED

    def test_suppress_marks_downstream_orphan(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph.add_feature(_make_feature("pad1", "P", "pad", references=["sk1"], input="sk1"))
        graph.add_feature(_make_feature("hole1", "H", "hole", references=["pad1"], input="pad1"))
        graph._ensure_order()
        orphaned = graph.suppress_feature("sk1")
        assert "pad1" in orphaned
        assert "hole1" in orphaned
        assert graph.get_feature("pad1").state == FeatureState.ORPHAN
        assert graph.get_feature("hole1").state == FeatureState.ORPHAN

    def test_suppress_does_not_affect_unrelated_features(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph.add_feature(_make_feature("pad1", "P", "pad", references=["sk1"], input="sk1"))
        graph.add_feature(_make_feature("sk2", "S2", "sketch"))
        graph._ensure_order()
        orphaned = graph.suppress_feature("sk1")
        assert "sk2" not in orphaned
        assert graph.get_feature("sk2").state == FeatureState.ACTIVE

    def test_unsuppress_restores_downstream(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph.add_feature(_make_feature("pad1", "P", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        graph.suppress_feature("sk1")
        assert graph.get_feature("pad1").state == FeatureState.ORPHAN
        restored = graph.unsuppress_feature("sk1")
        assert graph.get_feature("sk1").state == FeatureState.ACTIVE
        assert "pad1" in restored
        assert graph.get_feature("pad1").state == FeatureState.ACTIVE

    def test_suppress_nonexistent_raises(self):
        graph = FeatureGraph()
        with pytest.raises(ValueError, match="不存在"):
            graph.suppress_feature("nope")

    def test_suppress_marks_pending_for_rebuild(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph.add_feature(_make_feature("pad1", "P", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        graph.get_feature("sk1").rebuild_status = RebuildStatus.SUCCESS
        graph.get_feature("pad1").rebuild_status = RebuildStatus.SUCCESS
        graph.suppress_feature("sk1")
        assert graph.get_feature("sk1").rebuild_status == RebuildStatus.PENDING
        assert graph.get_feature("pad1").rebuild_status == RebuildStatus.PENDING


# ── Reorder tests ──

class TestReorderFeature:
    def test_reorder_move_later(self):
        """合法的 move-later：不跨過下游依賴；跨過則違規。"""
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("sk2", "S2", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        # sk1=0, sk2=1, pad1=2
        # 把 sk1 移到 1（仍在其下游 pad1 之前）——合法
        graph.reorder_feature("sk1", 1)
        assert graph.get_feature("sk1").order == 1
        # sk2 shift 到 0
        assert graph.get_feature("sk2").order == 0
        # 把 sk1 移到 2（跨過依賴它的 pad1）——違規
        with pytest.raises(ReorderDependencyViolationError):
            graph.reorder_feature("sk1", 2)

    def test_reorder_move_earlier(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph.add_feature(_make_feature("fillet1", "F1", "fillet", references=["pad1"], input="pad1"))
        graph.add_feature(_make_feature("hole1", "H1", "hole", references=["pad1"], input="pad1"))
        graph._ensure_order()
        # sk1=0, pad1=1, fillet1=2, hole1=3
        # Move hole1 to position 2 (before fillet1, both depend on pad1)
        graph.reorder_feature("hole1", 2)
        assert graph.get_feature("hole1").order == 2
        assert graph.get_feature("fillet1").order == 3

    def test_reorder_dependency_violation_raises(self):
        """reorder 違反依賴——pad 的 order 不能 ≤ sk1 的 order。"""
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        # sk1=0, pad1=1
        # Try to move pad1 to order=0 (before sk1) — violates dependency
        with pytest.raises(ReorderDependencyViolationError):
            graph.reorder_feature("pad1", 0)

    def test_reorder_same_position_ok(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        # sk1=0, pad1=1 — move pad1 to same position
        graph.reorder_feature("pad1", 1)
        assert graph.get_feature("pad1").order == 1

    def test_reorder_nonexistent_raises(self):
        graph = FeatureGraph()
        with pytest.raises(ValueError, match="不存在"):
            graph.reorder_feature("nope", 0)

    def test_reorder_marks_pending(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph.add_feature(_make_feature("hole1", "H1", "hole", references=["pad1"], input="pad1"))
        graph._ensure_order()
        for f in graph.features.values():
            f.rebuild_status = RebuildStatus.SUCCESS
        # 合法 reorder（原位）——被移動者與其下游標 pending，上游不動
        graph.reorder_feature("pad1", 1)
        assert graph.get_feature("sk1").rebuild_status == RebuildStatus.SUCCESS
        assert graph.get_feature("pad1").rebuild_status == RebuildStatus.PENDING
        assert graph.get_feature("hole1").rebuild_status == RebuildStatus.PENDING


# ── Rollback tests ──

class TestSetRollback:
    def test_set_rollback_to_midpoint(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph.add_feature(_make_feature("hole1", "H1", "hole", references=["pad1"], input="pad1"))
        graph._ensure_order()
        # sk1=0, pad1=1, hole1=2
        graph.set_rollback(1)
        rebuild_ids = graph.get_rebuild_features()
        assert "sk1" in rebuild_ids
        assert "pad1" in rebuild_ids
        assert "hole1" not in rebuild_ids  # Beyond rollback position

    def test_set_rollback_null_rebuilds_all(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        graph.set_rollback(None)
        rebuild_ids = graph.get_rebuild_features()
        assert len(rebuild_ids) == 2

    def test_set_rollback_negative_raises(self):
        graph = FeatureGraph()
        with pytest.raises(ValueError, match="負數"):
            graph.set_rollback(-1)

    def test_set_rollback_marks_all_pending(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        for f in graph.features.values():
            f.rebuild_status = RebuildStatus.SUCCESS
        graph.set_rollback(0)
        assert graph.get_feature("sk1").rebuild_status == RebuildStatus.PENDING
        assert graph.get_feature("pad1").rebuild_status == RebuildStatus.PENDING

    def test_rollback_excludes_suppressed(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1"))
        graph._ensure_order()
        graph.suppress_feature("pad1")
        graph.set_rollback(None)
        rebuild_ids = graph.get_rebuild_features()
        assert "sk1" in rebuild_ids
        assert "pad1" not in rebuild_ids  # Suppressed


# ── Feature state machine tests ──

class TestFeatureState:
    def test_default_state_is_active(self):
        f = Feature(feature_id="x", name="X", type=FeatureType.SKETCH)
        assert f.state == FeatureState.ACTIVE

    def test_state_serializes_to_string(self):
        f = Feature(feature_id="x", name="X", type=FeatureType.SKETCH, state=FeatureState.SUPPRESSED)
        d = f.to_dict()
        assert d["state"] == "suppressed"

    def test_state_deserializes_from_string(self):
        d = {
            "feature_id": "x",
            "type": "sketch",
            "name": "X",
            "state": "orphan",
        }
        f = Feature.from_dict(d)
        assert f.state == FeatureState.ORPHAN


# ── Body / Order tests ──

class TestBodyOrder:
    def test_default_body_is_body1(self):
        f = Feature(feature_id="x", name="X", type=FeatureType.SKETCH)
        assert f.body == "body1"

    def test_multi_body_features(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch", body="body1"))
        graph.add_feature(_make_feature("sk2", "S2", "sketch", body="body2"))
        graph._ensure_order()
        body1_features = graph.get_ordered_features(body="body1")
        body2_features = graph.get_ordered_features(body="body2")
        assert len(body1_features) == 1
        assert len(body2_features) == 1

    def test_order_per_body_independent(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch", body="body1"))
        graph.add_feature(_make_feature("pad1", "P1", "pad", references=["sk1"], input="sk1", body="body1"))
        graph.add_feature(_make_feature("sk2", "S2", "sketch", body="body2"))
        graph._ensure_order()
        # body1: sk1=0, pad1=1
        # body2: sk2=0 (independent numbering)
        assert graph.get_feature("sk1").order == 0
        assert graph.get_feature("pad1").order == 1
        assert graph.get_feature("sk2").order == 0

    def test_body_serialization(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S1", "sketch"))
        d = graph.to_dict()
        assert "bodies" in d
        assert d["bodies"][0]["id"] == "body1"

    def test_ordered_features_sorted_by_order(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("c", "C", "sketch"))
        graph.add_feature(_make_feature("a", "A", "sketch"))
        graph.add_feature(_make_feature("b", "B", "sketch"))
        graph._ensure_order()
        ordered = graph.get_ordered_features()
        ids = [f.feature_id for f in ordered]
        assert ids == ["c", "a", "b"]  # Insertion order


# ── v2 document model fields ──

class TestDocumentModelFields:
    def test_bodies_default(self):
        graph = FeatureGraph()
        assert len(graph.bodies) == 1
        assert graph.bodies[0]["id"] == "body1"

    def test_rollback_position_default_null(self):
        graph = FeatureGraph()
        assert graph.rollback_position is None

    def test_global_variables_default_empty(self):
        graph = FeatureGraph()
        assert graph.global_variables == []

    def test_configurations_default_empty(self):
        graph = FeatureGraph()
        assert graph.configurations == []

    def test_custom_properties_default_empty(self):
        graph = FeatureGraph()
        assert graph.custom_properties == {}

    def test_reference_geometry_default_empty(self):
        graph = FeatureGraph()
        assert graph.reference_geometry == []

    def test_bodies_in_to_dict(self):
        graph = FeatureGraph()
        graph.bodies = [{"id": "body1", "name": "Main", "material": "AL6061", "appearance": None}]
        d = graph.to_dict()
        assert d["bodies"][0]["material"] == "AL6061"


# ── Clone / save / load ──

class TestCloneV2:
    def test_clone_preserves_v2_fields(self):
        graph = FeatureGraph()
        graph.add_feature(_make_feature("sk1", "S", "sketch"))
        graph._ensure_order()
        graph.set_rollback(0)
        graph.bodies = [{"id": "body1", "name": "Main", "material": "AL", "appearance": None}]
        cloned = graph.clone()
        assert cloned.rollback_position == 0
        assert len(cloned.bodies) == 1
        assert cloned.bodies[0]["material"] == "AL"
        assert cloned.get_feature("sk1").order is not None