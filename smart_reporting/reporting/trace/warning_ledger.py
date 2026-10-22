"""Lossless warning worklist; grouping never adjudicates business correctness."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from ..contract import StrictModel
from .assertions import AssertionResult
from .chart_quality import ChartQualityCheck
from .contracts_v1 import (
    ChartTraceV1,
    FactRefV1,
    RevisionTraceIndexV1,
    SubjectBindingV1,
    TableTraceV1,
    canonical_sha256,
)
from .quality_bundle import QualityIssue
from .semantic_alignment import SemanticAlignmentCheck
from .table_quality import TableQualityCheck

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
    "approved_mapping_unavailable": ("unresolved", ("R003", "R020", "R057"), "核查服务端批准映射及冻结记录，不由模型自行批准需求到证据的对应关系", "review"),
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
    fact_refs: tuple[FactRefV1, ...] = Field(default=(), alias="factRefs")
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
    grouping_version: Literal["fact-reference/2"] = Field(default="fact-reference/2", alias="groupingVersion")
    quality_input_sha256: str = Field(alias="qualityInputSha256")
    original_issue_count: int = Field(alias="originalIssueCount")
    group_count: int = Field(alias="groupCount")
    groups: tuple[WarningGroup, ...]
    business_acceptance_evaluated: Literal[False] = Field(default=False, alias="businessAcceptanceEvaluated")


class WarningReviewCase(StrictModel):
    case_id: str = Field(alias="caseId")
    group_id: str = Field(alias="groupId")
    issue_index: int = Field(alias="issueIndex", ge=0)
    issue: QualityIssue
    subject: SubjectBindingV1 | None = None
    assertion: AssertionResult | None = None
    chart: ChartTraceV1 | None = None
    table: TableTraceV1 | None = None
    chart_check: ChartQualityCheck | None = Field(default=None, alias="chartCheck")
    table_check: TableQualityCheck | None = Field(default=None, alias="tableCheck")
    semantic_check: SemanticAlignmentCheck | None = Field(default=None, alias="semanticCheck")
    review_ids: tuple[str, ...] = Field(alias="reviewIds")
    required_actions: tuple[str, ...] = Field(alias="requiredActions")
    adjudication: Literal["not_adjudicated"] = "not_adjudicated"


class WarningReviewPacket(StrictModel):
    version: Literal["warning-review-packet/1"] = "warning-review-packet/1"
    report_id: str = Field(alias="reportId")
    revision: int
    quality_sha256: str = Field(alias="qualitySha256")
    index_sha256: str = Field(alias="indexSha256")
    ledger: WarningLedger
    cases: tuple[WarningReviewCase, ...]
    business_acceptance_evaluated: Literal[False] = Field(default=False, alias="businessAcceptanceEvaluated")


def build_warning_review_packet(quality: QualityBundle, index: RevisionTraceIndexV1) -> WarningReviewPacket:
    """Prepare individual evidence, without inventing reviewer decisions or authorization.

    Content hashes bind even issue reordering and index-only edits. They establish
    consistency, not source authenticity. The caller must verify source authority.
    """
    ledger = build_warning_ledger(quality, index)
    markdown = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    if markdown.sha256 != quality.markdown_sha256:
        raise ValueError("Quality and registered Markdown identities differ")
    quality_hash = canonical_sha256(quality.model_dump(mode="json", by_alias=True))
    index_hash = canonical_sha256(index.model_dump(mode="json", by_alias=True))
    subjects = {subject.subject_id: subject for subject in index.subject_bindings}
    charts = {chart.chart_id: chart for chart in index.chart_traces}
    tables = {table.table_id: table for table in index.tables}
    assertions = {assertion.assertion_id: assertion for assertion in quality.assertions}
    if len(assertions) != len(quality.assertions):
        raise ValueError("Duplicate assertion identities")
    groups = {position: group.group_id for group in ledger.groups for position in group.issue_indices}
    cases = []
    for position, issue in enumerate(quality.issues):
        guidance = [_GUIDANCE[reason] for reason in issue.reasons if reason in _GUIDANCE]
        actions = tuple(dict.fromkeys(item[2] for item in guidance))
        if not guidance or any(reason not in _GUIDANCE and not re.fullmatch(r"markdown_line:\d+", reason)
                               for reason in issue.reasons):
            actions += ("保留原始诊断并逐项裁定，不能自动判为金额错误或通过",)
        cases.append(WarningReviewCase(
            caseId="wc-" + canonical_sha256([quality_hash, index_hash, position]),
            groupId=groups[position], issueIndex=position, issue=issue,
            subject=subjects.get(issue.subject_id or ""),
            assertion=assertions.get(quality.subject_assertions.get(issue.subject_id or "", "")),
            chart=charts.get(issue.subject_id or ""), table=tables.get(issue.subject_id or ""),
            chartCheck=quality.chart_checks.get(issue.subject_id or ""),
            tableCheck=quality.table_checks.get(issue.subject_id or ""),
            semanticCheck=quality.semantic_checks.get(issue.subject_id or ""),
            reviewIds=tuple(sorted({ref for item in guidance for ref in item[1]} | {
                reason for reason in issue.reasons if re.fullmatch(r"R\d{3}", reason)
            })),
            requiredActions=actions,
        ))
    return WarningReviewPacket(reportId=quality.report_id, revision=quality.revision,
                               qualitySha256=quality_hash, indexSha256=index_hash,
                               ledger=ledger, cases=tuple(cases))


def build_warning_ledger(quality: QualityBundle, index: RevisionTraceIndexV1) -> WarningLedger:
    """Use a caller-verified index; never merge different subjects without identity.

    Input matching here is consistency only, not file or authorization validation.
    Every issue belongs to exactly one group and remains in quality.issues.
    """
    if quality.report_id != index.report_id or quality.revision != index.revision:
        raise ValueError("Quality and index identities differ")
    subjects = {item.subject_id: item for item in index.subject_bindings}
    files = {file.resource_id: file for file in index.files}
    references: dict[str, FactRefV1] = {}

    def reference_identity(ref: FactRefV1) -> str:
        # factKey is only a defensive key inside a frozen file, never a global
        # identity. Include unkeyed operands, exact pointers and registered bytes.
        file = files.get(ref.file_resource_id)
        identity = canonical_sha256([
            ref.model_dump(mode="json", by_alias=True),
            [file.sha256, file.size] if file is not None else None,
        ])
        references[identity] = ref
        return identity

    buckets: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    for position, issue in enumerate(quality.issues):
        subject = subjects.get(issue.subject_id or "")
        facts = tuple(sorted({reference_identity(ref) for ref in subject.fact_refs})) if subject else ()
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
            groupId="wg-" + canonical_sha256([
                "fact-reference/2", quality.report_id, quality.revision, kind, identity,
            ])[:20],
            targetKind=kind,
            subjectIds=tuple(dict.fromkeys(issue.subject_id for issue in issues if issue.subject_id)),
            factIds=tuple(sorted({fact_key for key in identity
                                  if (fact_key := references[key].fact_key) is not None})) if kind == "fact" else (),
            factRefs=tuple(references[key] for key in identity) if kind == "fact" else (),
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
