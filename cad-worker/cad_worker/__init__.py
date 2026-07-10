"""OpenCad CAD Worker — Python 幾何引擎。

此 Worker 以獨立程序運行，透過 localhost HTTP（FastAPI）與主程式通訊。
Worker 負責：
  - 接收受控 JSON Command
  - 依 Feature Graph 重建模型
  - 幾何驗證
  - 輸出 STEP／STL／GLB／PNG

LLM 不得直接存取此 Worker 的任意 Python 執行功能。
所有命令必須通過 Command Schema 驗證。
"""

__version__ = "0.1.0"