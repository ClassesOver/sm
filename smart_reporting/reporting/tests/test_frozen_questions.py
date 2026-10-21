import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_reporting_state import initial_state
from smart_reporting.reporting.workflow.questions import (
    AnswerEvaluation,
    QuestionSet,
    effective_answer_coverage,
    freeze_analysis_questions,
    request_questions,
)
from smart_reporting.reporting.workflow.state import ReportingStateError, apply


def analyses():
    return [
        {
            "analysisId": "analysis_001",
            "managementQuestion": "本期收入多少",
            "completionConditions": ["核验本期收入"],
        },
        {
            "analysisId": "analysis_002",
            "managementQuestion": "本期收入多少",
            "completionConditions": ["核验本期收入"],
        },
    ]


def test_request_requirements_stay_distinct_from_allocated_analysis_questions():
    original = request_questions("分析收入和成本", ("保留反例", "保留反例"))
    frozen = freeze_analysis_questions(original, analyses())
    assert frozen.required_question_ids == original.required_question_ids
    assert len(frozen.required_question_ids) == 2
    assert (
        frozen.analysis_to_question["analysis_001"] == frozen.analysis_to_question["analysis_002"]
    )
    restored = QuestionSet.model_validate_json(frozen.model_dump_json(by_alias=True))
    assert freeze_analysis_questions(restored, analyses()) == frozen
    assert effective_answer_coverage(frozen, (), set()) == {
        "required": 2,
        "evaluated": 0,
        "answered": 0,
        "effectiveAnswerRate": None,
        "evaluationStatus": "not_fully_evaluated",
    }


def test_frozen_criteria_and_required_denominator_cannot_be_rewritten():
    frozen = freeze_analysis_questions(request_questions("分析收入"), analyses())
    changed = [{**item, "completionConditions": ["只检查是否生成章节"]} for item in analyses()]
    with pytest.raises(ValueError, match="不可"):
        freeze_analysis_questions(frozen, changed)
    payload = frozen.model_dump(mode="json", by_alias=True)
    payload["requiredQuestionIds"] = list(frozen.analysis_to_question.values())[:1]
    with pytest.raises(ValidationError, match="必答"):
        QuestionSet.model_validate(payload)


def test_answer_requires_reviewed_criteria_and_supported_evidence_not_allocation():
    questions = request_questions("本期收入多少")
    spec = questions.questions[0]
    record = AnswerEvaluation(
        questionId=spec.question_id,
        status="answered",
        reviewer="deterministic",
        completedConditions=spec.completion_conditions,
        assertionIds=("proof-1",),
    )
    assert effective_answer_coverage(questions, (record,), {"proof-1"})["effectiveAnswerRate"] == 1
    assert effective_answer_coverage(questions, (record,), set())["effectiveAnswerRate"] == 0
    assert (
        effective_answer_coverage(
            questions, (record.model_copy(update={"completed_conditions": ()}),), {"proof-1"}
        )["answered"]
        == 0
    )
    with pytest.raises(ValueError, match="重复"):
        effective_answer_coverage(questions, (record, record), {"proof-1"})


def test_question_contract_is_frozen_in_existing_plan_cas():
    frozen = freeze_analysis_questions(request_questions("分析收入"), analyses())
    payload = {
        "analysisIds": list(frozen.analysis_to_question),
        "questionSpecs": frozen.model_dump(mode="json", by_alias=True),
        "analysisPlans": {
            aid: {"questionId": qid} for aid, qid in frozen.analysis_to_question.items()
        },
    }
    state = apply(
        initial_state(), {"name": "set_analysis_plan", "commandId": "first", "payload": payload}
    ).state
    other = freeze_analysis_questions(request_questions("只分析简单问题"), analyses())
    changed = {**payload, "questionSpecs": other.model_dump(mode="json", by_alias=True)}
    with pytest.raises(ReportingStateError) as error:
        apply(state, {"name": "set_analysis_plan", "commandId": "overwrite", "payload": changed})
    assert error.value.code == "report_question_specs_conflict"
    assert state.payload["questionSpecs"] == payload["questionSpecs"]
