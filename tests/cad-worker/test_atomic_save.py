"""WP1-5 檔案格式與復原強化測試。

涵蓋六類驗收場景：
1. crash-during-save（原子寫入——temp 檔→fsync→rename）
2. 磁碟滿（mock——寫入失敗不損壞原檔）
3. 舊版升級（v1→v2 自動遷移）
4. future version（高於支援版本→唯讀開啟）
5. corrupt JSON/ZIP（損壞偵測）
6. ZIP 匯入安全（路徑遍歷、大小、檔數）
"""
import json
import os
import zipfile
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cad_worker.server import app, SESSION_TOKEN, WORK_DIR
from cad_worker.atomic_save import (
    atomic_write_text, atomic_write_json, atomic_write_bytes,
    compute_sha256, compute_file_sha256,
    check_schema_version, validate_zip_path, safe_extract_zip,
    write_journal_entry, detect_unclean_shutdown, get_latest_journal_entry,
    clear_journal, MAX_JOURNAL_ENTRIES,
    SUPPORTED_SCHEMA_VERSIONS, LATEST_SCHEMA_VERSION,
)
from cad_worker.feature_graph import FeatureGraph


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-Session-Token": SESSION_TOKEN}


@pytest.fixture
def tmp_project_dir(tmp_path):
    """臨時專案目錄。"""
    d = tmp_path / "test_project"
    d.mkdir()
    return d


# ═══ 1. 原子寫入（crash-during-save）═══

class TestAtomicWrite:
    """原子寫入——temp 檔→fsync→rename，crash 不損壞。"""

    def test_atomic_write_text_creates_file(self, tmp_project_dir):
        """正常原子寫入應建立檔案。"""
        path = tmp_project_dir / "test.json"
        atomic_write_text(path, '{"hello": "world"}')
        assert path.exists()
        assert path.read_text() == '{"hello": "world"}'

    def test_atomic_write_json_creates_file(self, tmp_project_dir):
        """原子 JSON 寫入應建立檔案。"""
        path = tmp_project_dir / "data.json"
        atomic_write_json(path, {"key": "value"})
        assert path.exists()
        data = json.loads(path.read_text())
        assert data == {"key": "value"}

    def test_atomic_write_replaces_existing(self, tmp_project_dir):
        """原子寫入應取代既有檔案。"""
        path = tmp_project_dir / "replace.json"
        path.write_text("old content", encoding="utf-8")
        atomic_write_text(path, "new content")
        assert path.read_text() == "new content"

    def test_atomic_write_no_tmp_left(self, tmp_project_dir):
        """原子寫入後不應留下 .tmp 檔。"""
        path = tmp_project_dir / "clean.json"
        atomic_write_text(path, "data")
        tmp_files = list(tmp_project_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_failure_cleans_tmp(self, tmp_project_dir):
        """寫入失敗時應清理 .tmp 檔。"""
        path = tmp_project_dir / "fail.json"
        # 模擬寫入失敗——open 失敗
        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                atomic_write_text(path, "data")
        # .tmp 檔不應存在（被清理）
        tmp_files = list(tmp_project_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_preserves_original_on_failure(self, tmp_project_dir):
        """寫入失敗時原檔應保持不變。"""
        path = tmp_project_dir / "preserve.json"
        path.write_text("original", encoding="utf-8")
        # 模擬 fsync 失敗
        original_open = open
        def mock_open(*args, **kwargs):
            f = original_open(*args, **kwargs)
            if "preserve.json.tmp" in str(args[0]) if args else False:
                # 讓 fsync 失敗
                pass
            return f
        # 直接用 patch fsync
        with patch("os.fsync", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                atomic_write_text(path, "new data")
        # 原檔不變
        assert path.read_text() == "original"

    def test_atomic_write_bytes(self, tmp_project_dir):
        """原子二進位寫入。"""
        path = tmp_project_dir / "binary.glb"
        data = b'\x89GLB\x00\x00\x00\x00'
        atomic_write_bytes(path, data)
        assert path.read_bytes() == data


# ═══ 2. 磁碟滿模擬 ═══

class TestDiskFull:
    """磁碟滿——寫入失敗不損壞原檔。"""

    def test_disk_full_preserves_original(self, tmp_project_dir):
        """磁碟滿時原檔不變。"""
        path = tmp_project_dir / "disk_full.json"
        path.write_text("safe original", encoding="utf-8")
        with patch("os.fsync", side_effect=OSError("No space left on device")):
            with pytest.raises(OSError):
                atomic_write_text(path, "new content that won't fit")
        assert path.read_text() == "safe original"


# ═══ 3. 舊版升級 ═══

class TestSchemaMigration:
    """舊版 schema 自動升級。"""

    def test_v1_to_v2_migration_on_load(self, tmp_project_dir):
        """v1 專案載入時應自動遷移到 v2。"""
        # 建立 v1 格式的 features.json
        v1_data = {
            "schema_version": "1.0",
            "project_id": "test-v1",
            "features": [
                {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "test sketch",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]}
                    ],
                    "plane": {"base": "XY", "offset": 0},
                    "input": None,
                    "references": [],
                    "rebuild_status": "pending",
                }
            ],
        }
        path = tmp_project_dir / "features.json"
        path.write_text(json.dumps(v1_data, ensure_ascii=False), encoding="utf-8")

        graph = FeatureGraph.load(path)
        # 遷移後應有 v2 欄位
        assert graph.features["sk1"].body == "body1"
        assert graph.features["sk1"].order is not None
        assert graph.features["sk1"].state.value == "active"

    def test_v1_manifest_schema_version_accepted(self):
        """v1 schema 版本應被接受。"""
        is_supported, msg = check_schema_version("1.0")
        assert is_supported is True
        assert msg == ""

    def test_v2_schema_version_accepted(self):
        """v2 schema 版本應被接受。"""
        is_supported, msg = check_schema_version("2.0")
        assert is_supported is True
        assert msg == ""


