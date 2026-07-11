"""FreeCAD Headless Worker Server — WP0-1 Spike.

HTTP API server using FreeCAD as modeling engine.
Mirrors existing cad-worker conventions: random port + token file + /api/health.

Endpoints:
  GET  /api/health
  POST /api/projects
  POST /api/projects/{id}/commands
  POST /api/projects/{id}/rebuild
  POST /api/projects/{id}/exports
  GET  /api/projects/{id}/display_map
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ── FreeCAD 環境初始化 ──
_FREECAD_DIR = os.environ.get("FREECAD_DIR", "")
if not _FREECAD_DIR:
    # 嘗試常見路徑
    candidates = [
        r"C:\Users\Johnson\Desktop\文件資料\學習文件\OpenScad\FreeCAD\FreeCAD_1.1.1-Windows-x86_64-py311",
    ]
    for c in candidates:
        if Path(c).exists():
            _FREECAD_DIR = c
            break

if _FREECAD_DIR:
    _bin = os.path.join(_FREECAD_DIR, "bin")
    _lib = os.path.join(_FREECAD_DIR, "lib")
    for p in [_bin, _lib]:
        if p not in sys.path:
            sys.path.insert(0, p)

import FreeCAD
import Part
import Sketcher


# ── HTTP server（純標準庫，不引入 FastAPI）──

class FreeCadWorker:
    """FreeCAD headless worker — single-threaded (FreeCAD Document not thread-safe)."""

    def __init__(self) -> None:
        self._projects: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()  # 序列化所有 FreeCAD 操作

    # ── 專案管理 ──

    def create_project(self, name: str = "untitled") -> dict[str, Any]:
        with self._lock:
            project_id = str(uuid.uuid4())[:8]
            doc = FreeCAD.newDocument(f"proj_{project_id}")
            self._projects[project_id] = {
                "id": project_id,
                "name": name,
                "doc": doc,
                "features": [],
                "shape": None,
                "display_map": None,
                "mesh_revision": 0,
            }
            return {"project_id": project_id, "name": name, "status": "created"}

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._projects.get(project_id)

    # ── 特徵指令 ──

    def execute_command(self, project_id: str, command: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            proj = self._projects.get(project_id)
            if not proj:
                return {"status": "error", "error_code": "PROJECT_NOT_FOUND"}

            cmd_type = command.get("type", "")
            if cmd_type == "create_feature":
                return self._create_feature(proj, command.get("parameters", {}))
            elif cmd_type == "update_feature":
                return self._update_feature(proj, command.get("parameters", {}))
            elif cmd_type == "delete_feature":
                return self._delete_feature(proj, command.get("parameters", {}))
            else:
                return {"status": "error", "error_code": "UNKNOWN_COMMAND", "message": f"Unknown: {cmd_type}"}

    def _create_feature(self, proj: dict, params: dict) -> dict:
        feat_type = params.get("type", "")
        feature_id = params.get("feature_id", f"f{len(proj['features']) + 1}")

        if feat_type == "sketch":
            return self._create_sketch(proj, feature_id, params)
        elif feat_type == "pad":
            return self._create_pad(proj, feature_id, params)
        elif feat_type == "hole":
            return self._create_hole(proj, feature_id, params)
        elif feat_type == "fillet":
            return self._create_fillet(proj, feature_id, params)
        elif feat_type == "box":
            return self._create_box(proj, feature_id, params)
        else:
            return {"status": "error", "error_code": "UNSUPPORTED_FEATURE_TYPE", "message": feat_type}

    def _create_box(self, proj: dict, fid: str, params: dict) -> dict:
        """Create a box feature."""
        w = params.get("width", 50)
        d = params.get("depth", 50)
        h = params.get("height", 10)
        box = Part.makeBox(w, d, h)
        proj["shape"] = box
        proj["features"].append({
            "feature_id": fid,
            "type": "box",
            "parameters": {"width": w, "depth": d, "height": h},
        })
        return {"status": "ok", "feature_id": fid}

    def _create_sketch(self, proj: dict, fid: str, params: dict) -> dict:
        """Create a sketch with rectangle geometry."""
        doc = proj["doc"]
        sketch = doc.addObject("Sketcher::SketchObject", fid)

        # 支援 sketch_entities 格式
        entities = params.get("sketch_entities", [])
        constraints = params.get("constraints", [])

        if not entities:
            # 預設：矩形草圖
            w = params.get("width", 60)
            h = params.get("height", 40)
            entities = [
                {"type": "line", "start": [0, 0], "end": [w, 0]},
                {"type": "line", "start": [w, 0], "end": [w, h]},
                {"type": "line", "start": [w, h], "end": [0, h]},
                {"type": "line", "start": [0, h], "end": [0, 0]},
            ]

        for ent in entities:
            if ent["type"] == "line":
                s = ent["start"]
                e = ent["end"]
                sketch.addGeometry(Part.LineSegment(
                    FreeCAD.Vector(s[0], s[1], 0),
                    FreeCAD.Vector(e[0], e[1], 0),
                ))
            elif ent["type"] == "circle":
                c = ent["center"]
                r = ent["radius"]
                sketch.addGeometry(Part.Circle(
                    FreeCAD.Vector(c[0], c[1], 0),
                    FreeCAD.Vector(0, 0, 1),
                    r,
                ))

        # 加入約束
        for con in constraints:
            ctype = con.get("type", "").lower()
            if ctype == "coincident":
                sketch.addConstraint(Sketcher.Constraint("Coincident",
                    con["line1"], con.get("point1", 2),
                    con["line2"], con.get("point2", 1)))
            elif ctype == "horizontal":
                sketch.addConstraint(Sketcher.Constraint("Horizontal", con["line"]))
            elif ctype == "vertical":
                sketch.addConstraint(Sketcher.Constraint("Vertical", con["line"]))
            elif ctype == "distance":
                sketch.addConstraint(Sketcher.Constraint("Distance", con["line"], con["value"]))
            elif ctype == "radius":
                sketch.addConstraint(Sketcher.Constraint("Radius", con["line"], con["value"]))

        sketch.solve()
        doc.recompute()

        proj["features"].append({
            "feature_id": fid,
            "type": "sketch",
            "sketch_obj": sketch,
            "parameters": params,
        })
        return {"status": "ok", "feature_id": fid, "dof": sketch.DoF}

    def _create_pad(self, proj: dict, fid: str, params: dict) -> dict:
        """Create a pad (extrude) from a sketch."""
        sketch_id = params.get("sketch_id", "")
        length = params.get("length", 10)

        sketch_feat = None
        for f in proj["features"]:
            if f["feature_id"] == sketch_id:
                sketch_feat = f
                break

        if not sketch_feat:
            return {"status": "error", "error_code": "SKETCH_NOT_FOUND", "message": sketch_id}

        sketch = sketch_feat["sketch_obj"]
        # 用 Part API 直接 extrude sketch wire
        wire = Part.Wire(sketch.Shape.Edges)
        face = Part.Face(wire)
        pad_shape = face.extrude(FreeCAD.Vector(0, 0, length))

        # 與現有 shape 合併
        if proj["shape"] is None:
            proj["shape"] = pad_shape
        else:
            proj["shape"] = proj["shape"].fuse(pad_shape)

        proj["features"].append({
            "feature_id": fid,
            "type": "pad",
            "parameters": params,
        })
        return {"status": "ok", "feature_id": fid}

    def _create_hole(self, proj: dict, fid: str, params: dict) -> dict:
        """Create a hole (cylinder cut)."""
        if proj["shape"] is None:
            return {"status": "error", "error_code": "NO_SHAPE", "message": "No shape to cut"}

        diameter = params.get("diameter", 6)
        radius = diameter / 2
        pos = params.get("position", [0, 0, 0])
        depth = params.get("depth", 100)
        direction = params.get("direction", [0, 0, 1])

        cyl = Part.makeCylinder(
            radius, depth,
            FreeCAD.Vector(pos[0], pos[1], pos[2]),
            FreeCAD.Vector(direction[0], direction[1], direction[2]),
        )
        proj["shape"] = proj["shape"].cut(cyl)

        proj["features"].append({
            "feature_id": fid,
            "type": "hole",
            "parameters": params,
        })
        return {"status": "ok", "feature_id": fid}

    def _create_fillet(self, proj: dict, fid: str, params: dict) -> dict:
        """Create a fillet on specified edges."""
        if proj["shape"] is None:
            return {"status": "error", "error_code": "NO_SHAPE", "message": "No shape to fillet"}

        radius = params.get("radius", 2)
        edge_filter = params.get("edge_filter", "top")  # top, bottom, all_vertical, all

        shape = proj["shape"]
        bb = shape.BoundBox
        edges_to_fillet = []

        for edge in shape.Edges:
            verts = edge.Vertexes
            if not verts:
                continue

            if edge_filter == "top":
                if all(abs(v.Point.z - bb.ZMax) < 0.01 for v in verts):
                    edges_to_fillet.append(edge)
            elif edge_filter == "bottom":
                if all(abs(v.Point.z - bb.ZMin) < 0.01 for v in verts):
                    edges_to_fillet.append(edge)
            elif edge_filter == "all":
                edges_to_fillet.append(edge)
            elif edge_filter == "all_vertical":
                # 垂直邊
                if len(verts) == 2:
                    dz = abs(verts[0].Point.z - verts[1].Point.z)
                    dx = abs(verts[0].Point.x - verts[1].Point.x)
                    dy = abs(verts[0].Point.y - verts[1].Point.y)
                    if dz > 0.1 and dx < 0.01 and dy < 0.01:
                        edges_to_fillet.append(edge)

        if not edges_to_fillet:
            return {"status": "ok", "feature_id": fid, "message": "no matching edges"}

        try:
            proj["shape"] = shape.makeFillet(radius, edges_to_fillet)
        except Exception as e:
            return {"status": "error", "error_code": "FILLET_FAILED", "message": str(e)}

        proj["features"].append({
            "feature_id": fid,
            "type": "fillet",
            "parameters": params,
        })
        return {"status": "ok", "feature_id": fid, "edges_filleted": len(edges_to_fillet)}

    def _update_feature(self, proj: dict, params: dict) -> dict:
        """Update a feature's parameters and rebuild."""
        feature_id = params.get("feature_id", "")
        for f in proj["features"]:
            if f["feature_id"] == feature_id:
                f["parameters"].update(params.get("parameters", {}))
                break
        # 簡化：直接 rebuild all
        return self._rebuild_all(proj)

    def _delete_feature(self, proj: dict, params: dict) -> dict:
        """Delete a feature."""
        feature_id = params.get("feature_id", "")
        proj["features"] = [f for f in proj["features"] if f["feature_id"] != feature_id]
        return self._rebuild_all(proj)

    # ── 重建 ──

    def rebuild(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            proj = self._projects.get(project_id)
            if not proj:
                return {"status": "error", "error_code": "PROJECT_NOT_FOUND"}

            result = self._rebuild_all(proj)
            if result["status"] == "ok":
                # Tessellate + generate display_map
                self._generate_display_map(proj)
                result["mesh_revision"] = proj["mesh_revision"]
                result["volume"] = proj["shape"].Volume if proj["shape"] else 0
            return result

    def _rebuild_all(self, proj: dict) -> dict:
        """Rebuild shape from feature list."""
        proj["shape"] = None
        doc = proj["doc"]
        for feat in proj["features"]:
            ftype = feat["type"]
            params = feat.get("parameters", {})
            if ftype == "box":
                box = Part.makeBox(
                    params.get("width", 50),
                    params.get("depth", 50),
                    params.get("height", 10),
                )
                proj["shape"] = box if proj["shape"] is None else proj["shape"].fuse(box)
            elif ftype == "sketch":
                # Sketch geometry already updated in FreeCAD document
                # Just re-solve to ensure constraints are satisfied
                if "sketch_obj" in feat:
                    feat["sketch_obj"].solve()
                    doc.recompute()
            elif ftype == "pad":
                sketch_id = params.get("sketch_id", "")
                length = params.get("length", 10)
                sketch_feat = None
                for f in proj["features"]:
                    if f["feature_id"] == sketch_id:
                        sketch_feat = f
                        break
                if sketch_feat and "sketch_obj" in sketch_feat:
                    sketch = sketch_feat["sketch_obj"]
                    # Re-solve sketch to get updated geometry
                    sketch.solve()
                    doc.recompute()
                    wire = Part.Wire(sketch.Shape.Edges)
                    if wire.isClosed():
                        face = Part.Face(wire)
                        pad_shape = face.extrude(FreeCAD.Vector(0, 0, length))
                        proj["shape"] = pad_shape if proj["shape"] is None else proj["shape"].fuse(pad_shape)
            elif ftype == "hole":
                if proj["shape"] is None:
                    continue
                diameter = params.get("diameter", 6)
                pos = params.get("position", [0, 0, 0])
                depth = params.get("depth", 100)
                cyl = Part.makeCylinder(diameter / 2, depth,
                    FreeCAD.Vector(pos[0], pos[1], pos[2]),
                    FreeCAD.Vector(0, 0, 1))
                proj["shape"] = proj["shape"].cut(cyl)
            elif ftype == "fillet":
                if proj["shape"] is None:
                    continue
                radius = params.get("radius", 2)
                edge_filter = params.get("edge_filter", "top")
                shape = proj["shape"]
                bb = shape.BoundBox
                edges = []
                for edge in shape.Edges:
                    verts = edge.Vertexes
                    if not verts:
                        continue
                    if edge_filter == "top" and all(abs(v.Point.z - bb.ZMax) < 0.01 for v in verts):
                        edges.append(edge)
                    elif edge_filter == "all":
                        edges.append(edge)
                if edges:
                    try:
                        proj["shape"] = shape.makeFillet(radius, edges)
                    except Exception:
                        pass  # Fillet may fail — skip gracefully

        doc.recompute()
        return {"status": "ok"}

    # ── Tessellation + Display Map ──

    def _generate_display_map(self, proj: dict) -> None:
        """Tessellate per face, generate display_map + GLB."""
        shape = proj["shape"]
        if shape is None:
            return

        faces = shape.Faces
        all_verts: list[list[float]] = []
        all_indices: list[list[int]] = []
        display_map_faces = []
        display_map_edges = []
        tri_offset = 0

        # surface_type 對齊 schemas/display_map.schema.json 的 enum
        _stype_map = {"plane": "plane", "cylinder": "cylinder", "cone": "cone",
                      "sphere": "sphere", "toroid": "torus", "torus": "torus"}

        for i, face in enumerate(faces):
            result = face.tessellate(0.1)
            if result:
                verts, tris = result
                vert_offset = len(all_verts)
                for v in verts:
                    all_verts.append([v.x, v.y, v.z])
                for tri in tris:
                    all_indices.append([tri[0] + vert_offset, tri[1] + vert_offset, tri[2] + vert_offset])

                tri_count = len(tris)
                raw_stype = face.Surface.TypeId.replace("Part::Geom", "").lower()
                stype = _stype_map.get(raw_stype, "other")
                c = face.CenterOfMass
                # 欄位對齊 WP0-3 契約（schemas/display_map.schema.json）：
                # face_id 字串、triangle_range 含頭不含尾、source_feature_id/brep_face_ref
                display_map_faces.append({
                    "face_id": f"f-{i}",
                    "brep_face_ref": f"unknown/result/face/{i}",
                    "source_feature_id": "unknown",
                    "triangle_range": [tri_offset, tri_offset + tri_count],
                    "surface_type": stype,
                    "area_mm2": round(face.Area, 2),
                    "centroid": [round(c.x, 2), round(c.y, 2), round(c.z, 2)],
                })
                tri_offset += tri_count

        for i, edge in enumerate(shape.Edges):
            try:
                pts = edge.discretize(Deflection=0.1)
                if len(pts) < 2:
                    continue
                display_map_edges.append({
                    "display_edge_id": f"e-{i}",
                    "brep_edge_ref": f"unknown/result/edge/{i}",
                    "source_feature_id": "unknown",
                    "polyline": [[round(p.x, 3), round(p.y, 3), round(p.z, 3)] for p in pts],
                })
            except Exception:
                continue

        proj["mesh_revision"] += 1
        proj["display_map"] = {
            "mesh_revision": proj["mesh_revision"],
            "faces": display_map_faces,
            "edges": display_map_edges,
        }
        proj["all_verts"] = all_verts
        proj["all_indices"] = all_indices

    # ── 匯出 ──

    def export(self, project_id: str, fmt: str, export_dir: Path) -> dict[str, Any]:
        with self._lock:
            proj = self._projects.get(project_id)
            if not proj:
                return {"status": "error", "error_code": "PROJECT_NOT_FOUND"}
            if proj["shape"] is None:
                return {"status": "error", "error_code": "NO_SHAPE"}

            export_dir.mkdir(parents=True, exist_ok=True)

            if fmt == "step":
                path = export_dir / "model.step"
                # 使用 Import.export（Part.export 產生的 STEP 無法被 Part.read 讀回）
                import Import as FCImport
                doc = proj["doc"]
                # 確保 shape 存於 document 中
                obj = doc.addObject("Part::Feature", "ExportShape")
                obj.Shape = proj["shape"]
                doc.recompute()
                FCImport.export([obj], str(path))
                doc.removeObject(obj.Name)
                return {"status": "ok", "format": "step", "path": str(path)}

            elif fmt == "glb":
                if "all_verts" not in proj:
                    self._generate_display_map(proj)
                path = export_dir / "model.glb"
                self._write_glb(proj, path)
                return {"status": "ok", "format": "glb", "path": str(path)}

            elif fmt == "fcstd":
                path = export_dir / "model.FCStd"
                proj["doc"].saveAs(str(path))
                return {"status": "ok", "format": "fcstd", "path": str(path)}

            return {"status": "error", "error_code": "UNSUPPORTED_FORMAT", "message": fmt}

    def _write_glb(self, proj: dict, path: Path) -> None:
        """Write GLB file from tessellated mesh data."""
        verts = proj.get("all_verts", [])
        indices = proj.get("all_indices", [])
        if not verts or not indices:
            return

        verts_flat = []
        for v in verts:
            verts_flat.extend(v)
        indices_flat = []
        for tri in indices:
            indices_flat.extend(tri)

        bin_data = struct.pack(f'<{len(verts_flat)}f', *verts_flat)
        bin_data += struct.pack(f'<{len(indices_flat)}I', *indices_flat)

        glb_json = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": len(verts_flat) * 4, "target": 34962},
                {"buffer": 0, "byteOffset": len(verts_flat) * 4, "byteLength": len(indices_flat) * 4, "target": 34963},
            ],
            "accessors": [
                {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "FLOAT",
                 "max": [max(v[0] for v in verts), max(v[1] for v in verts), max(v[2] for v in verts)],
                 "min": [min(v[0] for v in verts), min(v[1] for v in verts), min(v[2] for v in verts)]},
                {"bufferView": 1, "componentType": 5125, "count": len(indices_flat), "type": "SCALAR"},
            ],
        }
        json_data = json.dumps(glb_json).encode('utf-8')
        while len(json_data) % 4 != 0:
            json_data += b' '
        while len(bin_data) % 4 != 0:
            bin_data += b'\x00'

        total_length = 12 + 8 + len(json_data) + 8 + len(bin_data)
        glb = struct.pack('<III', 0x46546C67, 2, total_length)
        glb += struct.pack('<II', len(json_data), 0x4E4F534A)
        glb += json_data
        glb += struct.pack('<II', len(bin_data), 0x004E4942)
        glb += bin_data

        with open(path, 'wb') as f:
            f.write(glb)

    # ── 存檔/重開 ──

    def save_project(self, project_id: str, path: Path) -> dict[str, Any]:
        with self._lock:
            proj = self._projects.get(project_id)
            if not proj:
                return {"status": "error", "error_code": "PROJECT_NOT_FOUND"}
            path.parent.mkdir(parents=True, exist_ok=True)
            proj["doc"].saveAs(str(path))
            return {"status": "ok", "path": str(path)}

    def load_project(self, path: Path) -> dict[str, Any]:
        with self._lock:
            if not path.exists():
                return {"status": "error", "error_code": "FILE_NOT_FOUND"}
            doc = FreeCAD.openDocument(str(path))
            project_id = str(uuid.uuid4())[:8]
            self._projects[project_id] = {
                "id": project_id,
                "name": path.stem,
                "doc": doc,
                "features": [],
                "shape": None,
                "display_map": None,
                "mesh_revision": 0,
            }
            return {"status": "ok", "project_id": project_id, "name": path.stem}


