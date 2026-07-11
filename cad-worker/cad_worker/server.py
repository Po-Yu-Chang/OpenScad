"""OpenCad CAD Worker — FastAPI Server。

以獨立程序運行，透過 localhost HTTP（FastAPI）與主程式通訊。
只監聽 127.0.0.1，使用隨機工作階段 Token。

API 端點：
  POST /api/projects                  — 建立專案
  POST /api/projects/{id}/commands    — 套用命令
  POST /api/projects/{id}/rebuild     — 重建模型
  POST /api/projects/{id}/validate    — 驗證模型
  POST /api/projects/{id}/exports     — 匯出模型
  GET  /api/projects/{id}/preview.glb — 取得預覽
  GET  /api/projects/{id}/events      — 重建進度串流（SSE）
  GET  /api/health                     — 健康檢查
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
import zipfile
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from .feature_graph import FeatureGraph, Feature, FeatureType, ParameterValue, ReorderDependencyViolationError
from .validators import GeometryValidator, ValidationReport
from .exporters import ExportManager, GlbExporter
from .sketch_solver import solve as solve_sketch, Constraint, CONSTRAINT_TYPES

# WP1-0R 地雷 #17: FreeCAD Document 非線程安全——rebuild 必須全域序列化。
# 兩個引擎都鎖（build123d 無害且簡單）。
_rebuild_lock = asyncio.Lock()

# WP1-0R: 引擎狀態——記錄請求的引擎與實際生效的引擎
_ENGINE_REQUESTED = os.environ.get("OPENCAD_ENGINE", "build123d").lower()
from .atomic_save import (
    atomic_write_json, atomic_write_bytes,
    compute_file_sha256,
    check_schema_version, write_journal_entry, detect_unclean_shutdown,
    get_latest_journal_entry, clear_journal,
    safe_extract_zip,
)

# 隋機工作階段 Token（避免其他本機程序任意呼叫）
SESSION_TOKEN = secrets.token_hex(16)

# 專案儲存目錄——持久化，重啟後仍可讀回
WORK_DIR = Path(os.environ.get("OPENCAD_WORK_DIR", Path.home() / ".opencad" / "worker"))

# Token 檔案路徑（由主程式透過環境變數指定）
_TOKEN_FILE = os.environ.get("OPENCAD_TOKEN_FILE")


def _write_token_file() -> None:
    """將工作階段 Token 寫入檔案，供主程式（Avalonia）讀取。"""
    if _TOKEN_FILE:
        token_path = Path(_TOKEN_FILE)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(SESSION_TOKEN, encoding="utf-8")


_write_token_file()

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # startup: WP1-0R: Explicitly check engine availability at startup
    # This will fail fast if OPENCAD_ENGINE=freecad but FreeCAD is unavailable
    try:
        _get_adapter()
    except ImportError as e:
        print(f"Startup failed: {e}")
        raise
    yield
    # shutdown: 清除所有專案的 journal——標記為正常關閉
    for proj_id, proj in projects.items():
        try:
            clear_journal(proj["dir"])
        except Exception:
            pass
    # WP-H2: 清理 temp 目錄
    _cleanup_temp_dir()

app = FastAPI(
    title="OpenCad CAD Worker",
    version="0.1.0",
    description="Python 幾何引擎 Worker（build123d / OCCT）",
    lifespan=_lifespan,
)


@app.middleware("http")
async def _origin_guard(request: Request, call_next):
    """WP-H2: 嚴格 Origin 驗證——跨站 Origin 一律 403（無 Origin 的本機請求放行）。"""
    origin = request.headers.get("Origin")
    if origin and not _is_allowed_origin(origin):
        return JSONResponse(status_code=403, content={"detail": "不允許的 Origin"})
    return await call_next(request)

# 伺服 3D Viewer 靜態檔案（viewer.html＋Three.js assets）。
# 讓 viewer 與 preview.glb 同源，避免 file:// 下 ES module 與 fetch 的 CORS 限制。
_VIEWER_DIR = os.environ.get("OPENCAD_VIEWER_DIR")
if _VIEWER_DIR and Path(_VIEWER_DIR).is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/viewer", StaticFiles(directory=_VIEWER_DIR, html=True), name="viewer")

# 全域狀態
projects: dict[str, dict[str, Any]] = {}  # project_id -> {graph, part, dir, manifest}


def _load_existing_projects() -> None:
    """啟動時從磁碟載入既有專案，實現「關閉後重新開啟仍能繼續修改」。"""
    if not WORK_DIR.exists():
        return
    for proj_dir in WORK_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        manifest_path = proj_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_id = manifest.get("project_id", proj_dir.name)
            graph = FeatureGraph()
            features_path = proj_dir / "features.json"
            if features_path.exists():
                graph = FeatureGraph.load(features_path)
            # 還原目前版本號——否則重啟後 undo 會誤判「已是最早版本」
            current_rev = 0
            rev_dir = proj_dir / "revisions"
            if rev_dir.exists():
                rev_files = sorted(rev_dir.glob("*.json"))
                if rev_files:
                    current_rev = int(rev_files[-1].stem)

            projects[project_id] = {
                "graph": graph,
                "part": None,  # BREP 需重建才有
                "dir": proj_dir,
                "manifest": manifest,
                "_current_rev": current_rev,
                "mesh_revision": 0,
                "display_map": None,
            }
        except Exception:
            pass  # 跳過損壞的專案目錄


_load_existing_projects()


# ─── 認證 ───

def verify_token(x_session_token: str = Header(None, alias="X-Session-Token")) -> None:
    """驗證工作階段 Token（WP-H2: token 僅走 header，不記錄到 log）。"""
    if x_session_token != SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="無效的工作階段 Token")


# ─── WP-H2: 安全強化 ───

# Origin 白名單——只允許 WebView2 同源 + app 自身
_ALLOWED_ORIGINS: set[str] = set()
_ALLOWED_ORIGIN_PATTERNS = [
    "http://localhost",
    "http://127.0.0.1",
    "https://localhost",
    "https://127.0.0.1",
    # WebView2 使用 file:// 或 ms-appx:// 等
    "file://",
    "ms-appx:",
    "ms-appx-web:",
]


def _is_allowed_origin(origin: str | None) -> bool:
    """WP-H2: 嚴格 Origin 驗證。"""
    if not origin:
        return True  # 非 browser 請求（如 TestClient）不帶 Origin
    for pattern in _ALLOWED_ORIGIN_PATTERNS:
        if origin.startswith(pattern):
            return True
    return False


def _canonicalize_path(path: Path) -> Path:
    """WP-H2: 路徑正規化——拒絕 symlink 逃逸。

    確保所有路徑都在 WORK_DIR 之下，拒絕 ../ 或 symlink 逃逸。
    """
    try:
        resolved = path.resolve()
        work_resolved = WORK_DIR.resolve()
        # 確保路徑在 WORK_DIR 下
        if not str(resolved).startswith(str(work_resolved)):
            raise HTTPException(403, "路徑逃逸：拒絕存取 WORK_DIR 外的路徑")
        return resolved
    except OSError:
        raise HTTPException(403, "路徑解析失敗")


# WP-H2: 檔案大小上限
MAX_IMPORT_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_STEP_FACES = 500_000  # STEP 面數上限
MAX_TRIANGLE_COUNT = 2_000_000  # 三角形數上限

# WP-H2: Worker 資源配額
REBUILD_TIMEOUT_SECONDS = 60  # 重建超時（秒）
MAX_REBUILD_MEMORY_MB = 1024  # 重建記憶體上限（MB）


def _cleanup_temp_dir() -> None:
    """WP-H2: 清理 Worker temp 目錄。"""
    import tempfile
    import glob
    # 清理 WORK_DIR 下的 temp 子目錄
    temp_dir = WORK_DIR / "tmp"
    if temp_dir.exists():
        for item in temp_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    import shutil
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass


# ─── 請求模型 ───

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    units: str = "mm"
    engine: str = "build123d"
    material: str = "pla"


class ApplyCommandRequest(BaseModel):
    action: str
    document_id: str | None = None
    target_feature_id: str | None = None
    feature: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    preserve: list[str] = []
    export_format: str = "all"
    standard_parts: dict[str, Any] | None = None
    sketch_entities: list[dict[str, Any]] | None = None
    plane: dict[str, Any] | None = None
    constraints: list[dict[str, Any]] | None = None
    reasoning: str = ""


class ExportRequest(BaseModel):
    format: str = "all"  # step / stl / 3mf / glb / png / all
    filename: str = "model"


# ─── API 端點 ───

@app.get("/api/health")
async def health() -> dict[str, Any]:
    """健康檢查。"""
    # WP1-0R: 回傳實際生效引擎與請求引擎
    engine_requested = os.environ.get("OPENCAD_ENGINE", "build123d").lower()
    engine_actual = engine_requested
    if engine_requested == "freecad":
        from .adapters.freecad_adapter import FREECAD_AVAILABLE
        if not FREECAD_AVAILABLE:
            engine_actual = "unavailable"
    else:
        engine_actual = "build123d"
    return {
        "status": "ok" if engine_actual != "unavailable" else "degraded",
        "version": "0.1.0",
        "build123d_available": _check_build123d(),
        "engine": engine_actual,
        "engine_requested": engine_requested,
    }


@app.post("/api/projects")
async def create_project(req: CreateProjectRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    """建立專案。"""
    project_id = str(uuid.uuid4())
    project_dir = WORK_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    graph = FeatureGraph()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "1.0",
        "project_id": project_id,
        "name": req.name,
        "description": req.description,
        "units": req.units,
        "engine": req.engine,
        "material": req.material,
        "created_at": now,
        "modified_at": now,
    }
    atomic_write_json(project_dir / "manifest.json", manifest)

    projects[project_id] = {
        "graph": graph,
        "part": None,
        "dir": project_dir,
        "manifest": manifest,
        "mesh_revision": 0,
        "display_map": None,
    }
    return {"project_id": project_id, "manifest": manifest}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """取得專案資訊。"""
    proj = _get_project(project_id)
    return {
        "manifest": proj["manifest"],
        "features": proj["graph"].to_dict(),
    }


@app.post("/api/projects/{project_id}/commands")
async def apply_command(project_id: str, req: ApplyCommandRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    """套用受控命令。"""
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]

    # Python 端命令驗證——與 C# 端 CommandValidator 對稱
    from .validators.command_validator import CommandValidator
    cmd_dict = req.model_dump()
    val_errors = CommandValidator.validate(cmd_dict)
    if val_errors:
        raise HTTPException(400, "; ".join(val_errors))

    if req.action == "create_feature":
        if req.feature is None:
            raise HTTPException(400, "create_feature 需要 feature 欄位")
        feature = Feature.from_dict(req.feature)
        graph.add_feature(feature)
        _save_revision(proj, req)
        return {"status": "created", "feature_id": feature.feature_id}

    elif req.action == "update_feature":
        if req.target_feature_id is None or (
            req.parameters is None and req.standard_parts is None and
            req.sketch_entities is None and req.plane is None and
            req.constraints is None
        ):
            raise HTTPException(400, "update_feature 需要 target_feature_id 和 parameters、standard_parts、sketch_entities、plane 或 constraints")
        feature = graph.update_feature(
            req.target_feature_id, req.parameters or {}, req.standard_parts, req.sketch_entities, req.plane, req.constraints,
        )
        _save_revision(proj, req)
        return {"status": "updated", "feature_id": feature.feature_id}

    elif req.action == "delete_feature":
        if req.target_feature_id is None:
            raise HTTPException(400, "delete_feature 需要 target_feature_id")
        downstream = graph.delete_feature(req.target_feature_id)
        if downstream:
            # 有依賴者——禁止靜默刪除
            return {
                "status": "has_dependencies",
                "target_feature_id": req.target_feature_id,
                "affected_features": downstream,
                "message": "此特徵被其他特徵依賴，請確認是否連同刪除",
            }
        _save_revision(proj, req)
        return {"status": "deleted", "feature_id": req.target_feature_id}

    elif req.action == "delete_feature_recursive":
        if req.target_feature_id is None:
            raise HTTPException(400, "delete_feature_recursive 需要 target_feature_id")
        deleted = graph.delete_feature_recursive(req.target_feature_id)
        _save_revision(proj, req)
        return {"status": "deleted", "deleted_features": deleted}

    elif req.action == "rebuild":
        return await _rebuild(project_id, proj)

    elif req.action == "validate":
        return await _validate(project_id, proj)

    elif req.action == "export":
        return await _export(project_id, proj, req.export_format or "all")

    elif req.action == "set_material":
        material = req.parameters or {}
        material_name = material.get("material")
        if not material_name:
            raise HTTPException(400, "set_material 需要 parameters.material")
        from .standard_parts import get_material_density
        get_material_density(material_name)  # 驗證材質存在
        proj["manifest"]["material"] = material_name.lower().replace(" ", "_")
        from datetime import datetime, timezone
        proj["manifest"]["modified_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(proj["dir"] / "manifest.json", proj["manifest"])
        return {"status": "material_set", "material": material_name}

    # ── v2 commands ──
    # 地雷 #14：這些命令會改 graph，必須走 staging clone→套用→重建驗證→commit；
    # 重建失敗時正式 graph 完全不變。

    elif req.action == "suppress_feature":
        if req.target_feature_id is None:
            raise HTTPException(400, "suppress_feature 需要 target_feature_id")
        result = await _commit_graph_mutation(
            proj, req, lambda g: {"orphaned": g.suppress_feature(req.target_feature_id)})
        return {"status": "suppressed", "feature_id": req.target_feature_id, **result}

    elif req.action == "unsuppress_feature":
        if req.target_feature_id is None:
            raise HTTPException(400, "unsuppress_feature 需要 target_feature_id")
        result = await _commit_graph_mutation(
            proj, req, lambda g: {"restored": g.unsuppress_feature(req.target_feature_id)})
        return {"status": "unsuppressed", "feature_id": req.target_feature_id, **result}

    elif req.action == "reorder_feature":
        if req.target_feature_id is None:
            raise HTTPException(400, "reorder_feature 需要 target_feature_id")
        new_order = req.parameters.get("new_order") if req.parameters else None
        if new_order is None:
            raise HTTPException(400, "reorder_feature 需要 parameters.new_order")
        await _commit_graph_mutation(
            proj, req, lambda g: g.reorder_feature(req.target_feature_id, int(new_order)))
        return {"status": "reordered", "feature_id": req.target_feature_id, "new_order": new_order}

    elif req.action == "set_rollback":
        rollback_pos = req.parameters.get("rollback_position") if req.parameters else None
        if rollback_pos is not None:
            rollback_pos = int(rollback_pos)
        await _commit_graph_mutation(proj, req, lambda g: g.set_rollback(rollback_pos))
        return {"status": "rollback_set", "rollback_position": rollback_pos}

    else:
        raise HTTPException(400, f"未知的 action: {req.action}")


class ApplyPlanRequest(BaseModel):
    """批量命令交易請求——所有命令在 staging graph 上試跑，
    重建成功才 commit；任一步驟失敗則回滾，原圖不受影響。"""
    commands: list[ApplyCommandRequest]
    plan_label: str = ""


@app.post("/api/projects/{project_id}/apply_plan")
async def apply_plan(project_id: str, req: ApplyPlanRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    """交易式套用多個命令（staging + rollback）。

    流程：
    1. 複製目前 graph → staging
    2. 在 staging 上依序執行所有 commands
    3. 在 staging 上重建
    4. 若任一步驟或重建失敗 → 回滾（原 graph 不變），回傳錯誤
    5. 若全部成功 → commit：取代原 graph、儲存單一 revision、回傳重建結果

    這確保 LLM 計畫要嘛完整套用，要完全不套用——不會留下半成品。
    """
    proj = _get_project(project_id)
    original_graph: FeatureGraph = proj["graph"]

    # 1. 複製 → staging
    staging = original_graph.clone()
    applied_features: list[str] = []

    # 2. 在 staging 上依序執行
    for i, cmd in enumerate(req.commands):
        try:
            if cmd.action == "create_feature":
                if cmd.feature is None:
                    return _plan_error(f"第 {i+1} 步 create_feature 缺少 feature 欄位", applied_features)
                feature = Feature.from_dict(cmd.feature)
                staging.add_feature(feature)
                applied_features.append(feature.feature_id)

            elif cmd.action == "update_feature":
                if cmd.target_feature_id is None:
                    return _plan_error(f"第 {i+1} 步 update_feature 缺少 target_feature_id", applied_features)
                staging.update_feature(
                    cmd.target_feature_id, cmd.parameters or {},
                    cmd.standard_parts, cmd.sketch_entities, cmd.plane, cmd.constraints,
                )

            elif cmd.action == "delete_feature":
                if cmd.target_feature_id is None:
                    return _plan_error(f"第 {i+1} 步 delete_feature 缺少 target_feature_id", applied_features)
                downstream = staging.delete_feature(cmd.target_feature_id)
                if downstream:
                    return _plan_error(
                        f"第 {i+1} 步：特徵 '{cmd.target_feature_id}' 被其他特徵依賴（{downstream}）",
                        applied_features,
                    )

            elif cmd.action == "delete_feature_recursive":
                if cmd.target_feature_id is None:
                    return _plan_error(f"第 {i+1} 步 delete_feature_recursive 缺少 target_feature_id", applied_features)
                staging.delete_feature_recursive(cmd.target_feature_id)

            elif cmd.action == "set_material":
                material = cmd.parameters or {}
                material_name = material.get("material")
                if not material_name:
                    return _plan_error(f"第 {i+1} 步 set_material 缺少 parameters.material", applied_features)
                from .standard_parts import get_material_density
                get_material_density(material_name)  # 驗證材質存在

            else:
                return _plan_error(f"第 {i+1} 步：未知的 action '{cmd.action}'", applied_features)

        except Exception as e:
            return _plan_error(f"第 {i+1} 步失敗：{e}", applied_features)

    # 3. 在 staging 上重建
    try:
        adapter = _get_adapter()
        build_result = adapter.build_with_trace(staging)
        part = build_result.part
    except Exception as e:
        return _plan_error(f"重建失敗：{e}", applied_features, error_code=_classify_error(e))

    # 4. Commit——全部成功才取代原 graph
    proj["graph"] = staging
    proj["part"] = part

    # 儲存 features.json
    staging.save(proj["dir"] / "features.json")

    # 儲存單一 revision（整個 plan 一個 undo 步驟）
    _save_plan_revision(proj, req.plan_label or f"apply_plan ({len(req.commands)} commands)")

    # 質量屬性
    material = proj.get("manifest", {}).get("material", "pla")
    volume_mm3 = float(part.volume) if part else 0.0
    area_mm2 = float(part.area) if part else 0.0
    bounding_box = part.bounding_box() if part else None
    from .standard_parts import calculate_mass
    mass_g = calculate_mass(volume_mm3, material) if volume_mm3 > 0 else 0.0

    return {
        "status": "success",
        "applied_count": len(req.commands),
        "applied_features": applied_features,
        "mass_properties": {
            "volume_mm3": round(volume_mm3, 2),
            "surface_area_mm2": round(area_mm2, 2),
            "mass_g": round(mass_g, 2),
            "material": material,
            "density_g_cm3": round(mass_g / (volume_mm3 / 1000.0), 4) if volume_mm3 > 0 else 0.0,
            "bounding_box_mm": {
                "min_x": round(bounding_box.min.X, 2) if bounding_box else 0,
                "min_y": round(bounding_box.min.Y, 2) if bounding_box else 0,
                "min_z": round(bounding_box.min.Z, 2) if bounding_box else 0,
                "max_x": round(bounding_box.max.X, 2) if bounding_box else 0,
                "max_y": round(bounding_box.max.Y, 2) if bounding_box else 0,
                "max_z": round(bounding_box.max.Z, 2) if bounding_box else 0,
                "size_x": round(bounding_box.size.X, 2) if bounding_box else 0,
                "size_y": round(bounding_box.size.Y, 2) if bounding_box else 0,
                "size_z": round(bounding_box.size.Z, 2) if bounding_box else 0,
            },
        },
    }


async def _commit_graph_mutation(proj: dict[str, Any], req: ApplyCommandRequest, mutate) -> dict[str, Any]:
    """地雷 #14：v2 圖變更的 staging 交易。

    clone→套用 mutate→重建驗證→成功才 commit（graph+part+features.json+revision）；
    任一步失敗丟 HTTPException，正式 graph 完全不變。
    mutate(staging) 的回傳值（dict 或 None）併入呼叫端回應。
    """
    graph: FeatureGraph = proj["graph"]
    staging = graph.clone()
    try:
        extra = mutate(staging)
    except ReorderDependencyViolationError as e:
        raise HTTPException(400, f"REORDER_DEPENDENCY_VIOLATION: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    # staging 重建驗證（CPU-bound 丟 thread，事件迴圈不凍結）
    # WP1-0R 地雷 #17: 全域序列化——FreeCAD Document 非線程安全
    try:
        _rebuild_reference_geometry(staging, {})
        adapter = _get_adapter()
        async with _rebuild_lock:
            build_result = await asyncio.to_thread(adapter.build_with_trace, staging)
    except ImportError as e:
        raise HTTPException(503, f"CAD 引擎未安裝: {e}")
    except Exception as e:
        raise HTTPException(400, f"{_classify_error(e)}: 變更會導致重建失敗，已回滾：{e}")

    # commit
    proj["graph"] = staging
    proj["part"] = build_result.part
    staging.save(proj["dir"] / "features.json")
    _save_revision(proj, req)
    return extra if isinstance(extra, dict) else {}


def _plan_error(message: str, applied_features: list[str], error_code: str = "PLAN_FAILED") -> JSONResponse:
    """回傳 plan 失敗回應——原 graph 不受影響（staging 被丟棄）。"""
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": error_code,
            "engine_message": message,
            "applied_features": applied_features,  # 已在 staging 嘗試過的特徵（未被 commit）
        },
    )


def _save_plan_revision(proj: dict[str, Any], label: str) -> None:
    """為 apply_plan/reset 儲存單一 revision（一個 plan = 一個 undo 步驟）。"""
    _write_revision_snapshot(proj, {"action": "apply_plan", "label": label}, "apply_plan")


@app.post("/api/projects/{project_id}/reset")
async def reset_project(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """原子性清除所有特徵（Clear All）——單一交易，一個 undo 步驟。

    不同於逐一刪除，這會建立一個空白 graph 的 revision，
    讓使用者可以一次 Undo 回到清除前的完整狀態。
    """
    proj = _get_project(project_id)
    proj["graph"] = FeatureGraph()
    proj["part"] = None

    # 清除舊的 mesh cache——否則 export/preview 會回傳清除前的舊幾何
    proj["display_map"] = None
    gen_dir = proj["dir"] / "generated"
    for stale in ("model.glb", "display_map.json"):
        try:
            (gen_dir / stale).unlink(missing_ok=True)
        except OSError:
            pass

    # 儲存 features.json（空白）
    proj["graph"].save(proj["dir"] / "features.json")

    # 儲存 revision（一個 undo 步驟回到清除前）
    _save_plan_revision(proj, "reset_project (clear all)")

    return {"status": "cleared", "feature_count": 0}


@app.post("/api/projects/{project_id}/rebuild")
async def rebuild(project_id: str, dry_run: bool = False, _: None = Depends(verify_token)) -> dict[str, Any]:
    """重建模型。dry_run=true 時只試跑不 commit（WP-H1 rebuild_staging 工具）。

    WP-H2: 重建有超時保護——超時則 rollback 到上一版本，不污染 production version。
    """
    proj = _get_project(project_id)
    if dry_run:
        return await _rebuild_dry_run(project_id, proj)

    # WP-H2: 保存重建前的 graph 快照——超時 rollback 用
    import copy
    graph_snapshot = copy.deepcopy(proj["graph"].to_dict())
    part_snapshot = proj.get("part")
    mesh_rev_snapshot = proj.get("mesh_revision", 0)
    # display_map 只會被整包取代、不會就地修改——保留參考即可，免去大型深拷貝
    display_map_snapshot = proj.get("display_map")

    try:
        result = await asyncio.wait_for(
            _rebuild(project_id, proj),
            timeout=REBUILD_TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        # WP-H2: 超時 rollback——graph 不變，確保不污染 production version
        proj["graph"] = FeatureGraph.from_dict(graph_snapshot)
        proj["part"] = part_snapshot
        proj["mesh_revision"] = mesh_rev_snapshot
        proj["display_map"] = display_map_snapshot
        raise HTTPException(
            408,
            f"重建超時（{REBUILD_TIMEOUT_SECONDS}秒），已 rollback 到上一版本",
        )


# 每類型的參數名稱提示（供 LLM capability payload；型別軸以 schema enum 為準，
# 不在 enum 裡的 key 不會出現在 catalog）
_FEATURE_PARAM_HINTS: dict[str, list[str]] = {
    "sketch": ["sketch_entities", "plane", "constraints"],
    "pad": ["length", "taper_deg"],
    "pocket": ["depth", "through_all"],
    "hole": ["diameter", "depth", "through_all", "positions", "hole_type"],
    "fillet": ["radius", "edges", "exclude_holes"],
    "chamfer": ["length", "edges", "exclude_holes"],
    "shell": ["thickness"],
    "revolve": ["angle"],
    "linear_pattern": ["count", "spacing_mm", "direction"],
    "circular_pattern": ["count", "angle_deg"],
    "draft": ["angle_deg", "face_selector", "direction"],
    "rib": ["thickness", "direction", "sketch_id"],
    "thin": ["length", "thickness"],
    "variable_fillet": ["radii", "edge_selector", "radius"],
    "countersink": ["diameter", "countersink_diameter", "countersink_angle_deg", "positions"],
    "cosmetic_thread": ["diameter", "pitch", "depth", "positions"],
}


@app.get("/api/capability")
async def get_capability(_: None = Depends(verify_token)) -> dict[str, Any]:
    """Capability payload（WP-H1）——LLM 每次呼叫必帶的引擎能力資訊。

    feature 類型清單從 schema 的 type enum 生成，禁手寫類型清單。
    """
    # 特徵類型清單的唯一來源是 feature.schema.json 的 type enum——
    # schema 沒定義的類型不得出現在 catalog（禁手寫 fallback 清單）。
    # 每類型的參數提示 schema 沒有逐型定義，維護在 _FEATURE_PARAM_HINTS。
    # 打包環境可用 OPENCAD_SCHEMAS_DIR 指定 schemas 目錄。
    schemas_dir = Path(os.environ.get(
        "OPENCAD_SCHEMAS_DIR",
        Path(__file__).parent.parent.parent / "schemas",
    ))
    schema_path = schemas_dir / "feature.schema.json"
    type_enum: list[str] = []
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
        type_enum = (
            schema.get("definitions", {})
            .get("feature", {})
            .get("properties", {})
            .get("type", {})
            .get("enum", [])
        )
    if not type_enum:
        raise HTTPException(
            500,
            f"feature.schema.json 不存在或缺 definitions.feature.properties.type.enum：{schema_path}"
            "（可用 OPENCAD_SCHEMAS_DIR 環境變數指定 schemas 目錄）",
        )
    catalog = [
        {"type": t, "parameters": _FEATURE_PARAM_HINTS.get(t, [])}
        for t in type_enum
    ]
    # Unsupported features (LLM 拒絕規則)
    unsupported = ["thread", "knit", "trim_surface", "thicken", "delete_face", "helical_gear"]
    return {
        "schema_version": "1.0",
        "engine_version": "opencad-worker-1.0",
        "feature_catalog": catalog,
        "unsupported_features": unsupported,
        "tools": [
            "inspect_document",
            "query_feature_catalog",
            "propose_transaction",
            "validate_transaction",
            "rebuild_staging",
            "request_user_confirmation",
        ],
    }


@app.post("/api/projects/{project_id}/validate")
async def validate(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """驗證模型。"""
    proj = _get_project(project_id)
    return await _validate(project_id, proj)


@app.post("/api/projects/{project_id}/exports")
async def export_model(project_id: str, req: ExportRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    """匯出模型。"""
    proj = _get_project(project_id)
    return await _export(project_id, proj, req.format, req.filename)


# WP-H2: 預簽 token——給無法帶 header 的 WebView GLTFLoader 使用
# 每個預簽 token 只用一次且短時效（60秒），不會長期暴露在 URL 中
import time as _time
_presigned_tokens: dict[str, float] = {}  # token -> expiry timestamp
_PRESIGNED_TTL = 60  # 秒


def _generate_presigned_token() -> str:
    """WP-H2: 產生短時效預簽 token（60 秒有效）。"""
    t = secrets.token_hex(16)
    _presigned_tokens[t] = _time.time() + _PRESIGNED_TTL
    return t


def _verify_presigned_token(token: str) -> bool:
    """WP-H2: 驗證預簽 token（用後即棄）。"""
    expiry = _presigned_tokens.get(token)
    if expiry is None:
        return False
    # 過期 token 清理
    if _time.time() > expiry:
        del _presigned_tokens[token]
        return False
    # 用後即棄
    del _presigned_tokens[token]
    return True


@app.post("/api/presign")
async def presign_url(_: None = Depends(verify_token)) -> dict[str, str]:
    """WP-H2: 取得短時效預簽 token（取代 URL 中的靜態 token）。

    前端用 X-Session-Token 呼叫此端點，取得預簽 token 後附加到 GLB/display_map URL。
    預簽 token 60 秨有效、用後即棄，不會長期暴露在 URL 中。
    """
    return {"presigned_token": _generate_presigned_token()}


@app.get("/api/projects/{project_id}/preview.glb")
async def get_preview(request: Request, project_id: str, token: str = "") -> Any:
    """取得 GLB 預覽。

    WP-H2: 認證方式——X-Session-Token header 或短時效預簽 ?token=（用後即棄）。
    """
    header_token = request.headers.get("X-Session-Token", "")
    if header_token != SESSION_TOKEN and not _verify_presigned_token(token):
        raise HTTPException(status_code=401, detail="無效的工作階段 Token")
    proj = _get_project(project_id)
    glb_path = proj["dir"] / "generated" / "model.glb"
    if not glb_path.exists():
        raise HTTPException(404, "預覽尚未生成，請先重建模型")
    return FileResponse(str(glb_path), media_type="model/gltf-binary")


@app.get("/api/projects/{project_id}/display_map")
async def get_display_map(request: Request, project_id: str, token: str = "") -> Any:
    """取得 display_map（面/邊拓撲對應表，供 viewer 精確 picking）。

    WP-H2: 認證方式——X-Session-Token header 或短時效預簽 ?token=（用後即棄）。
    """
    header_token = request.headers.get("X-Session-Token", "")
    if header_token != SESSION_TOKEN and not _verify_presigned_token(token):
        raise HTTPException(status_code=401, detail="無效的工作階段 Token")
    proj = _get_project(project_id)
    display_map = proj.get("display_map")
    if display_map is None:
        # 嘗試從磁碟讀回
        map_path = proj["dir"] / "generated" / "display_map.json"
        if map_path.exists():
            display_map = json.loads(map_path.read_text(encoding="utf-8"))
            proj["display_map"] = display_map
        else:
            raise HTTPException(404, "display_map 尚未生成，請先重建模型")
    return display_map


@app.get("/api/projects/{project_id}/events")
async def events(request: Request, project_id: str, _: None = Depends(verify_token)) -> StreamingResponse:
    """重建進度串流（SSE）。逐特徵回報進度與狀態。"""
    proj = _get_project(project_id)

    async def event_stream():
        graph: FeatureGraph = proj["graph"]
        order = graph.topological_sort()
        for i, fid in enumerate(order):
            feature = graph.get_feature(fid)
            if feature:
                yield f"data: {json.dumps({'feature_id': fid, 'name': feature.name, 'index': i + 1, 'total': len(order)})}\n\n"
        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── 專案列表 ───

@app.get("/api/projects")
async def list_projects(_: None = Depends(verify_token)) -> dict[str, Any]:
    """列出所有已載入專案。"""
    result = []
    for pid, proj in projects.items():
        manifest = proj.get("manifest", {})
        graph: FeatureGraph = proj["graph"]
        result.append({
            "project_id": pid,
            "name": manifest.get("name", pid),
            "modified_at": manifest.get("modified_at", ""),
            "feature_count": len(graph.features),
        })
    return {"projects": result}


# ─── 版本紀錄與 Undo/Redo ───

MAX_REVISIONS = 50

def _save_revision(proj: dict[str, Any], req: ApplyCommandRequest | None = None) -> None:
    """在成功的命令後儲存 graph 快照到 revisions/ 目錄。"""
    command = {
        "action": req.action,
        "target_feature_id": req.target_feature_id,
        "parameters": req.parameters,
        "standard_parts": req.standard_parts,
    } if req else None
    _write_revision_snapshot(proj, command, req.action if req else "unknown")


def _write_revision_snapshot(proj: dict[str, Any], command: dict[str, Any] | None, journal_action: str) -> None:
    """共用 revision 快照寫入：截斷 redo 分支→編號→原子寫入→修剪→manifest→journal。

    _save_revision（單一命令）與 _save_plan_revision（apply_plan/reset）都走這裡，
    確保 autosave journal 永遠與最新 revision 同步（WP1-5 crash recovery 依賴這點）。
    """
    proj_dir: Path = proj["dir"]
    rev_dir = proj_dir / "revisions"
    rev_dir.mkdir(parents=True, exist_ok=True)

    # undo 後有新命令——捨棄 redo 分支（刪除目前的 revision 之後的所有檔案）
    current_rev = proj.get("_current_rev", 0)
    if current_rev > 0:
        for f in rev_dir.glob("*.json"):
            if int(f.stem) > current_rev:
                f.unlink()

    existing = sorted(rev_dir.glob("*.json"))
    next_num = int(existing[-1].stem) + 1 if existing else 1

    from datetime import datetime, timezone
    snapshot = {
        "revision": next_num,
        "graph": proj["graph"].to_dict(),
        "command": command,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(rev_dir / f"{next_num:04d}.json", snapshot)
    proj["_current_rev"] = next_num

    # 快照上限 50——超過刪最舊
    all_revs = sorted(rev_dir.glob("*.json"))
    if len(all_revs) > MAX_REVISIONS:
        for f in all_revs[:len(all_revs) - MAX_REVISIONS]:
            f.unlink()

    # 更新 manifest modified_at
    manifest = proj.get("manifest", {})
    manifest["modified_at"] = snapshot["timestamp"]
    atomic_write_json(proj_dir / "manifest.json", manifest)

    # WP1-5: autosave journal
    write_journal_entry(proj_dir, journal_action, proj["graph"].to_dict())


@app.get("/api/projects/{project_id}/revisions")
async def list_revisions(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """列出專案的版本紀錄。"""
    proj = _get_project(project_id)
    rev_dir = proj["dir"] / "revisions"
    result = []
    if rev_dir.exists():
        for f in sorted(rev_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cmd = data.get("command") or {}
                summary = cmd.get("action", "")
                if cmd.get("target_feature_id"):
                    summary += f" → {cmd['target_feature_id']}"
                result.append({
                    "revision": data["revision"],
                    "timestamp": data["timestamp"],
                    "summary": summary,
                })
            except Exception:
                pass
    return {"revisions": result, "current": proj.get("_current_rev", 0)}


@app.post("/api/projects/{project_id}/undo")
async def undo(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """回到上一版。"""
    proj = _get_project(project_id)
    rev_dir = proj["dir"] / "revisions"
    current = proj.get("_current_rev", 0)

    if current <= 0:
        raise HTTPException(400, "已是最早版本，無法復原")

    target = current - 1
    if target == 0:
        # 回到 revision 0（空白狀態——apply_plan 或 reset_project 前的起點）
        proj["graph"] = FeatureGraph()
        proj["part"] = None
        proj["_current_rev"] = 0
        return {"status": "ok", "current": 0}

    rev_path = rev_dir / f"{target:04d}.json"
    if not rev_path.exists():
        raise HTTPException(404, f"找不到版本 {target}")

    data = json.loads(rev_path.read_text(encoding="utf-8"))
    proj["graph"] = FeatureGraph.from_dict(data["graph"])
    proj["part"] = None  # 需重建
    proj["_current_rev"] = target
    return {"status": "ok", "current": target}


@app.post("/api/projects/{project_id}/redo")
async def redo(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """前進一版。"""
    proj = _get_project(project_id)
    rev_dir = proj["dir"] / "revisions"
    current = proj.get("_current_rev", 0)

    target = current + 1
    rev_path = rev_dir / f"{target:04d}.json"
    if not rev_path.exists():
        raise HTTPException(400, "已是最新版本，無法重做")

    data = json.loads(rev_path.read_text(encoding="utf-8"))
    proj["graph"] = FeatureGraph.from_dict(data["graph"])
    proj["part"] = None
    proj["_current_rev"] = target
    return {"status": "ok", "current": target}


# ─── WP1-5: 檔案格式與復原強化 ───

@app.get("/api/projects/{project_id}/crash-recovery")
async def check_crash_recovery(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """偵測上次是否未正常關閉，回傳 journal 最新條目供還原。"""
    proj = _get_project(project_id)
    project_dir = proj["dir"]
    has_journal = detect_unclean_shutdown(project_dir)
    latest = get_latest_journal_entry(project_dir) if has_journal else None
    return {
        "unclean_shutdown": has_journal,
        "latest_journal": latest,
    }


@app.post("/api/projects/{project_id}/crash-recovery/restore")
async def restore_from_journal(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """從 journal 最新條目還原 graph。"""
    proj = _get_project(project_id)
    project_dir = proj["dir"]
    latest = get_latest_journal_entry(project_dir)
    if latest is None:
        raise HTTPException(400, "沒有可還原的 journal 條目")
    graph_data = latest.get("graph", {})
    proj["graph"] = FeatureGraph.from_dict(graph_data)
    proj["part"] = None  # 需重建
    clear_journal(project_dir)
    return {"status": "restored", "action": latest.get("action", "")}


@app.post("/api/projects/{project_id}/crash-recovery/dismiss")
async def dismiss_crash_recovery(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """清除 journal——使用者選擇不還原。"""
    proj = _get_project(project_id)
    clear_journal(proj["dir"])
    return {"status": "dismissed"}


@app.post("/api/projects/import-zip")
async def import_project_zip(req: Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """從 ZIP 匯入專案——路徑遍歷防護、大小限制。"""
    import tempfile
    import shutil
    body = await req.body()
    if len(body) > MAX_IMPORT_SIZE:
        raise HTTPException(413, f"ZIP 檔過大（上限 {MAX_IMPORT_SIZE // (1024*1024)}MB）")

    tmp_zip = WORK_DIR / f"import_{uuid.uuid4()}.zip"
    atomic_write_bytes(tmp_zip, body)
    try:
        project_id = str(uuid.uuid4())
        project_dir = WORK_DIR / project_id
        # WP-H2: 路徑正規化——確保 project_dir 在 WORK_DIR 下
        _canonicalize_path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        try:
            extracted = safe_extract_zip(tmp_zip, project_dir)
        except ValueError as e:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise HTTPException(400, str(e))
        except zipfile.BadZipFile:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise HTTPException(400, "損壞的 ZIP 檔")

        # 檢查 manifest 存在
        manifest_path = project_dir / "manifest.json"
        if not manifest_path.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
            raise HTTPException(400, "ZIP 內缺少 manifest.json")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 檢查 schema 版本
        version = manifest.get("schema_version", "1.0")
        is_supported, msg = check_schema_version(version)
        if not is_supported and msg == "future_version":
            manifest["__read_only"] = True
            manifest["__warning"] = f"未來版本 {version}，唯讀開啟"

        # 載入 features.json
        graph = FeatureGraph()
        features_path = project_dir / "features.json"
        if features_path.exists():
            graph = FeatureGraph.load(features_path)

        manifest["project_id"] = project_id
        from datetime import datetime, timezone
        manifest["imported_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(manifest_path, manifest)

        projects[project_id] = {
            "graph": graph,
            "part": None,
            "dir": project_dir,
            "manifest": manifest,
            "mesh_revision": 0,
            "display_map": None,
        }
        return {"project_id": project_id, "manifest": manifest, "extracted_files": extracted}
    finally:
        tmp_zip.unlink(missing_ok=True)


# ─── WP1-2: 草圖約束求解 ───

class SolveRequest(BaseModel):
    entities: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []


@app.post("/api/projects/{project_id}/sketch/{feature_id}/solve")
async def solve_sketch_constraints(
    project_id: str,
    feature_id: str,
    req: SolveRequest,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """求解草圖約束——互動式，不進入歷史。

    取 entities + constraints → 回傳解算後座標 + solver_status（dof, state, conflicts）。
    最終 solve 在 update_feature commit 時保存。
    """
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]

    # 從 feature 取得既有 entities/constraints（若請求未提供）
    if feature_id in graph._features:
        feature = graph._features[feature_id]
        entities = req.entities if req.entities else feature.sketch_entities
        constraints_dicts = req.constraints if req.constraints else feature.constraints
    else:
        entities = req.entities
        constraints_dicts = req.constraints

    # 驗證約束類型
    for c in constraints_dicts:
        ctype = c.get("type", "")
        if ctype not in CONSTRAINT_TYPES:
            raise HTTPException(400, f"未知約束類型: {ctype}")

    # 建構 Constraint 物件
    constraints = [Constraint.from_dict(c) for c in constraints_dicts]

    # 求解
    result = solve_sketch(entities, constraints)
    return result


# ─── WP1-3 基準幾何 ───


class ReferenceGeometryRequest(BaseModel):
    """建立/更新基準幾何的請求。"""
    id: str
    name: str = ""
    kind: str  # plane / axis / point
    definition: dict[str, Any]


@app.get("/api/projects/{project_id}/reference_geometry")
async def list_reference_geometry(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """列出所有基準幾何。"""
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]
    # 重建以計算 derived_geometry
    _rebuild_reference_geometry(graph, proj)
    return {"reference_geometry": graph.reference_geometry}


@app.post("/api/projects/{project_id}/reference_geometry")
async def create_reference_geometry(
    project_id: str,
    req: ReferenceGeometryRequest,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """建立基準幾何。進入歷史。"""
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]
    datum = {
        "id": req.id,
        "name": req.name or req.id,
        "kind": req.kind,
        "definition": req.definition,
    }
    try:
        graph.add_reference_geometry(datum)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebuild_reference_geometry(graph, proj)
    _save_revision(proj, None)
    return {"reference_geometry": graph.reference_geometry}


@app.delete("/api/projects/{project_id}/reference_geometry/{rg_id}")
async def delete_reference_geometry(
    project_id: str,
    rg_id: str,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """刪除基準幾何。進入歷史。"""
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]
    if not graph.delete_reference_geometry(rg_id):
        raise HTTPException(404, f"基準幾何不存在: {rg_id}")
    _save_revision(proj, None)
    return {"ok": True}


@app.put("/api/projects/{project_id}/reference_geometry/{rg_id}")
async def update_reference_geometry(
    project_id: str,
    rg_id: str,
    req: ReferenceGeometryRequest,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """更新基準幾何定義。進入歷史。"""
    proj = _get_project(project_id)
    graph: FeatureGraph = proj["graph"]
    updates = {
        "name": req.name or req.id,
        "kind": req.kind,
        "definition": req.definition,
    }
    result = graph.update_reference_geometry(rg_id, updates)
    if result is None:
        raise HTTPException(404, f"基準幾何不存在: {rg_id}")
    _rebuild_reference_geometry(graph, proj)
    _save_revision(proj, None)
    return {"reference_geometry": graph.reference_geometry}


def _rebuild_reference_geometry(graph: FeatureGraph, proj: dict[str, Any]) -> None:
    """重建基準幾何——計算 derived_geometry（origin/normal/direction/point）。

    簡化實作：offset datum plane 基於來源面的法向量偏移；
    其他類型留 derived_geometry 為空（build123d adapter 未完整接線）。
    """
    from .reference_geometry_builder import build_reference_geometry
    build_reference_geometry(graph)


# ─── 內部方法 ───

def _get_project(project_id: str) -> dict[str, Any]:
    proj = projects.get(project_id)
    if proj is None:
        raise HTTPException(404, f"專案不存在: {project_id}")
    return proj


async def _rebuild(project_id: str, proj: dict[str, Any]) -> dict[str, Any]:
    """重建模型。產生 GLB + display_map（同一程式碼路徑），再 bump mesh_revision。"""
    graph: FeatureGraph = proj["graph"]
    proj_dir: Path = proj["dir"]

    # WP1-3: 重建基準幾何——計算 derived_geometry
    _rebuild_reference_geometry(graph, proj)

    try:
        adapter = _get_adapter()
        # WP1-0R 地雷 #17: 全域序列化——FreeCAD Document 非線程安全
        async with _rebuild_lock:
            build_result = await asyncio.to_thread(adapter.build_with_trace, graph)
        part = build_result.part
        proj["part"] = part
        trace = build_result.trace

        # 儲存 Feature Graph
        graph.save(proj_dir / "features.json")

        # 產生 GLB + display_map（逐面 tessellation，三角形順序一致）
        gen_dir = proj_dir / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)

        if part is not None:
            glb_path = gen_dir / "model.glb"
            display_map = await asyncio.to_thread(GlbExporter.export_per_face, part, glb_path, trace)
            # bump mesh_revision（GLB + display_map 都就緒後才 +1）
            proj["mesh_revision"] = proj.get("mesh_revision", 0) + 1
            display_map["mesh_revision"] = proj["mesh_revision"]
            proj["display_map"] = display_map
            # 持久化 display_map（原子寫入）
            atomic_write_json(gen_dir / "display_map.json", display_map)

            # WP1-5: content checksum——manifest 記錄 cache 檔的 sha256
            glb_sha = compute_file_sha256(glb_path)
            dm_sha = compute_file_sha256(gen_dir / "display_map.json")
            proj["manifest"]["cache_checksums"] = {
                "glb": glb_sha,
                "display_map": dm_sha,
            }
            atomic_write_json(proj_dir / "manifest.json", proj["manifest"])
        else:
            proj["mesh_revision"] = proj.get("mesh_revision", 0) + 1
            proj["display_map"] = {"mesh_revision": proj["mesh_revision"], "faces": [], "edges": []}

        # 質量屬性
        material = proj.get("manifest", {}).get("material", "pla")
        volume_mm3 = float(part.volume) if part else 0.0
        area_mm2 = float(part.area) if part else 0.0
        bounding_box = part.bounding_box() if part else None
        from .standard_parts import calculate_mass
        mass_g = calculate_mass(volume_mm3, material) if volume_mm3 > 0 else 0.0

        return {
            "status": "success",
            "feature_count": len(graph.features),
            "mesh_revision": proj.get("mesh_revision", 0),
            "mass_properties": {
                "volume_mm3": round(volume_mm3, 2),
                "surface_area_mm2": round(area_mm2, 2),
                "mass_g": round(mass_g, 2),
                "material": material,
                "density_g_cm3": round(mass_g / (volume_mm3 / 1000.0), 4) if volume_mm3 > 0 else 0.0,
                "bounding_box_mm": {
                    "min_x": round(bounding_box.min.X, 2) if bounding_box else 0,
                    "min_y": round(bounding_box.min.Y, 2) if bounding_box else 0,
                    "min_z": round(bounding_box.min.Z, 2) if bounding_box else 0,
                    "max_x": round(bounding_box.max.X, 2) if bounding_box else 0,
                    "max_y": round(bounding_box.max.Y, 2) if bounding_box else 0,
                    "max_z": round(bounding_box.max.Z, 2) if bounding_box else 0,
                    "size_x": round(bounding_box.size.X, 2) if bounding_box else 0,
                    "size_y": round(bounding_box.size.Y, 2) if bounding_box else 0,
                    "size_z": round(bounding_box.size.Z, 2) if bounding_box else 0,
                },
            },
        }
    except ImportError as e:
        raise HTTPException(503, f"CAD 引擎未安裝: {e}")
    except Exception as e:
        # Worker 失敗時回傳結構化錯誤
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "error_code": _classify_error(e),
                "engine_message": str(e),
            },
        )


async def _rebuild_dry_run(project_id: str, proj: dict[str, Any]) -> dict[str, Any]:
    """Dry-run rebuild（WP-H1 rebuild_staging）——只試跑不寫盤、不 bump mesh_revision。

    複製 graph 做深拷貝後重建，不影響正式版本。
    """
    import copy
    graph: FeatureGraph = proj["graph"]
    # 深拷貝 graph 以免污染正式版本
    graph_backup = copy.deepcopy(graph)
    try:
        _rebuild_reference_geometry(graph_backup, {})
        adapter = _get_adapter()
        # WP1-0R 地雷 #17: 全域序列化——FreeCAD Document 非線程安全
        async with _rebuild_lock:
            build_result = await asyncio.to_thread(adapter.build_with_trace, graph_backup)
        part = build_result.part
        volume_mm3 = float(part.volume) if part else 0.0
        area_mm2 = float(part.area) if part else 0.0
        bounding_box = part.bounding_box() if part else None
        return {
            "status": "success",
            "dry_run": True,
            "feature_count": len(graph_backup.features),
            "mass_properties": {
                "volume_mm3": round(volume_mm3, 2),
                "surface_area_mm2": round(area_mm2, 2),
                "bounding_box_mm": {
                    "size_x": round(bounding_box.size.X, 2) if bounding_box else 0,
                    "size_y": round(bounding_box.size.Y, 2) if bounding_box else 0,
                    "size_z": round(bounding_box.size.Z, 2) if bounding_box else 0,
                },
            },
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "dry_run": True,
                "error_code": _classify_error(e),
                "engine_message": str(e),
            },
        )


async def _validate(project_id: str, proj: dict[str, Any]) -> dict[str, Any]:
    """驗證模型。"""
    part = proj.get("part")
    graph: FeatureGraph = proj["graph"]

    # 收集預期條件
    expected: dict[str, Any] = {}
    for feature in graph.features.values():
        if feature.validation:
            if feature.validation.must_be_single_solid:
                expected["expected_solid_count"] = 1
            if feature.validation.min_thickness_mm:
                expected["min_thickness_mm"] = feature.validation.min_thickness_mm
            if feature.validation.expected_hole_count:
                expected["expected_hole_count"] = feature.validation.expected_hole_count

    validator = GeometryValidator()
    report = validator.validate(part, expected)
    return {"report": report.to_dict()}


async def _export(project_id: str, proj: dict[str, Any], fmt: str, filename: str = "model") -> dict[str, Any]:
    """匯出模型。GLB 已在 _rebuild 時由逐面 tessellation 產生，直接回傳既有檔案。"""
    part = proj.get("part")
    export_dir = proj["dir"] / "generated"
    export_dir.mkdir(parents=True, exist_ok=True)

    # part 為 None（尚未重建、reset 後、重啟後）一律 400——
    # 不得回傳磁碟上殘留的舊檔（guard 必須在 GLB 分支之前）
    if part is None:
        raise HTTPException(400, "模型尚未重建")

    if fmt == "glb":
        # GLB 已在 rebuild 時產生（逐面 tessellation，與 display_map 同路徑）
        glb_path = export_dir / "model.glb"
        if not glb_path.exists():
            raise HTTPException(400, "GLB 尚未產生，請先重建模型")
        return {"status": "exported", "format": "glb", "path": str(glb_path)}

    # WP-H2: STEP 面數上限檢查
    if fmt == "step":
        try:
            face_count = len(part.faces())
        except Exception:
            face_count = 0
        if face_count > MAX_STEP_FACES:
            raise HTTPException(
                413,
                f"STEP 面數過多：{face_count} > {MAX_STEP_FACES}",
            )

    mgr = ExportManager()
    path = mgr.export(part, fmt, export_dir, filename)
    return {"status": "exported", "format": fmt, "path": str(path)}


def _get_adapter():
    """取得建模引擎 Adapter。

    依 OPENCAD_ENGINE 環境變數切換：
    - "freecad"：使用 FreeCAD Adapter（需要 FREECAD_DIR）
    - "build123d"（預設）：使用 build123d Adapter

    WP1-0R: OPENCAD_ENGINE=freecad 但 FreeCAD 不可用時，不再靜默回退到 build123d。
    權威核心不得被偷換——直接拋 ImportError，由呼叫端轉為 503。
    """
    engine = os.environ.get("OPENCAD_ENGINE", "build123d").lower()
    if engine == "freecad":
        from .adapters.freecad_adapter import FreeCADAdapter, FREECAD_AVAILABLE, _FREECAD_IMPORT_ERROR
        if not FREECAD_AVAILABLE:
            raise ImportError(
                f"OPENCAD_ENGINE=freecad 但 FreeCAD 不可用: {_FREECAD_IMPORT_ERROR or '未知原因'}。"
                f"請設定 FREECAD_DIR 環境變數指向 FreeCAD 安裝目錄。"
            )
        return FreeCADAdapter()
    from .adapters import Build123dAdapter
    return Build123dAdapter()


def _classify_error(e: Exception) -> str:
    """將例外分類為結構化錯誤碼。

    內部錯誤訊息為繁體中文，比對中英文關鍵字以正確分類。
    """
    msg = str(e)
    msg_lower = msg.lower()
    # 圓角半徑過大
    if ("fillet" in msg_lower and "radius" in msg_lower) or "圓角" in msg and "半徑" in msg:
        return "FILLET_RADIUS_TOO_LARGE"
    # 薄殼失敗
    if "shell" in msg_lower or "薄殼" in msg:
        return "SHELL_FAILED"
    # 布林運算失敗
    if "boolean" in msg_lower or "fuse" in msg_lower or "cut" in msg_lower or "布林" in msg:
        return "BOOLEAN_OPERATION_FAILED"
    # 循環依賴
    if "cycle" in msg_lower or "circular" in msg_lower or "循環" in msg or "依賴" in msg:
        return "CIRCULAR_DEPENDENCY"
    # 標準件查表失敗
    if "螺絲標準" in msg or "配合等級" in msg or "nema" in msg_lower or "未知的 nema" in msg.lower():
        return "INVALID_STANDARD_PART"
    # 草圖未閉合
    if "未閉合" in msg or "not closed" in msg_lower or "sketch_not_closed" in msg_lower:
        return "SKETCH_NOT_CLOSED"
    # 特徵參照不存在
    if "not found" in msg_lower or "不存在" in msg or "找不到" in msg:
        return "FEATURE_REFERENCE_NOT_FOUND"
    # 參照消失（WP0-4 persistent reference）
    if "REFERENCE_LOST" in msg or "參照目標不存在" in msg or "reference_lost" in msg_lower:
        return "REFERENCE_LOST"
    # 參照歧義（WP0-4 persistent reference）
    if "REFERENCE_AMBIGUOUS" in msg or "參照歧義" in msg or "reference_ambiguous" in msg_lower:
        return "REFERENCE_AMBIGUOUS"
    # reorder 違反依賴（v2）
    if "REORDER_DEPENDENCY_VIOLATION" in msg or "reorder" in msg_lower and "依賴" in msg:
        return "REORDER_DEPENDENCY_VIOLATION"
    return "GEOMETRY_ERROR"


def _check_build123d() -> bool:
    try:
        import build123d  # noqa: F401
        return True
    except ImportError:
        return False


def _watch_parent_process() -> None:
    """監看父程序（Avalonia 主程式）——父程序結束時自我終止。

    避免主程式被強制關閉（工作管理員、當機）時留下殭屍 Worker
    佔用埠號，導致下次啟動綁定失敗。
    """
    parent_pid_str = os.environ.get("OPENCAD_PARENT_PID")
    if not parent_pid_str:
        return
    parent_pid = int(parent_pid_str)

    import threading
    import time

    def _pid_alive(pid: int) -> bool:
        if os.name == "nt":
            import ctypes
            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not h:
                return False
            # WaitForSingleObject 0ms：WAIT_TIMEOUT(258)=仍在執行
            alive = ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 258
            ctypes.windll.kernel32.CloseHandle(h)
            return alive
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _watch() -> None:
        while True:
            time.sleep(3)
            if not _pid_alive(parent_pid):
                os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def main() -> None:
    """啟動 CAD Worker Server。"""
    import uvicorn
    # 埠號由主程式指定（避免殭屍程序佔用固定埠造成綁定失敗）；
    # 手動啟動時預設 8765
    port = int(os.environ.get("OPENCAD_WORKER_PORT", "8765"))
    print(f"OpenCad CAD Worker v0.1.0")
    print(f"工作目錄: {WORK_DIR}")
    print(f"監聽埠: {port}")
    print(f"工作階段 Token: {SESSION_TOKEN}")
    if _TOKEN_FILE:
        print(f"Token 檔案: {_TOKEN_FILE}")
    print(f"已載入專案數: {len(projects)}")
    print(f"build123d 可用: {_check_build123d()}")
    _watch_parent_process()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()