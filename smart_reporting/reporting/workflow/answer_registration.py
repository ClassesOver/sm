"""Trusted application hook for exact answer mappings; never a model tool.

The hook approves requirement-to-evidence intent, not the current truth of an
answer. Only a durable frozen plan and freshly evaluated proofs can establish it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..trace.assertions import AssertionResult
from ..trace.contracts_v1 import FactRefV1, NumberReferenceV1, RevisionTraceIndexV1
from .answer_review import AnswerReviewPlan
from .questions import QuestionSet

if TYPE_CHECKING:
    from ..trace.quality_bundle import QualityBundle

MAX_REGISTRATION_BYTES = 256 * 1024
MAX_CONTEXT_BYTES = 2 * 1024 * 1024
PROVIDER_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class AnswerReviewCandidate:
    subject_id: str
    fact_refs: tuple[FactRefV1, ...]
    number_reference: NumberReferenceV1
    assertion: AssertionResult | None
    statement_verified: bool


@dataclass(frozen=True)
class AnswerReviewRegistrationContext:
    report_id: str
    revision: int
    profile_hash: str
    authorization_scope_hash: str
    markdown_sha256: str
    quality_input_sha256: str
    questions: QuestionSet
    candidates: tuple[AnswerReviewCandidate, ...]


AnswerReviewPlanProvider = Callable[
    [AnswerReviewRegistrationContext], Awaitable[AnswerReviewPlan | None]
]


def registration_context(quality: QualityBundle, index: RevisionTraceIndexV1,
                         authorization_scope_hash: str) -> AnswerReviewRegistrationContext:
    """Use only the current server evaluation; caller must verify source bytes."""
    files = {file.resource_id: file for file in index.files}
    if (quality.report_id != index.report_id or quality.revision != index.revision
            or quality.markdown_sha256 != files[index.markdown_file_resource_id].sha256
            or quality.question_specs is None):
        raise ValueError("answer registration input identity mismatch")
    assertions = {item.assertion_id: item for item in quality.assertions}
    if len(assertions) != len(quality.assertions):
        raise ValueError("answer registration assertion identity ambiguous")
    blocked = {issue.subject_id for issue in quality.issues if issue.subject_id is not None}
    candidates = []
    context_bytes = len(quality.question_specs.model_dump_json(by_alias=True).encode())
    if context_bytes > MAX_CONTEXT_BYTES:
        raise ValueError("answer registration context exceeds budget")
    for subject in index.subject_bindings:
        if subject.number_reference is None:
            continue
        assertion = assertions.get(quality.subject_assertions.get(subject.subject_id, ""))
        if assertion is not None and (assertion.profile_hash != (index.profile_hash or "0" * 64)
                or assertion.authorization_scope_hash != authorization_scope_hash):
            raise ValueError("answer registration assertion provenance mismatch")
        context_bytes += len(subject.number_reference.model_dump_json(by_alias=True).encode()) + len(subject.subject_id.encode())
        if assertion is not None:
            context_bytes += len(assertion.model_dump_json(by_alias=True).encode())
        context_bytes += sum(len(ref.model_dump_json(by_alias=True).encode()) for ref in subject.fact_refs)
        if context_bytes > MAX_CONTEXT_BYTES:
            raise ValueError("answer registration context exceeds budget")
        candidates.append(AnswerReviewCandidate(subject.subject_id, subject.fact_refs, subject.number_reference,
            assertion.model_copy(deep=True) if assertion is not None else None,
            assertion is not None and subject.subject_id not in blocked))
    return AnswerReviewRegistrationContext(index.report_id, index.revision,
        index.profile_hash or "0" * 64, authorization_scope_hash, quality.markdown_sha256,
        quality.input_sha256, quality.question_specs.model_copy(deep=True), tuple(candidates))


def validate_registration(plan: AnswerReviewPlan, context: AnswerReviewRegistrationContext) -> None:
    """Unknown conditions remain present; approval cannot redirect a selector."""
    plan.validate_questions(context.questions)
    if len(plan.model_dump_json(by_alias=True).encode()) > MAX_REGISTRATION_BYTES:
        raise ValueError("answer registration exceeds budget")
    candidates = {item.subject_id: item for item in context.candidates}
    for criterion in plan.criteria:
        for subject_id in criterion.subject_ids:
            candidate = candidates.get(subject_id)
            if candidate is None or candidate.assertion is None or candidate.assertion.request != criterion.request:
                raise ValueError("answer registration subject or request mismatch")
