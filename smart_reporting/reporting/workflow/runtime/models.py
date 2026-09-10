from __future__ import annotations

import re
from copy import copy
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...contract import FIELD_REF_PATTERN, MeasureSemantic, ReportPeriod
from ...data_sources import MAX_REPORT_INPUTS
from ..query_pipeline import QueryRequirement

MAX_ANALYSIS_REQUIREMENTS = MAX_REPORT_INPUTS // 3

_FORBIDDEN_DERIVATION_PATTERN = re.compile(r"拟合|估算|推算|插值|外推|年化|平滑|补齐数据")


def _contains_forbidden_derivation(value: str) -> bool:
    return _FORBIDDEN_DERIVATION_PATTERN.search(value) is not None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class NormalizedReportPrompt(_StrictModel):
    period: ReportPeriod | None = None
    report_type: Literal["comprehensive", "topic"] | None = Field(default=None, alias="reportType")
    clarification_question: str | None = Field(
        default=None, alias="clarificationQuestion", min_length=1, max_length=1000
    )


_NUMERIC_MEASURE_TYPE_PATTERN = re.compile(
    r"^(?:TINYINT|SMALLINT|INT|INTEGER|BIGINT|LARGEINT|FLOAT|DOUBLE|DECIMAL)",
    re.IGNORECASE,
)


class TableReference(_StrictModel):
    source_id: str = Field(
        alias="sourceId",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
        description="候选表所属数据源 ID，必须与输入 Schema 完全一致。",
    )
    table: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*$",
        description="规范 database.table，必须直接复制输入 Schema 中的 table。",
    )

    @field_validator("table")
    @classmethod
    def normalize_table(cls, value: str) -> str:
        return value.lower()


class DataUnderstandingTable(TableReference):
    role: str = Field(min_length=1, max_length=200, description="该表对报告目标的必要作用。")
    period_column: str = Field(
        alias="periodColumn",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$",
        description="用于限定请求期间的物理字段，必须来自该表。",
    )
    period_granularity: Literal["date", "month", "year"] = Field(
        alias="periodGranularity",
        description=(
            "期间值的时间语义，与数据库字段类型无关：完整日期值使用 date，"
            "YYYY/MM、YYYY-MM 或 YYYYMM 月份值使用 month，仅存日历年份的值使用 year；"
            "不得根据报告汇总粒度选择。"
        ),
    )


class DataUnderstandingPlan(_StrictModel):
    tables: tuple[DataUnderstandingTable, ...] = Field(
        min_length=1,
        max_length=200,
        description="完成报告目标所必需的表及其物理期间字段，不包含指标、SQL 或报告提纲。",
    )


class PlanningSchemaColumn(_StrictModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(alias="dataType", min_length=1, max_length=128)
    description: str = Field(default="", max_length=2_000)


class PlanningSchemaTable(TableReference):
    description: str = Field(default="", max_length=4_000)
    columns: tuple[PlanningSchemaColumn, ...] = Field(min_length=1, max_length=500)


class PlanningSchema(_StrictModel):
    tables: tuple[PlanningSchemaTable, ...] = Field(min_length=1, max_length=200)
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )


