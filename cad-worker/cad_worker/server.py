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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field

from .feature_graph import FeatureGraph, Feature, FeatureType, ParameterValue
from .validators import GeometryValidator, ValidationReport
from .exporters import ExportManager

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

app = FastAPI(
    title="OpenCad CAD Worker",
    version="0.1.0",
    description="Python 幾何引擎 Worker（build123d / OCCT）",
)

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
            projects[project_id] = {
                "graph": graph,
                "part": None,  # BREP 需重建才有
                "dir": proj_dir,
                "manifest": manifest,
            }
        except Exception:
            pass  # 跳過損壞的專案目錄


_load_existing_projects()


# ─── 認證 ───

def verify_token(x_session_token: str = Header(None, alias="X-Session-Token")) -> None:
    """驗證工作階段 Token。"""
    if x_session_token != SESSION_TOKEN:
        raise HTTPException(status_code=403, detail="無效的工作階段 Token")


# ─── 請求模型 ───

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    units: str = "mm"
    engine: str = "build123d"


class ApplyCommandRequest(BaseModel):
    action: str
    document_id: str | None = None
    target_feature_id: str | None = None
    feature: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    preserve: list[str] = []
    export_format: str = "all"
    standard_parts: dict[str, Any] | None = None
    reasoning: str = ""


class ExportRequest(BaseModel):
    format: str = "all"  # step / stl / 3mf / glb / png / all
    filename: str = "model"


# ─── API 端點 ───

@app.get("/api/health")
async def health() -> dict[str, Any]:
    """健康檢查。"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "build123d_available": _check_build123d(),
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
        "created_at": now,
        "modified_at": now,
    }
    (project_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    projects[project_id] = {
        "graph": graph,
        "part": None,
        "dir": project_dir,
        "manifest": manifest,
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

    if req.action == "create_feature":
        if req.feature is None:
            raise HTTPException(400, "create_feature 需要 feature 欄位")
        feature = Feature.from_dict(req.feature)
        graph.add_feature(feature)
        return {"status": "created", "feature_id": feature.feature_id}

    elif req.action == "update_feature":
        if req.target_feature_id is None or req.parameters is None:
            raise HTTPException(400, "update_feature 需要 target_feature_id 和 parameters")
        feature = graph.update_feature(req.target_feature_id, req.parameters)
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
        return {"status": "deleted", "feature_id": req.target_feature_id}

    elif req.action == "rebuild":
        return await _rebuild(project_id, proj)

    elif req.action == "validate":
        return await _validate(project_id, proj)

    elif req.action == "export":
        return await _export(project_id, proj, req.export_format or "all")

    else:
        raise HTTPException(400, f"未知的 action: {req.action}")


@app.post("/api/projects/{project_id}/rebuild")
async def rebuild(project_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    """重建模型。"""
    proj = _get_project(project_id)
    return await _rebuild(project_id, proj)


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


@app.get("/api/projects/{project_id}/preview.glb")
async def get_preview(request: Request, project_id: str, token: str = "") -> Any:
    """取得 GLB 預覽。

    支援兩種認證方式：
    1. X-Session-Token header（一般 API 呼叫）
    2. ?token= query 參數（WebView GLTFLoader 無法帶自訂 header）
    """
    header_token = request.headers.get("X-Session-Token", "")
    if header_token != SESSION_TOKEN and token != SESSION_TOKEN:
        raise HTTPException(status_code=403, detail="無效的工作階段 Token")
    proj = _get_project(project_id)
    glb_path = proj["dir"] / "generated" / "model.glb"
    if not glb_path.exists():
        raise HTTPException(404, "預覽尚未生成，請先重建模型")
    return FileResponse(str(glb_path), media_type="model/gltf-binary")


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


# ─── 內部方法 ───

def _get_project(project_id: str) -> dict[str, Any]:
    proj = projects.get(project_id)
    if proj is None:
        raise HTTPException(404, f"專案不存在: {project_id}")
    return proj


async def _rebuild(project_id: str, proj: dict[str, Any]) -> dict[str, Any]:
    """重建模型。"""
    graph: FeatureGraph = proj["graph"]
    proj_dir: Path = proj["dir"]

    try:
        adapter = _get_adapter()
        part = adapter.build(graph)
        proj["part"] = part

        # 儲存 Feature Graph
        graph.save(proj_dir / "features.json")

        return {
            "status": "success",
            "feature_count": len(graph.features),
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
    """匯出模型。"""
    part = proj.get("part")
    if part is None:
        raise HTTPException(400, "模型尚未重建")
    export_dir = proj["dir"] / "generated"
    export_dir.mkdir(parents=True, exist_ok=True)
    mgr = ExportManager()
    path = mgr.export(part, fmt, export_dir, filename)
    return {"status": "exported", "format": fmt, "path": str(path)}


def _get_adapter():
    """取得建模引擎 Adapter。"""
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
    # 特徵參照不存在
    if "not found" in msg_lower or "不存在" in msg or "找不到" in msg:
        return "FEATURE_REFERENCE_NOT_FOUND"
    return "GEOMETRY_ERROR"


def _check_build123d() -> bool:
    try:
        import build123d  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> None:
    """啟動 CAD Worker Server。"""
    import uvicorn
    print(f"OpenCad CAD Worker v0.1.0")
    print(f"工作目錄: {WORK_DIR}")
    print(f"工作階段 Token: {SESSION_TOKEN}")
    if _TOKEN_FILE:
        print(f"Token 檔案: {_TOKEN_FILE}")
    print(f"已載入專案數: {len(projects)}")
    print(f"build123d 可用: {_check_build123d()}")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()