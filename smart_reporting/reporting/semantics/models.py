"""新业务契约。组织身份仍由服务端验证，模型不授予资源访问权限。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from .request_types import (
    SHA256_PATTERN,
    DomainCode,
    FieldRef,
    Identity,
    MetricVersionRef,
    PolicyVersionRef,
    ReportQuestion,
    Revision,
    RunIdentity,
    SemanticModel,
)

FiniteDecimal = Annotated[Decimal, Field(allow_inf_nan=False)]
Scalar = StrictStr | StrictInt | StrictBool | FiniteDecimal | None


class Period(SemanticModel):
    """所有新计算窗口统一采用[start, end)，不复用旧闭区间约定。"""

    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Period:
        if self.start >= self.end:
            raise ValueError("期间必须为非空半开区间")
        return self

    def contains(self, value: date) -> bool:
        return self.start <= value < self.end


class DimensionDefinition(SemanticModel):
    id: Identity
    field_ref: FieldRef


class DimensionValue(SemanticModel):
    dimension_id: Identity
    value: Scalar


class AggregationPolicy(SemanticModel):
    observation_kind: Literal["flow", "cumulative_snapshot"]
    time_aggregation: Literal["sum", "difference", "none"]
    reset: Literal["calendar_year_zero", "none"] | None = None

    @model_validator(mode="after")
    def compatible(self) -> AggregationPolicy:
        if self.observation_kind == "flow" and (self.time_aggregation == "difference" or self.reset is not None):
            raise ValueError("事件流不能声明快照差分或重置")
        if self.observation_kind == "cumulative_snapshot" and self.time_aggregation == "sum":
            raise ValueError("累计快照不能直接按时间求和")
        return self


class MetricDefinition(SemanticModel):
    id: Identity
    name: str = Field(min_length=1, max_length=200)
    scope_id: Identity
    revision: Revision
    kind: Literal["sum", "count", "count_distinct", "ratio"]
    field_ref: FieldRef | None = None
    numerator_version: MetricVersionRef | None = None
    denominator_version: MetricVersionRef | None = None
    unit: str = Field(min_length=1, max_length=32)
    grain: tuple[Identity, ...] = Field(min_length=1, max_length=20)
    time_field: FieldRef | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=128)
    storage_time_zone: str | None = Field(default=None, min_length=1, max_length=128)
    dimensions: tuple[DimensionDefinition, ...] = Field(default=(), max_length=20)
    aggregation_policy: AggregationPolicy
    aliases: tuple[str, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def formula_shape(self) -> MetricDefinition:
        if (self.time_zone is None) != (self.storage_time_zone is None):
            raise ValueError("业务时区与存储时区须同时登记")
        for name in (self.time_zone, self.storage_time_zone):
            if name is not None:
                try:
                    ZoneInfo(name)
                except (ZoneInfoNotFoundError, ValueError):
                    raise ValueError("时区须使用有效的IANA名称") from None
        if self.kind == "ratio":
            if self.field_ref is not None or self.time_field is not None:
                raise ValueError("比率只能引用精确指标版本，不能另给字段")
            if self.numerator_version is None or self.denominator_version is None:
                raise ValueError("比率必须同时指定分子与分母版本")
            if self.unit not in ("%", "ratio"):
                raise ValueError("比率单位必须明确为%或ratio")
        elif self.field_ref is None or self.time_field is None or self.numerator_version or self.denominator_version:
            raise ValueError("基础指标必须指定字段与时间字段，且不得指定比率依赖")
        ids = [item.id for item in self.dimensions]
        if len(ids) != len(set(ids)) or len(self.grain) != len(set(self.grain)):
            raise ValueError("维度和粒度不能重复")
        if not set(self.grain).issubset(ids):
            raise ValueError("粒度必须使用已登记维度")
        return self

    def version_ref(self) -> MetricVersionRef:
        return MetricVersionRef(metric_id=self.id, revision=self.revision)


class PolicyFilter(SemanticModel):
    field_ref: FieldRef
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "is_null"]
    values: tuple[Scalar, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def arity(self) -> PolicyFilter:
        if self.operator == "is_null" and self.values:
            raise ValueError("is_null不接受比较值")
        if self.operator == "in" and not self.values:
            raise ValueError("in必须有比较值")
        if self.operator not in ("in", "is_null") and len(self.values) != 1:
            raise ValueError("比较运算必须有一个值")
        return self


class PolicyJoin(SemanticModel):
    left_keys: tuple[FieldRef, ...] = Field(min_length=1, max_length=10)
    right_keys: tuple[FieldRef, ...] = Field(min_length=1, max_length=10)
    cardinality: Literal["many_to_one"] = "many_to_one"
    output_grain: tuple[Identity, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def key_pairs(self) -> PolicyJoin:
        if len(self.left_keys) != len(self.right_keys):
            raise ValueError("关联两端键数必须相同")
        return self


class DataReadinessPolicy(SemanticModel):
    expected_periods: tuple[Period, ...] = ()
    expected_groups: tuple[tuple[DimensionValue, ...], ...] = ()
    watermark_field: FieldRef | None = None
    maximum_delay_seconds: int | None = Field(default=None, ge=0, strict=True)
    empty_observation: Literal["unknown", "zero_when_complete"] = "unknown"

    @model_validator(mode="after")
    def unambiguous_rules(self):
        periods = sorted(self.expected_periods, key=lambda item: item.start)
        if any(left.end > right.start for left, right in zip(periods, periods[1:])):
            raise ValueError("数据就绪期间不能重叠")
        groups = []
        for group in self.expected_groups:
            if not group or len({item.dimension_id for item in group}) != len(group):
                raise ValueError("预期对象必须有唯一的维度值")
            groups.append(frozenset(group))
        if len(set(groups)) != len(groups):
            raise ValueError("预期对象不能重复")
        if self.maximum_delay_seconds is not None and self.watermark_field is None:
            raise ValueError("最大延迟必须同时声明水位字段")
        return self


class StatisticalPolicy(SemanticModel):
    id: Identity
    name: str = Field(min_length=1, max_length=200)
    scope_id: Identity
    revision: Revision
    scenario: Identity
    valid_from: date
    valid_to: date | None = None
    metric_versions: tuple[MetricVersionRef, ...] = Field(min_length=1, max_length=200)
    filters: tuple[PolicyFilter, ...] = Field(default=(), max_length=100)
    joins: tuple[PolicyJoin, ...] = Field(default=(), max_length=20)
    evidence_release_id: Identity
    readiness_policy: DataReadinessPolicy = Field(default_factory=DataReadinessPolicy)
    decision_notes: str = Field(default="", max_length=20000)

    @model_validator(mode="after")
    def validity(self) -> StatisticalPolicy:
        if self.valid_to is not None and self.valid_from >= self.valid_to:
            raise ValueError("生效期必须为非空半开区间")
        if len(set(self.metric_versions)) != len(self.metric_versions):
            raise ValueError("指标版本不能重复")
        return self


class SemanticIssue(SemanticModel):
    code: Identity
    object_id: Identity
    message: str = Field(min_length=1, max_length=2000)
    impact: Literal["unavailable", "warning"]


class MetricRequest(SemanticModel):
    metric_version: MetricVersionRef
    basis_id: Identity
    period: Period
    dimensions: tuple[Identity, ...] = ()
    filter_values: tuple[PolicyFilter, ...] = ()


class MetricResult(SemanticModel):
    metric_version: MetricVersionRef
    basis_id: Identity
    calculation_id: Identity
    fact_id: Identity
    period: Period
    value: FiniteDecimal | None
    unit: str = Field(min_length=1, max_length=32)
    dimensions: tuple[DimensionValue, ...] = ()
    status: Literal["computed", "unavailable"]
    issue_codes: tuple[Identity, ...] = ()
    dataset_ids: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def result_state(self) -> MetricResult:
        if self.status == "computed" and (self.value is None or not self.dataset_ids):
            raise ValueError("计算成功必须有数值和来源数据集")
        if self.status == "unavailable" and (self.value is not None or not self.issue_codes):
            raise ValueError("不可计算必须无值并给出原因")
        return self


class QuestionCoverage(SemanticModel):
    question_id: Identity
    status: Literal["answered", "partial", "unavailable"]
    finding_ids: tuple[Identity, ...] = ()
    subject_ids: tuple[Identity, ...] = ()
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def coverage_state(self) -> QuestionCoverage:
        if self.status == "answered" and not (self.finding_ids or self.subject_ids):
            raise ValueError("已回答必须关联可核对对象")
        if self.status != "answered" and not self.issue_codes:
            raise ValueError("未完整回答必须说明原因")
        return self


class ClaimSupport(SemanticModel):
    subject_id: Identity
    kind: Literal["fact", "inference", "recommendation"]
    fact_refs: tuple[Identity, ...] = ()
    evidence_refs: tuple[Identity, ...] = ()
    support_status: Literal["supported", "unverified", "conflicted"]

    @model_validator(mode="after")
    def support_references(self) -> ClaimSupport:
        if self.support_status == "supported":
            if not (self.fact_refs or self.evidence_refs):
                raise ValueError("已支持必须有关联证据")
            if self.kind == "fact" and not self.fact_refs:
                raise ValueError("数据事实必须关联计算事实")
            if self.kind in {"inference", "recommendation"} and not self.evidence_refs:
                raise ValueError("有数值不等于已支持原因解释")
        return self


class MetricCandidate(SemanticModel):
    metric_version: MetricVersionRef
    reason: str = Field(min_length=1, max_length=2000)


class MetricSelection(SemanticModel):
    question_id: Identity
    status: Literal["resolved", "ambiguous", "unavailable"]
    candidates: tuple[MetricCandidate, ...] = ()
    selected: MetricVersionRef | None = None
    source: Literal["explicit", "scenario", "clarified"] | None = None
    reason: str = Field(default="", max_length=2000)
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def selected_state(self) -> MetricSelection:
        if self.status == "resolved":
            if self.source is None or not self.reason or self.selected not in [c.metric_version for c in self.candidates]:
                raise ValueError("明确选择必须是已核对候选，且有来源和理由")
        elif self.selected is not None or not self.issue_codes:
            raise ValueError("未解决选择不得静默选用，且必须说明原因")
        return self


class CorrectedVersionRef(SemanticModel):
    asset_type: Literal["metric", "statistical_policy", "document", "evidence_release"]
    asset_id: Identity
    revision: Revision | None = None

    @model_validator(mode="after")
    def precise_version(self) -> CorrectedVersionRef:
        if self.asset_type == "evidence_release":
            if self.revision is not None:
                raise ValueError("证据集合自身ID已经标识不可变发布，不另造修订号")
        elif self.revision is None:
            raise ValueError("修复引用必须有精确修订号")
        return self


class ReportIssueReview(SemanticModel):
    issue_id: Identity
    report_revision: Identity
    object_refs: tuple[Identity, ...] = Field(min_length=1)
    category: Literal["calculation", "policy", "data", "citation", "interpretation"]
    description: str = Field(min_length=1, max_length=10000)
    status: Literal["open", "needs_evidence", "accepted", "rejected", "resolved"]
    decision_reason: str = Field(default="", max_length=10000)
    corrected_versions: tuple[CorrectedVersionRef, ...] = ()
    regression_case_ids: tuple[Identity, ...] = ()
    new_report_revision: Identity | None = None
    not_recalculated_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def closure_evidence(self) -> ReportIssueReview:
        if self.status in ("accepted", "rejected", "resolved") and not self.decision_reason:
            raise ValueError("裁定必须有理由")
        if self.status == "resolved" and not (
            self.corrected_versions and self.regression_case_ids
            and (self.new_report_revision or self.not_recalculated_reason)
        ):
            raise ValueError("关闭修复问题必须有版本、回归和重算处理证据")
        return self


class RequestAssumption(SemanticModel):
    field: Identity
    value: str = Field(min_length=1, max_length=4000)
    source: Literal["explicit", "default", "unresolved"]


class ReportRequestSummary(SemanticModel):
    goal: str = Field(min_length=1, max_length=20000)
    scenario: Identity
    organization: Identity
    period: Period
    comparison_period: Period | None = None
    display_unit: str = Field(min_length=1, max_length=32)
    domains: tuple[DomainCode, ...] | None = Field(default=None, min_length=1, max_length=6)
    requested_outputs: tuple[Literal["pdf", "docx", "pptx", "xlsx"], ...] = Field(min_length=1, max_length=4)
    questions: tuple[ReportQuestion, ...] = Field(min_length=1, max_length=50)
    assumptions: tuple[RequestAssumption, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_questions(self) -> ReportRequestSummary:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("问题ID不能重复")
        if len(self.requested_outputs) != len(set(self.requested_outputs)):
            raise ValueError("输出形式不能重复")
        if self.domains is not None and len(self.domains) != len(set(self.domains)):
            raise ValueError("业务范围不能重复")
        return self


class ReadinessCheck(SemanticModel):
    name: Identity
    status: Literal["pass", "fail", "unknown"]
    fact_refs: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def passed_evidence(self) -> ReadinessCheck:
        if self.status == "pass" and not self.fact_refs:
            raise ValueError("通过检查必须有事实依据")
        return self


class UnmatchedGroup(SemanticModel):
    side: Literal["numerator", "denominator"]
    dimensions: tuple[DimensionValue, ...] = Field(min_length=1)
    value: FiniteDecimal | None
    unit: str = Field(min_length=1, max_length=32)
    fact_refs: tuple[Identity, ...] = Field(min_length=1)


class DataReadiness(SemanticModel):
    metric_version: MetricVersionRef
    requested_period: Period
    observed_period: Period | None
    extracted_at: AwareDatetime
    source_watermark: AwareDatetime | None = None
    checks: tuple[ReadinessCheck, ...] = Field(min_length=1)
    unmatched_groups: tuple[UnmatchedGroup, ...] = ()
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def readiness_state(self) -> DataReadiness:
        if any(check.status != "pass" for check in self.checks) and not self.issue_codes:
            raise ValueError("数据检查失败或未知必须有具体原因")
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("同名就绪检查不能有多个状态")
        return self


class SourceVersionRef(SemanticModel):
    source_id: Identity
    revision: Revision
    content_hash: str = Field(pattern=SHA256_PATTERN)


class BuildIdentity(SemanticModel):
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_hash: str = Field(pattern=SHA256_PATTERN)
    dependency_hash: str = Field(pattern=SHA256_PATTERN)
    compiler_version: Identity


class ReportBasis(SemanticModel):
    id: Identity
    run_id: RunIdentity
    scope_id: Identity
    policy_version: PolicyVersionRef
    metric_versions: tuple[MetricVersionRef, ...] = Field(min_length=1)
    source_versions: tuple[SourceVersionRef, ...] = Field(min_length=1)
    catalog_refs: tuple[SourceVersionRef, ...] = Field(min_length=1)
    evidence_release_id: Identity
    background_release_id: Identity | None = None
    request_summary: ReportRequestSummary
    build_identity: BuildIdentity
    knowledge_as_of: AwareDatetime
    reproducible_until: AwareDatetime | None = None
    registered_at: AwareDatetime
    status: Literal["registered", "completed", "partial"] = "registered"

    @model_validator(mode="after")
    def basis_identity(self) -> ReportBasis:
        if self.request_summary.organization != self.scope_id:
            raise ValueError("报告请求与依据scope不一致")
        if self.knowledge_as_of > self.registered_at:
            raise ValueError("不能声称知道登记时间之后的知识")
        for refs in (self.metric_versions, self.source_versions, self.catalog_refs):
            if len(refs) != len(set(refs)):
                raise ValueError("精确版本引用不能重复")
        sources = [ref.source_id for ref in self.source_versions]
        catalogs = [ref.source_id for ref in self.catalog_refs]
        if len(sources) != len(set(sources)) or len(catalogs) != len(set(catalogs)) or set(sources) != set(catalogs):
            raise ValueError("每个数据源必须有唯一已登记版本与目录")
        return self