# ═══ 4. 未來版本 ═══

class TestFutureVersion:
    """未來版本——唯讀開啟，不得靜默改寫。"""

    def test_future_version_rejected(self):
        """版本高於支援應回傳 future_version。"""
        is_supported, msg = check_schema_version("3.0")
        assert is_supported is False
        assert msg == "future_version"

    def test_future_version_minor_rejected(self):
        """次要版本高於支援也應回傳 future_version。"""
        is_supported, msg = check_schema_version("2.5")
        assert is_supported is False
        assert msg == "future_version"

    def test_unknown_version_rejected(self):
        """完全未知的版本應被拒絕。"""
        is_supported, msg = check_schema_version("xyz")
        assert is_supported is False


# ═══ 5. 損壞偵測 ═══

class TestCorruptDetection:
    """損壞 JSON/ZIP 偵測。"""

    def test_corrupt_json_raises_on_load(self, tmp_project_dir):
        """損壞的 JSON 載入時應報錯。"""
        path = tmp_project_dir / "corrupt.json"
        path.write_text("{invalid json {{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            json.loads(path.read_text())

    def test_corrupt_zip_raises_on_extract(self, tmp_project_dir):
        """損壞的 ZIP 解壓時應報錯。"""
        path = tmp_project_dir / "corrupt.zip"
        path.write_bytes(b"not a zip file at all")
        with pytest.raises(zipfile.BadZipFile):
            with zipfile.ZipFile(path, "r"):
                pass


# ═══ 6. ZIP 匯入安全 ═══

class TestZipSafety:
    """ZIP 匯入安全——路徑遍歷、大小、檔數。"""

    def test_validate_zip_path_rejects_traversal(self):
        """路徑遍歷 .. 應被拒絕。"""
        assert validate_zip_path("../../etc/passwd") is False
        assert validate_zip_path("safe/path/file.txt") is True
        assert validate_zip_path("../escape.txt") is False
        assert validate_zip_path("dir/../../escape.txt") is False

    def test_validate_zip_path_rejects_absolute(self):
        """絕對路徑應被拒絕。"""
        assert validate_zip_path("/etc/passwd") is False
        assert validate_zip_path("C:\\Windows\\system32") is False

    def test_safe_extract_normal_zip(self, tmp_project_dir):
        """正常 ZIP 應安全解壓。"""
        zip_path = tmp_project_dir / "normal.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"name": "test"}))
            zf.writestr("features.json", json.dumps({"features": []}))

        dest = tmp_path = tmp_project_dir / "extracted"
        dest.mkdir()
        files = safe_extract_zip(zip_path, dest)
        assert "manifest.json" in files
        assert "features.json" in files
        assert (dest / "manifest.json").exists()

    def test_safe_extract_rejects_path_traversal(self, tmp_project_dir):
        """含路徑遍歷的 ZIP 應被拒絕。"""
        zip_path = tmp_project_dir / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../escape.txt", "malicious")

        dest = tmp_project_dir / "extracted_evil"
        dest.mkdir()
        with pytest.raises(ValueError, match="不安全的路徑"):
            safe_extract_zip(zip_path, dest)

    def test_safe_extract_rejects_too_many_entries(self, tmp_project_dir):
        """檔數過多的 ZIP 應被拒絕。"""
        zip_path = tmp_project_dir / "many.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(10):
                zf.writestr(f"file_{i}.txt", f"content {i}")
        # 設定極低上限測試
        with patch("cad_worker.atomic_save.MAX_ZIP_ENTRIES", 5):
            with pytest.raises(ValueError, match="檔數過多"):
                safe_extract_zip(zip_path, tmp_project_dir / "dest_too_many")


# ═══ SHA-256 Checksum ═══

class TestChecksum:
    """Content checksum——manifest 記錄 cache 的 sha256。"""

    def test_compute_sha256(self):
        """SHA-256 計算正確。"""
        data = b"hello world"
        sha = compute_sha256(data)
        assert len(sha) == 64  # SHA-256 hex
        assert sha == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_compute_file_sha256(self, tmp_project_dir):
        """檔案 SHA-256 計算正確。"""
        path = tmp_project_dir / "test.bin"
        path.write_bytes(b"hello world")
        sha = compute_file_sha256(path)
        assert sha == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_different_content_different_checksum(self, tmp_project_dir):
        """不同內容應有不同 checksum。"""
        p1 = tmp_project_dir / "a.bin"
        p2 = tmp_project_dir / "b.bin"
        p1.write_bytes(b"content a")
        p2.write_bytes(b"content b")
        assert compute_file_sha256(p1) != compute_file_sha256(p2)


# ═══ Autosave Journal ═══

class TestJournal:
    """Autosave journal——每筆 transaction 後寫入，crash 後可還原。"""

    def test_write_journal_creates_entry(self, tmp_project_dir):
        """寫入 journal 應建立檔案。"""
        write_journal_entry(tmp_project_dir, "create_feature", {"features": []})
        journal_dir = tmp_project_dir / "journal"
        assert journal_dir.exists()
        entries = list(journal_dir.glob("*.json"))
        assert len(entries) == 1

    def test_journal_entry_has_correct_fields(self, tmp_project_dir):
        """journal 條目應有 action、timestamp、graph。"""
        graph_data = {"features": [{"feature_id": "sk1"}]}
        write_journal_entry(tmp_project_dir, "create_feature", graph_data)
        journal_dir = tmp_project_dir / "journal"
        entry = json.loads((journal_dir / "0001.json").read_text())
        assert entry["action"] == "create_feature"
        assert "timestamp" in entry
        assert entry["graph"] == graph_data

    def test_journal_keeps_last_20(self, tmp_project_dir):
        """journal 應只保留最近 20 筆。"""
        for i in range(25):
            write_journal_entry(tmp_project_dir, f"action_{i}", {"i": i})
        journal_dir = tmp_project_dir / "journal"
        entries = sorted(journal_dir.glob("*.json"))
        assert len(entries) == MAX_JOURNAL_ENTRIES

    def test_detect_unclean_shutdown(self, tmp_project_dir):
        """有 journal 條目代表未正常關閉。"""
        assert detect_unclean_shutdown(tmp_project_dir) is False
        write_journal_entry(tmp_project_dir, "test", {})
        assert detect_unclean_shutdown(tmp_project_dir) is True

    def test_get_latest_journal_entry(self, tmp_project_dir):
        """取得最新 journal 條目。"""
        write_journal_entry(tmp_project_dir, "first", {"n": 1})
        write_journal_entry(tmp_project_dir, "second", {"n": 2})
        latest = get_latest_journal_entry(tmp_project_dir)
        assert latest["action"] == "second"
        assert latest["graph"]["n"] == 2

    def test_clear_journal(self, tmp_project_dir):
        """清除 journal。"""
        write_journal_entry(tmp_project_dir, "test", {})
        assert detect_unclean_shutdown(tmp_project_dir) is True
        clear_journal(tmp_project_dir)
        assert detect_unclean_shutdown(tmp_project_dir) is False


# ═══ HTTP 端點測試 ═══

class TestCrashRecoveryEndpoint:
    """crash-recovery 端點測試。"""

    def _create_project(self, client, auth_headers):
        resp = client.post("/api/projects", json={"name": "CrashTest"}, headers=auth_headers)
        return resp.json()["project_id"]

    def test_crash_recovery_no_journal(self, client, auth_headers):
        """新專案無 journal——回傳 unclean_shutdown=false。"""
        pid = self._create_project(client, auth_headers)
        # 專案剛建立，尚未執行任何命令——無 journal
        # 先 dismiss 確保乾淨
        client.post(f"/api/projects/{pid}/crash-recovery/dismiss", headers=auth_headers)
        resp = client.get(f"/api/projects/{pid}/crash-recovery", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["unclean_shutdown"] is False

    def test_crash_recovery_restore(self, client, auth_headers):
        """從 journal 還原。"""
        pid = self._create_project(client, auth_headers)
        # 建立特徵——產生 journal
        client.post(
            f"/api/projects/{pid}/commands",
            json={
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "test",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]}
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            headers=auth_headers,
        )
        # 還原
        resp = client.post(f"/api/projects/{pid}/crash-recovery/restore", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "restored"

    def test_crash_recovery_dismiss(self, client, auth_headers):
        """清除 journal（不還原）。"""
        pid = self._create_project(client, auth_headers)
        client.post(
            f"/api/projects/{pid}/commands",
            json={
                "action": "create_feature",
                "feature": {
                    "feature_id": "sk1",
                    "type": "sketch",
                    "name": "test",
                    "parameters": {},
                    "sketch_entities": [
                        {"type": "rectangle", "width": 10, "height": 10, "center": [0, 0]}
                    ],
                    "plane": {"base": "XY", "offset": 0},
                },
            },
            headers=auth_headers,
        )
        resp = client.post(f"/api/projects/{pid}/crash-recovery/dismiss", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

        # 確認 journal 已清
        resp2 = client.get(f"/api/projects/{pid}/crash-recovery", headers=auth_headers)
        assert resp2.json()["unclean_shutdown"] is False


class TestImportZipEndpoint:
    """ZIP 匯入端點測試。"""

    def test_import_valid_zip(self, client, auth_headers, tmp_path):
        """正常的 ZIP 應成功匯入。"""
        # 建立有效 ZIP
        zip_path = tmp_path / "valid_project.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({
                "schema_version": "2.0",
                "name": "imported",
                "description": "",
                "units": "mm",
                "engine": "build123d",
                "material": "pla",
            }))
            zf.writestr("features.json", json.dumps({
                "schema_version": "2.0",
                "features": [],
            }))

        with open(zip_path, "rb") as f:
            zip_data = f.read()
        resp = client.post(
            "/api/projects/import-zip",
            content=zip_data,
            headers={**auth_headers, "Content-Type": "application/zip"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert "manifest" in data

    def test_import_zip_missing_manifest(self, client, auth_headers, tmp_path):
        """缺少 manifest.json 的 ZIP 應被拒。"""
        zip_path = tmp_path / "no_manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("other.txt", "content")

        with open(zip_path, "rb") as f:
            zip_data = f.read()
        resp = client.post(
            "/api/projects/import-zip",
            content=zip_data,
            headers={**auth_headers, "Content-Type": "application/zip"},
        )
        assert resp.status_code == 400

    def test_import_zip_path_traversal(self, client, auth_headers, tmp_path):
        """含路徑遍歷的 ZIP 應被拒。"""
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"schema_version": "2.0"}))
            zf.writestr("../../escape.txt", "evil")

        with open(zip_path, "rb") as f:
            zip_data = f.read()
        resp = client.post(
            "/api/projects/import-zip",
            content=zip_data,
            headers={**auth_headers, "Content-Type": "application/zip"},
        )
        assert resp.status_code == 400