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
    SWEEP = "sweep"
    LOFT = "loft"
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
    DRAFT = "draft"
    RIB = "rib"
    THIN = "thin"
    VARIABLE_FILLET = "variable_fillet"
    COUNTERSINK = "countersink"
    COSMETIC_THREAD = "cosmetic_thread"


class RebuildStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"


class FeatureState(str, Enum):
    """特徵狀態機（v2）。"""
    ACTIVE = "active"
    SUPPRESSED = "suppressed"
    FAILED = "failed"
    ORPHAN = "orphan"


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
    plane: dict[str, Any] = field(default_factory=lambda: {"base": "XY", "offset": 0})
    validation: ValidationSpec | None = None
    source: FeatureSource = FeatureSource.LLM
    llm_description: str = ""
    rebuild_status: RebuildStatus = RebuildStatus.PENDING
    error_message: str = ""
    # v2 fields
    body: str = "body1"
    order: int | None = None
    state: FeatureState = FeatureState.ACTIVE

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
            "plane": self.plane,
            "validation": self.validation.to_dict() if self.validation else None,
            "source": self.source.value if isinstance(self.source, FeatureSource) else self.source,
            "llm_description": self.llm_description,
            "rebuild_status": self.rebuild_status.value if isinstance(self.rebuild_status, RebuildStatus) else self.rebuild_status,
            "error_message": self.error_message,
            "body": self.body,
            "order": self.order,
            "state": self.state.value if isinstance(self.state, FeatureState) else self.state,
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
            plane=d.get("plane", {"base": "XY", "offset": 0}),
            validation=validation,
            source=FeatureSource(d.get("source", "llm")),
            llm_description=d.get("llm_description", ""),
            rebuild_status=RebuildStatus(d.get("rebuild_status", "pending")),
            error_message=d.get("error_message", ""),
            body=d.get("body", "body1"),
            order=d.get("order"),
            state=FeatureState(d.get("state", "active")),
        )


class ReorderDependencyViolationError(ValueError):
    """reorder 違反依賴關係（地雷 #14 關聯）。"""
    pass


