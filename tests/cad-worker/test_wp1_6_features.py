"""WP1-6 特徵補全（第二批）golden tests.

驗收條件（Master Plan §WP1-6）：
每特徵 ≥2 golden tests（正常＋邊界）；LLM 一句話生成案例各 1 個實測。

特徵清單：
- Draft（拔模）
- Rib（輪廓拉伸＋fuse）
- Thin feature（薄件拉伸）
- Variable fillet（per-edge 半徑）
- Countersink（沉頭孔）
- Cosmetic thread（裝飾牙線）
"""
import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN

client = TestClient(app)
headers = {"X-Session-Token": SESSION_TOKEN}


def create_project(name="wp1-6-test"):
    resp = client.post("/api/projects", json={"name": name, "description": "WP1-6 test"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def apply_cmd(pid, action, **kwargs):
    cmd = {"schema_version": "1.0", "action": action, **kwargs}
    resp = client.post(f"/api/projects/{pid}/commands", json=cmd, headers=headers)
    return resp


def rebuild(pid):
    return client.post(f"/api/projects/{pid}/rebuild", headers=headers)


def make_sketch(fid, name, width, height):
    return {"feature_id": fid, "type": "sketch", "name": name, "parameters": {},
            "sketch_entities": [{"type": "rectangle", "width": width, "height": height, "center": [0, 0]}],
            "plane": {"base": "XY", "offset": 0}}


def make_pad(fid, name, input_id, length):
    return {"feature_id": fid, "type": "pad", "name": name,
            "parameters": {"length": length}, "input": input_id, "references": [input_id]}


def get_features(pid):
    resp = client.get(f"/api/projects/{pid}", headers=headers)
    return {f["feature_id"]: f for f in resp.json()["features"]["features"]}


def create_base_part(pid, width=40, height=40, length=10):
    """Create sketch + pad base for testing."""
    apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", width, height))
    apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", length))
    rebuild(pid)


# ── Draft（拔模）──

class TestDraft:
    def test_draft_normal(self):
        """正常拔模——5 度拔模角。"""
        pid = create_project("draft-normal")
        create_base_part(pid, 40, 40, 10)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "d1", "type": "draft", "name": "draft 5deg",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"angle_deg": 5, "face_selector": "all"}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"

    def test_draft_boundary_zero_angle(self):
        """邊界——0 度拔模角（無變化）。"""
        pid = create_project("draft-zero")
        create_base_part(pid, 20, 20, 5)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "d1", "type": "draft", "name": "draft 0deg",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"angle_deg": 0}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"


# ── Rib（加強肋）──

class TestRib:
    def test_rib_normal(self):
        """正常加強肋——5mm 厚度。"""
        pid = create_project("rib-normal")
        create_base_part(pid, 40, 40, 10)
        # Rib needs a sketch profile
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "rs1", "type": "sketch", "name": "rib sketch",
                           "parameters": {},
                           "sketch_entities": [{"type": "rectangle", "width": 30, "height": 5, "center": [0, 0]}],
                           "plane": {"base": "XZ", "offset": 0}})
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "r1", "type": "rib", "name": "rib 5mm",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"thickness": 5, "direction": "symmetric", "sketch_id": "rs1"}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"

    def test_rib_boundary_thin(self):
        """邊界——1mm 極薄肋。"""
        pid = create_project("rib-thin")
        create_base_part(pid, 30, 30, 8)
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "rs1", "type": "sketch", "name": "rib sketch",
                           "parameters": {},
                           "sketch_entities": [{"type": "rectangle", "width": 20, "height": 3, "center": [0, 0]}],
                           "plane": {"base": "XZ", "offset": 0}})
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "r1", "type": "rib", "name": "rib 1mm",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"thickness": 1, "sketch_id": "rs1"}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"


# ── Thin feature（薄件拉伸）──

class TestThin:
    def test_thin_normal(self):
        """正常薄件——10mm 長度 2mm 厚度。"""
        pid = create_project("thin-normal")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "thin sketch", 30, 30))
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "t1", "type": "thin", "name": "thin 2mm",
                                  "input": "s1", "references": ["s1"],
                                  "parameters": {"length": 10, "thickness": 2}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"

    def test_thin_boundary_minimal(self):
        """邊界——最小厚度 0.5mm。"""
        pid = create_project("thin-minimal")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "thin sketch", 20, 20))
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "t1", "type": "thin", "name": "thin 0.5mm",
                                  "input": "s1", "references": ["s1"],
                                  "parameters": {"length": 5, "thickness": 0.5}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"


# ── Variable fillet（變化圓角）──

class TestVariableFillet:
    def test_variable_fillet_normal(self):
        """正常變化圓角——r1=2mm r2=5mm。"""
        pid = create_project("vf-normal")
        create_base_part(pid, 30, 30, 10)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "vf1", "type": "variable_fillet", "name": "var fillet",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"radii": [2, 5], "edge_selector": "all"}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"

    def test_variable_fillet_boundary_equal_radii(self):
        """邊界——所有半徑相同（等於固定圓角）。"""
        pid = create_project("vf-equal")
        create_base_part(pid, 25, 25, 8)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "vf1", "type": "variable_fillet", "name": "equal fillet",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"radii": [3, 3], "edge_selector": "all"}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"


