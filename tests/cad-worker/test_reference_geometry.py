"""WP1-3 基準幾何（Reference Geometry）測試。"""

import pytest
from fastapi.testclient import TestClient
from cad_worker.server import app
from cad_worker.feature_graph import FeatureGraph
from cad_worker.reference_geometry_builder import build_reference_geometry


# ─── FeatureGraph reference_geometry 管理 ───


class TestFeatureGraphReferenceGeometry:
    """FeatureGraph 的基準幾何 CRUD。"""

    def test_add_reference_geometry(self):
        graph = FeatureGraph()
        datum = {"id": "dp1", "name": "偏移面", "kind": "plane",
                 "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}}
        graph.add_reference_geometry(datum)
        assert len(graph.reference_geometry) == 1
        assert graph.reference_geometry[0]["id"] == "dp1"

    def test_add_duplicate_id_raises(self):
        graph = FeatureGraph()
        datum = {"id": "dp1", "kind": "plane", "definition": {"method": "offset"}}
        graph.add_reference_geometry(datum)
        with pytest.raises(ValueError, match="已存在"):
            graph.add_reference_geometry({"id": "dp1", "kind": "plane", "definition": {"method": "offset"}})

    def test_add_without_id_raises(self):
        graph = FeatureGraph()
        with pytest.raises(ValueError, match="id"):
            graph.add_reference_geometry({"kind": "plane", "definition": {"method": "offset"}})

    def test_delete_reference_geometry(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({"id": "dp1", "kind": "plane", "definition": {"method": "offset"}})
        assert graph.delete_reference_geometry("dp1") is True
        assert len(graph.reference_geometry) == 0
        assert graph.delete_reference_geometry("dp1") is False

    def test_update_reference_geometry(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({"id": "dp1", "name": "舊", "kind": "plane",
                                      "definition": {"method": "offset", "offset_mm": 5}})
        result = graph.update_reference_geometry("dp1", {"name": "新", "definition": {"method": "offset", "offset_mm": 15}})
        assert result is not None
        assert result["name"] == "新"
        assert result["definition"]["offset_mm"] == 15

    def test_update_nonexistent_returns_none(self):
        graph = FeatureGraph()
        assert graph.update_reference_geometry("nope", {"name": "x"}) is None

    def test_reference_geometry_in_to_dict(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({"id": "dp1", "kind": "plane", "definition": {"method": "offset"}})
        d = graph.to_dict()
        assert "reference_geometry" in d
        assert d["reference_geometry"][0]["id"] == "dp1"

    def test_reference_geometry_from_dict(self):
        d = {"schema_version": "2.0", "features": [], "bodies": [],
             "reference_geometry": [{"id": "dp1", "kind": "plane", "definition": {"method": "offset"}}]}
        graph = FeatureGraph.from_dict(d)
        assert len(graph.reference_geometry) == 1
        assert graph.reference_geometry[0]["id"] == "dp1"


# ─── reference_geometry_builder ───


class TestReferenceGeometryBuilder:
    """基準幾何重建器。"""

    def test_build_offset_plane(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "origin" in dg
        assert "normal" in dg
        # top face normal = [0,0,1], offset 10 → origin z = 10+10 = 20
        assert dg["origin"][2] == 20.0
        assert dg["normal"] == [0, 0, 1]

    def test_build_offset_plane_negative_offset(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.bottom", "offset_mm": -5}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        # bottom face normal = [0,0,-1], offset -5 → origin z = 0 + (-1)*(-5) = 5
        assert dg["origin"][2] == 5.0

    def test_build_mid_plane(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "mid_plane", "source_ref": "face:f1.top", "source_ref_2": "face:f1.bottom"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        # mid of top(0,0,10) and bottom(0,0,0) → (0,0,5)
        assert dg["origin"][2] == 5.0

    def test_build_angle_between(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "angle_between", "source_ref": "face:f1.top", "source_ref_2": "face:f1.front", "angle_deg": 30}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "origin" in dg
        assert "normal" in dg

    def test_build_intersection_axis(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "da1", "kind": "axis",
            "definition": {"method": "intersection", "source_ref": "face:f1.top", "source_ref_2": "face:f1.front"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "direction" in dg
        # top normal [0,0,1] × front normal [0,1,0] = [1*0-0*0, 0*0-0*0, 0*1-0*0]... 
        # Actually [0,0,1] × [0,1,0] = [0*0-1*1, 1*0-0*0, 0*1-0*0] = [-1, 0, 0]
        # Normalized: [-1, 0, 0]
        assert dg["direction"][0] == pytest.approx(-1.0, abs=0.01)

    def test_build_cylinder_axis(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "da1", "kind": "axis",
            "definition": {"method": "cylinder_axis", "source_ref": "face:f1.top"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "direction" in dg
        assert "origin" in dg

    def test_build_vertex_point(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "point",
            "definition": {"method": "vertex", "source_ref": "vertex:body1.f1.v0"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "point" in dg

    def test_build_center_point(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "point",
            "definition": {"method": "center", "source_ref": "face:f1.top"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "point" in dg

    def test_build_empty_for_unknown_method(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "nonexistent"}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg == {}

    def test_build_empty_for_missing_source(self):
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "", "offset_mm": 10}
        })
        build_reference_geometry(graph)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg == {}


# ─── HTTP 端點 ───


class TestReferenceGeometryEndpoints:
    """基準幾何 HTTP 端點。"""

    def setup_method(self):
        from cad_worker.server import SESSION_TOKEN
        self.client = TestClient(app)
        self.headers = {"X-Session-Token": SESSION_TOKEN}

    def _create_project(self):
        resp = self.client.post("/api/projects", json={
            "name": "test_rg", "description": "test",
            "units": "mm", "engine": "build123d", "material": "pla"
        }, headers=self.headers)
        return resp.json()["project_id"]

    def test_list_empty(self):
        pid = self._create_project()
        resp = self.client.get(f"/api/projects/{pid}/reference_geometry", headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["reference_geometry"] == []

    def test_create_reference_geometry(self):
        pid = self._create_project()
        resp = self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "name": "偏移面", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}
        }, headers=self.headers)
        assert resp.status_code == 200
        rg = resp.json()["reference_geometry"]
        assert len(rg) == 1
        assert rg[0]["id"] == "dp1"
        assert rg[0]["kind"] == "plane"

    def test_create_duplicate_id_400(self):
        pid = self._create_project()
        self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "kind": "plane", "definition": {"method": "offset", "offset_mm": 5}
        }, headers=self.headers)
        resp = self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "kind": "plane", "definition": {"method": "offset", "offset_mm": 10}
        }, headers=self.headers)
        assert resp.status_code == 400

    def test_delete_reference_geometry(self):
        pid = self._create_project()
        self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "kind": "plane", "definition": {"method": "offset", "offset_mm": 5}
        }, headers=self.headers)
        resp = self.client.delete(f"/api/projects/{pid}/reference_geometry/dp1", headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_404(self):
        pid = self._create_project()
        resp = self.client.delete(f"/api/projects/{pid}/reference_geometry/nonexistent", headers=self.headers)
        assert resp.status_code == 404

    def test_update_reference_geometry(self):
        pid = self._create_project()
        self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "name": "舊", "kind": "plane",
            "definition": {"method": "offset", "offset_mm": 5}
        }, headers=self.headers)
        resp = self.client.put(f"/api/projects/{pid}/reference_geometry/dp1", json={
            "id": "dp1", "name": "新", "kind": "plane",
            "definition": {"method": "offset", "offset_mm": 15}
        }, headers=self.headers)
        assert resp.status_code == 200
        rg = resp.json()["reference_geometry"]
        assert rg[0]["name"] == "新"
        assert rg[0]["definition"]["offset_mm"] == 15

    def test_update_nonexistent_404(self):
        pid = self._create_project()
        resp = self.client.put(f"/api/projects/{pid}/reference_geometry/nonexistent", json={
            "id": "dp1", "kind": "plane", "definition": {"method": "offset", "offset_mm": 5}
        }, headers=self.headers)
        assert resp.status_code == 404

    def test_reference_geometry_enters_history(self):
        """建立 datum plane 後，專案 features.json 應包含 reference_geometry。"""
        pid = self._create_project()
        self.client.post(f"/api/projects/{pid}/reference_geometry", json={
            "id": "dp1", "name": "偏移面", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}
        }, headers=self.headers)
        resp = self.client.get(f"/api/projects/{pid}", headers=self.headers)
        assert resp.status_code == 200
        features = resp.json()["features"]
        assert "reference_geometry" in features
        assert len(features["reference_geometry"]) == 1

    def test_404_for_unknown_project(self):
        resp = self.client.get("/api/projects/nonexistent/reference_geometry", headers=self.headers)
        assert resp.status_code == 404


# ─── Command validator ───


class TestReferenceGeometryValidation:
    """命令驗證器對 reference_geometry 命令的驗證。"""

    def test_validate_create_reference_geometry_valid(self):
        from cad_worker.validators.command_validator import CommandValidator
        cmd = {
            "action": "create_reference_geometry",
            "document_id": "p1",
            "reference_geometry": {"id": "dp1", "kind": "plane", "definition": {"method": "offset"}}
        }
        errors = CommandValidator.validate(cmd)
        assert len(errors) == 0

    def test_validate_create_reference_geometry_missing_id(self):
        from cad_worker.validators.command_validator import CommandValidator
        cmd = {
            "action": "create_reference_geometry",
            "document_id": "p1",
            "reference_geometry": {"kind": "plane", "definition": {"method": "offset"}}
        }
        errors = CommandValidator.validate(cmd)
        assert any("id" in e for e in errors)

    def test_validate_create_reference_geometry_missing_rg(self):
        from cad_worker.validators.command_validator import CommandValidator
        cmd = {"action": "create_reference_geometry", "document_id": "p1"}
        errors = CommandValidator.validate(cmd)
        assert any("reference_geometry" in e for e in errors)

    def test_validate_delete_reference_geometry_missing_target(self):
        from cad_worker.validators.command_validator import CommandValidator
        cmd = {"action": "delete_reference_geometry", "document_id": "p1"}
        errors = CommandValidator.validate(cmd)
        assert any("target_feature_id" in e for e in errors)

    def test_validate_update_reference_geometry_missing_rg(self):
        from cad_worker.validators.command_validator import CommandValidator
        cmd = {"action": "update_reference_geometry", "document_id": "p1", "target_feature_id": "dp1"}
        errors = CommandValidator.validate(cmd)
        assert any("reference_geometry" in e for e in errors)