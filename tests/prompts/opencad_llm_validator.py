"""WP-H1 LLM 拒絕規則程式硬檢查——與 C# ValidateAgainstCatalog 對應。

雙層防護：system prompt + 程式硬檢查。本模組實作程式硬檢查部分。
"""
from typing import Any

UNSUPPORTED_FEATURES = frozenset({
    "thread", "knit", "trim_surface", "thicken", "delete_face",
    "helical_gear",
})

REPAIR_WHITELIST = frozenset({
    "SKETCH_NOT_CLOSED",
    "INVALID_STANDARD_PART",
    "REFERENCE_NOT_FOUND",
    "FILLET_RADIUS_TOO_LARGE",
    "CHAMFER_DISTANCE_TOO_LARGE",
})

MAX_REPAIR_RETRIES = 2


def validate_against_catalog(command: dict[str, Any]) -> tuple[bool, str]:
    """程式硬檢查——拒絕不支援的功能，防止 LLM 偷換近似幾何。

    回傳 (True, "") 表示通過；(False, reason) 表示被拒絕。
    """
    action = command.get("action", "")
    reasoning = command.get("reasoning", "") or ""

    # Check create_feature with unsupported type
    if action == "create_feature":
        feature = command.get("feature") or {}
        feat_type = (feature.get("type") or "").lower()
        if feat_type in UNSUPPORTED_FEATURES:
            return False, f"不支援的功能：{feat_type}。引擎不支援此特徵類型，不得以近似幾何替代。"

    # Check reasoning mentions unsupported but action is not rebuild (偷換)
    if action != "rebuild":
        for unsupported in UNSUPPORTED_FEATURES:
            if unsupported.lower() in reasoning.lower():
                return False, f"需求涉及不支援的功能：{unsupported}。應設 action=rebuild 並在 reasoning 中說明。不得以近似幾何替代。"

    return True, ""


def is_repairable(error_code: str) -> bool:
    """判斷錯誤碼是否在修復白名單中。"""
    return error_code in REPAIR_WHITELIST