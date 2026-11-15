"""正式结果的可读来源说明，不借用草稿、最新规则或浮点近似值。"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_references


def formal_reference(context=None):
    analysis, original, result = analysis_inputs()
    context = context or original
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:fact-budget:value:CNY}}'
    return resolve_number_references([token], [content])[token], result


def test_formal_source_explains_exact_versions_and_keeps_decimal_and_limitations():
    selected, _ = formal_reference()
    explanation = selected['explanation']
    assert explanation is not None
    assert '预算额（第1版）' in explanation
    assert '求和' in explanation
    assert '合成预算执行（第1版）' in explanation
    assert '300.123456789123456789 CNY' in explanation
    assert '取数时间未登记' in explanation
    assert '数据完整性与更新状态尚未核实' in explanation
    assert '不等于业务核验通过' in explanation
    assert 'warehouse.test' not in explanation
    assert selected['period'] == {'start': '2026-11-01', 'end': '2026-12-01'}
    # 展示补充不能让尚未核验的半开期间走旧的字面匹配并自动通过。
    assert selected['periods'] == ()


def ratio_reference(*, missing_dependency=False, long_names=False):
    analysis, context, original = analysis_inputs()
    budget = context.metrics[0].model_copy(update={'id': 'budget-base'})
    latest = budget.model_copy(update={'revision': 2, 'name': '另一个预算定义'})
    actual = budget.model_copy(update={'id': 'actual-base', 'name': '实际额'})
    ratio = budget.model_copy(update={'id': 'budget', 'name': '执行率', 'kind': 'ratio',
        'field_ref': None, 'time_field': None, 'unit': '%',
        'numerator_version': actual.version_ref(), 'denominator_version': budget.version_ref()})
    result = original.model_copy(update={'unit': '%', 'value': Decimal('63.333333333333333333')})
    calculation = context.calculations[0].model_copy(update={'results': (result,)})
    metrics = (ratio, actual, latest) + (() if missing_dependency else (budget,))
    context = context.model_copy(update={'metrics': metrics, 'calculations': (calculation,)})
    if long_names:
        from smart_reporting.reporting.semantics.models import DataReadiness, ReadinessCheck

        readiness = DataReadiness(metric_version=result.metric_version, requested_period=result.period,
            observed_period=None, extracted_at=datetime(2026, 11, 5, 1, 2, tzinfo=UTC),
            checks=(ReadinessCheck(name='coverage', status='unknown'),), issue_codes=('data_readiness_unknown',))
        context = context.model_copy(update={
            'metrics': tuple(item.model_copy(update={'name': item.name[0] * 200}) for item in metrics),
            'policy': context.policy.model_copy(update={'name': '口' * 200}),
            'calculations': (calculation.model_copy(update={'readiness': (readiness,), 'results': (
                result.model_copy(update={'issue_codes': ('data_readiness_unknown', 'source_watermark_unknown')}),)}),)})
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:fact-budget:value:%}}'
    return resolve_number_references([token], [content])[token]


@pytest.mark.parametrize('missing_dependency', [False, True])
def test_ratio_source_uses_precise_versions_and_never_borrows_latest(missing_dependency):
    selected = ratio_reference(missing_dependency=missing_dependency)
    assert selected is not None
    explanation = selected['explanation']
    assert '实际额（第1版） ÷ ' in explanation
    assert ' × 100%' in explanation
    assert '操作数需查计算明细' in explanation
    assert '登记结果 63.333333333333333333 %' in explanation
    assert '另一个预算定义' not in explanation
    if missing_dependency:
        assert '依赖指标版本未登记' in explanation
    else:
        assert '预算额（第1版）' in explanation


@pytest.mark.parametrize('kind', ['claim', 'table'])
def test_legal_long_source_explanation_keeps_every_name_version_and_limitation(kind):
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _trace_source_appendix_html,
    )
    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown

    explanation = ratio_reference(long_names=True)['explanation']
    assert len(explanation) > 1000
    common = {'subjectIds': [], 'status': 'stale', 'datasetIds': [], 'links': []}
    sources = {'claims': [], 'tables': [], 'charts': [], 'datasets': {}}
    if kind == 'claim':
        sources['claims'] = [{**common, 'claimId': 'long-formal', 'factValue': '63.333333333333333333',
            'unit': '%', 'periods': ['[2026-11-01, 2026-12-01)'], 'formula': explanation, 'scope': {}}]
    else:
        sources['tables'] = [{**common, 'tableId': 'long-formal', 'methods': [explanation]}]
    _, _, trace = _pdf_markdown('', [], include_sources=True, trace_sources=sources)
    rendered = _trace_source_appendix_html(trace)
    for value in ('执' * 200, '实' * 200, '预' * 200, '口' * 200, '63.333333333333333333',
            '数据完整性与更新状态尚未核实', '缺少源数据更新时间', '登记结果不等于业务核验通过'):
        assert value in rendered


def test_source_uses_only_matching_metric_and_period_extraction_receipts():
    from smart_reporting.reporting.semantics.models import DataReadiness, Period, ReadinessCheck

    _, context, result = analysis_inputs()
    readiness = DataReadiness(metric_version=result.metric_version, requested_period=result.period,
        observed_period=None, extracted_at=datetime(2026, 11, 5, 1, 2, tzinfo=UTC),
        checks=(ReadinessCheck(name='coverage', status='unknown'),), issue_codes=('data_readiness_unknown',))
    unrelated = readiness.model_copy(update={'requested_period': Period(start='2026-10-01', end='2026-11-01'),
        'extracted_at': datetime(2026, 10, 5, 1, 2, tzinfo=UTC)})
    calculation = context.calculations[0].model_copy(update={'readiness': (unrelated, readiness)})
    selected, _ = formal_reference(context.model_copy(update={'calculations': (calculation,)}))
    assert '2026-11-05T01:02:00+00:00' in selected['explanation']
    assert '2026-10-05' not in selected['explanation']


@pytest.mark.anyio
async def test_source_summary_does_not_use_formal_result_from_a_different_basis(tmp_path, monkeypatch):
    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.reporting.tests import test_http_publication_lineage as fixtures

    builder = fixtures.build_csv_trace_index
    monkeypatch.setattr(fixtures, 'build_csv_trace_index',
        lambda **values: builder(**{**values, 'report_basis_id': 'basis-foreign'}))
    runtime, arguments, scope, durable, _, _, _, _ = await fixtures._publication_fixture(tmp_path, registered_result=True)
    await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    try:
        runtime.workspace_registry.resolve(scope)
        markdown = await runtime.workspace_service.aread_text(context.scope['threadId'], context.markdown_path)
        validation = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        for table in validation['tables']:
            for location in table['locations']:
                assert not location.get('formulaText')
                assert location.get('factValue') is None
    finally:
        await editor.aclose()


@pytest.mark.anyio
async def test_formal_sources_survive_actual_pdf_word_rendering(tmp_path):
    import json
    import os
    import re
    import shutil
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
    from smart_reporting.reporting.tests.test_report_runtime_full_render import (
        _TEMPORARY_PDF_PATH,
        _build_workspace,
        _render_dependencies_available,
    )

    available, reason = _render_dependencies_available()
    if not available:
        pytest.skip(reason)
    runtime, arguments, scope, durable, _, _, _, _ = await _publication_fixture(tmp_path, registered_result=True)
    await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    try:
        runtime.workspace_registry.resolve(scope)
        _, index = await editor.trace.load_manifest_and_index(context)
        markdown = await runtime.workspace_service.aread_text(context.scope['threadId'], context.markdown_path)
        validation = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        sources = _build_export_trace_sources(index, validation,
            public_base_url='https://reports.example.com', report_id=context.report_id, revision=3)
        root = tmp_path / 'render'
        state = _build_workspace(root)
        (root / 'report.md').write_text(markdown.replace('# Report\n',
            '# 正式指标计算说明验收\n\n[[section:overview]]\n\n## 1. 经营概览\n'), encoding='utf-8')
        file = next(item for item in index.files if item.resource_id == index.datasets[0].file_resource_id)
        csv, _ = await runtime.workspace_service.afile_bytes(context.scope['threadId'], file.path)
        (root / 'data/overview.csv').write_bytes(csv)
        state['sources'] = [{'path': 'data/overview.csv', 'size': len(csv), 'sha256': hashlib.sha256(csv).hexdigest()}]
        state['_documentContext'].update(title='正式指标计算说明验收', periodLabel='2026年11月')
        state['_editorExportSettings'] = {'cover': False, 'toc': False, 'sources': True}
        state['_traceSourcePresentations'] = sources
        rendered = ReportRuntime(root).render_markdown(state, 'report.md', 'reports/formal.pdf',
            _TEMPORARY_PDF_PATH)
        assert rendered['status'] == 'rendered'
        output = Path('/tmp') / f'smart-reporting-formal-sources-{os.getpid()}'
        output.mkdir(exist_ok=True)
        for registered in index.files:
            raw, _ = await runtime.workspace_service.afile_bytes(context.scope['threadId'], registered.path)
            assert len(raw) == registered.size and hashlib.sha256(raw).hexdigest() == registered.sha256
            saved = output / 'registered' / registered.path
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
        (output / 'index.json').write_text(index.model_dump_json(by_alias=True, indent=2), encoding='utf-8')
        for label, extension in [('pdf', 'pdf'), ('word', 'docx')]:
            path = root / rendered[label + 'Path']
            text = ('\n'.join(page.extract_text() or '' for page in PdfReader(path).pages) if label == 'pdf'
                else '\n'.join(paragraph.text for paragraph in Document(path).paragraphs))
            compact = re.sub(r'\s+', '', text)
            for expected in ('数据来源附录', '预算额（第1版）', '合成预算执行（第1版）',
                    '300.123456789123456789CNY', '2026-11-01', '2026-12-01', '含起日、不含止日',
                    '数据完整性与更新状态尚未核实', '登记结果不等于业务核验通过'):
                assert expected in compact
            shutil.copy2(path, output / f'formal.{extension}')
            (output / f'{label}-text.txt').write_text(text, encoding='utf-8')
        shutil.copy2(root / 'report.md', output / 'source.md')
        for name, value in [('sources', sources), ('validation', validation), ('render', rendered), ('job', state)]:
            (output / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    finally:
        await editor.aclose()


@pytest.mark.anyio
async def test_table_only_formal_result_reaches_pdf_word_source_appendix(tmp_path):
    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _trace_source_appendix_html,
    )
    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture

    runtime, arguments, scope, durable, _, _, _, _ = await _publication_fixture(tmp_path, registered_result=True)
    await runtime.issue_http_publication(**arguments)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    try:
        runtime.workspace_registry.resolve(scope)
        _, index = await editor.trace.load_manifest_and_index(context)
        markdown = await runtime.workspace_service.aread_text(context.scope['threadId'], context.markdown_path)
        validation = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        sources = _build_export_trace_sources(index, validation,
            public_base_url='https://reports.example.com', report_id=context.report_id, revision=3)
        assert sources['claims'] == []
        _, _, trace = _pdf_markdown(markdown, [], include_sources=True, trace_sources=sources)
        rendered = _trace_source_appendix_html(trace)
        assert '预算额（第1版）' in rendered
        assert '合成预算执行（第1版）' in rendered
        assert '300.123456789123456789 CNY' in rendered
        assert '2026-11-01' in rendered and '2026-12-01' in rendered
        assert '含起日、不含止日' in rendered
        assert '数据完整性与更新状态尚未核实' in rendered
        assert '不等于业务核验通过' in rendered
    finally:
        await editor.aclose()


async def exercise_formal_source_export_fault(tmp_path, monkeypatch):
    """从真实来源校验失败走原生导出与HTTP下载；持久库使用隔离内存端口。"""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.reporting.delivery.publishing import (
        ReportDownloadHttpService,
        create_report_download_router,
    )
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import _StateRepository
    from smart_reporting.reporting.tests.test_report_runtime_full_render import (
        _build_workspace,
        _render_dependencies_available,
    )
    from smart_reporting.reporting.trace import reader_formulas
    from smart_reporting.reporting.workflow.state import ReportingRunState
    from smart_reporting.reporting.workspace import WorkspaceReportService, thread_binding

    available, reason = _render_dependencies_available()
    if not available:
        pytest.skip(reason)
    runtime, arguments, scope, durable, artifacts, _, _, index = await _publication_fixture(
        tmp_path, registered_result=True, native_document=True,
    )
    await runtime.issue_http_publication(**arguments)
    runtime.workspace_registry.resolve(scope)
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    state = _build_workspace(tmp_path / 'metadata')
    state['_documentContext']['title'] = 'Report'
    file = next(item for item in index.files if item.resource_id == index.datasets[0].file_resource_id)
    job = {**state, 'jobId': context.job_id, '_threadBinding': thread_binding(scope.workspace_key),
        'sources': [{'path': file.path, 'size': file.size, 'sha256': file.sha256}]}
    render = {'markdown': await runtime.workspace_service.ahash_file(scope.workspace_key, context.markdown_path),
        'images': []}
    for label, suffix in [('pdf', 'pdf'), ('word', 'docx')]:
        raw, _ = await runtime.workspace_service.afile_bytes(scope.workspace_key, arguments['output'][label + 'Path'])
        path = f'reports/revision-2/formal.{suffix}'
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, raw)
        render[label] = await runtime.workspace_service.ahash_file(scope.workspace_key, path)
    job['render'] = render
    job['jobId'] = 'c511e4e3-6395-44a9-8948-d78e69f32659'
    context = context.model_copy(update={'job_id': job['jobId'], 'job': job})
    repository = _StateRepository(ReportingRunState.initial(report_run_id=context.workflow_run_id,
        external_run_id='external-1', thread_id='caller-thread', owner_user_id='user-1',
        payload={'reportEditorContexts': {'2': context.model_dump(mode='json', by_alias=True)}}), failure=None)
    editor = ReportEditorService(state_repository=repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service, report_tools=WorkspaceReportService(runtime.workspace_service),
        artifact_persistence=runtime.artifact_persistence, download_grants=runtime.download_grants,
        editor_grants=runtime.editor_grants, public_base_url='http://reports.test',
        trace_cursor_secret=b'trace-cursor-secret-32-bytes-ok!')
    calls = []

    def unavailable(_resolved):
        calls.append('formal_source_failure')
        raise OSError('injected formal source explanation failure')

    monkeypatch.setattr(reader_formulas, '_formal_metric_formula', unavailable)
    try:
        document = await editor.read_document(context)
        result = await editor.export_revision(context, expected_sha256=document.sha256,
            settings={'sources': True, 'cover': False, 'toc': False})
        assert calls == ['formal_source_failure']
        assert result['validation']['ok'] is False
        assert any(item['code'] == 'report_editor_lineage_unavailable'
            for item in result['validation']['issues'])
        app = FastAPI()
        app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
            for label in ('pdf', 'word'):
                response = await client.get(result[label]['downloadUrl'])
                assert response.status_code == 200
                assert len(response.content) == result[label]['size']
                assert hashlib.sha256(response.content).hexdigest() == result[label]['sha256']
                if label == 'pdf':
                    assert response.content.startswith(b'%PDF-')
                else:
                    assert response.content.startswith(b'PK')
    finally:
        await editor.aclose()
