"""采用新口径前的只读核对；预检不是新依据、计算或业务批准。"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from ..trace.contracts_v1 import canonical_sha256
from .models import (
    Identity,
    MetricSelection,
    MetricVersionRef,
    PolicyVersionRef,
    ReportQuestion,
    RunIdentity,
    SemanticIssue,
    SemanticModel,
    SourceVersionRef,
)

PolicyChangeField = Literal['name', 'metric_versions', 'filters', 'joins', 'valid_from', 'valid_to',
    'evidence_release_id', 'readiness_policy', 'decision_notes']


class PolicyAdoptionChange(SemanticModel):
    field: PolicyChangeField
    before: str
    after: str


class PolicyAdoptionMetricOption(SemanticModel):
    metric_version: MetricVersionRef
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=32)


class PolicyAdoptionPreview(SemanticModel):
    parent_basis_id: Identity
    parent_basis_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    original_policy_version: PolicyVersionRef
    target_policy_version: PolicyVersionRef
    target_policy_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    questions: tuple[ReportQuestion, ...] = Field(min_length=1, max_length=50)
    metric_options: tuple[PolicyAdoptionMetricOption, ...]
    source_versions: tuple[SourceVersionRef, ...]
    catalog_refs: tuple[SourceVersionRef, ...]
    metric_versions_added: tuple[MetricVersionRef, ...]
    metric_versions_removed: tuple[MetricVersionRef, ...]
    changed_fields: tuple[PolicyChangeField, ...]
    changes: tuple[PolicyAdoptionChange, ...]
    issues: tuple[SemanticIssue, ...]
    requires_question_confirmation: Literal[True] = True
    calculation_status: Literal['not_recalculated'] = 'not_recalculated'

    def digest(self):
        return canonical_sha256(self.model_dump(mode='json', by_alias=True))


class PolicyAdoptionQuestionChoice(SemanticModel):
    question_id: Identity
    metric_version: MetricVersionRef | None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def explained_choice(self):
        if not self.reason.strip():
            raise ValueError('显式问题选择必须说明原因')
        return self


PolicyAdoptionRequestId = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]


class PolicyAdoptionConfirmation(SemanticModel):
    request_id: PolicyAdoptionRequestId
    target_policy_version: PolicyVersionRef
    preview_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    question_choices: tuple[PolicyAdoptionQuestionChoice, ...] = Field(min_length=1, max_length=50)


def policy_adoption_id(parent_basis_id, request_id):
    return 'policy-adoption-' + canonical_sha256({'parentBasisId': parent_basis_id, 'requestId': request_id})


class BasisPolicyAdoptionReceipt(SemanticModel):
    kind: Literal['policy_adoption'] = 'policy_adoption'
    receipt_id: Identity
    basis_id: Identity
    target_run_id: RunIdentity
    target_basis_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    report_revision: Literal['policy-adoption-registration'] = 'policy-adoption-registration'
    parent_run_id: RunIdentity
    parent_basis_id: Identity
    parent_basis_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    input_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmation: PolicyAdoptionConfirmation
    preview: PolicyAdoptionPreview
    selections: tuple[MetricSelection, ...]
    created_at: AwareDatetime

    @model_validator(mode='after')
    def confirmed_parent(self):
        expected = policy_adoption_id(self.parent_basis_id, self.confirmation.request_id)
        if (self.parent_basis_id == self.basis_id or self.parent_run_id == self.target_run_id
                or self.receipt_id != expected or self.target_run_id != expected
                or (self.parent_basis_id, self.parent_basis_hash) != (
                    self.preview.parent_basis_id, self.preview.parent_basis_hash)
                or self.confirmation.target_policy_version != self.preview.target_policy_version
                or self.confirmation.preview_hash != self.preview.digest()):
            raise ValueError('新依据必须绑定完整确认预检及独立父链')
        choices = {choice.question_id: choice for choice in self.confirmation.question_choices}
        selections = {selection.question_id: selection for selection in self.selections}
        if (len(choices) != len(self.confirmation.question_choices) or len(selections) != len(self.selections)
                or set(choices) != set(selections)):
            raise ValueError('确认问题与指标选择必须完整且唯一')
        for question_id, selection in selections.items():
            chosen = choices[question_id].metric_version
            if selection.status == 'ambiguous':
                raise ValueError('明确确认不能保留歧义选择')
            if chosen is None:
                if selection.status != 'unavailable' or selection.candidates:
                    raise ValueError('未选择问题不能标为已解决或自动补候选')
                continue
            if chosen not in tuple(candidate.metric_version for candidate in selection.candidates):
                raise ValueError('显式版本必须保留在已核对候选中')
            if selection.status == 'resolved' and (selection.selected != chosen or selection.source != 'explicit'):
                raise ValueError('指标选择不能覆盖明确确认')
        return self
