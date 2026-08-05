from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .factset import OperationModel

ReportType = Literal["comprehensive", "topic"]
_SERIALIZED_MEMBER_PATTERN = re.compile(
    r'(?:"?)[A-Za-z_][A-Za-z0-9_.-]*"?\s*:\s*(?:true|false|null|"|\{|\[|-?\d)',
    re.IGNORECASE,
)


def _looks_like_serialized_structure(value: str) -> bool:
    normalized = value.strip().replace('\\"', '"')
    try:
        parsed = json.loads(normalized)
    except (TypeError, ValueError):
        parsed = None
    return isinstance(parsed, (dict, list)) or bool(_SERIALIZED_MEMBER_PATTERN.search(normalized))


class ReportOutlineSection(OperationModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=300)
    focus: tuple[str, ...] = Field(default=(), max_length=20)
    finding_ids: tuple[str, ...] = Field(default=(), alias="findingIds", max_length=2_000)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not any(character.isalnum() for character in normalized)
            or normalized[:1] in {":", "："}
            or _looks_like_serialized_structure(normalized)
        ):
            raise ValueError("章节标题必须是可展示的自然语言")
        return normalized

    @field_validator("focus")
    @classmethod
    def validate_focus(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(
            not item or _looks_like_serialized_structure(item) for item in normalized
        ):
            raise ValueError("章节重点必须是不重复的中文自然语言")
        return normalized

    @field_validator("finding_ids")
    @classmethod
    def validate_findings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(
            not re.fullmatch(r"^finding_[0-9]{3,6}$", item) for item in normalized
        ):
            raise ValueError("章节只能引用服务端生成的 findingId")
        return normalized


class OutlineSectionProposal(OperationModel):
    """提纲模型只提交中文展示字段和发现引用，不提交 section code。"""

    title: str = Field(min_length=1, max_length=300)
    focus: tuple[str, ...] = Field(default=(), max_length=20)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1, max_length=2_000)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not any("\u4e00" <= character <= "\u9fff" for character in normalized)
            or _looks_like_serialized_structure(normalized)
            or re.search(r"(?:section|finding)[-_][A-Za-z0-9_]+", normalized, re.I)
        ):
            raise ValueError("动态章节标题必须是中文自然语言且不得包含机器标识")
        return normalized

    @field_validator("focus")
    @classmethod
    def validate_focus(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(
            not item
            or not any("\u4e00" <= character <= "\u9fff" for character in item)
            or _looks_like_serialized_structure(item)
            for item in normalized
        ):
            raise ValueError("动态章节重点必须是不重复的中文自然语言")
        return normalized

    @field_validator("finding_ids")
    @classmethod
    def validate_finding_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"finding_[0-9]{3,6}", item) for item in value
        ):
            raise ValueError("动态章节只能引用不重复的服务端 findingId")
        return value


class ReportOutlineProposal(OperationModel):
    report_type: ReportType = Field(alias="reportType")
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[OutlineSectionProposal, ...] = Field(min_length=1, max_length=30)
    assumptions: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def validate_sections(self) -> ReportOutlineProposal:
        titles = [item.title for item in self.sections]
        finding_ids = [finding_id for item in self.sections for finding_id in item.finding_ids]
        if len(titles) != len(set(titles)):
            raise ValueError("动态提纲章节标题不能重复")
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("同一 findingId 只能归属一个动态章节")
        return self