class MeasureSemanticDecision(_StrictModel):
    field_ref: str = Field(alias="fieldRef", pattern=FIELD_REF_PATTERN)
    classification: Literal["measure", "dimension"]
    reason: str = Field(min_length=1, max_length=1_000)
    measure_semantic: MeasureSemantic | None = Field(default=None, alias="measureSemantic")

    @field_validator("field_ref")
    @classmethod
    def normalize_field_ref(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def validate_classification(self) -> MeasureSemanticDecision:
        # 决策对象同时保留字段分类和可审阅理由，但只有 measure 可以携带
        # MeasureSemantic。这个互斥约束防止模型把同一字段一边声明为维度，
        # 一边又偷偷提供聚合规则，导致审核界面与最终提交内容不一致。
        if self.classification == "measure":
            if self.measure_semantic is None:
                raise ValueError("measure 分类必须提供 measureSemantic")
            if self.measure_semantic.field_ref.lower() != self.field_ref:
                raise ValueError("measureSemantic.fieldRef 必须与决策字段一致")
        elif self.measure_semantic is not None:
            raise ValueError("dimension 分类不得提供 measureSemantic")
        return self


class MeasureSemanticProposal(_StrictModel):
    decisions: tuple[MeasureSemanticDecision, ...] = Field(default=(), max_length=2_000)

    @field_validator("decisions")
    @classmethod
    def validate_decisions(
        cls, value: tuple[MeasureSemanticDecision, ...]
    ) -> tuple[MeasureSemanticDecision, ...]:
        field_refs = [item.field_ref for item in value]
        if len(field_refs) != len(set(field_refs)):
            raise ValueError("指标语义候选不能重复分类同一字段")
        return value


class AnalysisItem(_StrictModel):
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    management_question: str = Field(alias="managementQuestion", min_length=1, max_length=2_000)
    primary_metric_family: str = Field(alias="primaryMetricFamily", min_length=1, max_length=256)
    requirement_ids: tuple[str, ...] = Field(
        alias="requirementIds",
        min_length=1,
        max_length=100,
        description="引用 requirements 中已有的 ID，每个 ID 只出现一次；maxItems 只是上限。",
    )

    @field_validator("requirement_ids")
    @classmethod
    def validate_requirement_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("requirementIds 不能重复")
        return value

    @field_validator("description", "management_question")
    @classmethod
    def validate_analysis_text(cls, value: str) -> str:
        if _contains_forbidden_derivation(value):
            # 自然语言关键词无法可靠区分动作、否定声明和引用说明。这里只保留
            # 不含正文的审计信号；真正的数据派生安全由后续取数、脚本和事实校验负责。
            logger.warning("report_analysis_forbidden_derivation_mentioned")
        return value


class AnalysisBundle(_StrictModel):
    analyses: tuple[AnalysisItem, ...] = Field(min_length=1, max_length=100)
    requirements: tuple[QueryRequirement, ...] = Field(
        min_length=1, max_length=MAX_ANALYSIS_REQUIREMENTS
    )


def _strip_source_table_prefix(value: str, source_id: Any) -> str:
    normalized = value.strip()
    if not isinstance(source_id, str):
        return normalized
    prefix = f"{source_id}."
    table_ref = normalized[len(prefix) :] if normalized.startswith(prefix) else normalized
    return table_ref if table_ref.count(".") == 1 else normalized


def _column_leaf(value: str, source_id: Any, table_refs: list[Any]) -> str:
    # 列字段契约只允许裸列名。模型偶尔把 measureSemantics.fieldRef
    # （source.database.table.column）或 table.column 全量复制进列字段；
    # 仅在限定符能精确绑定到当前数据源和目标表时收敛到裸列名。
    normalized = value.strip()
    qualifier, separator, column = normalized.rpartition(".")
    if not separator or not isinstance(source_id, str):
        return normalized

    allowed_qualifiers: set[str] = set()
    for table_ref in table_refs:
        if not isinstance(table_ref, str):
            continue
        normalized_table = _strip_source_table_prefix(table_ref, source_id).lower()
        table_parts = normalized_table.split(".")
        if len(table_parts) not in {1, 2}:
            continue
        allowed_qualifiers.add(table_parts[-1].lower())
        allowed_qualifiers.add(normalized_table)

    # SQL 表引用沿用表名契约的小写归一化；sourceId 仍须精确匹配。
    if qualifier.lower() in allowed_qualifiers:
        return column
    source_prefix = f"{source_id}."
    if qualifier.startswith(source_prefix) and (
        qualifier[len(source_prefix) :].lower() in allowed_qualifiers
    ):
        return column
    return normalized


def _column_leaf_list(values: list[Any], source_id: Any, table_refs: list[Any]) -> list[Any]:
    return [
        _column_leaf(item, source_id, table_refs) if isinstance(item, str) else item
        for item in values
    ]


_RELATION_TABLE_FIELDS = ("leftTable", "rightTable", "left_table", "right_table")


def _normalize_analysis_bundle_table_refs(candidate: Any) -> Any:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("requirements"), list):
        return candidate

    # 模型偶尔把 sourceId 当成 SQL catalog 前缀，生成 sourceId.database.table；
    # 也会把完整 fieldRef（source.database.table.column）复制进列字段。
    # 这里仅做服务端可证明的收敛：表引用精确移除当前 requirement 的 sourceId，
    # 列引用的限定符匹配目标表时才收敛到裸列名；其余引用由严格 Schema 拒绝。
    normalized = copy(candidate)
    normalized_requirements: list[Any] = []
    for raw_requirement in candidate["requirements"]:
        if not isinstance(raw_requirement, dict):
            normalized_requirements.append(raw_requirement)
            continue
        requirement = copy(raw_requirement)
        source_id = raw_requirement.get("sourceId", raw_requirement.get("source_id"))
        raw_tables = raw_requirement.get("tables")
        requirement_table_refs = (
            [item.get("table") for item in raw_tables if isinstance(item, dict)]
            if isinstance(raw_tables, list)
            else []
        )

        dimension_key = (
            "dimensionColumns" if "dimensionColumns" in requirement else "dimension_columns"
        )
        grain_key = "grainColumns" if "grainColumns" in requirement else "grain_columns"
        column_keys = (
            (dimension_key, grain_key)
            if isinstance(raw_tables, list) and len(raw_tables) == 1
            else (grain_key,)
        )
        for key in column_keys:
            values = requirement.get(key)
            if isinstance(values, list):
                requirement[key] = _column_leaf_list(
                    values,
                    source_id,
                    requirement_table_refs,
                )

        # grainColumns 是 dimensionColumns 的物化子集，这个关系是协议结构事实，不是
        # 业务推断。模型在复杂计划中常只把共同粒度写入 grainColumns；若等到
        # QueryRequirement 构造后再修正，Pydantic 会先拒绝整份 Bundle，Reporting
        # 的带反馈纠错也就没有机会运行。这里只追加已经由模型明确声明的合法字符串，
        # 未知列、重复列、字段上限及后续语义约束仍由原有严格校验失败关闭。
        dimensions = requirement.get(dimension_key)
        grain = requirement.get(grain_key)
        if isinstance(dimensions, list) and isinstance(grain, list):
            known = {item.casefold() for item in dimensions if isinstance(item, str)}
            merged = list(dimensions)
            for item in grain:
                if isinstance(item, str) and item.casefold() not in known:
                    merged.append(item)
                    known.add(item.casefold())
            requirement[dimension_key] = merged

        for key in ("tables", "relations"):
            raw_items = raw_requirement.get(key)
            if not isinstance(raw_items, list):
                continue
            items: list[Any] = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    items.append(raw_item)
                    continue
                item = copy(raw_item)
                target_table_refs = (
                    [raw_item.get("table")]
                    if key == "tables"
                    else [raw_item.get(field) for field in _RELATION_TABLE_FIELDS]
                )
                for column_key in ("measureColumns", "measure_columns"):
                    if isinstance(item.get(column_key), list):
                        item[column_key] = _column_leaf_list(
                            item[column_key], source_id, target_table_refs
                        )
                for column_key in ("joinColumns", "join_columns"):
                    if isinstance(item.get(column_key), list):
                        item[column_key] = _column_leaf_list(
                            item[column_key], source_id, target_table_refs
                        )
                for column_key in ("periodColumn", "period_column"):
                    if isinstance(item.get(column_key), str):
                        item[column_key] = _column_leaf(
                            item[column_key], source_id, target_table_refs
                        )
                fields = ("table",) if key == "tables" else _RELATION_TABLE_FIELDS
                if isinstance(source_id, str):
                    for field in fields:
                        value = item.get(field)
                        if not isinstance(value, str):
                            continue
                        item[field] = _strip_source_table_prefix(value, source_id)
                items.append(item)
            requirement[key] = items
        normalized_requirements.append(requirement)
    normalized["requirements"] = normalized_requirements
    return normalized


class GeneratedQuery(_StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=262_144)
    period_role: Literal["current", "yoy", "mom"] = Field(default="current", alias="periodRole")


class GeneratedQueryBatch(_StrictModel):
    queries: tuple[GeneratedQuery, ...] = Field(min_length=1, max_length=100)


__all__ = [
    "NormalizedReportPrompt",
    "TableReference",
    "DataUnderstandingTable",
    "DataUnderstandingPlan",
    "PlanningSchemaColumn",
    "PlanningSchemaTable",
    "PlanningSchema",
    "MeasureSemanticDecision",
    "MeasureSemanticProposal",
    "AnalysisItem",
    "AnalysisBundle",
    "GeneratedQuery",
    "GeneratedQueryBatch",
]
