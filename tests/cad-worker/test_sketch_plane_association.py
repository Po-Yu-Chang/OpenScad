import unittest
from unittest.mock import Mock, patch
from cad_worker.feature_graph import Feature, FeatureType
from cad_worker.adapters.build123d_adapter import Build123dAdapter
from cad_worker.adapters.freecad_adapter import FreeCADAdapter

class TestSketchPlaneAssociation(unittest.TestCase):
    def test_build123d_sketch_with_base_plane(self):
        """測試 build123d 草圖與基準面的關聯"""
        # 準備測試資料
        sketch_feature = Feature(
            id="sketch1",
            type=FeatureType.SKETCH,
            plane={"base": "XY", "offset": 5.0},
            sketch_entities=[
                {
                    "type": "rectangle",
                    "parameters": {"width": 10, "height": 5, "center_x": 0, "center_y": 0}
                }
            ]
        )
        
        # 建立 adapter 並測試
        adapter = Build123dAdapter()
        # 這裡需要 mock 相關的依賴，因為我們只測試關聯邏輯
        with patch.object(adapter, '_has_closed_profile', return_value=True):
            result = adapter._build_sketch(sketch_feature, {}, None, None)
            # 驗證結果不為 None
            self.assertIsNotNone(result)
    
    def test_build123d_sketch_with_datum_plane(self):
        """測試 build123d 草圖與自訂基準面的關聯"""
        # 準備測試資料
        sketch_feature = Feature(
            id="sketch1",
            type=FeatureType.SKETCH,
            plane={"base": "datum:plane1", "offset": 0.0},
            sketch_entities=[
                {
                    "type": "circle",
                    "parameters": {"radius": 5, "center_x": 0, "center_y": 0}
                }
            ]
        )
        
        # 模擬 graph 和 reference_geometry
        mock_graph = Mock()
        mock_graph.reference_geometry = [
            {
                "id": "plane1",
                "kind": "plane",
                "derived_geometry": {
                    "origin": [10, 10, 10],
                    "normal": [0, 0, 1]
                }
            }
        ]
        
        # 建立 adapter 並測試
        adapter = Build123dAdapter()
        adapter._current_graph = mock_graph
        with patch.object(adapter, '_has_closed_profile', return_value=True):
            result = adapter._build_sketch(sketch_feature, {}, mock_graph, None)
            # 驗證結果不為 None
            self.assertIsNotNone(result)
    
    def test_freecad_sketch_with_base_plane(self):
        """測試 FreeCAD 草圖與基準面的關聯"""
        # 準備測試資料
        sketch_feature = Feature(
            id="sketch1",
            type=FeatureType.SKETCH,
            plane={"base": "XZ", "offset": 3.0},
            sketch_entities=[
                {
                    "type": "rectangle",
                    "parameters": {"width": 8, "height": 4, "center_x": 0, "center_y": 0}
                }
            ]
        )
        
        # 建立 adapter 並測試
        adapter = FreeCADAdapter()
        # 這裡需要 mock 相關的依賴，因為我們只測試關聯邏輯
        with patch.object(adapter, '_has_closed_profile', return_value=True):
            result = adapter._build_sketch(sketch_feature, {}, Mock(), Mock())
            # 驗證結果不為 None
            self.assertIsNotNone(result)
    
    def test_freecad_sketch_with_datum_plane(self):
        """測試 FreeCAD 草圖與自訂基準面的關聯"""
        # 準備測試資料
        sketch_feature = Feature(
            id="sketch1",
            type=FeatureType.SKETCH,
            plane={"base": "datum:plane2", "offset": 0.0},
            sketch_entities=[
                {
                    "type": "circle",
                    "parameters": {"radius": 3, "center_x": 0, "center_y": 0}
                }
            ]
        )
        
        # 模擬 graph 和 reference_geometry
        mock_graph = Mock()
        mock_graph.reference_geometry = [
            {
                "id": "plane2",
                "kind": "plane",
                "derived_geometry": {
                    "origin": [5, 5, 5],
                    "normal": [0, 1, 0]
                }
            }
        ]
        
        # 建立 adapter 並測試
        adapter = FreeCADAdapter()
        with patch.object(adapter, '_has_closed_profile', return_value=True):
            result = adapter._build_sketch(sketch_feature, {}, mock_graph, Mock())
            # 驗證結果不為 None
            self.assertIsNotNone(result)

if __name__ == '__main__':
    unittest.main()