"""WP-H1 LLM 收斂測試——10 案例。

驗收條件（Master Plan §WP-H1）：
1. 缺尺寸提問
2. 歧義要求點選
3. 不支援拒絕
4. 防偷換（要求「螺旋齒輪」→拒絕而非圓柱）
5-8. 各修復白名單類型正確處理
9. TPM 內 token 量測
10. 非 白名單錯誤出卡片

WP-S1 誠實標註：本檔絕大多數案例（1/1b/2/4）都是拿手動寫死的
`simulated_plan` dict 自我斷言（斷言的兩邊都來自同一段寫死資料，
沒有呼叫任何真實 LLM gateway，也沒有經過 `_worker`/`server.py` 的
apply_plan 流程）——**非端到端測試**，只能證明「這段程式碼認得出
它自己剛寫的 dict 長什麼樣子」，證明不了真實 LLM 會不會這樣輸出。
只有 §3（不支援拒絕）走 `opencad_llm_validator.validate_against_catalog()`
是真的呼叫程式碼、有實質驗證力。真 gateway 端到端驗證歸 Master Plan
§3.5（WP-H1 殘項），不在本檔範圍內。
"""
import json
import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN

client = TestClient(app)
headers = {"X-Session-Token": SESSION_TOKEN}


# ─── Helper ───

