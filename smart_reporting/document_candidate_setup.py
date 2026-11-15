"""Explicit, opt-in assembly of the existing Word candidate service.

No format is enabled merely by importing this module. The host must supply
its authenticated scope resolver and the existing Word assistant.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from .document_candidate_contract import DocumentAdapterRegistry, DocumentScope
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