# ── Countersink（沉頭孔）──

class TestCountersink:
    def test_countersink_normal(self):
        """正常沉頭孔——5mm 主孔 + 10mm 沉頭。"""
        pid = create_project("cs-normal")
        create_base_part(pid, 40, 40, 10)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "cs1", "type": "countersink", "name": "countersink M5",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"diameter": 5, "countersink_diameter": 10,
                                                 "countersink_angle_deg": 90, "positions": [[0, 0]]}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"

    def test_countersink_boundary_small(self):
        """邊界——最小沉頭孔 2mm。"""
        pid = create_project("cs-small")
        create_base_part(pid, 20, 20, 5)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "cs1", "type": "countersink", "name": "cs small",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"diameter": 2, "countersink_diameter": 4,
                                                 "countersink_angle_deg": 82, "positions": [[0, 0]]}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"


# ── Cosmetic thread（裝飾牙線）──

class TestCosmeticThread:
    def test_cosmetic_thread_normal(self):
        """正常裝飾牙線——M6 螺紋。"""
        pid = create_project("ct-normal")
        create_base_part(pid, 30, 30, 10)
        # First create a hole for the thread
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "h1", "type": "hole", "name": "hole M6",
                           "input": "p1", "references": ["p1"],
                           "parameters": {"diameter": 6, "through_all": True}})
        rebuild(pid)
        resp = apply_cmd(pid, "create_feature",
                         feature={"feature_id": "ct1", "type": "cosmetic_thread", "name": "thread M6",
                                  "input": "p1", "references": ["p1"],
                                  "parameters": {"diameter": 6, "pitch": 1, "depth": 10, "positions": [[0, 0]]}})
        assert resp.status_code == 200, resp.text
        r = rebuild(pid)
        assert r.json()["status"] == "success"
        # Verify feature exists
        feats = get_features(pid)
        assert "ct1" in feats

    def test_cosmetic_thread_boundary_no_geometry_change(self):
        """邊界——裝飾牙線不改變幾何（體積與無牙線時相同）。"""
        pid = create_project("ct-nochange")
        create_base_part(pid, 25, 25, 8)
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "h1", "type": "hole", "name": "hole 4mm",
                           "input": "p1", "references": ["p1"],
                           "parameters": {"diameter": 4, "through_all": True}})
        rebuild(pid)

        # Get volume after hole (before cosmetic thread)
        r1 = rebuild(pid)
        vol_before = r1.json()["mass_properties"]["volume_mm3"]

        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "ct1", "type": "cosmetic_thread", "name": "thread M4",
                           "input": "p1", "references": ["p1"],
                           "parameters": {"diameter": 4, "pitch": 0.7, "depth": 8, "positions": [[0, 0]]}})
        rebuild(pid)
        r2 = rebuild(pid)
        vol_after = r2.json()["mass_properties"]["volume_mm3"]

        # Cosmetic thread should not change geometry
        assert abs(vol_before - vol_after) < 0.01, f"裝飾牙線不應改變體積: before={vol_before} after={vol_after}"


# ── Schema/validator tests ──

class TestWP1_6SchemaValidation:
    """驗證 schema 和 validator 正確接受新特徵類型。"""

    def test_all_new_types_in_capability(self):
        """capability endpoint 應列出所有新特徵類型。"""
        resp = client.get("/api/capability", headers=headers)
        assert resp.status_code == 200
        cap = resp.json()
        catalog_types = [f["type"] for f in cap["feature_catalog"]]
        for t in ["draft", "rib", "thin", "variable_fillet", "countersink", "cosmetic_thread"]:
            assert t in catalog_types, f"{t} 不在 feature_catalog 中"

    def test_rib_removed_from_unsupported(self):
        """rib 和 draft 應已從 unsupported_features 移除。"""
        resp = client.get("/api/capability", headers=headers)
        cap = resp.json()
        unsupported = cap["unsupported_features"]
        assert "rib" not in unsupported, "rib 應已支援"
        assert "draft" not in unsupported, "draft 應已支援"

    def test_validator_accepts_new_types(self):
        """command validator 應接受新特徵類型的 create_feature。"""
        pid = create_project("validator-test")
        for ftype in ["draft", "rib", "thin", "variable_fillet", "countersink", "cosmetic_thread"]:
            resp = apply_cmd(pid, "create_feature",
                             feature={"feature_id": f"t_{ftype}", "type": ftype, "name": f"test {ftype}",
                                      "input": "p1", "references": ["p1"],
                                      "parameters": {"thickness": 2, "length": 5, "diameter": 5,
                                                     "radii": [2, 3], "countersink_diameter": 10,
                                                     "countersink_angle_deg": 90, "pitch": 1,
                                                     "depth": 5, "positions": [[0, 0]]}})
            # Should not get a validation error about unknown type
            assert resp.status_code == 200, f"{ftype} 被拒: {resp.text}"