COMPREHENSIVE_SECTIONS = (
    ReportOutlineSection(code="operation_overview", title="运营总览"),
    ReportOutlineSection(code="income", title="收入分析"),
    ReportOutlineSection(code="workload", title="工作量分析"),
    ReportOutlineSection(code="budget", title="预算分析"),
    ReportOutlineSection(code="full_cost", title="全成本分析"),
    ReportOutlineSection(code="cost_control", title="费控分析"),
    ReportOutlineSection(code="funds", title="资金分析"),
    ReportOutlineSection(code="cross_domain", title="跨域运营分析"),
    ReportOutlineSection(code="risk_and_data_quality", title="风险与数据质量"),
    ReportOutlineSection(code="management_actions", title="管理行动"),
)
_SECTION_ORDER = {item.code: index for index, item in enumerate(COMPREHENSIVE_SECTIONS)}
_DOMAIN_OR_CROSS = frozenset(
    {"income", "workload", "budget", "full_cost", "cost_control", "funds", "cross_domain"}
)
_TOPIC_REQUIRED = frozenset({"operation_overview", "risk_and_data_quality", "management_actions"})


class ReportOutline(OperationModel):
    report_type: ReportType = Field(alias="reportType")
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[ReportOutlineSection, ...] = Field(min_length=1, max_length=30)
    assumptions: tuple[str, ...] = Field(default=(), max_length=30)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not any(character.isalnum() for character in normalized):
            raise ValueError("报告标题必须包含有效文字或数字")
        return normalized

    @field_validator("assumptions")
    @classmethod
    def validate_assumptions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(not item for item in normalized):
            raise ValueError("报告假设不能为空或重复")
        forbidden = re.compile(r"拟合|估算|推算|插值|外推|年化|平滑|补齐")
        if any(forbidden.search(item) and "不" not in item for item in normalized):
            raise ValueError("报告假设不得拟合、估算、推算、插值、外推、年化、平滑或补齐数据")
        return normalized

    @field_validator("sections")
    @classmethod
    def validate_unique_sections(
        cls, value: tuple[ReportOutlineSection, ...]
    ) -> tuple[ReportOutlineSection, ...]:
        codes = [item.code for item in value]
        if len(codes) != len(set(codes)):
            raise ValueError("提纲包含重复章节 code")
        legacy = all(item in _SECTION_ORDER for item in codes)
        dynamic = all(re.fullmatch(r"section_[0-9]{3,6}", item) for item in codes)
        if not legacy and not dynamic:
            raise ValueError("提纲章节 code 必须由服务端生成 section_NNN")
        if legacy and codes != sorted(codes, key=_SECTION_ORDER.__getitem__):
            raise ValueError("提纲章节必须按综合报告十章主序排列")
        if dynamic:
            expected = [f"section_{index:03d}" for index in range(1, len(codes) + 1)]
            if codes != expected:
                raise ValueError("动态提纲 section code 必须从 section_001 连续生成")
        return value

    @model_validator(mode="after")
    def validate_report_type(self) -> ReportOutline:
        codes = tuple(item.code for item in self.sections)
        legacy = all(item in _SECTION_ORDER for item in codes)
        if (
            legacy
            and self.report_type == "comprehensive"
            and codes != tuple(item.code for item in COMPREHENSIVE_SECTIONS)
        ):
            raise ValueError("综合报告必须精确包含固定十章")
        if legacy and self.report_type == "topic":
            actual = set(codes)
            if not _TOPIC_REQUIRED.issubset(actual) or not actual.intersection(_DOMAIN_OR_CROSS):
                raise ValueError("专题报告必须包含总览、业务分析、风险与数据质量和管理行动")
        if not legacy and not any(section.finding_ids for section in self.sections):
            raise ValueError("动态提纲至少需要引用一个真实发现")
        return self


