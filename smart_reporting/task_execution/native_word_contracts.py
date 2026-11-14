"""Private, versioned Word task persistence values, never generic task output.

These DTOs do not authenticate callers or derive editor authority. Only the trusted
editor coordinator may build them after validating its grant/context/source/selection.
No Codex/provider/HTTP integration is registered here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_NATIVE_WORD_INPUT_BYTES = 256 * 1024
MAX_NATIVE_WORD_RECEIPT_BYTES = 512 * 1024
_SHA = r'^[0-9a-f]{64}$'


def canonical_bytes(value: Any) -> bytes:
    def check_keys(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError('native_word_json_invalid')
            for child in item.values():
                check_keys(child)
        elif isinstance(item, list | tuple):
            for child in item:
                check_keys(child)

    try:
        # json.dumps otherwise silently converts numeric object keys to strings,
        # producing the same digest for structurally different Python inputs.
        check_keys(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('native_word_json_invalid') from error


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class _WordValue(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, populate_by_name=True, hide_input_in_errors=True)

    @field_validator('version', mode='before', check_fields=False)
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError('native_word_version_invalid')
        return value


class NativeWordScope(_WordValue):
    """Persistence DTO of the existing NativeScope four-tuple, not a new grant."""
    database: str = Field(min_length=1, max_length=256)
    company_id: str = Field(alias='companyId', min_length=1, max_length=256)
    user_id: str = Field(alias='userId', min_length=1, max_length=256)
    thread_id: str = Field(alias='threadId', min_length=1, max_length=256)


class NativeWordTaskBinding(_WordValue):
    task_id: str = Field(alias='taskId', min_length=1, max_length=128)
    scope: NativeWordScope
    document_id: str = Field(alias='documentId', min_length=1, max_length=256)
    revision: int = Field(ge=1)
    format: Literal['docx']
    context_sha256: str = Field(alias='contextSha256', pattern=_SHA)
    source_sha256: str = Field(alias='sourceSha256', pattern=_SHA)
    snapshot_sha256: str = Field(alias='snapshotSha256', pattern=_SHA)
    draft_operations_sha256: str = Field(alias='draftOperationsSha256', pattern=_SHA)
    selection_sha256: str = Field(alias='selectionSha256', pattern=_SHA)
    server_session_reference: str = Field(alias='serverSessionReference', pattern=_SHA, repr=False)


class NativeWordParagraph(_WordValue):
    block_id: str = Field(alias='blockId', min_length=1, max_length=256)
    type: Literal['paragraph']
    text: str = Field(repr=False)
    expected_object_sha256: str = Field(alias='expectedObjectSha256', pattern=_SHA)
    allowed_operations: list[str] = Field(alias='allowedOperations', min_length=1, max_length=64)
    before: list[str] = Field(default_factory=list, repr=False)
    after: list[str] = Field(default_factory=list, repr=False)
    style_changes: list[dict[str, Any]] = Field(alias='styleChanges', default_factory=list, repr=False)
    draft_operations: list[dict[str, Any]] = Field(alias='draftOperations', default_factory=list, repr=False)


class NativeWordTaskInput(_WordValue):
    version: Literal[1]
    binding: NativeWordTaskBinding = Field(repr=False)
    instruction_sha256: str = Field(alias='instructionSha256', pattern=_SHA)
    selected_paragraphs: list[NativeWordParagraph] = Field(alias='selectedParagraphs', min_length=1, max_length=100, repr=False)

    @model_validator(mode='after')
    def validate_selection(self) -> NativeWordTaskInput:
        selected = [item.model_dump(mode='json', by_alias=True) for item in self.selected_paragraphs]
        if len({item['blockId'] for item in selected}) != len(selected):
            raise ValueError('native_word_selection_duplicate')
        if canonical_digest(selected) != self.binding.selection_sha256:
            raise ValueError('native_word_selection_digest_mismatch')
        return self


def normalize_word_input(value: NativeWordTaskInput | dict[str, Any]) -> tuple[NativeWordTaskInput, dict[str, Any], str]:
    payload = value.model_dump(mode='python', by_alias=True) if isinstance(value, NativeWordTaskInput) else value
    encoded = canonical_bytes(payload)
    if len(encoded) > MAX_NATIVE_WORD_INPUT_BYTES:
        raise ValueError('native_word_input_too_large')
    parsed = NativeWordTaskInput.model_validate_json(encoded)
    stored = parsed.model_dump(mode='json', by_alias=True)
    return parsed, stored, canonical_digest(stored)


def normalize_word_proposal(word_input: NativeWordTaskInput, proposal: dict[str, Any]) -> dict[str, Any]:
    # Reuse the existing Word schema and scope/operation validator. Lazy import keeps
    # task schema/status operations independent of editor app initialization.
    from ..report_editor.native_word_ai import NativeWordAIProposal, word_candidate

    model = NativeWordAIProposal.model_validate_json(canonical_bytes(proposal))
    selected = [item.model_dump(mode='json', by_alias=True) for item in word_input.selected_paragraphs]
    checked = word_candidate(model.engine_operations(), selected)
    return {'summary': model.summary, 'operations': [
        {'kind': item['kind'], 'arguments': {key: value for key, value in item.items() if key != 'kind'}}
        for item in checked]}


class NativeWordCommitOrigin(_WordValue):
    internal_run_id: str = Field(alias='internalRunId', min_length=1, max_length=128)
    attempt_no: int = Field(alias='attemptNo', ge=0)
    lease_owner: str = Field(alias='leaseOwner', min_length=1, max_length=128)
    lease_epoch: int = Field(alias='leaseEpoch', ge=1)
    committed_at: AwareDatetime = Field(alias='committedAt')


class NativeWordCandidateReceipt(_WordValue):
    version: Literal[1]
    task_id: str = Field(alias='taskId', min_length=1, max_length=128)
    input_sha256: str = Field(alias='inputSha256', pattern=_SHA)
    candidate_sha256: str = Field(alias='candidateSha256', pattern=_SHA)
    proposal: dict[str, Any] = Field(repr=False)
    origin_commit: NativeWordCommitOrigin = Field(alias='originCommit', repr=False)
    receipt_sha256: str = Field(alias='receiptSha256', pattern=_SHA)


def candidate_digest(input_sha256: str, proposal: dict[str, Any]) -> str:
    return canonical_digest({'inputSha256': input_sha256, 'proposal': proposal})


def normalize_word_receipt(value: dict[str, Any], *, word_input: NativeWordTaskInput,
                           input_sha256: str, candidate_sha256: str) -> dict[str, Any]:
    encoded = canonical_bytes(value)
    if len(encoded) > MAX_NATIVE_WORD_RECEIPT_BYTES:
        raise ValueError('native_word_receipt_too_large')
    parsed = NativeWordCandidateReceipt.model_validate_json(encoded)
    stored = parsed.model_dump(mode='json', by_alias=True)
    unsigned = {key: item for key, item in stored.items() if key != 'receiptSha256'}
    normalized = normalize_word_proposal(word_input, parsed.proposal)
    if (parsed.task_id != word_input.binding.task_id or parsed.input_sha256 != input_sha256
            or parsed.candidate_sha256 != candidate_sha256
            or normalized != parsed.proposal
            or candidate_digest(input_sha256, normalized) != candidate_sha256
            or canonical_digest(unsigned) != parsed.receipt_sha256):
        raise ValueError('native_word_receipt_integrity_mismatch')
    return stored


def word_finish_reference(receipt: dict[str, Any]) -> dict[str, Any]:
    """Small reference attached to existing finish receipt; not an acceptance grant."""
    return {'nativeWordReceiptVersion': 1, 'nativeWordCandidateSha256': receipt['candidateSha256'],
            'nativeWordInputSha256': receipt['inputSha256']}


def validate_word_finish_reference(finish_receipt: Any, receipt: dict[str, Any]) -> None:
    if (not isinstance(finish_receipt, dict)
            or type(finish_receipt.get('nativeWordReceiptVersion')) is not int
            or finish_receipt.get('nativeWordReceiptVersion') != 1
            or any(finish_receipt.get(key) != value for key, value in word_finish_reference(receipt).items())):
        raise ValueError('native_word_finish_reference_mismatch')
