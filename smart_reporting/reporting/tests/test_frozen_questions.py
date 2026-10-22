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


def test_same_session_feedback_refreshes_frozen_request_questions():
    # 审阅：首轮冻结到 analysis 阶段后，同一会话追加的反馈永远不进入必答问题。
    from smart_reporting.reporting.contract import ReportRequestEnvelope
    from smart_reporting.reporting.workflow.runtime.planning import RuntimePlanningMixin

    envelope = ReportRequestEnvelope.model_validate(
        {"reportGoal": "分析收入", "period": {"start": "2025-01-01", "end": "2025-12-31"}}
    )
    frozen = freeze_analysis_questions(request_questions("分析收入"), analyses())
    state = {"report_request_context": {
        "originalGoal": "分析收入", "feedback": [], "questionSpecs": frozen.model_dump(mode="json", by_alias=True),
    }}
    RuntimePlanningMixin._record_normalized_request(state, envelope)
    assert state["report_request_context"]["questionSpecs"]["stage"] == "analysis"
    state["report_request_context"]["feedback"].append({"sequence": 1, "content": "补充成本对比"})
    RuntimePlanningMixin._record_normalized_request(state, envelope)
    refreshed = QuestionSet.model_validate(state["report_request_context"]["questionSpecs"])
    assert refreshed.stage == "request"
    assert refreshed.required_question_ids == request_questions("分析收入", ("补充成本对比",)).required_question_ids


def test_replanned_analyses_refreeze_from_current_request_instead_of_failing():
    # 审阅：会话沿用的冻结问题与新一轮规划不一致时抛 ValueError，整份报告失败。
    from smart_reporting.reporting.workflow.questions import freeze_plan_questions

    frozen = freeze_analysis_questions(request_questions("分析收入"), analyses())
    replanned = [{"analysisId": "analysis_009", "managementQuestion": "成本如何", "completionConditions": ["核验成本"]}]
    refrozen = freeze_plan_questions(frozen, replanned, goal="分析收入", feedback=("补充成本",))
    assert set(refrozen.analysis_to_question) == {"analysis_009"}
    assert refrozen.required_question_ids == request_questions("分析收入", ("补充成本",)).required_question_ids
    # 计划本身无效仍报错；一致时沿用原冻结结果。
    with pytest.raises(ValueError, match="缺少"):
        freeze_plan_questions(frozen, [{"analysisId": "a"}], goal="分析收入")
    assert freeze_plan_questions(frozen, analyses(), goal="分析收入") == frozen
