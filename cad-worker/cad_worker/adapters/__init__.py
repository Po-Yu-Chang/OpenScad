"""OpenCad CAD Worker Adapters。

Adapter 負責將 Feature Graph 轉譯成各引擎的建模命令。
特徵只描述意圖與參數，由各 Adapter 負責轉譯（引擎中立）。
"""

from .build123d_adapter import Build123dAdapter

__all__ = ["Build123dAdapter"]

# FreeCAD Adapter — 可選，需要 FREECAD_DIR 環境變數
try:
    from .freecad_adapter import FreeCADAdapter, FREECAD_AVAILABLE
    __all__.append("FreeCADAdapter")
except ImportError:
    pass