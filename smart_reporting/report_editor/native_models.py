"""独立原生文件身份；不改变 Markdown 报告上下文或其授权摘要。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from ..reporting.contract import SHA256_PATTERN
from ..reporting.delivery.artifacts_v1 import ArtifactFile

NativeFormat = Literal["docx", "pdf", "xlsx", "pptx"]
NativeMedia = Literal[
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
]
NATIVE_MEDIA: dict[NativeFormat, NativeMedia] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
NATIVE_ARTIFACT_KEYS: dict[NativeFormat, str] = {
    "docx": "word", "pdf": "pdf", "xlsx": "xlsx", "pptx": "pptx"
}
NATIVE_ARTIFACT_MEDIA = {key: NATIVE_MEDIA[format] for format, key in NATIVE_ARTIFACT_KEYS.items()}
NativeOrigin = Literal["report", "upload", "derived"]


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class NativeScope(NativeModel):
    database: str = Field(min_length=1, max_length=256)
    company_id: str = Field(alias="companyId", min_length=1, max_length=256)
    user_id: str = Field(alias="userId", min_length=1, max_length=256)
    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)


class NativeSource(NativeModel):
    format: NativeFormat
    origin: NativeOrigin
    source_file: ArtifactFile = Field(alias="sourceFile")
    display_name: str | None = Field(default=None, alias="displayName", min_length=1, max_length=160)
    report_id: str | None = Field(default=None, alias="reportId", min_length=1)
    workflow_run_id: str | None = Field(default=None, alias="workflowRunId", min_length=1)
    revision: int | None = Field(default=None, ge=1)
    report_context_sha256: str | None = Field(default=None, alias='reportContextSha256', pattern=SHA256_PATTERN)
    parent_document_id: str | None = Field(default=None, alias="parentDocumentId", min_length=1, max_length=256)
    parent_revision: int | None = Field(default=None, alias="parentRevision", ge=1)
    parent_sha256: str | None = Field(default=None, alias="parentSha256", pattern=SHA256_PATTERN)

    @model_serializer(mode="wrap")
    def serialize_source(self, handler):
        result = handler(self)
        if self.display_name is None:
            result.pop('displayName', None)
            result.pop('display_name', None)
        if self.report_context_sha256 is None:
            result.pop('reportContextSha256', None)
            result.pop('report_context_sha256', None)
        # 旧来源的创建幂等键依赖完整序列化；新增追溯字段不能改变旧请求摘要。
        if self.origin != "derived":
            for key in ("parent_document_id", "parent_revision", "parent_sha256", "parentDocumentId", "parentRevision", "parentSha256"):
                result.pop(key, None)
        return result

    @model_validator(mode="after")
    def validate_identity(self) -> NativeSource:
        expected = NATIVE_MEDIA[self.format]
        if self.source_file.media_type != expected:
            raise ValueError("原生格式与来源文件类型不一致")
        identity = (self.report_id, self.workflow_run_id, self.revision)
        if self.origin == "report" and any(value is None for value in identity):
            raise ValueError("报告来源必须携带完整报告身份")
        if self.origin == "upload" and any(value is not None for value in identity):
            raise ValueError("上传来源不能伪造报告身份")
        parent = (self.parent_document_id, self.parent_revision, self.parent_sha256)
        if self.origin == "derived":
            if any(value is None for value in parent) or any(value is not None for value in identity):
                raise ValueError("派生来源必须绑定父文档身份，不能伪造报告来源")
        elif any(value is not None for value in parent):
            raise ValueError("只有派生来源可以携带父文档身份")
        return self


class NativeEditorContext(NativeModel):
    document_id: str = Field(alias="documentId", min_length=1, max_length=256)
    format: NativeFormat
    revision: int = Field(ge=1)
    scope: NativeScope
    source_file: ArtifactFile = Field(alias="sourceFile")
    display_name: str | None = Field(default=None, alias="displayName", min_length=1, max_length=160)
    origin: NativeOrigin
    parent_revision: int | None = Field(default=None, alias="parentRevision", ge=1)

    @model_serializer(mode="wrap")
    def serialize_context(self, handler):
        result = handler(self)
        if self.display_name is None:
            result.pop('displayName', None)
            result.pop('display_name', None)
        return result

    @model_validator(mode="after")
    def validate_file(self) -> NativeEditorContext:
        expected = NATIVE_MEDIA[self.format]
        if self.source_file.media_type != expected:
            raise ValueError("原生上下文文件类型不一致")
        if self.parent_revision is not None and self.parent_revision >= self.revision:
            raise ValueError("父修订必须早于当前修订")
        return self

    @property
    def report_id(self) -> str:
        return self.document_id

    @property
    def workflow_run_id(self) -> str:
        return f"native:{self.document_id}"

    def digest(self) -> str:
        return native_digest(
            {
                "kind": "native-editor-context:v1",
                "context": self.model_dump(mode="json", by_alias=True),
            }
        )


class EditorGrantContext(Protocol):
    @property
    def report_id(self) -> str: ...
    @property
    def workflow_run_id(self) -> str: ...
    @property
    def revision(self) -> int: ...
    def digest(self) -> str: ...


class NativeIssue(NativeModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(default="", max_length=2000)


class NativeValidation(NativeModel):
    ok: bool
    issues: tuple[NativeIssue, ...] = ()


class NativeArtifacts(NativeModel):
    word: ArtifactFile | None = None
    pdf: ArtifactFile | None = None
    xlsx: ArtifactFile | None = None
    pptx: ArtifactFile | None = None

    @model_validator(mode="after")
    def validate_types(self) -> NativeArtifacts:
        for format, key in NATIVE_ARTIFACT_KEYS.items():
            artifact = getattr(self, key)
            if artifact is not None and artifact.media_type != NATIVE_MEDIA[format]:
                raise ValueError(f"{format.upper()} 产物类型不一致")
        return self


class NativeDocument(NativeModel):
    document_id: str = Field(alias="documentId")
    scope: NativeScope
    owner_id: str = Field(alias="ownerId")
    source: NativeSource
    created_at: datetime = Field(alias="createdAt")
    next_revision: int = Field(alias="nextRevision", ge=2)


class NativeRevision(NativeModel):
    document_id: str = Field(alias="documentId")
    revision: int = Field(ge=1)
    scope: NativeScope
    parent_revision: int | None = Field(default=None, alias="parentRevision", ge=1)
    request_id: str = Field(alias="requestId", min_length=1, max_length=256)
    request_sha256: str = Field(alias="requestSha256", pattern=SHA256_PATTERN)
    note: str = Field(default="", max_length=200)
    status: Literal["reserved", "saved", "failed"]
    context: NativeEditorContext | None = None
    artifacts: NativeArtifacts = Field(default_factory=NativeArtifacts)
    validation: NativeValidation | None = None
    created_at: datetime = Field(alias="createdAt")
    failure_code: str | None = Field(default=None, alias="failureCode")


def native_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
