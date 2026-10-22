"""Versioned shadow evaluation; never a publication/download gate."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from ..contract import SHA256_PATTERN, StrictModel
from ..hospital_operation.professional_review import (
    PROFESSIONAL_REVIEW_VERSION,
    review_professional_content,
)
from ..workflow.answer_review import AnswerReviewPlan, AnswerReviewResult, evaluate_answer_review
from ..workflow.management_overview import (
    OVERVIEW_VERSION,
    ManagementOverview,
    build_management_overview,
)
from ..workflow.questions import QuestionSet
from .assertions import (
    RULE_VERSION,
    AssertionCompiler,
    AssertionResult,
    assertion_request_for_token,
)
from .chart_quality import ChartQualityCheck, evaluate_chart_quality
from .contracts_v1 import RevisionTraceIndexV1, canonical_sha256
from .semantic_alignment import SemanticAlignmentCheck, evaluate_semantic_alignment
from .semantic_bindings import reference_fact_ids, statement_fingerprints
from .table_quality import TableQualityCheck, evaluate_table_quality, uncovered_table_lines

QUALITY_FILENAME = "quality-bundle-v1.json"
SEMANTIC_RULE_VERSIONS = {"topSets": "1", "businessSemantics": "1", "groupContributions": "1", "calendarComparisons": "1", "registeredRatios": "2", "cumulativeChanges": "3", "professionalReview": PROFESSIONAL_REVIEW_VERSION, "tableCoverage": "1", "tablePeriods": "1", "managementOverview": OVERVIEW_VERSION, "scopeValues": "1", "overviewSourceBinding": "1", "periodIdentity": "1", "unitIdentity": "1", "statementReview": "1", "scopeWording": "1"}


class StatementReview(StrictModel):
    """Existing local numeric check, not a business-acceptance verdict.

    A matching number may still have scope, period, unit or selector warnings.
    Preserve those observations instead of collapsing them into an opaque code.
    """

    numeric_status: Literal["valid", "stale", "unbound"] = Field(alias="numericStatus")
    warnings: tuple[str, ...] = ()


class QualityIssue(StrictModel):
    code: str
    subject_id: str | None = Field(default=None, alias="subjectId")
    severity: Literal["warning", "error"] = "warning"
    checker: Literal["deterministic"] = "deterministic"
    reasons: tuple[str, ...] = ()
    statement_review: StatementReview | None = Field(default=None, alias="statementReview")


class QualityBundle(StrictModel):
    version: Literal["1"] = "1"
    checker_version: Literal["assertions/1"] = Field(default=RULE_VERSION, alias="checkerVersion")
    report_id: str = Field(alias="reportId")
    revision: int
    markdown_sha256: str = Field(alias="markdownSha256", pattern=SHA256_PATTERN)
    input_sha256: str = Field(alias="inputSha256", pattern=SHA256_PATTERN)
    mode: Literal["shadow", "enabled"] = "shadow"
    all_key_facts_evaluated: Literal[False] = Field(default=False, alias="allKeyFactsEvaluated")
    assertions: tuple[AssertionResult, ...] = ()
    issues: tuple[QualityIssue, ...] = ()
    subject_assertions: dict[str, str] = Field(default_factory=dict, alias="subjectAssertions")
    chart_checks: dict[str, ChartQualityCheck] = Field(default_factory=dict, alias="chartChecks")
    semantic_checks: dict[str, SemanticAlignmentCheck] = Field(default_factory=dict, alias="semanticChecks")
    table_checks: dict[str, TableQualityCheck] = Field(default_factory=dict, alias="tableChecks")
    semantic_rule_versions: dict[str, str] = Field(default_factory=dict, alias="semanticRuleVersions")
    question_specs: QuestionSet | None = Field(default=None, alias="questionSpecs")
    answer_review_plan: AnswerReviewPlan | None = Field(default=None, alias="answerReviewPlan")
    answer_review: AnswerReviewResult | None = Field(default=None, alias="answerReview")
    management_overview: ManagementOverview | None = Field(default=None, alias="managementOverview")
    question_coverage: dict = Field(default_factory=dict, alias="questionCoverage")
    question_assertions: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, alias="questionAssertions"
    )


def evaluate_quality_bundle(
    index: RevisionTraceIndexV1,
    markdown: str,
    sources: Mapping[str, bytes],
    *,
    authorization_scope_hash: str,
    mode: Literal["shadow", "enabled"] = "shadow",
    questions: QuestionSet | None = None,
    interactive_charts: Mapping[str, str] | None = None,
    answer_review_plan: AnswerReviewPlan | None = None,
) -> QualityBundle:
    """Identity-check again at this boundary. Missing data only degrades dependents."""
    trusted: list[str] = []
    documents = {}
    unavailable: set[str] = set()
    files = {file.resource_id: file for file in index.files}
    for entry in index.fact_files:
        file = files[entry.file_resource_id]
        raw = sources.get(file.resource_id)
        if raw is None or len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
            unavailable.add(file.resource_id)
            continue
        try:
            from ..models import ReportingError
            from .fact_service import read_fact_document

            document = read_fact_document(raw)
            if document.get("analysisId") != entry.analysis_id:
                unavailable.add(file.resource_id)
                continue
            documents[file.resource_id] = document
            trusted.append(raw.decode("utf-8"))
        except (UnicodeDecodeError, ReportingError):
            unavailable.add(file.resource_id)
    compiler = AssertionCompiler(
        trusted,
        profile_hash=index.profile_hash or "0" * 64,
        authorization_scope_hash=authorization_scope_hash,
    )
    issues: list[QualityIssue] = []
    issues.extend(QualityIssue(code=issue.code, reasons=(issue.message, *issue.review_ids))
                  for issue in review_professional_content(markdown))
    chart_checks = evaluate_chart_quality(index, markdown, sources, interactive_charts or {})
    issues.extend(
        QualityIssue(code="chart_support_unknown", subjectId=chart_id, reasons=(check.reason,))
        for chart_id, check in chart_checks.items()
        if check.status != "verified"
    )
    semantic_checks = evaluate_semantic_alignment(index, sources, chart_checks=chart_checks)
    issues.extend(
        QualityIssue(code="chart_semantic_alignment_unknown", subjectId=chart_id, reasons=check.reasons)
        for chart_id, check in semantic_checks.items() if check.status != "verified"
    )
    original_markdown = None
    markdown_file = files.get(index.markdown_file_resource_id)
    if markdown_file is not None:
        original_raw = sources.get(markdown_file.resource_id, markdown.encode("utf-8"))
        if len(original_raw) == markdown_file.size and hashlib.sha256(original_raw).hexdigest() == markdown_file.sha256:
            try:
                original_markdown = original_raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
    table_checks = evaluate_table_quality(index, markdown, documents, original_markdown=original_markdown)
    issues.extend(
        QualityIssue(code="table_support_unknown", subjectId=table_id, reasons=check.reasons)
        for table_id, check in table_checks.items() if check.status != "verified"
    )
    issues.extend(
        QualityIssue(
            code="table_coverage_unknown",
            subjectId=f"markdown-table:L{line}",
            reasons=("table_registration_unavailable", f"markdown_line:{line}"),
        )
        for line in uncovered_table_lines(markdown, {table.table_id for table in index.tables})
    )
    assertions: dict[str, AssertionResult] = {}
    bindings: dict[str, str] = {}
    question_assertions: dict[str, list[str]] = {}
    from .subject_builder import prepare_claim_status

    check_claim = prepare_claim_status(markdown)
    fingerprints = statement_fingerprints(
        markdown,
        (
            subject.number_reference.claim_id
            for subject in index.subject_bindings
            if subject.number_reference is not None
        ),
    )
    for subject in index.subject_bindings:
        number = subject.number_reference
        if number is None:
            continue
        reasons = []
        statement_review = None
        if any(ref.file_resource_id in unavailable for ref in subject.fact_refs):
            reasons.append("source_unavailable")
        if number.table_derivation is None:
            if set(reference_fact_ids(number.token)) != {ref.fact_key for ref in subject.fact_refs}:
                reasons.append("fact_binding_mismatch")
            from .fact_index import fact_entry_from_pointer

            for ref in subject.fact_refs:
                try:
                    document = documents[ref.file_resource_id]
                    kind, fact_entry = fact_entry_from_pointer(document, ref.json_pointer)
                    if (
                        document.get("analysisId") != ref.analysis_id
                        or kind != ref.fact_kind
                        or fact_entry.get("factId") != ref.fact_key
                    ):
                        reasons.append("fact_binding_mismatch")
                except KeyError:
                    reasons.append("fact_binding_mismatch")
        if fingerprints[number.claim_id] != number.statement_sha256:
            reasons.append("statement_changed")
        request = (
            assertion_request_for_token(number.token, compiler.resolver)
            if number.table_derivation is None
            else None
        )
        if number.table_derivation is not None or request is None:
            # Legacy calculation support is not a complete business proof.
            reasons.append("operation_semantics_not_evaluated")
        elif not reasons:
            assertion = compiler.compile(request)
            assertions[assertion.assertion_id] = assertion
            bindings[subject.subject_id] = assertion.assertion_id
            if questions is not None:
                for ref in subject.fact_refs:
                    question_id = questions.analysis_to_question.get(ref.analysis_id)
                    if question_id is not None:
                        question_assertions.setdefault(question_id, []).append(
                            assertion.assertion_id
                        )
            reasons.extend(assertion.reasons)
            selected = compiler.resolver.resolve(number.token)
            if selected is not None:
                detail = check_claim(
                    number.claim_id,
                    selected["value"],
                    expected_unit=selected["unit"],
                    expected_periods=selected["periods"],
                    expected_scope=selected["scope"],
                    expected_period_roles=selected["period_roles"],
                    expected_reference=selected,
                    section_id=subject.locator.section_id,
                )
                if detail["status"] != "valid" or detail["warnings"]:
                    reasons.append("statement_not_supported")
                    statement_review = StatementReview(numericStatus=detail["status"], warnings=tuple(detail["warnings"]))
        if reasons:
            issues.append(
                QualityIssue(
                    code="assertion_support_unknown",
                    subjectId=subject.subject_id,
                    reasons=tuple(dict.fromkeys(reasons)),
                    statementReview=statement_review,
                )
            )
    markdown_hash = hashlib.sha256(markdown.encode()).hexdigest()
    input_hash = canonical_sha256(
        {
            "markdownSha256": markdown_hash,
            "profileHash": index.profile_hash,
            "sourceIdentities": sorted(
                (file.resource_id, file.sha256)
                for file in index.files
                if not file.path.endswith("/" + QUALITY_FILENAME)
            ),
            "bindings": [
                item.model_dump(mode="json", by_alias=True) for item in index.subject_bindings
            ],
            "unavailable": sorted(unavailable),
            "ruleVersion": RULE_VERSION,
            "semanticRuleVersions": SEMANTIC_RULE_VERSIONS,
            "authorizationScopeHash": authorization_scope_hash,
            "answerReviewPlan": answer_review_plan.model_dump(mode="json", by_alias=True) if answer_review_plan else None,
            "questionSpecs": questions.model_dump(mode="json", by_alias=True)
            if questions
            else None,
            "tables": [item.model_dump(mode="json", by_alias=True) for item in index.tables],
            "chartTraces": [item.model_dump(mode="json", by_alias=True) for item in index.chart_traces],
            "tableChecks": {key: check.model_dump(mode="json", by_alias=True) for key, check in table_checks.items()},
            "interactiveCharts": dict(interactive_charts or {}),
            "semanticChecks": {key: check.model_dump(mode="json", by_alias=True) for key, check in semantic_checks.items()},
            "chartChecks": {
                key: check.model_dump(mode="json", by_alias=True)
                for key, check in chart_checks.items()
            },
        }
    )
    review = None
    coverage = {
        "required": len(questions.required_question_ids) if questions is not None else None,
        "evaluated": 0, "answered": 0, "effectiveAnswerRate": None,
        "evaluationStatus": "review_unavailable" if questions is not None else "specification_unavailable",
    }
    if questions is not None:
        try:
            review = evaluate_answer_review(
                questions, answer_review_plan, tuple(assertions.values()), bindings,
                {issue.subject_id for issue in issues if issue.subject_id is not None},
                input_sha256=input_hash,
            )
            coverage = review.coverage(questions)
            if answer_review_plan is not None:
                issues.extend(
                    QualityIssue(code="answer_condition_unverified", subjectId=check.question_id,
                                 reasons=(check.condition, *check.reasons))
                    for check in review.conditions if check.status != "met"
                )
        except Exception as error:
            from loguru import logger

            review = None
            logger.warning("answer_review_unavailable reason={}", type(error).__name__)
            issues.append(QualityIssue(code="answer_review_unavailable", reasons=("review_plan_or_checker_invalid",)))
    bundle = QualityBundle(
        reportId=index.report_id,
        revision=index.revision,
        markdownSha256=markdown_hash,
        inputSha256=input_hash,
        mode=mode,
        semanticRuleVersions=SEMANTIC_RULE_VERSIONS,
        assertions=tuple(assertions.values()),
        subjectAssertions=bindings,
        chartChecks=chart_checks,
        semanticChecks=semantic_checks,
        tableChecks=table_checks,
        issues=tuple(issues),
        questionSpecs=questions,
        answerReviewPlan=answer_review_plan,
        answerReview=review,
        questionCoverage=coverage,
        questionAssertions={
            key: tuple(dict.fromkeys(values)) for key, values in question_assertions.items()
        },
    )
    try:
        overview = build_management_overview(bundle)
    except Exception as error:
        from loguru import logger

        logger.warning("management_overview_unavailable reason={}", type(error).__name__)
        overview = ManagementOverview(
            inputSha256=input_hash, markdownSha256=markdown_hash, status="unavailable",
            requiredQuestionCount=len(questions.required_question_ids) if questions else None,
            reasons=("overview_check_failed",),
        )
        bundle = bundle.model_copy(update={"issues": (*bundle.issues, QualityIssue(
            code="management_overview_unavailable", reasons=("overview_check_failed",),
        ))})
    return bundle.model_copy(update={"management_overview": overview})


def quality_bundle_is_current(
    bundle: QualityBundle,
    index: RevisionTraceIndexV1,
    markdown: str,
    *,
    input_sha256: str,
) -> bool:
    return (
        bundle.report_id == index.report_id
        and bundle.revision == index.revision
        and bundle.markdown_sha256 == hashlib.sha256(markdown.encode()).hexdigest()
        and bundle.input_sha256 == input_sha256
        and bundle.checker_version == RULE_VERSION
        and bundle.semantic_rule_versions == SEMANTIC_RULE_VERSIONS
    )
