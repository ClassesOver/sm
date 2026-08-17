"""Dataset 级来源告警与 Coding 执行回执。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, model_validator

from .schema import HospitalOperationSchema

SHA256_PATTERN = r"^[0-9a-f]{64}$"

SourcePolicy = Literal["csv", "source_compare", "source_explicit"]
SOURCE_WARNING_CODES = frozenset(
    {
        "source_coverage_difference",
        "source_period_difference",
        "source_data_quality",
    }
)


class SourceWarning(HospitalOperationSchema):
    """数据质量或来源差异告警，不修改不可变 Dataset 的内容。"""

    code: Literal[
        "source_coverage_difference",
        "source_period_difference",
        "source_data_quality",
    ]
    message: str = Field(min_length=1, max_length=2_000)
    dataset_ids: tuple[str, ...] = Field(default=(), alias="datasetIds", max_length=100)
    query_ids: tuple[str, ...] = Field(default=(), alias="queryIds", max_length=100)
    details: dict[str, Any] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def validate_warning(self) -> SourceWarning:
        if not self.dataset_ids and not self.query_ids:
            raise ValueError("来源告警至少需要一个 Dataset 或查询引用")
        for values in (self.dataset_ids, self.query_ids):
            if len(values) != len(set(values)):
                raise ValueError("来源告警引用不能重复")
        return self


class SourceBinding(HospitalOperationSchema):
    """Coding 计算实际使用的数据来源。"""

    policy: SourcePolicy = Field(default="csv", alias="sourcePolicy")
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)
    query_ids: tuple[str, ...] = Field(default=(), alias="queryIds", max_length=100)
    warnings: tuple[SourceWarning, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_references(self) -> SourceBinding:
        for values in (self.dataset_ids, self.query_ids):
            if len(values) != len(set(values)):
                raise ValueError("实际来源引用不能重复")
        if any(set(item.dataset_ids) - set(self.dataset_ids) for item in self.warnings):
            raise ValueError("来源告警引用必须属于实际 Dataset")
        return self


class PlanExecutionReceipt(HospitalOperationSchema):
    """Coding 对单个 analysisId 的可追溯执行回执。"""

    plan_id: str = Field(alias="planId", min_length=1, max_length=128)
    plan_hash: str = Field(alias="planHash", pattern=SHA256_PATTERN)
    input_snapshot_hash: str = Field(alias="inputSnapshotHash", pattern=SHA256_PATTERN)
    actual_source: SourceBinding = Field(alias="actualSource")
    input_row_count: int = Field(alias="inputRowCount", ge=0)
    output_summary: dict[str, Any] = Field(alias="outputSummary", max_length=100)
    warnings: tuple[SourceWarning, ...] = Field(default=(), max_length=100)
    artifact_sha256: str = Field(alias="artifactSha256", pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_warning_union(self) -> PlanExecutionReceipt:
        def canonical(item: SourceWarning) -> str:
            return json.dumps(
                item.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        if {canonical(item) for item in self.warnings} != {
            canonical(item) for item in self.actual_source.warnings
        }:
            raise ValueError("执行回执不得丢失实际来源告警")
        return self


__all__ = [
    "PlanExecutionReceipt",
    "SOURCE_WARNING_CODES",
    "SourceBinding",
    "SourcePolicy",
    "SourceWarning",
]
