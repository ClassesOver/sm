from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from ..data_source.period import PeriodRole
from ..models import ReportingError

MoneyUnit = Literal["元", "万元", "亿元"]
# FactSet 的基础 facts 是服务端冻结的审计事实，不是模型上下文。真实瑞金验收中，
# 多张明细查询合计约 16 万条事实；上限必须高于该受控规模，但仍要与单文件 200 MiB
# 边界配套，防止无界输入占用内存。模型只消费下游的可展示 MetricFact。
MAX_FACT_COUNT = 250_000
MAX_METRIC_FACT_COUNT = 20_000
MAX_METRIC_INPUT_FACT_COUNT = 100_000
CoverageStatus = Literal[
    "complete", "partial", "zero_placeholder", "missing", "conflict", "unconfirmed"
]
MetricOperation = Literal["sum", "difference", "ratio_percent"]


class OperationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class FactEvidence(OperationModel):
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    schema_hash: str | None = Field(default=None, alias="schemaHash", pattern=r"^[0-9a-f]{64}$")
    sql_hash: str | None = Field(default=None, alias="sqlHash", pattern=r"^[0-9a-f]{64}$")
    file_hash: str | None = Field(default=None, alias="fileHash", pattern=r"^[0-9a-f]{64}$")
    references: tuple[str, ...] = Field(default=(), max_length=50)


class HospitalOperationFact(OperationModel):
    """一个不可变业务事实；原值和规范值同时保留，避免展示换算丢失证据。"""

    fact_id: str = Field(alias="factId", min_length=1, max_length=256)
    domain: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=128)
    hospital: str = Field(min_length=1, max_length=200)
    campus: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    accounting_unit: str | None = Field(default=None, alias="accountingUnit", max_length=200)
    period: str = Field(min_length=1, max_length=32)
    period_role: PeriodRole = Field(default="current", alias="periodRole")
    coverage: CoverageStatus
    raw_value: Decimal | None = Field(default=None, alias="rawValue")
    raw_unit: str = Field(alias="rawUnit", min_length=1, max_length=32)
    normalized_value: Decimal | None = Field(default=None, alias="normalizedValue")
    normalized_unit: str = Field(alias="normalizedUnit", min_length=1, max_length=32)
    conversion_factor: Decimal = Field(default=Decimal("1"), alias="conversionFactor")
    formula: str | None = Field(default=None, max_length=500)
    grain: tuple[str, ...] = Field(default=(), max_length=30)
    evidence: FactEvidence
    conflicts: tuple[str, ...] = Field(default=(), max_length=50)
    pending_confirmations: tuple[str, ...] = Field(
        default=(), alias="pendingConfirmations", max_length=50
    )
    parent_metric: str | None = Field(default=None, alias="parentMetric", max_length=128)
    is_subset: bool = Field(default=False, alias="isSubset")

    @field_serializer("raw_value", "normalized_value", "conversion_factor")
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")

    @model_validator(mode="after")
    def validate_value(self) -> HospitalOperationFact:
        if self.raw_value is None:
            if self.normalized_value is not None:
                raise ValueError("缺少原值时不得写入规范值")
            return self
        expected = self.raw_value * self.conversion_factor
        if self.normalized_value is None:
            object.__setattr__(self, "normalized_value", expected)
        elif self.normalized_value != expected:
            raise ValueError("normalizedValue 与 rawValue/conversionFactor 不一致")
        if self.coverage == "missing" and self.raw_value is not None:
            raise ValueError("missing 事实不得包含原值")
        if self.conflicts and self.coverage != "conflict":
            raise ValueError("包含冲突的事实必须标记为 conflict")
        if self.pending_confirmations and self.coverage not in {"unconfirmed", "conflict"}:
            raise ValueError("待确认事实必须标记为 unconfirmed 或 conflict")
        return self

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class MetricFormula(OperationModel):
    """服务端可复算公式；左右事实集合的角色固定，禁止依赖自然语言公式。"""

    operation: MetricOperation
    left_fact_ids: tuple[str, ...] = Field(
        alias="leftFactIds", min_length=1, max_length=MAX_METRIC_INPUT_FACT_COUNT
    )
    right_fact_ids: tuple[str, ...] = Field(
        default=(), alias="rightFactIds", max_length=MAX_METRIC_INPUT_FACT_COUNT
    )

    @model_validator(mode="after")
    def validate_operands(self) -> MetricFormula:
        values = (*self.left_fact_ids, *self.right_fact_ids)
        if len(values) != len(set(values)):
            raise ValueError("MetricFact 公式输入 factId 不能重复")
        if self.operation == "sum" and self.right_fact_ids:
            raise ValueError("sum 公式不得包含右侧输入")
        if self.operation != "sum" and not self.right_fact_ids:
            raise ValueError("difference/ratio_percent 公式必须包含右侧输入")
        return self

    @property
    def input_fact_ids(self) -> tuple[str, ...]:
        return (*self.left_fact_ids, *self.right_fact_ids)


