"""Lossless warning worklist; grouping never adjudicates business correctness."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from ..contract import StrictModel
from .contracts_v1 import RevisionTraceIndexV1, canonical_sha256

if TYPE_CHECKING:
    from .quality_bundle import QualityBundle

# Word review requirements, not evidence that an individual warning is correct.
# Scope unknown remains unresolved: missing metadata and checker omissions both
# occur, and neither can be decided from a diagnostic code alone.
_GUIDANCE = {
    "scope_unknown": ("unresolved", ("R013", "R024", "R043"), "确认冻结范围及组织映射，不默认全院", "analysis"),
    "scope_value_unknown": ("unresolved", ("R013", "R024", "R043"), "核对空组织值的采集及映射状态，不补造归属", "analysis"),
    "unit_unknown": ("unresolved", ("R004", "R005", "R011"), "补齐冻结指标的明确单位，不把空白当作已知单位", "analysis"),
    "period_unknown": ("definition_review", ("R002", "R035", "R064"), "核对原始期间的有效日历与登记粒度，不从无效桶或外层范围补造期间", "analysis"),
    "ranking_context_unknown": ("proof_not_evaluated", ("R015", "R050"), "补齐完整同维度总体及排名上下文", "analysis"),
    "operation_semantics_not_evaluated": ("proof_not_evaluated", ("R009", "R033", "R052", "R061"), "登记对应公式的期间、用途和分子分母前提，再验证运算", "analysis"),
    "statement_not_supported": ("unresolved", ("R004", "R005", "R011", "R032"), "对照当前句子与所选事实复核范围、期间、单位及结论", "draft"),
    "interactive_spec_unregistered": ("artifact_gap", ("R004", "R019", "R026"), "补齐登记图形规格，并与冻结数组及事实共同核验", "render"),
    "chart_arrays_unverified": ("proof_not_evaluated", ("R004", "R019", "R026"), "先处理同一图表的数组或规格检查，再复核语义对齐", "render"),
    "cell_period_label_mismatch": ("definition_review", ("R002", "R035", "R064"), "核实源字段及聚合粒度，不从月初日期猜测月度", "analysis"),
    "cell_period_identity_unavailable": ("definition_review", ("R002", "R035", "R064"), "核对原始期间是否为有效日历及已登记粒度，不将无效日期截成月份", "analysis"),
    "cell_fact_binding_unavailable": ("traceability_gap", ("R014", "R016", "R068"), "核查单元格的原始事实绑定，缺失保持缺失而非补零", "table"),
    "table_registration_unavailable": ("traceability_gap", ("R004", "R032", "R074"), "由结构化表格与事实选择器共同生成正文及绑定", "table"),
}


class WarningGroup(StrictModel):
    group_id: str = Field(alias="groupId")
    target_kind: str = Field(alias="targetKind")
    subject_ids: tuple[str, ...] = Field(alias="subjectIds")
    fact_ids: tuple[str, ...] = Field(alias="factIds")
    issue_indices: tuple[int, ...] = Field(alias="issueIndices")
    issue_codes: tuple[str, ...] = Field(alias="issueCodes")
    reasons: tuple[str, ...]
    assessments: tuple[str, ...]
    review_ids: tuple[str, ...] = Field(alias="reviewIds")
    required_actions: tuple[str, ...] = Field(alias="requiredActions")
    repair_stages: tuple[str, ...] = Field(alias="repairStages")
    adjudication: Literal["not_adjudicated"] = "not_adjudicated"


class WarningLedger(StrictModel):
    version: Literal["warning-ledger/1"] = "warning-ledger/1"
    quality_input_sha256: str = Field(alias="qualityInputSha256")
    original_issue_count: int = Field(alias="originalIssueCount")
    group_count: int = Field(alias="groupCount")
    groups: tuple[WarningGroup, ...]
    business_acceptance_evaluated: Literal[False] = Field(default=False, alias="businessAcceptanceEvaluated")


def build_warning_ledger(quality: QualityBundle, index: RevisionTraceIndexV1) -> WarningLedger:
    """Use a caller-verified index; never merge different subjects without identity.

    Input matching here is consistency only, not file or authorization validation.
    Every issue belongs to exactly one group and remains in quality.issues.
    """
    if quality.report_id != index.report_id or quality.revision != index.revision:
        raise ValueError("Quality and index identities differ")
    subjects = {item.subject_id: item for item in index.subject_bindings}
    buckets: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    for position, issue in enumerate(quality.issues):
        subject = subjects.get(issue.subject_id or "")
        facts = tuple(sorted({ref.fact_key for ref in subject.fact_refs if ref.fact_key})) if subject else ()
        identity: tuple[str, ...]
        if issue.code in {"chart_support_unknown", "chart_semantic_alignment_unknown"}:
            # Only the same actual chart combines its upstream/downstream checks.
            kind, identity = "chart", (issue.subject_id or f"issue:{position}",)
        elif issue.code == "assertion_support_unknown" and facts:
            kind, identity = "fact", facts
        else:
            kind, identity = issue.code, (issue.subject_id or f"issue:{position}",)
        buckets.setdefault((kind, identity), []).append(position)
    groups = []
    for (kind, identity), positions in buckets.items():
        issues = [quality.issues[position] for position in positions]
        reasons = tuple(dict.fromkeys(reason for issue in issues for reason in issue.reasons))
        guidance = [_GUIDANCE[reason] for reason in reasons if reason in _GUIDANCE]
        unknown = any(reason not in _GUIDANCE and not re.fullmatch(r"markdown_line:\d+", reason)
                      for reason in reasons) or not guidance
        groups.append(WarningGroup(
            groupId="wg-" + canonical_sha256([quality.report_id, quality.revision, kind, identity])[:20],
            targetKind=kind,
            subjectIds=tuple(dict.fromkeys(issue.subject_id for issue in issues if issue.subject_id)),
            factIds=identity if kind == "fact" else (),
            issueIndices=tuple(positions),
            issueCodes=tuple(dict.fromkeys(issue.code for issue in issues)),
            reasons=reasons,
            assessments=tuple(dict.fromkeys([item[0] for item in guidance] + (["unclassified"] if unknown else []))),
            reviewIds=tuple(sorted({ref for item in guidance for ref in item[1]} | {
                reason for reason in reasons if re.fullmatch(r"R\d{3}", reason)
            })),
            requiredActions=tuple(dict.fromkeys([item[2] for item in guidance] + (
                ["保留原始诊断并逐项裁定，不能自动判为金额错误或通过"] if unknown else []
            ))),
            repairStages=tuple(sorted({item[3] for item in guidance} | ({"review"} if unknown else set()))),
        ))
    return WarningLedger(
        qualityInputSha256=quality.input_sha256,
        originalIssueCount=len(quality.issues), groupCount=len(groups), groups=tuple(groups),
    )
