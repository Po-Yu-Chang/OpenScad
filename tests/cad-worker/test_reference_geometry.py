"""WP1-3 基準幾何（Reference Geometry）測試。"""

import pytest
from fastapi.testclient import TestClient
from cad_worker.server import app
from cad_worker.feature_graph import FeatureGraph, Feature, FeatureType
from cad_worker.reference_geometry_builder import build_reference_geometry
from cad_worker.adapters.build123d_adapter import Build123dAdapter


def _build_test_box(w=20, h=20, length=10):
    """建一個真實的 box（sketch+pad，pad 的 feature_id="f1"），回傳
    (part, trace)。WP-S1：TestReferenceGeometryBuilder 改用真實 BREP 取代
    原本的硬編數字（`_resolve_face` 原本不管實際模型多大，"top" 永遠回傳
    origin=[0,0,10]——現在改成真的查詢這個 box 的面）。
    """
    graph = FeatureGraph()
    graph.add_feature(Feature(
        feature_id="sk1", name="sk1", type=FeatureType.SKETCH,
        plane={"base": "XY", "offset": 0},
        sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": w, "height": h, "center_x": 0, "center_y": 0}}],
    ))
    graph.add_feature(Feature(
        feature_id="f1", name="f1", type=FeatureType.PAD, input="sk1", parameters={"length": length},
    ))
    adapter = Build123dAdapter()
    result = adapter.build_with_trace(graph)
    return result.part, result.trace, graph


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
    """基準幾何重建器。

    WP-S1：`_resolve_face`/`_resolve_vertex` 改用真實 BREP（見
    reference_geometry_builder.py 模組文件）——不再是與模型大小無關的
    硬編數字，因此這裡改用一個真實建出來的 20×20×10 box（sketch+pad，
    pad 的 feature_id="f1"）當 fixture，驗證算出來的座標跟這個 box 的
    真實面一致。沒有 part（`build_reference_geometry(graph)` 不帶 part）
    時，derived_geometry 必須誠實留空，不能再假裝有值。
    """

    def test_build_offset_plane(self):
        part, trace, graph = _build_test_box(length=10)
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "origin" in dg
        assert "normal" in dg
        # top face 真實 z=10（pad length），offset 10 → origin z = 10+10 = 20
        assert dg["origin"][2] == pytest.approx(20.0, abs=0.01)
        assert dg["normal"] == pytest.approx([0, 0, 1], abs=0.01)

    def test_build_offset_plane_from_face_centroid_ref(self):
        """WP-S1 新增：桌面 UI「真選面」用的 face_centroid:<id>:<x,y,z> 格式
        （使用者點了哪個面，就把該面的真實 centroid 傳回來就近比對），
        取代原本硬編 "face:f1.top" 的 demo 級對話框。"""
        part, trace, graph = _build_test_box(length=10)
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face_centroid:f1:0.0,0.0,10.0", "offset_mm": 2}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg["origin"][2] == pytest.approx(12.0, abs=0.01)
        assert dg["normal"] == pytest.approx([0, 0, 1], abs=0.01)

    def test_build_offset_plane_negative_offset(self):
        part, trace, graph = _build_test_box(length=10)
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.bottom", "offset_mm": -5}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        # bottom face 真實 z=0，normal=[0,0,-1]，offset -5 → origin z = 0 + (-1)*(-5) = 5
        assert dg["origin"][2] == pytest.approx(5.0, abs=0.01)

    def test_build_mid_plane(self):
        part, trace, graph = _build_test_box(length=10)
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "mid_plane", "source_ref": "face:f1.top", "source_ref_2": "face:f1.bottom"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        # mid of top(z=10) and bottom(z=0) → z=5
        assert dg["origin"][2] == pytest.approx(5.0, abs=0.01)

    def test_build_angle_between(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "angle_between", "source_ref": "face:f1.top", "source_ref_2": "face:f1.front", "angle_deg": 30}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "origin" in dg
        assert "normal" in dg

    def test_build_intersection_axis(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "da1", "kind": "axis",
            "definition": {"method": "intersection", "source_ref": "face:f1.top", "source_ref_2": "face:f1.front"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "direction" in dg
        # top normal [0,0,1] × front normal [0,-1,0] = [-1,0,0]（正規化後）
        assert abs(dg["direction"][0]) == pytest.approx(1.0, abs=0.01)
        assert dg["direction"][1] == pytest.approx(0.0, abs=0.01)
        assert dg["direction"][2] == pytest.approx(0.0, abs=0.01)

    def test_build_cylinder_axis(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "da1", "kind": "axis",
            "definition": {"method": "cylinder_axis", "source_ref": "face:f1.top"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "direction" in dg
        assert "origin" in dg

    def test_build_vertex_point_unresolved_stays_empty(self):
        """WP-S1：topology.resolve_reference 尚無 vertex 級查詢（見模組文件
        限制 2），_resolve_vertex 誠實回傳 None，不再假裝是原點。"""
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "point",
            "definition": {"method": "vertex", "source_ref": "vertex:body1.f1.v0"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg == {}

    def test_build_center_point(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "point",
            "definition": {"method": "center", "source_ref": "face:f1.top"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert "point" in dg

    def test_build_empty_for_unknown_method(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "nonexistent"}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg == {}

    def test_build_empty_for_missing_source(self):
        part, trace, graph = _build_test_box()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "", "offset_mm": 10}
        })
        build_reference_geometry(graph, part, trace)
        dg = graph.reference_geometry[0]["derived_geometry"]
        assert dg == {}

    def test_build_without_part_stays_empty(self):
        """WP-S1 核心案例：沒有 part（尚無上一輪 rebuild 結果）時，
        derived_geometry 必須誠實留空，不能再回傳硬編假數字。"""
        graph = FeatureGraph()
        graph.add_reference_geometry({
            "id": "dp1", "kind": "plane",
            "definition": {"method": "offset", "source_ref": "face:f1.top", "offset_mm": 10}
        })
        build_reference_geometry(graph)  # part/trace 都不給，模擬第一輪 rebuild 前
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


# ─── datum 平面草圖——雙引擎端到端（WP-S1：FreeCAD 原本一律當 XY，見下）───

import os as _os
import sys as _sys

_FREECAD_DIR = _os.environ.get("FREECAD_DIR", "")
if not _FREECAD_DIR:
    _FREECAD_DIR = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "FreeCAD", "FreeCAD_1.1.1-Windows-x86_64-py311",
    )
    _os.environ.setdefault("FREECAD_DIR", _FREECAD_DIR)
if _os.path.isdir(_FREECAD_DIR):
    for _p in [_os.path.join(_FREECAD_DIR, "bin"), _os.path.join(_FREECAD_DIR, "lib")]:
        if _p not in _sys.path:
            _sys.path.insert(0, _p)

try:
    from cad_worker.adapters.freecad_adapter import FreeCADAdapter, FREECAD_AVAILABLE
except ImportError:
    FREECAD_AVAILABLE = False


def _build_datum_plane_sketch_graph(adapter_cls):
    """base box(20x20x10) → datum plane（top 面 offset 5mm）→ 該 datum 上
    再 sketch+pad 一個 10x10x3 的小塊，回傳兩輪 rebuild 後的最終 part。

    這是驗證「datum 平面不再一律被當成 XY」的核心情境：如果 datum 平面
    解析失效、退回 XY，第二個 pad 會長在 z=[0,3]（跟 base box 重疊）；
    解析正確的話，會長在 z=[15,18]（base box 頂面 10 + datum offset 5）。
    """
    graph = FeatureGraph()
    graph.add_feature(Feature(
        feature_id="sk1", name="sk1", type=FeatureType.SKETCH,
        plane={"base": "XY", "offset": 0},
        sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": 20, "height": 20, "center_x": 0, "center_y": 0}}],
    ))
    graph.add_feature(Feature(
        feature_id="base_pad", name="base_pad", type=FeatureType.PAD, input="sk1", parameters={"length": 10},
    ))
    graph.add_reference_geometry({
        "id": "dp1", "kind": "plane",
        "definition": {"method": "offset", "source_ref": "face:base_pad.top", "offset_mm": 5},
    })

    adapter = adapter_cls()

    # 第一輪：只建 base box，取得 part/trace 供 datum 解析用
    result1 = adapter.build_with_trace(graph)
    build_reference_geometry(graph, result1.part, result1.trace)
    dg = graph.reference_geometry[0]["derived_geometry"]
    assert dg.get("origin") is not None, "datum 應該要能解析到 base_pad 的頂面"

    # 第二輪：加上 datum 平面上的 sketch+pad，用剛解析出的 derived_geometry 重建
    graph.add_feature(Feature(
        feature_id="sk2", name="sk2", type=FeatureType.SKETCH,
        plane={"base": "datum:dp1", "offset": 0},
        sketch_entities=[{"entity_type": "rectangle", "parameters": {"width": 10, "height": 10, "center_x": 0, "center_y": 0}}],
    ))
    graph.add_feature(Feature(
        feature_id="top_pad", name="top_pad", type=FeatureType.PAD, input="sk2", parameters={"length": 3},
    ))
    result2 = adapter.build_with_trace(graph)
    return result2.part


class TestDatumPlaneSketchBuild123d:
    def test_sketch_on_datum_plane_positions_correctly(self):
        part = _build_datum_plane_sketch_graph(Build123dAdapter)
        bb = part.bounding_box()
        # base box 頂面在 z=10，datum 平面偏移 5 → 頂面新拉伸應到 z=18
        assert bb.max.Z == pytest.approx(18.0, abs=0.5)


@pytest.mark.skipif(not FREECAD_AVAILABLE, reason="FreeCAD not available（需 cp311 環境）")
class TestDatumPlaneSketchFreeCAD:
    def test_sketch_on_datum_plane_positions_correctly(self):
        """WP-S1 修復核心案例：FreeCAD 引擎原本 datum 平面一律當 XY 處理
        （_sketch_entity_to_edges 的 datum 分支硬寫 `return Vector(x,y,offset)`，
        跟 derived_geometry 完全無關）。修復後應與 build123d 得到一致的高度。
        """
        part = _build_datum_plane_sketch_graph(FreeCADAdapter)
        bb = part.BoundBox
        assert bb.ZMax == pytest.approx(18.0, abs=0.5)