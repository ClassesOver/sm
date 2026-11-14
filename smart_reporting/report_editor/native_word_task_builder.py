"""Unregistered internal Word input builder; never submits tasks or starts providers.

The caller is trusted server policy supplying the task scope and an already
registered session reference. This is not an HTTP/MCP authentication endpoint.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ..task_execution.models import TaskExecutionScope
from ..task_execution.native_word_contracts import (
    NativeWordTaskInput,
    canonical_bytes,
    canonical_digest,
    normalize_word_input,
)
from .native_word_ai import selected_word_objects


def _invalid():
    # Do not expose session references, source text, paths or underlying errors.
    return ValueError('native_word_builder_invalid')


def _session_identity(session) -> bytes:
    return canonical_bytes({
        'reportId': session.report_id, 'revision': session.revision,
        'workflowRunId': session.workflow_run_id, 'contextSha256': session.context_sha256,
        'expiresAt': session.expires_at.isoformat(), 'capabilities': session.capabilities,
    })


class NativeWordTaskInputBuilder:
    """Return private typed input only; current authority must be checked again later."""
    def __init__(self, grants: Any, editor: Any):
        self.grants, self.editor = grants, editor

    async def build(self, *, scope: TaskExecutionScope, server_session_reference: str,
                    instruction: str, expected_sha256: str, operations: list[dict[str, Any]],
                    selection: list[dict[str, str]]) -> NativeWordTaskInput:
        try:
            return await self._build(scope=scope, server_session_reference=server_session_reference,
                instruction=instruction, expected_sha256=expected_sha256,
                operations=operations, selection=selection)
        except Exception:
            raise _invalid() from None

    async def _build(self, *, scope, server_session_reference, instruction, expected_sha256,
                     operations, selection):
        # All mutable caller input is bounded/copied before the first suspension.
        if (not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000
                or not isinstance(server_session_reference, str) or len(server_session_reference) != 64
                or any(c not in '0123456789abcdef' for c in server_session_reference)
                or not isinstance(scope, TaskExecutionScope)):
            raise _invalid()
        encoded = canonical_bytes(operations)
        if len(encoded) > 12 * 1024 * 1024:
            raise _invalid()
        base = json.loads(encoded)
        selected_request = json.loads(canonical_bytes(selection))
        if (not isinstance(base, list) or len(base) > 500 or any(not isinstance(op, dict) for op in base)
                or not isinstance(selected_request, list) or not 1 <= len(selected_request) <= 100
                or any(not isinstance(item, dict) or set(item) != {'blockId'}
                       or not isinstance(item['blockId'], str) or not 1 <= len(item['blockId']) <= 256
                       for item in selected_request)):
            raise _invalid()
        session = await self.grants.lookup_registered_session(server_session_reference)
        session_identity = _session_identity(session)
        context = await self.editor.context_for_session(session)
        context_identity = canonical_bytes(context.model_dump(mode='json', by_alias=True))
        if (context.format != 'docx' or context.scope.user_id != scope.owner_user_id
                or context.scope.thread_id != scope.thread_id
                or expected_sha256 != context.source_file.sha256):
            raise _invalid()
        self.editor.require_enabled('docx')
        original = await self.editor.preview(context, expected_sha256=expected_sha256, operations=[])
        targets = selected_word_objects(original['model'], base, selected_request)
        if any(item.get('type') != 'paragraph' or item.get('cellId') or item.get('selectionKind')
               for item in targets):
            raise _invalid()
        await self.editor.preview(context, expected_sha256=expected_sha256, operations=base)
        # Reuse the existing exact full-draft snapshot definition, not a new hash convention.
        from .native_ai import NativeAIService

        snapshot = NativeAIService._snapshot(context, base)
        fields = ('blockId', 'type', 'text', 'expectedObjectSha256', 'allowedOperations',
                  'before', 'after', 'styleChanges', 'draftOperations')
        paragraphs = [{name: target[name] for name in fields} for target in targets]
        payload = {
            'version': 1, 'instructionSha256': hashlib.sha256(instruction.encode()).hexdigest(),
            'binding': {'taskId': scope.external_run_id,
                'scope': context.scope.model_dump(mode='json', by_alias=True),
                'documentId': context.document_id, 'revision': context.revision, 'format': 'docx',
                'contextSha256': context.digest(), 'sourceSha256': context.source_file.sha256,
                'snapshotSha256': snapshot, 'draftOperationsSha256': canonical_digest(base),
                'selectionSha256': canonical_digest(paragraphs),
                'serverSessionReference': server_session_reference},
            'selectedParagraphs': paragraphs,
        }
        parsed, _, _ = normalize_word_input(payload)
        final_session = await self.grants.lookup_registered_session(server_session_reference)
        final_identity = _session_identity(final_session)
        final_context = await self.editor.context_for_session(final_session)
        if (final_identity != session_identity
                or _session_identity(final_session) != session_identity
                or canonical_bytes(final_context.model_dump(mode='json', by_alias=True)) != context_identity):
            raise _invalid()
        # Context recovery also suspends. Re-observe registry after it, and do not
        # rely on lookup's pre-await timestamp for validity at return. This remains
        # observed validity, not cross-service linearizable revocation.
        last_session = await self.grants.lookup_registered_session(server_session_reference)
        if (_session_identity(last_session) != session_identity
                or last_session.expires_at <= datetime.now(UTC)):
            raise _invalid()
        # A private DTO, not a generic snapshot/result or externally serializable response.
        return normalize_word_input(parsed)[0]
