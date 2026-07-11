"""Tests for CAD Worker API server endpoints.

Tests the health endpoint and auth security model.
The server uses X-Session-Token header for authentication.
"""
import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-Session-Token": SESSION_TOKEN}


class TestHealthEndpoint:
    def test_health_no_auth(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestAuthSecurity:
    def test_invalid_token_rejected(self, client):
        resp = client.post("/api/projects", json={"name": "Test"},
                          headers={"X-Session-Token": "wrong-token"})
        assert resp.status_code == 401

    def test_missing_token_rejected(self, client):
        resp = client.post("/api/projects", json={"name": "Test"})
        assert resp.status_code == 401


class TestCreateProject:
    def test_create_project_with_auth(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert data["manifest"]["name"] == "Test"


class TestPreviewToken:
    """preview.glb 的 query token 走預簽流程（WebView GLTFLoader 無法帶自訂 header）。

    WP-H2 契約：URL 中只接受 /api/presign 發出的短時效預簽 token；
    靜態 SESSION_TOKEN 放在 URL 一律 401（test_wp_h2_security 也驗證此點）。
    """

    def test_preview_with_valid_query_token(self, client, auth_headers):
        # 先建立專案
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        # 取得預簽 token 後用 query 帶入——認證必須通過（404=檔案未生成，非認證失敗）
        presigned = client.post("/api/presign", headers=auth_headers).json()["presigned_token"]
        resp = client.get(f"/api/projects/{pid}/preview.glb?token={presigned}")
        assert resp.status_code in (200, 404)

    def test_preview_with_static_session_token_in_url_rejected(self, client, auth_headers):
        """靜態 SESSION_TOKEN 不得放 URL——必須 401（token 不寫入 log/URL）。"""
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        resp = client.get(f"/api/projects/{pid}/preview.glb?token={SESSION_TOKEN}")
        assert resp.status_code == 401

    def test_preview_with_invalid_query_token(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        resp = client.get(f"/api/projects/{pid}/preview.glb?token=wrong-token")
        assert resp.status_code == 401

    def test_preview_with_valid_header_token(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        resp = client.get(f"/api/projects/{pid}/preview.glb", headers=auth_headers)
        assert resp.status_code != 403

    def test_preview_without_any_token(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        resp = client.get(f"/api/projects/{pid}/preview.glb")
        assert resp.status_code == 401


class TestApplyPlanTransaction:
    """apply_plan 端點：staging + rollback 交易。"""

    def _create_project(self, client, auth_headers, name="TestPlan"):
        resp = client.post("/api/projects", json={"name": name}, headers=auth_headers)
        return resp.json()["project_id"]

    def test_apply_plan_success(self, client, auth_headers):
        """正常的 plan 應該 commit 所有特徵。"""
        pid = self._create_project(client, auth_headers)
        commands = [
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "rect sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "pad1",
                    "type": "pad",
                    "name": "extrude",
                    "parameters": {"length": 5},
                    "input": "sk1",
                    "references": ["sk1"],
                },
            },
        ]
        resp = client.post(
            f"/api/projects/{pid}/apply_plan",
            json={"commands": commands, "plan_label": "test plan"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["applied_count"] == 2

        # 驗證特徵已 commit 到實際 graph
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert "sk1" in feat_ids
        assert "pad1" in feat_ids

    def test_apply_plan_rollback_on_bad_command(self, client, auth_headers):
        """命令格式錯誤時應回滾——原 graph 不受影響。"""
        pid = self._create_project(client, auth_headers)
        commands = [
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "good_sk",
                    "type": "sketch",
                    "name": "ok sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            {
                "action": "create_feature",
                "feature": None,  # 故意錯誤
            },
        ]
        resp = client.post(
            f"/api/projects/{pid}/apply_plan",
            json={"commands": commands, "plan_label": "bad plan"},
            headers=auth_headers,
        )
        assert resp.status_code == 500
        data = resp.json()
        assert data["status"] == "error"

        # 驗證原 graph 未被修改——good_sk 不應存在
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert "good_sk" not in feat_ids  # 回滾了

    def test_apply_plan_rollback_on_rebuild_failure(self, client, auth_headers):
        """重建失敗時應回滾。"""
        pid = self._create_project(client, auth_headers)
        commands = [
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "rect sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "pad1",
                    "type": "pad",
                    "name": "extrude",
                    "parameters": {"length": 5},
                    "input": "sk1",
                    "references": ["sk1"],
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "bad_fillet",
                    "type": "fillet",
                    "name": "huge fillet",
                    "parameters": {"radius": 999, "edge_selector": "all"},
                    "input": "pad1",
                    "references": ["pad1"],
                },
            },
        ]
        resp = client.post(
            f"/api/projects/{pid}/apply_plan",
            json={"commands": commands, "plan_label": "will fail rebuild"},
            headers=auth_headers,
        )
        data = resp.json()
        # 重建失敗——回滾
        assert data["status"] == "error"

        # 確認 graph 未被修改
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert "sk1" not in feat_ids  # 完全回滾

    def test_apply_plan_one_undo_step(self, client, auth_headers):
        """apply_plan 應只產生一個 revision——一次 Undo 回到 plan 前的狀態。"""
        pid = self._create_project(client, auth_headers)
        commands = [
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "rect sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "pad1",
                    "type": "pad",
                    "name": "extrude",
                    "parameters": {"length": 5},
                    "input": "sk1",
                    "references": ["sk1"],
                },
            },
        ]
        # 套用 plan
        client.post(
            f"/api/projects/{pid}/apply_plan",
            json={"commands": commands, "plan_label": "test plan"},
            headers=auth_headers,
        )

        # 檢查 revision 數量——應為 1
        rev_resp = client.get(f"/api/projects/{pid}/revisions", headers=auth_headers)
        rev_data = rev_resp.json()
        assert len(rev_data["revisions"]) == 1

        # Undo 一次應回到 plan 前的空狀態
        undo_resp = client.post(f"/api/projects/{pid}/undo", headers=auth_headers)
        assert undo_resp.status_code == 200

        # 確認 graph 已空
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert len(feat_ids) == 0

    def test_apply_plan_step3_failure_no_history(self, client, auth_headers):
        """TX-001: 4 步 plan 第 3 步（重建）失敗 → graph 不變且不產生 history event。"""
        pid = self._create_project(client, auth_headers)
        rev_before = len(
            client.get(f"/api/projects/{pid}/revisions", headers=auth_headers).json()["revisions"]
        )

        commands = [
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "rect sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "p1",
                    "type": "pad",
                    "name": "pad",
                    "parameters": {"length": 5},
                    "input": "sk1",
                    "references": ["sk1"],
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "f1",
                    "type": "fillet",
                    "name": "bad fillet",
                    "parameters": {"radius": 999, "edge_selector": "all"},
                    "input": "p1",
                    "references": ["p1"],
                },
            },
            {
                "action": "create_feature",
                "feature": {
                    "feature_id": "h1",
                    "type": "hole",
                    "name": "hole",
                    "parameters": {"diameter": 3, "through_all": True},
                    "input": "f1",
                    "references": ["f1"],
                },
            },
        ]
        resp = client.post(
            f"/api/projects/{pid}/apply_plan",
            json={"commands": commands, "plan_label": "4-step, fails at step 3"},
            headers=auth_headers,
        )
        assert resp.json()["status"] == "error"

        # graph 完全不變——一個特徵都沒進
        proj_data = client.get(f"/api/projects/{pid}", headers=auth_headers).json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert len(feat_ids) == 0

        # 重點：失敗的 plan 不得產生 history event
        rev_after = len(
            client.get(f"/api/projects/{pid}/revisions", headers=auth_headers).json()["revisions"]
        )
        assert rev_after == rev_before


