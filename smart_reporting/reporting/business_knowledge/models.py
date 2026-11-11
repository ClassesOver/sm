"""原文定位与解析回执，不对外传递服务器路径。"""

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ..contract import SHA256_PATTERN
from ..semantics.models import Identity, SemanticModel

IngestionStatus = Literal["queued", "running", "parsed", "failed", "ready", "needs_transcription"]


class BusinessObjectRef(SemanticModel):
    kind: Literal["metric", "project", "organization"]
    id: Identity


class BusinessDocumentInput(SemanticModel):
    id: Identity
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["rule_evidence", "background"]
    valid_from: date | None = None
    valid_to: date | None = None
    event_time: date | None = None
    applies_to: tuple[BusinessObjectRef, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def applicable_period(self) -> "BusinessDocumentInput":
        if not self.title.strip():
            raise ValueError("文档标题不能为空白")
        if self.valid_from is not None and self.valid_to is not None and self.valid_from >= self.valid_to:
            raise ValueError("文档适用期必须为非空半开区间")
        return self


class DocumentReceipt(SemanticModel):
    document_id: Identity
    revision: int = Field(ge=1, strict=True)
    version: int = Field(ge=1, strict=True)
    job_id: Identity
    status: IngestionStatus
    issue_codes: tuple[Identity, ...] = ()


class IngestionReceipt(SemanticModel):
    job_id: Identity
    document_id: Identity
    revision: int = Field(ge=1, strict=True)
    attempt: int = Field(ge=0, strict=True)
    status: IngestionStatus
    issue_codes: tuple[Identity, ...] = ()


class IngestionLease(SemanticModel):
    scope_id: Identity
    job_id: Identity
    document_id: Identity
    revision: int = Field(ge=1, strict=True)
    attempt: int = Field(ge=1, strict=True)
    lease_owner: Identity
    lease_until: AwareDatetime


class DocumentLocator(SemanticModel):
    kind: Literal["text_lines", "pdf_page", "docx_paragraph", "docx_table_cell"]
    page: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    table: int | None = Field(default=None, ge=1)
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def exact_coordinates(self) -> "DocumentLocator":
        required = {
            "text_lines": {"line_start", "line_end"}, "pdf_page": {"page"},
            "docx_paragraph": {"paragraph"}, "docx_table_cell": {"table", "row", "column"},
        }[self.kind]
        coordinates = {name for name in ("page", "line_start", "line_end", "paragraph", "table", "row", "column") if getattr(self, name) is not None}
        if coordinates != required:
            raise ValueError("原文定位坐标与文档类型不一致")
        if self.kind == "text_lines" and self.line_start > self.line_end:
            raise ValueError("行定位区间倒置")
        return self


class LocatedFragment(SemanticModel):
    locator: DocumentLocator
    text: str = Field(min_length=1, max_length=2000000)


class ParsedDocument(SemanticModel):
    original_hash: str = Field(pattern=SHA256_PATTERN)
    parser_identity: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    status: Literal["parsed", "needs_transcription"]
    fragments: tuple[LocatedFragment, ...]
    issue_codes: tuple[Identity, ...] = ()

    @model_validator(mode="after")
    def parsed_content(self) -> "ParsedDocument":
        if self.status == "parsed" and not self.fragments:
            raise ValueError("空解析不能当成成功")
        if self.status == "needs_transcription" and not self.issue_codes:
            raise ValueError("需要转录必须说明原因")
        if sum(len(fragment.text) for fragment in self.fragments) > 2000000:
            raise ValueError("text_limit")
        return self
