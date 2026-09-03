from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .models import WarningDisposition


class QualityWarningContractError(ValueError):
    """告警规则、主体或阶段协议不满足审计契约。"""


@dataclass(frozen=True, slots=True)
class WarningRule:
    code: str
    disposition: WarningDisposition
    subject_types: frozenset[str]


_QUALITY_WARNING_CODES: Final[frozenset[str]] = frozenset(
    {
        "source_coverage_difference",
        "source_period_difference",
        "source_data_quality",
        "analysis_period_incomparable",
        "analysis_data_incomplete",
        "analysis_data_quality",
        "analysis_warning",
        "report_metric_definition_incomplete",
        "chart_low_resolution",
        "chart_low_effective_dpi",
        "chart_extreme_aspect_ratio",
        "chart_visual_review_not_run",
        "report_chart_low_resolution",
        "report_chart_low_effective_dpi",
        "report_chart_extreme_aspect_ratio",
        "report_chart_metric_unfrozen",
        "report_section_claim_invalid",
        "report_section_claim_duplicate",
        "report_section_claim_metric_unknown",
        "report_section_claim_question_unknown",
        "report_section_claim_citation_unknown",
        "report_section_claim_chart_unknown",
        "report_section_claim_citation_missing",
        "report_section_block_citation_unknown",
        "report_section_block_chart_unknown",
        "report_section_chart_citation_unknown",
        "report_section_claim_chart_semantics_conflict",
        "report_section_claim_brief_conflict",
        "report_section_claim_chart_conflict",
        "report_section_claim_period_missing",
        "report_section_block_claim_unknown",
        "report_section_block_citation_unknown",
        "report_section_block_chart_unknown",
        "report_section_citation_missing",
        "report_reference_only_marker_missing",
        "unused_chart_excluded",
        "chart_path_normalized",
        "markdown_strong_marker_normalized",
        "duplicate_section_heading_removed",
    }
)

_REVIEW_REQUIRED_CODES: Final[frozenset[str]] = frozenset(
    {
        "report_period_basis_conflict",
        "report_aggregation_duplicate_unresolved",
        "report_entity_grain_unproven",
        "report_cross_source_inference_unsupported",
    }
)

_INFORMATIONAL_CODES: Final[frozenset[str]] = frozenset(
    {
        "chart_path_normalized",
        "markdown_strong_marker_normalized",
        "duplicate_section_heading_removed",
    }
)


def _subject_types(code: str) -> frozenset[str]:
    if code.startswith("source_"):
        return frozenset({"dataset", "query"})
    if code.startswith("analysis_"):
        return frozenset({"report", "metric"})
    if code == "report_metric_definition_incomplete":
        return frozenset({"metric"})
    if code == "unused_chart_excluded":
        return frozenset({"report"})
    if code.startswith("report_section_block_"):
        return frozenset({"section_block"})
    if "claim" in code or code.startswith("report_period_"):
        return frozenset({"section_claim", "section", "report"})
    if "chart" in code:
        return frozenset({"analysis_chart", "section"})
    if code.startswith("chart_"):
        return frozenset({"analysis_chart", "section"})
    if code in {"report_section_citation_missing", "report_reference_only_marker_missing"}:
        return frozenset({"section"})
    if code in {
        "chart_path_normalized",
        "markdown_strong_marker_normalized",
        "duplicate_section_heading_removed",
    }:
        return frozenset({"report", "section"})
    return frozenset({"section", "report"})


_RULES: Final[dict[str, WarningRule]] = {
    code: WarningRule(
        code=code,
        disposition=(
            "review_required"
            if code in _REVIEW_REQUIRED_CODES
            else "informational"
            if code in _INFORMATIONAL_CODES
            else "quality_warning"
        ),
        subject_types=_subject_types(code),
    )
    for code in _QUALITY_WARNING_CODES | _REVIEW_REQUIRED_CODES
}


def get_warning_rule(code: str) -> WarningRule:
    try:
        return _RULES[code]
    except KeyError as error:
        raise QualityWarningContractError(f"规则未登记：{code}") from error


__all__ = ["QualityWarningContractError", "WarningRule", "get_warning_rule"]
