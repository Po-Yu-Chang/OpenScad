"""Tests for revision snapshots and undo/redo endpoints (Phase 1 A4)."""
import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def headers():
    return {"X-Session-Token": SESSION_TOKEN}


def _create_project_with_features(client, headers):
    resp = client.post("/api/projects", json={"name": "rev-test"}, headers=headers)
    pid = resp.json()["project_id"]
    client.post(f"/api/projects/{pid}/commands", headers=headers, json={
        "action": "create_feature",
        "feature": {"feature_id": "sk", "type": "sketch", "name": "S",
                    "sketch_entities": [{"entity_id": "r1", "entity_type": "rectangle",
                                         "parameters": {"width": 60, "height": 60}}]},
    })
    client.post(f"/api/projects/{pid}/commands", headers=headers, json={
        "action": "create_feature",
        "feature": {"feature_id": "pad", "type": "pad", "name": "P",
                    "input": "sk", "references": ["sk"], "parameters": {"length": 5}},
    })
    return pid


def _get_pad(client, headers, pid):
    data = client.get(f"/api/projects/{pid}", headers=headers).json()
    features = data["features"]
    # graph 格式：{schema_version, features: [...]}
    if isinstance(features, dict) and "features" in features:
        features = features["features"]
    if isinstance(features, list):
        return next(f for f in features if f["feature_id"] == "pad")
    return features["pad"]


class TestRevisionSnapshots:
    def test_commands_create_revisions(self, client, headers):
        pid = _create_project_with_features(client, headers)
        resp = client.get(f"/api/projects/{pid}/revisions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["revisions"]) == 2
        assert data["current"] == 2

    def test_update_with_standard_parts(self, client, headers):
        pid = _create_project_with_features(client, headers)
        resp = client.post(f"/api/projects/{pid}/commands", headers=headers, json={
            "action": "update_feature",
            "target_feature_id": "pad",
            "standard_parts": {"fastener": {"standard": "M5", "fit": "normal_clearance"}},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"
        pad = _get_pad(client, headers, pid)
        assert pad["standard_parts"]["fastener"]["standard"] == "M5"


class TestUndoRedo:
    def test_undo_reverts_update(self, client, headers):
        pid = _create_project_with_features(client, headers)
        client.post(f"/api/projects/{pid}/commands", headers=headers, json={
            "action": "update_feature", "target_feature_id": "pad",
            "parameters": {"length": 8},
        })
        assert _get_pad(client, headers, pid)["parameters"]["length"] == 8

        resp = client.post(f"/api/projects/{pid}/undo", headers=headers)
        assert resp.status_code == 200
        assert _get_pad(client, headers, pid)["parameters"]["length"] == 5

    def test_redo_reapplies_update(self, client, headers):
        pid = _create_project_with_features(client, headers)
        client.post(f"/api/projects/{pid}/commands", headers=headers, json={
            "action": "update_feature", "target_feature_id": "pad",
            "parameters": {"length": 8},
        })
        client.post(f"/api/projects/{pid}/undo", headers=headers)
        resp = client.post(f"/api/projects/{pid}/redo", headers=headers)
        assert resp.status_code == 200
        assert _get_pad(client, headers, pid)["parameters"]["length"] == 8

    def test_new_command_after_undo_discards_redo(self, client, headers):
        pid = _create_project_with_features(client, headers)
        client.post(f"/api/projects/{pid}/commands", headers=headers, json={
            "action": "update_feature", "target_feature_id": "pad",
            "parameters": {"length": 8},
        })
        client.post(f"/api/projects/{pid}/undo", headers=headers)
        client.post(f"/api/projects/{pid}/commands", headers=headers, json={
            "action": "update_feature", "target_feature_id": "pad",
            "parameters": {"length": 10},
        })
        resp = client.post(f"/api/projects/{pid}/redo", headers=headers)
        assert resp.status_code == 400  # redo 分支已捨棄

    def test_undo_past_beginning_rejected(self, client, headers):
        pid = _create_project_with_features(client, headers)
        client.post(f"/api/projects/{pid}/undo", headers=headers)
        resp = client.post(f"/api/projects/{pid}/undo", headers=headers)
        assert resp.status_code == 400


class TestProjectList:
    def test_list_projects_includes_created(self, client, headers):
        pid = _create_project_with_features(client, headers)
        resp = client.get("/api/projects", headers=headers)
        assert resp.status_code == 200
        ids = [p["project_id"] for p in resp.json()["projects"]]
        assert pid in ids
