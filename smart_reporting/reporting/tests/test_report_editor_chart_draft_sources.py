"""AI 改图接受后，正文来源入口必须绑定当前改图而非已移除的底图。"""

import hashlib
import asyncio
import json
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.chart_edits import (
    ChartEditChartMeta, ChartEditFileRef, ChartEditPage, ChartEditRecord,
    append_chart_edit_record, chart_edit_page_chart_id, chart_edit_page_src, chart_edits_registry_path,
)
from smart_reporting.reporting.models import ReportingError
from .test_report_editor_chart_ai import _make_editor_with_chart


async def _edited_chart(tmp_path, *, pages=1):
    fixture = await _make_editor_with_chart(tmp_path)
    editor, context = fixture.editor, fixture.context
    index = await editor.trace.require_index(context)
    edit_id = 'cedit-12345678'
    directory = f'reports/revision-1/chart-edits/{edit_id}'
    script = b'# verified chart script'
    await fixture.workspace.awrite_bytes(fixture.thread_id, f'{directory}/chart.py', script)
    chart = ChartEditChartMeta(title='收入对比', altText='收入对比', visualForm='横向条形图', datasetIds=fixture.chart.dataset_ids)
    page_records = []
    for number in range(1, pages + 1):
        path = f'{directory}/' + ('chart.png' if number == 1 else f'chart--page-{number}.png')
        await fixture.workspace.awrite_bytes(fixture.thread_id, path, fixture.chart_bytes)
        page_records.append(ChartEditPage(pageNumber=number, image=ChartEditFileRef(
            path=path, size=len(fixture.chart_bytes), sha256=hashlib.sha256(fixture.chart_bytes).hexdigest(),
        ), chart=chart))
    files = {file.resource_id: file for file in index.files}
    record = ChartEditRecord(
        editId=edit_id, chartId='chart_001', baseImagePath=fixture.chart_path,
        baseImageSha256=fixture.chart.sha256, instruction='改成横向条形图', level=('L1',),
        image=page_records[0].image, chart=chart, pages=tuple(page_records),
        script=ChartEditFileRef(path=f'{directory}/chart.py', size=len(script), sha256=hashlib.sha256(script).hexdigest()),
        plotDataFiles=tuple(ChartEditFileRef(path=files[key].path, size=files[key].size, sha256=files[key].sha256)
                           for key in index.chart_traces[0].plot_data_file_resource_ids),
        createdAt='2026-10-30T00:00:00Z', userId=context.scope['userId'],
    )
    await append_chart_edit_record(fixture.workspace, fixture.thread_id, context.markdown_path, record)
    original = await fixture.workspace.aread_text(fixture.thread_id, context.markdown_path)
    images = '\n\n'.join(f'![收入对比]({chart_edit_page_src(context.markdown_path, edit_id, page.page_number)})'
                           for page in record.pages)
    markdown = original.replace('![Revenue](chart-001.png)', images)
    return fixture, record, markdown


