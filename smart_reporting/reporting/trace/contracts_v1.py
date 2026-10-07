"""报告追溯契约 V1（B0 冻结）。

对应实施计划 `docs/superpowers/specs/2026-09-29-report-editor-data-lineage-batched-implementation.md`
第 3 节统一追溯模型。本模块只定义不可变数据契约、canonical 规则、稳定错误码与
资源预算常量；文件读取、API 与授权在 B1+ 批次实现。

约束（计划 3.2/3.4）：
- 索引本身不以自身携带的 hash 作为唯一信任根，必须被权威 manifest/context 登记。
- `TraceFileRefV1.path` 是工作区相对路径，只存在于服务端 sidecar 层，API 不返回。
- 引用一律通过 `resource_id` 等不透明身份解析，客户端不能提交路径或授权身份。
- canonical 序列化禁止 NaN/Infinity；时间使用 ISO8601 UTC；sha256 为小写 hex。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from ..contract import SHA256_PATTERN, StrictModel

TRACE_CONTRACT_VERSION = "1"

# ---------------------------------------------------------------------------
# 身份模式
# ---------------------------------------------------------------------------

# 索引内文件资源 ID：服务端按 path 内容寻址生成，索引内唯一。
TRACE_RESOURCE_ID_PATTERN = r"^trf-[0-9a-f]{20}$"
# 正文/表格/图表 subject 稳定 ID：服务端按 kind+定位规范化内容寻址生成。
TRACE_SUBJECT_ID_PATTERN = r"^sub-[0-9a-f]{16}$"
# 计算记录 ID。
TRACE_COMPUTATION_ID_PATTERN = r"^comp-[0-9a-f]{16}$"
# 与现有交付产物一致的标识空间。
TRACE_DATASET_ID_PATTERN = r"^dataset-[A-Za-z0-9-]{6,64}$"
TRACE_ANALYSIS_ID_PATTERN = r"^analysis_[0-9]{3,6}$"
TRACE_CHART_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"
TRACE_TABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
TRACE_STRUCTURE_KEY_PATTERN = r"^[^\r\n]{1,128}$"
# ISO8601 UTC 时间戳；物化时间未知时为 null，禁止用 mtime 推断（计划 3.2）。
TRACE_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"

# RFC 6901 JSON Pointer：空串（整文档）或若干 `/token`，token 中 `~` 仅允许 `~0`/`~1`。
_JSON_POINTER_PATTERN = re.compile(r"^(?:/(?:[^~/]|~[01])*)*$")

#: FactRef JSON Pointer 最大长度（计划 3.2：限制指针长度和访问范围）。
TRACE_FACT_POINTER_MAX_CHARS = 256


def validate_json_pointer(value: str) -> str:
    if len(value) > TRACE_FACT_POINTER_MAX_CHARS:
        raise ValueError(f"JSON Pointer 长度超过 {TRACE_FACT_POINTER_MAX_CHARS}")
    if not _JSON_POINTER_PATTERN.fullmatch(value):
        raise ValueError("JSON Pointer 必须符合 RFC 6901（~ 仅允许 ~0/~1 转义）")
    return value


def utc_now_timestamp() -> str:
    """当前 UTC 时间的契约时间戳（ISO8601，秒级，Z 结尾）。"""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# canonical 规则（计划 3.2）
# ---------------------------------------------------------------------------


def canonical_json_bytes(value: Any) -> bytes:
    """契约 canonical JSON：排序键、紧凑分隔、禁止 NaN/Infinity。"""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_subject_content(text: str) -> str:
    """subject 规范化内容：统一换行、去每行首尾空白、去整体首尾空白。

    用于内容指纹（subjectSha256），识别"有效格式变化与实质内容变化"（计划 B6）。
    """

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.strip() for line in lines).strip()


def subject_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_subject_content(text).encode("utf-8")).hexdigest()


def derive_resource_id(path: str) -> str:
    """由工作区相对路径派生文件资源 ID；同一索引内 path 唯一则 ID 唯一。"""

    return f"trf-{hashlib.sha256(path.encode('utf-8')).hexdigest()[:20]}"


# ---------------------------------------------------------------------------
# 状态维度（计划 3.3，读取层运行时状态；仅计算核对的初始值进入不可变记录）
# ---------------------------------------------------------------------------

BindingStatusV1 = Literal["valid", "stale", "unbound"]
FileAvailabilityV1 = Literal["available", "missing", "expired", "integrity_failed"]
VerificationStatusV1 = Literal["verified", "not_checked", "failed", "not_applicable"]
EvidenceKindV1 = Literal["observed", "computed", "estimated", "interpretation"]
ReproducibilityV1 = Literal["reproducible", "limited", "unavailable"]

#: 快照内单维度下钻算法。``semi_additive_last`` 表示先在每个分组中选择
#: 最新期间，再对该期间的值求和；期间本身不能作为可选下钻维度。
DrilldownAggregationV1 = Literal[
    "sum",
    "count",
    "count_distinct",
    "average",
    "ratio",
    "semi_additive_last",
]

#: 图表系列性质：区分观测、预测及区间（计划 4.4）。
ChartSeriesKindV1 = Literal[
    "observed", "predicted", "confidence_interval", "target", "other"
]

#: 追溯文件媒体类型。比 delivery ArtifactFile 现有枚举新增 json/csv，
#: B1/B3 接入交付清单时同步扩展 ArtifactFile（计划第 2 节缺口表）。
TraceMediaTypeV1 = Literal[
    "text/markdown",
    "image/png",
    "image/jpeg",
    "application/vnd.plotly.v1+json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json",
    "text/csv",
]

#: 事实文件内容类别：确定性 facts bundle / 补充分析证据 / 作图数据（chart-input/v1）。
FactFileContentKindV1 = Literal[
    "deterministic_bundle", "supplemental_evidence", "chart_input"
]

#: 事实种类，对应 DeterministicAnalysisBundle 条目与补充分析 findings。
FactKindV1 = Literal[
    "metric",
    "comparison",
    "derived",
    "reconciliation",
    "correlation",
    "supplemental_finding",
]


# ---------------------------------------------------------------------------
# 契约对象（计划 3.2 建议契约表）
# ---------------------------------------------------------------------------


class TraceFileRefV1(StrictModel):
    """索引内文件引用。path 仅存在于服务端 sidecar，API 不返回（计划 3.2）。"""

    resource_id: str = Field(alias="resourceId", pattern=TRACE_RESOURCE_ID_PATTERN)
    path: str = Field(min_length=1, max_length=512)
    media_type: TraceMediaTypeV1 = Field(alias="mediaType")
    size: int = Field(ge=1, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("追溯文件路径必须使用 POSIX 相对路径")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("追溯文件路径必须位于工作区内")
        return value

    @model_validator(mode="after")
    def validate_resource_id(self) -> TraceFileRefV1:
        if self.resource_id != derive_resource_id(self.path):
            raise ValueError("resourceId 必须由登记路径派生")
        return self


class DatasetSnapshotRefV1(StrictModel):
    """CSV 快照引用。数据库与 URL CSV 区分；物化时间未知为 null（计划 3.2）。"""

    dataset_id: str = Field(alias="datasetId", pattern=TRACE_DATASET_ID_PATTERN)
    file_resource_id: str = Field(
        alias="fileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    source_type: Literal["starrocks_materialized", "url_csv"] = Field(
        alias="sourceType"
    )
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    sql_hash: str | None = Field(default=None, alias="sqlHash", pattern=SHA256_PATTERN)
    period_roles: tuple[Literal["current", "yoy", "mom"], ...] = Field(
        alias="periodRoles", min_length=1
    )
    query_window_id: str = Field(
        alias="queryWindowId", min_length=1, max_length=128, default="current"
    )
    row_count: int = Field(alias="rowCount", ge=0)
    materialized_at: str | None = Field(
        default=None, alias="materializedAt", pattern=TRACE_TIMESTAMP_PATTERN
    )
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    #: 业务标签（需求描述等）；仅展示用，不参与身份。
    business_label: str | None = Field(
        default=None, alias="businessLabel", max_length=255
    )
    query_sql: str | None = Field(default=None, alias="querySql", max_length=262_144)


class DrilldownDimensionV1(StrictModel):
    """服务端冻结的单维度下钻入口；``field`` 是快照内实际列名。"""

    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    field: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=200)


class DrilldownMetricV1(StrictModel):
    """指标在一个冻结快照上的受限下钻声明（计划 B7）。

    客户端只提交 ``metricCode`` 与已登记的 dimension code；字段、固定范围、
    聚合算法和对账答案均来自本声明，不能由请求覆盖。
    """

    metric_code: str = Field(
        alias="metricCode", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
    )
    dataset_id: str = Field(alias="datasetId", pattern=TRACE_DATASET_ID_PATTERN)
    aggregation: DrilldownAggregationV1
    value_field: str | None = Field(default=None, alias="valueField", max_length=128)
    numerator_field: str | None = Field(
        default=None, alias="numeratorField", max_length=128
    )
    denominator_field: str | None = Field(
        default=None, alias="denominatorField", max_length=128
    )
    period_field: str | None = Field(default=None, alias="periodField", max_length=128)
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    dimensions: tuple[DrilldownDimensionV1, ...] = Field(
        min_length=1, max_length=100
    )
    fixed_scope: Mapping[str, str] = Field(
        default_factory=dict, alias="fixedScope", max_length=100
    )
    expected_value: float | None = Field(default=None, alias="expectedValue")
    tolerance: float = Field(default=0.01, ge=0)
    unit: str | None = Field(default=None, max_length=64)
    fact_keys: tuple[str, ...] = Field(
        default=(), alias="factKeys", max_length=100
    )

    @model_validator(mode="after")
    def validate_algorithm_inputs(self) -> DrilldownMetricV1:
        dimension_codes = [item.code for item in self.dimensions]
        dimension_fields = [item.field for item in self.dimensions]
        if len(dimension_codes) != len(set(dimension_codes)):
            raise ValueError("下钻维度 code 不能重复")
        if len(dimension_fields) != len(set(dimension_fields)):
            raise ValueError("下钻维度字段不能重复")
        if self.aggregation == "ratio":
            if (
                self.value_field is not None
                or not self.numerator_field
                or not self.denominator_field
            ):
                raise ValueError("ratio 下钻必须且只能声明分子、分母字段")
        elif (
            not self.value_field
            or self.numerator_field is not None
            or self.denominator_field is not None
        ):
            raise ValueError("非 ratio 下钻必须且只能声明 valueField")
        if self.aggregation == "semi_additive_last":
            if not self.period_field:
                raise ValueError("半可加下钻必须声明 periodField")
            if self.period_field in dimension_fields:
                raise ValueError("半可加指标不能沿期间维度汇总")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("periodStart 与 periodEnd 必须同时声明")
        if (self.period_start is not None or self.period_end is not None) and not self.period_field:
            raise ValueError("期间范围必须绑定 periodField")
        return self


class FactRefV1(StrictModel):
    """事实精确定位：冻结文件身份 + JSON Pointer（计划 3.2）。

    pointer 只在同一个冻结文件身份下有效；新文件重排不静默迁移旧引用。
    fact_key 是防御性核对键（如 B2 起写入事实条目的 factId），读取层用于
    识别位置漂移，不作为定位手段。
    """

    analysis_id: str = Field(alias="analysisId", pattern=TRACE_ANALYSIS_ID_PATTERN)
    file_resource_id: str = Field(
        alias="fileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    json_pointer: str = Field(alias="jsonPointer", default="")
    fact_kind: FactKindV1 = Field(alias="factKind")
    fact_key: str | None = Field(default=None, alias="factKey", max_length=256)

    @field_validator("json_pointer")
    @classmethod
    def _validate_pointer(cls, value: str) -> str:
        return validate_json_pointer(value)


class ComputationRecordV1(StrictModel):
    """通用计算记录：方法、输入输出与执行身份（计划 4.3）。

    输入输出引用必须齐全；运行成功不自动标记数值复核通过（verification
    初始 not_checked，复算形成新记录，不覆盖本记录）。
    """

    computation_id: str = Field(
        alias="computationId", pattern=TRACE_COMPUTATION_ID_PATTERN
    )
    method: str = Field(min_length=1, max_length=128)
    method_version: str | None = Field(
        default=None, alias="methodVersion", max_length=64
    )
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    input_dataset_ids: tuple[str, ...] = Field(
        alias="inputDatasetIds", max_length=100
    )
    input_fact_refs: tuple[FactRefV1, ...] = Field(
        default=(), alias="inputFactRefs", max_length=200
    )
    #: 预处理说明（筛选、join、期间对齐、异常/缺失处理等），人读文本。
    preprocessing: tuple[str, ...] = Field(default=(), max_length=50)
    intermediate_file_resource_ids: tuple[str, ...] = Field(
        default=(), alias="intermediateFileResourceIds", max_length=100
    )
    script_file_resource_id: str | None = Field(
        default=None, alias="scriptFileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    execution_id: str | None = Field(default=None, alias="executionId", max_length=128)
    #: 环境摘要（解释最终结果所必需的依赖版本、种子等）。
    environment: Mapping[str, str] | None = Field(default=None)
    output_fact_refs: tuple[FactRefV1, ...] = Field(
        alias="outputFactRefs", min_length=1, max_length=500
    )
    limitations: tuple[str, ...] = Field(default=(), max_length=50)
    verification: VerificationStatusV1 = "not_checked"
    reproducibility: ReproducibilityV1 = "unavailable"

    @model_validator(mode="after")
    def validate_acyclic_self(self) -> ComputationRecordV1:
        output_analyses = {ref.analysis_id for ref in self.output_fact_refs}
        self_inputs = {ref.analysis_id for ref in self.input_fact_refs}
        if output_analyses & self_inputs:
            raise ValueError("计算记录的输入与输出不能指向同一 analysis")
        if len(self.input_dataset_ids) != len(set(self.input_dataset_ids)):
            raise ValueError("输入数据集不能重复")
        return self


class ChartSeriesV1(StrictModel):
    """图表系列映射：名称、单位、性质与类别（计划 4.4）。"""

    name: str = Field(min_length=1, max_length=255)
    unit: str | None = Field(default=None, max_length=64)
    series_kind: ChartSeriesKindV1 = Field(
        alias="seriesKind", default="observed"
    )
    categories: tuple[str, ...] = Field(default=(), max_length=500)


class ChartTraceV1(StrictModel):
    """静态图表追溯：图片 → 实际作图数据 → 规则 → facts/CSV（计划 4.4）。

    图片必须由登记的同一份作图数据生成；plotData 文件角色与源 CSV 不同，
    分别登记。
    """

    chart_id: str = Field(alias="chartId", pattern=TRACE_CHART_ID_PATTERN)
    presentation_sha256: str | None = Field(
        default=None, alias="presentationSha256", pattern=SHA256_PATTERN
    )
    image_file_resource_id: str = Field(
        alias="imageFileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    plot_data_file_resource_ids: tuple[str, ...] = Field(
        alias="plotDataFileResourceIds", min_length=1, max_length=50
    )
    dataset_ids: tuple[str, ...] = Field(
        alias="datasetIds", min_length=1, max_length=100
    )
    fact_refs: tuple[FactRefV1, ...] = Field(
        default=(), alias="factRefs", max_length=100
    )
    computation_id: str | None = Field(
        default=None, alias="computationId", pattern=TRACE_COMPUTATION_ID_PATTERN
    )
    #: 转换说明：排序、Top N/其他项、缺值、单位换算、分面等。
    transform_notes: tuple[str, ...] = Field(
        alias="transformNotes", default=(), max_length=50
    )
    series: tuple[ChartSeriesV1, ...] = Field(default=(), max_length=100)
    axis_unit: str | None = Field(default=None, alias="axisUnit", max_length=64)
    script_file_resource_id: str | None = Field(
        default=None, alias="scriptFileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )

    @model_validator(mode="after")
    def validate_unique(self) -> ChartTraceV1:
        if len(self.plot_data_file_resource_ids) != len(
            set(self.plot_data_file_resource_ids)
        ):
            raise ValueError("作图数据文件引用不能重复")
        if len(self.dataset_ids) != len(set(self.dataset_ids)):
            raise ValueError("图表数据集引用不能重复")
        if not self.fact_refs and self.computation_id is None:
            # 基础图直接追到 CSV；分析结果图必须追到 facts 或计算记录。
            if self.series and all(
                s.series_kind in ("predicted", "confidence_interval")
                for s in self.series
            ):
                raise ValueError("预测/区间系列必须绑定 facts 或计算记录")
        return self


class TableCellBindingV1(StrictModel):
    """表格单元格绑定。rowKey/columnKey 是冻结结构键（计划 3.2）。"""

    row_key: str = Field(alias="rowKey", pattern=TRACE_STRUCTURE_KEY_PATTERN)
    column_key: str = Field(alias="columnKey", pattern=TRACE_STRUCTURE_KEY_PATTERN)
    fact_refs: tuple[FactRefV1, ...] = Field(
        default=(), alias="factRefs", max_length=50
    )
    computation_id: str | None = Field(
        default=None, alias="computationId", pattern=TRACE_COMPUTATION_ID_PATTERN
    )
    dataset_ids: tuple[str, ...] = Field(default=(), alias="datasetIds", max_length=10)


class TableTraceV1(StrictModel):
    """结构化表格追溯：冻结行列键与单元格绑定（计划 4.2）。

    插入行列不能复用旧单元格身份：单元格身份 = (rowKey, columnKey)，
    与渲染位置无关。
    """

    table_id: str = Field(alias="tableId", pattern=TRACE_TABLE_ID_PATTERN)
    row_keys: tuple[str, ...] = Field(alias="rowKeys", min_length=1, max_length=1000)
    column_keys: tuple[str, ...] = Field(
        alias="columnKeys", min_length=1, max_length=200
    )
    cells: tuple[TableCellBindingV1, ...] = Field(default=(), max_length=2000)

    @model_validator(mode="after")
    def validate_structure(self) -> TableTraceV1:
        if len(self.row_keys) != len(set(self.row_keys)):
            raise ValueError("rowKey 不能重复")
        if len(self.column_keys) != len(set(self.column_keys)):
            raise ValueError("columnKey 不能重复")
        seen: set[tuple[str, str]] = set()
        for cell in self.cells:
            if cell.row_key not in self.row_keys:
                raise ValueError(f"单元格 rowKey 未在表结构中登记: {cell.row_key}")
            if cell.column_key not in self.column_keys:
                raise ValueError(
                    f"单元格 columnKey 未在表结构中登记: {cell.column_key}"
                )
            key = (cell.row_key, cell.column_key)
            if key in seen:
                raise ValueError(f"单元格身份重复: {key}")
            seen.add(key)
        return self


class SubjectLocatorV1(StrictModel):
    """subject 结构定位。字段组合由 SubjectBindingV1 按 kind 校验。"""

    section_id: str | None = Field(default=None, alias="sectionId", max_length=128)
    table_id: str | None = Field(default=None, alias="tableId", max_length=128)
    row_key: str | None = Field(default=None, alias="rowKey", max_length=128)
    column_key: str | None = Field(default=None, alias="columnKey", max_length=128)
    chart_id: str | None = Field(default=None, alias="chartId", max_length=128)


class SubjectBindingV1(StrictModel):
    """正文/单元格/图表 subject 绑定（计划 3.2）。

    不依赖易变字符偏移或最近数字；subjectSha256 是生成时规范化内容指纹，
    内容绑定状态（valid/stale/unbound）由读取层对比当前内容计算，不写入
    本对象。重复标记不能复制有效授权：subjectId 由 kind+定位内容寻址。
    """

    subject_id: str = Field(alias="subjectId", pattern=TRACE_SUBJECT_ID_PATTERN)
    subject_kind: Literal[
        "text_claim", "table_cell", "chart", "chart_caption"
    ] = Field(alias="subjectKind")
    locator: SubjectLocatorV1
    subject_sha256: str = Field(alias="subjectSha256", pattern=SHA256_PATTERN)
    claim_id: str | None = Field(default=None, alias="claimId", max_length=128)
    fact_refs: tuple[FactRefV1, ...] = Field(
        default=(), alias="factRefs", max_length=100
    )
    computation_id: str | None = Field(
        default=None, alias="computationId", pattern=TRACE_COMPUTATION_ID_PATTERN
    )
    #: 证据性质：数值事实与解释性推断分开（计划 3.3/F05）。
    evidence_kind: EvidenceKindV1 = Field(alias="evidenceKind", default="computed")

    @model_validator(mode="after")
    def validate_locator(self) -> SubjectBindingV1:
        loc = self.locator
        if self.subject_kind == "table_cell":
            if not (loc.table_id and loc.row_key and loc.column_key):
                raise ValueError("table_cell 必须定位 tableId+rowKey+columnKey")
            if loc.chart_id:
                raise ValueError("table_cell 不能定位 chartId")
        elif self.subject_kind in ("chart", "chart_caption"):
            if not loc.chart_id:
                raise ValueError("图表 subject 必须定位 chartId")
            if loc.table_id or loc.row_key or loc.column_key:
                raise ValueError("图表 subject 不能定位表格结构")
        else:  # text_claim
            if loc.table_id or loc.row_key or loc.column_key or loc.chart_id:
                raise ValueError("text_claim 只能定位章节，不能定位表格或图表")
        if self.subject_kind != "text_claim" and self.claim_id is not None:
            raise ValueError("只有 text_claim 可以引用 claim")
        if not self.fact_refs and self.computation_id is None:
            raise ValueError("subject 必须至少绑定 fact 或计算记录")
        return self


class FactFileEntryV1(StrictModel):
    """事实文件登记：analysisId → 冻结文件资源（确定性 bundle / 补证 / 作图数据）。"""

    analysis_id: str = Field(alias="analysisId", pattern=TRACE_ANALYSIS_ID_PATTERN)
    file_resource_id: str = Field(
        alias="fileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    content_kind: FactFileContentKindV1 = Field(alias="contentKind")


class RevisionTraceIndexV1(StrictModel):
    """revision 级追溯索引（计划 3.2）。

    被权威 manifest/context 登记后生效；所有内部引用在构造时校验存在性，
    读取层只需按 resourceId 解析，不从客户端身份或最新可变状态猜测。
    """

    version: Literal["1"] = TRACE_CONTRACT_VERSION
    report_id: str = Field(alias="reportId", min_length=1, max_length=128)
    revision: int = Field(ge=1)
    workflow_run_id: str = Field(
        alias="workflowRunId", min_length=1, max_length=128
    )
    markdown_file_resource_id: str = Field(
        alias="markdownFileResourceId", pattern=TRACE_RESOURCE_ID_PATTERN
    )
    profile_hash: str | None = Field(
        default=None, alias="profileHash", pattern=SHA256_PATTERN
    )
    files: tuple[TraceFileRefV1, ...] = Field(min_length=1, max_length=2000)
    datasets: tuple[DatasetSnapshotRefV1, ...] = Field(
        min_length=1, max_length=100
    )
    fact_files: tuple[FactFileEntryV1, ...] = Field(
        default=(), alias="factFiles", max_length=500
    )
    computations: tuple[ComputationRecordV1, ...] = Field(default=(), max_length=500)
    chart_traces: tuple[ChartTraceV1, ...] = Field(
        default=(), alias="chartTraces", max_length=200
    )
    tables: tuple[TableTraceV1, ...] = Field(default=(), max_length=2000)
    subject_bindings: tuple[SubjectBindingV1, ...] = Field(
        default=(), alias="subjectBindings", max_length=2000
    )
    drilldown_metrics: tuple[DrilldownMetricV1, ...] = Field(
        default=(), alias="drilldownMetrics", max_length=1000
    )

    @model_validator(mode="after")
    def validate_index(self) -> RevisionTraceIndexV1:
        resource_ids = [f.resource_id for f in self.files]
        paths = [f.path for f in self.files]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("文件 resourceId 不能重复")
        if len(paths) != len(set(paths)):
            raise ValueError("文件路径不能重复")
        known_files = set(resource_ids)

        dataset_ids = [d.dataset_id for d in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("datasetId 不能重复")
        for dataset in self.datasets:
            if dataset.file_resource_id not in known_files:
                raise ValueError(f"数据集引用未登记文件: {dataset.dataset_id}")

        drilldown_keys = [
            (item.metric_code, item.dataset_id) for item in self.drilldown_metrics
        ]
        if len(drilldown_keys) != len(set(drilldown_keys)):
            raise ValueError("同一数据集的下钻指标不能重复")
        for item in self.drilldown_metrics:
            if item.dataset_id not in dataset_ids:
                raise ValueError(f"下钻指标引用未登记数据集: {item.metric_code}")

        if self.markdown_file_resource_id not in known_files:
            raise ValueError("正文文件未登记")

        analysis_files: dict[str, str] = {}
        for entry in self.fact_files:
            if entry.analysis_id in analysis_files:
                raise ValueError(f"analysisId 不能重复: {entry.analysis_id}")
            if entry.file_resource_id not in known_files:
                raise ValueError(f"事实文件未登记: {entry.analysis_id}")
            analysis_files[entry.analysis_id] = entry.file_resource_id

        computation_ids = [c.computation_id for c in self.computations]
        if len(computation_ids) != len(set(computation_ids)):
            raise ValueError("computationId 不能重复")

        def _check_fact_ref(ref: FactRefV1) -> None:
            if ref.analysis_id not in analysis_files:
                raise ValueError(f"factRef 引用未登记 analysis: {ref.analysis_id}")
            if ref.file_resource_id != analysis_files[ref.analysis_id]:
                raise ValueError(
                    f"factRef 文件与 analysis 登记不一致: {ref.analysis_id}"
                )

        for computation in self.computations:
            for ref in (*computation.input_fact_refs, *computation.output_fact_refs):
                _check_fact_ref(ref)
            if computation.script_file_resource_id not in (None, *resource_ids):
                raise ValueError("计算记录引用未登记脚本文件")
            unknown_intermediates = [
                rid
                for rid in computation.intermediate_file_resource_ids
                if rid not in known_files
            ]
            if unknown_intermediates:
                raise ValueError("计算记录引用未登记中间文件")
            unknown_datasets = [
                did
                for did in computation.input_dataset_ids
                if did not in dataset_ids
            ]
            if unknown_datasets:
                raise ValueError("计算记录引用未登记数据集")

        for chart in self.chart_traces:
            if chart.image_file_resource_id not in known_files:
                raise ValueError(f"图表引用未登记图片: {chart.chart_id}")
            unknown_plot = [
                rid
                for rid in chart.plot_data_file_resource_ids
                if rid not in known_files
            ]
            if unknown_plot:
                raise ValueError(f"图表引用未登记作图数据: {chart.chart_id}")
            unknown_datasets = [
                did for did in chart.dataset_ids if did not in dataset_ids
            ]
            if unknown_datasets:
                raise ValueError(f"图表引用未登记数据集: {chart.chart_id}")
            for ref in chart.fact_refs:
                _check_fact_ref(ref)
            if chart.computation_id is not None and (
                chart.computation_id not in computation_ids
            ):
                raise ValueError(f"图表引用未登记计算记录: {chart.chart_id}")

        table_ids = [t.table_id for t in self.tables]
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("tableId 不能重复")
        for table in self.tables:
            for cell in table.cells:
                for ref in cell.fact_refs:
                    _check_fact_ref(ref)
                if cell.computation_id is not None and (
                    cell.computation_id not in computation_ids
                ):
                    raise ValueError("单元格引用未登记计算记录")
                unknown_datasets = [
                    did for did in cell.dataset_ids if did not in dataset_ids
                ]
                if unknown_datasets:
                    raise ValueError("单元格引用未登记数据集")

        subject_ids = [s.subject_id for s in self.subject_bindings]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("subjectId 不能重复")
        known_tables = set(table_ids)
        known_charts = {c.chart_id for c in self.chart_traces}
        for subject in self.subject_bindings:
            loc = subject.locator
            if loc.table_id is not None and loc.table_id not in known_tables:
                raise ValueError(f"subject 引用未登记表格: {subject.subject_id}")
            if loc.chart_id is not None and loc.chart_id not in known_charts:
                raise ValueError(f"subject 引用未登记图表: {subject.subject_id}")
            for ref in subject.fact_refs:
                _check_fact_ref(ref)
            if subject.computation_id is not None and (
                subject.computation_id not in computation_ids
            ):
                raise ValueError(f"subject 引用未登记计算记录: {subject.subject_id}")
        return self


# ---------------------------------------------------------------------------
# 稳定错误码与 HTTP 映射（计划 5.2，B0 冻结；接入 report_editor API 时生效）
# ---------------------------------------------------------------------------

TRACE_ERROR_HTTP_STATUS: Mapping[str, int] = {
    "source_missing": 404,
    # 元数据 200 携带 warningCodes；依赖该 subject 的写操作/校验按 409 拒绝。
    "subject_stale": 409,
    "fact_binding_unavailable": 409,
    "snapshot_expired": 410,
    "snapshot_integrity_failed": 409,
    "dataset_access_denied": 403,
    "cursor_invalid": 400,
    # 请求形状非法（不存在的列、非法 limit 等），不进入执行器（计划 5.2）。
    "request_invalid": 400,
    "drilldown_unavailable": 409,
    # 请求形状超出固定预算；并发饱和沿用现有 busy 语义（429）。
    "resource_limit_exceeded": 413,
}

#: 资源预算（计划 4.1/5.3 与 B0-6 基线推导；B1 起生效并纳入压测）。
TRACE_BUDGETS_V1: Mapping[str, int] = {
    "preview_default_rows": 50,
    "preview_max_rows_per_page": 100,
    "preview_max_columns": 50,
    "preview_max_cell_bytes": 4096,
    "preview_max_response_bytes": 1024 * 1024,
    "fact_expand_max_depth": 3,
    "fact_expand_max_nodes": 50,
    "fact_expand_max_response_bytes": 1024 * 1024,
    "drilldown_max_groups": 100,
    "drilldown_max_response_bytes": 1024 * 1024,
    "dataset_max_file_bytes": 200 * 1024 * 1024,
    "max_report_inputs": 100,
    "fact_ref_pointer_max_chars": TRACE_FACT_POINTER_MAX_CHARS,
    "index_max_files": 2000,
    "index_max_subject_bindings": 2000,
    "index_max_charts": 200,
    "index_max_tables": 2000,
    "index_max_computations": 500,
    "export_derived_retention_seconds": 24 * 3600,
}
