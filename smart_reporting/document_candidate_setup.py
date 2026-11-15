"""Explicit, opt-in assembly of the existing Word candidate service.

No format is enabled merely by importing this module. The host must supply
its authenticated scope resolver and the existing Word assistant.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from .document_candidate_contract import (
    DocumentAdapterRegistry, DocumentCandidateAdapter, DocumentFormat, DocumentScope,
)
from .document_candidate_gateway import DocumentCandidateGateway
from .document_candidate_word_adapter import ChannelWordCandidateAdapter
from .report_channel_api import ConnectorIdentity
from .report_channel_word import ReportChannelWordAssistant


def build_word_document_gateway(
    word: ReportChannelWordAssistant,
    resolve_scope: Callable[[str, ConnectorIdentity], Awaitable[DocumentScope | None]],
    identity_for_scope: Callable[[DocumentScope], Awaitable[ConnectorIdentity | None]],
) -> DocumentCandidateGateway:
    """Register DOCX only; other formats remain disabled until implemented."""
    registry = DocumentAdapterRegistry()
    registry.register(ChannelWordCandidateAdapter(word, identity_for_scope))
    return DocumentCandidateGateway(registry, resolve_scope)


def build_document_gateway(
    resolve_scope: Callable[[str, ConnectorIdentity], Awaitable[DocumentScope | None]],
    *,
    docx: DocumentCandidateAdapter | None = None,
    xlsx: DocumentCandidateAdapter | None = None,
    pptx: DocumentCandidateAdapter | None = None,
    pdf: DocumentCandidateAdapter | None = None,
) -> DocumentCandidateGateway:
    """Register only explicitly supplied adapters, never placeholder engines.

    Each adapter must have its own real host authorization/source validators.
    Missing formats remain unavailable (HTTP 409 at the channel API).
    """
    registry = DocumentAdapterRegistry()
    for expected, adapter in (
        (DocumentFormat.DOCX, docx),
        (DocumentFormat.XLSX, xlsx),
        (DocumentFormat.PPTX, pptx),
        (DocumentFormat.PDF, pdf),
    ):
        if adapter is not None:
            if adapter.format != expected:
                raise ValueError("document_adapter_format_mismatch")
            registry.register(adapter)
    return DocumentCandidateGateway(registry, resolve_scope)