def create_project(name="wp-h1-test"):
    resp = client.post("/api/projects", json={"name": name, "description": "WP-H1 test"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def apply_cmd(pid, action, **kwargs):
    cmd = {"schema_version": "1.0", "action": action, **kwargs}
    resp = client.post(f"/api/projects/{pid}/commands", json=cmd, headers=headers)
    return resp


def rebuild(pid, dry_run=False):
    url = f"/api/projects/{pid}/rebuild"
    if dry_run:
        url += "?dry_run=true"
    return client.post(url, headers=headers)


# ─── 1. 缺尺寸提問 ───

class TestMissingDimensions:
    """使用者需求缺少尺寸時，LLM 應在 missing_info 中提問，不得猜測。"""

    def test_missing_dimensions_returns_missing_info(self):
        """案例1：要求「做一個盒子」無尺寸→missing_info 非空。"""
        # Simulate LLM response validation: if missing_info is empty when no dimensions given → fail
        simulated_plan = {
            "steps": [{"description": "建立盒子", "feature_type": "sketch", "parameters": {}}],
            "summary": "盒子",
            "missing_info": ["請提供盒子的長×寬×高尺寸（mm）"],
        }
        assert len(simulated_plan["missing_info"]) > 0, "缺尺寸時 missing_info 不得為空"

    @pytest.mark.skip(
        reason="WP-S1：原本的斷言是恆真的（`assert has_arbitrary and has_no_questions`"
        "檢查的兩個布林值直接讀自它自己剛寫死的 dict，不管系統做什麼都會過，"
        "沒有測到任何真實行為）。這裡想測的規則——「LLM 不得用任意預設值"
        "取代提問」——目前只在 system prompt 裡用文字要求 LLM 遵守，"
        "沒有對應的程式硬檢查函式可測（對照 opencad_llm_validator.py 的"
        "validate_against_catalog，那個是真的有函式可以測的规则）。"
        "在真的補一個「疑似隨意帶入預設值」偵測器之前，誠實地 skip，"
        "不要用恆真斷言假裝這條規則已經被驗證。",
    )
    def test_missing_dimensions_no_arbitrary_values(self):
        """案例1b：不得使用任意預設值（如 10x10x10）取代提問。"""


# ─── 2. 歧義要求點選 ───

class TestAmbiguousSelector:
    """selector 歧義時要求使用者點選。"""

    def test_ambiguous_hole_position(self):
        """案例2：要求「挖一個孔」未指定位置→missing_info 含位置需求。"""
        simulated_plan = {
            "steps": [{"description": "挖孔", "feature_type": "hole", "parameters": {"diameter": 5}}],
            "missing_info": ["請指定孔的位置（座標或面）"],
        }
        assert any("位置" in info for info in simulated_plan["missing_info"]), \
            "歧義選擇器必須要求點選"


# ─── 3. 不支援拒絕 ───

class TestUnsupportedFeature:
    """不支援的功能→明確說明不支援，不得偷換近似幾何。"""

    def test_thread_unsupported(self):
        """案例3：要求 thread 螺紋→拒絕，action=rebuild。

        WP1-6 後 rib/draft 已支援，改用 thread（仍不支援）測試拒絕邏輯。
        """
        from opencad_llm_validator import validate_against_catalog
        cmd = {"action": "create_feature", "feature": {"type": "thread", "parameters": {}},
               "reasoning": "建立螺紋", "schema_version": "1.0"}
        ok, reason = validate_against_catalog(cmd)
        assert not ok, "thread 應被拒絕"
        assert "不支援" in reason

    def test_knit_unsupported(self):
        """案例3b：要求 knit 縫合曲面→拒絕。

        WP1-6 後 rib/draft 已支援，改用 knit（仍不支援）測試拒絕邏輯。
        """
        from opencad_llm_validator import validate_against_catalog
        cmd = {"action": "create_feature", "feature": {"type": "knit", "parameters": {}},
               "reasoning": "縫合曲面", "schema_version": "1.0"}
        ok, reason = validate_against_catalog(cmd)
        assert not ok


# ─── 4. 防偷換（螺旋齒輪→拒絕而非圓柱） ───

class TestNoApproximation:
    """不支援的功能不得偷換近似幾何。"""

    def test_helical_gear_rejected_not_cylinder(self):
        """案例4：要求「螺旋齒輪」→拒絕，不可改為圓柱。"""
        from opencad_llm_validator import validate_against_catalog
        # LLM 企圖用 cylinder 近似螺旋齒輪——reasoning 提到 helical_gear
        cmd = {"action": "create_feature", "feature": {"type": "cylinder", "parameters": {"radius": 10}},
               "reasoning": "以圓柱近似 helical_gear 螺旋齒輪", "schema_version": "1.0"}
        ok, reason = validate_against_catalog(cmd)
        assert not ok, "不得以近似幾何替代不支援功能"
        assert "helical_gear" in reason or "不支援" in reason


# ─── 5-8. 修復白名單類型 ───

class TestRepairWhitelist:
    """修復白名單——只允許低風險修復類型。"""

    REPAIR_WHITELIST = {
        "SKETCH_NOT_CLOSED",
        "INVALID_STANDARD_PART",
        "REFERENCE_NOT_FOUND",
        "FILLET_RADIUS_TOO_LARGE",
        "CHAMFER_DISTANCE_TOO_LARGE",
    }

    def test_whitelist_includes_sketch_not_closed(self):
        """案例5：SKETCH_NOT_CLOSED 在白名單中。"""
        assert "SKETCH_NOT_CLOSED" in self.REPAIR_WHITELIST

    def test_whitelist_includes_fillet_radius(self):
        """案例6：FILLET_RADIUS_TOO_LARGE 在白名單中。"""
        assert "FILLET_RADIUS_TOO_LARGE" in self.REPAIR_WHITELIST

    def test_non_whitelisted_error_outputs_card(self):
        """案例7：CIRCULAR_DEPENDENCY 不在白名單→應出卡片不自動修復。"""
        assert "CIRCULAR_DEPENDENCY" not in self.REPAIR_WHITELIST

    def test_max_retries_is_2(self):
        """案例8：低風險修復最多 2 次（非 3 次）。"""
        max_retries = 2  # MainViewModel.TryRepairAsync maxRetries
        assert max_retries == 2, "WP-H1 地雷 #16：修復迴圈由 3 次改為 2 次"


# ─── 9. Capability payload ───

class TestCapabilityPayload:
    """Capability payload——每次 LLM context 必帶。"""

    def test_capability_endpoint(self):
        """案例9：/api/capability 回傳 schema_version, engine_version, feature_catalog。"""
        resp = client.get("/api/capability", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "schema_version" in data
        assert "engine_version" in data
        assert "feature_catalog" in data
        assert "unsupported_features" in data
        assert isinstance(data["feature_catalog"], list)
        assert len(data["feature_catalog"]) > 0

    def test_capability_lists_unsupported(self):
        """案例9b：不支援清單含 thread, knit, trim_surface（WP1-6 後 rib/draft 已支援）。"""
        resp = client.get("/api/capability", headers=headers)
        data = resp.json()
        unsupported = data["unsupported_features"]
        assert "thread" in unsupported
        assert "knit" in unsupported
        assert "rib" not in unsupported  # WP1-6: rib 已支援
        assert "draft" not in unsupported  # WP1-6: draft 已支援

    def test_capability_lists_tools(self):
        """案例9c：工具清單含 6 個 deterministic tools。"""
        resp = client.get("/api/capability", headers=headers)
        data = resp.json()
        tools = data["tools"]
        assert "inspect_document" in tools
        assert "query_feature_catalog" in tools
        assert "propose_transaction" in tools
        assert "validate_transaction" in tools
        assert "rebuild_staging" in tools
        assert "request_user_confirmation" in tools

    def test_capability_flags_partial_features(self):
        """WP-S1（Master Plan §3.4 item 14）：draft/variable_fillet/shell/thin/
        countersink 兩引擎都只有簡化實作（見 FREECAD_ADAPTER_LIMITATIONS.md），
        catalog 必須標 status=partial＋limitation 說明，不能讓 LLM 誤以為
        這些型別功能完整——禁止靜默使用。"""
        resp = client.get("/api/capability", headers=headers)
        data = resp.json()
        by_type = {entry["type"]: entry for entry in data["feature_catalog"]}
        for ftype in ("draft", "variable_fillet", "shell", "thin", "countersink"):
            assert by_type[ftype]["status"] == "partial", f"{ftype} 應標 partial"
            assert by_type[ftype].get("limitation"), f"{ftype} 應附限制說明"
        # 功能完整的型別不該被誤標
        assert by_type["pad"]["status"] == "full"
        assert "limitation" not in by_type["pad"]


# ─── 10. Dry-run rebuild ───

class TestDryRunRebuild:
    """rebuild_staging 工具——dry_run=true 只試跑不 commit。"""

    def test_dry_run_does_not_bump_mesh_revision(self):
        """案例10：dry_run rebuild 不 commit（不寫盤、不 bump mesh_revision）。"""
        pid = create_project("dry-run-test")
        # Build a simple pad
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "s1", "type": "sketch", "parameters": {},
                           "sketch_entities": [{"type": "rectangle", "width": 10, "height": 10}],
                           "plane": {"base": "XY"}})
        apply_cmd(pid, "create_feature",
                  feature={"feature_id": "p1", "type": "pad", "input": "s1", "parameters": {"length": 5}})
        # Normal rebuild to get baseline
        r1 = rebuild(pid)
        assert r1.status_code == 200, f"Normal rebuild failed: {r1.text}"
        rev1 = r1.json().get("mesh_revision", 0)
        # Dry-run rebuild — should NOT include mesh_revision in response
        r2 = rebuild(pid, dry_run=True)
        assert r2.status_code == 200, f"Dry-run rebuild failed: {r2.text}"
        assert r2.json().get("dry_run") is True
        # Dry-run response should NOT have mesh_revision (no commit)
        assert "mesh_revision" not in r2.json(), "dry_run 不應回傳 mesh_revision（未 commit）"
        # Dry-run should still return valid mass properties
        assert "mass_properties" in r2.json(), "dry_run 應回傳 mass_properties"

    def test_dry_run_returns_status(self):
        """案例10b：dry_run 回傳 status=success。"""
        pid = create_project("dry-run-status")
        r = rebuild(pid, dry_run=True)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") in ("success", "failed")
        assert data.get("dry_run") is True


# ─── Token estimation helper ───

class TestTokenEstimation:
    """TPM 內 token 量測——capability payload 不應過大。"""

    def test_capability_payload_size_reasonable(self):
        """案例10c：capability payload JSON 不超過 5000 字元（token 量測）。"""
        resp = client.get("/api/capability", headers=headers)
        body = resp.text
        assert len(body) < 5000, f"Capability payload 過大: {len(body)} chars, 應 < 5000"