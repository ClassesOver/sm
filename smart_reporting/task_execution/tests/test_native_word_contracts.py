"""Private Word persistence DTOs are strict, bounded and independent of task output."""
from copy import deepcopy

import pytest

from smart_reporting.task_execution.native_word_contracts import (
    MAX_NATIVE_WORD_INPUT_BYTES,
    NativeWordTaskInput,
    canonical_digest,
    normalize_word_input,
)


def word_input(task_id='word-task'):
    selected = [{'blockId': 'p1', 'type': 'paragraph', 'text': 'Synthetic paragraph',
                 'expectedObjectSha256': 'a' * 64, 'allowedOperations': ['replaceParagraph'],
                 'before': [], 'after': [], 'styleChanges': [], 'draftOperations': []}]
    return {
        'version': 1,
        'binding': {
            'taskId': task_id,
            'scope': {'database': 'synthetic-db', 'companyId': 'company',
                      'userId': 'user', 'threadId': 'thread'},
            'documentId': 'document', 'revision': 1, 'format': 'docx',
            'contextSha256': 'b' * 64, 'sourceSha256': 'c' * 64,
            'snapshotSha256': 'd' * 64, 'draftOperationsSha256': 'e' * 64,
            'selectionSha256': canonical_digest(selected),
            'serverSessionReference': 'f' * 64,
        },
        'instructionSha256': canonical_digest('synthetic instruction'),
        'selectedParagraphs': selected,
    }


def test_input_is_canonical_and_copies_private_selection():
    payload = word_input()
    parsed, stored, digest = normalize_word_input(payload)
    assert isinstance(parsed, NativeWordTaskInput)
    assert 'Synthetic paragraph' not in repr(parsed)
    assert 'f' * 64 not in repr(parsed)
    assert digest == canonical_digest(stored)
    payload['selectedParagraphs'][0]['text'] = 'mutated caller'
    assert stored['selectedParagraphs'][0]['text'] == 'Synthetic paragraph'
    assert 'serverSessionReference' in stored['binding']


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(cookie='forbidden'),
    lambda p: p['binding'].update(bearer='forbidden'),
    lambda p: p['binding']['scope'].update(companyId=''),
    lambda p: p['binding'].update(revision=True),
    lambda p: p['binding'].update(serverSessionReference='raw-cookie'),
    lambda p: p.update(version=2),
    lambda p: p.update(version=True),
    lambda p: p['selectedParagraphs'][0].update(type='table'),
    lambda p: p['selectedParagraphs'][0].update(text=float('nan')),
    lambda p: p['selectedParagraphs'].append(deepcopy(p['selectedParagraphs'][0])),
    lambda p: p['binding'].update(selectionSha256='0' * 64),
])
def test_invalid_private_input_is_rejected(mutate):
    payload = word_input()
    mutate(payload)
    with pytest.raises(ValueError):
        normalize_word_input(payload)


def test_private_input_size_is_bounded_in_utf8():
    payload = word_input()
    payload['selectedParagraphs'][0]['text'] = '密' * MAX_NATIVE_WORD_INPUT_BYTES
    payload['binding']['selectionSha256'] = canonical_digest(payload['selectedParagraphs'])
    with pytest.raises(ValueError, match='too_large'):
        normalize_word_input(payload)


@pytest.mark.parametrize('finish', [None, {}, {'nativeWordReceiptVersion': 1},
    {'nativeWordReceiptVersion': True, 'nativeWordCandidateSha256': 'a' * 64, 'nativeWordInputSha256': 'b' * 64},
    {'nativeWordReceiptVersion': 1, 'nativeWordCandidateSha256': '0' * 64, 'nativeWordInputSha256': 'b' * 64},
])
def test_word_finish_reference_must_identify_exact_candidate_and_input(finish):
    from smart_reporting.task_execution.native_word_contracts import validate_word_finish_reference

    with pytest.raises(ValueError, match='finish_reference'):
        validate_word_finish_reference(finish, {'candidateSha256': 'a' * 64, 'inputSha256': 'b' * 64})


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['oversized', 'unregistered'])
async def test_candidate_preflight_rejects_before_any_database_connection(mode):
    from types import SimpleNamespace

    from smart_reporting.task_execution.repository import (
        TaskExecutionRepository,
        TaskExecutionRepositoryError,
    )

    # No connection methods exist: this proves rejected input needs no DB access.
    repository = TaskExecutionRepository(SimpleNamespace(db_engine=SimpleNamespace(
        dialect=SimpleNamespace(name='postgresql'))))
    proposal = {'summary': 'Synthetic', 'operations': []}
    registered = {'summary': 'Different', 'operations': []}
    expected = 'native_word_registered_proposal_mismatch'
    if mode == 'oversized':
        proposal['summary'] = 'x' * (512 * 1024 + 1)
        registered = proposal
        expected = 'native_word_proposal_too_large'
    with pytest.raises(TaskExecutionRepositoryError) as rejected:
        await repository.commit_native_word_candidate(proposal=proposal, registered_proposal=registered)
    assert rejected.value.code == expected


def test_canonical_json_does_not_coerce_non_string_keys_into_authorized_strings():
    with pytest.raises(ValueError, match='json_invalid'):
        canonical_digest({'styleChanges': {1: 'not a JSON object key'}})


def test_paragraph_repr_hides_inserted_and_draft_business_text():
    payload = word_input()
    payload['selectedParagraphs'][0].update(before=['private-before'], after=['private-after'],
        styleChanges=[{'private-style': 'private-style-value'}],
        draftOperations=[{'kind': 'replaceParagraph', 'text': 'private-draft'}])
    payload['binding']['selectionSha256'] = canonical_digest(payload['selectedParagraphs'])
    parsed, _stored, _digest = normalize_word_input(payload)
    rendered = repr(parsed.selected_paragraphs[0])
    for private in ['private-before', 'private-after', 'private-style-value', 'private-draft']:
        assert private not in rendered
