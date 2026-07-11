"""WP-H2: 安全強化測試。

驗收條件（Master Plan §544）：
- token 錯誤 → 401
- 跨 Origin → 403
- 超大檔案 → 413
- 重建超時 → rollback，graph 不變
"""

from __future__ import annotations

import asyncio
import copy
import time
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
    """建立測試專案。"""
    resp = client.post(
        "/api/projects",
        json={"name": "sec-test", "description": "", "units": "mm"},
        headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
    )
    assert resp.status_code == 200
    pid = resp.json()["project_id"]

    # 建立草圖+pad
    for cmd in [
        {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "s1", "type": "sketch", "name": "S", "parameters": {}, "sketch_entities": [{"type": "rectangle", "center": [0, 0], "width": 10, "height": 10}], "plane": {"base": "XY", "offset": 0}}},
        {"schema_version": "1.0", "action": "create_feature", "feature": {"feature_id": "p1", "type": "pad", "name": "Pad", "parameters": {"length": 5}, "input": "s1", "references": ["s1"]}},
    ]:
        r = client.post(f"/api/projects/{pid}/commands", json=cmd, headers={"X-Session-Token": client._token})  # type: ignore[attr-defined]
        assert r.status_code == 200, f"Command failed: {r.text}"

    return pid


# ─── Token 錯誤 → 401 ───


