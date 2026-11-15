"""Shared, fail-closed contract for document candidate adapters.

This module does not grant edit access or implement format-specific engines.
The host must resolve the document and revision from an authenticated grant.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class DocumentFormat(StrEnum):
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    PDF = "pdf"


@dataclass(frozen=True)
class DocumentScope:
    channel: str
    grant: str
    document_id: str
    revision: str
    source_sha256: str
    format: DocumentFormat

    def __post_init__(self) -> None:
        if not all((self.channel, self.grant, self.document_id, self.revision)):
            raise ValueError("document_scope_incomplete")
        if len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("document_source_digest_invalid")


@dataclass(frozen=True)
class DocumentCandidateRequest:
    scope: DocumentScope
    request_id: str
    instruction: str
    selection: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.request_id) <= 128 or not self.request_id.isascii() or not all(
            c.isalnum() or c in "-_" for c in self.request_id
        ):
            raise ValueError("document_request_id_invalid")
        if not self.instruction.strip() or len(self.instruction) > 2000:
            raise ValueError("document_instruction_invalid")
        if not self.selection or len(self.selection) > 100 or any(
            not isinstance(item, dict) or not item for item in self.selection
        ):
            raise ValueError("document_selection_invalid")
        # Frozen dataclasses do not freeze nested caller-owned dictionaries.
        # Snapshot selections so a caller cannot change targets during an await.
        object.__setattr__(self, "selection", tuple(deepcopy(item) for item in self.selection))


class DocumentCandidateAdapter(Protocol):
    format: DocumentFormat

    async def prepare(self, request: DocumentCandidateRequest) -> str:
        """Return an opaque task ID; never save or accept a candidate."""

    async def status(self, scope: DocumentScope, task_id: str) -> dict[str, Any]:
        """Return a sanitized task status only after host authorization."""


class DocumentAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[DocumentFormat, DocumentCandidateAdapter] = {}

    def register(self, adapter: DocumentCandidateAdapter) -> None:
        fmt = DocumentFormat(adapter.format)
        if fmt in self._adapters:
            raise ValueError("document_adapter_already_registered")
        self._adapters[fmt] = adapter

    def require(self, fmt: DocumentFormat) -> DocumentCandidateAdapter:
        try:
            return self._adapters[DocumentFormat(fmt)]
        except (KeyError, ValueError) as exc:
            raise ValueError("document_adapter_unavailable") from exc
