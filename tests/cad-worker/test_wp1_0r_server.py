"""WP1-0R: Server engine hardening tests.

Tests for:
- Health endpoint returns engine + engine_requested fields
- OPENCAD_ENGINE=freecad with FreeCAD unavailable → 503 (no silent fallback)
- Concurrent rebuilds are serialized (landmine #17)
"""

from __future__ import annotations

import asyncio
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from cad_worker.server import app, SESSION_TOKEN
    with TestClient(app) as c:
        c._token = SESSION_TOKEN  # type: ignore[attr-defined]
        yield c


@pytest.fixture()
def project(client):
    """建立測試專案 with sketch + pad."""
    resp = client.post(
        "/api/projects",
        json={"name": "engine-test", "description": "", "units": "mm"},
        headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
    )
    assert resp.status_code == 200
    pid = resp.json()["project_id"]

    for cmd in [
        {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "s1", "type": "sketch", "name": "S", "parameters": {}, "sketch_entities": [{"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}], "plane": {"base": "XY", "offset": 0}}},
        {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "p1", "type": "pad", "name": "Pad", "parameters": {"length": 10}, "input": "s1", "references": ["s1"]}},
    ]:
        r = client.post(f"/api/projects/{pid}/commands", json=cmd, headers={"X-Session-Token": client._token})  # type: ignore[attr-defined]
        assert r.status_code == 200, f"Command failed: {r.text}"

    return pid


class TestHealthEngineFields:
    """Health endpoint should report engine + engine_requested."""

    def test_health_has_engine_fields(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "engine" in data
        assert "engine_requested" in data

    def test_health_engine_default_build123d(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        # Default engine is build123d
        assert data["engine_requested"] == "build123d"
        assert data["engine"] == "build123d"


class TestNoSilentFallback:
    """OPENCAD_ENGINE=freecad but FreeCAD unavailable → 503, not silent fallback."""

    def test_freecad_unavailable_returns_503(self, client, monkeypatch):
        """When OPENCAD_ENGINE=freecad but FreeCAD is unavailable,
        rebuild should return 503, not silently use build123d."""
        # Create a project first (with build123d engine, which is the default)
        resp = client.post(
            "/api/projects",
            json={"name": "fb-test", "description": "", "units": "mm"},
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        assert resp.status_code == 200
        pid = resp.json()["project_id"]

        # Add sketch + pad (with build123d engine, works fine)
        for cmd in [
            {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "s1", "type": "sketch", "name": "S", "parameters": {}, "sketch_entities": [{"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}], "plane": {"base": "XY", "offset": 0}}},
            {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "p1", "type": "pad", "name": "Pad", "parameters": {"length": 10}, "input": "s1", "references": ["s1"]}},
        ]:
            r = client.post(f"/api/projects/{pid}/commands", json=cmd, headers={"X-Session-Token": client._token})  # type: ignore[attr-defined]
            assert r.status_code == 200

        # Now monkeypatch OPENCAD_ENGINE to freecad and make FreeCAD unavailable
        monkeypatch.setenv("OPENCAD_ENGINE", "freecad")

        # Monkeypatch the freecad adapter to be unavailable
        import cad_worker.adapters.freecad_adapter as fc_adapter
        monkeypatch.setattr(fc_adapter, "FREECAD_AVAILABLE", False)
        monkeypatch.setattr(fc_adapter, "_FREECAD_IMPORT_ERROR", "Test: FreeCAD not available")

        # Rebuild should fail with 503 (or 400 from _classify_error), not silently use build123d
        r = client.post(f"/api/projects/{pid}/rebuild", headers={"X-Session-Token": client._token})  # type: ignore[attr-defined]
        assert r.status_code in (400, 503), f"Expected 400/503 for unavailable FreeCAD, got {r.status_code}: {r.text}"

    def test_freecad_engine_health_degraded(self, client, monkeypatch):
        """Health endpoint should show degraded status when freecad is unavailable."""
        monkeypatch.setenv("OPENCAD_ENGINE", "freecad")

        import cad_worker.adapters.freecad_adapter as fc_adapter
        monkeypatch.setattr(fc_adapter, "FREECAD_AVAILABLE", False)

        resp = client.get("/api/health")
        data = resp.json()
        assert data["engine_requested"] == "freecad"
        assert data["engine"] == "unavailable"
        assert data["status"] == "degraded"


class TestConcurrentRebuild:
    """Landmine #17: Concurrent rebuilds must be serialized."""

    def test_concurrent_rebuilds_succeed(self, client, project):
        """Two concurrent rebuilds on the same project should both succeed
        without crashes — the asyncio.Lock serializes them."""
        import threading

        results = []
        errors = []

        def do_rebuild():
            try:
                r = client.post(
                    f"/api/projects/{project}/rebuild",
                    headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
                )
                results.append(r.status_code)
            except Exception as e:
                errors.append(e)

        # Launch two rebuilds concurrently
        t1 = threading.Thread(target=do_rebuild)
        t2 = threading.Thread(target=do_rebuild)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Both should succeed (200) — serialized by the lock
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2
        for code in results:
            assert code == 200, f"Rebuild failed with {code}"