"""FreeCAD Headless Worker — WP0-1 Spike.

以 FreeCAD 1.1.1 作為建模引擎，提供與現有 cad-worker 同風格的 HTTP API。
使用 Part workbench API（非 PartDesign）以確保 headless 穩定性。

啟動方式：(b) 以 Python 匯入 FreeCAD 模組
FreeCAD bin/ 加入 sys.path，然後 import FreeCAD, Part, Sketcher。
"""