class TestResetProject:
    """reset_project 端點：原子性清除所有特徵。"""

    def _create_project_with_features(self, client, auth_headers):
        """建立專案並加入兩個特徵。"""
        resp = client.post("/api/projects", json={"name": "ResetTest"}, headers=auth_headers)
        pid = resp.json()["project_id"]
        for feat_id in ["sk1", "pad1"]:
            client.post(
                f"/api/projects/{pid}/commands",
                json={
                    "action": "create_feature",
                    "feature": {
                        "feature_id": feat_id,
                        "type": "sketch" if feat_id == "sk1" else "pad",
                        "name": feat_id,
                        "parameters": {} if feat_id == "sk1" else {"length": 5},
                        "input": "sk1" if feat_id == "pad1" else None,
                        "references": ["sk1"] if feat_id == "pad1" else [],
                        "sketch_entities": [
                            {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]},
                        ] if feat_id == "sk1" else [],
                        "plane": {"base": "XY", "offset": 0} if feat_id == "sk1" else {},
                    },
                },
                headers=auth_headers,
            )
        return pid

    def test_reset_clears_all_features(self, client, auth_headers):
        """reset_project 應清除所有特徵。"""
        pid = self._create_project_with_features(client, auth_headers)
        resp = client.post(f"/api/projects/{pid}/reset", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["feature_count"] == 0

        # 確認 graph 為空
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert len(feat_ids) == 0

    def test_reset_creates_one_undo_step(self, client, auth_headers):
        """reset 應產生一個 revision——一次 Undo 回到清除前。"""
        pid = self._create_project_with_features(client, auth_headers)
        # 兩個 create_feature 產生 revision 1, 2
        client.post(f"/api/projects/{pid}/reset", headers=auth_headers)
        # reset 產生 revision 3

        rev_resp = client.get(f"/api/projects/{pid}/revisions", headers=auth_headers)
        rev_data = rev_resp.json()
        assert len(rev_data["revisions"]) == 3  # 2 creates + 1 reset

        # Undo 一次應回到 reset 前（有特徵的狀態）
        client.post(f"/api/projects/{pid}/undo", headers=auth_headers)
        proj_resp = client.get(f"/api/projects/{pid}", headers=auth_headers)
        proj_data = proj_resp.json()
        feat_ids = [f["feature_id"] for f in proj_data["features"]["features"]]
        assert len(feat_ids) == 2  # 回到 reset 前的兩個特徵