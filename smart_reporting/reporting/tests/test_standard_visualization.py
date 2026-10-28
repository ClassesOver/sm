import json
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def fixture(form='bar'):
    chart = SimpleNamespace(chart_id='chart_001', renderer='matplotlib', interactive_path=None,
                            visual_form=form, source_path='chart.png', title='收入趋势')
    content = json.dumps({'columns': ['period', 'value'],
                          'rows': [['2025-01', 10], ['2025-02', 20]]}).encode()
    source = ChartInputFile('input.json', content)
    entry = {'chartId': chart.chart_id, 'path': source.path, 'sha256': source.sha256}
    return SimpleNamespace(charts=(chart,)), ChartInputMaterialization(files=(source,), entries=(entry,))


@pytest.mark.parametrize('form', ['bar', 'line', 'barh'])
def test_standard_template_executes_and_rejects_changed_input(tmp_path, form):
    plan, inputs = fixture(form)
    script = standard_visualization_script(plan, inputs)
    assert script is not None
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    (tmp_path / 'draw.py').write_text(script)
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()
    assert (tmp_path / 'chart.png').read_bytes().startswith(b'\x89PNG')
    (tmp_path / 'input.json').write_text('{}')
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode != 0
    assert b'identity changed' in completed.stderr


@pytest.mark.parametrize('fault', ['complex', 'identity', 'fallback', 'renderer'])
def test_unsupported_or_unverified_inputs_do_not_select_standard_route(fault):
    plan, inputs = fixture()
    if fault == 'complex':
        plan.charts[0].visual_form = '双轴组合图'
    elif fault == 'renderer':
        plan.charts[0].renderer = 'plotly'
    elif fault == 'identity':
        inputs.entries[0]['sha256'] = '0' * 64
    else:
        inputs = ChartInputMaterialization(fallback_chart_ids=frozenset({'chart_001'}))
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('failed_stage', [None, 'write_script', 'run_script', 'view_image', 'submit_script'])
async def test_standard_execution_keeps_all_existing_gates(monkeypatch, failed_stage):
    from smart_reporting.reporting.workflow.runtime import code_generation as module

    receipt = SimpleNamespace(source_file='signed-script')
    binding = SimpleNamespace(execution_receipt=receipt, visual_inspection_receipts={})

    @asynccontextmanager
    async def bind(*args):
        yield binding

    toolkit = SimpleNamespace(**{
        stage: AsyncMock(return_value={'ok': stage != failed_stage})
        for stage in ('write_script', 'run_script', 'view_image', 'submit_script')
    }, require_current_receipt=AsyncMock(), refresh_delivery_state=AsyncMock())
    monkeypatch.setattr(module, 'ReportingCodeModeToolkit', lambda *args, **kwargs: toolkit)
    runner = object.__new__(module.ReportingCodeGenerationRunner)
    runner.registry = SimpleNamespace(bind=bind)
    runner.code_mode_runtime = SimpleNamespace(shutdown=AsyncMock())
    runner.vision_reviewer = object()
    runner.lsp_manager = None
    context = SimpleNamespace(declared_output_paths=('chart.png',), code_mode_session_id='session')
    if failed_stage:
        with pytest.raises(module.ReportingError, match='标准可视化'):
            await runner.run_standard_visualization(context, object(), 'source', {})
        toolkit.require_current_receipt.assert_not_called()
    else:
        result = await runner.run_standard_visualization(context, object(), 'source', {})
        assert result.execution_receipt is receipt
        toolkit.require_current_receipt.assert_awaited_once_with(receipt)
    runner.code_mode_runtime.shutdown.assert_awaited_once_with('session')
