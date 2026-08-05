from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from ..models import ReportingError
from .domains import DOMAIN_CODES, DomainResolution, normalize_domain_code, resolve_domain_mentions
from .factset import OperationModel


class ClarificationRequired(OperationModel):
    code: Literal["domain_ambiguous", "period_required", "report_type_required"]
    question: str = Field(min_length=1, max_length=1_000)
    candidates: tuple[str, ...] = Field(default=(), max_length=6)


class CorrectionFeedback(OperationModel):
    """只描述一个失败字段的可执行纠错，不携带整份模型输出。"""

    path: str = Field(min_length=1, max_length=500)
    rejected_value: object = Field(alias="rejectedValue")
    allowed_values: tuple[object, ...] = Field(default=(), alias="allowedValues", max_length=100)
    required_action: str = Field(alias="requiredAction", min_length=1, max_length=1_000)


class ContextFeedback(OperationModel):
    sequence: int = Field(ge=1)
    stage: Literal["request_supplement", "outline_feedback"]
    content: str = Field(min_length=1, max_length=20_000)


class ReportRequestContext(OperationModel):
    original_goal: str = Field(alias="originalGoal", min_length=1, max_length=20_000)
    report_type: Literal["comprehensive", "topic"] = Field(
        default="comprehensive", alias="reportType"
    )
    domains: tuple[str, ...] | None = Field(default=None, max_length=6)
    primary_domain: str | None = Field(default=None, alias="primaryDomain", max_length=64)
    available_domains: tuple[str, ...] = Field(
        default=DOMAIN_CODES, alias="availableDomains", min_length=1, max_length=6
    )
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    hospital: str = Field(min_length=1, max_length=200)
    source_ids: tuple[str, ...] = Field(alias="sourceIds", min_length=1, max_length=20)
    feedback: tuple[ContextFeedback, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_context(self) -> ReportRequestContext:
        if self.period_start > self.period_end:
            raise ValueError("请求期间无效")
        sequences = [item.sequence for item in self.feedback]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("请求反馈必须按顺序连续保存")
        if any(item not in DOMAIN_CODES for item in self.available_domains):
            raise ValueError("availableDomains 包含未知领域")
        if (
            tuple(item for item in DOMAIN_CODES if item in self.available_domains)
            != self.available_domains
        ):
            raise ValueError("availableDomains 必须按六域稳定顺序且不能重复")
        if self.domains is not None:
            if any(item not in self.available_domains for item in self.domains):
                raise ValueError("domains 必须属于 availableDomains")
            if tuple(item for item in DOMAIN_CODES if item in self.domains) != self.domains:
                raise ValueError("domains 必须按六域稳定顺序且不能重复")
            if self.report_type == "comprehensive" and set(self.domains) != set(
                self.available_domains
            ):
                raise ValueError("指定领域子集必须标记为 topic")
        if (
            self.primary_domain is not None
            and self.domains
            and self.primary_domain not in self.domains
        ):
            raise ValueError("primaryDomain 必须属于 domains")
        return self

    def append_feedback(
        self, content: str, *, stage: Literal["request_supplement", "outline_feedback"]
    ) -> ReportRequestContext:
        item = ContextFeedback(
            sequence=len(self.feedback) + 1, stage=stage, content=content.strip()
        )
        return self.model_copy(update={"feedback": (*self.feedback, item)})

    def assert_same_identity(
        self,
        *,
        report_type: str,
        period_start: date,
        period_end: date,
        hospital: str,
        source_ids: tuple[str, ...],
    ) -> None:
        if (
            report_type != self.report_type
            or period_start != self.period_start
            or period_end != self.period_end
            or hospital != self.hospital
            or source_ids != self.source_ids
        ):
            raise ReportingError(
                "report_context_restart_required",
                "报告类型、期间、医院或数据源已变化，必须取消当前运行并重新发起。",
            )

    def period_windows(self):
        from ..data_source.period import build_period_windows

        return build_period_windows(self.period_start, self.period_end)


def normalize_report_request(
    *,
    original_goal: str,
    period_start: date | None,
    period_end: date | None,
    hospital: str,
    source_ids: tuple[str, ...],
    report_type: Literal["comprehensive", "topic"] | None = None,
    domains: tuple[str, ...] | None = None,
    available_domains: tuple[str, ...] = DOMAIN_CODES,
) -> ReportRequestContext | ClarificationRequired:
    normalized_goal = original_goal.strip()
    available = tuple(code for code in DOMAIN_CODES if code in available_domains)
    if not available:
        raise ReportingError("report_domain_unavailable", "没有可用的医院运营领域。")
    resolution: DomainResolution
    if domains is not None:
        normalized_domains: list[str] = []
        try:
            for value in domains:
                code = normalize_domain_code(value)
                if code not in normalized_domains:
                    normalized_domains.append(code)
        except ValueError as error:
            raise ReportingError(
                "report_domain_invalid", "请求领域不是六域稳定代码或唯一别名。"
            ) from error
        selected = tuple(code for code in DOMAIN_CODES if code in normalized_domains)
        resolution = DomainResolution(
            selected=selected,
            primary=selected[0] if selected else None,
            matched_aliases=(),
        )
    else:
        resolution = resolve_domain_mentions(normalized_goal)
        if resolution.is_ambiguous:
            return ClarificationRequired(
                code="domain_ambiguous",
                question="请明确主分析领域：全成本或费控。",
                candidates=resolution.ambiguous_aliases,
            )
        selected = resolution.selected
    selected = tuple(code for code in DOMAIN_CODES if code in selected and code in available)
    if period_start is None or period_end is None:
        return ClarificationRequired(
            code="period_required",
            question="请明确唯一的分析期间。",
        )
    if period_start > period_end:
        raise ReportingError("report_period_invalid", "请求期间无效。")
    # 未指定领域或覆盖全部实际可用领域视为综合；明确子集自动视为专题。
    derived_type: Literal["comprehensive", "topic"] = (
        "comprehensive" if not selected or set(selected) == set(available) else "topic"
    )
    if report_type is not None and report_type == "topic" and selected:
        derived_type = "topic"
    if report_type == "comprehensive" and selected and set(selected) != set(available):
        # 兼容字段不能放宽领域范围；服务端以规范化领域事实为准。
        derived_type = "topic"
    return ReportRequestContext(
        originalGoal=normalized_goal,
        reportType=derived_type,
        domains=selected or None,
        primaryDomain=resolution.primary,
        availableDomains=available,
        periodStart=period_start,
        periodEnd=period_end,
        hospital=hospital.strip(),
        sourceIds=source_ids,
    )
