"""明确的纠错关闭处理，独立于报告验收与下载许可。"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ..trace.contracts_v1 import canonical_sha256
from .issue_approval import ApprovedRegressionRef
from .models import CorrectedVersionRef, Identity, SemanticModel


class IssueResolutionRequest(SemanticModel):
    request_id: Identity
    expected_issue_version: int = Field(ge=1, strict=True)
    regression_receipt_ids: tuple[Identity, ...] = Field(min_length=1, max_length=50)
    business_approval_request_id: Identity
    mode: Literal['recalculated', 'not_recalculated']
    decision_reason: str = Field(min_length=1, max_length=10000)
    not_recalculated_reason: str = Field(default='', max_length=2000)
    original_report_unchanged: Literal[True]

    @model_validator(mode='after')
    def explicit_disposition(self):
        if (not self.decision_reason.strip()
                or len(set(self.regression_receipt_ids)) != len(self.regression_receipt_ids)
                or (self.mode == 'not_recalculated') != bool(self.not_recalculated_reason.strip())
                or self.mode == 'recalculated' and self.not_recalculated_reason):
            raise ValueError('关闭须明确裁定，不重算须说明理由，原报告必须保留')
        return self


class ResolutionOriginalSnapshot(SemanticModel):
    document_id: Identity
    revision: int = Field(ge=1, strict=True)
    state_version: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    size: int = Field(ge=1, strict=True)
    metadata_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResolutionArtifactSnapshot(SemanticModel):
    format: Literal['pdf', 'docx', 'pptx', 'xlsx']
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    size: int = Field(ge=1, strict=True)


class ResolutionDeliverySnapshot(SemanticModel):
    regression_receipt_id: Identity
    target_run_id: Identity
    target_basis_id: Identity
    adoption_receipt_id: Identity
    registration_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    output_revision: int = Field(ge=1, strict=True)
    validation_passed: bool
    artifacts: tuple[ResolutionArtifactSnapshot, ...] = Field(min_length=1, max_length=4)


class ResolutionEvidence(SemanticModel):
    checked_at: AwareDatetime
    regression_evidence_ready: Literal[True]
    original_evidence_ready: Literal[True]
    business_approval_ready: Literal[True]
    delivery_ready: bool
    fact_presentation_ready: bool
    approval_receipt_id: Identity
    approval_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    regressions: tuple[ApprovedRegressionRef, ...] = Field(min_length=1, max_length=50)
    originals: tuple[ResolutionOriginalSnapshot, ...] = Field(min_length=1)
    deliveries: tuple[ResolutionDeliverySnapshot, ...] = Field(max_length=50)
    new_report_revision: Identity | None = None


def resolution_receipt_id(basis_id, issue_id, request_id):
    return 'issue-resolution-' + canonical_sha256({'basisId': basis_id, 'issueId': issue_id, 'requestId': request_id})


class BasisIssueResolutionReceipt(SemanticModel):
    kind: Literal['issue_resolution'] = 'issue_resolution'
    receipt_id: Identity
    basis_id: Identity
    report_revision: Literal['issue-resolution'] = 'issue-resolution'
    issue_id: Identity
    request: IssueResolutionRequest
    corrected_versions: tuple[CorrectedVersionRef, ...] = Field(min_length=1, max_length=50)
    evidence: ResolutionEvidence
    resolved_issue_version: int = Field(ge=2, strict=True)
    resolved_by_account_id: int = Field(ge=1, strict=True)
    resolved_by_username: str = Field(min_length=1, max_length=128)
    issue_closed: Literal[True] = True
    created_at: AwareDatetime

    @model_validator(mode='after')
    def bound_resolution(self):
        if (self.receipt_id != resolution_receipt_id(self.basis_id, self.issue_id, self.request.request_id)
                or self.resolved_issue_version != self.request.expected_issue_version + 1
                or tuple(item.receipt_id for item in self.evidence.regressions) != self.request.regression_receipt_ids
                or self.request.mode == 'recalculated' and not (self.evidence.delivery_ready
                    and self.evidence.fact_presentation_ready and self.evidence.new_report_revision
                    and len(self.evidence.deliveries) == len(self.request.regression_receipt_ids))
                or self.request.mode == 'not_recalculated' and self.evidence.new_report_revision is not None):
            raise ValueError('关闭回执须绑定精确问题、回归及本次处理方式')
        return self