def make_outline(
    report_type: ReportType,
    *,
    title: str,
    selected_codes: tuple[str, ...] = (),
    title_overrides: dict[str, str] | None = None,
    focus: dict[str, tuple[str, ...]] | None = None,
    findings: Iterable[Any] | None = None,
    proposal: ReportOutlineProposal | Mapping[str, Any] | None = None,
) -> ReportOutline:
    """构造提纲。

    传入 findings/proposal 时走动态章节路径；未传入时保留 v1 固定提纲兼容入口，
    便于迁移既有非医院产物。
    """
    if findings is not None or proposal is not None:
        if proposal is None:
            proposals = _default_outline_proposals(tuple(findings or ()), report_type=report_type)
            proposal_obj = ReportOutlineProposal(
                reportType=report_type,
                title=title,
                sections=proposals,
                assumptions=(),
            )
        else:
            proposal_obj = (
                proposal
                if isinstance(proposal, ReportOutlineProposal)
                else ReportOutlineProposal.model_validate(proposal)
            )
            if proposal_obj.report_type != report_type or proposal_obj.title != title:
                proposal_obj = proposal_obj.model_copy(
                    update={"report_type": report_type, "title": title}
                )
        return freeze_outline(proposal_obj, findings=tuple(findings or ()))
    overrides = title_overrides or {}
    focus_values = focus or {}
    if report_type == "comprehensive":
        selected = {item.code for item in COMPREHENSIVE_SECTIONS}
    else:
        selected = set(selected_codes) | _TOPIC_REQUIRED
    sections = tuple(
        item.model_copy(
            update={
                "title": overrides.get(item.code, item.title),
                "focus": focus_values.get(item.code, ()),
            }
        )
        for item in COMPREHENSIVE_SECTIONS
        if item.code in selected
    )
    return ReportOutline(reportType=report_type, title=title, sections=sections)


def freeze_outline(
    proposal: ReportOutlineProposal | Mapping[str, Any],
    *,
    findings: Iterable[Any],
) -> ReportOutline:
    """在批准边界生成稳定 section_001... code，并冻结发现引用。"""
    proposal_obj = (
        proposal
        if isinstance(proposal, ReportOutlineProposal)
        else ReportOutlineProposal.model_validate(proposal)
    )
    finding_ids = {
        item.finding_id if hasattr(item, "finding_id") else str(item.get("findingId"))
        for item in findings
        if isinstance(item, Mapping) or hasattr(item, "finding_id")
    }
    if not finding_ids:
        raise ValueError("没有可供提纲引用的真实发现")
    sections: list[ReportOutlineSection] = []
    for index, section in enumerate(proposal_obj.sections, start=1):
        unknown = set(section.finding_ids) - finding_ids
        if unknown:
            raise ValueError(f"提纲引用未知 findingId: {', '.join(sorted(unknown))}")
        sections.append(
            ReportOutlineSection(
                code=f"section_{index:03d}",
                title=section.title,
                focus=section.focus,
                findingIds=section.finding_ids,
            )
        )
    return ReportOutline(
        reportType=proposal_obj.report_type,
        title=proposal_obj.title,
        sections=tuple(sections),
        assumptions=proposal_obj.assumptions,
    )


def _default_outline_proposals(
    findings: tuple[Any, ...],
    *,
    report_type: ReportType,
) -> tuple[OutlineSectionProposal, ...]:
    grouped: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for finding in findings:
        if isinstance(finding, Mapping):
            finding_id = str(finding.get("findingId") or "")
            domain = str(finding.get("domain") or "data_quality")
            title = str(finding.get("title") or "运营发现")
        else:
            finding_id = str(getattr(finding, "finding_id", ""))
            domain = str(getattr(finding, "domain", "data_quality"))
            title = str(getattr(finding, "title", "运营发现"))
        if not finding_id:
            continue
        grouped.setdefault(domain, []).append(finding_id)
        titles.setdefault(domain, title)
    proposals = tuple(
        OutlineSectionProposal(
            title=titles[domain],
            focus=(f"围绕{titles[domain]}核对事实和经营影响",),
            findingIds=tuple(grouped[domain]),
        )
        for domain in grouped
    )
    if not proposals:
        raise ValueError("没有可供提纲引用的真实发现")
    return proposals


__all__ = [
    "COMPREHENSIVE_SECTIONS",
    "OutlineSectionProposal",
    "ReportOutline",
    "ReportOutlineProposal",
    "ReportOutlineSection",
    "freeze_outline",
    "make_outline",
]
