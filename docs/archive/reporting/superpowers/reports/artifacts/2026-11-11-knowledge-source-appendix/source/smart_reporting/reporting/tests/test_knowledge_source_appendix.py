"""知识原文附录只展示本次核验授权的精确材料，不继承历史支持。"""

import hashlib
from dataclasses import replace

import pytest

from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
from smart_reporting.report_editor.service import _build_export_trace_sources
from smart_reporting.reporting.delivery.report_runtime.markdown import _trace_source_appendix_html
from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown
from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'revoked', 'foreign_basis', 'changed_quote'])
async def test_current_knowledge_original_reaches_editor_export_without_borrowing_old_text(tmp_path, monkeypatch, fault):
    evidence = candidate()

    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': 'irrelevant',
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote],
            'claimEvidence': ['预算合计']}])

    runtime, arguments, scope, durable, _, _, _, _ = await native_quality_inputs(
        tmp_path, publication_fixture=True, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    runtime.workspace_registry.resolve(scope)
    calls = []

    async def resolve(*args):
        calls.append(True)
        current = evidence
        if fault == 'foreign_basis':
            current = replace(evidence, reference=evidence.reference.model_copy(update={'basis_id': 'foreign'}))
        if fault == 'changed_quote':
            current = replace(evidence, hit=evidence.hit.model_copy(update={'quote': '已改写的原文不能被采用'}))
        return {'status': 'available' if fault == 'none' else 'unavailable', 'issueCodes': [], 'sections': []}, (
            {} if fault == 'revoked' else {evidence.reference.evidence_id: current})

    monkeypatch.setattr(editor.trace, 'resolve_knowledge_dependencies', resolve)
    try:
        _, index = await editor.trace.load_manifest_and_index(context)
        markdown = await runtime.workspace_service.aread_text(scope.workspace_key, context.markdown_path)
        validation = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        assert calls == [True]
        sources = validation.get('knowledgeSources')
        assert sources, '已登记知识引用未进入导出展示投影'
        source, = sources
        assert source['supportStatus'] == 'unverified'
        payload = _build_export_trace_sources(index, validation, public_base_url='https://reports.example.com',
            report_id=context.report_id, revision=3)
        _, _, trace = _pdf_markdown(markdown, [], include_sources=True, trace_sources=payload)
        html = _trace_source_appendix_html(trace)
        assert '业务知识来源' in html
        assert '待核实' in html
        if fault == 'none':
            assert source['available'] is True
            assert evidence.hit.title in html and evidence.hit.quote in html
            assert '第1版' in html and '原件第1–1行' in html
            assert '原文可访问不等于解释已获支持' in html
        else:
            assert source['available'] is False
            assert source.get('quote') is None and source.get('title') is None
            assert evidence.hit.quote not in html and '已改写的原文' not in html
            assert '原文未能按当前权限核验' in html
    finally:
        await editor.aclose()


@pytest.mark.anyio
async def test_narrative_without_any_fact_still_has_a_knowledge_appendix(tmp_path):
    from smart_reporting.reporting.business_knowledge.claims import knowledge_source_presentations
    from smart_reporting.reporting.trace.contracts_v1 import NarrativeReferenceV1

    evidence = candidate()

    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': 'irrelevant',
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote],
            'claimEvidence': ['预算合计']}])

    index, _, _ = await native_quality_inputs(tmp_path, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    subject, = index.subject_bindings
    number = subject.number_reference
    narrative = NarrativeReferenceV1(offset=0, claimId=subject.claim_id,
        basisId=index.report_basis_id, period=evidence.period,
        statementSha256=number.statement_sha256, semanticReceipt=number.semantic_receipt)
    index = index.model_copy(update={'subject_bindings': (subject.model_copy(update={
        'fact_refs': (), 'number_reference': None, 'narrative_reference': narrative}),)})
    sources = knowledge_source_presentations(index, (), {evidence.reference.evidence_id: evidence})
    payload = _build_export_trace_sources(index, {'knowledgeSources': sources},
        public_base_url='https://reports.example.com', report_id=index.report_id, revision=3)
    assert not payload['claims'] and not payload['tables']
    _, _, trace = _pdf_markdown('仅有建议的正文', [], include_sources=True, trace_sources=payload)
    assert evidence.hit.quote in _trace_source_appendix_html(trace)


def test_knowledge_source_does_not_bypass_the_shared_16kib_export_budget():
    from types import SimpleNamespace

    from smart_reporting.reporting.business_knowledge.claim_models import (
        KnowledgeSourcePresentation,
    )
    from smart_reporting.reporting.models import ReportingError

    original = candidate()
    entry = KnowledgeSourcePresentation(subjectId='sub-' + 'a' * 16,
        evidenceId=original.reference.evidence_id, available=True, supportStatus='unverified',
        title=original.hit.title, documentRevision=1, role=original.hit.role,
        locator=original.hit.locator, quote='原' * 1200, period=original.period,
        recordedAt=original.hit.recorded_at).model_dump(mode='json', by_alias=True)
    validation = {'knowledgeSources': [entry] * 5}
    index = SimpleNamespace(datasets=(), subject_bindings=(), tables=(), chart_traces=(), files=(), computations=())
    with pytest.raises(ReportingError) as error:
        _build_export_trace_sources(index, validation, public_base_url='https://reports.example.com',
            report_id='report-1', revision=3)
    assert error.value.code == 'report_editor_trace_sources_too_large'
    assert validation['knowledgeSources'][0]['quote'] == '原' * 1200


def knowledge_only_payload(*, quote=None):
    from smart_reporting.reporting.business_knowledge.claim_models import (
        KnowledgeSourcePresentation,
    )
    from smart_reporting.reporting.business_knowledge.claims import knowledge_source_summary

    evidence = candidate()
    value = KnowledgeSourcePresentation(subjectId='sub-' + 'a' * 16,
        evidenceId=evidence.reference.evidence_id, available=True, supportStatus='unverified',
        title=evidence.hit.title, documentRevision=evidence.hit.revision, role=evidence.hit.role,
        locator=evidence.hit.locator, quote=quote or evidence.hit.quote, period=evidence.period,
        recordedAt=evidence.hit.recorded_at)
    return {'claims': [], 'tables': [], 'charts': [], 'datasets': {}, 'knowledge': [{
        'subjectId': value.subject_id, 'summary': knowledge_source_summary(value),
        'links': [{'subjectId': value.subject_id,
            'url': 'https://reports.example.com/reports/v1/editor/report-1/3?subject=' + value.subject_id}]}]}


def test_knowledge_only_appendix_escapes_original_and_keeps_rendering_identity():
    from smart_reporting.reporting.delivery.report_runtime.projection import build_render_projection

    original = '<script>危险标题</script> & [外链](https://invalid.example)'
    payload = knowledge_only_payload(quote=original)
    first = build_render_projection('# 预算报告', (), include_sources=True, trace_sources=payload)
    html = _trace_source_appendix_html(first.trace_source_render)
    assert '业务知识来源' in html
    assert '<script>' not in html and '&lt;script&gt;' in html and '&amp;' in html
    assert '<a href="https://invalid.example' not in html
    payload['knowledge'][0]['summary'][3] = '原文摘录：另一份摘录'
    second = build_render_projection('# 预算报告', (), include_sources=True, trace_sources=payload)
    assert first.receipt['presentationSha256'] != second.receipt['presentationSha256']


@pytest.mark.parametrize('fault', ['extra_key', 'long_quote', 'bad_link', 'oversized'])
def test_knowledge_appendix_rejects_invalid_or_unbounded_payload(fault):
    from smart_reporting.reporting.delivery.report_runtime.validation import ReportFailure

    payload = knowledge_only_payload()
    if fault == 'extra_key':
        payload['knowledge'][0]['serverPath'] = '/private/original.txt'
    elif fault == 'long_quote':
        payload['knowledge'][0]['summary'] = ['x' * 1501]
    elif fault == 'bad_link':
        payload['knowledge'][0]['links'][0]['url'] = 'javascript:alert(1)'
    else:
        payload['knowledge'] *= 401
    with pytest.raises(ReportFailure):
        _pdf_markdown('# Report', [], include_sources=True, trace_sources=payload)


@pytest.mark.parametrize('fault', ['missing_title', 'missing_quote', 'disabled_but_visible'])
def test_native_visibility_detects_missing_or_unexpected_knowledge_original(tmp_path, fault):
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.delivery.report_runtime.validation import ReportFailure

    payload = knowledge_only_payload()
    item = payload['knowledge'][0]
    visible = '业务知识来源 [知识来源 001] ' + ' '.join(item['summary'])
    if fault == 'missing_title':
        visible = visible.replace('业务知识来源', '')
    elif fault == 'missing_quote':
        visible = visible.replace(item['summary'][3], '')
    render = {'traceSourcePresentations': {'entries': [], 'knowledge': payload['knowledge']},
        'exportSettings': {'sources': fault != 'disabled_but_visible'},
        'traceSourceAppendixPresent': False, 'knowledgeSourceAppendixPresent': fault != 'disabled_but_visible'}
    with pytest.raises(ReportFailure, match='知识'):
        ReportRuntime(tmp_path)._validate_trace_source_visibility(render, visible)


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('with_data', [False, True])
def test_knowledge_only_and_mixed_appendices_follow_the_same_source_toggle(tmp_path, enabled, with_data):
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    payload = knowledge_only_payload()
    entries = [{'alias': '[数据来源 001]'}] if with_data else []
    visible = ''
    if enabled:
        visible = '业务知识来源 [知识来源 001] ' + ' '.join(payload['knowledge'][0]['summary'])
        if with_data:
            visible += ' 数据来源附录 [数据来源 001]'
    render = {'traceSourcePresentations': {'entries': entries, 'knowledge': payload['knowledge']},
        'exportSettings': {'sources': enabled}, 'traceSourceAppendixPresent': enabled and with_data,
        'knowledgeSourceAppendixPresent': enabled}
    ReportRuntime(tmp_path)._validate_trace_source_visibility(render, visible)


def test_knowledge_only_original_survives_actual_pdf_word_rendering(tmp_path):
    import json
    import os
    import shutil
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_runtime_full_render import (
        _TEMPORARY_PDF_PATH,
        _build_workspace,
        _render_dependencies_available,
    )

    available, reason = _render_dependencies_available()
    if not available:
        pytest.skip(reason)
    root = tmp_path / 'render'
    state = _build_workspace(root)
    (root / 'report.md').write_text('# 业务知识附录验证\n\n[[section:overview]]\n\n## 1. 经营概览\n\n'
        '建议按原始金额累计预算，解释支持关系待核实。', encoding='utf-8')
    state['_documentContext'].update(title='业务知识附录验证', generatedDate='2026-11-11')
    state['_editorExportSettings'].update(sources=True)
    state['_traceSourcePresentations'] = knowledge_only_payload()
    rendered = ReportRuntime(root).render_markdown(state, 'report.md', 'reports/knowledge.pdf', _TEMPORARY_PDF_PATH)
    assert rendered['status'] == 'rendered'
    assert rendered['render']['knowledgeSourceAppendixPresent'] is True
    saved = Path('/tmp') / f'smart-reporting-knowledge-sources-{os.getpid()}'
    saved.mkdir(exist_ok=True)
    for kind, suffix in [('pdf', 'pdf'), ('word', 'docx')]:
        file = root / rendered[kind + 'Path']
        text = ('\n'.join(page.extract_text() or '' for page in PdfReader(file).pages) if kind == 'pdf'
            else '\n'.join(paragraph.text for paragraph in Document(file).paragraphs))
        if kind == 'pdf':
            ReportRuntime(root)._validate_trace_source_visibility(rendered['render'], text)
        compact = ''.join(text.split())
        for expected in ['业务知识来源', '预算制度（第1版）', '原件第1–1行', candidate().hit.quote,
            '原文可访问不等于解释已获支持', '待核实']:
            assert expected in compact
        if kind == 'word':
            title = next(paragraph for paragraph in Document(file).paragraphs if paragraph.text == '业务知识来源')
            assert title.style.name == 'Report Source Appendix'
            assert title.paragraph_format.page_break_before is True
        shutil.copy2(file, saved / ('knowledge.' + suffix))
        (saved / (kind + '-text.txt')).write_text(text, encoding='utf-8')
    shutil.copy2(root / 'report.md', saved / 'source.md')
    for name, value in [('render', rendered), ('job', state), ('sources', state['_traceSourcePresentations'])]:
        (saved / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
