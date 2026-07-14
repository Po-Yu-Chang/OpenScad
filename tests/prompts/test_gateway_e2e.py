"""WP-H1 §3.5 殘項——真 LiteLLM/OpenAI-compatible gateway 端到端測試。

跟 `test_llm_convergence.py`（大多是手寫 dict 自我斷言，非端到端）不同，
這裡的 5 個案例會真的呼叫 `~/.opencad/settings.json` 設定的 gateway，
驗證真實回應內容——這是 Master Plan §3.5 item 1 要求的「真實 LiteLLM
gateway 案例」。

**沒有設定真 gateway 時，全部 skip（不是 fail、更不是假裝 PASS）**——
`require_gateway()` 會在每個測試開頭檢查並給出明確原因。本機開發環境
目前 `llm.provider = "none"`，所以這些測試預期會 skip；要拿到真實輸出
證據，需要使用者設定一個真的 provider/base_url/api_key/model。

`TestGatewayClientPureLogic` 這組不需要網路，驗證 client 本身的邏輯
（設定檔解析、JSON 圍欄剝除）——這些是確定性的，一定要跑。
"""
from __future__ import annotations

import json
import os

import pytest

from gateway_client import (
    call_gateway,
    gateway_available,
    load_gateway_config,
    require_gateway,
    _extract_json,
    SYSTEM_PROMPT,
)


# ── 純邏輯測試（不需要網路，一定要跑）──

class TestGatewayClientPureLogic:
    def test_extract_json_plain(self):
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_extract_json_with_code_fence(self):
        text = '```json\n{"a": 1, "b": [1,2]}\n```'
        assert json.loads(_extract_json(text)) == {"a": 1, "b": [1, 2]}

    def test_extract_json_with_surrounding_prose(self):
        text = '這是結果：\n{"a": 1}\n希望有幫助！'
        assert json.loads(_extract_json(text)) == {"a": 1}

    def test_extract_json_no_json_raises(self):
        with pytest.raises(ValueError):
            _extract_json("沒有 JSON 在這裡")

    def test_load_gateway_config_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCAD_SETTINGS_PATH", str(tmp_path / "nonexistent.json"))
        assert load_gateway_config() is None

    def test_load_gateway_config_provider_none_returns_none(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"llm": {"provider": "none"}}), encoding="utf-8")
        monkeypatch.setenv("OPENCAD_SETTINGS_PATH", str(settings))
        assert load_gateway_config() is None

    def test_load_gateway_config_openai_provider_no_base_url_returns_none(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"llm": {"provider": "openai"}}), encoding="utf-8")
        monkeypatch.setenv("OPENCAD_SETTINGS_PATH", str(settings))
        assert load_gateway_config() is None

    def test_load_gateway_config_valid(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "llm": {"provider": "openai", "base_url": "http://gw:4000/v1", "api_key": "sk-x", "model": "coding"},
        }), encoding="utf-8")
        monkeypatch.setenv("OPENCAD_SETTINGS_PATH", str(settings))
        cfg = load_gateway_config()
        assert cfg == {"base_url": "http://gw:4000/v1", "api_key": "sk-x", "model": "coding"}

    def test_this_machine_has_no_gateway_configured(self):
        """誠實記錄現況：本機 ~/.opencad/settings.json 是 provider="none"，
        以下 5 個真 gateway 案例預期全部 skip。這不是本測試套件的缺陷，
        是 Master Plan §3.5 明文允許的「無 LLM 環境 skip」情境。"""
        if gateway_available():
            pytest.skip("本機已設定真 gateway——這個提示不適用，忽略即可")
        assert not gateway_available()


# ── 5 個真 gateway 端到端案例 ──

class TestRealGatewayMissingDimensions:
    """案例 1：缺尺寸提問——「做一個盒子」不給尺寸，真實回應必須提問。"""

    def test_box_without_dimensions_asks_for_missing_info(self):
        require_gateway()
        result = call_gateway(SYSTEM_PROMPT, "幫我做一個盒子。")
        assert result.get("missing_info"), (
            f"缺尺寸時 missing_info 應非空，實際回應：{json.dumps(result, ensure_ascii=False)[:500]}"
        )


