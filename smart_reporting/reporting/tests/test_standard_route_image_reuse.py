"""混合路由只复用当前执行的真实图片；最终仍必须取得新的执行/审查回执。"""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.code_agent.toolkit import _collect_preflight, validate_script_source
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_phase_models import _chart
from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.standard_chart_routing import (
    run_standard_chart_routes,
)

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


def identity(path):
    raw = Path(path).read_bytes()
    return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


async def mixed_case(tmp_path, monkeypatch, *, fault=None, receipt=True, forms=('line', 'custom')):
    from matplotlib.figure import Figure

    monkeypatch.chdir(tmp_path)
    _, inputs, context = setup(tmp_path, forms)
    plan = VisualizationPlanDraft(charts=tuple(_chart(f'chart-{i}.png').model_copy(update={
        'chart_id': str(i), 'visual_form': form, 'standard_form': form,
    }) for i, form in enumerate(forms)))
    drawn, reviewed, executions, snapshots = [], [], [], []
    savefig = Figure.savefig

    def save(fig, path, *args, **kwargs):
        drawn.append(str(path))
        return savefig(fig, path, *args, **kwargs)

    monkeypatch.setattr(Figure, 'savefig', save)

    async def standard(ctx, workspace, source, facts):
        validate_script_source(ctx, source)
        assert not _collect_preflight(ast.parse(source), source, 'write_script', ctx)
        final = ctx.script_path == context.script_path
        if final and fault in {'snapshot', 'input', 'component'}:
            path = (snapshots[0] if fault == 'snapshot' else
                    'input-0.json' if fault == 'input' else 'charts-chart-001.py')
            Path(path).write_bytes(b'changed identity')
        Path(ctx.script_path).write_text(source)
        exec(source, {})
        run_id = f'run-{len(executions) + 1}'
        execution = ExecutionReceipt(runId=run_id, sourceFile=identity(ctx.script_path),
            outputFiles=tuple(identity(path) for path in ctx.declared_output_paths))
        executions.append(execution)
        reviewed.extend((run_id, path) for path in ctx.declared_output_paths)
        if final and fault == 'review' and sum(item.source_file.path == context.script_path for item in executions) == 1:
            raise ReportingError('review_failed', '需要局部修复', details={'standardDiagnostic': {
                'code': 'visual_review_failed', 'details': {'sourcePath': 'chart-0.png'},
            }})
        return SimpleNamespace(script_file=execution.source_file, execution_receipt=execution if receipt else None)

    async def coding(ctx, workspace, facts, **kwargs):
        source = ('import matplotlib.pyplot as plt\nplt.figure()\n'
                  f'plt.plot([0, 1], [10, {30 if kwargs.get("diagnostic") else 20}])\n'
                  f'plt.savefig({ctx.declared_output_paths[0]!r})\nplt.close()\n')
        return await standard(ctx, workspace, source, facts)

    async def read(task, path):
        return Path(path).read_bytes(), 'application/octet-stream'

    async def write(task, path, raw, *, overwrite=False):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open('wb' if overwrite else 'xb') as stream:
            stream.write(raw)
        snapshots.append(path)

    workspace = SimpleNamespace(afile_bytes=read, awrite_bytes=write,
                                apath_exists=lambda *args: None)
    result = await run_standard_chart_routes(SimpleNamespace(run_standard_visualization=standard, run=coding),
        context, workspace, plan, inputs, {}, object())
    return result, drawn, reviewed, executions, snapshots


async def test_mixed_current_receipt_reuses_pixels_but_final_executes_and_reviews(tmp_path, monkeypatch):
    result, drawn, reviewed, executions, snapshots = await mixed_case(tmp_path, monkeypatch)
    assert drawn == ['chart-0.png', 'chart-1.png']
    assert len(snapshots) == 2
    assert len(executions) == 3
    assert result.execution_receipt.run_id == 'run-3'
    assert reviewed[-2:] == [('run-3', 'chart-0.png'), ('run-3', 'chart-1.png')]
    assert result.standard_render_proofs[0]['proof'].image_sha256 == identity('chart-0.png').sha256


@pytest.mark.parametrize('fault', ['snapshot', 'input', 'component'])
async def test_final_reuse_rejects_changed_dependency_before_issuing_receipt(tmp_path, monkeypatch, fault):
    with pytest.raises(ValueError, match='identity changed'):
        await mixed_case(tmp_path, monkeypatch, fault=fault)


async def test_missing_real_receipt_retains_compatibility_redraw(tmp_path, monkeypatch):
    result, drawn, reviewed, executions, snapshots = await mixed_case(tmp_path, monkeypatch, receipt=False)
    assert drawn == ['chart-0.png', 'chart-1.png', 'chart-0.png', 'chart-1.png']
    assert snapshots == []
    assert result.execution_receipt is None
    assert result.standard_render_proofs == ()
    assert len(executions) == 3
    assert reviewed[-2:] == [('run-3', 'chart-0.png'), ('run-3', 'chart-1.png')]


async def test_final_review_failure_repairs_only_failed_component_and_reviews_all_again(tmp_path, monkeypatch):
    result, drawn, reviewed, executions, snapshots = await mixed_case(tmp_path, monkeypatch, fault='review')
    assert drawn == ['chart-0.png', 'chart-1.png', 'chart-0.png']
    assert len(snapshots) == 3
    assert snapshots[0] != snapshots[2]
    assert Path(snapshots[0]).read_bytes() != Path(snapshots[2]).read_bytes()
    assert Path('chart-0.png').read_bytes() == Path(snapshots[2]).read_bytes()
    assert Path('chart-1.png').read_bytes() == Path(snapshots[1]).read_bytes()
    assert len(executions) == 5
    assert result.execution_receipt.run_id == 'run-5'
    assert reviewed[-2:] == [('run-5', 'chart-0.png'), ('run-5', 'chart-1.png')]
    assert result.standard_render_proofs == ()
    assert [item['routePhase'] for item in result.execution_attempts] == [
        'component_standard', 'component_coding', 'final', 'component_repair', 'final',
    ]


async def test_single_preflight_reuse_keeps_independent_proof_recompile_with_real_receipt(tmp_path, monkeypatch):
    from smart_reporting.reporting.workflow.runtime import (
        standard_chart_proof,
        standard_chart_routing,
    )

    calls = []
    compile_route = standard_chart_routing.standard_visualization_preflight
    compile_proof = standard_chart_proof.standard_visualization_preflight

    def preflight(*args):
        calls.append('route')
        return compile_route(*args)

    def proof(*args):
        calls.append('proof')
        return compile_proof(*args)

    monkeypatch.setattr(standard_chart_routing, 'standard_visualization_preflight', preflight)
    monkeypatch.setattr(standard_chart_proof, 'standard_visualization_preflight', proof)
    result, drawn, _reviewed, executions, _snapshots = await mixed_case(tmp_path, monkeypatch, forms=('line',))
    assert calls == ['route', 'proof']
    assert drawn == ['chart-0.png'] and len(executions) == 1
    assert len(result.standard_render_proofs) == 1
    proof = result.standard_render_proofs[0]['proof']
    assert proof.run_id == executions[0].run_id
    assert proof.script_sha256 == identity('charts.py').sha256
    assert proof.image_sha256 == identity('chart-0.png').sha256
