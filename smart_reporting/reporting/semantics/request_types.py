"""报告入口与业务定义共享的严格身份类型；不依赖工作流契约。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ...office.contract import SHA256_PATTERN as SHA256_PATTERN

FIELD_REF_PATTERN = (
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}$"
)

FieldRef = Annotated[str, Field(pattern=FIELD_REF_PATTERN)]

Identity = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
RunIdentity = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Revision = Annotated[int, Field(gt=0, strict=True)]
DomainCode = Literal["income", "workload", "budget", "full_cost", "cost_control", "funds"]


class SemanticModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, alias_generator=to_camel,
    )


class ReportQuestion(SemanticModel):
    id: Identity
    text: str = Field(min_length=1, max_length=4000)


class PolicyVersionRef(SemanticModel):
    policy_id: Identity
    revision: Revision


class ReportScenarioCandidate(SemanticModel):
    scenario: Identity
    name: str = Field(min_length=1, max_length=200)


class MetricVersionRef(SemanticModel):
    metric_id: Identity
    revision: Revision
