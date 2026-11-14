"""管理验收只复用修订冻结判断，失败保留模板原文及实际产物。"""

import base64
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from docx import Document

from smart_reporting.reporting.delivery.template_signature_semantics import (
    inspect_signature_candidates,
)
from smart_reporting.reporting.template_semantic_review import _record
from smart_reporting.reporting.workflow.runtime.template_semantics import semantic_review_reference
from smart_reporting.tests.test_preference_preflight import _inputs, _run
from smart_reporting.tests.test_preference_template_preflight import identity, template_case


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _template():
    document = Document()
    document.add_paragraph('业务引用：清川分析室在2001-02-03确认收入，必须保留。')
    document.add_paragraph('{{report_title}}')
    document.add_paragraph('{{report_content}}')
    document.add_paragraph('清川分析室')
    document.add_paragraph('2001-02-03')
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _review(raw):
    blocks = inspect_signature_candidates(raw)['blocks']
    opinion = {'status': 'resolved', 'blocks': [
        {**{key: blocks[index][key] for key in ('blockId', 'text')}, 'role': role}
        for index, role in [(3, 'sample_identity'), (4, 'sample_date')]]}
    return _record(raw, 'resolved', (opinion, deepcopy(opinion)))


def _materials(tmp_path):
    draft, materials = _inputs(tmp_path)
    raw = _template()
    (tmp_path / 'template.docx').write_bytes(raw)
    record = _review(raw)
    state = deepcopy(materials.state)
    state['sources'].append(identity('template.docx', raw))
    source = {'identity': {**identity('template.docx', raw), 'filename': '来源模板.docx', 'mediaType': None},
        'templateFormat': 'docx', 'sourceContent': state['sources'][0], 'images': [],
        'semanticReview': record, 'semanticIssues': [],
        'semanticSource': {'review': semantic_review_reference(record), 'materialRunId': 'frozen-run',
            'binding': {'schemaVersion': 1, 'originRevision': 1, 'originContextSha256': 'a' * 64}}}
    return draft, replace(materials, state=state, sheets=(), slides=(), template_source=source), raw


def _no_preview(monkeypatch):
    from smart_reporting.management import preference_preflight

    def failed_preview(*_args, **_kwargs):
        raise OSError('本节点不验收预览转换')
    monkeypatch.setattr(preference_preflight, 'libreoffice_to_pdf', failed_preview)


