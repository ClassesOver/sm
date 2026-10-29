"""Reset presentation parameters without resetting the verified data cohort."""

import json
from types import SimpleNamespace

import pytest
from agno.tools.code import CodeMode
from pydantic import ValidationError

from smart_reporting.report_editor.chart_ai import (
    ChartAIEditRequest,
    ChartEditPlan,
    ChartStandardEditRequest,
)
from smart_reporting.report_editor.chart_edits import load_chart_edit_records
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    _await_edit,
    _make_editor_with_chart,
    _service,
)
from smart_reporting.reporting.tests.test_report_editor_standard_charts import StandardRunner
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner


def payload(**kwargs):
    return {'standard': {'standardForm': 'funnel'}, 'baseImagePath': 'reports/chart.png',
            'expectedSha256': 'a' * 64, **kwargs}


def test_parameter_inheritance_defaults_to_existing_behavior_and_accepts_explicit_reset():
    assert ChartStandardEditRequest.model_validate(payload()).inherit_previous_standard is True
    assert ChartStandardEditRequest.model_validate(payload(inheritPreviousStandard=False)).inherit_previous_standard is False
    with pytest.raises(ValidationError):
        ChartAIEditRequest.model_validate({'instruction': '自由改图', 'inheritPreviousStandard': False})


@pytest.mark.parametrize('value', ['false', 'true', 0, 1, None, []])
def test_reset_requires_a_real_boolean(value):
    with pytest.raises(ValidationError):
        ChartStandardEditRequest.model_validate(payload(inheritPreviousStandard=value))


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_native_switch_can_reset_pagination_without_losing_rebound_data(tmp_path):
    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    requests = []

    async def planner(request):
        requests.append(request)
        assert len(requests) == 1, '标准直达续改不得调用规划模型'
        binding = next(item for item in request['registeredBindings'] if item['dataPath'] == 'metrics[0].periodValues')
        return ChartEditPlan(level=['L2'], title='完整收入', altText='冻结期间数据', visualForm='barh',
            drawInstruction='按期间完整分页',
            dataBindings=[{key: binding[key] for key in ('analysisId', 'factPath', 'dataPath', 'fields', 'role')}],
            standard={'standardForm': 'barh', 'standardValueFields': ['value'],
                      'standardStyle': {'palette': 'viridis'}, 'standardPagination': {'pageSize': 1}})

    service = _service(fixture, StandardRunner(fixture.chart_bytes), planner=planner, timeout_seconds=60)
    runtime = lsp = None
    try:
        started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
            ChartAIEditRequest(instruction='换绑冻结期间并完整分页'))
        initial = await _await_edit(service, fixture.context, 'chart_001', started['editId'])
        assert initial['status'] == 'succeeded', initial
        original = (await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path))[-1]
        assert original.data_origin == 'rebound' and len(original.pages) == 3
        original_data = [(await fixture.workspace.afile_bytes(fixture.thread_id, ref.path))[0] for ref in original.plot_data_files]

        def forbidden_model(**kwargs):
            raise AssertionError('不应调用编码模型')

        identity = fixture.editor.workspace_registry.get(fixture.thread_id)
        runtime = ReportingCodeModeRuntime(CodeMode(snapshot=False, allow_shell=True, cwd=str(identity.root), timeout=45, max_kernels=1))
        lsp = ReportingLspProcessManager()
        native = ReportingCodeGenerationRunner(forbidden_model, runtime, lsp, vision_reviewer=None)
        service.runner = native
        base = original.pages[1].image
        request = {'standard': {'standardForm': 'funnel'}, 'baseImagePath': base.path,
                   'expectedSha256': base.sha256, 'previousEditId': original.edit_id}
        # The default keeps existing parameters, so incompatible pagination is
        # diagnosed rather than silently discarded or sent to a model.
        inherited = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
            ChartStandardEditRequest.model_validate(request))
        rejected = await _await_edit(service, fixture.context, 'chart_001', inherited['editId'])
        assert rejected['status'] == 'failed', rejected
        assert len(await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)) == 1

        reset = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
            ChartStandardEditRequest.model_validate({**request, 'inheritPreviousStandard': False}))
        result = await _await_edit(service, fixture.context, 'chart_001', reset['editId'])
        assert result['status'] == 'succeeded', result
        assert result['planningRoute'] == 'direct' and result['renderingRoute'] == 'standard'
        changed = (await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path))[-1]
        assert changed.level == ('L1',) and changed.data_origin == 'rebound'
        assert changed.data_bindings == original.data_bindings and changed.chart.dataset_ids == original.chart.dataset_ids
        assert changed.standard_parameters['standardForm'] == 'funnel'
        assert changed.chart.visual_form == result['changes']['visualForm'] == 'funnel'
        assert (await service.edit_record(fixture.context, changed.edit_id))['visualForm'] == 'funnel'
        assert changed.standard_parameters['standardPagination'] is None
        assert changed.standard_parameters['standardStyle']['palette'] == 'report'
        assert changed.chart.title == '完整收入' and changed.chart.alt_text == '冻结期间数据'
        contents = [(await fixture.workspace.afile_bytes(fixture.thread_id, ref.path))[0] for ref in changed.plot_data_files]
        assert contents == original_data and len(json.loads(contents[0])['rows']) == 3
        assert len(result['deterministicImageChecks']) == 1 and len(requests) == 1
        assert native.registry.active_count == 0 and not runtime._logged_connections
        missing_form = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), 'chart_001',
            ChartStandardEditRequest.model_validate({**request, 'standard': {}, 'inheritPreviousStandard': False}))
        invalid = await _await_edit(service, fixture.context, 'chart_001', missing_form['editId'])
        assert invalid['status'] == 'failed' and invalid['error']['code'] == 'report_editor_standard_form_required'
        assert len(await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)) == 2
    finally:
        await service.aclose()
        if lsp is not None:
            await lsp.aclose()
        if runtime is not None:
            await runtime.aclose()
