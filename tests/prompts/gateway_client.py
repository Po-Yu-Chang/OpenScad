"""真實 LiteLLM/OpenAI-compatible gateway HTTP client——供 WP-H1 §3.5
「真 gateway 端到端」測試使用。

與 `src/OpenCad.Llm/OpenAiCompatibleLlmProvider.cs` 走同一套契約：
- `POST {base_url}/chat/completions`
- messages = [{"role":"system",...}, {"role":"user",...}]（history 插在中間）
- `response_format: {"type":"json_object"}`，遇 400/422 退回不帶此欄位重試一次
- 回應在 `choices[0].message.content`，內容需要 `_extract_json` 去 ```json 圍欄
- `Authorization: Bearer <api_key>`（api_key 為空則不帶這個 header）

這裡用 Python 直接打同一個 gateway（而非呼叫 C# 或複製一份邏輯到別處），
驗證的是「真實 LLM 對這組提示詞的實際回應」，不是「C# 程式碼本身」。

**無 LLM 環境時全部 skip，不得 fail 或假裝 PASS**——見 Master Plan §3.5。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def _settings_path() -> Path:
    override = os.environ.get("OPENCAD_SETTINGS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".opencad" / "settings.json"


def load_gateway_config() -> dict[str, Any] | None:
    """讀取 `~/.opencad/settings.json` 的 llm 設定。

    `provider` 不是 "openai"/"auto"，或沒有 `base_url`，或檔案不存在／格式
    錯誤——一律回傳 None（代表沒有可用的真 gateway，呼叫端應該 skip）。
    """
    path = _settings_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    llm = data.get("llm", {})
    provider = llm.get("provider", "none")
    if provider not in ("openai", "auto"):
        return None
    base_url = llm.get("base_url", "")
    if not base_url:
        return None
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": llm.get("api_key", ""),
        "model": llm.get("model", ""),
    }


GATEWAY_CONFIG = load_gateway_config() if HTTPX_AVAILABLE else None


def gateway_available() -> bool:
    return GATEWAY_CONFIG is not None


SKIP_REASON = (
    "沒有可用的真 LLM gateway（~/.opencad/settings.json 的 llm.provider "
    "須為 openai 或 auto 且要有 base_url；本機目前是 provider=\"none\"，"
    "或 httpx 未安裝）——Master Plan §3.5 明文允許「無 LLM 環境 skip」，"
    "不得假裝 PASS。"
)


def require_gateway() -> None:
    """在測試開頭呼叫；沒有真 gateway 時乾淨 skip 並附原因。"""
    if not HTTPX_AVAILABLE:
        pytest.skip(SKIP_REASON + "（httpx 未安裝）")
    if not gateway_available():
        pytest.skip(SKIP_REASON)


def _extract_json(content: str) -> str:
    """與 `LlmProviderBase.cs` 的 `ExtractJson` 對齊：去 ```json 圍欄，
    取第一個 `{` 到最後一個 `}` 的片段。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"回應中找不到 JSON 物件：{text[:300]}")
    return text[start:end + 1]


def call_gateway(
    system_prompt: str,
    user_prompt: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """呼叫真 gateway，回傳解析後的 JSON dict。

    Args:
        system_prompt: system role 內容（含規則與 schema 說明）。
        user_prompt: 這一輪的使用者需求。
        history: 先前輪次 [{"role": "user"/"assistant", "content": "..."}]，
            插在 system 與這一輪 user 訊息之間——供多輪指涉測試使用。
    """
    if GATEWAY_CONFIG is None:
        raise RuntimeError("gateway 未設定，呼叫前應先用 require_gateway() 檢查")

    headers = {"Content-Type": "application/json"}
    if GATEWAY_CONFIG["api_key"]:
        headers["Authorization"] = f"Bearer {GATEWAY_CONFIG['api_key']}"

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    body: dict[str, Any] = {
        "model": GATEWAY_CONFIG["model"],
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    url = f"{GATEWAY_CONFIG['base_url']}/chat/completions"
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=body, headers=headers)
        if resp.status_code in (400, 422):
            # 部分 gateway/模型不支援 response_format——退回不帶此欄位重試一次，
            # 與 OpenAiCompatibleLlmProvider.cs 的 fallback 邏輯對齊。
            body.pop("response_format", None)
            resp = client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return json.loads(_extract_json(content))


# ── 與 LlmProviderBase.cs 的 BuildSystemPrompt() 對齊的系統提示詞 ──
# 逐條對應（22 條規則原文譯自 C#），確保測的是同一組真實指令，不是
# 簡化過、比較容易通過的替身版本。

SYSTEM_PROMPT = """你是 OpenCad 的 AI 建模助手。你的任務是：
1. 理解使用者的繁體中文工程設計需求。
2. 將需求轉換成受控的 CAD 命令（OpenCad Command JSON）。
3. 你只能透過受控命令操作模型，不能直接存取任意檔案或執行任意程式碼。
4. 標準件（如螺絲孔徑、NEMA 安裝尺寸）只選擇「標準與等級」，數值由引擎查表。
5. 如果需求中有缺少或矛盾的條件，必須提問，不得自行猜測。
6. 單位以 mm 為主。如果使用者混用單位，自動換算。
7. sketch 特徵必須指定 plane.base：XY=上基準面（俯視）、XZ=前基準面（正視）、YZ=右基準面（側視）。offset 為沿法線偏移量(mm)，預設 0。
20. WP-H1 拒絕規則（系統提示＋程式硬檢查雙層）：
    a. 缺尺寸→必須提問，不得自行猜測數值（如「做一個盒子」無尺寸→提問，不可用任意值）。
    b. selector 歧義→要求使用者點選（如「挖一個孔」未指定位置→提問，回傳 missing_info）。
    c. 不支援的功能→明確說明不支援，不得偷換近似幾何（如「螺旋齒輪」→拒絕，不可改為圓柱）。
       目前不支援清單（唯一真相）：thread、knit、trim_surface、thicken、delete_face、helical_gear。
    d. 不得靜默改尺寸/刪特徵——所有變更必須在 reasoning 中說明。
21. WP-H1 Capability payload：模型不得憑 prompt 記憶猜功能——只能使用 feature_catalog 中列出的型別與參數。
重要：你的輸出必須是合法 JSON，符合以下 Schema：
{
  "type": "object",
  "properties": {
    "steps": {"type": "array", "items": {"type": "object",
      "properties": {
        "description": {"type": "string"},
        "feature_type": {"type": "string"},
        "parameters": {"type": "object"},
        "sketch_entities": {"type": "array"},
        "plane": {"type": "object"}
      }}},
    "summary": {"type": "string"},
    "warnings": {"type": "array", "items": {"type": "string"}},
    "missing_info": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["steps", "summary"]
}
"""
