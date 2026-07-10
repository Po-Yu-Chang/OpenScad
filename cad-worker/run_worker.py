#!/usr/bin/env python3
"""OpenCad CAD Worker 啟動入口。

使用方式：
  python run_worker.py

啟動後監聯 127.0.0.1:8765，並印出工作階段 Token。
主程式（Avalonia）需使用此 Token 呼叫 API。
"""

from cad_worker.server import main

if __name__ == "__main__":
    main()