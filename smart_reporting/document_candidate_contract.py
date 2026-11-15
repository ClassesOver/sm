"""Shared, fail-closed contract for document candidate adapters.

This module does not grant edit access or implement format-specific engines.
The host must resolve the document and revision from an authenticated grant.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
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
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.channel, self.grant, self.document_id, self.revision)
        ):
            raise ValueError("document_scope_incomplete")
        try:
            DocumentFormat(self.format)
        except (TypeError, ValueError) as exc:
            raise ValueError("document_format_invalid") from exc
        if not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.source_sha256
        ):
            raise ValueError("document_source_digest_invalid")


@dataclass(frozen=True)
class DocumentCandidateRequest:
    scope: DocumentScope
    request_id: str
    instruction: str
    selection: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not 1 <= len(self.request_id) <= 128 or not self.request_id.isascii() or not all(
            c.isalnum() or c in "-_" for c in self.request_id
        ):
            raise ValueError("document_request_id_invalid")
        if not isinstance(self.instruction, str) or not self.instruction.strip() or len(self.instruction) > 2000:
            raise ValueError("document_instruction_invalid")
        if not isinstance(self.selection, (tuple, list)) or not self.selection or len(self.selection) > 100 or any(
            not isinstance(item, dict) or not item for item in self.selection
        ):
            raise ValueError("document_selection_invalid")
        # Adapter fingerprints sort JSON object keys. Validate that keys are
        # strings throughout nested selections and that canonical serialization
        # is safe before any async adapter work starts.
        pending: list[Any] = list(self.selection)
        seen_containers: set[int] = set()
        while pending:
            value = pending.pop()
            if isinstance(value, (dict, tuple, list)):
                if id(value) in seen_containers:
                    continue
                seen_containers.add(id(value))
                if isinstance(value, dict):
                    if any(not isinstance(key, str) for key in value):
                        raise ValueError("document_selection_invalid")
                    pending.extend(value.values())
                else:
                    pending.extend(value)
        try:
            encoded = json.dumps(
                self.selection, allow_nan=False, ensure_ascii=False, sort_keys=True,
            )
            if len(encoded.encode("utf-8")) > 65536:
                raise ValueError("document_selection_invalid")
        except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
            raise ValueError("document_selection_invalid") from exc
        # Frozen dataclasses do not freeze nested caller-owned dictionaries.
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