class TestRealGatewayAmbiguousSelector:
    """案例 2：selector 歧義——「挖一個孔」未指定位置，必須要求點選。"""

    def test_hole_without_position_asks_for_selection(self):
        require_gateway()
        result = call_gateway(
            SYSTEM_PROMPT,
            "在一塊 100x80x10 的底板上挖一個直徑 5mm 的孔。",
        )
        assert result.get("missing_info"), (
            f"未指定孔位時應提問位置，實際回應：{json.dumps(result, ensure_ascii=False)[:500]}"
        )


class TestRealGatewayUnsupportedRejection:
    """案例 3：不支援拒絕——要求 thread（螺紋）特徵，必須明確拒絕。"""

    def test_thread_feature_rejected(self):
        require_gateway()
        result = call_gateway(
            SYSTEM_PROMPT,
            "幫我在這根軸上加工出螺紋（thread），M8 x 1.25。",
        )
        steps = result.get("steps", [])
        feature_types = [s.get("feature_type", "") for s in steps]
        assert "thread" not in feature_types, "不得直接建立 thread 特徵"
        # 拒絕的證據：missing_info/summary/warnings 至少一處提到無法支援
        text_blob = " ".join([
            result.get("summary", ""),
            " ".join(result.get("missing_info", [])),
            " ".join(result.get("warnings", [])),
        ])
        assert any(kw in text_blob for kw in ("不支援", "無法", "thread", "螺紋")), (
            f"應在 summary/missing_info/warnings 中說明不支援，實際回應：{json.dumps(result, ensure_ascii=False)[:500]}"
        )


class TestRealGatewayNoApproximation:
    """案例 4：防偷換——要求「螺旋齒輪」，不得偷換成圓柱近似。"""

    def test_helical_gear_not_approximated_as_cylinder(self):
        require_gateway()
        result = call_gateway(
            SYSTEM_PROMPT,
            "幫我做一個螺旋齒輪（helical gear），模數 2、齒數 20。",
        )
        steps = result.get("steps", [])
        # 不得只用一個 cylinder/circle pad 就交差了事，假裝完成了齒輪
        feature_types = [s.get("feature_type", "") for s in steps]
        assert "helical_gear" not in feature_types
        looks_like_bare_cylinder_substitute = (
            len(steps) <= 2 and
            all(t in ("sketch", "pad") for t in feature_types) and
            not result.get("missing_info") and
            "不支援" not in result.get("summary", "") and
            "無法" not in result.get("summary", "")
        )
        assert not looks_like_bare_cylinder_substitute, (
            f"疑似用光禿禿的 sketch+pad 圓柱偷換螺旋齒輪，未說明限制："
            f"{json.dumps(result, ensure_ascii=False)[:500]}"
        )


class TestRealGatewayMultiTurnReference:
    """案例 5：多輪指涉——第二輪用「它」指涉第一輪建立的物件，須正確承接。"""

    def test_second_turn_refers_back_to_first(self):
        require_gateway()
        first = call_gateway(SYSTEM_PROMPT, "做一個 60x40x10 的長方體。")
        history = [
            {"role": "user", "content": "做一個 60x40x10 的長方體。"},
            {"role": "assistant", "content": json.dumps(first, ensure_ascii=False)},
        ]
        second = call_gateway(SYSTEM_PROMPT, "把它的長度改成 80mm。", history=history)
        # 第二輪應該理解「它」＝第一輪的長方體，產生 update_feature 風格的步驟
        # （用 feature_type 或 parameters 提到長度變更），而不是重新問「什麼是它」。
        assert second.get("steps") or second.get("missing_info"), (
            f"第二輪應該有實質回應（steps 或進一步澄清），不應完全空白："
            f"{json.dumps(second, ensure_ascii=False)[:500]}"
        )
        if second.get("missing_info"):
            pytest.fail(
                f"多輪指涉失敗——「它」應該能從對話歷史解析出來，不該回頭問使用者："
                f"{json.dumps(second, ensure_ascii=False)[:500]}"
            )
