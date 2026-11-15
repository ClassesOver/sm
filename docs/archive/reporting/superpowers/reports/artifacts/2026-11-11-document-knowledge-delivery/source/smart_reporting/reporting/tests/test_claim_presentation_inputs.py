"""展示复核读取已登记文件和当前授权，不能继承历史支持状态。"""

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.workflow import claim_presentation


@pytest.mark.anyio
@pytest.mark.parametrize('current', [True, False])
@pytest.mark.parametrize('native', [False, True], ids=['document', 'native'])
async def test_registered_presentation_rechecks_current_knowledge_and_original_bytes(tmp_path, monkeypatch, current, native):
    from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs

    evidence = candidate()

    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': 'supports',
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote],
            'claimEvidence': ['预算合计']}])

    runtime, arguments, scope, _, _, _, contents, index = await native_quality_inputs(
        tmp_path, publication_fixture=True, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    identity = arguments['output']['artifactManifest']
    raw, _ = await runtime.workspace_service.afile_bytes(scope.workspace_key, identity['path'])
    manifest = ReportArtifactManifest.model_validate_json(raw)
    calls = []

    async def knowledge(actual_runtime, context, actual_index):
        assert actual_index == index
        calls.append('current_authorization')
        return (), {evidence.reference.evidence_id: evidence} if current else {}

    monkeypatch.setattr(claim_presentation, 'resolve_runtime_knowledge', knowledge)
    runtime = SimpleNamespace(workspace_service=runtime.workspace_service,
        _scope=lambda _: {'threadId': scope.workspace_key, 'userId': scope.user_id})
    loader = (claim_presentation.registered_native_claim_presentations if native
        else claim_presentation.registered_claim_support_projection)
    result = await loader(runtime, object(), manifest)
    assert calls == ['current_authorization']
    if native:
        item, = [value for values in result.values() for value in values]
        assert item['subjectId'] == index.subject_bindings[0].subject_id
        assert item['supportStatus'] == ('supported' if current else 'unverified')
        assert item['sourceSha256'] == manifest.markdown.sha256
        return
    assert result['sourceSha256'] == hashlib.sha256(contents[manifest.markdown.path]).hexdigest()
    assert result['claims'] == [{'sectionId': index.subject_bindings[0].locator.section_id,
        'claimId': index.subject_bindings[0].claim_id, 'kind': 'inference',
        'supportStatus': 'supported' if current else 'unverified'}]


@pytest.mark.anyio
@pytest.mark.parametrize('document_sources', [False, True])
@pytest.mark.parametrize('fault', ['index_bytes', 'source_bytes', 'report', 'basis', 'revision', 'markdown', 'budget'])
async def test_registered_presentation_rejects_changed_or_foreign_inputs_before_authorization(
    tmp_path, monkeypatch, fault, document_sources,
):
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs

    runtime, arguments, scope, _, _, _, _, _ = await native_quality_inputs(tmp_path, publication_fixture=True)
    raw, _ = await runtime.workspace_service.afile_bytes(scope.workspace_key, arguments['output']['artifactManifest']['path'])
    manifest = ReportArtifactManifest.model_validate_json(raw)
    if fault in {'index_bytes', 'source_bytes'}:
        file = manifest.trace_index if fault == 'index_bytes' else manifest.markdown
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, file.path, b'changed', overwrite=True)
    elif fault == 'markdown':
        manifest = manifest.model_copy(update={'markdown': manifest.markdown.model_copy(update={'sha256': '0' * 64})})
    elif fault == 'budget':
        manifest = manifest.model_copy(update={'trace_index': manifest.trace_index.model_copy(update={'size': 16 * 1024 * 1024 + 1})})
    else:
        key = {'report': 'report_id', 'basis': 'report_basis_id', 'revision': 'revision'}[fault]
        manifest = manifest.model_copy(update={key: 99 if fault == 'revision' else 'foreign'})

    async def forbidden(*args):
        pytest.fail('不可信登记不得进入当前知识授权和质量复核')

    monkeypatch.setattr(claim_presentation, 'resolve_runtime_knowledge', forbidden)
    runtime = SimpleNamespace(workspace_service=runtime.workspace_service,
        _scope=lambda _: {'threadId': scope.workspace_key, 'userId': scope.user_id})
    loader = (claim_presentation.registered_document_presentations if document_sources
        else claim_presentation.registered_claim_support_projection)
    with pytest.raises(ValueError, match='claim presentation'):
        await loader(runtime, object(), manifest)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'revoked', 'projection', 'budget', 'no_public_url'])
async def test_document_presentations_reuse_current_authorization_and_isolate_source_failure(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.business_knowledge import claims
    from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs

    evidence = candidate()

    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': 'supports',
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote],
            'claimEvidence': ['预算合计']}])

    runtime, arguments, scope, _, _, _, _, index = await native_quality_inputs(
        tmp_path, publication_fixture=True, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    raw, _ = await runtime.workspace_service.afile_bytes(scope.workspace_key, arguments['output']['artifactManifest']['path'])
    manifest = ReportArtifactManifest.model_validate_json(raw)
    calls = []

    async def knowledge(actual_runtime, context, actual_index):
        assert actual_index == index
        calls.append('current_authorization')
        return (), {} if fault == 'revoked' else {evidence.reference.evidence_id: evidence}

    monkeypatch.setattr(claim_presentation, 'resolve_runtime_knowledge', knowledge)
    if fault == 'projection':
        def unavailable(*args):
            raise OSError('injected source projection failure')

        monkeypatch.setattr(claims, 'knowledge_source_presentations', unavailable)
    if fault == 'budget':
        monkeypatch.setattr(claims, 'knowledge_source_summary', lambda _: ['原' * 6000])
    runtime = SimpleNamespace(workspace_service=runtime.workspace_service,
        report_public_base_url=None if fault == 'no_public_url' else 'https://reports.example.com',
        _scope=lambda _: {'threadId': scope.workspace_key, 'userId': scope.user_id})
    result = await claim_presentation.registered_document_presentations(runtime, object(), manifest)
    assert calls == ['current_authorization']
    assert result['claimSupport']['sourceSha256'] == manifest.markdown.sha256
    assert result['claimSupport']['claims'][0]['supportStatus'] == ('unverified' if fault == 'revoked' else 'supported')
    if fault in {'projection', 'budget'}:
        assert result['traceSources'] is None
        assert result['sourceIssue']['code'] == 'knowledge_source_projection_unavailable'
        return
    assert result.get('sourceIssue') is None
    source, = result['traceSources']['knowledge']
    if fault == 'revoked':
        assert evidence.hit.quote not in ''.join(source['summary'])
        assert '未附旧摘录' in ''.join(source['summary'])
    else:
        assert '原文摘录：' + evidence.hit.quote in source['summary']
    if fault == 'no_public_url':
        assert source['links'] == []
    else:
        from urllib.parse import quote

        assert source['links'] == [{'subjectId': source['subjectId'], 'url':
            f'https://reports.example.com/reports/v1/editor/{quote(index.report_id, safe="")}/{index.revision}?subject={source["subjectId"]}'}]
