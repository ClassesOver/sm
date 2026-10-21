"""Answer coverage requires approved finite criteria and current statement proofs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.trace.assertions import AssertionRequest
from smart_reporting.reporting.trace.contracts_v1 import canonical_sha256
from smart_reporting.reporting.workflow.answer_review import (
    AnswerConditionCheck,
    AnswerCriterion,
    AnswerReviewPlan,
    evaluate_answer_review,
    questions_sha256,
)
from smart_reporting.reporting.workflow.questions import (
    freeze_analysis_questions,
    request_questions,
)
from smart_reporting.reporting.workflow.state import ReportingStateError, apply

from .test_assertion_compiler import compiler, facts, token
from .test_reporting_state import initial_state


def fixture():
    questions = freeze_analysis_questions(
        request_questions("核验北院支出"),
        [
            {
                "analysisId": "analysis_001",
                "managementQuestion": "北院支出是多少",
                "completionConditions": ["支出值已核验"],
            }
        ],
    )
    request = AssertionRequest(operation="value", operands=(token(),))
    proof = compiler([facts(scope={"院区": "北院"})]).compile(request)
    assert proof.status == "supported"
    spec = questions.questions[0]
    criterion = AnswerCriterion(
        questionId=spec.question_id,
        condition=spec.completion_conditions[0],
        request=request,
        subjectIds=("subject-1",),
    )
    plan = AnswerReviewPlan(questionSetSha256=questions_sha256(questions), criteria=(criterion,))
    return questions, proof, plan


def run(questions, proof, plan, *, subjects=None, blocked=None, input_sha256="a" * 64):
    return evaluate_answer_review(
        questions,
        plan,
        (proof,),
        subjects if subjects is not None else {"subject-1": proof.assertion_id},
        blocked or set(),
        input_sha256=input_sha256,
    )


def test_finite_condition_execution_can_establish_required_answer_without_borrowing_analysis_allocation():
    questions, proof, plan = fixture()
    review = run(questions, proof, plan)
    assert review.coverage(questions)["effectiveAnswerRate"] == 1
    # The allocated analysis question has no approved mapping and remains unknown.
    assert review.conditions[-1].status == "unknown"
    assert review.conditions[-1].reasons == ("condition_mapping_unavailable",)
    assert review.input_sha256 == "a" * 64
    assert review.plan_sha256 == canonical_sha256(plan.model_dump(mode="json", by_alias=True))


@pytest.mark.parametrize(
    "fault", ["no_plan", "blocked", "no_subject", "wrong_request", "unknown_proof", "analysis_only"]
)
def test_unknown_and_unanswered_conditions_do_not_become_effective_answers(fault):
    questions, proof, plan = fixture()
    kwargs = {}
    if fault == "no_plan":
        plan = None
    elif fault == "blocked":
        kwargs["blocked"] = {"subject-1"}
    elif fault == "no_subject":
        kwargs["subjects"] = {}
    elif fault == "wrong_request":
        criterion = plan.criteria[0].model_copy(
            update={
                "request": AssertionRequest(
                    operation="value", operands=(token(selector="periodValues.0"),)
                )
            }
        )
        plan = plan.model_copy(update={"criteria": (criterion,)})
    elif fault == "unknown_proof":
        proof = proof.model_copy(update={"status": "unknown", "reasons": ("scope_unknown",)})
    else:
        spec = questions.questions[-1]
        criterion = plan.criteria[0].model_copy(
            update={"question_id": spec.question_id, "condition": spec.completion_conditions[0]}
        )
        plan = plan.model_copy(update={"criteria": (criterion,)})
    review = run(questions, proof, plan, **kwargs)
    coverage = review.coverage(questions)
    assert coverage["answered"] == 0
    assert coverage["effectiveAnswerRate"] == (
        0 if fault in {"no_subject", "wrong_request"} else None
    )
    if fault == "no_subject":
        assert review.evaluations(questions)[0].status == "unanswered"
        assert review.conditions[0].reasons == ("required_evidence_absent",)


def test_all_required_subjects_and_each_required_request_condition_must_pass():
    questions, proof, plan = fixture()
    criterion = plan.criteria[0].model_copy(update={"subject_ids": ("subject-1", "subject-2")})
    review = run(questions, proof, plan.model_copy(update={"criteria": (criterion,)}))
    assert review.coverage(questions)["effectiveAnswerRate"] == 0
    assert not review.conditions[0].assertion_ids
    # An otherwise valid proof cannot conceal a changed mandatory statement.
    review = run(
        questions,
        proof,
        plan.model_copy(update={"criteria": (criterion,)}),
        subjects={"subject-1": proof.assertion_id, "subject-2": proof.assertion_id},
        blocked={"subject-2"},
    )
    assert review.coverage(questions)["effectiveAnswerRate"] is None


def test_plan_identity_and_question_conditions_cannot_be_forged():
    questions, proof, plan = fixture()
    with pytest.raises(ValueError, match="冻结问题"):
        run(questions, proof, plan.model_copy(update={"question_set_sha256": "f" * 64}))
    criterion = plan.criteria[0].model_copy(update={"condition": "只需章节生成"})
    with pytest.raises(ValueError, match="冻结条件"):
        run(questions, proof, plan.model_copy(update={"criteria": (criterion,)}))
    with pytest.raises(ValidationError, match="重复"):
        AnswerReviewPlan(
            questionSetSha256=questions_sha256(questions), criteria=(*plan.criteria, *plan.criteria)
        )
    with pytest.raises(ValueError, match="断言身份重复"):
        evaluate_answer_review(questions, plan, (proof, proof), {}, set(), input_sha256="a" * 64)
    with pytest.raises(ValidationError, match="只有满足"):
        AnswerConditionCheck(
            questionId=questions.required_question_ids[0], condition="x", status="met"
        )


def test_review_recomputes_current_subject_evidence_instead_of_reusing_a_pass():
    questions, proof, plan = fixture()
    first = run(questions, proof, plan)
    second = run(questions, proof, plan, blocked={"subject-1"}, input_sha256="b" * 64)
    assert first.coverage(questions)["answered"] == 1
    assert second.coverage(questions)["answered"] == 0
    assert first.input_sha256 != second.input_sha256


def command(state, name, **payload):
    return apply(
        state,
        {"name": name, "commandId": f"{name}-{state.state_version}", "payload": payload},
        state.state_version,
    )


def test_cas_plan_freeze_review_record_restore_and_input_conflicts():
    questions, proof, plan = fixture()
    state = initial_state()
    aids = list(questions.analysis_to_question)
    state = command(
        state,
        "set_analysis_plan",
        analysisIds=aids,
        analysisPlans={aid: {"questionId": questions.analysis_to_question[aid]} for aid in aids},
        questionSpecs=questions.model_dump(mode="json", by_alias=True),
    ).state
    raw_plan = plan.model_dump(mode="json", by_alias=True)
    state = command(state, "freeze_answer_review_plan", plan=raw_plan).state
    state = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    assert state.payload["answerReviewPlan"] == raw_plan
    wrong = plan.model_copy(update={"criteria": ()}).model_dump(mode="json", by_alias=True)
    with pytest.raises(ReportingStateError) as error:
        command(state, "freeze_answer_review_plan", plan=wrong)
    assert error.value.code == "report_answer_review_plan_conflict"
    review = run(questions, proof, plan)
    state = command(
        state,
        "record_answer_review",
        revision=state.revision,
        review=review.model_dump(mode="json", by_alias=True),
    ).state
    assert state.payload["currentAnswerReviewInputSha256"] == review.input_sha256
    state = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    changed = run(questions, proof, plan, subjects={})
    with pytest.raises(ReportingStateError) as error:
        command(
            state,
            "record_answer_review",
            revision=state.revision,
            review=changed.model_dump(mode="json", by_alias=True),
        )
    assert error.value.code == "report_answer_review_result_conflict"
    with pytest.raises(ReportingStateError) as error:
        command(
            state,
            "record_answer_review",
            revision=state.revision + 1,
            review=review.model_dump(mode="json", by_alias=True),
        )
    assert error.value.code == "report_answer_review_revision_conflict"
    with pytest.raises(ReportingStateError):
        command(
            state,
            "record_answer_review",
            revision=state.revision,
            review=review.model_copy(update={"plan_sha256": "f" * 64}).model_dump(
                mode="json", by_alias=True
            ),
        )


def test_cas_without_an_approved_plan_never_accepts_a_pass():
    questions, proof, plan = fixture()
    state = initial_state().model_copy(
        update={"payload": {"questionSpecs": questions.model_dump(mode="json", by_alias=True)}}
    )
    review = run(questions, proof, plan)
    with pytest.raises(ReportingStateError):
        command(
            state,
            "record_answer_review",
            revision=state.revision,
            review=review.model_dump(mode="json", by_alias=True),
        )
    unknown = run(questions, proof, None)
    state = command(
        state,
        "record_answer_review",
        revision=state.revision,
        review=unknown.model_dump(mode="json", by_alias=True),
    ).state
    assert state.payload["answerReviews"]


def test_coverage_denominator_keeps_unmapped_original_feedback_and_partial_conditions():
    questions, proof, plan = fixture()
    original = request_questions("核验北院支出", ("说明数据限制",))
    questions = freeze_analysis_questions(
        original,
        [
            {
                "analysisId": "analysis_001",
                "managementQuestion": "北院支出是多少",
                "completionConditions": ["支出值已核验"],
            }
        ],
    )
    plan = plan.model_copy(update={"question_set_sha256": questions_sha256(questions)})
    review = run(questions, proof, plan)
    assert review.coverage(questions) == {
        "required": 2,
        "evaluated": 1,
        "answered": 1,
        "effectiveAnswerRate": None,
        "evaluationStatus": "not_fully_evaluated",
    }
    # A required question with two approved conditions is only partial when one
    # mandatory statement is absent, even though its other proof is supported.
    questions, proof, plan = fixture()
    request_spec = questions.questions[0].model_copy(update={"completion_conditions": ("a", "b")})
    questions = questions.model_copy(update={"questions": (request_spec, *questions.questions[1:])})
    criterion = plan.criteria[0].model_copy(update={"condition": "a"})
    missing = criterion.model_copy(update={"condition": "b", "subject_ids": ("subject-missing",)})
    plan = plan.model_copy(
        update={
            "question_set_sha256": questions_sha256(questions),
            "criteria": (criterion, missing),
        }
    )
    review = run(questions, proof, plan)
    assert review.evaluations(questions)[0].status == "partial"
    assert review.evaluations(questions)[0].completed_conditions == ("a",)
    assert review.coverage(questions)["effectiveAnswerRate"] == 0


def test_ambiguous_duplicate_frozen_conditions_are_rejected_before_review():
    from smart_reporting.reporting.workflow.questions import QuestionSpec

    questions, _, _ = fixture()
    raw = questions.questions[0].model_dump(mode="json", by_alias=True)
    for conditions in (["a", "a"], [" "]):
        with pytest.raises(ValidationError, match="不可重复"):
            QuestionSpec.model_validate({**raw, "completionConditions": conditions})
