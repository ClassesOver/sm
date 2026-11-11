"""逐声明引用只保存不可变原文身份和语义关系，不把原文复制到修订索引。"""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from ..semantics.models import Identity, Period, Revision, SemanticModel
from .models import DocumentLocator


class KnowledgeReference(SemanticModel):
    evidence_id: Identity
    basis_id: Identity
    section_code: Identity
    receipt_id: Identity
    release_id: Identity
    document_id: Identity
    document_revision: Revision
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    locator: DocumentLocator
    quote_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    role: Literal['rule_evidence', 'background']


class KnowledgeSourcePresentation(SemanticModel):
    """当前授权的导出摘要；不可用时不得携带历史标题或原文。"""

    subject_id: Identity
    evidence_id: Identity
    available: StrictBool
    support_status: Literal['supported', 'unverified', 'conflicted']
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_revision: Revision | None = None
    role: Literal['rule_evidence', 'background'] | None = None
    locator: DocumentLocator | None = None
    quote: str | None = Field(default=None, min_length=1, max_length=1200)
    period: Period | None = None
    recorded_at: AwareDatetime | None = None
    event_time: date | None = None
    issue_codes: tuple[Identity, ...] = Field(default=(), max_length=20)

    @model_validator(mode='after')
    def authorized_content(self):
        fields = (self.title, self.document_revision, self.role, self.locator,
            self.quote, self.period, self.recorded_at)
        if self.available and any(value is None for value in fields):
            raise ValueError('可用知识摘要必须具有完整原文身份和定位')
        if not self.available and (any(value is not None for value in fields)
                or self.event_time is not None or not self.issue_codes or self.support_status != 'unverified'):
            raise ValueError('不可用知识摘要只能展示未核验状态和具体原因')
        return self


class KnowledgeSourceSpan(SemanticModel):
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class KnowledgeRelation(SemanticModel):
    evidence_id: Identity
    relationship: Literal['supports', 'contradicts', 'irrelevant', 'unknown']
    explanation_type: Literal['causal', 'interpretation', 'recommendation', 'unknown'] = 'unknown'
    claim_evidence: tuple[str, ...] = Field(default=(), max_length=8)
    source_evidence: tuple[str, ...] = Field(default=(), max_length=8)
    source_spans: tuple[KnowledgeSourceSpan, ...] = Field(default=(), max_length=8)
