"""tests/prompts 的 pytest 設定。

本目錄有 __init__.py（是 package），pytest 只會把 tests/ 加進 sys.path，
導致 `from opencad_llm_validator import ...` 找不到模組——
把本目錄補進 sys.path 讓鄰居模組可直接 import。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
