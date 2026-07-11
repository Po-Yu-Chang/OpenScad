"""Atomic save utilities——「temp 檔→fsync→rename 取代」安全寫入。

WP1-5 檔案格式與復原強化：所有專案 JSON/BREP 寫入改用原子寫入，
確保 crash-during-save 不會留下半寫的損壞檔。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """原子寫入文字檔——temp 檔→fsync→rename 取代原檔。

    寫入流程：
    1. 寫入同目錄下的 .tmp 檔
    2. fsync 確保資料落盤
    3. os.replace 原子性地取代原檔（Windows 上等同 MoveFileEx MOVEFILE_REPLACE_EXISTING）
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        # 清理 temp 檔
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """原子寫入二進位檔——temp 檔→fsync→rename。"""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(path: Path, obj: Any, indent: int = 2) -> None:
    """原子寫入 JSON 檔。"""
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    atomic_write_text(path, text)


def compute_sha256(data: bytes) -> str:
    """計算 SHA-256 checksum。"""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(path: Path) -> str:
    """計算檔案的 SHA-256 checksum。"""
    return compute_sha256(path.read_bytes())


# ── Schema version safety ──

SUPPORTED_SCHEMA_VERSIONS = {"1.0", "2.0"}
LATEST_SCHEMA_VERSION = "2.0"


def check_schema_version(version: str) -> tuple[bool, str]:
    """檢查 schema 版本是否受支援。

    回傳 (is_supported, message)：
    - 版本受支援 → (True, "")
    - 版本高於支援 → (False, "future_version") → 唯讀開啟
    - 版本未知/低於支援 → (False, "unknown_version")
    """
    if version in SUPPORTED_SCHEMA_VERSIONS:
        return True, ""
    # 嘗判斷是否為未來版本
    try:
        major, minor = version.split(".")
        latest_major, latest_minor = LATEST_SCHEMA_VERSION.split(".")
        if int(major) > int(latest_major) or (
            int(major) == int(latest_major) and int(minor) > int(latest_minor)
        ):
            return False, "future_version"
    except (ValueError, IndexError):
        pass
    return False, "unknown_version"


# ── ZIP import safety ──

MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_ZIP_ENTRIES = 10000
MAX_EXTRACTED_SIZE = 500 * 1024 * 1024  # 500 MB total extracted


def validate_zip_path(entry_name: str) -> bool:
    """驗證 ZIP 內路徑是否安全——拒絕 .. 路徑遍歷。"""
    # 正規化路徑
    normalized = entry_name.replace("\\", "/")
    # 拒絕 .. 路徑遍歷
    if ".." in normalized.split("/"):
        return False
    # 拒絕絕對路徑（Unix / 開頭或 Windows drive letter）
    if normalized.startswith("/"):
        return False
    # 拒絕 Windows drive letter（如 C:）
    if len(normalized) > 1 and normalized[1] == ":":
        return False
    return True


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> list[str]:
    """安全解壓 ZIP——路徑遍歷防護、大小限制、檔數限制。

    回傳解壓的檔案路徑列表。
    失敗時 raise ValueError。
    """
    if not zip_path.exists():
        raise ValueError(f"ZIP 檔不存在：{zip_path}")

    # 檢查 ZIP 檔大小
    zip_size = zip_path.stat().st_size
    if zip_size > MAX_ZIP_SIZE:
        raise ValueError(f"ZIP 檔過大：{zip_size} bytes（上限 {MAX_ZIP_SIZE}）")

    extracted_files: list[str] = []
    total_extracted = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        entries = zf.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError(f"ZIP 內檔數過多：{len(entries)}（上限 {MAX_ZIP_ENTRIES}）")

        for entry in entries:
            # 路徑安全檢查
            if not validate_zip_path(entry.filename):
                raise ValueError(f"不安全的路徑：{entry.filename}")

            # 累計解壓大小
            total_extracted += entry.file_size
            if total_extracted > MAX_EXTRACTED_SIZE:
                raise ValueError(f"解壓總大小超限：{total_extracted} bytes（上限 {MAX_EXTRACTED_SIZE}）")

            # 解壓
            zf.extract(entry, dest_dir)
            extracted_files.append(entry.filename)

    return extracted_files


# ── Autosave journal ──

MAX_JOURNAL_ENTRIES = 20


def write_journal_entry(project_dir: Path, action: str, graph_snapshot: dict[str, Any]) -> None:
    """寫入 autosave journal 條目——每筆 committed transaction 後記錄。

    保留最近 MAX_JOURNAL_ENTRIES 筆，超過刪最舊。
    """
    journal_dir = project_dir / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone
    entry = {
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "graph": graph_snapshot,
    }

    # 找下一個編號
    existing = sorted(journal_dir.glob("*.json"))
    next_num = 1
    if existing:
        next_num = int(existing[-1].stem) + 1

    # 寫入（原子）
    journal_path = journal_dir / f"{next_num:04d}.json"
    atomic_write_json(journal_path, entry)

    # 清理超過上限的舊條目
    all_entries = sorted(journal_dir.glob("*.json"))
    if len(all_entries) > MAX_JOURNAL_ENTRIES:
        for f in all_entries[:len(all_entries) - MAX_JOURNAL_ENTRIES]:
            f.unlink()


def detect_unclean_shutdown(project_dir: Path) -> bool:
    """偵測上次是否未正常關閉——檢查 journal 是否有未清理的條目。

    正常關閉時應清除 journal；如果 journal 有條目代表上次未正常關閉。
    """
    journal_dir = project_dir / "journal"
    if not journal_dir.exists():
        return False
    entries = list(journal_dir.glob("*.json"))
    return len(entries) > 0


def get_latest_journal_entry(project_dir: Path) -> dict[str, Any] | None:
    """取得最新的 journal 條目（用於 crash 後還原提示）。"""
    journal_dir = project_dir / "journal"
    if not journal_dir.exists():
        return None
    entries = sorted(journal_dir.glob("*.json"))
    if not entries:
        return None
    return json.loads(entries[-1].read_text(encoding="utf-8"))


def clear_journal(project_dir: Path) -> None:
    """清除 journal——正常關閉時呼叫。"""
    journal_dir = project_dir / "journal"
    if journal_dir.exists():
        for f in journal_dir.glob("*.json"):
            f.unlink()