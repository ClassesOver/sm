"""管理员对精确回归预期的显式签认；不等同于整份报告批准或问题关闭。"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ..business_knowledge.models import DocumentLocator
from ..trace.contracts_v1 import canonical_sha256
from .models import CorrectedVersionRef, Identity, Revision, SemanticModel


class ExpectationSource(SemanticModel):
    regression_receipt_id: Identity
    document_id: Identity
    revision: Revision
    locator: DocumentLocator
    quote: str = Field(min_length=1, max_length=10000)


class IssueBusinessApprovalRequest(SemanticModel):
    request_id: Identity
    expected_issue_version: int = Field(ge=1, strict=True)
    decision: Literal['approve_expected_values']
    regression_receipt_ids: tuple[Identity, ...] = Field(min_length=1, max_length=50)
    sources: tuple[ExpectationSource, ...] = Field(min_length=1, max_length=100)
    approval_reason: str = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def complete_sources(self):
        keys = [(item.regression_receipt_id, item.document_id, item.revision, item.locator.model_dump_json()) for item in self.sources]
        if (not self.approval_reason.strip() or any(not item.quote.strip() for item in self.sources)
                or len(set(self.regression_receipt_ids)) != len(self.regression_receipt_ids)
                or len(set(keys)) != len(keys)
                or set(self.regression_receipt_ids) != {item.regression_receipt_id for item in self.sources}):
            raise ValueError('每条回归须有明确原文来源及签认理由，不得重复或附带其他回归')
        return self


class ApprovedRegressionRef(SemanticModel):
    receipt_id: Identity
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class ApprovedSourceSnapshot(SemanticModel):
    document_id: Identity
    revision: Revision
    state_version: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    size: int = Field(ge=1, strict=True)
    metadata_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    parse_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


def approval_receipt_id(basis_id, issue_id, request_id):
    return 'issue-approval-' + canonical_sha256({'basisId': basis_id, 'issueId': issue_id, 'requestId': request_id})


class BasisIssueBusinessApprovalReceipt(SemanticModel):
    kind: Literal['issue_business_approval'] = 'issue_business_approval'
    receipt_id: Identity
    basis_id: Identity
    report_revision: Literal['issue-business-approval'] = 'issue-business-approval'
    issue_id: Identity
    request: IssueBusinessApprovalRequest
    corrected_versions: tuple[CorrectedVersionRef, ...] = Field(min_length=1, max_length=50)
    regressions: tuple[ApprovedRegressionRef, ...] = Field(min_length=1, max_length=50)
    sources: tuple[ApprovedSourceSnapshot, ...] = Field(min_length=1, max_length=100)
    approved_by_account_id: int = Field(ge=1, strict=True)
    approved_by_username: str = Field(min_length=1, max_length=128)
    approval_scope: Literal['regression_expected_values'] = 'regression_expected_values'
    business_approval: Literal['explicitly_approved'] = 'explicitly_approved'
    created_at: AwareDatetime

    @model_validator(mode='after')
    def bound_approval(self):
        if (self.receipt_id != approval_receipt_id(self.basis_id, self.issue_id, self.request.request_id)
                or tuple(item.receipt_id for item in self.regressions) != self.request.regression_receipt_ids
                or {(item.document_id, item.revision) for item in self.sources}
                    != {(item.document_id, item.revision) for item in self.request.sources}):
            raise ValueError('签认必须绑定本问题、精确回归和全部原文来源')
        return self