class HospitalOperationMetricFact(OperationModel):
    """由服务端从已冻结事实复算的可展示指标；模型只能引用，不能提交数值。"""

    fact_id: str = Field(alias="factId", min_length=1, max_length=256)
    domain: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=128)
    hospital: str = Field(min_length=1, max_length=200)
    scope: Literal["month", "report_period", "common_period", "support"]
    period_role: PeriodRole = Field(default="current", alias="periodRole")
    periods: tuple[str, ...] = Field(min_length=1, max_length=1_200)
    coverage: CoverageStatus
    normalized_value: Decimal = Field(alias="normalizedValue")
    normalized_unit: str = Field(alias="normalizedUnit", min_length=1, max_length=32)
    formula: MetricFormula
    input_fact_ids: tuple[str, ...] = Field(
        alias="inputFactIds", min_length=1, max_length=MAX_METRIC_INPUT_FACT_COUNT
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    display_value: Decimal = Field(alias="displayValue")
    display_unit: str = Field(alias="displayUnit", min_length=1, max_length=32)
    display_factor: Decimal = Field(alias="displayFactor", gt=0)
    display_scale: int = Field(alias="displayScale", ge=0, le=8)
    display_text: str = Field(alias="displayText", min_length=1, max_length=100)
    # support 事实只用于分块复算，不得被正文、图表或发布门禁作为业务指标引用。
    publishable: bool = True

    @field_serializer("normalized_value", "display_value", "display_factor")
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")

    @model_validator(mode="after")
    def validate_metric(self) -> HospitalOperationMetricFact:
        if self.scope == "support" and self.publishable:
            raise ValueError("support MetricFact 不得标记为可发布")
        if self.scope != "support" and not self.publishable:
            raise ValueError("非 support MetricFact 必须标记为可发布")
        if self.input_fact_ids != self.formula.input_fact_ids:
            raise ValueError("MetricFact inputFactIds 与结构化公式不一致")
        if (
            len(self.periods) != len(set(self.periods))
            or tuple(sorted(self.periods)) != self.periods
        ):
            raise ValueError("MetricFact periods 必须有序且不能重复")
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("MetricFact citationId 不能重复")
        expected_value = (self.normalized_value / self.display_factor).quantize(
            Decimal(1).scaleb(-self.display_scale), rounding=ROUND_HALF_UP
        )
        if self.display_value != expected_value:
            raise ValueError("MetricFact displayValue 与规范值、换算因子或舍入规则不一致")
        expected_text = f"{self.display_value:.{self.display_scale}f}{self.display_unit}"
        if self.display_text != expected_text:
            raise ValueError("MetricFact displayText 不是服务端规范展示值")
        if self.coverage in {"missing", "conflict", "unconfirmed", "zero_placeholder"}:
            raise ValueError("阻断覆盖状态不得生成可展示 MetricFact")
        return self

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class FactSetIssue(OperationModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    status: Literal["missing", "conflict", "unconfirmed"]
    message: str = Field(min_length=1, max_length=2_000)
    domains: tuple[str, ...] = Field(default=(), max_length=6)
    periods: tuple[str, ...] = Field(default=(), max_length=1_200)
    period_roles: tuple[PeriodRole, ...] = Field(default=(), alias="periodRoles", max_length=3)
    dataset_ids: tuple[str, ...] = Field(default=(), alias="datasetIds", max_length=100)
    fact_ids: tuple[str, ...] = Field(default=(), alias="factIds", max_length=10_000)


class HospitalOperationAnalysisFact(OperationModel):
    """给成稿模型使用的紧凑分析事实卡，不包含明细输入 ID 或原始数值。"""

    fact_id: str = Field(alias="factId", min_length=1, max_length=256)
    domain: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=128)
    hospital: str = Field(min_length=1, max_length=200)
    scope: Literal["month", "report_period", "common_period"]
    period_role: PeriodRole = Field(default="current", alias="periodRole")
    periods: tuple[str, ...] = Field(min_length=1, max_length=1_200)
    display_text: str = Field(alias="displayText", min_length=1, max_length=100)
    display_unit: str = Field(alias="displayUnit", min_length=1, max_length=32)
    formula_operation: MetricOperation = Field(alias="formulaOperation")
    input_fact_count: int = Field(alias="inputFactCount", ge=1, le=MAX_FACT_COUNT)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class HospitalOperationAnalysisFactSet(OperationModel):
    """服务端给模型的分析目录；原始明细仍只在完整 FactSet/CSV 中审计。"""

    version: Literal["1"] = "1"
    hospital: str = Field(min_length=1, max_length=200)
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    period_roles: tuple[PeriodRole, ...] = Field(
        default=("current",), alias="periodRoles", min_length=1, max_length=3
    )
    source_fact_set_hash: str = Field(alias="sourceFactSetHash", pattern=r"^[0-9a-f]{64}$")
    facts: tuple[HospitalOperationAnalysisFact, ...] = Field(
        alias="facts", max_length=MAX_METRIC_FACT_COUNT
    )
    issues: tuple[FactSetIssue, ...] = Field(default=(), max_length=1_000)
    pending_confirmations: tuple[str, ...] = Field(
        default=(), alias="pendingConfirmations", max_length=100
    )
    analysis_hash: str = Field(alias="analysisHash", pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_analysis_set(self) -> HospitalOperationAnalysisFactSet:
        if self.period_start > self.period_end:
            raise ValueError("分析 FactSet 期间无效")
        ids = [item.fact_id for item in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("分析 FactSet factId 不能重复")
        if any(issue.fact_ids for issue in self.issues):
            raise ValueError("分析目录不得携带明细 factId 列表")
        if set(item.period_role for item in self.facts) - set(self.period_roles):
            raise ValueError("分析 FactSet 包含未声明的期间角色")
        if (
            compute_analysis_fact_set_hash(
                self.source_fact_set_hash,
                self.facts,
                self.issues,
                self.pending_confirmations,
                self.period_roles,
            )
            != self.analysis_hash
        ):
            raise ValueError("分析 FactSet hash 与目录内容不一致")
        return self

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class AnalysisFactSetHandle(OperationModel):
    """分析目录的受信文件身份；只允许当前 Workflow 读取。"""

    version: Literal["1"] = "1"
    path: str = Field(min_length=1, max_length=1_024, pattern=r"^[^/].*\.json$")
    size: int = Field(ge=1, le=50 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fact_set_hash: str = Field(alias="sourceFactSetHash", pattern=r"^[0-9a-f]{64}$")
    fact_count: int = Field(alias="factCount", ge=0, le=MAX_METRIC_FACT_COUNT)

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class HospitalOperationFactSet(OperationModel):
    version: Literal["1"] = "1"
    hospital: str = Field(min_length=1, max_length=200)
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    period_roles: tuple[PeriodRole, ...] = Field(
        default=("current",), alias="periodRoles", min_length=1, max_length=3
    )
    facts: tuple[HospitalOperationFact, ...] = Field(max_length=MAX_FACT_COUNT)
    metric_facts: tuple[HospitalOperationMetricFact, ...] = Field(
        default=(), alias="metricFacts", max_length=MAX_METRIC_FACT_COUNT
    )
    issues: tuple[FactSetIssue, ...] = Field(default=(), max_length=1_000)
    pending_confirmations: tuple[str, ...] = Field(
        default=(), alias="pendingConfirmations", max_length=100
    )
    fact_set_hash: str = Field(alias="factSetHash", pattern=r"^[0-9a-f]{64}$")
    generated_at: str = Field(alias="generatedAt", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_set(self) -> HospitalOperationFactSet:
        if self.period_start > self.period_end:
            raise ValueError("FactSet 期间无效")
        if any(item.hospital != self.hospital for item in self.facts):
            raise ValueError("FactSet 包含其他医院事实")
        used_roles = {item.period_role for item in self.facts} | {
            item.period_role for item in self.metric_facts
        }
        if used_roles - set(self.period_roles):
            raise ValueError("FactSet 包含未声明的期间角色")
        if (
            len(self.period_roles) != len(set(self.period_roles))
            or "current" not in self.period_roles
        ):
            raise ValueError("FactSet 期间角色必须包含唯一 current")
        ids = [item.fact_id for item in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("FactSet factId 不能重复")
        metric_ids = [item.fact_id for item in self.metric_facts]
        if len(metric_ids) != len(set(metric_ids)) or set(ids).intersection(metric_ids):
            raise ValueError("FactSet 基础事实与 MetricFact factId 不能重复")
        _validate_metric_facts(self.facts, self.metric_facts)
        fact_ids = set(ids) | set(metric_ids)
        if any(set(issue.fact_ids) - fact_ids for issue in self.issues):
            raise ValueError("FactSet issue 引用了未知 factId")
        if (
            compute_fact_set_hash(
                self.facts,
                metric_facts=self.metric_facts,
                issues=self.issues,
                pending_confirmations=self.pending_confirmations,
                period_roles=self.period_roles,
            )
            != self.fact_set_hash
        ):
            raise ValueError("FactSet hash 与事实内容不一致")
        return self

    def by_domain(self, domain: str) -> tuple[HospitalOperationFact, ...]:
        return tuple(item for item in self.facts if item.domain == domain)

    def metric_by_domain(self, domain: str) -> tuple[HospitalOperationMetricFact, ...]:
        return tuple(item for item in self.metric_facts if item.domain == domain)

    @property
    def all_fact_ids(self) -> frozenset[str]:
        return frozenset(
            [*(item.fact_id for item in self.facts), *(item.fact_id for item in self.metric_facts)]
        )

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class FactSetHandle(OperationModel):
    """Workflow 中持久化的 FactSet 身份；基础事实只保存在受信工作区文件供服务端审计。"""

    version: Literal["1"] = "1"
    path: str = Field(min_length=1, max_length=1_024, pattern=r"^[^/].*\.json$")
    size: int = Field(ge=1, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_set_hash: str = Field(alias="factSetHash", pattern=r"^[0-9a-f]{64}$")
    fact_count: int = Field(alias="factCount", ge=0, le=MAX_FACT_COUNT)
    metric_fact_count: int = Field(
        default=0, alias="metricFactCount", ge=0, le=MAX_METRIC_FACT_COUNT
    )
    domain_counts: dict[str, int] = Field(
        default_factory=dict,
        alias="domainCounts",
        max_length=6,
    )
    analysis_fact_set: AnalysisFactSetHandle | None = Field(default=None, alias="analysisFactSet")

    @model_validator(mode="after")
    def validate_counts(self) -> FactSetHandle:
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", domain)
            or isinstance(count, bool)
            or count < 0
            for domain, count in self.domain_counts.items()
        ):
            raise ValueError("domainCounts 无效")
        if sum(self.domain_counts.values()) != self.fact_count:
            raise ValueError("domainCounts 与 factCount 不一致")
        return self

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class FactSetBuilder:
    """以服务端确定的换算因子和证据构造 FactSet。"""

    def __init__(
        self,
        *,
        hospital: str,
        period_start: date,
        period_end: date,
        generated_at: str,
        pending_confirmations: tuple[str, ...] = (),
        period_roles: tuple[PeriodRole, ...] = ("current",),
    ):
        self.hospital = hospital
        self.period_start = period_start
        self.period_end = period_end
        self.generated_at = generated_at
        self._facts: list[HospitalOperationFact] = []
        self._issues: list[FactSetIssue] = []
        self._pending_confirmations = pending_confirmations
        self._period_roles = period_roles

    def add(
        self,
        *,
        fact_id: str,
        domain: str,
        metric: str,
        period: str,
        period_role: PeriodRole = "current",
        value: Any,
        raw_unit: str,
        normalized_unit: str | None = None,
        evidence: FactEvidence,
        coverage: CoverageStatus = "complete",
        hospital: str | None = None,
        campus: str | None = None,
        department: str | None = None,
        accounting_unit: str | None = None,
        grain: tuple[str, ...] = (),
        formula: str | None = None,
        conflicts: tuple[str, ...] = (),
        pending_confirmations: tuple[str, ...] = (),
        parent_metric: str | None = None,
        is_subset: bool = False,
    ) -> HospitalOperationFact:
        raw = None if value is None else _decimal(value)
        factor = _unit_factor(raw_unit) if raw is not None else Decimal("1")
        target_unit = normalized_unit or ("元" if _is_money_unit(raw_unit) else raw_unit)
        fact = HospitalOperationFact(
            factId=fact_id,
            domain=domain,
            metric=metric,
            hospital=hospital or self.hospital,
            campus=campus,
            department=department,
            accountingUnit=accounting_unit,
            period=period,
            periodRole=period_role,
            coverage=coverage,
            rawValue=raw,
            rawUnit=raw_unit,
            normalizedValue=None if raw is None else raw * factor,
            normalizedUnit=target_unit,
            conversionFactor=factor,
            formula=formula,
            grain=grain,
            evidence=evidence,
            conflicts=conflicts,
            pendingConfirmations=pending_confirmations,
            parentMetric=parent_metric,
            isSubset=is_subset,
        )
        self._facts.append(fact)
        return fact

    def add_issue(
        self,
        *,
        code: str,
        status: Literal["missing", "conflict", "unconfirmed"],
        message: str,
        domains: tuple[str, ...] = (),
        periods: tuple[str, ...] = (),
        period_roles: tuple[PeriodRole, ...] = (),
        dataset_ids: tuple[str, ...] = (),
        fact_ids: tuple[str, ...] = (),
    ) -> FactSetIssue:
        issue = FactSetIssue(
            code=code,
            status=status,
            message=message,
            domains=domains,
            periods=periods,
            periodRoles=period_roles,
            datasetIds=dataset_ids,
            factIds=fact_ids,
        )
        self._issues.append(issue)
        return issue

    def snapshot(self) -> tuple[tuple[HospitalOperationFact, ...], tuple[FactSetIssue, ...]]:
        """返回当前已校验的构建中事实，供对账阶段读取而不提前冻结 FactSet。"""
        return tuple(self._facts), tuple(self._issues)

    def build(
        self,
        *,
        metric_facts: tuple[HospitalOperationMetricFact, ...] = (),
    ) -> HospitalOperationFactSet:
        facts = tuple(self._facts)
        issues = tuple(self._issues)
        if len(facts) > MAX_FACT_COUNT:
            raise ReportingError(
                "hospital_operation_factset_too_large",
                f"确定性 FactSet 基础事实数量 {len(facts)} 超过受控上限 {MAX_FACT_COUNT}。",
            )
        if len(metric_facts) > MAX_METRIC_FACT_COUNT:
            raise ReportingError(
                "hospital_operation_metric_factset_too_large",
                f"确定性 MetricFact 数量 {len(metric_facts)} 超过受控上限 {MAX_METRIC_FACT_COUNT}。",
            )
        return HospitalOperationFactSet(
            hospital=self.hospital,
            periodStart=self.period_start,
            periodEnd=self.period_end,
            periodRoles=self._period_roles,
            facts=facts,
            metricFacts=metric_facts,
            issues=issues,
            pendingConfirmations=self._pending_confirmations,
            factSetHash=compute_fact_set_hash(
                facts,
                metric_facts=metric_facts,
                issues=issues,
                pending_confirmations=self._pending_confirmations,
                period_roles=self._period_roles,
            ),
            generatedAt=self.generated_at,
        )


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ReportingError("hospital_operation_value_invalid", "业务事实数值无效。") from error
    if not result.is_finite():
        raise ReportingError("hospital_operation_value_invalid", "业务事实不得为 NaN 或无穷值。")
    return result


def money_factor(unit: str) -> Decimal:
    normalized = unit.strip().lower()
    factors = {
        "元": Decimal("1"),
        "人民币元": Decimal("1"),
        "yuan": Decimal("1"),
        "万元": Decimal("10000"),
        "万": Decimal("10000"),
        "亿元": Decimal("100000000"),
        "亿": Decimal("100000000"),
    }
    try:
        return factors[normalized]
    except KeyError as error:
        raise ReportingError(
            "hospital_operation_unit_invalid", f"不支持的金额单位: {unit}"
        ) from error


def _is_money_unit(unit: str) -> bool:
    try:
        money_factor(unit)
    except ReportingError:
        return False
    return True


def _unit_factor(unit: str) -> Decimal:
    return money_factor(unit) if _is_money_unit(unit) else Decimal("1")


def normalize_money(value: Any, unit: str) -> Decimal:
    """将金额统一保存为人民币元；不依据数值大小猜测单位。"""
    return _decimal(value) * money_factor(unit)


def display_money(value_in_yuan: Any, *, factor: Decimal, unit: MoneyUnit) -> Decimal:
    if factor <= 0:
        raise ReportingError("hospital_operation_display_factor_invalid", "展示换算因子必须为正。")
    expected = {"元": Decimal("1"), "万元": Decimal("10000"), "亿元": Decimal("100000000")}[unit]
    if factor != expected:
        raise ReportingError(
            "hospital_operation_display_factor_invalid", "展示单位与换算因子不一致。"
        )
    return _decimal(value_in_yuan) / factor


def compute_fact_set_hash(
    facts: tuple[HospitalOperationFact, ...] | list[HospitalOperationFact],
    *,
    metric_facts: tuple[HospitalOperationMetricFact, ...] | list[HospitalOperationMetricFact] = (),
    issues: tuple[FactSetIssue, ...] | list[FactSetIssue] = (),
    pending_confirmations: tuple[str, ...] = (),
    period_roles: tuple[PeriodRole, ...] = ("current",),
) -> str:
    payload = {
        "facts": [item.public_dict() for item in sorted(facts, key=lambda item: item.fact_id)],
        "metricFacts": [
            item.public_dict() for item in sorted(metric_facts, key=lambda item: item.fact_id)
        ],
        "issues": [
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(issues, key=lambda item: (item.code, item.message))
        ],
        "pendingConfirmations": list(pending_confirmations),
        "periodRoles": list(period_roles),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_analysis_fact_set_hash(
    source_fact_set_hash: str,
    facts: tuple[HospitalOperationAnalysisFact, ...] | list[HospitalOperationAnalysisFact],
    issues: tuple[FactSetIssue, ...] | list[FactSetIssue],
    pending_confirmations: tuple[str, ...] = (),
    period_roles: tuple[PeriodRole, ...] = ("current",),
) -> str:
    payload = {
        "sourceFactSetHash": source_fact_set_hash,
        "facts": [item.public_dict() for item in sorted(facts, key=lambda item: item.fact_id)],
        "issues": [
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(issues, key=lambda item: (item.code, item.message))
        ],
        "pendingConfirmations": list(pending_confirmations),
        "periodRoles": list(period_roles),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_analysis_fact_set(
    fact_set: HospitalOperationFactSet,
) -> HospitalOperationAnalysisFactSet:
    """从完整 FactSet 生成不含明细 ID/原值的模型消费目录。"""
    source_counts: dict[str, int] = {item.fact_id: 1 for item in fact_set.facts}
    for item in fact_set.metric_facts:
        source_counts[item.fact_id] = sum(source_counts[fact_id] for fact_id in item.input_fact_ids)
    cards = tuple(
        HospitalOperationAnalysisFact(
            factId=item.fact_id,
            domain=item.domain,
            metric=item.metric,
            hospital=item.hospital,
            scope=cast(Literal["month", "report_period", "common_period"], item.scope),
            periodRole=item.period_role,
            periods=item.periods,
            displayText=item.display_text,
            displayUnit=item.display_unit,
            formulaOperation=item.formula.operation,
            inputFactCount=source_counts[item.fact_id],
            citationIds=item.citation_ids,
        )
        for item in fact_set.metric_facts
        if item.publishable
    )
    issues = tuple(
        FactSetIssue(
            code=item.code,
            status=item.status,
            message=item.message,
            domains=item.domains,
            periods=item.periods,
            periodRoles=item.period_roles,
            datasetIds=item.dataset_ids,
            factIds=(),
        )
        for item in fact_set.issues
    )
    analysis_hash = compute_analysis_fact_set_hash(
        fact_set.fact_set_hash,
        cards,
        issues,
        fact_set.pending_confirmations,
        fact_set.period_roles,
    )
    return HospitalOperationAnalysisFactSet(
        hospital=fact_set.hospital,
        periodStart=fact_set.period_start,
        periodEnd=fact_set.period_end,
        periodRoles=fact_set.period_roles,
        sourceFactSetHash=fact_set.fact_set_hash,
        facts=cards,
        issues=issues,
        pendingConfirmations=fact_set.pending_confirmations,
        analysisHash=analysis_hash,
    )


def _validate_metric_facts(
    facts: tuple[HospitalOperationFact, ...],
    metric_facts: tuple[HospitalOperationMetricFact, ...],
) -> None:
    """按冻结顺序复算 MetricFact，禁止前向引用、循环引用和伪造 citation。"""
    values: dict[str, tuple[Decimal, str]] = {
        item.fact_id: (item.normalized_value, item.normalized_unit)
        for item in facts
        if item.normalized_value is not None
    }
    citations: dict[str, tuple[str, ...]] = {
        item.fact_id: tuple(sorted(set(item.evidence.references))) for item in facts
    }
    period_roles = {item.fact_id: item.period_role for item in facts}
    for metric in metric_facts:
        unknown = set(metric.input_fact_ids) - set(values)
        if unknown:
            raise ValueError("MetricFact 引用了未知、无值或尚未生成的输入事实")
        input_roles = {period_roles[item] for item in metric.input_fact_ids}
        if input_roles != {metric.period_role}:
            raise ValueError("MetricFact 不得混合不同期间角色")
        left = [values[item] for item in metric.formula.left_fact_ids]
        right = [values[item] for item in metric.formula.right_fact_ids]
        if metric.formula.operation in {"sum", "difference"}:
            units = {unit for _value, unit in (*left, *right)}
            if units != {metric.normalized_unit}:
                raise ValueError("MetricFact 加减公式输入单位不一致")
        left_value = sum((value for value, _unit in left), Decimal("0"))
        right_value = sum((value for value, _unit in right), Decimal("0"))
        if metric.formula.operation == "sum":
            expected = left_value
        elif metric.formula.operation == "difference":
            expected = left_value - right_value
        else:
            if metric.normalized_unit != "%" or right_value == 0:
                raise ValueError("MetricFact 比率公式单位或分母无效")
            expected = left_value / right_value * Decimal("100")
        if metric.normalized_value != expected:
            raise ValueError("MetricFact 数值无法由输入事实复算")
        expected_citations = tuple(
            sorted(
                {citation for fact_id in metric.input_fact_ids for citation in citations[fact_id]}
            )
        )
        if metric.citation_ids != expected_citations:
            raise ValueError("MetricFact citation 与输入事实血缘不一致")
        values[metric.fact_id] = (metric.normalized_value, metric.normalized_unit)
        citations[metric.fact_id] = metric.citation_ids
        period_roles[metric.fact_id] = metric.period_role


def build_metric_facts(
    fact_set: HospitalOperationFactSet,
) -> tuple[HospitalOperationMetricFact, ...]:
    """兼容公开入口；实际实现留在独立 metrics 模块以避免职责混杂。"""
    from .metrics import build_metric_facts as build

    return build(fact_set)
