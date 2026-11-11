"""服务端正式问题完成映射入口；模型输出和公开请求不能注册批准。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..semantics.models import ClaimSupport
from ..semantics.question_coverage import RegisteredAnswerPlan
from ..trace.contracts_v1 import SubjectBindingV1
from .questions import QuestionSet


@dataclass(frozen=True)
class RegisteredAnswerRegistrationContext:
    report_id: str
    revision: int
    report_basis_id: str
    questions: QuestionSet
    supports: tuple[ClaimSupport, ...]
    subjects: tuple[SubjectBindingV1, ...]


RegisteredAnswerPlanProvider = Callable[[RegisteredAnswerRegistrationContext], Awaitable[RegisteredAnswerPlan | None]]


def validate_registered_answer_plan(plan, context):
    plan.validate_questions(context.questions, context.report_basis_id)
    if len(plan.model_dump_json(by_alias=True).encode()) > 256 * 1024:
        raise ValueError('正式问题完成映射超出容量限制')
    supports = {item.subject_id: item for item in context.supports}
    for item in plan.criteria:
        if any(identity not in supports for identity in item.subject_ids):
            raise ValueError('完成映射引用未登记主体')
        facts = {fact for identity in item.subject_ids for fact in supports[identity].fact_refs}
        if facts != set(item.fact_refs):
            raise ValueError('完成映射的原始事实与主体不一致')
