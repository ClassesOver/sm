"""发布集合和检索回执；无命中、不可用、撤销分别表达。"""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ..semantics.models import Identity, Period, Revision, SemanticModel
from .index import IndexBuildReceipt, IndexHit
from .models import BusinessDocumentInput, BusinessObjectRef


class DocumentRevisionRef(SemanticModel):
    document_id: Identity
    revision: Revision


class ReleasedDocument(SemanticModel):
    reference: DocumentRevisionRef
    metadata: BusinessDocumentInput
    recorded_at: AwareDatetime


class EvidenceRelease(SemanticModel):
    release_id: Identity
    scope_id: Identity
    request_id: Identity
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["rule_evidence", "background"]
    documents: tuple[ReleasedDocument, ...] = Field(min_length=1, max_length=200)
    index_receipt: IndexBuildReceipt
    published_at: AwareDatetime


class EvidenceQuery(SemanticModel):
    query: str = Field(min_length=1, max_length=4000)
    metric_ids: tuple[Identity, ...] = Field(default=(), max_length=200)
    project_ids: tuple[Identity, ...] = Field(default=(), max_length=200)
    period: Period
    knowledge_as_of: AwareDatetime
    limit: int = Field(default=5, ge=1, le=5, strict=True)


class EvidenceHit(IndexHit):
    title: str
    role: Literal["rule_evidence", "background"]
    recorded_at: AwareDatetime
    event_time: date | None = None
    applies_to: tuple[BusinessObjectRef, ...] = Field(default=(), max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None


class EvidenceSearchReceipt(SemanticModel):
    release_id: Identity
    request: EvidenceQuery
    status: Literal["matched", "no_match", "unavailable", "inapplicable", "revoked"]
    hits: tuple[EvidenceHit, ...] = Field(default=(), max_length=5)
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def result_state(self):
        if bool(self.hits) != (self.status == "matched"):
            raise ValueError("检索命中必须与状态一致")
        if self.status in ("unavailable", "inapplicable", "revoked") and not self.issue_codes:
            raise ValueError("不可用依据必须说明原因")
        return self


def is_applicable(document: ReleasedDocument, scope_id: str, request: EvidenceQuery) -> bool:
    metadata = document.metadata
    if document.recorded_at > request.knowledge_as_of:
        return False
    if metadata.valid_from is not None and metadata.valid_from > request.period.start:
        return False
    if metadata.valid_to is not None and metadata.valid_to < request.period.end:
        return False
    if metadata.event_time is not None and (metadata.event_time >= request.period.end or metadata.event_time > request.knowledge_as_of.date()):
        return False
    groups = {kind: {ref.id for ref in metadata.applies_to if ref.kind == kind}
              for kind in ("metric", "project", "organization")}
    return (not groups["metric"] or bool(groups["metric"] & set(request.metric_ids))) and (
        not groups["project"] or bool(groups["project"] & set(request.project_ids))) and (
        not groups["organization"] or scope_id in groups["organization"])


class ReportEvidenceSearchReceipt(SemanticModel):
    """绑定报告依据的检索结果；未配置背景不能借用制度集合。"""
    basis_id: Identity
    kind: Literal['rule_evidence', 'background']
    search: EvidenceSearchReceipt | None = None
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode='after')
    def missing_release(self):
        if self.search is None and not self.issue_codes:
            raise ValueError('缺少发布集合必须说明原因')
        return self
