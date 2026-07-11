"""命令契約驗證器——在 Worker 端驗證命令格式。

與 C# 端 CommandValidator 對稱，確保兩端用同一組規則。
"""
from __future__ import annotations

from typing import Any


class CommandValidator:
    """驗證命令格式與語意，回傳錯誤訊息列表。空列表表示通過。"""

    # 每個特徵類型的必要參數
    REQUIRED_PARAMS: dict[str, list[str]] = {
        "fillet": ["radius"],  # radius_mm 也接受
        "chamfer": ["radius"],
        "shell": ["thickness"],
        "rib": ["thickness"],
        "thin": ["length", "thickness"],
        "countersink": ["diameter"],
    }

    # 每個特徵類型的必要 input（必須指向上游）
    REQUIRES_INPUT: set[str] = {
        "pad", "revolve", "pocket", "hole", "fillet", "chamfer",
        "shell", "sweep", "loft", "mirror",
        "linear_pattern", "circular_pattern",
        "boolean_union", "boolean_difference", "boolean_intersection",
        "draft", "rib", "thin", "variable_fillet",
        "countersink", "cosmetic_thread",
    }

    # 必須有 references 的特徵
    REQUIRES_REFERENCES: set[str] = {"pocket"}

    # 必須有 sketch_entities 的特徵
    REQUIRES_SKETCH_ENTITIES: set[str] = {"sketch"}

    @classmethod
    def validate(cls, command: dict[str, Any]) -> list[str]:
        """驗證命令，回傳錯誤訊息列表。"""
        errors: list[str] = []
        action = command.get("action", "")
        if not action:
            errors.append("action 不得為空")
            return errors

        if action == "create_feature":
            cls._validate_create(command, errors)
        elif action == "update_feature":
            cls._validate_update(command, errors)
        elif action in ("delete_feature", "delete_feature_recursive"):
            if not command.get("target_feature_id"):
                errors.append(f"{action} 需要 target_feature_id")
        elif action in ("suppress_feature", "unsuppress_feature"):
            if not command.get("target_feature_id"):
                errors.append(f"{action} 需要 target_feature_id")
        elif action == "reorder_feature":
            if not command.get("target_feature_id"):
                errors.append("reorder_feature 需要 target_feature_id")
            params = command.get("parameters", {})
            if not params or "new_order" not in params:
                errors.append("reorder_feature 需要 parameters.new_order")
        elif action == "set_rollback":
            params = command.get("parameters", {})
            if not params or "rollback_position" not in params:
                errors.append("set_rollback 需要 parameters.rollback_position（null 或整數）")
        elif action in ("rebuild", "validate", "export", "set_material"):
            pass
        elif action == "create_reference_geometry":
            rg = command.get("reference_geometry")
            if rg is None:
                errors.append("create_reference_geometry 需要 reference_geometry 欄位")
            else:
                if not rg.get("id"):
                    errors.append("reference_geometry 需要 id")
                if not rg.get("kind"):
                    errors.append("reference_geometry 需要 kind")
                if not rg.get("definition"):
                    errors.append("reference_geometry 需要 definition")
        elif action in ("update_reference_geometry", "delete_reference_geometry"):
            if not command.get("target_feature_id"):
                errors.append(f"{action} 需要 target_feature_id")
            if action == "update_reference_geometry" and not command.get("reference_geometry"):
                errors.append("update_reference_geometry 需要 reference_geometry 欄位")
        else:
            errors.append(f"未知的 action: {action}")

        return errors

    @classmethod
    def _validate_create(cls, command: dict[str, Any], errors: list[str]) -> None:
        feature = command.get("feature")
        if feature is None:
            errors.append("create_feature 需要 feature 欄位")
            return

        fid = feature.get("feature_id", "")
        ftype = feature.get("type", "")

        if not fid:
            errors.append("feature.feature_id 不得為空")
        if not feature.get("name"):
            errors.append(f"特徵 {fid} 缺少 name")

        # sketch 必須有 sketch_entities
        if ftype in cls.REQUIRES_SKETCH_ENTITIES:
            entities = feature.get("sketch_entities", [])
            if not entities:
                errors.append(f"特徵 {fid}（{ftype}）缺少 sketch_entities——空草圖會導致 pad 失敗")

        # 必須有 input
        if ftype in cls.REQUIRES_INPUT:
            if not feature.get("input"):
                errors.append(f"特徵 {fid}（{ftype}）缺少 input——必須指向上游特徵")

        # 必須有 references
        if ftype in cls.REQUIRES_REFERENCES:
            refs = feature.get("references", [])
            if not refs:
                errors.append(f"特徵 {fid}（{ftype}）缺少 references——必須指向草圖輪廓")

        # 必須有特定參數
        if ftype in cls.REQUIRED_PARAMS:
            params = feature.get("parameters", {})
            for key in cls.REQUIRED_PARAMS[ftype]:
                # 接受 key 或 key_mm
                if key not in params and f"{key}_mm" not in params:
                    errors.append(f"特徵 {fid}（{ftype}）缺少 {key} 參數")

        # 數值正負檢查
        params = feature.get("parameters", {})
        for key in ("radius", "radius_mm", "thickness", "thickness_mm",
                     "diameter", "diameter_mm", "length", "length_mm"):
            if key in params:
                val = params[key]
                if isinstance(val, (int, float)) and val <= 0:
                    errors.append(f"特徵 {fid} {key} 必須 > 0，得到 {val}")

        # hole 必須有 diameter 或 standard_parts
        if ftype == "hole":
            params = feature.get("parameters", {})
            std_parts = feature.get("standard_parts", {})
            if "diameter" not in params and "diameter_mm" not in params and not std_parts:
                errors.append(f"特徵 {fid}（hole）缺少 diameter 或 standard_parts")

        # plane 格式檢查
        if ftype == "sketch":
            plane = feature.get("plane", {})
            if not plane:
                errors.append(f"特徵 {fid}（sketch）缺少 plane 定義")
            else:
                base = str(plane.get("base", "XY")).upper()
                if base not in ("XY", "XZ", "YZ"):
                    # 檢查是否為 datum 平面引用
                    if not (base.startswith("DATUM:") and len(base) > 6):
                        errors.append(f"特徵 {fid} plane.base 必須為 XY、XZ、YZ 或 datum:id，得到：{base}")

    @classmethod
    def _validate_update(cls, command: dict[str, Any], errors: list[str]) -> None:
        if not command.get("target_feature_id"):
            errors.append("update_feature 需要 target_feature_id")
        if (command.get("parameters") is None and
                command.get("standard_parts") is None and
                command.get("sketch_entities") is None and
                command.get("plane") is None and
                command.get("constraints") is None):
            errors.append("update_feature 需要 parameters、standard_parts、sketch_entities、plane 或 constraints 至少一項")