@pytest.mark.anyio
@pytest.mark.parametrize('pages', [1, 2])
async def test_accepted_chart_keeps_exact_body_source_before_autosave(tmp_path, pages):
    fixture, record, markdown = await _edited_chart(tmp_path, pages=pages)
    result = await fixture.editor.trace.validate(fixture.context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert len(result['charts']) == pages
    for page, chart in zip(record.pages, result['charts'], strict=True):
        assert chart['status'] == 'valid'
        assert chart['chartId'] == chart_edit_page_chart_id(record, page.page_number)
        assert chart['locationSource'] == chart_edit_page_src(fixture.context.markdown_path, record.edit_id, page.page_number)
        assert chart['editId'] == record.edit_id
        source = await fixture.editor.trace_chart_source(fixture.context, SimpleNamespace(capabilities=None), chart['chartId'], edit_id=record.edit_id)
        assert source['image']['sha256'] == page.image.sha256
        assert source['datasetIds'] == list(page.chart.dataset_ids)
        assert source['plotData']
    assert '[[citation:citation_001]]' in markdown


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['image', 'script', 'partial_pages', 'registry'])
async def test_invalid_chart_edit_never_gets_a_body_source_binding(tmp_path, fault):
    fixture, record, markdown = await _edited_chart(tmp_path, pages=2)
    if fault == 'partial_pages':
        markdown = markdown.replace(f'![收入对比]({chart_edit_page_src(fixture.context.markdown_path, record.edit_id, 2)})', '')
    elif fault == 'registry':
        await fixture.workspace.awrite_bytes(fixture.thread_id, chart_edits_registry_path(fixture.context.markdown_path), b'{broken', overwrite=True)
    else:
        identity = record.pages[1].image if fault == 'image' else record.script
        await fixture.workspace.awrite_bytes(fixture.thread_id, identity.path, b'tampered', overwrite=True)
    result = await fixture.editor.trace.validate(fixture.context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert all(chart['status'] == 'unbound' for chart in result['charts'])
    assert result['sourceIssues']
    if fault != 'partial_pages':
        with pytest.raises(ReportingError, match='snapshot_integrity_failed'):
            await fixture.editor.trace.chart_source(fixture.context, 'chart_001', edit_id=record.edit_id)


@pytest.mark.anyio
async def test_body_source_selects_adopted_edit_not_latest_generated_edit(tmp_path):
    fixture, first, markdown = await _edited_chart(tmp_path)
    image_bytes = fixture.chart_bytes + b'next-version'
    image = first.image.model_copy(update={
        'path': first.image.path.replace('cedit-12345678', 'cedit-abcdefgh'),
        'size': len(image_bytes), 'sha256': hashlib.sha256(image_bytes).hexdigest(),
    })
    await fixture.workspace.awrite_bytes(fixture.thread_id, image.path, image_bytes)
    second = first.model_copy(update={
        'edit_id': 'cedit-abcdefgh', 'image': image,
        'pages': (first.pages[0].model_copy(update={'image': image}),),
    })
    await append_chart_edit_record(fixture.workspace, fixture.thread_id, fixture.context.markdown_path, second)
    for record, draft in ((first, markdown), (second, markdown.replace('cedit-12345678', 'cedit-abcdefgh'))):
        result = await fixture.editor.trace.validate(fixture.context, draft, hashlib.sha256(draft.encode()).hexdigest())
        assert result['charts'][0]['editId'] == record.edit_id
        assert result['charts'][0]['status'] == 'valid'
        source = await fixture.editor.trace.chart_source(fixture.context, 'chart_001', edit_id=record.edit_id)
        assert source['image']['sha256'] == record.image.sha256
    for chart_id, edit_id in (('other-chart', first.edit_id), ('chart_001', 'cedit-unknown1')):
        with pytest.raises(ReportingError, match='source_missing'):
            await fixture.editor.trace.chart_source(fixture.context, chart_id, edit_id=edit_id)


@pytest.mark.anyio
@pytest.mark.parametrize('path_kind', ['other_edit', 'original'])
async def test_explicit_edit_source_never_falls_back_to_original_chart(tmp_path, path_kind):
    fixture, record, _markdown = await _edited_chart(tmp_path)
    path = record.image.path.replace('cedit-12345678', 'cedit-abcdefgh') if path_kind == 'other_edit' else fixture.chart_path
    forged = record.model_copy(update={'pages': (), 'image': record.image.model_copy(update={'path': path})})
    registry = {'version': 1, 'records': [forged.model_dump(mode='json', by_alias=True)]}
    await fixture.workspace.awrite_bytes(fixture.thread_id, chart_edits_registry_path(fixture.context.markdown_path), json.dumps(registry).encode(), overwrite=True)
    with pytest.raises(ReportingError, match='snapshot_integrity_failed'):
        await fixture.editor.trace.chart_source(fixture.context, 'chart_001', edit_id=record.edit_id)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', [None, 'sha256', 'dataset_ids'])
async def test_edited_source_matches_publication_id_by_unique_image_identity(tmp_path, fault):
    fixture, record, markdown = await _edited_chart(tmp_path)
    manifest = await fixture.editor.trace.load_manifest(fixture.context)
    chart = manifest.charts[0].model_copy(update={'chart_id': 'publication-chart-001'})
    if fault:
        chart = chart.model_copy(update={fault: '0' * 64 if fault == 'sha256' else ('other-dataset',)})
    charts = (chart,)
    manifest = manifest.model_copy(update={'charts': charts})
    content = manifest.model_dump_json(by_alias=True).encode()
    await fixture.workspace.awrite_bytes(fixture.thread_id, fixture.context.artifact_manifest.path, content, overwrite=True)
    identity = fixture.context.artifact_manifest.model_copy(update={'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    context = fixture.context.model_copy(update={'artifact_manifest': identity})
    result = await fixture.editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    if fault is None:
        assert result['charts'][0]['status'] == 'valid'
        source = await fixture.editor.trace.chart_source(context, 'chart_001', edit_id=record.edit_id)
        assert source['image']['sha256'] == record.image.sha256
    else:
        assert all(chart['status'] == 'unbound' for chart in result['charts'])
        assert result['sourceIssues']
        with pytest.raises(ReportingError, match='snapshot_integrity_failed'):
            await fixture.editor.trace.chart_source(context, 'chart_001', edit_id=record.edit_id)


@pytest.mark.anyio
async def test_unregistered_illustration_does_not_erase_valid_edited_source(tmp_path):
    fixture, record, markdown = await _edited_chart(tmp_path)
    markdown += '\n\n![用户说明图](extra.png)'
    result = await fixture.editor.trace.validate(fixture.context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['charts'][0]['status'] == 'valid'
    assert result['charts'][0]['editId'] == record.edit_id
    assert result['charts'][1]['status'] == 'unbound'
    assert result['charts'][1]['locationSource'] == 'extra.png'


@pytest.mark.anyio
async def test_rebound_chart_source_uses_registered_new_plot_data(tmp_path):
    from smart_reporting.report_editor.chart_ai import ChartAIEditRequest
    from smart_reporting.report_editor.chart_edits import load_chart_edit_records
    from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
    from .test_report_editor_chart_ai import FakeRunner, _planner, _service

    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    binding = ChartDataBinding(
        analysisId='analysis_001', factPath='报表/智能分析/report-1/facts/revision-1/analysis_001.json',
        dataPath='metrics[0].periodValues', fields=('period', 'value'), role='main',
    )
    service = _service(fixture, FakeRunner(fixture.chart_bytes), _planner(level=('L2',), data_bindings=(binding,)))
    try:
        started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001', ChartAIEditRequest(
            instruction='换成逐月收入对比', baseImagePath=fixture.chart_path, expectedSha256=fixture.chart.sha256,
        ))
        for _ in range(400):
            status = service.edit_status(fixture.context, 'chart_001', started['editId'])
            if status['status'] in {'succeeded', 'failed'}:
                break
            await asyncio.sleep(0.02)
        assert status['status'] == 'succeeded', status
    finally:
        await service.aclose()
    record, = await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)
    original = await fixture.workspace.aread_text(fixture.thread_id, fixture.context.markdown_path)
    draft = original.replace('chart-001.png', chart_edit_page_src(fixture.context.markdown_path, record.edit_id, 1))
    result = await fixture.editor.trace.validate(fixture.context, draft, hashlib.sha256(draft.encode()).hexdigest())
    assert result['charts'][0]['status'] == 'valid'
    source = await fixture.editor.trace.chart_source(fixture.context, 'chart_001', edit_id=record.edit_id)
    assert source['plotData'][0]['columns'] == ['period', 'value']
    assert source['plotData'][0]['rows'] == [['2025-07', 1200.0], ['2025-08', 1500.0], ['2025-09', 1800.0]]
