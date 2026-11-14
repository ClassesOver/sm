"""要求证据必须引用本次独立回读的同格式原生/预览文件。"""

from copy import deepcopy

import pytest

from smart_reporting.management.models import ManagementError
from smart_reporting.management.preference_evidence import PreferenceEvidenceService


def material():
    reference = {'size': 4, 'sha256': 'a' * 64}
    row = {'format': 'md', 'dimension': 'native', 'authorized': True, 'status': 'passed',
        'sourceArtifact': {'format': 'md', 'role': 'artifact'},
        'artifact': {'sha256': 'a' * 64, 'sizeBytes': 4}}
    return {'evidence': [row]}, {'formats': {'md': {'artifact': reference}}, 'issues': []}


def test_requirement_evidence_is_bound_to_independently_read_artifact():
    document, checked = material()
    original = deepcopy(document)
    result = PreferenceEvidenceService._qualified_evidence(document, checked)
    assert result == document['evidence'] and document == original


@pytest.mark.parametrize('fault', ['sha256', 'size', 'missing_source', 'wrong_role', 'wrong_format', 'unauthorized'])
def test_requirement_evidence_cannot_use_other_or_unretained_bytes(fault):
    document, checked = material()
    row = document['evidence'][0]
    if fault == 'sha256':
        row['artifact']['sha256'] = 'b' * 64
    elif fault == 'size':
        row['artifact']['sizeBytes'] = True
    elif fault == 'missing_source':
        row.pop('sourceArtifact')
    elif fault == 'wrong_role':
        row['sourceArtifact']['role'] = 'pdf'
    elif fault == 'wrong_format':
        row['format'] = 'word'
    else:
        row['authorized'] = False
    with pytest.raises(ManagementError, match='management_preference_evidence_artifact_mismatch'):
        PreferenceEvidenceService._qualified_evidence(document, checked)


def test_lifecycle_evidence_names_its_actual_file_and_failed_check_is_preserved():
    document, checked = material()
    document['evidence'][0].update(format='system', status='failed')
    assert PreferenceEvidenceService._qualified_evidence(document, checked)[0]['status'] == 'failed'


@pytest.mark.parametrize('manifest', [{}, {'runtimeIdentityComplete': False, 'runtimeIdentityIssues': []},
    {'runtimeIdentityComplete': True, 'runtimeIdentityIssues': [{'code': 'missing', 'resource': 'pdfium.wasm'}]}])
def test_missing_runtime_identity_is_an_explicit_approval_gap(manifest):
    gaps = PreferenceEvidenceService._runtime_identity_gaps(manifest)
    assert gaps and all(gap['reason'] == 'executor_identity_unavailable' for gap in gaps)


def test_complete_runtime_identity_does_not_fabricate_visual_evidence():
    assert PreferenceEvidenceService._runtime_identity_gaps(
        {'runtimeIdentityComplete': True, 'runtimeIdentityIssues': []}) == []


def test_native_word_evidence_cannot_borrow_pdf_preview():
    document, checked = material()
    row = document['evidence'][0]
    row.update(format='word', dimension='native', sourceArtifact={'format': 'word', 'role': 'pdf'})
    checked['formats'] = {'word': {'pdf': {'size': 4, 'sha256': 'a' * 64}}}
    with pytest.raises(ManagementError, match='management_preference_evidence_artifact_mismatch'):
        PreferenceEvidenceService._qualified_evidence(document, checked)


def test_visual_word_evidence_requires_its_pdf_preview_instead_of_native_document():
    document, checked = material()
    row = document['evidence'][0]
    row.update(format='word', dimension='visual', sourceArtifact={'format': 'word', 'role': 'artifact'})
    checked['formats'] = {'word': {'artifact': {'size': 4, 'sha256': 'a' * 64},
        'pdf': {'size': 9, 'sha256': 'b' * 64}}}
    with pytest.raises(ManagementError, match='management_preference_evidence_artifact_mismatch'):
        PreferenceEvidenceService._qualified_evidence(document, checked)
    row['sourceArtifact']['role'] = 'pdf'
    row['artifact'] = {'sizeBytes': 9, 'sha256': 'b' * 64}
    assert PreferenceEvidenceService._qualified_evidence(document, checked) == document['evidence']
