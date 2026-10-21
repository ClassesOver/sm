"""Server-only, finite answer criteria; never infer business answers from prose.

A trusted server/domain integration must approve the mapping from natural-language
requirements to exact assertion requests and subject identities. Model plans and
completion text do not grant that authority. Missing mappings stay unknown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..trace.assertions import AssertionRequest, AssertionResult
from ..trace.contracts_v1 import canonical_sha256
from .questions import AnswerEvaluation, QuestionSet, effective_answer_coverage


class AnswerCriterion(StrictModel):
    question_id: str = Field(alias="questionId")
    condition: str = Field(min_length=1, max_length=8000)
    request: AssertionRequest
    subject_ids: tuple[str, ...] = Field(alias="subjectIds", min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_subjects(self) -> AnswerCriterion:
        if len(set(self.subject_ids)) != len(self.subject_ids) or any(
            not value for value in self.subject_ids
        ):
            raise ValueError("回答条件必须使用唯一且非空的正文主体身份")
        return self


class AnswerReviewPlan(StrictModel):
    version: Literal["1"] = "1"
    question_set_sha256: str = Field(alias="questionSetSha256", pattern=SHA256_PATTERN)
    criteria: tuple[AnswerCriterion, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def unique_conditions(self) -> AnswerReviewPlan:
        if len({(item.question_id, item.condition) for item in self.criteria}) != len(
            self.criteria
        ):
            raise ValueError("回答条件映射不可重复")
        return self

    def validate_questions(self, questions: QuestionSet) -> None:
        if self.question_set_sha256 != questions_sha256(questions):
            raise ValueError("回答审核计划不属于当前冻结问题")
        by_id = {item.question_id: item for item in questions.questions}
        if any(
            item.question_id not in by_id
            or item.condition not in by_id[item.question_id].completion_conditions
            for item in self.criteria
        ):
            raise ValueError("回答审核计划不得增删或改写冻结条件")


def questions_sha256(questions: QuestionSet) -> str:
    return canonical_sha256(questions.model_dump(mode="json", by_alias=True))


class AnswerConditionCheck(StrictModel):
    question_id: str = Field(alias="questionId")
    condition: str
    status: Literal["met", "not_met", "unknown"]
    assertion_ids: tuple[str, ...] = Field(default=(), alias="assertionIds")
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_evidence(self) -> AnswerConditionCheck:
        if (self.status == "met") != bool(self.assertion_ids):
            raise ValueError("只有满足的回答条件可登记已核验断言")
        if len(set(self.assertion_ids)) != len(self.assertion_ids):
            raise ValueError("回答证据不可重复")
        return self


class AnswerReviewResult(StrictModel):
    version: Literal["1"] = "1"
    input_sha256: str = Field(alias="inputSha256", pattern=SHA256_PATTERN)
    question_set_sha256: str = Field(alias="questionSetSha256", pattern=SHA256_PATTERN)
    plan_sha256: str | None = Field(default=None, alias="planSha256", pattern=SHA256_PATTERN)
    conditions: tuple[AnswerConditionCheck, ...] = ()

    def validate_questions(self, questions: QuestionSet) -> None:
        if self.question_set_sha256 != questions_sha256(questions):
            raise ValueError("回答审核结果不属于当前冻结问题")
        expected = {
            (spec.question_id, condition)
            for spec in questions.questions
            for condition in spec.completion_conditions
        }
        observed = {(item.question_id, item.condition) for item in self.conditions}
        if expected != observed or len(observed) != len(self.conditions):
            raise ValueError("回答审核必须逐条保留全部冻结条件")

    def evaluations(self, questions: QuestionSet) -> tuple[AnswerEvaluation, ...]:
        self.validate_questions(questions)
        grouped: dict[str, list[AnswerConditionCheck]] = {}
        for item in self.conditions:
            grouped.setdefault(item.question_id, []).append(item)
        result = []
        for spec in questions.questions:
            checks = grouped.get(spec.question_id, [])
            if not checks or any(item.status == "unknown" for item in checks):
                continue
            met = [item for item in checks if item.status == "met"]
            result.append(
                AnswerEvaluation(
                    questionId=spec.question_id,
                    status="answered"
                    if len(met) == len(checks)
                    else "partial"
                    if met
                    else "unanswered",
                    completedConditions=tuple(item.condition for item in met),
                    assertionIds=tuple(
                        dict.fromkeys(aid for item in met for aid in item.assertion_ids)
                    ),
                    reviewer="deterministic",
                )
            )
        return tuple(result)

    def coverage(self, questions: QuestionSet) -> dict:
        return effective_answer_coverage(
            questions,
            self.evaluations(questions),
            {aid for item in self.conditions if item.status == "met" for aid in item.assertion_ids},
        )


def evaluate_answer_review(
    questions: QuestionSet,
    plan: AnswerReviewPlan | None,
    assertions: Sequence[AssertionResult],
    subject_assertions: Mapping[str, str],
    blocked_subject_ids: set[str],
    *,
    input_sha256: str,
) -> AnswerReviewResult:
    """Re-evaluate exact current proofs and presentation, never reuse prior passes.

    Call only with server-compiled assertions from the current quality evaluation.
    A proof is insufficient when its current subject failed statement/identity checks.
    """
    if plan is not None:
        plan.validate_questions(questions)
    criteria = (
        {(item.question_id, item.condition): item for item in plan.criteria}
        if plan is not None
        else {}
    )
    by_id = {item.assertion_id: item for item in assertions}
    if len(by_id) != len(assertions):
        raise ValueError("回答审核输入断言身份重复")
    checks = []
    for spec in questions.questions:
        for condition in spec.completion_conditions:
            criterion = criteria.get((spec.question_id, condition))
            status: Literal["met", "not_met", "unknown"] = "unknown"
            evidence = []
            reasons = []
            if criterion is None:
                reasons.append("condition_mapping_unavailable")
            else:
                unknown = False
                for subject_id in criterion.subject_ids:
                    assertion_id = subject_assertions.get(subject_id)
                    assertion = by_id.get(assertion_id) if assertion_id is not None else None
                    if subject_id in blocked_subject_ids:
                        unknown = True
                        reasons.append("current_statement_unverified")
                    elif assertion is None:
                        reasons.append("required_evidence_absent")
                    elif assertion.request != criterion.request:
                        reasons.append("required_assertion_mismatch")
                    elif assertion.status != "supported":
                        unknown = True
                        reasons.extend(assertion.reasons or ("assertion_support_unknown",))
                    else:
                        evidence.append(assertion.assertion_id)
                # All declared subjects are mandatory. One valid citation cannot
                # hide a contradictory/deleted required statement elsewhere.
                if len(evidence) == len(criterion.subject_ids):
                    status = "met"
                elif unknown:
                    status = "unknown"
                    evidence = []
                else:
                    status = "not_met"
                    evidence = []
            checks.append(
                AnswerConditionCheck(
                    questionId=spec.question_id,
                    condition=condition,
                    status=status,
                    assertionIds=tuple(dict.fromkeys(evidence)),
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )
    return AnswerReviewResult(
        inputSha256=input_sha256,
        questionSetSha256=questions_sha256(questions),
        planSha256=canonical_sha256(plan.model_dump(mode="json", by_alias=True))
        if plan is not None
        else None,
        conditions=tuple(checks),
    )
