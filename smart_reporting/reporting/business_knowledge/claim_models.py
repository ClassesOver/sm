"""逐声明引用只保存不可变原文身份和语义关系，不把原文复制到修订索引。"""

from typing import Literal

from pydantic import Field, StrictInt

from ..semantics.models import Identity, Revision, SemanticModel
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
