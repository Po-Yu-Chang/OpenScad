"""OpenCad Exporters — 模型輸出。

負責將 BREP 實體輸出為 STEP、STL、GLB、PNG 等格式。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class StepExporter:
    """輸出 STEP 格式（保留精確幾何，用於工程交換）。"""

    @staticmethod
    def export(part: Any, path: Path) -> None:
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
    """輸出 GLB 格式（輕量、瀏覽器顯示方便）。"""

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