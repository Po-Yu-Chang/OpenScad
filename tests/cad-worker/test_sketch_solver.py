"""WP1-2 Real Sketcher 測試——約束求解器 + solve 端點。

測試涵蓋：
- 14 種約束類型各一案例
- DOF 計算與狀態（under/full/over）
- 衝突偵測
- solve 端點（HTTP）
- 互動式不進入歷史
"""
import json
import pytest
from fastapi.testclient import TestClient

from cad_worker.sketch_solver import (
    Constraint, SolverStatus, calculate_dof, solve,
    CONSTRAINT_TYPES, CONSTRAINT_DOF_COST,
)
from cad_worker.feature_graph import Feature, FeatureType, FeatureGraph


# ── 約束資料模型測試 ──

class TestConstraintModel:
    def test_constraint_to_dict(self):
        c = Constraint(id="c1", type="distance", targets=["e1.start", "e2.end"], value_mm=60, name="d1")
        d = c.to_dict()
        assert d["id"] == "c1"
        assert d["type"] == "distance"
        assert d["targets"] == ["e1.start", "e2.end"]
        assert d["value_mm"] == 60
        assert d["name"] == "d1"

    def test_constraint_from_dict(self):
        d = {"id": "c2", "type": "radius", "targets": ["e1.center"], "value_mm": 5}
        c = Constraint.from_dict(d)
        assert c.id == "c2"
        assert c.type == "radius"
        assert c.value_mm == 5
        assert c.name == ""

    def test_constraint_types_complete(self):
        """確保 14 種約束類型都有定義。"""
        expected = {
            "coincident", "horizontal", "vertical", "parallel", "perpendicular",
            "equal", "distance", "radius", "diameter", "midpoint", "symmetric",
            "angle", "concentric", "tangent",
        }
        assert CONSTRAINT_TYPES == expected

    def test_constraint_dof_cost(self):
        """每種約束消耗的自由度必須 > 0。"""
        for ctype in CONSTRAINT_TYPES:
            assert CONSTRAINT_DOF_COST[ctype] > 0, f"{ctype} DOF cost missing"


# ── DOF 計算測試 ──