def test_word_and_pdf_generation_and_readback_share_independently_checked_preparation(tmp_path, monkeypatch):
    from smart_reporting.management import preference_template_preflight as generation
    from smart_reporting.management import preference_template_readback as reader

    draft, materials, raw = _materials(tmp_path)
    _no_preview(monkeypatch)
    seen_generation, seen_readback = [], []
    fill, read = generation.fill_report_template, reader.read_template_document
    def filling(template, **kwargs):
        seen_generation.append(template)
        return fill(template, **kwargs)
    def reading(content, format, resolved, frozen, original, **kwargs):
        seen_readback.append(original)
        return read(content, format, resolved, frozen, original, **kwargs)
    monkeypatch.setattr(generation, 'fill_report_template', filling)
    monkeypatch.setattr(reader, 'read_template_document', reading)
    result = _run(draft, materials, formats=('word', 'pdf'))
    assert len(seen_generation) == len(seen_readback) == 2
    assert seen_generation[0] != raw
    assert all(item == seen_generation[0] for item in [*seen_generation, *seen_readback])
    word = result['formats']['word']
    content = base64.b64decode(word['artifact']['base64'])
    (tmp_path / 'verified-word.docx').write_bytes(content)
    (tmp_path / 'verified-pdf.pdf').write_bytes(base64.b64decode(result['formats']['pdf']['artifact']['base64']))
    document = Document(BytesIO(content))
    text = '\n'.join(document._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == text.count('2001-02-03') == 1
    assert '草稿验收编制' in text and '冻结业务原值 1234.56' in text
    assert word['templateReadback']['signature']['declaration'] == 'semantic_signature_sdt'
    assert word['templateReadback']['signature']['status'] == 'passed'
    assert word['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    assert word['templateReadback']['semanticPreparation']['preparationReadback']['status'] == 'passed'
    assert word['provenance']['placement'] == 'semantic_template_slot'
    assert word['provenance']['template']['sha256'] == sha256(raw).hexdigest()
    assert result['formats']['pdf']['artifact'] is not None
    assert result['formats']['pdf']['templateReadback']['signature']['status'] == 'unverified'
    assert result['canApply'] is False
    assert (tmp_path / 'template.docx').read_bytes() == raw
    assert 'readbackTemplate' not in str(result)


@pytest.mark.parametrize('fault', ['missing', 'record', 'reference', 'prepare_exception', 'reader_failed', 'reader_exception'])
def test_semantic_preparation_failure_keeps_unmarked_sample_and_actual_word(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.delivery import template_signature_readback
    from smart_reporting.reporting.workflow.runtime import template_semantics

    draft, materials, raw = _materials(tmp_path)
    _no_preview(monkeypatch)
    if fault == 'missing':
        materials.template_source.pop('semanticReview')
        materials.template_source.pop('semanticSource')
    elif fault == 'record':
        materials.template_source['semanticReview']['reviews'][1]['blocks'][0]['text'] = '漂移'
    elif fault == 'reference':
        materials.template_source['semanticSource']['review']['recordSha256'] = 'f' * 64
    elif fault == 'prepare_exception':
        monkeypatch.setattr(template_semantics, 'prepare_semantic_template',
            lambda *_args: (_ for _ in ()).throw(RuntimeError('private path')))
    elif fault == 'reader_failed':
        monkeypatch.setattr(template_signature_readback, 'read_semantic_preparation', lambda *_args: {
            'status': 'failed', 'coverage': 'unverified', 'issues': [{'code': 'reader_failed', 'message': '回读失败'}]})
    else:
        monkeypatch.setattr(template_signature_readback, 'read_semantic_preparation',
            lambda *_args: (_ for _ in ()).throw(RuntimeError('private path')))
    result = _run(draft, materials, formats=('word',))
    entry = result['formats']['word']
    content = base64.b64decode(entry['artifact']['base64'])
    text = '\n'.join(Document(BytesIO(content))._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == text.count('2001-02-03') == 2
    assert '草稿验收编制' in text and '冻结业务原值 1234.56' in text
    assert entry['templateReadback']['signature']['status'] == 'unverified'
    assert entry['provenance']['placement'] == 'body_end'
    assert any('semantic' in issue['code'] or issue['code'] == 'reader_failed' for issue in entry['issues'])
    assert result['canApply'] is False
    assert (tmp_path / 'template.docx').read_bytes() == raw
    assert 'private path' not in str(result)


async def _bound(tmp_path):
    service, args, preferences, repository, context, root, registered, _, file = await template_case(tmp_path)
    raw = _template()
    (root / file['path']).write_bytes(raw)
    file.update(identity(file['path'], raw))
    repository.state.payload['requestMaterials']['templateInput'] = file
    record = _review(raw)
    job = {**context.job, '_templateSemanticReview': semantic_review_reference(record)}
    context = context.model_copy(update={'job': job})
    repository.state.payload['reportEditorContexts'][str(context.revision)] = context.model_dump(mode='json', by_alias=True)
    grant, _ = await service.grants.issue(context)
    session, _ = await service.grants.exchange(grant)
    args.update(editor_session=session, expected_context_hash=context.digest())
    resolved = SimpleNamespace(identity=SimpleNamespace(model_dump=lambda **_kwargs: {**file, 'mediaType': None}),
        content=raw, semantic_review=record, semantic_issues=(), material_run_id=context.workflow_run_id,
        binding={'schemaVersion': 1, 'originRevision': 1, 'originContextSha256': context.digest()})
    return service, args, repository, context, raw, resolved


@pytest.mark.anyio
async def test_snapshot_binds_the_same_authorized_frozen_record_and_origin_reference(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module
    from smart_reporting.report_editor import template_source

    service, args, _, context, _, resolved = await _bound(tmp_path)
    resolver = AsyncMock(return_value=resolved)
    monkeypatch.setattr(template_source, 'resolve_editor_template', resolver)
    async def inspect_only(_function, _draft, materials, **_kwargs):
        assert materials.template_source['semanticReview'] == resolved.semantic_review
        assert materials.template_source['semanticSource'] == {'review': semantic_review_reference(resolved.semantic_review),
            'materialRunId': resolved.material_run_id, 'binding': resolved.binding}
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', inspect_only)
    result = await service.run(**args)
    assert resolver.await_count == 2
    assert all(call.kwargs['source_context'].digest() == context.digest() for call in resolver.await_args_list)
    assert result['binding']['valid'] is True
    assert result['binding']['templateSource']['semanticReview'] == resolved.semantic_review


@pytest.mark.anyio
async def test_historical_template_without_marker_never_creates_a_new_semantic_judgment(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module
    from smart_reporting.report_editor import template_source

    service, args, _, _, _, _, _, _, _ = await template_case(tmp_path)
    resolver = AsyncMock(side_effect=AssertionError('无marker不得重新解释历史模板'))
    monkeypatch.setattr(template_source, 'resolve_editor_template', resolver)
    async def inspect_only(_function, _draft, materials, **_kwargs):
        assert materials.template_source.get('semanticReview') is None
        return {'status': 'incomplete', 'canApply': False, 'formats': {}}
    monkeypatch.setattr(module, 'run_office_engine', inspect_only)
    result = await service.run(**args)
    assert result['binding']['valid'] is True
    resolver.assert_not_awaited()


@pytest.mark.anyio
async def test_semantic_source_drift_after_generation_keeps_actual_artifact_and_fails_binding(tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as module
    from smart_reporting.report_editor import template_source

    service, args, _, _, _, resolved = await _bound(tmp_path)
    changed = SimpleNamespace(**{**vars(resolved), 'semantic_review': None,
        'semantic_issues': ({'code': 'semantic_unavailable', 'message': '冻结记录身份变化'},)})
    monkeypatch.setattr(template_source, 'resolve_editor_template', AsyncMock(side_effect=[resolved, changed]))
    async def generated(_function, _draft, _materials, **_kwargs):
        return {'status': 'incomplete', 'canApply': False, 'formats': {'word': {
            'artifact': {'base64': 'a2VlcA==', 'size': 4, 'sha256': sha256(b'keep').hexdigest()}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    assert result['formats']['word']['artifact']['base64'] == 'a2VlcA=='
    assert result['binding']['valid'] is False and result['canApply'] is False
    assert result['issues'][-1]['code'] == 'management_preference_materials_changed'
