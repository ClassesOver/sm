"""共同数据修订服务使用登记输入、不可变文件及真实状态reducer。"""
import asyncio
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.service import ReportEditorContext
from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_data_revision_state import state_with_report
from smart_reporting.reporting.tests.test_report_data_snapshot_edits import case
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
from smart_reporting.reporting.workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDraft
from smart_reporting.reporting.workflow.state import ReportingStateReducer
from smart_reporting.workspace import WorkspacePathConflict

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


def service_case(*, paginated=False):
    from smart_reporting.report_editor.data_revisions import ReportDataRevisionService
    snapshot, contents = case()
    state = state_with_report()
    context = ReportEditorContext.model_validate(state.payload['reportEditorContexts']['1'])
    files, refs, traces, charts = {}, [], [], []
    markdown = b'# Report\n\n![Revenue](chart_a.png)\n\n![Cost](chart_b.png)\n\n![Other](chart_c.png)\n'
    # 宿主只接受已登记图片；此层冻结不重新签发视觉通过。
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _png_bytes
    png = _png_bytes()

    def ref(path, raw, resource=None):
        value = SimpleNamespace(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if resource:
            value.resource_id = resource
            refs.append(value)
        files[path] = raw
        return value

    markdown_ref = ref(context.markdown_path, markdown)
    for table_id, raw in contents.items():
        ref(snapshot['tables'][table_id]['file']['path'], raw, table_id)
    for chart_id, table_id in [('chart_a', 'table_a'), ('chart_b', 'table_b'), ('chart_c', 'table_c')]:
        image = ref(f'reports/{chart_id}.png', png, f'image_{chart_id}')
        charts.append(SimpleNamespace(chart_id=chart_id, **{key: getattr(image, key) for key in ('path', 'size', 'sha256')}))
        proof = None
        if paginated and chart_id == 'chart_a':
            plan = ChartDraft(chartId=chart_id, sourcePath=image.path, title='逐月营业收入',
                altText='两个月的营业收入', citationIds=['citation'], metricCodes=['revenue'],
                currentPeriod='2026-10', sourceDatasetId='dataset', aggregationGrain='month',
                visualForm='barh', standardValueFields=['value'], standardPagination={'pageSize': 1},
                dataBindings=[{'analysisId': 'analysis_001', 'factPath': 'facts/analysis_001.json',
                    'dataPath': 'metrics[0].periodValues', 'fields': ['period', 'value'], 'role': 'measure'}])
            proof = SimpleNamespace(plan={'charts': [plan.model_dump(mode='json', by_alias=True)]})
        traces.append(SimpleNamespace(chart_id=chart_id, image_file_resource_id=f'image_{chart_id}',
            plot_data_file_resource_ids=(table_id,), standard_render_proof=proof))

    class Repository:
        async def get(self, run_id):
            return self.state

        async def apply(self, run_id, command, *, expected_version):
            result = ReportingStateReducer.apply(self.state, command, expected_version)
            self.state = result.state
            return result

    repository = Repository()
    repository.state = state

    async def restore(expected):
        if expected.digest() != context.digest():
            raise ReportingError('report_editor_forbidden', '报告作用域不匹配。')
        return context

    async def load(expected):
        return SimpleNamespace(markdown=markdown_ref, charts=charts), SimpleNamespace(files=refs, chart_traces=traces)

    async def read(thread, path):
        return files[path], 'application/octet-stream'

    async def write(thread, path, raw, *, overwrite=False):
        if path in files and not overwrite:
            raise WorkspacePathConflict('exists')
        files[path] = raw

    editor = SimpleNamespace(_restore=restore, state_repository=repository,
        trace=SimpleNamespace(load_manifest_and_index=load),
        workspace=SimpleNamespace(afile_bytes=read, awrite_bytes=write))
    editor.workspace.workspace = lambda thread: editor.workspace
    editor.workspace_registry = SimpleNamespace(get=lambda thread: SimpleNamespace(root='/tmp/data-revision-test'))
    return ReportDataRevisionService(editor=editor), context, repository, files, editor


async def test_freeze_registers_baseline_and_reads_only_registered_historical_snapshot():
    service, context, repository, files, _editor = service_case()
    original = dict(files)
    baseline = await service.freeze(context)
    assert baseline['status'] == 'ready'
    assert len(baseline['tables']) == 3 and len(baseline['charts']) == 3
    assert repository.state.payload['reportDataRevisions']['report-1']['latestSnapshotId'] == baseline['snapshotId']
    for table in baseline['tables'].values():
        assert table['file']['path'] != table['originalFile']['path']
        assert files[table['file']['path']] == original[table['originalFile']['path']]
    files['inputs/table_a.json'] = b'original path later changed'
    assert await service.read(context, baseline['snapshotId']) == baseline
    with pytest.raises(ReportingError):
        await service.read(context, 'not-registered')


async def test_prepare_writes_new_inputs_without_activating_or_overwriting_parent():
    service, context, repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    before = deepcopy(baseline), dict(files)
    candidate = await service.prepare(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]})
    assert candidate['invalidatedChartIds'] == ['chart_a', 'chart_b']
    assert repository.state.payload['reportDataRevisions']['report-1']['latestSnapshotId'] == baseline['snapshotId']
    assert await service.read(context, baseline['snapshotId']) == before[0]
    assert all(files[key] == raw for key, raw in before[1].items())
    for key in ['table_a', 'table_b']:
        raw = files[candidate['tables'][key]['file']['path']]
        assert json.loads(raw)['rows'][1][1] == 180
    with pytest.raises(ReportingError, match='重绘'):
        await service.commit(context, candidate)


