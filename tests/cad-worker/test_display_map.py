"""WP0-3 display_map 引擎層驗證。

測試範圍（Master Plan §WP0-3 line 185）：
1. face 數 > 0
2. 每面 triangle_range 相鄰不重疊
3. 總三角形數等於 GLB 三角形數
4. hole 特徵至少貢獻一個 surface_type=="cylinder" 的面
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cad_worker.adapters.build123d_adapter import Build123dAdapter
from cad_worker.exporters import GlbExporter, build_display_map
from cad_worker.feature_graph import FeatureGraph


EXAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples"
)


def _load_example(name: str) -> FeatureGraph:
    """載入範例 Feature Graph。"""
    path = os.path.join(EXAMPLES_DIR, name, "features.json")
    return FeatureGraph.load(Path(path))


def _build_and_tessellate(name: str):
    """重建範例並產生 GLB + display_map（同一程式碼路徑）。"""
    graph = _load_example(name)
    adapter = Build123dAdapter()
    build_result = adapter.build_with_trace(graph)
    return build_result.part, build_result.trace


class TestDisplayMap:
    """display_map 引擎層驗證（Master Plan §WP0-3）。"""

    @pytest.fixture
    def nema17(self):
        part, trace = _build_and_tessellate("nema17-mount")
        # 產生 display_map
        display_map = build_display_map(part, trace, mesh_revision=1)
        return part, trace, display_map

    def test_face_count_positive(self, nema17):
        """face 數 > 0。"""
        _, _, display_map = nema17
        assert len(display_map["faces"]) > 0, "display_map 應至少有一個面"

    def test_triangle_ranges_non_overlapping(self, nema17):
        """每面 triangle_range 相鄰不重疊。"""
        _, _, display_map = nema17
        ranges = [f["triangle_range"] for f in display_map["faces"]]
        # 排序後檢查相鄰不重疊
        sorted_ranges = sorted(ranges, key=lambda r: r[0])
        for i in range(1, len(sorted_ranges)):
            prev_end = sorted_ranges[i - 1][1]
            curr_start = sorted_ranges[i][0]
            assert curr_start >= prev_end, (
                f"triangle_range 重疊：[{sorted_ranges[i-1]}] 與 [{sorted_ranges[i]}]"
            )

    def test_total_triangles_matches_glb(self, nema17, tmp_path):
        """總三角形數等於 GLB 三角形數。"""
        part, trace, display_map = nema17
        # 用 export_per_face 產生 GLB（與 display_map 同程式碼路徑）
        glb_path = tmp_path / "model.glb"
        glb_display_map = GlbExporter.export_per_face(part, glb_path, trace)

        # display_map 的總三角形數 = 最後一個面的 triangle_range[1]
        total_from_map = display_map["faces"][-1]["triangle_range"][1] if display_map["faces"] else 0
        total_from_glb = glb_display_map["faces"][-1]["triangle_range"][1] if glb_display_map["faces"] else 0

        assert total_from_map == total_from_glb, (
            f"display_map 三角形數 {total_from_map} != GLB 三角形數 {total_from_glb}"
        )
        assert total_from_map > 0, "應有三角形"

    def test_hole_contributes_cylinder_face(self, nema17):
        """hole 特徵至少貢獻一個 surface_type=="cylinder" 的面。"""
        _, _, display_map = nema17
        cylinder_faces = [f for f in display_map["faces"] if f["surface_type"] == "cylinder"]
        assert len(cylinder_faces) > 0, (
            "hole 特徵應至少貢獻一個 cylinder 面，"
            f"但所有面為 {[f['surface_type'] for f in display_map['faces']]}"
        )

    def test_display_map_has_mesh_revision(self, nema17):
        """display_map 包含 mesh_revision。"""
        _, _, display_map = nema17
        assert "mesh_revision" in display_map
        assert display_map["mesh_revision"] == 1

    def test_faces_have_required_fields(self, nema17):
        """每個 face entry 包含所有必要欄位。"""
        _, _, display_map = nema17
        required = {"face_id", "brep_face_ref", "source_feature_id", "surface_type",
                    "triangle_range", "area_mm2", "centroid"}
        for face in display_map["faces"]:
            missing = required - set(face.keys())
            assert not missing, f"face {face.get('face_id')} 缺少欄位: {missing}"

    def test_edges_have_required_fields(self, nema17):
        """每個 edge entry 包含所有必要欄位。"""
        _, _, display_map = nema17
        if not display_map["edges"]:
            pytest.skip("此範例無邊資料")
        required = {"display_edge_id", "brep_edge_ref", "source_feature_id", "polyline"}
        for edge in display_map["edges"]:
            missing = required - set(edge.keys())
            assert not missing, f"edge {edge.get('display_edge_id')} 缺少欄位: {missing}"

    def test_triangle_range_is_list_of_two(self, nema17):
        """triangle_range 是 [start, end) 格式。"""
        _, _, display_map = nema17
        for face in display_map["faces"]:
            r = face["triangle_range"]
            assert isinstance(r, list), f"triangle_range 不是 list: {r}"
            assert len(r) == 2, f"triangle_range 長度不為 2: {r}"
            assert r[0] < r[1], f"triangle_range start >= end: {r}"

    def test_centroid_is_3d(self, nema17):
        """centroid 是 [x, y, z] 三維座標。"""
        _, _, display_map = nema17
        for face in display_map["faces"]:
            c = face["centroid"]
            assert isinstance(c, list), f"centroid 不是 list: {c}"
            assert len(c) == 3, f"centroid 不是三維: {c}"