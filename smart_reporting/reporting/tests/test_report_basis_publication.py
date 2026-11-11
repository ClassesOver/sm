"""产物清单引用新计算依据，拒绝旧业务Profile契约。"""

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.artifacts_v1 import (
    DocxArtifactManifest,
    PdfArtifactManifest,
    ReportArtifactManifest,
)


def draft_payload():
    return {
        'reportId': 'report-1', 'revision': 1, 'codingTaskKey': 'task-1',
        'datasetSnapshotHash': 'a' * 64, 'reportBasisId': 'basis-registered-1',
        'markdown': {'path': 'reports/report.md', 'mediaType': 'text/markdown', 'size': 1, 'sha256': 'b' * 64},
        'citations': [{'citationId': 'citation_001', 'datasetId': 'dataset_001',
            'requirementId': 'requirement_001', 'snapshotHash': 'a' * 64}],
        'sections': ['section_001'], 'sectionNumbers': ['1'],
        'headingNumbers': [{'level': 2, 'number': '1', 'title': '计算说明',
            'sectionCode': 'section_001', 'anchor': 'report-section-001'}],
    }


def rendered_payload(model):
    payload = {key: value for key, value in draft_payload().items()
        if key in {'reportId', 'revision', 'reportBasisId', 'sections', 'sectionNumbers', 'headingNumbers'}}
    payload['sourceMarkdownSha256'] = 'b' * 64
    if model is PdfArtifactManifest:
        payload.update(pdf={'path': 'reports/report.pdf', 'mediaType': 'application/pdf', 'size': 3, 'sha256': 'c' * 64}, pageCount=1)
    else:
        payload.update(docx={'path': 'reports/report.docx', 'mediaType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'size': 3, 'sha256': 'c' * 64}, convertedPageCount=1, sectionCount=1, tocEntryCount=1)
    return payload


@pytest.mark.parametrize('model', [ReportArtifactManifest, PdfArtifactManifest, DocxArtifactManifest])
def test_artifact_manifest_requires_registered_basis_without_profile_conversion(model):
    payload = draft_payload() if model is ReportArtifactManifest else rendered_payload(model)
    manifest = model.model_validate(payload)
    assert manifest.report_basis_id == 'basis-registered-1'
    assert 'effectiveProfileHash' not in manifest.model_dump(by_alias=True)
    legacy = {**payload, 'effectiveProfileHash': 'e' * 64}
    del legacy['reportBasisId']
    with pytest.raises(ValidationError):
        model.model_validate(legacy)
    with pytest.raises(ValidationError):
        model.model_validate({**payload, 'effectiveProfileHash': 'e' * 64})


@pytest.mark.parametrize('changed', ['pdf', 'word'])
def test_rendered_artifacts_cannot_claim_a_different_registered_basis(changed):
    from smart_reporting.reporting.delivery.artifacts_v1 import (
        dataset_snapshot_hash,
        validate_rendered_artifacts,
    )
    from smart_reporting.reporting.models import ReportingError

    draft = ReportArtifactManifest.model_validate({**draft_payload(), 'datasetSnapshotHash': dataset_snapshot_hash(())})
    pdf = PdfArtifactManifest.model_validate(rendered_payload(PdfArtifactManifest))
    word = DocxArtifactManifest.model_validate(rendered_payload(DocxArtifactManifest))
    if changed == 'pdf':
        pdf = pdf.model_copy(update={'report_basis_id': 'basis-other'})
    else:
        word = word.model_copy(update={'report_basis_id': 'basis-other'})
    with pytest.raises(ReportingError, match='报告计算依据'):
        validate_rendered_artifacts(draft, pdf, word, lineage=())


@pytest.mark.anyio
async def test_quality_cache_identity_includes_the_registered_basis(tmp_path):
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

    _, _, _, _, _, _, contents, index = await _publication_fixture(tmp_path, registered_result=True)
    sources = {file.resource_id: contents[file.path] for file in index.files}
    markdown = contents['reports/report.md'].decode()
    first = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    changed = evaluate_quality_bundle(index.model_copy(update={'report_basis_id': 'basis-other'}),
        markdown, sources, authorization_scope_hash='a' * 64)
    assert first.input_sha256 != changed.input_sha256
    assert next(iter(first.table_checks.values())).status == 'verified'
    assert next(iter(changed.table_checks.values())).status == 'unknown'

    # Editor独立附表检查也必须核对依据，不能只依赖上层质量过滤。
    from smart_reporting.reporting.trace.fact_service import read_fact_document
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

    documents = {entry.file_resource_id: read_fact_document(sources[entry.file_resource_id]) for entry in index.fact_files}
    independent = evaluate_table_quality(index.model_copy(update={'report_basis_id': 'basis-other'}), markdown, documents)
    assert next(iter(independent.values())).status == 'unknown'
    assert next(iter(independent.values())).checked_cells == 0
