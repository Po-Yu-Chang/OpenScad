# OpenCad — 全本地 LLM 原生參數化機械 CAD

OpenCad 是一套以本地大型語言模型（LLM）為主要操作入口的參數化機械 CAD。使用者以繁體中文、尺寸表或參考圖片描述工程需求，由本地 LLM 轉換成受控的 CAD 特徵命令，再交由確定性的幾何引擎（OpenCascade BREP）建立、修改、驗證並輸出模型。

> **LLM 負責理解、規劃與選擇工具；CAD 引擎負責精確、可重現及可驗證的幾何計算。**

## 核心特色

- **全本地運行** — 模型、提示詞與設計資料不離開電腦，網路中斷仍可完整操作
- **參數化建模** — 可編輯草圖、特徵歷史樹、精確 BREP 實體，不是「看起來像零件的 STL」
- **語意化修改** — 「把這四個孔改成 M5」只更新目標特徵，不重寫整個模型
- **幾何驗證閉環** — 每次重建以 Bounding Box、孔數、壁厚、實體有效性等幾何資料驗證
- **工程輸出** — STEP（工程交換）、STL／3MF（3D 列印）、GLB（預覽）
- **跨平台** — Windows、macOS、Linux 同一套程式碼

## 架構總覽

```
繁中對話/圖片/尺寸表 → 本地 LLM Agent → Command JSON → 驗證與權限層
    → Feature Graph → build123d/FreeCAD Worker → OCCT BREP
    → STEP/STL/GLB 輸出 + 幾何驗證器 → 結果回饋（不符合則回到 LLM）
```

| 模組 | 選型 |
|---|---|
| 桌面應用程式 | C# Avalonia UI／.NET 8（跨平台） |
| 3D 顯示 | 跨平台 WebView＋Three.js |
| CAD 引擎 | build123d／FreeCAD＋OpenCascade（OCCT） |
| 本地 LLM | Ollama／llama.cpp（OpenAI-compatible、受限解碼） |
| 程序通訊 | localhost HTTP（FastAPI） |

完整規劃請見：[**OpenCad 架構規劃書**](Documemt/OpenCad_Local_AI_CAD_Architecture.md)

## 安裝

目標為三平台一鍵安裝包（由 CI/CD 於 GitHub Releases 自動發布）：

| 平台 | 格式 |
|---|---|
| Windows | `.exe` 安裝精靈 |
| macOS | `.dmg` |
| Linux | `.AppImage` |

> 專案目前處於 Phase 0 實作階段，以下為開發者建置指南。

## 開發者建置指南

### 必要條件

- **.NET SDK 8.0+** — [下載](https://dotnet.microsoft.com/download/dotnet/8.0)
- **Python 3.12+** — [下載](https://www.python.org/downloads/)
- **Ollama**（可選，LLM 功能）— [下載](https://ollama.ai)

### 建置 .NET 桌面應用程式

```bash
# 還原 NuGet 套件
dotnet restore

# 建置方案
dotnet build

# 執行桌面應用程式
dotnet run --project src/OpenCad.Desktop

# 執行單元測試
dotnet test
```

### 建置 Python CAD Worker

```bash
cd cad-worker

# 安裝相依套件
pip install -r requirements.txt

# 安裝測試相依套件
pip install -r ../tests/cad-worker/requirements-test.txt

# 啟動 CAD Worker（預設監聽 127.0.0.1:8765）
python run_worker.py

# 執行測試
cd ..
python -m pytest tests/cad-worker/ -v
```

### 專案結構

```
OpenScad/
├── schemas/                      # JSON Schema（Command、Feature、Project、Standard Parts）
├── cad-worker/                   # Python CAD Worker（FastAPI + build123d）
│   ├── cad_worker/
│   │   ├── server.py             # FastAPI 伺服器（API 端點）
│   │   ├── feature_graph.py      # Feature Graph 核心資料結構
│   │   ├── standard_parts.py     # ISO 273、NEMA 標準件查表
│   │   ├── adapters/             # build123d 引擎轉接器
│   │   ├── validators/           # 幾何驗證器
│   │   └── exporters/            # STEP/STL/GLB/PNG 匯出器
│   └── run_worker.py             # 啟動腳本
├── src/                          # C# .NET 8 專案
│   ├── OpenCad.Domain/           # 領域模型（Feature Graph、Command、Enums）
│   ├── OpenCad.Application/      # 應用層介面、版本管理、錯誤碼
│   ├── OpenCad.Infrastructure/   # CAD Worker HTTP 客戶端、程序生命週期管理
│   ├── OpenCad.Llm/              # Ollama LLM Provider（結構化輸出）
│   ├── OpenCad.Viewer/           # Three.js 3D 檢視器（WebView 橋接）
│   └── OpenCad.Desktop/          # Avalonia UI 桌面應用程式
├── tests/
│   ├── OpenCad.Tests/            # .NET xUnit 單元測試
│   └── cad-worker/               # Python pytest 單元測試
├── examples/                     # 範例模型
│   ├── nema17-mount/             # NEMA17 步進馬達安裝支架
│   ├── needle-box-5x10/          # 5x10 針座盒
│   └── esp32cam-enclosure/       # ESP32-CAM 外殼
├── .github/workflows/            # GitHub Actions CI/CD
└── Documemt/                     # 架構規劃書
```

## 開發路線

- **Phase 0** ✅ — 技術驗證：Avalonia＋Python Worker＋build123d＋GLB 顯示＋三平台 CI
  - ✅ JSON Schema（Command、Feature、Project、Standard Parts）
  - ✅ Python CAD Worker（FastAPI、Feature Graph、build123d Adapter、驗證器、匯出器）
  - ✅ .NET 8 Avalonia UI 桌面應用程式（MVVM 架構）
  - ✅ Ollama LLM Provider（結構化輸出）
  - ✅ Three.js 3D 檢視器
  - ✅ 單元測試（.NET 17 項 + Python 30 項）
  - ✅ 範例模型（NEMA17 支架、針座盒、ESP32-CAM 外殼）
  - ✅ GitHub Actions CI/CD（三平台矩陣）
- **Phase 1** — 單零件 AI CAD：Command Schema、Feature Graph、重建與驗證
- **Phase 2** — 選取與局部修改：Persistent Reference、差異比較
- **Phase 3** — 圖片與草圖輸入
- **Phase 4** — 組立、配合、干涉檢查、BOM
- **Phase 5** — 工程圖與製造規則

## 授權相依

build123d（Apache 2.0）、OCCT（LGPL 2.1 with exception）、FreeCAD（LGPL 2.0+）、Three.js（MIT）