class TestTokenSecurity:
    """WP-H2: Token 安全——錯誤 token 回 401。"""

    def test_no_token_returns_401(self, client):
        """不帶 token → 401。"""
        resp = client.get("/api/projects")
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client):
        """錯誤 token → 401。"""
        resp = client.get(
            "/api/projects",
            headers={"X-Session-Token": "wrong-token"},
        )
        assert resp.status_code == 401

    def test_correct_token_returns_200(self, client):
        """正確 token → 200。"""
        resp = client.get(
            "/api/projects",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        assert resp.status_code == 200

    def test_token_not_in_url(self, client, project):
        """WP-H2: GLB 端點不接受 URL 中的靜態 token——只接受預簽 token。"""
        # 用舊的靜態 token（SESSION_TOKEN）放在 URL 中應該被拒
        resp = client.get(
            f"/api/projects/{project}/preview.glb",
            params={"token": client._token},  # type: ignore[attr-defined]
        )
        # SESSION_TOKEN 不是預簽 token——應該 401
        assert resp.status_code == 401

    def test_presign_then_glb(self, client, project):
        """WP-H2: 預簽 token 流程——先 /api/presign 取得 token，再帶 token 下載 GLB。"""
        # 先重建（產生 GLB）
        rebuild = client.post(
            f"/api/projects/{project}/rebuild",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        assert rebuild.status_code == 200

        # 取得預簽 token
        resp = client.post(
            "/api/presign",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        assert resp.status_code == 200
        presigned = resp.json()["presigned_token"]

        # 用預簽 token 下載 GLB
        resp = client.get(
            f"/api/projects/{project}/preview.glb",
            params={"token": presigned},
        )
        assert resp.status_code == 200

    def test_presigned_token_single_use(self, client, project):
        """WP-H2: 預簽 token 用後即棄——第二次使用應 401。"""
        # 先重建
        client.post(
            f"/api/projects/{project}/rebuild",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        # 取得預簽 token
        resp = client.post(
            "/api/presign",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )
        presigned = resp.json()["presigned_token"]

        # 第一次使用——成功
        r1 = client.get(f"/api/projects/{project}/preview.glb", params={"token": presigned})
        assert r1.status_code == 200

        # 第二次使用——應該 401（用後即棄）
        r2 = client.get(f"/api/projects/{project}/preview.glb", params={"token": presigned})
        assert r2.status_code == 401


# ─── 跨 Origin → 403 ───


class TestOriginSecurity:
    """WP-H2: Origin 驗證——只允許 WebView2 同源 + app 自身。"""

    def test_allowed_origin_localhost(self, client):
        """localhost origin 應允許。"""
        resp = client.get(
            "/api/projects",
            headers={
                "X-Session-Token": client._token,  # type: ignore[attr-defined]
                "Origin": "http://localhost:8080",
            },
        )
        assert resp.status_code == 200

    def test_allowed_origin_127(self, client):
        """127.0.0.1 origin 應允許。"""
        resp = client.get(
            "/api/projects",
            headers={
                "X-Session-Token": client._token,  # type: ignore[attr-defined]
                "Origin": "http://127.0.0.1:8080",
            },
        )
        assert resp.status_code == 200

    def test_blocked_origin_external(self, client):
        """外部 origin 應被拒——403。

        注意：TestClient 預設不送 Origin header，且 _is_allowed_origin
        對空 Origin 回 True。這個測試確認惡意 Origin 被拒。
        """
        # 直接測試 _is_allowed_origin 函數
        from cad_worker.server import _is_allowed_origin
        assert _is_allowed_origin("http://evil.com") is False
        assert _is_allowed_origin("https://attacker.example.com") is False
        assert _is_allowed_origin("http://localhost:8080") is True
        assert _is_allowed_origin("http://127.0.0.1:3000") is True
        assert _is_allowed_origin(None) is True  # 非 browser 請求
        assert _is_allowed_origin("file:///app/viewer.html") is True
        assert _is_allowed_origin("ms-appx-web:///index.html") is True


# ─── 超大檔案 → 413 ───


class TestFileSizeLimit:
    """WP-H2: 檔案大小限制。"""

    def test_import_too_large_returns_413(self, client):
        """ZIP 匯入超過 MAX_IMPORT_SIZE → 413。"""
        from cad_worker.server import MAX_IMPORT_SIZE
        # 製造超過上限的 body——只差 1 byte
        oversized = b"\x00" * (MAX_IMPORT_SIZE + 1)
        resp = client.post(
            "/api/projects/import-zip",
            content=oversized,
            headers={
                "X-Session-Token": client._token,  # type: ignore[attr-defined]
                "Content-Type": "application/zip",
            },
        )
        assert resp.status_code == 413

    def test_step_face_limit_constant(self):
        """WP-H2: STEP 面數上限常數存在。"""
        from cad_worker.server import MAX_STEP_FACES, MAX_TRIANGLE_COUNT
        assert MAX_STEP_FACES > 0
        assert MAX_TRIANGLE_COUNT > 0


# ─── 重建超時 → rollback，graph 不變 ───


class TestRebuildTimeout:
    """WP-H2: 重建超時 → rollback 到上一版本，graph 不變。"""

    def test_rebuild_timeout_endpoint_rollback(self, client, project):
        """重建超時 → endpoint 回 408 且 graph 不變（monkeypatch 版）。"""
        # 先正常重建——確保 graph 是穩定的
        client.post(
            f"/api/projects/{project}/rebuild",
            headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
        )

        from cad_worker.server import _get_project
        proj = _get_project(project)
        graph_before = copy.deepcopy(proj["graph"].to_dict())

        # Monkeypatch _rebuild to be very slow
        async def slow_rebuild(pid, p):
            await asyncio.sleep(100)
            return {}

        import cad_worker.server as srv
        original_rebuild = srv._rebuild
        original_timeout = srv.REBUILD_TIMEOUT_SECONDS
        srv._rebuild = slow_rebuild
        srv.REBUILD_TIMEOUT_SECONDS = 1  # 1 秒超時——測試不會等太久
        try:
            resp = client.post(
                f"/api/projects/{project}/rebuild",
                headers={"X-Session-Token": client._token},  # type: ignore[attr-defined]
            )
            assert resp.status_code == 408
        finally:
            srv._rebuild = original_rebuild
            srv.REBUILD_TIMEOUT_SECONDS = original_timeout

        # graph 應不變
        proj = _get_project(project)
        graph_after = proj["graph"].to_dict()
        assert graph_after == graph_before


# ─── 路徑正規化 ───


class TestPathCanonicalization:
    """WP-H2: 路徑正規化——拒絕 symlink 逃逸。"""

    def test_canonicalize_within_workdir(self):
        """WORK_DIR 下的路徑應通過。"""
        from cad_worker.server import _canonicalize_path, WORK_DIR
        result = _canonicalize_path(WORK_DIR / "test_project")
        assert str(result).startswith(str(WORK_DIR.resolve()))

    def test_canonicalize_outside_workdir_rejected(self):
        """WORK_DIR 外的路徑應被拒——403。"""
        from pathlib import Path as _Path
        from cad_worker.server import _canonicalize_path
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _canonicalize_path(_Path("/etc/passwd"))
        assert exc_info.value.status_code == 403

    def test_canonicalize_parent_traversal_rejected(self):
        """../ 遍歷應被拒。"""
        from pathlib import Path as _Path
        from cad_worker.server import _canonicalize_path, WORK_DIR
        from fastapi import HTTPException
        # 嘗試逃逸到 WORK_DIR 上層
        escape_path = _Path(str(WORK_DIR)) / "../../../etc/passwd"
        with pytest.raises(HTTPException) as exc_info:
            _canonicalize_path(escape_path)
        assert exc_info.value.status_code == 403


# ─── Temp 清理 ───


class TestTempCleanup:
    """WP-H2: Worker temp 目錄清理。"""

    def test_cleanup_temp_dir(self, tmp_path):
        """_cleanup_temp_dir 應清理 tmp 子目錄下的檔案。"""
        from cad_worker.server import _cleanup_temp_dir, WORK_DIR
        # 建立假 temp 檔案
        temp_dir = WORK_DIR / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        test_file = temp_dir / "test_tmp.txt"
        test_file.write_text("temp")
        assert test_file.exists()

        _cleanup_temp_dir()

        # 檔案應被清理
        assert not test_file.exists()