class FeatureGraph:
    """Feature Graph——管理特徵依賴關係與拓撲排序。

    特徵只描述意圖與參數，由各 Adapter 負責轉譯（引擎中立）。
    """

    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}
        # v2 document model fields
        self._bodies: list[dict[str, Any]] = [{"id": "body1", "name": "主體", "material": "", "appearance": None}]
        self._reference_geometry: list[dict[str, Any]] = []
        self._rollback_position: int | None = None
        self._global_variables: list[dict[str, Any]] = []
        self._configurations: list[dict[str, Any]] = []
        self._custom_properties: dict[str, Any] = {}

    def add_feature(self, feature: Feature) -> None:
        """加入特徵。feature_id 不得重複。自動分配 order。"""
        if feature.feature_id in self._features:
            raise ValueError(f"feature_id '{feature.feature_id}' 已存在")
        # 自動分配 order（per-body 遞增）
        if feature.order is None:
            max_order = max(
                (f.order for f in self._features.values() if f.body == feature.body and f.order is not None),
                default=-1,
            )
            feature.order = max_order + 1
        self._features[feature.feature_id] = feature

    def get_feature(self, feature_id: str) -> Feature | None:
        return self._features.get(feature_id)

    def update_feature(
        self, feature_id: str, parameters: dict[str, Any] | None = None,
        standard_parts: dict[str, Any] | None = None,
        sketch_entities: list[dict[str, Any]] | None = None,
        plane: dict[str, Any] | None = None,
        constraints: list[dict[str, Any]] | None = None,
    ) -> Feature:
        """更新特徵參數、標準件、草圖實體、基準面、約束，並將其下游特徵標記為 pending。"""
        if feature_id not in self._features:
            raise ValueError(f"特徵 '{feature_id}' 不存在")
        feature = self._features[feature_id]
        if parameters:
            feature.parameters.update(parameters)
        if standard_parts:
            feature.standard_parts.update(standard_parts)
        if sketch_entities is not None:
            feature.sketch_entities = sketch_entities
        if plane is not None:
            feature.plane = plane
        if constraints is not None:
            feature.constraints = constraints
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
        """拓撲排序，回傳特徵 ID 列表（上游在前）。

        注意：這是依賴序（DFS over 插入順序），不是 order 欄位排序；
        依 order 排序請用 get_ordered_features()/get_rebuild_features()。
        """
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
            "schema_version": "2.0",
            "features": [f.to_dict() for f in self._features.values()],
            "bodies": self._bodies,
            "reference_geometry": self._reference_geometry,
            "rollback_position": self._rollback_position,
            "global_variables": self._global_variables,
            "configurations": self._configurations,
            "custom_properties": self._custom_properties,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeatureGraph":
        graph = cls()
        # Schema migration: v1 → v2
        sv = d.get("schema_version", "1.0")
        if sv == "1.0":
            graph = FeatureGraph._migrate_v1_to_v2(d)
        else:
            # v2 format
            if "features" in d and isinstance(d["features"], list):
                for feat_dict in d["features"]:
                    graph.add_feature(Feature.from_dict(feat_dict))
            else:
                for fid, feat_dict in d.items():
                    if isinstance(feat_dict, dict) and "feature_id" in feat_dict:
                        graph.add_feature(Feature.from_dict(feat_dict))
            graph._bodies = d.get("bodies", [{"id": "body1", "name": "主體", "material": "", "appearance": None}])
            graph._reference_geometry = d.get("reference_geometry", [])
            graph._rollback_position = d.get("rollback_position")
            graph._global_variables = d.get("global_variables", [])
            graph._configurations = d.get("configurations", [])
            graph._custom_properties = d.get("custom_properties", {})
        # Ensure order is set for all features
        graph._ensure_order()
        return graph

    def save(self, path: Path) -> None:
        from .atomic_save import atomic_write_json
        atomic_write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> "FeatureGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def clone(self) -> "FeatureGraph":
        """深複製 Feature Graph，用於 staging/rollback 交易。"""
        return FeatureGraph.from_dict(self.to_dict())

    @property
    def features(self) -> dict[str, Feature]:
        return self._features

    # ── v2 properties ──

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return self._bodies

    @bodies.setter
    def bodies(self, value: list[dict[str, Any]]) -> None:
        self._bodies = value

    @property
    def reference_geometry(self) -> list[dict[str, Any]]:
        return self._reference_geometry

    def add_reference_geometry(self, datum: dict[str, Any]) -> None:
        """加入基準幾何（datum plane/axis/point）。id 不得重複。"""
        rid = datum.get("id", "")
        if not rid:
            raise ValueError("reference_geometry 需要 id 欄位")
        if any(r.get("id") == rid for r in self._reference_geometry):
            raise ValueError(f"reference_geometry id '{rid}' 已存在")
        self._reference_geometry.append(datum)

    def delete_reference_geometry(self, rid: str) -> bool:
        """刪除基準幾何。回傳是否成功。"""
        before = len(self._reference_geometry)
        self._reference_geometry = [r for r in self._reference_geometry if r.get("id") != rid]
        return len(self._reference_geometry) < before

    def update_reference_geometry(self, rid: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """更新基準幾何定義。"""
        for r in self._reference_geometry:
            if r.get("id") == rid:
                r.update(updates)
                return r
        return None

    @property
    def rollback_position(self) -> int | None:
        return self._rollback_position

    @rollback_position.setter
    def rollback_position(self, value: int | None) -> None:
        self._rollback_position = value

    @property
    def global_variables(self) -> list[dict[str, Any]]:
        return self._global_variables

    @property
    def configurations(self) -> list[dict[str, Any]]:
        return self._configurations

    @property
    def custom_properties(self) -> dict[str, Any]:
        return self._custom_properties

    # ── v2 methods ──

    def _ensure_order(self) -> None:
        """為沒有 order 的特徵自動編號（依加入順序，per-body 遞增）。"""
        body_orders: dict[str, int] = {}
        for fid, feature in self._features.items():
            if feature.order is None:
                body = feature.body
                if body not in body_orders:
                    # Find max existing order in this body
                    max_order = -1
                    for f in self._features.values():
                        if f.body == body and f.order is not None:
                            max_order = max(max_order, f.order)
                    body_orders[body] = max_order + 1
                else:
                    body_orders[body] += 1
                feature.order = body_orders[body]

    @staticmethod
    def _migrate_v1_to_v2(d: dict[str, Any]) -> "FeatureGraph":
        """v1 → v2 遷移：單 body、order=陣列序、state=active。"""
        graph = FeatureGraph()
        if "features" in d and isinstance(d["features"], list):
            for i, feat_dict in enumerate(d["features"]):
                feature = Feature.from_dict(feat_dict)
                feature.body = "body1"
                feature.order = i
                feature.state = FeatureState.ACTIVE
                graph.add_feature(feature)
        else:
            for i, (fid, feat_dict) in enumerate(d.items()):
                if isinstance(feat_dict, dict) and "feature_id" in feat_dict:
                    feature = Feature.from_dict(feat_dict)
                    feature.body = "body1"
                    feature.order = i
                    feature.state = FeatureState.ACTIVE
                    graph.add_feature(feature)
        return graph

    def suppress_feature(self, feature_id: str) -> list[str]:
        """抑制特徵——跳過重建但保留參數。下游參照 suppressed 產物→標 orphan。

        Returns:
            被標為 orphan 的下游特徵 ID 列表。
        """
        if feature_id not in self._features:
            raise ValueError(f"特徵 '{feature_id}' 不存在")
        feature = self._features[feature_id]
        feature.state = FeatureState.SUPPRESSED
        feature.rebuild_status = RebuildStatus.PENDING
        # Mark downstream as orphan
        downstream = self._get_downstream(feature_id)
        for dep_id in downstream:
            dep = self._features[dep_id]
            if dep.state == FeatureState.ACTIVE:
                dep.state = FeatureState.ORPHAN
                dep.rebuild_status = RebuildStatus.PENDING
        return downstream

    def unsuppress_feature(self, feature_id: str) -> list[str]:
        """取消抑制——恢復特徵及下游到 active 狀態。

        Returns:
            從 orphan 恢復為 active 的下游特徵 ID 列表。
        """
        if feature_id not in self._features:
            raise ValueError(f"特徵 '{feature_id}' 不存在")
        feature = self._features[feature_id]
        feature.state = FeatureState.ACTIVE
        feature.rebuild_status = RebuildStatus.PENDING
        # Restore downstream from orphan to active
        downstream = self._get_downstream(feature_id)
        restored: list[str] = []
        for dep_id in downstream:
            dep = self._features[dep_id]
            if dep.state == FeatureState.ORPHAN:
                dep.state = FeatureState.ACTIVE
                dep.rebuild_status = RebuildStatus.PENDING
                restored.append(dep_id)
        return restored

    def reorder_feature(self, feature_id: str, new_order: int) -> None:
        """重新排序特徵。違反依賴的 reorder 回 REORDER_DEPENDENCY_VIOLATION。

        規則：特徵的 order 不能小於其任何上游依賴的 order。
        """
        if feature_id not in self._features:
            raise ValueError(f"特徵 '{feature_id}' 不存在")
        feature = self._features[feature_id]
        old_order = feature.order or 0
        body = feature.body

        # Check dependency: new_order must be > all upstream deps' order in same body
        upstream_orders: list[int] = []
        for ref_id in feature.references:
            ref_feat = self._features.get(ref_id)
            if ref_feat and ref_feat.body == body and ref_feat.order is not None:
                upstream_orders.append(ref_feat.order)
        if feature.input:
            input_feat = self._features.get(feature.input)
            if input_feat and input_feat.body == body and input_feat.order is not None:
                upstream_orders.append(input_feat.order)

        if upstream_orders and new_order <= max(upstream_orders):
            raise ReorderDependencyViolationError(
                f"reorder 違反依賴：{feature_id} 的 order({new_order}) "
                f"必須大於上游依賴的最大 order({max(upstream_orders)})"
            )

        # Check dependency: new_order must be < all downstream dependents' order in same body
        downstream_orders: list[int] = []
        for f in self._features.values():
            if f.feature_id == feature_id or f.body != body or f.order is None:
                continue
            if feature_id in f.references or f.input == feature_id:
                downstream_orders.append(f.order)
        if downstream_orders and new_order >= min(downstream_orders):
            raise ReorderDependencyViolationError(
                f"reorder 違反依賴：{feature_id} 的 order({new_order}) "
                f"必須小於下游依賴的最小 order({min(downstream_orders)})"
            )

        # Shift other features' order in the same body
        body_features = sorted(
            [f for f in self._features.values() if f.body == body and f.feature_id != feature_id],
            key=lambda f: f.order or 0
        )
        if new_order < old_order:
            # Moving earlier: shift features between new_order and old_order-1 up by 1
            for f in body_features:
                f_order = f.order or 0
                if new_order <= f_order < old_order:
                    f.order = f_order + 1
        else:
            # Moving later: shift features between old_order+1 and new_order down by 1
            for f in body_features:
                f_order = f.order or 0
                if old_order < f_order <= new_order:
                    f.order = f_order - 1
        feature.order = new_order
        feature.rebuild_status = RebuildStatus.PENDING
        # Mark downstream pending
        for dep_id in self._get_downstream(feature_id):
            self._features[dep_id].rebuild_status = RebuildStatus.PENDING

    def set_rollback(self, position: int | None) -> None:
        """設定回溯位置。None=末端（重建全部）。整數=重建到該 order。"""
        if position is not None and position < 0:
            raise ValueError("rollback_position 不得為負數")
        self._rollback_position = position
        # Mark all features as pending for rebuild
        for feature in self._features.values():
            feature.rebuild_status = RebuildStatus.PENDING

    def get_ordered_features(self, body: str | None = None) -> list[Feature]:
        """取得依 order 排序的特徵列表。可指定 body 過濾。"""
        features = list(self._features.values())
        if body:
            features = [f for f in features if f.body == body]
        return sorted(features, key=lambda f: f.order or 0)

    def get_rebuild_features(self) -> list[str]:
        """取得需要重建的特徵 ID 列表（依 order 排序，排除 suppressed/orphan，截至 rollback_position）。"""
        ordered = self.get_ordered_features()
        result: list[str] = []
        for feature in ordered:
            if feature.state in (FeatureState.SUPPRESSED, FeatureState.ORPHAN):
                continue
            if self._rollback_position is not None and (feature.order or 0) > self._rollback_position:
                break
            result.append(feature.feature_id)
        return result