class TestDofCalculation:
    def test_empty_sketch_dof_zero(self):
        """空草圖 DOF=0，state=full。"""
        status = calculate_dof([], [])
        assert status.dof == 0
        assert status.state == "full"

    def test_rectangle_no_constraints_under(self):
        """矩形 4 DOF，無約束 → under。"""
        entities = [{"id": "e1", "type": "rectangle", "width": 40, "height": 20}]
        status = calculate_dof(entities, [])
        assert status.dof == 4
        assert status.state == "under"

    def test_rectangle_fully_constrained(self):
        """矩形 4 DOF，4 個約束(各消耗 1 DOF) → full。"""
        entities = [{"id": "e1", "type": "rectangle", "width": 40, "height": 20}]
        constraints = [
            Constraint(id="c1", type="horizontal", targets=["e1"]),
            Constraint(id="c2", type="vertical", targets=["e1"]),
            Constraint(id="c3", type="radius", targets=["e1.center"], value_mm=5),
            Constraint(id="c4", type="diameter", targets=["e1.center"], value_mm=10),
        ]
        status = calculate_dof(entities, constraints)
        assert status.dof == 0
        assert status.state == "full"

    def test_over_constrained(self):
        """矩形 4 DOF，5 個約束(各消耗 1 DOF) → over，有衝突。"""
        entities = [{"id": "e1", "type": "rectangle", "width": 40, "height": 20}]
        constraints = [
            Constraint(id="c1", type="horizontal", targets=["e1"]),
            Constraint(id="c2", type="vertical", targets=["e1"]),
            Constraint(id="c3", type="radius", targets=["e1.center"], value_mm=5),
            Constraint(id="c4", type="diameter", targets=["e1.center"], value_mm=10),
            Constraint(id="c5", type="horizontal", targets=["e1"]),  # 多餘
        ]
        status = calculate_dof(entities, constraints)
        assert status.state == "over"
        assert len(status.conflicts) == 1

    def test_circle_dof(self):
        """圓 3 DOF。"""
        entities = [{"id": "e1", "type": "circle", "radius": 5}]
        status = calculate_dof(entities, [])
        assert status.dof == 3
        assert status.state == "under"

    def test_line_dof(self):
        """線段 4 DOF。"""
        entities = [{"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}]
        status = calculate_dof(entities, [])
        assert status.dof == 4


# ── 求解器測試（14 種約束各一案例） ──

class TestSolverConstraints:
    def setup_method(self):
        """建立測試用的線段和圓實體。"""
        self.line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 5}
        self.line2 = {"id": "e2", "type": "line", "x1": 0, "y1": 0, "x2": 5, "y2": 10}
        self.circle1 = {"id": "c1", "type": "circle", "center_x": 0, "center_y": 0, "radius": 5}
        self.circle2 = {"id": "c2", "type": "circle", "center_x": 10, "center_y": 0, "radius": 3}

    def test_horizontal_constraint(self):
        """水平約束——y1=y2。"""
        result = solve([self.line1], [
            Constraint(id="h1", type="horizontal", targets=["e1"])
        ])
        entity = result["entities"][0]
        assert entity["y1"] == entity["y2"]

    def test_vertical_constraint(self):
        """鉛直約束——x1=x2。"""
        result = solve([self.line1], [
            Constraint(id="v1", type="vertical", targets=["e1"])
        ])
        entity = result["entities"][0]
        assert entity["x1"] == entity["x2"]

    def test_coincident_constraint(self):
        """重合約束——兩點座標相同。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        line2 = {"id": "e2", "type": "line", "x1": 5, "y1": 5, "x2": 15, "y2": 5}
        result = solve([line1, line2], [
            Constraint(id="co1", type="coincident", targets=["e1.end", "e2.start"])
        ])
        # e2.start 應被移動到 e1.end
        e2 = result["entities"][1]
        e1 = result["entities"][0]
        assert e2["x1"] == e1["x2"]
        assert e2["y1"] == e1["y2"]

    def test_distance_constraint(self):
        """距離約束——兩點距離=value_mm。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        result = solve([line1], [
            Constraint(id="d1", type="distance", targets=["e1.start", "e1.end"], value_mm=60)
        ])
        import math
        e = result["entities"][0]
        dist = math.sqrt((e["x2"] - e["x1"])**2 + (e["y2"] - e["y1"])**2)
        assert abs(dist - 60) < 0.01

    def test_radius_constraint(self):
        """半徑約束——radius=value_mm。"""
        result = solve([self.circle1], [
            Constraint(id="r1", type="radius", targets=["c1.center"], value_mm=10)
        ])
        assert result["entities"][0]["radius"] == 10

    def test_diameter_constraint(self):
        """直徑約束——radius=value_mm/2。"""
        result = solve([self.circle1], [
            Constraint(id="dia1", type="diameter", targets=["c1.center"], value_mm=20)
        ])
        assert result["entities"][0]["radius"] == 10

    def test_equal_constraint(self):
        """等長約束——兩線段等長。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        line2 = {"id": "e2", "type": "line", "x1": 0, "y1": 0, "x2": 5, "y2": 0}
        result = solve([line1, line2], [
            Constraint(id="eq1", type="equal", targets=["e1", "e2"])
        ])
        import math
        e2 = result["entities"][1]
        len2 = math.sqrt((e2["x2"] - e2["x1"])**2 + (e2["y2"] - e2["y1"])**2)
        assert abs(len2 - 10) < 0.01

    def test_parallel_constraint(self):
        """平行約束——角度相同。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        line2 = {"id": "e2", "type": "line", "x1": 0, "y1": 5, "x2": 5, "y2": 10}
        result = solve([line1, line2], [
            Constraint(id="p1", type="parallel", targets=["e1", "e2"])
        ])
        import math
        e2 = result["entities"][1]
        angle2 = math.atan2(e2["y2"] - e2["y1"], e2["x2"] - e2["x1"])
        assert abs(angle2) < 0.01  # 應為 0（水平）

    def test_perpendicular_constraint(self):
        """垂直約束——角度差 90°。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        line2 = {"id": "e2", "type": "line", "x1": 0, "y1": 0, "x2": 5, "y2": 0}
        result = solve([line1, line2], [
            Constraint(id="pe1", type="perpendicular", targets=["e1", "e2"])
        ])
        import math
        e2 = result["entities"][1]
        angle2 = math.atan2(e2["y2"] - e2["y1"], e2["x2"] - e2["x1"])
        assert abs(angle2 - math.pi / 2) < 0.01

    def test_concentric_constraint(self):
        """同心約束——中心重合。"""
        result = solve([self.circle1, self.circle2], [
            Constraint(id="cc1", type="concentric", targets=["c1.center", "c2.center"])
        ])
        c2 = result["entities"][1]
        c1 = result["entities"][0]
        assert c2["center_x"] == c1["center_x"]
        assert c2["center_y"] == c1["center_y"]

    def test_midpoint_constraint(self):
        """中點約束——點在線段中點。"""
        line1 = {"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}
        line2 = {"id": "e2", "type": "line", "x1": 3, "y1": 5, "x2": 7, "y2": 5}
        result = solve([line1, line2], [
            Constraint(id="m1", type="midpoint", targets=["e1", "e2.start"])
        ])
        e2 = result["entities"][1]
        assert e2["x1"] == 5  # (0+10)/2
        assert e2["y1"] == 0

    def test_angle_constraint_type_exists(self):
        """角度約束類型存在。"""
        c = Constraint(id="a1", type="angle", targets=["e1", "e2"], value_deg=45)
        assert c.type == "angle"
        assert c.value_deg == 45

    def test_symmetric_constraint_type_exists(self):
        """對稱約束類型存在。"""
        c = Constraint(id="s1", type="symmetric", targets=["e1.start", "e2.end"])
        assert c.type == "symmetric"

    def test_tangent_constraint_type_exists(self):
        """相切約束類型存在。"""
        c = Constraint(id="t1", type="tangent", targets=["e1", "c1.center"])
        assert c.type == "tangent"

    def test_solve_returns_solver_status(self):
        """solve 回傳 solver_status。"""
        result = solve([self.line1], [])
        assert "solver_status" in result
        assert "dof" in result["solver_status"]
        assert "state" in result["solver_status"]

    def test_solve_preserves_entity_count(self):
        """solve 不改變實體數量。"""
        result = solve([self.line1, self.line2, self.circle1], [])
        assert len(result["entities"]) == 3


# ── SolverStatus 測試 ──

class TestSolverStatus:
    def test_to_dict(self):
        s = SolverStatus(dof=2, state="under", conflicts=[])
        d = s.to_dict()
        assert d["dof"] == 2
        assert d["state"] == "under"
        assert d["conflicts"] == []

    def test_to_dict_with_conflicts(self):
        s = SolverStatus(dof=0, state="over", conflicts=["c5"])
        d = s.to_dict()
        assert d["state"] == "over"
        assert "c5" in d["conflicts"]


# ── Feature Graph 約束整合測試 ──

class TestFeatureGraphConstraints:
    def test_feature_with_constraints(self):
        """Feature 可以儲存 constraints。"""
        feat = Feature(
            feature_id="sketch1",
            type=FeatureType.SKETCH,
            name="草圖1",
            sketch_entities=[{"id": "e1", "type": "rectangle", "width": 40, "height": 20}],
            constraints=[{"id": "c1", "type": "horizontal", "targets": ["e1"]}],
        )
        d = feat.to_dict()
        assert "constraints" in d
        assert len(d["constraints"]) == 1

    def test_feature_from_dict_with_constraints(self):
        """Feature 從 dict 載入 constraints。"""
        d = {
            "feature_id": "sketch1",
            "type": "sketch",
            "name": "草圖1",
            "constraints": [{"id": "c1", "type": "vertical", "targets": ["e1"]}],
        }
        feat = Feature.from_dict(d)
        assert len(feat.constraints) == 1
        assert feat.constraints[0]["type"] == "vertical"

    def test_update_feature_with_constraints(self):
        """update_feature 接受 constraints 參數。"""
        graph = FeatureGraph()
        graph.add_feature(Feature(
            feature_id="sketch1",
            type=FeatureType.SKETCH,
            name="草圖1",
        ))
        graph.update_feature("sketch1", constraints=[{"id": "c1", "type": "horizontal", "targets": ["e1"]}])
        feat = graph.get_feature("sketch1")
        assert len(feat.constraints) == 1


# ── HTTP solve 端點測試 ──

class TestSolveEndpoint:
    @pytest.fixture
    def client_and_project(self):
        from cad_worker.server import app, projects, SESSION_TOKEN
        client = TestClient(app)
        # 建立專案
        resp = client.post("/api/projects", json={
            "name": "test", "description": "test",
            "units": "mm", "engine": "build123d", "material": "pla"
        }, headers={"X-Session-Token": SESSION_TOKEN})
        pid = resp.json()["project_id"]
        # 建立 sketch 特徵
        client.post(f"/api/projects/{pid}/commands", json={
            "action": "create_feature",
            "feature": {
                "feature_id": "sketch1",
                "type": "sketch",
                "name": "草圖1",
                "sketch_entities": [{"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 5}],
            },
        }, headers={"X-Session-Token": SESSION_TOKEN})
        return client, pid, SESSION_TOKEN

    def test_solve_endpoint_returns_entities(self, client_and_project):
        """solve 端點回傳 entities + solver_status。"""
        client, pid, token = client_and_project
        resp = client.post(f"/api/projects/{pid}/sketch/sketch1/solve", json={
            "entities": [{"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 5}],
            "constraints": [{"id": "h1", "type": "horizontal", "targets": ["e1"]}],
        }, headers={"X-Session-Token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "solver_status" in data
        assert data["solver_status"]["state"] in ("under", "full", "over")

    def test_solve_endpoint_uses_feature_entities(self, client_and_project):
        """solve 端點使用特徵既有的 entities（請求未提供時）。"""
        client, pid, token = client_and_project
        resp = client.post(f"/api/projects/{pid}/sketch/sketch1/solve", json={
            "entities": [],
            "constraints": [],
        }, headers={"X-Session-Token": token})
        assert resp.status_code == 200
        data = resp.json()
        # 應使用特徵的 sketch_entities（1 line entity）
        assert len(data["entities"]) == 1

    def test_solve_endpoint_rejects_unknown_constraint_type(self, client_and_project):
        """未知約束類型 → 400。"""
        client, pid, token = client_and_project
        resp = client.post(f"/api/projects/{pid}/sketch/sketch1/solve", json={
            "entities": [{"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}],
            "constraints": [{"id": "x1", "type": "unknown_type", "targets": ["e1"]}],
        }, headers={"X-Session-Token": token})
        assert resp.status_code == 400

    def test_solve_does_not_enter_history(self, client_and_project):
        """solve 端點不進入歷史（互動式）。"""
        client, pid, token = client_and_project
        # 先記錄 revision 數
        resp1 = client.get(f"/api/projects/{pid}/revisions", headers={"X-Session-Token": token})
        rev_count_before = len(resp1.json().get("revisions", []))

        # 呼叫 solve
        client.post(f"/api/projects/{pid}/sketch/sketch1/solve", json={
            "entities": [{"id": "e1", "type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}],
            "constraints": [{"id": "h1", "type": "horizontal", "targets": ["e1"]}],
        }, headers={"X-Session-Token": token})

        # revision 數不應增加
        resp2 = client.get(f"/api/projects/{pid}/revisions", headers={"X-Session-Token": token})
        rev_count_after = len(resp2.json().get("revisions", []))
        assert rev_count_after == rev_count_before

    def test_solve_endpoint_404_unknown_project(self):
        """不存在的專案 → 404。"""
        from cad_worker.server import app, SESSION_TOKEN
        client = TestClient(app)
        resp = client.post("/api/projects/nonexistent/sketch/feat1/solve", json={
            "entities": [], "constraints": []
        }, headers={"X-Session-Token": SESSION_TOKEN})
        assert resp.status_code == 404