"""OpenCad Exporters — 模型輸出。

負責將 BREP 實體輸出為 STEP、STL、GLB、PNG 等格式。
也負責產生 display_map（面/邊的拓撲對應表，供 viewer 精確 picking）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

# GeomType → surface_type 字串對應表
_SURFACE_TYPE_MAP: dict[str, str] = {}


def _init_surface_type_map() -> None:
    """初始化 GeomType → surface_type 字串的對應表。"""
    global _SURFACE_TYPE_MAP
    try:
        from build123d import GeomType
        _SURFACE_TYPE_MAP = {
            GeomType.PLANE: "plane",
            GeomType.CYLINDER: "cylinder",
            GeomType.CONE: "cone",
            GeomType.SPHERE: "sphere",
            GeomType.TORUS: "torus",
        }
    except ImportError:
        pass


_init_surface_type_map()


def _geom_type_to_surface_type(geom_type: Any) -> str:
    """將 build123d GeomType 或 FreeCAD 字串轉為 display_map 的 surface_type 字串。"""
    # build123d GeomType enum 路徑
    if _SURFACE_TYPE_MAP:
        result = _SURFACE_TYPE_MAP.get(geom_type)
        if result:
            return result
    # FreeCAD 字串路徑（FreeCADFaceProxy 回傳大寫字串）
    if isinstance(geom_type, str):
        lower = geom_type.lower()
        str_map = {
            "plane": "plane",
            "cylinder": "cylinder",
            "cone": "cone",
            "sphere": "sphere",
            "torus": "torus",
        }
        return str_map.get(lower, "other")
    return "other"


def _tessellate_with_map(
    part: Any,
    trace: Any | None = None,
) -> tuple[list[list[float]], list[list[int]], list[dict[str, Any]], list[dict[str, Any]]]:
    """單一 tessellation pass：逐面三角化＋逐邊離散化。

    build_display_map 與 GlbExporter.export_per_face 都走這裡——
    同一段程式碼同時產生 mesh buffer 與 display_map，
    保證 GLB 三角形順序與 triangle_range 永遠一致（picking 契約的根基）。

    Returns:
        (all_vertices, all_faces, faces_data, edges_data)
    """
    all_vertices: list[list[float]] = []
    all_faces: list[list[int]] = []
    faces_data: list[dict[str, Any]] = []
    edges_data: list[dict[str, Any]] = []

    if part is None:
        return all_vertices, all_faces, faces_data, edges_data

    try:
        part_faces = list(part.faces())
        part_edges = list(part.edges())
    except Exception:
        return all_vertices, all_faces, faces_data, edges_data

    # ── 面：逐面 tessellate，串接 buffer 並記錄 triangle_range（含頭不含尾）──
    vertex_offset = 0
    triangle_offset = 0
    for i, face in enumerate(part_faces):
        try:
            verts, tris = face.tessellate(0.1)
        except Exception:
            continue
        if not tris:
            continue

        num_tris = len(tris)

        for v in verts:
            all_vertices.append([v.X, v.Y, v.Z])
        for t in tris:
            all_faces.append([t[0] + vertex_offset, t[1] + vertex_offset, t[2] + vertex_offset])
        vertex_offset += len(verts)

        tri_start = triangle_offset
        tri_end = triangle_offset + num_tris

        s_type = _geom_type_to_surface_type(face.geom_type)
        try:
            c = face.center()
            centroid = [round(c.X, 2), round(c.Y, 2), round(c.Z, 2)]
        except Exception:
            centroid = [0.0, 0.0, 0.0]

        try:
            area = round(float(face.area), 2)
        except Exception:
            area = 0.0

        source_fid = ""
        if trace is not None:
            fid = trace.resolve_face_feature(face)
            if fid:
                source_fid = fid

        faces_data.append({
            "face_id": f"f-{i}",
            "brep_face_ref": f"{source_fid or 'unknown'}/result/face/{i}",
            "source_feature_id": source_fid or "unknown",
            "surface_type": s_type,
            "triangle_range": [tri_start, tri_end],
            "area_mm2": area,
            "centroid": centroid,
        })

        triangle_offset = tri_end

    # ── 邊：離散化為 polyline（弦高容差 ≈ 0.1mm；至少 2 點，曲線依長度分段）──
    for i, edge in enumerate(part_edges):
        try:
            edge_len = float(edge.length)
        except Exception:
            edge_len = 0.0

        if edge_len < 0.01:
            continue
        num_samples = max(2, min(100, int(edge_len / 0.5) + 2))

        try:
            pts = edge.positions([t / (num_samples - 1) for t in range(num_samples)])
            polyline = [[round(p.X, 3), round(p.Y, 3), round(p.Z, 3)] for p in pts]
        except Exception:
            try:
                sp = edge.start_point()
                ep = edge.end_point()
                polyline = [
                    [round(sp.X, 3), round(sp.Y, 3), round(sp.Z, 3)],
                    [round(ep.X, 3), round(ep.Y, 3), round(ep.Z, 3)],
                ]
            except Exception:
                continue

        source_fid = ""
        if trace is not None:
            fid = trace.resolve_edge_feature(edge)
            if fid:
                source_fid = fid

        edges_data.append({
            "display_edge_id": f"e-{i}",
            "brep_edge_ref": f"{source_fid or 'unknown'}/result/edge/{i}",
            "source_feature_id": source_fid or "unknown",
            "polyline": polyline,
        })

    return all_vertices, all_faces, faces_data, edges_data


def build_display_map(
    part: Any,
    trace: Any | None = None,
    mesh_revision: int = 0,
) -> dict[str, Any]:
    """由 BREP 實體產生 display_map（面/邊的拓撲對應表）。

    與 GlbExporter.export_per_face 共用 _tessellate_with_map 同一個 pass，
    確保 display_map 的 triangle_range 與 GLB 三角形順序一致。

    Returns:
        display_map dict（符合 schemas/display_map.schema.json）
    """
    _, _, faces_data, edges_data = _tessellate_with_map(part, trace)
    return {
        "mesh_revision": mesh_revision,
        "faces": faces_data,
        "edges": edges_data,
    }


class StepExporter:
    """輸出 STEP 格式（保留精確幾何，用於工程交換）。"""

    @staticmethod
    def export(part: Any, path: Path) -> None:
        # FreeCAD 路徑：part 可能是 FreeCADShapeWrapper 或 FreeCAD shape
        freecad_shape = getattr(part, "_freecad_shape", None)
        if freecad_shape is None:
            # 嘗試直接使用（可能是裸 FreeCAD shape）
            import inspect
            if hasattr(part, "exportStep"):
                freecad_shape = part
        if freecad_shape is not None:
            freecad_shape.exportStep(str(path))
            return
        # build123d 路徑
        try:
            from build123d import export_step
            export_step(part, str(path))
        except ImportError:
            # 嘗試 OCP 直接匯出
            try:
                from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
                writer = STEPControl_Writer()
                writer.Transfer(part.wrapped, STEPControl_AsIs)
                writer.Write(str(path))
            except ImportError:
                raise ImportError("無法匯出 STEP：build123d 或 OCP 未安裝")


class StlExporter:
    """輸出 STL 格式（三角化網格，用於 3D 列印）。"""

    @staticmethod
    def export(part: Any, path: Path) -> None:
        # FreeCAD 路徑
        freecad_shape = getattr(part, "_freecad_shape", None)
        if freecad_shape is None:
            if hasattr(part, "exportStl"):
                freecad_shape = part
        if freecad_shape is not None:
            freecad_shape.exportStl(str(path))
            return
        # build123d 路徑
        try:
            from build123d import export_stl
            export_stl(part, str(path))
        except ImportError:
            try:
                from OCP.StlAPI import StlAPI_Writer
                writer = StlAPI_Writer()
                writer.Write(part.wrapped, str(path))
            except ImportError:
                raise ImportError("無法匯出 STL：build123d 或 OCP 未安裝")


def _part_to_trimesh(part: Any):
    """BREP → trimesh，經 STL 中介格式三角化。

    build123d 的 Mesher 不能直接產生記憶體網格物件（其 API 為
    add_shape + write 檔案），因此統一走 STL 中介路徑。
    """
    import tempfile
    import trimesh
    tmp_stl = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp_stl.close()
    try:
        StlExporter.export(part, Path(tmp_stl.name))
        mesh = trimesh.load(tmp_stl.name)
    finally:
        Path(tmp_stl.name).unlink(missing_ok=True)
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    return mesh


class GlbExporter:
    """輸出 GLB 格式（輕量、瀏覽器顯示方便）。

    使用逐面 tessellation，三角形順序與 display_map 一致（同邏輯產生）。
    """

    @staticmethod
    def export(part: Any, path: Path) -> None:
        try:
            import trimesh
        except ImportError:
            raise ImportError("無法匯出 GLB：trimesh 未安裝")
        mesh = _part_to_trimesh(part)
        scene = trimesh.Scene(mesh)
        glb_data = scene.export(file_type="glb")
        path.write_bytes(glb_data)

    @staticmethod
    def export_per_face(part: Any, path: Path, trace: Any | None = None) -> dict[str, Any]:
        """逐面 tessellate 產生 GLB，同時回傳 display_map。

        GLB 三角形順序與 display_map 的 triangle_range 完全一致——
        逐面 tessellate 後串接，同一段程式碼同時產生 mesh 與 map。

        Args:
            part: build123d Part
            path: GLB 輸出路徑
            trace: TopologyTrace（含 feature→face provenance）

        Returns:
            display_map dict（符合 schemas/display_map.schema.json）
        """
        try:
            import trimesh
            import numpy as np
        except ImportError:
            raise ImportError("無法匯出 GLB：trimesh/numpy 未安裝")

        if part is None:
            # 空模型——產生最小 GLB 與空 map
            empty_mesh = trimesh.Trimesh(vertices=[[0,0,0]], faces=[[0,0,0]])
            scene = trimesh.Scene(empty_mesh)
            path.write_bytes(scene.export(file_type="glb"))
            return {"mesh_revision": 0, "faces": [], "edges": []}

        # 與 build_display_map 共用同一個 tessellation pass
        all_vertices, all_faces, faces_data, edges_data = _tessellate_with_map(part, trace)

        # ── 產生 GLB ──
        if all_vertices and all_faces:
            mesh = trimesh.Trimesh(
                vertices=np.array(all_vertices, dtype=np.float64),
                faces=np.array(all_faces, dtype=np.int64),
            )
            # 修正 winding（trimesh 會自動修正 normals）
            mesh.fix_normals()
        else:
            mesh = trimesh.Trimesh(vertices=[[0,0,0]], faces=[[0,0,0]])

        scene = trimesh.Scene(mesh)
        glb_data = scene.export(file_type="glb")
        path.write_bytes(glb_data)

        display_map = {
            "mesh_revision": 0,  # 由 server 層設定
            "faces": faces_data,
            "edges": edges_data,
        }
        return display_map


class PngExporter:
    """輸出 PNG 預覽（離屏渲染，不依賴桌面 GUI）。"""

    @staticmethod
    def export(part: Any, path: Path, width: int = 800, height: int = 600) -> None:
        try:
            import trimesh
        except ImportError:
            raise ImportError("無法匯出 PNG：trimesh 未安裝")
        mesh = _part_to_trimesh(part)
        # 離屏渲染
        scene = trimesh.Scene(mesh)
        png_data = scene.save_image(resolution=[width, height])
        path.write_bytes(png_data)


class ExportManager:
    """匯出管理器——統一管理所有格式的匯出。"""

    def __init__(self) -> None:
        self._exporters = {
            "step": StepExporter,
            "stl": StlExporter,
            "glb": GlbExporter,
            "png": PngExporter,
        }

    def export(self, part: Any, fmt: str, output_dir: Path, filename: str = "model") -> Path:
        """匯出模型。

        Args:
            part: build123d Part
            fmt: 格式 step / stl / glb / png / all
            output_dir: 輸出目錄
            filename: 檔名（不含副檔名）

        Returns:
            最後匯出的檔案路徑（all 時回傳最後一個）
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        last_path = output_dir / f"{filename}.{fmt}"

        if fmt == "all":
            last_path = None
            for f, exporter in self._exporters.items():
                p = output_dir / f"{filename}.{f}"
                exporter.export(part, p)
                last_path = p
        else:
            exporter = self._exporters.get(fmt)
            if exporter is None:
                raise ValueError(f"不支援的匯出格式: {fmt}")
            exporter.export(part, last_path)

        return last_path