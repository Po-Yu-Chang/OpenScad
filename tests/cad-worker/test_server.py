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
        assert resp.status_code == 403

    def test_missing_token_rejected(self, client):
        resp = client.post("/api/projects", json={"name": "Test"})
        assert resp.status_code == 403


class TestCreateProject:
    def test_create_project_with_auth(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "Test"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert data["manifest"]["name"] == "Test"