async def test_frozen_manifest_or_table_tampering_never_activates_candidate():
    service, context, repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    before = deepcopy(repository.state)
    table_path = baseline['tables']['table_a']['file']['path']
    files[table_path] += b' '
    with pytest.raises(ReportingError):
        await service.prepare(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
            {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
        ]})
    assert repository.state == before
    record = before.payload['reportDataRevisions']['report-1']['revisions'][baseline['snapshotId']]
    files[record['manifest']['path']] = canonical_json_bytes({'snapshotId': 'forged'})
    with pytest.raises(ReportingError):
        await service.read(context, baseline['snapshotId'])


def attach_runner(service, files, *, fault=None, barrier=None):
    calls = []

    def identity(path):
        raw = files[path]
        return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    async def execute(context, workspace, facts, source='pass\n'):
        chart_id = facts['visualizationPlan']['charts'][0]['chartId']
        inputs = [json.loads(files[item['path']]) for item in facts['chartInputs']]
        calls.append((chart_id, inputs, context))
        if barrier:
            await barrier()
        if fault == 'draw':
            raise ReportingError('draw_failed', '重绘失败。')
        files[context.script_path] = source.encode()
        from smart_reporting.reporting.tests.test_report_editor_chart_ai import _png_bytes
        raw = _png_bytes()
        for output in context.declared_output_paths:
            files[output] = raw
        receipt = ExecutionReceipt(runId=f'run-{len(calls)}-{context.code_mode_session_id}',
            sourceFile=identity(context.script_path), outputFiles=tuple(identity(path) for path in context.declared_output_paths))
        reviews = tuple(ChartVisualInspectionReceipt(sourcePath=path, sha256=identity(path).sha256,
            reviewed=True, requiresRevision=False, modelId='test-independent-reviewer') for path in context.declared_output_paths)
        if fault == 'old_review':
            reviews = (reviews[0].model_copy(update={'sha256': 'f' * 64}),)
        if fault == 'missing_page_review':
            reviews = tuple(item for item in reviews if '--page-' not in item.source_path)
        if fault == 'visual_warning':
            reviews = (reviews[0].model_copy(update={'requires_revision': True, 'warnings': ('长标签需要人工调整。',)}),)
        return SimpleNamespace(script_file=identity(context.script_path), execution_receipt=receipt,
            visual_inspection_receipts=reviews, standard_render_proofs=())

    async def standard(context, workspace, source, facts):
        return await execute(context, workspace, facts, source)

    async def coding(context, workspace, facts, **kwargs):
        return await execute(context, workspace, facts)

    service.chart_service = SimpleNamespace(runner=SimpleNamespace(run=coding, run_standard_visualization=standard))
    return calls


