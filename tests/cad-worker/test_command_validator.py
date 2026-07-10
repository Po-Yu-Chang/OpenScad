"""Tests for Python CommandValidator — server-side command contract validation."""
import pytest
from cad_worker.validators.command_validator import CommandValidator


class TestCommandValidator:
    def test_empty_action_returns_error(self):
        errors = CommandValidator.validate({})
        assert len(errors) == 1
        assert "action" in errors[0]

    def test_unknown_action_returns_error(self):
        errors = CommandValidator.validate({"action": "do_weird_thing"})
        assert any("未知的 action" in e for e in errors)

    def test_create_feature_null_feature_returns_error(self):
        errors = CommandValidator.validate({"action": "create_feature", "feature": None})
        assert any("feature 欄位" in e for e in errors)

    def test_create_feature_empty_id_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "", "type": "sketch", "name": "S"},
        })
        assert any("feature_id" in e for e in errors)

    def test_sketch_without_entities_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "sk1", "type": "sketch", "name": "S",
                        "sketch_entities": []},
        })
        assert any("sketch_entities" in e for e in errors)

    def test_pad_without_input_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "p1", "type": "pad", "name": "P",
                        "parameters": {"length": 5}},
        })
        assert any("input" in e for e in errors)

    def test_fillet_without_radius_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "f1", "type": "fillet", "name": "F",
                        "input": "pad1", "parameters": {}},
        })
        assert any("radius" in e for e in errors)

    def test_fillet_negative_radius_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "f1", "type": "fillet", "name": "F",
                        "input": "pad1", "parameters": {"radius": -2}},
        })
        assert any("radius 必須 > 0" in e for e in errors)

    def test_hole_without_diameter_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "h1", "type": "hole", "name": "H",
                        "input": "pad1", "parameters": {}},
        })
        assert any("diameter" in e for e in errors)

    def test_pocket_without_references_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "p1", "type": "pocket", "name": "P",
                        "input": "pad1", "references": [], "parameters": {"depth": 3}},
        })
        assert any("references" in e for e in errors)

    def test_shell_without_thickness_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {"feature_id": "s1", "type": "shell", "name": "S",
                        "input": "pad1", "parameters": {}},
        })
        assert any("thickness" in e for e in errors)

    def test_valid_sketch_passes(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {
                "feature_id": "sk1", "type": "sketch", "name": "S",
                "sketch_entities": [{"type": "rectangle", "width": 10, "height": 10}],
                "plane": {"base": "XY", "offset": 0},
            },
        })
        assert errors == []

    def test_valid_pad_passes(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {
                "feature_id": "pad1", "type": "pad", "name": "P",
                "input": "sk1", "references": ["sk1"],
                "parameters": {"length": 5},
            },
        })
        assert errors == []

    def test_valid_fillet_passes(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {
                "feature_id": "f1", "type": "fillet", "name": "F",
                "input": "pad1", "references": ["pad1"],
                "parameters": {"radius": 2, "edge_selector": "all"},
            },
        })
        assert errors == []

    def test_delete_without_target_returns_error(self):
        errors = CommandValidator.validate({"action": "delete_feature"})
        assert any("target_feature_id" in e for e in errors)

    def test_update_without_target_returns_error(self):
        errors = CommandValidator.validate({
            "action": "update_feature", "parameters": {"x": 1},
        })
        assert any("target_feature_id" in e for e in errors)

    def test_sketch_bad_plane_base_returns_error(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {
                "feature_id": "sk1", "type": "sketch", "name": "S",
                "sketch_entities": [{"type": "rectangle", "width": 10, "height": 10}],
                "plane": {"base": "DIAGONAL", "offset": 0},
            },
        })
        assert any("plane.base" in e for e in errors)

    def test_fillet_radius_mm_suffix_passes(self):
        errors = CommandValidator.validate({
            "action": "create_feature",
            "feature": {
                "feature_id": "f1", "type": "fillet", "name": "F",
                "input": "pad1", "references": ["pad1"],
                "parameters": {"radius_mm": 2},
            },
        })
        assert errors == []