"""Current, approved question-to-proof matrix, never a prose summarizer.

R003/R020/R057 require a common-period overview. This view preserves every
frozen condition and only displays server proof fragments for current met rows.
It cannot approve mappings, infer metric purposes, or invent missing results.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..trace.contracts_v1 import canonical_sha256

if TYPE_CHECKING:
    from ..trace.quality_bundle import QualityBundle

OVERVIEW_VERSION: Literal["1"] = "1"
MAX_OVERVIEW_ROWS = 500
MAX_OVERVIEW_BYTES = 256 * 1024


class OverviewEvidence(StrictModel):
    assertion_id: str = Field(alias="assertionId")
    subject_ids: tuple[str, ...] = Field(alias="subjectIds", min_length=1)
    text: str
    source_hashes: tuple[str, ...] = Field(alias="sourceHashes", min_length=1)


class OverviewRow(StrictModel):
    question_id: str = Field(alias="questionId")
    question_kind: Literal["request", "analysis"] = Field(alias="questionKind")
    question: str
    condition: str | None
    status: Literal["met", "not_met", "unknown"]
    evidence: tuple[OverviewEvidence, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def verified_rows_only(self) -> OverviewRow:
        if (self.status == "met") != bool(self.evidence):
            raise ValueError("Only met overview conditions may display verified facts")
        return self


class ManagementOverview(StrictModel):
    version: Literal["1"] = OVERVIEW_VERSION
    input_sha256: str = Field(alias="inputSha256", pattern=SHA256_PATTERN)
    markdown_sha256: str | None = Field(default=None, alias="markdownSha256", pattern=SHA256_PATTERN)
    status: Literal["evaluated", "unavailable"]
    required_question_count: int | None = Field(alias="requiredQuestionCount")
    rows: tuple[OverviewRow, ...] = ()
    reasons: tuple[str, ...] = ()
    business_acceptance_evaluated: Literal[False] = Field(default=False, alias="businessAcceptanceEvaluated")


def build_management_overview(quality: QualityBundle) -> ManagementOverview:
    """Caller supplies current identity-checked quality, not model-issued proofs."""
    questions, review, plan = quality.question_specs, quality.answer_review, quality.answer_review_plan
    if questions is None:
        return ManagementOverview(inputSha256=quality.input_sha256, markdownSha256=quality.markdown_sha256, status="unavailable",
                                  requiredQuestionCount=None, reasons=("question_specification_unavailable",))
    required = len(questions.required_question_ids)
    if sum(max(1, len(question.completion_conditions)) for question in questions.questions) > MAX_OVERVIEW_ROWS:
        return ManagementOverview(inputSha256=quality.input_sha256, markdownSha256=quality.markdown_sha256, status="unavailable",
                                  requiredQuestionCount=required, reasons=("overview_budget_exceeded",))
    invalid = []
    if quality.semantic_rule_versions.get("managementOverview") != OVERVIEW_VERSION:
        invalid.append("overview_rule_unavailable")
    if review is None or review.input_sha256 != quality.input_sha256:
        invalid.append("current_review_unavailable")
    else:
        try:
            review.validate_questions(questions)
            if plan is not None:
                plan.validate_questions(questions)
                if review.plan_sha256 != canonical_sha256(plan.model_dump(mode="json", by_alias=True)):
                    invalid.append("review_plan_identity_mismatch")
            elif review.plan_sha256 is not None:
                invalid.append("review_plan_unavailable")
        except ValueError:
            invalid.append("review_question_identity_mismatch")
    assertions = {item.assertion_id: item for item in quality.assertions}
    if len(assertions) != len(quality.assertions):
        invalid.append("assertion_identity_ambiguous")
    checks = {(item.question_id, item.condition): item for item in review.conditions} if review else {}
    criteria = {(item.question_id, item.condition): item for item in plan.criteria} if plan else {}
    blocked = {issue.subject_id for issue in quality.issues if issue.subject_id is not None}
    rows = []
    row_bytes = 0
    for question in questions.questions:
        for condition in question.completion_conditions or (None,):
            check = checks.get((question.question_id, condition)) if condition is not None else None
            criterion = criteria.get((question.question_id, condition)) if condition is not None else None
            reasons = list(invalid)
            evidence: list[OverviewEvidence] = []
            status: Literal["met", "not_met", "unknown"] = "unknown"
            if condition is None:
                reasons.append("completion_conditions_unavailable")
            elif not invalid and check is not None:
                status = check.status
                reasons.extend(check.reasons)
                if status == "met":
                    if criterion is None:
                        reasons.append("condition_mapping_unavailable")
                    else:
                        selected: dict[str, list[str]] = {}
                        for subject_id in criterion.subject_ids:
                            aid = quality.subject_assertions.get(subject_id)
                            assertion = assertions.get(aid or "")
                            if (
                                subject_id in blocked or assertion is None
                                or assertion.status != "supported" or assertion.request != criterion.request
                                or assertion.value is None or not assertion.source_hashes
                                or not assertion.unit or not assertion.unit.strip() or not assertion.periods
                                or not assertion.scope or any(
                                    not key.strip() or not value.strip() for key, value in assertion.scope.items()
                                )
                            ):
                                reasons.append("current_evidence_unavailable")
                            else:
                                selected.setdefault(assertion.assertion_id, []).append(subject_id)
                        if set(selected) != set(check.assertion_ids):
                            reasons.append("review_evidence_identity_mismatch")
                        if not reasons:
                            evidence = [OverviewEvidence(
                                assertionId=aid, subjectIds=tuple(subject_ids),
                                text=assertions[aid].factual_fragment(),
                                sourceHashes=assertions[aid].source_hashes,
                            ) for aid, subject_ids in selected.items()]
                    if reasons or not evidence:
                        status = "unknown"
            else:
                reasons.append("current_condition_review_unavailable")
            row = OverviewRow(
                questionId=question.question_id, questionKind=question.kind,
                question=question.text, condition=condition, status=status,
                evidence=tuple(evidence), reasons=tuple(dict.fromkeys(reasons)),
            )
            row_bytes += len(row.model_dump_json(by_alias=True).encode("utf-8"))
            if row_bytes > MAX_OVERVIEW_BYTES:
                return ManagementOverview(inputSha256=quality.input_sha256, markdownSha256=quality.markdown_sha256, status="unavailable",
                                          requiredQuestionCount=required, reasons=("overview_budget_exceeded",))
            rows.append(row)
    result = ManagementOverview(inputSha256=quality.input_sha256, markdownSha256=quality.markdown_sha256, status="unavailable" if invalid else "evaluated",
                                requiredQuestionCount=required, rows=tuple(rows), reasons=tuple(invalid))
    if len(result.model_dump_json(by_alias=True).encode("utf-8")) > MAX_OVERVIEW_BYTES:
        return ManagementOverview(inputSha256=quality.input_sha256, markdownSha256=quality.markdown_sha256, status="unavailable",
                                  requiredQuestionCount=required, reasons=("overview_budget_exceeded",))
    return result


def render_management_overview(overview: ManagementOverview, *, formal: bool = False,
                               source_citations: dict[str, str] | None = None) -> str:
    """Render the registered matrix for review or an explicitly bound report view."""
    def cell(text: str) -> str:
        return re.sub(r"([\\`*_{}\[\]()<>|#])", r"\\\1", " ".join(text.splitlines()))

    lines = ([] if formal else ["# 经营问题核验总览", ""]) + [
        "以下事实分别保留核验时的期间和范围；缺少同口径证据的事项暂不评价，不据此推断经营原因。", "",
    ]
    if not overview.rows:
        if "overview_budget_exceeded" in overview.reasons:
            message = "核验事项较多，本次未生成总览；完整核验记录仍保留，未截取部分事项冒充完整结论。"
        elif "question_specification_unavailable" in overview.reasons:
            message = ("尚未形成可核验的经营总览，本页暂不列示汇总数值。请结合正文的口径说明与待确认事项阅读。"
                       if formal else "尚未登记可核验的管理问题及完成条件，暂不列示经营数值。")
        else:
            message = "经营总览核验暂不可用，暂不列示经营数值。"
        lines += [message, ""]
    else:
        lines += ["| 核验事项 | 当前已核验事实 | 状态与缺项 |", "| --- | --- | --- |"]
        for row in overview.rows:
            label = row.condition or "完成条件待确认"
            facts = " ".join(item.text for item in row.evidence) or "暂不列示数值"
            state = {"met": "该项已核验", "not_met": "该项尚未满足", "unknown": "该项待核实"}[row.status]
            if row.status != "met":
                state += "；需确认对应指标用途、同范围期间和事实依据"
            citations = tuple(dict.fromkeys(
                (source_citations or {})[subject]
                for evidence in row.evidence for subject in evidence.subject_ids
                if subject in (source_citations or {})
            ))
            markers = "".join(f"[[citation:{citation}]]" for citation in citations)
            lines.append(f"| {cell(row.question + '：' + label)} | {cell(facts)}{markers} | {cell(state)} |")
    return "\n".join([*lines, "", "本表不代表整份报告业务验收通过，不授权因果解释、责任目标或预算口径推断。", ""])


def unavailable_management_overview_projection(markdown_sha256: str) -> dict:
    """总览证据不可用时的固定投影：渲染器只显示缺项说明，不含任何数值。"""
    return {
        "version": "management-overview-render/1", "sourceSha256": markdown_sha256,
        "qualityInputSha256": "0" * 64, "status": "unavailable", "markdown": "",
    }


def management_overview_projection(overview: ManagementOverview | None, markdown_sha256: str,
                                   presentations=None) -> dict:
    """Server-only presentation envelope; not a signature or a source proof."""
    overview = overview or ManagementOverview(
        inputSha256="0" * 64, status="unavailable", requiredQuestionCount=None,
        reasons=("question_specification_unavailable",),
    )
    if overview.status == "evaluated" and overview.markdown_sha256 != markdown_sha256:
        raise ValueError("overview does not belong to the rendered Markdown")
    citations = {}
    subjects = {subject for row in overview.rows for evidence in row.evidence for subject in evidence.subject_ids}
    for item in presentations if isinstance(presentations, list) else ():
        if not isinstance(item, dict):
            continue
        citation = item.get("citationId")
        subject = item.get("subjectId") or citation
        if isinstance(subject, str) and subject in subjects and isinstance(citation, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", citation):
            citations[subject] = citation
    return {
        "version": "management-overview-render/1", "sourceSha256": markdown_sha256,
        "qualityInputSha256": overview.input_sha256, "status": overview.status,
        "markdown": render_management_overview(overview, formal=True, source_citations=citations),
    }