async def test_revise_redraws_only_affected_charts_and_commits_fresh_receipts():
    service, context, repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    calls = attach_runner(service, files)
    revised = await service.revise(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]})
    assert [item[0] for item in calls] == ['chart_a', 'chart_b']
    assert all(item[1][0]['rows'][1][1] == 180 for item in calls)
    assert revised['status'] == 'ready'
    assert revised['charts']['chart_c'] == baseline['charts']['chart_c']
    for key in ['chart_a', 'chart_b']:
        chart = revised['charts'][key]
        assert chart['sourceSnapshotId'] == revised['snapshotId']
        assert chart['chartRevision'] == revised['snapshotId']
        assert chart['executionReceipt']['runId'].startswith('run-')
        assert chart['visualReceipts'][0]['sha256'] == chart['image']['sha256']
    assert (await service.read(context)) == revised
    assert (await service.read(context, baseline['snapshotId'])) == baseline
    assert repository.state.payload['reportDataRevisions']['report-1']['latestSnapshotId'] == revised['snapshotId']


async def test_residual_visual_problems_are_visible_soft_warnings():
    service, context, _repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    attach_runner(service, files, fault='visual_warning')
    revised = await service.revise(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]})
    shown = await service.presentation(context, revised)
    assert shown['status'] == 'ready'
    warnings = [item for item in shown['warnings'] if item['code'] == 'report_data_chart_review_required']
    assert {item['chartId'] for item in warnings} == {'chart_a', 'chart_b'}
    assert all('长标签需要人工调整' in item['message'] for item in warnings)


@pytest.mark.parametrize('fault', [None, 'missing_page_review'])
async def test_revise_expands_verified_standard_pages_and_requires_current_receipts_for_each_page(fault):
    service, context, _repository, files, _editor = service_case(paginated=True)
    baseline = await service.freeze(context)
    calls = attach_runner(service, files, fault=fault)
    request = {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]}
    if fault:
        with pytest.raises(ReportingError) as caught:
            await service.revise(context, request)
        assert caught.value.code == 'report_data_redraw_unverified'
        assert await service.read(context) == baseline
        return
    revised = await service.revise(context, request)
    chart = revised['charts']['chart_a']
    images = [chart['image'], *(page['image'] for page in chart['pages'])]
    assert [image['path'].rsplit('/', 1)[-1] for image in images] == ['chart.png', 'chart--page-2.png']
    assert {(item['sourcePath'], item['sha256']) for item in chart['visualReceipts']} == {
        (image['path'], image['sha256']) for image in images
    }
    assert set(calls[0][2].declared_output_paths) == {image['path'] for image in images}
    assert revised['charts']['chart_c'] == baseline['charts']['chart_c']
    assert await service.read(context, baseline['snapshotId']) == baseline


async def test_new_editor_revision_cannot_silently_reuse_old_revision_snapshot():
    service, context, _repository, _files, editor = service_case()
    await service.freeze(context)
    newer = context.model_copy(update={'revision': 2})

    async def restore(expected):
        return newer

    editor._restore = restore
    with pytest.raises(ReportingError) as caught:
        await service.freeze(newer)
    assert caught.value.code == 'report_data_base_revision_conflict'


@pytest.mark.parametrize('fault', ['draw', 'old_review'])
async def test_redraw_failure_or_old_review_preserves_latest_and_original_files(fault):
    service, context, repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    originals = dict(files)
    attach_runner(service, files, fault=fault)
    with pytest.raises(ReportingError):
        await service.revise(context, {'expectedSnapshotId': baseline['snapshotId'], 'edits': [
            {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
        ]})
    assert repository.state.payload['reportDataRevisions']['report-1']['latestSnapshotId'] == baseline['snapshotId']
    assert all(files[path] == raw for path, raw in originals.items())


async def test_concurrent_revisions_have_one_cas_winner_without_overwriting_history():
    service, context, repository, files, _editor = service_case()
    baseline = await service.freeze(context)
    entered, ready = [0], asyncio.Event()

    async def barrier():
        entered[0] += 1
        if entered[0] >= 2:
            ready.set()
        await ready.wait()

    attach_runner(service, files, barrier=barrier)
    results = await asyncio.gather(*(service.revise(context, {
        'expectedSnapshotId': baseline['snapshotId'], 'edits': [
            {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': value},
        ],
    }) for value in [180, 190]), return_exceptions=True)
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, Exception) for item in results) == 1
    conflict = next(item for item in results if isinstance(item, Exception))
    assert isinstance(conflict, ReportingError) and conflict.code == 'report_data_revision_conflict'
    history = repository.state.payload['reportDataRevisions']['report-1']
    assert len(history['revisions']) == 2
    assert (await service.read(context, baseline['snapshotId'])) == baseline
