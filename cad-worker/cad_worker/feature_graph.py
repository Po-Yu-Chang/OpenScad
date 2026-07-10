"""Feature Graph — OpenCad 的核心資料結構。

保存設計意圖和依賴關係，不能只保存最終 STL。
每個特徵至少需要：feature_id、type、name、input、parameters、references、
source、llm_description、validation、rebuild_status、error_message。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class FeatureType(str, Enum):
    SKETCH = "sketch"
    PAD = "pad"
    POCKET = "pocket"
    REVOLVE = "revolve"
    HOLE = "hole"
    LINEAR_PATTERN = "linear_pattern"
    CIRCULAR_PATTERN = "circular_pattern"
    MIRROR = "mirror"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    SHELL = "shell"
    BOOLEAN_UNION = "boolean_union"
    BOOLEAN_DIFFERENCE = "boolean_difference"
    BOOLEAN_INTERSECTION = "boolean_intersection"


class RebuildStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"


class FeatureSource(str, Enum):
    LLM = "llm"
    USER = "user"
    IMPORTED = "imported"


@dataclass
class ParameterValue:
    """帶單位的參數值。內部一律以 mm 為正準單位。"""
    value: float
    unit: str = "mm"

    def to_mm(self) -> float:
        """將值轉換為 mm。"""
        if self.unit == "mm":
            return self.value
        elif self.unit == "cm":
            return self.value * 10.0
        elif self.unit == "m":
            return self.value * 1000.0
        elif self.unit == "inch":
            return self.value * 25.4
        elif self.unit in ("deg", "rad"):
            return self.value  # 角度不換算
        return self.value

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParameterValue":
        return cls(value=float(d["value"]), unit=d.get("unit", "mm"))


@dataclass
class ValidationSpec:
    """特徵驗證條件。"""
    min_thickness_mm: float | None = None
    must_be_single_solid: bool | None = None
    expected_hole_count: int | None = None
    expected_bounding_box: dict[str, list[float]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "ValidationSpec | None":
        if d is None:
            return None
        return cls(**d)


@dataclass
class Feature:
    """Feature Graph 中的特徵節點。"""
    feature_id: str
    type: FeatureType
    name: str
    input: str | None = None
    references: list[str] = field(default_factory=list)
    sketch_entities: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    standard_parts: dict[str, Any] = field(default_factory=dict)
    validation: ValidationSpec | None = None
    source: FeatureSource = FeatureSource.LLM
    llm_description: str = ""
    rebuild_status: RebuildStatus = RebuildStatus.PENDING
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "feature_id": self.feature_id,
            "type": self.type.value if isinstance(self.type, FeatureType) else self.type,
            "name": self.name,
            "input": self.input,
            "references": self.references,
            "sketch_entities": self.sketch_entities,
            "constraints": self.constraints,
            "parameters": self.parameters,
            "standard_parts": self.standard_parts,
            "validation": self.validation.to_dict() if self.validation else None,
            "source": self.source.value if isinstance(self.source, FeatureSource) else self.source,
            "llm_description": self.llm_description,
            "rebuild_status": self.rebuild_status.value if isinstance(self.rebuild_status, RebuildStatus) else self.rebuild_status,
            "error_message": self.error_message,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Feature":
        validation = ValidationSpec.from_dict(d.get("validation"))
        return cls(
            feature_id=d["feature_id"],
            type=FeatureType(d["type"]),
            name=d["name"],
            input=d.get("input"),
            references=d.get("references", []),
            sketch_entities=d.get("sketch_entities", []),
            constraints=d.get("constraints", []),
            parameters=d.get("parameters", {}),
            standard_parts=d.get("standard_parts", {}),
            validation=validation,
            source=FeatureSource(d.get("source", "llm")),
            llm_description=d.get("llm_description", ""),
            rebuild_status=RebuildStatus(d.get("rebuild_status", "pending")),
            error_message=d.get("error_message", ""),
        )


class FeatureGraph:
    """Feature Graph——管理特徵依賴關係與拓撲排序。

    特徵只描述意圖與參數，由各 Adapter 負責轉譯（引擎中立）。
    """

    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}

    def add_feature(self, feature: Feature) -> None:
        """加入特徵。feature_id 不得重複。"""
        if feature.feature_id in self._features:
            raise ValueError(f"feature_id '{feature.feature_id}' 已存在")
        self._features[feature.feature_id] = feature

    def get_feature(self, feature_id: str) -> Feature | None:
        return self._features.get(feature_id)

    def update_feature(
        self, feature_id: str, parameters: dict[str, Any] | None = None,
        standard_parts: dict[str, Any] | None = None,
        sketch_entities: list[dict[str, Any]] | None = None,
    ) -> Feature:
        """更新特徵參數、標準件、草圖實體，並將其下游特徵標記為 pending。"""
        if feature_id not in self._features:
            raise ValueError(f"特徵 '{feature_id}' 不存在")
        feature = self._features[feature_id]
        if parameters:
            feature.parameters.update(parameters)
        if standard_parts:
            feature.standard_parts.update(standard_parts)
        if sketch_entities is not None:
            feature.sketch_entities = sketch_entities
        feature.rebuild_status = RebuildStatus.PENDING
        # 標記所有下游為 pending（增量重建）
        for dep_id in self._get_downstream(feature_id):
            self._features[dep_id].rebuild_status = RebuildStatus.PENDING
        return feature

    def delete_feature(self, feature_id: str) -> list[str]:
        """刪除特徵。若被其他特徵依賴，列出受影響特徵供使用者選擇。

        Returns:
            受影響的下游特徵 ID 列表（不含目標本身）。空列表表示可安全刪除。
        """
        downstream = self._get_downstream(feature_id)
        if downstream:
            # 有依賴者——禁止靜默刪除，由呼叫端決定是否連同刪除
            return downstream
        del self._features[feature_id]
        return []

    def delete_feature_recursive(self, feature_id: str) -> list[str]:
        """連同下游依賴一起刪除。"""
        downstream = self._get_downstream(feature_id)
        deleted = [feature_id] + downstream
        for fid in deleted:
            self._features.pop(fid, None)
        return deleted

    def topological_sort(self) -> list[str]:
        """拓撲排序，回傳特徵 ID 列表（上游在前）。"""
        visited: set[str] = set()
        result: list[str] = []
        temp_marked: set[str] = set()

        def visit(fid: str) -> None:
            if fid in visited:
                return
            if fid in temp_marked:
                raise ValueError(f"偵測到循環依賴：{fid}")
            temp_marked.add(fid)
            feature = self._features.get(fid)
            if feature:
                for ref in feature.references:
                    if ref in self._features:
                        visit(ref)
                if feature.input and feature.input in self._features:
                    visit(feature.input)
            temp_marked.discard(fid)
            visited.add(fid)
            result.append(fid)

        for fid in self._features:
            visit(fid)
        return result

    def _get_downstream(self, feature_id: str, _visiting: set[str] | None = None) -> list[str]:
        """取得直接或間接依賴目標特徵的所有下游特徵。

        含循環依賴防護，避免互依特徵造成無限遞迴。
        """
        if _visiting is None:
            _visiting = set()
        # 循環依賴防護——若已在遞迴路徑上，不再繼續
        if feature_id in _visiting:
            return []
        _visiting.add(feature_id)

        downstream: list[str] = []
        for fid, feature in self._features.items():
            if feature_id in feature.references or feature.input == feature_id:
                if fid != feature_id:
                    downstream.append(fid)
                    downstream.extend(self._get_downstream(fid, _visiting))
        # 去重並保持順序
        seen: set[str] = set()
        result: list[str] = []
        for fid in downstream:
            if fid not in seen:
                seen.add(fid)
                result.append(fid)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "features": [f.to_dict() for f in self._features.values()],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeatureGraph":
        graph = cls()
        # 支援兩種格式：features 陣列（新版）或 feature_id 鍵值對（舊版）
        if "features" in d and isinstance(d["features"], list):
            for feat_dict in d["features"]:
                graph.add_feature(Feature.from_dict(feat_dict))
        else:
            for fid, feat_dict in d.items():
                if isinstance(feat_dict, dict) and "feature_id" in feat_dict:
                    graph.add_feature(Feature.from_dict(feat_dict))
        return graph

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "FeatureGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def features(self) -> dict[str, Feature]:
        return self._features