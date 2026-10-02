"""报告数据追溯 B0 冻结契约：revision 来源索引及其引用对象。

本模块只定义可校验的数据形状与引用关系，不读取文件、不签发权限。文件实际身份由
发布/Editor 服务按 FileRefV1 重新哈希核对；本索引自身的摘要不能作为唯一信任根，
必须被权威 manifest/context 登记后才可用于来源 API。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal

from jsonpointer import EndOfList, JsonPointer, JsonPointerException
from pydantic import Field, field_validator, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..workflow.checkpoint import FileIdentity

TRACE_CONTRACT_VERSION: Literal["1"] = "1"

# 资源 ID 对客户端不透明，由服务端生成；API 只能经当前 revision 的索引把它解析为文件。
RESOURCE_ID_PATTERN = r"^res_[0-9a-f]{32}$"
REF_ID_PATTERN = r"^[a-z]+_[0-9a-zA-Z_-]{1,120}$"
MAX_FACT_POINTER_LENGTH = 512

ContentBinding = Literal["valid", "stale", "unbound"]
FileAvailability = Literal["available", "missing", "expired", "integrity_failed"]
ComputationVerification = Literal["verified", "not_checked", "failed", "not_applicable"]
EvidenceNature = Literal["observed", "computed", "estimated", "interpretation"]
Reproducibility = Literal["reproducible", "limited", "unavailable"]

TraceErrorCode = Literal[
    "source_missing",
    "subject_stale",
    "fact_binding_unavailable",
    "snapshot_expired",
    "snapshot_integrity_failed",
    "dataset_access_denied",
    "cursor_invalid",
    "drilldown_unavailable",
    "resource_limit_exceeded",
]

# 合法对象的 stale/过期属于业务状态而非请求失败：元数据读取返回 200 并携带
# warningCodes；只有依赖文件内容的操作才按下表映射。404 不区分“不存在”与“不属于当前
# 授权索引”，避免探测其他报告对象。
TRACE_ERROR_HTTP_STATUS: Mapping[str, int] = {
    "source_missing": 404,
    "subject_stale": 409,
    "fact_binding_unavailable": 404,
    "snapshot_expired": 410,
    "snapshot_integrity_failed": 409,
    "dataset_access_denied": 403,
    "cursor_invalid": 400,
    "drilldown_unavailable": 422,
    "resource_limit_exceeded": 429,
}

FactKind = Literal[
    "metric", "comparison", "derived", "reconciliation", "correlation", "supplemental"
]

# FactRef 只能指向登记事实类型所在的集合，防止用指针读取同一文件中的任意内容。
FACT_COLLECTIONS: Mapping[str, frozenset[str]] = {
    "metric": frozenset({"metrics"}),
    "comparison": frozenset({"comparisons"}),
    "derived": frozenset({"derivedMetrics"}),
    "reconciliation": frozenset({"reconciliations"}),
    "correlation": frozenset({"correlations"}),
    "supplemental": frozenset({"findings", "reconciliations"}),
}

TraceMediaType = Literal[
    "text/csv",
    "application/json",
    "image/png",
    "image/jpeg",
    "text/x-python",
]


class FileRefV1(FileIdentity):
    """服务端相对路径 + 内容身份；API 响应不得返回 path。"""

    resource_id: str = Field(alias="resourceId", pattern=RESOURCE_ID_PATTERN)
    media_type: TraceMediaType = Field(alias="mediaType")


class DatasetSnapshotRefV1(StrictModel):
    dataset_ref_id: str = Field(alias="datasetRefId", pattern=REF_ID_PATTERN)
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    file: FileRefV1
    source_type: Literal["starrocks_materialized", "url_csv"] = Field(alias="sourceType")
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    period_roles: tuple[Literal["current", "yoy", "mom"], ...] = Field(
        alias="periodRoles", min_length=1, max_length=3
    )
    query_window_id: str = Field(alias="queryWindowId", min_length=1, max_length=128)
    row_count: int = Field(alias="rowCount", ge=0)
    # None 表示未知：旧数据不得用文件 mtime 推断物化时间。
    materialized_at: datetime | None = Field(default=None, alias="materializedAt")
    display_name: str = Field(alias="displayName", min_length=1, max_length=256)
    filename: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_snapshot(self) -> DatasetSnapshotRefV1:
        if self.file.media_type != "text/csv":
            raise ValueError("Dataset 快照必须是 CSV 文件")
        if len(self.period_roles) != len(set(self.period_roles)):
            raise ValueError("periodRoles 不能重复")
        # 与 DatasetHandle 保持一致：URL CSV 有用户文件名，物化查询结果没有。
        if (self.source_type == "url_csv") != (self.filename is not None):
            raise ValueError("只有 url_csv 快照必须且只能携带 filename")
        if self.materialized_at is not None and self.materialized_at.tzinfo is None:
            raise ValueError("materializedAt 必须带时区")
        return self


def parse_fact_pointer(pointer: str, kind: str) -> tuple[str, ...]:
    """解析受限 RFC 6901 指针；只允许指向登记事实集合内部的节点。"""

    if len(pointer) > MAX_FACT_POINTER_LENGTH or not pointer.startswith("/"):
        raise ValueError("FactRef pointer 必须是长度受限的绝对 JSON Pointer")
    try:
        parts = tuple(JsonPointer(pointer).get_parts())
    except JsonPointerException as error:
        raise ValueError("FactRef pointer 包含无效转义") from error
    allowed = FACT_COLLECTIONS.get(kind, frozenset())
    if len(parts) < 2 or parts[0] not in allowed or "-" in parts:
        raise ValueError("FactRef pointer 必须指向登记事实集合中的具体记录")
    return parts


class FactRefV1(StrictModel):
    """不可变事实文件中的精确记录；新文件重排不迁移旧引用。"""

    fact_ref_id: str = Field(alias="factRefId", pattern=REF_ID_PATTERN)
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    kind: FactKind
    file: FileRefV1
    pointer: str = Field(min_length=2, max_length=MAX_FACT_POINTER_LENGTH)
    evidence_nature: EvidenceNature = Field(alias="evidenceNature")
    dataset_ref_ids: tuple[str, ...] = Field(alias="datasetRefIds", max_length=20)
    input_fact_ref_ids: tuple[str, ...] = Field(default=(), alias="inputFactRefIds", max_length=50)

    @model_validator(mode="after")
    def validate_fact_ref(self) -> FactRefV1:
        if self.file.media_type != "application/json":
            raise ValueError("事实文件必须是 JSON")
        parse_fact_pointer(self.pointer, self.kind)
        if self.evidence_nature == "interpretation":
            raise ValueError("FactRef 只能登记数值事实；业务解释由 SubjectBinding 表达")
        _require_unique("datasetRefIds", self.dataset_ref_ids)
        _require_unique("inputFactRefIds", self.input_fact_ref_ids)
        if self.fact_ref_id in self.input_fact_ref_ids:
            raise ValueError("FactRef 不能依赖自身")
        if not self.dataset_ref_ids and not self.input_fact_ref_ids:
            raise ValueError("FactRef 必须能追溯到 CSV 快照或输入事实")
        return self


def resolve_fact(document: Any, ref: FactRefV1) -> Any:
    """在已核验身份的事实文件内容中解析 FactRef；未知指针统一视为绑定不可用。"""

    current = document
    try:
        for token in parse_fact_pointer(ref.pointer, ref.kind):
            if not isinstance(current, dict | list):
                raise JsonPointerException("FactRef 只能穿过 JSON object/array")
            current = JsonPointer.from_parts((token,)).resolve(current)
            if isinstance(current, EndOfList):
                raise JsonPointerException("FactRef 不接受数组末尾标记")
    except (JsonPointerException, TypeError, ValueError) as error:
        raise LookupError("fact_binding_unavailable") from error
    return current


class ComputationRecordV1(StrictModel):
    """多步/补充分析的计算依据；运行成功不代表数值复核通过。"""

    computation_id: str = Field(alias="computationId", pattern=REF_ID_PATTERN)
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    method: str = Field(min_length=1, max_length=128)
    method_version: str = Field(alias="methodVersion", min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=100)
    input_dataset_ref_ids: tuple[str, ...] = Field(
        default=(), alias="inputDatasetRefIds", max_length=100
    )
    input_fact_ref_ids: tuple[str, ...] = Field(default=(), alias="inputFactRefIds", max_length=200)
    preprocessing: tuple[str, ...] = Field(default=(), max_length=50)
    intermediate_files: tuple[FileRefV1, ...] = Field(
        default=(), alias="intermediateFiles", max_length=50
    )
    script: FileRefV1 | None = None
    execution_id: str | None = Field(default=None, alias="executionId", max_length=256)
    output_fact_ref_ids: tuple[str, ...] = Field(
        alias="outputFactRefIds", min_length=1, max_length=200
    )
    limitations: tuple[str, ...] = Field(default=(), max_length=50)
    verification: ComputationVerification
    reproducibility: Reproducibility

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def validate_record(self) -> ComputationRecordV1:
        _require_unique("inputDatasetRefIds", self.input_dataset_ref_ids)
        _require_unique("inputFactRefIds", self.input_fact_ref_ids)
        _require_unique("outputFactRefIds", self.output_fact_ref_ids)
        if not self.input_dataset_ref_ids and not self.input_fact_ref_ids:
            raise ValueError("计算记录必须声明输入 CSV 或输入事实")
        if set(self.input_fact_ref_ids) & set(self.output_fact_ref_ids):
            raise ValueError("计算记录的输入与输出事实不能重叠")
        if self.script is not None and self.script.media_type != "text/x-python":
            raise ValueError("计算脚本必须登记为 Python 文件")
        if self.reproducibility == "reproducible" and (
            self.script is None or self.execution_id is None
        ):
            raise ValueError("缺少脚本或执行身份时不能声明可复算")
        return self


class ChartSeriesV1(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    column: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=64)
    axis: Literal["primary", "secondary"] = "primary"
    kind: Literal["observed", "forecast", "interval_lower", "interval_upper"] = "observed"


class ChartTraceV1(StrictModel):
    """静态图片与实际传给绘图库的最终数据共同登记。"""

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    image: FileRefV1
    plot_data: tuple[FileRefV1, ...] = Field(alias="plotData", min_length=1, max_length=10)
    category_column: str = Field(alias="categoryColumn", min_length=1, max_length=128)
    series: tuple[ChartSeriesV1, ...] = Field(min_length=1, max_length=50)
    transformations: tuple[str, ...] = Field(default=(), max_length=50)
    dataset_ref_ids: tuple[str, ...] = Field(default=(), alias="datasetRefIds", max_length=100)
    fact_ref_ids: tuple[str, ...] = Field(default=(), alias="factRefIds", max_length=200)
    script: FileRefV1 | None = None
    visual_review_status: Literal["passed", "not_run"] = Field(alias="visualReviewStatus")

    @model_validator(mode="after")
    def validate_chart(self) -> ChartTraceV1:
        if self.image.media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("ChartTrace 只登记静态 PNG/JPEG 图片")
        if any(item.media_type != "text/csv" for item in self.plot_data):
            raise ValueError("作图数据必须登记为 CSV")
        if self.script is not None and self.script.media_type != "text/x-python":
            raise ValueError("作图脚本必须登记为 Python 文件")
        _require_unique("datasetRefIds", self.dataset_ref_ids)
        _require_unique("factRefIds", self.fact_ref_ids)
        _require_unique("series.name", tuple(item.name for item in self.series))
        if not self.dataset_ref_ids and not self.fact_ref_ids:
            raise ValueError("图表必须追溯到 CSV 快照或事实")
        return self


class TableCellLocatorV1(StrictModel):
    """rowKey/columnKey 是生成时冻结的结构键，不是显示位置。"""

    table_id: str = Field(alias="tableId", min_length=1, max_length=128)
    row_key: str = Field(alias="rowKey", min_length=1, max_length=256)
    column_key: str = Field(alias="columnKey", min_length=1, max_length=256)


class SubjectBindingV1(StrictModel):
    subject_id: str = Field(alias="subjectId", pattern=REF_ID_PATTERN)
    subject_type: Literal["claim", "table_cell", "chart"] = Field(alias="subjectType")
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    claim_id: str | None = Field(default=None, alias="claimId", max_length=128)
    table_cell: TableCellLocatorV1 | None = Field(default=None, alias="tableCell")
    chart_id: str | None = Field(default=None, alias="chartId", max_length=128)
    # 生成时规范化内容的摘要；编辑后用它判断 valid/stale，不依赖字符偏移。
    subject_sha256: str = Field(alias="subjectSha256", pattern=SHA256_PATTERN)
    evidence_nature: EvidenceNature = Field(alias="evidenceNature")
    fact_ref_ids: tuple[str, ...] = Field(default=(), alias="factRefIds", max_length=100)
    dataset_ref_ids: tuple[str, ...] = Field(default=(), alias="datasetRefIds", max_length=100)

    @model_validator(mode="after")
    def validate_subject(self) -> SubjectBindingV1:
        locators = {
            "claim": self.claim_id,
            "table_cell": self.table_cell,
            "chart": self.chart_id,
        }
        if locators[self.subject_type] is None or any(
            value is not None for key, value in locators.items() if key != self.subject_type
        ):
            raise ValueError("SubjectBinding 必须且只能携带与类型对应的定位")
        _require_unique("factRefIds", self.fact_ref_ids)
        _require_unique("datasetRefIds", self.dataset_ref_ids)
        if self.subject_type != "chart" and not self.fact_ref_ids and not self.dataset_ref_ids:
            raise ValueError("正文与单元格绑定必须引用事实或 CSV 快照")
        # 解释性结论必须保留支持事实，不能只挂在 dataset 级引用上冒充已验证结论。
        if self.evidence_nature == "interpretation" and not self.fact_ref_ids:
            raise ValueError("解释性结论必须引用支持事实")
        return self


class RevisionTraceIndexV1(StrictModel):
    version: Literal["1"] = TRACE_CONTRACT_VERSION
    report_id: str = Field(alias="reportId", min_length=1, max_length=256)
    revision: int = Field(ge=1)
    workflow_run_id: str = Field(alias="workflowRunId", min_length=1, max_length=256)
    markdown_sha256: str = Field(alias="markdownSha256", pattern=SHA256_PATTERN)
    effective_profile_hash: str = Field(alias="effectiveProfileHash", pattern=SHA256_PATTERN)
    datasets: tuple[DatasetSnapshotRefV1, ...] = Field(default=(), max_length=100)
    facts: tuple[FactRefV1, ...] = Field(default=(), max_length=20_000)
    computations: tuple[ComputationRecordV1, ...] = Field(default=(), max_length=2_000)
    charts: tuple[ChartTraceV1, ...] = Field(default=(), max_length=100)
    subjects: tuple[SubjectBindingV1, ...] = Field(default=(), max_length=20_000)

    @model_validator(mode="after")
    def validate_references(self) -> RevisionTraceIndexV1:
        dataset_ids = _unique_ids("datasetRefId", (item.dataset_ref_id for item in self.datasets))
        fact_ids = _unique_ids("factRefId", (item.fact_ref_id for item in self.facts))
        _unique_ids("computationId", (item.computation_id for item in self.computations))
        chart_ids = _unique_ids("chartId", (item.chart_id for item in self.charts))
        _unique_ids("subjectId", (item.subject_id for item in self.subjects))
        _unique_ids(
            "fact location",
            (f"{item.file.resource_id}#{item.pointer}" for item in self.facts),
        )
        self._validate_resources()

        def require_known(name: str, values: Iterable[str], known: set[str]) -> None:
            if set(values) - known:
                raise ValueError(f"来源索引引用了未登记的 {name}")

        for fact in self.facts:
            require_known("datasetRefId", fact.dataset_ref_ids, dataset_ids)
            require_known("factRefId", fact.input_fact_ref_ids, fact_ids)
        for computation in self.computations:
            require_known("datasetRefId", computation.input_dataset_ref_ids, dataset_ids)
            require_known("factRefId", computation.input_fact_ref_ids, fact_ids)
            require_known("factRefId", computation.output_fact_ref_ids, fact_ids)
        for chart in self.charts:
            require_known("datasetRefId", chart.dataset_ref_ids, dataset_ids)
            require_known("factRefId", chart.fact_ref_ids, fact_ids)
        for subject in self.subjects:
            require_known("datasetRefId", subject.dataset_ref_ids, dataset_ids)
            require_known("factRefId", subject.fact_ref_ids, fact_ids)
            if subject.chart_id is not None:
                require_known("chartId", (subject.chart_id,), chart_ids)

        producers: dict[str, str] = {}
        for computation in self.computations:
            for fact_id in computation.output_fact_ref_ids:
                if producers.setdefault(fact_id, computation.computation_id) != (
                    computation.computation_id
                ):
                    raise ValueError("同一事实不能由多个计算记录产出")
        _require_acyclic({item.fact_ref_id: item.input_fact_ref_ids for item in self.facts})
        computation_inputs: dict[str, tuple[str, ...]] = {}
        for computation in self.computations:
            for fact_id in computation.output_fact_ref_ids:
                computation_inputs[fact_id] = computation.input_fact_ref_ids
        _require_acyclic(computation_inputs)
        return self

    def _validate_resources(self) -> None:
        """同一 resourceId 必须始终指向同一文件身份，避免借 ID 复用读取其他文件。"""

        seen: dict[str, FileRefV1] = {}
        for ref in self.file_refs():
            previous = seen.setdefault(ref.resource_id, ref)
            if previous != ref:
                raise ValueError("同一 resourceId 绑定了不同文件身份")

    def file_refs(self) -> tuple[FileRefV1, ...]:
        refs: list[FileRefV1] = [item.file for item in self.datasets]
        refs.extend(item.file for item in self.facts)
        for computation in self.computations:
            refs.extend(computation.intermediate_files)
            if computation.script is not None:
                refs.append(computation.script)
        for chart in self.charts:
            refs.append(chart.image)
            refs.extend(chart.plot_data)
            if chart.script is not None:
                refs.append(chart.script)
        return tuple(refs)


def canonical_json_bytes(value: Any) -> bytes:
    """契约 canonical JSON：键排序、紧凑分隔、UTF-8；拒绝 NaN/Infinity 与非 JSON 类型。"""

    def reject_non_finite(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("契约 JSON 不允许 NaN/Infinity")
        if isinstance(item, Mapping):
            for child in item.values():
                reject_non_finite(child)
        elif isinstance(item, list | tuple):
            for child in item:
                reject_non_finite(child)

    reject_non_finite(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except TypeError as error:
        raise ValueError("契约 JSON 只能包含 JSON 原生类型") from error


def trace_index_sha256(index: RevisionTraceIndexV1) -> str:
    return hashlib.sha256(
        canonical_json_bytes(index.model_dump(mode="json", by_alias=True))
    ).hexdigest()


def _require_unique(name: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} 不能重复")


def _unique_ids(name: str, values: Iterable[str]) -> set[str]:
    items = tuple(values)
    _require_unique(name, items)
    return set(items)


def _require_acyclic(edges: Mapping[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    done: set[str] = set()
    for root in edges:
        if root in done:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        visiting.add(root)
        while stack:
            node, index = stack[-1]
            children = edges.get(node, ())
            if index >= len(children):
                stack.pop()
                visiting.discard(node)
                done.add(node)
                continue
            stack[-1] = (node, index + 1)
            child = children[index]
            if child in visiting:
                raise ValueError("事实依赖存在循环")
            if child not in done:
                visiting.add(child)
                stack.append((child, 0))