# ── HTTP server（基於 http.server）──

from http.server import HTTPServer, BaseHTTPRequestHandler


class _Handler(BaseHTTPRequestHandler):
    worker: FreeCadWorker = None  # type: ignore
    token: str = ""

    def _check_token(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self) -> None:
        if not self._check_token():
            self._send_json(401, {"error": "unauthorized"})
            return

        path = self.path.split("?")[0]
        parts = path.strip("/").split("/")

        if parts == ["api", "health"]:
            self._send_json(200, {"status": "ok", "engine": "freecad", "version": ".".join(FreeCAD.Version()[:3])})
            return

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "display_map":
            proj = self.worker.get_project(parts[2])
            if proj and proj.get("display_map"):
                self._send_json(200, proj["display_map"])
            else:
                self._send_json(404, {"error": "display_map not generated"})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._check_token():
            self._send_json(401, {"error": "unauthorized"})
            return

        path = self.path.split("?")[0]
        parts = path.strip("/").split("/")
        body = self._read_body()

        if parts == ["api", "projects"]:
            result = self.worker.create_project(body.get("name", "untitled"))
            self._send_json(201, result)
            return

        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "projects":
            pid = parts[2]

            if len(parts) == 4 and parts[3] == "commands":
                result = self.worker.execute_command(pid, body)
                self._send_json(200, result)
                return

            if len(parts) == 4 and parts[3] == "rebuild":
                result = self.worker.rebuild(pid)
                self._send_json(200, result)
                return

            if len(parts) == 4 and parts[3] == "exports":
                fmt = body.get("format", "step")
                export_dir = Path(body.get("dir", ".")) / pid
                result = self.worker.export(pid, fmt, export_dir)
                self._send_json(200, result)
                return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args) -> None:
        pass  # 靜默


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main() -> None:
    worker = FreeCadWorker()
    port = _find_free_port()
    token = secrets.token_hex(16)

    # 寫 token 檔（與現有 cad-worker 慣例一致）
    token_file = Path(os.environ.get("TOKEN_DIR", ".")) / "freecad_worker_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps({
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "engine": "freecad",
        "version": ".".join(FreeCAD.Version()[:3]),
    }), encoding="utf-8")

    _Handler.worker = worker
    _Handler.token = token

    server = HTTPServer(("127.0.0.1", port), _Handler)
    print(f"FreeCAD Worker listening on port {port}")
    print(f"Token file: {token_file}")
    print(f"FreeCAD version: {'.'.join(FreeCAD.Version()[:3])}")
    server.serve_forever()


if __name__ == "__main__":
    main()