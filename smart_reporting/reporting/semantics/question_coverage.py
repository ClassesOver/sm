"""原始问题的正式证据覆盖；计算成功不自动授予回答完成。"""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from .models import ClaimSupport, Identity, QuestionCoverage, SemanticModel
from .planning_contracts import MetricPlanningContext


class RegisteredAnswerCriterion(SemanticModel):
    question_id: Identity
    condition: str = Field(min_length=1, max_length=8000)
    kind: Literal['fact', 'inference', 'recommendation']
    subject_ids: tuple[Identity, ...] = Field(min_length=1, max_length=200)
    fact_refs: tuple[Identity, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_references(self):
        if len(set(self.subject_ids)) != len(self.subject_ids) or len(set(self.fact_refs)) != len(self.fact_refs):
            raise ValueError('完成条件的主体与事实身份不可重复')
        return self


class RegisteredAnswerPlan(SemanticModel):
    """只接收服务端批准的完整问题到证据映射，不接受模型自行登记。"""
    report_basis_id: Identity
    question_set_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    criteria: tuple[RegisteredAnswerCriterion, ...] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique_conditions(self):
        if len({(item.question_id, item.condition) for item in self.criteria}) != len(self.criteria):
            raise ValueError('问题完成条件不可重复')
        return self

    def validate_questions(self, questions, basis_id: str):
        from ..workflow.answer_review import questions_sha256

        by_id = {item.question_id: item for item in questions.questions}
        if (self.report_basis_id != basis_id or self.question_set_sha256 != questions_sha256(questions)
            or any(item.question_id not in questions.required_question_ids
                or item.condition not in by_id[item.question_id].completion_conditions for item in self.criteria)):
            raise ValueError('完成映射不属于当前计算依据或原始问题')


def evaluate_registered_question_coverage(*, basis_id: str, documents: Mapping,
    supports: Sequence[ClaimSupport], questions, plan: RegisteredAnswerPlan | None = None):
    """调用方先验证文件身份和依据；缺来源、选择或完成映射均保留具体缺项。"""
    from ..workflow.answer_review import questions_sha256

    contexts = [document['metricContext'] for document in documents.values() if document.get('metricContext')]
    context = MetricPlanningContext.model_validate(contexts[0]) if contexts else None
    context_valid = bool(context and context.basis_id == basis_id and all(item == contexts[0] for item in contexts))
    if questions is None and context_valid:
        from ..workflow.questions import request_questions

        questions = request_questions(context.request.goal, questions=context.request.questions)
    if questions is None:
        return ()
    by_id = {item.question_id: item for item in questions.questions}
    registered = {item.id: item.text for item in context.request.questions} if context_valid else {}
    plan_valid = bool(plan and plan.report_basis_id == basis_id
        and plan.question_set_sha256 == questions_sha256(questions)
        and all(item.question_id in questions.required_question_ids
            and item.condition in by_id[item.question_id].completion_conditions for item in plan.criteria))
    coverage = []
    for question_id in questions.required_question_ids:
        spec = by_id[question_id]
        issues = []
        if not context_valid:
            issues.append('registered_question_sources_unavailable')
        elif registered.get(question_id) != spec.text:
            issues.append('registered_question_identity_mismatch')
        choices = [item for item in context.selections if item.question_id == question_id] if context_valid else []
        choice = choices[0] if len(choices) == 1 else None
        if choice is None:
            issues.append('metric_selection_unavailable')
        elif choice.status != 'resolved':
            issues.extend(choice.issue_codes or ('metric_selection_unresolved',))
        results = [result for calculation in context.calculations for result in calculation.results
            if choice and choice.status == 'resolved' and result.metric_version == choice.selected
            and result.period in (context.request.period, context.request.comparison_period)] if context_valid else []
        result_ids = {item.fact_id for item in results}
        related = [support for support in supports if set(support.fact_refs) & result_ids]
        verified = {support.subject_id: support for support in related if support.support_status == 'supported'}
        computed = [item for item in results if item.status == 'computed']
        issues.extend(code for result in results for code in result.issue_codes)
        if not results:
            issues.append('registered_question_results_unavailable')
        elif {result.period for result in results} != {
            period for period in (context.request.period, context.request.comparison_period) if period is not None}:
            issues.append('registered_question_period_unavailable')
        if results and not verified:
            issues.append('question_support_unverified')
        checks = [item for item in plan.criteria if item.question_id == question_id] if plan_valid else []
        expected_conditions = set(spec.completion_conditions)
        checked = set()
        used_facts = set()
        for criterion in checks:
            selected = [verified[identity] for identity in criterion.subject_ids if identity in verified]
            facts = {fact for support in selected for fact in support.fact_refs}
            if (len(selected) == len(criterion.subject_ids) and all(item.kind == criterion.kind for item in selected)
                and facts == set(criterion.fact_refs) and facts.issubset(result_ids)):
                checked.add(criterion.condition)
                used_facts.update(facts)
        if not plan_valid or not checks:
            issues.append('question_completion_mapping_unavailable')
        elif checked != expected_conditions or used_facts != result_ids:
            issues.append('question_completion_evidence_unverified')
        if not expected_conditions:
            issues.append('question_completion_conditions_unavailable')
        status = 'answered' if not issues and checked == expected_conditions else 'partial' if computed else 'unavailable'
        coverage.append(QuestionCoverage(question_id=question_id, status=status,
            subject_ids=tuple(item.subject_id for item in related), issue_codes=tuple(dict.fromkeys(issues))))
    return tuple(coverage)
