from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SourceDraftInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default='starrocks', alias='type', pattern='^starrocks$')
    database: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z_][A-Za-z0-9_$]*$')
    dsn: SecretStr | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    metadata_version_id: str | None = Field(default=None, alias='metadataVersionId', max_length=64)

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('数据源名称不能为空。')
        return value

    @field_validator('database')
    @classmethod
    def normalize_database(cls, value: str) -> str:
        return value.lower()


@dataclass(frozen=True)
class SourceDraft:
    source_id: str
    scope_id: str
    version: int
    name: str
    source_type: str
    database: str
    credential_ref: str
    metadata_version_id: str | None


@dataclass(frozen=True)
class SourceVersion:
    source_id: str
    revision: int
    content_hash: str
    published_at: datetime
    name: str
    source_type: str
    database: str
    metadata_version_id: str | None
    credential_revision: int

    def public_dict(self) -> dict[str, Any]:
        return {'sourceId': self.source_id, 'revision': self.revision,
                'contentHash': self.content_hash, 'publishedAt': self.published_at.isoformat(),
                'name': self.name, 'type': self.source_type, 'database': self.database,
                'metadataVersionId': self.metadata_version_id}
