"""Frozen requirements, analysis-question identity and honest answer coverage."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from loguru import logger
from pydantic import Field, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..trace.contracts_v1 import canonical_sha256


class QuestionSpec(StrictModel):
    question_id: str = Field(alias="questionId", pattern=r"^question-[0-9a-f]{64}$")
    kind: Literal["request", "analysis"]
    text: str = Field(min_length=1, max_length=8000)
    analysis_ids: tuple[str, ...] = Field(default=(), alias="analysisIds", max_length=200)
    completion_conditions: tuple[str, ...] = Field(
        default=(), alias="completionConditions", max_length=100
    )

    @model_validator(mode="after")
    def check_conditions(self) -> QuestionSpec:
        if len(set(self.completion_conditions)) != len(self.completion_conditions) or any(
            not item.strip() for item in self.completion_conditions
        ):
            raise ValueError("冻结完成条件必须非空且不可重复")
        return self


class QuestionSet(StrictModel):
    version: Literal["1"] = "1"
    stage: Literal["request", "analysis"]
    request_sha256: str = Field(alias="requestSha256", pattern=SHA256_PATTERN)
    questions: tuple[QuestionSpec, ...] = Field(min_length=1, max_length=1000)
    required_question_ids: tuple[str, ...] = Field(
        alias="requiredQuestionIds", min_length=1, max_length=1000
    )
    analysis_to_question: dict[str, str] = Field(
        default_factory=dict, alias="analysisToQuestion", max_length=200
    )

    @model_validator(mode="after")
    def check_identity(self) -> QuestionSet:
        by_id = {item.question_id: item for item in self.questions}
        if len(by_id) != len(self.questions) or len(set(self.required_question_ids)) != len(
            self.required_question_ids
        ):
            raise ValueError("问题身份不可重复")
        if set(self.required_question_ids) != {
            item.question_id for item in self.questions if item.kind == "request"
        }:
            raise ValueError("必答分母必须保留全部原始需求，不得改为分析项计数")
        assigned = {
            aid: item.question_id
            for item in self.questions
            if item.kind == "analysis"
            for aid in item.analysis_ids
        }
        if assigned != self.analysis_to_question or sum(
            len(item.analysis_ids) for item in self.questions
        ) != len(assigned):
            raise ValueError("分析项必须唯一绑定冻结问题")
        if self.stage == "request" and assigned:
            raise ValueError("请求阶段不能伪造分析映射")
        return self


def request_questions(goal: str, feedback: Sequence[str] = ()) -> QuestionSet:
    request_hash = hashlib.sha256(goal.encode()).hexdigest()
    questions = tuple(
        QuestionSpec(
            questionId="question-"
            + canonical_sha256({"request": request_hash, "kind": "request", "text": text}),
            kind="request",
            text=text,
            completionConditions=(text,),
        )
        for text in dict.fromkeys(value.strip() for value in (goal, *feedback) if value.strip())
    )
    return QuestionSet(
        stage="request",
        requestSha256=request_hash,
        questions=questions,
        requiredQuestionIds=tuple(item.question_id for item in questions),
    )


def freeze_analysis_questions(
    current: QuestionSet, analyses: Sequence[Mapping[str, Any]]
) -> QuestionSet:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in analyses:
        text = item.get("managementQuestion")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(item.get("analysisId"), str)
        ):
            raise ValueError("分析计划缺少有效问题或身份")
        grouped.setdefault(text.strip(), []).append(item)
    questions = [item for item in current.questions if item.kind == "request"]
    mapping = {}
    for text, items in grouped.items():
        question_id = "question-" + canonical_sha256(
            {"request": current.request_sha256, "kind": "analysis", "text": text}
        )
        analysis_ids = tuple(item["analysisId"] for item in items)
        conditions = tuple(
            dict.fromkeys(
                condition for item in items for condition in item.get("completionConditions", ())
            )
        )
        questions.append(
            QuestionSpec(
                questionId=question_id,
                kind="analysis",
                text=text,
                analysisIds=analysis_ids,
                completionConditions=conditions,
            )
        )
        mapping.update(dict.fromkeys(analysis_ids, question_id))
    result = QuestionSet(
        stage="analysis",
        requestSha256=current.request_sha256,
        questions=tuple(questions),
        requiredQuestionIds=current.required_question_ids,
        analysisToQuestion=mapping,
    )
    if current.stage == "analysis" and current != result:
        raise ValueError("冻结的问题与完成条件不可由恢复或返工静默改写")
    return result



def freeze_plan_questions(
    current: QuestionSet, analyses: Sequence[Mapping[str, Any]], *, goal: str, feedback: Sequence[str] = (),
) -> QuestionSet:
    """按当前计划冻结问题。会话沿用的冻结问题与本次规划不一致（新一轮运行或修订重新规划）时，
    按当前请求问题重新冻结并软告警，不让语义映射校验中断整份报告；计划本身无效仍报错。"""
    try:
        return freeze_analysis_questions(current, analyses)
    except ValueError:
        if current.stage != "analysis":
            raise
    logger.warning("report_question_specs_refrozen analyses={}", len(analyses))
    return freeze_analysis_questions(request_questions(goal, feedback), analyses)

class AnswerEvaluation(StrictModel):
    question_id: str = Field(alias="questionId")
    status: Literal["answered", "partial", "unanswered"]
    completed_conditions: tuple[str, ...] = Field(default=(), alias="completedConditions")
    assertion_ids: tuple[str, ...] = Field(default=(), alias="assertionIds")
    reviewer: Literal["deterministic", "domain"]


def effective_answer_coverage(
    questions: QuestionSet,
    evaluations: Sequence[AnswerEvaluation],
    supported_assertion_ids: set[str],
) -> dict[str, Any]:
    """Allocation, workflow completion and unreviewed answers never count as answered.

    Evaluations must be issued by a trusted checker/domain review, not passed
    through from model prose. No model-facing write endpoint is provided.
    """
    by_id = {item.question_id: item for item in questions.questions}
    records = {item.question_id: item for item in evaluations}
    if len(records) != len(evaluations) or set(records) - set(by_id):
        raise ValueError("回答记录重复或引用未知问题")
    evaluated = 0
    answered = 0
    for question_id in questions.required_question_ids:
        record = records.get(question_id)
        if record is None:
            continue
        evaluated += 1
        spec = by_id[question_id]
        if (
            record.status == "answered"
            and spec.completion_conditions
            and set(record.completed_conditions) == set(spec.completion_conditions)
            and record.assertion_ids
            and set(record.assertion_ids) <= supported_assertion_ids
        ):
            answered += 1
    required = len(questions.required_question_ids)
    return {
        "required": required,
        "evaluated": evaluated,
        "answered": answered,
        "effectiveAnswerRate": answered / required if evaluated == required else None,
        "evaluationStatus": "evaluated" if evaluated == required else "not_fully_evaluated",
    }
