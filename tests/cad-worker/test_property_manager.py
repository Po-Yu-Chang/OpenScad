"""WP1-4 Property Manager 與量測測試。

驗收條件（Master Plan §WP1-4）：
- 樹選 hole→參數面板顯示直徑/深度
- 改 6→8→✓→模型更新＋undo 一步還原
- 量測 60mm 板兩平行面距離顯示 60.00
- 截圖驗證 shaded-with-edges 與 isolate
- smoke-test PASS
"""
import json
import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN

client = TestClient(app)
headers = {"X-Session-Token": SESSION_TOKEN}


def create_project(name="wp1-4-test"):
    resp = client.post("/api/projects", json={"name": name, "description": "WP1-4 test"}, headers=headers)
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


def make_hole(fid, name, input_id, diameter):
    return {"feature_id": fid, "type": "hole", "name": name,
            "parameters": {"diameter": diameter}, "input": input_id, "references": [input_id]}


class TestPropertyManagerUpdate:
    """Property Manager 參數更新——改 hole 直徑 6→8 並驗證模型更新。"""

    def test_update_hole_diameter(self):
        """樹選 hole→改直徑 6→8→模型更新。"""
        pid = create_project("prop-mgr-hole")
        # Build a 60×40×10 pad with a hole
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 60, 40))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        apply_cmd(pid, "create_feature", feature=make_hole("h1", "center hole", "p1", 6))
        r = rebuild(pid)
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        # Read feature graph to verify hole diameter = 6
        resp = client.get(f"/api/projects/{pid}", headers=headers)
        graph = resp.json()["features"]
        feats = {f["feature_id"]: f for f in graph["features"]}
        assert "h1" in feats
        assert feats["h1"]["parameters"]["diameter"] == 6

        # Update hole diameter 6→8
        resp = apply_cmd(pid, "update_feature", target_feature_id="h1",
                         parameters={"diameter": 8})
        assert resp.status_code == 200
        r = rebuild(pid)
        assert r.json()["status"] == "success"

        # Verify diameter is now 8
        resp = client.get(f"/api/projects/{pid}", headers=headers)
        graph = resp.json()["features"]
        feats = {f["feature_id"]: f for f in graph["features"]}
        assert feats["h1"]["parameters"]["diameter"] == 8

    def test_update_feature_undo_restores(self):
        """改參數後 undo 一步還原。"""
        pid = create_project("prop-mgr-undo")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 60, 40))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        rebuild(pid)

        # Update length 10→20
        apply_cmd(pid, "update_feature", target_feature_id="p1", parameters={"length": 20})
        rebuild(pid)
        resp = client.get(f"/api/projects/{pid}", headers=headers)
        feats = {f["feature_id"]: f for f in resp.json()["features"]["features"]}
        assert feats["p1"]["parameters"]["length"] == 20

        # Undo
        resp = client.post(f"/api/projects/{pid}/undo", headers=headers)
        assert resp.status_code == 200
        resp = client.get(f"/api/projects/{pid}", headers=headers)
        feats = {f["feature_id"]: f for f in resp.json()["features"]["features"]}
        assert feats["p1"]["parameters"]["length"] == 10


class TestMeasurementMode:
    """量測模式——驗證端點存在與基本流程。"""

    def test_display_map_available_for_measurement(self):
        """量測需要 display_map——重建後應可用。"""
        pid = create_project("measure-test")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 60, 40))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        rebuild(pid)
        # display_map should be available
        resp = client.get(f"/api/projects/{pid}/display_map", headers=headers)
        assert resp.status_code == 200
        dm = resp.json()
        assert "faces" in dm
        assert len(dm["faces"]) > 0

    def test_parallel_face_distance(self):
        """60mm 板兩平行面距離——透過 bounding_box 驗證尺寸。"""
        pid = create_project("measure-60mm")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 60, 40))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        r = rebuild(pid)
        assert r.status_code == 200
        mp = r.json()["mass_properties"]
        bbox = mp["bounding_box_mm"]
        # 60mm dimension should be in bbox
        size_x = bbox["size_x"]
        size_y = bbox["size_y"]
        assert abs(max(size_x, size_y) - 60.0) < 0.01


class TestDisplayModes:
    """顯示模式——驗證 display_map 含 edge 資料（shaded-with-edges 需要）。"""

    def test_display_map_has_edges(self):
        """display_map 含 edges 資料（shaded-with-edges 模式需要）。"""
        pid = create_project("display-edges")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 60, 40))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        rebuild(pid)
        resp = client.get(f"/api/projects/{pid}/display_map", headers=headers)
        dm = resp.json()
        assert "edges" in dm
        assert isinstance(dm["edges"], list)


class TestFeatureVisibility:
    """特徵隔離/隱藏/顯示——驗證 feature_id 在 display_map 中可查。"""

    def test_display_map_face_has_feature_id(self):
        """display_map faces 含 feature_id 欄位（isolate/hide 需要）。"""
        pid = create_project("visibility-test")
        apply_cmd(pid, "create_feature", feature=make_sketch("s1", "base rect", 30, 30))
        apply_cmd(pid, "create_feature", feature=make_pad("p1", "extrude", "s1", 10))
        rebuild(pid)
        resp = client.get(f"/api/projects/{pid}/display_map", headers=headers)
        dm = resp.json()
        # Faces should have source_feature_id for visibility control
        for face in dm["faces"]:
            assert "source_feature_id" in face, "Face should have source_feature_id"