"""A successfully expanded one-page chart must not accumulate host page suffixes."""

import json
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.chart_ai import ChartAIEditRequest, ChartEditPlan
from smart_reporting.report_editor.chart_edits import (
    chart_edits_registry_path,
    load_chart_edit_records,
)
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    _await_edit,
    _make_editor_with_chart,
    _service,
)
from smart_reporting.reporting.tests.test_report_editor_standard_charts import StandardRunner


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('legacy_record', [False, True])
async def test_one_page_pagination_keeps_business_caption_across_repeated_edits(tmp_path, legacy_record):
    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    requests = []

    async def planner(request):
        requests.append(request)
        if len(requests) > 1:
            return ChartEditPlan(level=['L1'], drawInstruction='保留数据和分页，只改变配色', standard={})
        binding = next(item for item in request['registeredBindings'] if item['dataPath'] == 'metrics[0].periodValues')
        return ChartEditPlan(level=['L2'], title='收入趋势', altText='完整冻结期间收入', visualForm='barh',
            drawInstruction='每页最多三条，全部数据显示',
            dataBindings=[{key: binding[key] for key in ('analysisId', 'factPath', 'dataPath', 'fields', 'role')}],
            standard={'standardValueFields': ['value'], 'standardPagination': {'pageSize': 3}})

    runner = StandardRunner(fixture.chart_bytes)
    service = _service(fixture, runner, planner=planner, timeout_seconds=60)
    previous = None
    try:
        for number in range(3):
            started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
                ChartAIEditRequest(instruction='保持完整单页，继续调整',
                    previousEditId=previous.edit_id if previous else None,
                    baseImagePath=previous.image.path if previous else None,
                    expectedSha256=previous.image.sha256 if previous else None))
            response = await _await_edit(service, fixture.context, 'chart_001', started['editId'])
            assert response['status'] == 'succeeded', response
            assert len(response['pages']) == 1
            records = await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)
            previous = records[-1]
            assert previous.chart.title == '收入趋势（第1/1页）'
            assert previous.chart.alt_text == '完整冻结期间收入（第1/1页）'
            assert previous.standard_parameters['standardPagination']['pageSize'] == 3
            content, _ = await fixture.workspace.afile_bytes(fixture.thread_id, previous.plot_data_files[0].path)
            assert len(json.loads(content)['rows']) == 3
            if number == 0 and legacy_record:
                # Simulate the old registry shape which omitted pages for a
                # successfully expanded 1/1 chart, keeping every signed ref.
                path = chart_edits_registry_path(fixture.context.markdown_path)
                payload = json.loads(await fixture.workspace.aread_text(fixture.thread_id, path))
                payload['records'][-1].pop('pages', None)
                await fixture.workspace.awrite_text(fixture.thread_id, path, json.dumps(payload, ensure_ascii=False), overwrite=True)
            elif not legacy_record:
                assert len(previous.pages) == 1
        assert len(runner.standard_calls) == 3 and not runner.calls
        assert requests[-1]['baseTitle'] == '收入趋势'
        assert requests[-1]['baseAltText'] == '完整冻结期间收入'
    finally:
        await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_pending_unsupported_pagination_does_not_erase_a_literal_caption_suffix(tmp_path):
    fixture = await _make_editor_with_chart(tmp_path)
    requests = []

    async def planner(request):
        requests.append(request)
        if len(requests) == 1:
            return ChartEditPlan(level=['L1'], title='业务页码（第1/1页）', altText='原有页码（第1/1页）',
                visualForm='line', drawInstruction='保留原有说明',
                standard={'standardValueFields': ['revenue'], 'standardPagination': {'pageSize': 3}})
        return ChartEditPlan(level=['L1'], drawInstruction='保持图题，只改变颜色', standard={})

    service = _service(fixture, StandardRunner(fixture.chart_bytes), planner=planner)
    previous = None
    try:
        for _ in range(2):
            started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
                ChartAIEditRequest(instruction='保留页码说明', previousEditId=previous.edit_id if previous else None))
            response = await _await_edit(service, fixture.context, 'chart_001', started['editId'])
            assert response['status'] == 'succeeded', response
            previous = (await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path))[-1]
            assert not previous.pages
            assert previous.chart.title == '业务页码（第1/1页）'
            assert previous.chart.alt_text == '原有页码（第1/1页）'
        assert requests[-1]['baseTitle'] == '业务页码（第1/1页）'
    finally:
        await service.aclose()
