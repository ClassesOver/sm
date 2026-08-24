from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .schema import HospitalOperationSchema

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


class ReportOutlineSection(HospitalOperationSchema):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    section_number: str = Field(alias="sectionNumber", pattern=r"^[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=300)
    focus: tuple[str, ...] = Field(default=(), max_length=20)
    analysis_ids: tuple[str, ...] = Field(default=(), alias="analysisIds", max_length=2_000)

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

    @field_validator("analysis_ids")
    @classmethod
    def validate_analyses(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(
            not re.fullmatch(r"^analysis_[0-9]{3,6}$", item) for item in normalized
        ):
            raise ValueError("章节只能引用服务端生成的 analysisId")
        return normalized


class OutlineSectionProposal(HospitalOperationSchema):
    """提纲模型只提交中文展示字段和发现引用，不提交 section code。"""

    title: str = Field(min_length=1, max_length=300)
    focus: tuple[str, ...] = Field(default=(), max_length=20)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=2_000)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not any("\u4e00" <= character <= "\u9fff" for character in normalized)
            or _looks_like_serialized_structure(normalized)
            or re.search(r"(?:section|analysis)[-_][A-Za-z0-9_]+", normalized, re.I)
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

    @field_validator("analysis_ids")
    @classmethod
    def validate_analysis_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"analysis_[0-9]{3,6}", item) for item in value
        ):
            raise ValueError("动态章节只能引用不重复的服务端 analysisId")
        return value


class ReportOutlineProposal(HospitalOperationSchema):
    report_type: ReportType = Field(alias="reportType")
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[OutlineSectionProposal, ...] = Field(min_length=1, max_length=30)
    assumptions: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def validate_sections(self) -> ReportOutlineProposal:
        titles = [item.title for item in self.sections]
        analysis_ids = [analysis_id for item in self.sections for analysis_id in item.analysis_ids]
        if len(titles) != len(set(titles)):
            raise ValueError("动态提纲章节标题不能重复")
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ValueError("同一 analysisId 只能归属一个动态章节")
        return self


class ReportOutline(HospitalOperationSchema):
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
        if not all(re.fullmatch(r"section_[0-9]{3,6}", item) for item in codes):
            raise ValueError("提纲章节 code 必须由服务端生成 section_NNN")
        expected = [f"section_{index:03d}" for index in range(1, len(codes) + 1)]
        if codes != expected:
            raise ValueError("动态提纲 section code 必须从 section_001 连续生成")
        expected_numbers = [str(index) for index in range(1, len(value) + 1)]
        if [item.section_number for item in value] != expected_numbers:
            raise ValueError("动态提纲 sectionNumber 必须从 1 连续生成")
        return value

    @model_validator(mode="after")
    def validate_report_type(self) -> ReportOutline:
        if not any(section.analysis_ids for section in self.sections):
            raise ValueError("动态提纲至少需要引用一个真实分析")
        return self


def freeze_outline(
    proposal: ReportOutlineProposal | Mapping[str, Any],
    *,
    analyses: Iterable[Any],
) -> ReportOutline:
    """在批准边界生成稳定 section_001... code，并冻结分析引用。"""
    proposal_obj = (
        proposal
        if isinstance(proposal, ReportOutlineProposal)
        else ReportOutlineProposal.model_validate(proposal)
    )
    analysis_ids = {
        item.analysis_id if hasattr(item, "analysis_id") else str(item.get("analysisId"))
        for item in analyses
        if isinstance(item, Mapping) or hasattr(item, "analysis_id")
    }
    if not analysis_ids:
        raise ValueError("没有可供提纲引用的真实分析")
    sections: list[ReportOutlineSection] = []
    referenced_analysis_ids: set[str] = set()
    for index, section in enumerate(proposal_obj.sections, start=1):
        unknown = set(section.analysis_ids) - analysis_ids
        if unknown:
            raise ValueError(f"提纲引用未知 analysisId: {', '.join(sorted(unknown))}")
        referenced_analysis_ids.update(section.analysis_ids)
        sections.append(
            ReportOutlineSection(
                code=f"section_{index:03d}",
                sectionNumber=str(index),
                title=section.title,
                focus=section.focus,
                analysisIds=section.analysis_ids,
            )
        )
    return ReportOutline(
        reportType=proposal_obj.report_type,
        title=proposal_obj.title,
        sections=tuple(sections),
        assumptions=proposal_obj.assumptions,
    )


__all__ = [
    "OutlineSectionProposal",
    "ReportOutline",
    "ReportOutlineProposal",
    "ReportOutlineSection",
    "freeze_outline",
]
