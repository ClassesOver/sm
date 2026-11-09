"""共同数据修订：只从已冻结表生成候选；重绘完成前不激活新快照。"""
import asyncio
import hashlib
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath
from types import SimpleNamespace
from uuid import uuid4

from agno.run import RunContext
from loguru import logger
from markdown_it import MarkdownIt

from ..reporting.code_agent.context import ExecutionReceipt, ReportingCodingTaskContext
from ..reporting.contract import safe_relative_posix_path
from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import canonical_json_bytes
from ..reporting.workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from ..reporting.workflow.runtime.chart_inputs import ChartInputFile, ChartInputMaterialization
from ..reporting.workflow.runtime.phase_models import ChartDraft, VisualizationPlanDraft
from ..reporting.workflow.runtime.standard_chart_pagination import expand_standard_pagination
from ..reporting.workflow.runtime.standard_chart_routing import run_standard_chart_routes
from ..reporting.workflow.state import ReportingCommand, ReportingStateError
from ..workspace import WorkspacePathConflict
from .data_revision_contract import ReportDataEditRequest, ReportDataExport, ReportDataRevision
from .revisions import apply_editor_command, next_manual_revision


def _same_cell(left, right):
    # JSON数值150/150.0可等价；布尔值不能与0/1混同。
    return type(left) is type(right) and left == right or (
        type(left) in (int, float) and type(right) in (int, float) and left == right
    )


def _source_key(document):
    source = document.get('source', {})
    if not all(isinstance(source.get(key), str) and source[key] for key in ('analysisId', 'path', 'dataPath')):
        raise ReportingError('report_data_source_invalid', '作图表缺少可核对的冻结来源。')
    return canonical_json_bytes({key: value for key, value in source.items()
        if key not in {'origin', 'snapshotId', 'parentFile'}})


def prepare_data_revision(snapshot, table_bytes, request, *, snapshot_id, output_root):
    """按冻结来源传播显式单元格编辑，不猜派生业务公式，不写入或提交状态。

    返回候选清单及需另存的新表字节。调用方必须先核验当前快照清单身份；本函数
    再核验清单中每张输入表的实际字节。所有受影响图在候选中丢弃旧回执和旧图片
    的当前身份，只有重新执行/审查后才能提交。原图仅以previousImage保留追溯。
    """
    request = ReportDataEditRequest.model_validate(request)
    if request.expected_snapshot_id != snapshot['snapshotId']:
        raise ReportingError('report_data_revision_conflict', '数据快照已变化，请重新载入。')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', snapshot_id) or snapshot_id == snapshot['snapshotId']:
        raise ValueError('新快照身份无效')
    root = safe_relative_posix_path(output_root, '数据快照路径无效')
    documents = {}
    for table_id, table in snapshot['tables'].items():
        ref = FileIdentity.model_validate(table['file'])
        raw = table_bytes.get(table_id)
        if not isinstance(raw, bytes) or len(raw) != ref.size or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ReportingError('report_data_source_changed', '冻结作图表身份已变化。')
        document = json.loads(raw)
        columns, rows = document.get('columns'), document.get('rows')
        if (document.get('schema') != 'chart-input/v1' or not isinstance(columns, list)
                or not columns or not all(isinstance(key, str) for key in columns)
                or len(columns) != len(set(columns)) or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
            raise ReportingError('report_data_table_invalid', '冻结作图表结构不受支持。')
        documents[table_id] = document
    sources = {key: _source_key(document) for key, document in documents.items()}
    updated, touched = {}, set()
    for edit in request.edits:
        selected = documents.get(edit.table_id)
        if selected is None or edit.column not in selected['columns'] or edit.row >= len(selected['rows']):
            raise ReportingError('report_data_cell_unknown', '编辑单元格不属于已登记作图表。')
        index = selected['columns'].index(edit.column)
        original = selected['rows'][edit.row][index]
        if not _same_cell(original, edit.expected_value):
            raise ReportingError('report_data_revision_conflict', '单元格值已变化，请重新载入。')
        if _same_cell(original, edit.value):
            continue
        for table_id, document in documents.items():
            if sources[table_id] != sources[edit.table_id] or edit.column not in document['columns']:
                continue
            column = document['columns'].index(edit.column)
            if document['columns'] == selected['columns'] and document['rows'] == selected['rows']:
                row_number = edit.row
            else:
                shared = [(selected['columns'].index(name), position)
                    for position, name in enumerate(document['columns']) if name in selected['columns']]
                matches = [n for n, row in enumerate(document['rows']) if all(
                    _same_cell(row[j], selected['rows'][edit.row][i]) for i, j in shared)]
                if len(matches) != 1:
                    raise ReportingError('report_data_dependency_ambiguous', '同源作图表无法唯一对齐编辑行，原快照保持不变。')
                row_number = matches[0]
            address = (table_id, row_number, column)
            if address in touched:
                raise ReportingError('report_data_edit_conflict', '同源单元格包含重复或冲突编辑。')
            touched.add(address)
            updated.setdefault(table_id, deepcopy(document))['rows'][row_number][column] = edit.value
    if not updated:
        raise ReportingError('report_data_no_changes', '编辑未改变作图数据。')
    candidate, changed = deepcopy(snapshot), {}
    candidate.update(snapshotId=snapshot_id, parentSnapshotId=snapshot['snapshotId'], status='pending_redraw')
    for table_id, document in updated.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', table_id):
            raise ValueError('冻结表标识无效')
        parent_file = snapshot['tables'][table_id]['file']
        document['source'].update(origin='user_edited', snapshotId=snapshot_id, parentFile=deepcopy(parent_file))
        document['nullableColumns'] = [column for position, column in enumerate(document['columns'])
            if any(row[position] is None for row in document['rows'])]
        raw = canonical_json_bytes(document)
        changed[table_id] = raw
        candidate['tables'][table_id].update(parentFile=deepcopy(parent_file), dataOrigin='user_edited',
            file=FileIdentity(path=str(root / 'inputs' / f'{table_id}.json'), size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest()).model_dump(mode='json'))
    invalidated = []
    for chart_id, chart in candidate['charts'].items():
        if set(chart['tableIds']).intersection(changed):
            chart.update(status='invalidated', previousImage=chart['image'], image=None,
                chartRevision=None, executionReceipt=None, visualReceipts=[], standardRenderProof=None)
            chart.pop('pages', None)
            invalidated.append(chart_id)
    candidate['invalidatedChartIds'] = sorted(invalidated)
    return candidate, changed


class ReportDataRevisionService:
    """沿用编辑上下文、追溯登记和状态CAS，客户端只能选择登记表及单元格。"""

    def __init__(self, *, editor, chart_service=None):
        self.editor = editor
        self.chart_service = chart_service

    async def _read_file(self, context, identity):
        ref = FileIdentity.model_validate(identity)
        raw, _mime = await self.editor.workspace.afile_bytes(context.scope['threadId'], ref.path)
        if len(raw) != ref.size or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ReportingError('report_data_source_changed', '数据修订文件身份已变化，未使用该文件。')
        return raw

    async def _write_file(self, context, path, raw):
        ref = FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        try:
            await self.editor.workspace.awrite_bytes(context.scope['threadId'], ref.path, raw, overwrite=False)
        except WorkspacePathConflict:
            if await self._read_file(context, ref.model_dump()) != raw:
                raise ReportingError('report_data_source_changed', '已冻结的数据修订不可覆盖。')
        return ref.model_dump(mode='json')

    async def _history(self, context):
        state = await self.editor.state_repository.get(context.workflow_run_id)
        return state.payload.get('reportDataRevisions', {}).get(context.report_id, {}).get(str(context.revision), {})

    async def read(self, expected, snapshot_id=None):
        context = await self.editor._restore(expected)
        history = await self._history(context)
        snapshot_id = snapshot_id or history.get('latestSnapshotId')
        record = history.get('revisions', {}).get(snapshot_id)
        if record is None:
            raise ReportingError('report_data_revision_unknown', '该报告没有登记的数据快照。')
        record = ReportDataRevision.model_validate(record)
        if record.base_revision != context.revision:
            raise ReportingError('report_data_base_revision_conflict', '数据快照绑定其他报告编辑版本，请从原版本打开数据修订。')
        snapshot = json.loads(await self._read_file(context, record.manifest.model_dump()))
        if (snapshot.get('schema') != 'report-data/v1' or snapshot.get('reportId') != context.report_id
                or snapshot.get('snapshotId') != record.snapshot_id or snapshot.get('baseRevision') != record.base_revision):
            raise ReportingError('report_data_revision_invalid', '数据快照与报告登记身份不一致。')
        await self._verify_files(context, snapshot)
        return snapshot

    async def _verify_files(self, context, snapshot):
        await self._read_file(context, snapshot['markdown'])
        for table in snapshot['tables'].values():
            await self._read_file(context, table['file'])
        for chart in snapshot['charts'].values():
            if chart['image'] is not None:
                await self._read_file(context, chart['image'])
            for page in chart.get('pages', []):
                await self._read_file(context, page['image'])

    async def presentation(self, expected, snapshot):
        """API仅返回不透明表标识、限定预览及修订状态，不暴露宿主路径/回执源码。"""
        context = await self.editor._restore(expected)
        tables = []
        for table_id, table in snapshot['tables'].items():
            document = json.loads(await self._read_file(context, table['file']))
            tables.append({'tableId': table_id, 'columns': document['columns'],
                'rows': document['rows'][:200], 'rowCount': len(document['rows']),
                'columnMeta': document.get('columnMeta', {}), 'dataOrigin': table['dataOrigin']})
        return {'snapshotId': snapshot['snapshotId'], 'parentSnapshotId': snapshot['parentSnapshotId'],
            'status': snapshot['status'], 'tables': tables, 'warnings': snapshot.get('warnings', []),
            'charts': [{'chartId': chart_id, 'chartRevision': chart['chartRevision'],
                'status': chart['status']} for chart_id, chart in snapshot['charts'].items()]}

    async def freeze(self, expected):
        context = await self.editor._restore(expected)
        history = await self._history(context)
        if history.get('latestSnapshotId'):
            return await self.read(context)
        manifest, index = await self.editor.trace.load_manifest_and_index(context)
        if manifest is None or index is None:
            raise ReportingError('report_data_revision_unavailable', '报告没有可核验的作图输入，不能猜测数据来源。')
        snapshot_id = context.digest()
        root = PurePosixPath(context.markdown_path).parent / '.data-revisions' / snapshot_id
        files = {ref.resource_id: ref for ref in index.files}
        markdown_ref = {key: getattr(manifest.markdown, key) for key in ('path', 'size', 'sha256')}
        markdown = await self._read_file(context, markdown_ref)
        captions = {}
        for token in MarkdownIt('commonmark').parse(markdown.decode('utf-8')):
            for child in token.children or ():
                if child.type == 'image':
                    captions[str(child.attrGet('src'))] = child.content
        frozen_markdown = await self._write_file(context, str(root / 'report.md'), markdown)
        tables, charts = {}, {}
        registered = {chart.chart_id: chart for chart in manifest.charts}
        if set(registered) != {trace.chart_id for trace in index.chart_traces}:
            raise ReportingError('report_data_dependency_missing', '图表及作图输入登记不完整，原报告保持不变。')
        for position, trace in enumerate(index.chart_traces, 1):
            image = files[trace.image_file_resource_id]
            chart = registered[trace.chart_id]
            original_image = {key: getattr(image, key) for key in ('path', 'size', 'sha256')}
            if any(getattr(chart, key) != original_image[key] for key in original_image):
                raise ReportingError('report_data_source_changed', '图表图片与报告登记身份不一致。')
            suffix = PurePosixPath(image.path).suffix.lower()
            if suffix not in {'.png', '.jpg', '.jpeg'}:
                raise ReportingError('report_data_image_unsupported', '共同数据修订仅使用静态PNG/JPEG图片。')
            frozen_image = await self._write_file(context, str(root / 'images' / f'chart-{position}{suffix}'),
                await self._read_file(context, original_image))
            for resource_id in trace.plot_data_file_resource_ids:
                if resource_id not in tables:
                    ref = files[resource_id]
                    original = {key: getattr(ref, key) for key in ('path', 'size', 'sha256')}
                    # 资源ID来自已核验索引；文件路径仍单独受FileIdentity限制。
                    frozen = await self._write_file(context, str(root / 'inputs' / f'{resource_id}.json'),
                        await self._read_file(context, original))
                    tables[resource_id] = {'originalFile': original, 'file': frozen, 'dataOrigin': 'original'}
            proof = trace.standard_render_proof
            plan = next((item for item in proof.plan.get('charts', []) if item.get('chartId') == trace.chart_id), {}) if proof else {}
            charts[trace.chart_id] = {'tableIds': list(trace.plot_data_file_resource_ids),
                'image': frozen_image, 'originalImage': original_image, 'plan': deepcopy(plan),
                'originalRelativePath': str(PurePosixPath(image.path).relative_to(PurePosixPath(context.markdown_path).parent)),
                'chartRevision': image.sha256, 'status': 'ready', 'sourceSnapshotId': snapshot_id,
                'executionReceipt': None, 'visualReceipts': [], 'standardRenderProof': None}
            caption = captions.get(charts[trace.chart_id]['originalRelativePath'], trace.chart_id)
            charts[trace.chart_id].update(title=plan.get('title') or caption, altText=plan.get('altText') or caption)
        snapshot = {'schema': 'report-data/v1', 'reportId': context.report_id, 'baseRevision': context.revision,
            'snapshotId': snapshot_id, 'parentSnapshotId': None, 'status': 'ready',
            'markdown': frozen_markdown, 'tables': tables, 'charts': charts, 'invalidatedChartIds': []}
        try:
            await self.commit(context, snapshot)
        except ReportingStateError as error:
            if error.code != 'report_data_revision_conflict':
                raise
            # 并发首次冻结只采纳已通过CAS登记的清单，不覆盖其他编辑结果。
            return await self.read(context)
        return snapshot

    async def prepare(self, expected, request):
        context = await self.editor._restore(expected)
        baseline = await self.freeze(context)
        contents = {table_id: await self._read_file(context, table['file'])
                    for table_id, table in baseline['tables'].items()}
        snapshot_id = uuid4().hex
        root = str(PurePosixPath(context.markdown_path).parent / '.data-revisions' / snapshot_id)
        candidate, changed = prepare_data_revision(baseline, contents, request,
            snapshot_id=snapshot_id, output_root=root)
        for table_id, raw in changed.items():
            await self._write_file(context, candidate['tables'][table_id]['file']['path'], raw)
        return candidate

    async def revise(self, expected, request):
        context = await self.editor._restore(expected)
        if self.chart_service is None or self.chart_service.runner is None:
            raise ReportingError('report_data_redraw_unavailable', '图表重绘服务未配置，原数据修订保持不变。')
        async with asyncio.timeout(getattr(self.chart_service, 'timeout_seconds', 1200)):
            candidate = await self.prepare(context, request)
            for position, chart_id in enumerate(candidate['invalidatedChartIds'], 1):
                candidate['charts'][chart_id] = await self._redraw_chart(context, candidate, chart_id, position)
            candidate['status'] = 'ready'
            candidate['warnings'] = [{'code': 'report_data_business_review_required',
                'message': '数据已由用户编辑；原有正文、表格结论及图注需按新数据复核。'},
                *(warning for chart in candidate['charts'].values() for warning in chart.get('warnings', []))]
            try:
                await self.commit(context, candidate)
            except ReportingStateError as error:
                if error.code != 'report_data_revision_conflict':
                    raise
                raise ReportingError(error.code, str(error)) from error
        return candidate

    async def _redraw_chart(self, context, snapshot, chart_id, position):
        from .chart_ai import CHART_EDIT_SCRIPT_MAX_BYTES, _bindings_from_plot_files
        from .standard_charts import StandardChartEditParameters, standard_edit_plan

        chart = deepcopy(snapshot['charts'][chart_id])
        thread_id = context.scope['threadId']
        identity = self.editor.workspace_registry.get(thread_id)
        if identity is None:
            raise ReportingError('report_host_workspace_missing', '图表工作区尚未恢复。')
        workspace = self.editor.workspace.workspace(thread_id)
        root = PurePosixPath(context.markdown_path).parent / '.data-revisions' / snapshot['snapshotId'] / f'chart-{position}'
        suffix = PurePosixPath(chart['originalRelativePath']).suffix.lower()
        script_path, output_path = str(root / 'draw.py'), str(root / f'chart{suffix}')
        plot_files = []
        for table_id in chart['tableIds']:
            ref = FileIdentity.model_validate(snapshot['tables'][table_id]['file'])
            plot_files.append(SimpleNamespace(path=ref.path, size=ref.size, sha256=ref.sha256,
                content=await self._read_file(context, ref.model_dump())))
        if chart['plan']:
            original = ChartDraft.model_validate(chart['plan'])
            plan = VisualizationPlanDraft(charts=(original.model_copy(update={
                'chart_id': chart_id, 'source_path': output_path,
            }),))
            inputs = ChartInputMaterialization(files=tuple(ChartInputFile(item.path, item.content) for item in plot_files),
                entries=tuple({'chartId': chart_id, 'path': item.path, 'sha256': item.sha256, 'size': item.size} for item in plot_files))
            plan = expand_standard_pagination(plan, inputs)
            # 每页只改变显示窗口，继续引用同一完整冻结表。
            inputs = ChartInputMaterialization(files=inputs.files, entries=tuple(
                {**entry, 'chartId': page.chart_id} for page in plan.charts for entry in inputs.entries
            ))
        else:
            # 旧自定义图没有可重编译计划，复用既有Coding runner和原图业务意图。
            plan, inputs = standard_edit_plan(chart_id=chart_id, output_path=output_path,
                title=chart['title'], alt_text=chart['altText'], visual_form='custom',
                standard=StandardChartEditParameters(standardForm='custom'),
                bindings=_bindings_from_plot_files(plot_files), plot_files=plot_files)
        previous = chart['previousImage']
        await self._read_file(context, previous)
        outputs = tuple(page.source_path for page in plan.charts)
        task = ReportingCodingTaskContext(task_id=f'data-revision:{snapshot["snapshotId"]}:{position}',
            task_kind='visualization', code_mode_session_id=f'data-revision:{snapshot["snapshotId"]}:{position}',
            workspace_key=thread_id, workspace_root=identity.root, script_path=script_path,
            authorized_read_paths=tuple(item.path for item in plot_files) + (previous['path'],),
            authorized_write_paths=(script_path, *outputs), declared_output_paths=outputs,
            max_source_bytes=CHART_EDIT_SCRIPT_MAX_BYTES)
        facts = {'visualizationMode': 'static', 'visualizationPlan': plan.model_dump(mode='json', by_alias=True),
            'chartInputs': list(inputs.entries), 'dataRevision': {'snapshotId': snapshot['snapshotId'],
                'dataOrigin': 'user_edited', 'previousImage': previous, 'originalChartPlan': chart['plan'],
                'instruction': '保持原图业务意图、标题和单位；仅使用本次授权表重绘。原图片仅供呈现参考，不是新数值来源。'}}
        result = await run_standard_chart_routes(self.chart_service.runner, task, workspace, plan, inputs, facts,
            RunContext(run_id=context.workflow_run_id, session_id=thread_id,
                user_id=context.scope['userId'], session_state={}))
        receipt = result.execution_receipt
        if receipt is None or receipt.source_file != result.script_file:
            raise ReportingError('report_data_redraw_unverified', '重绘未取得当前执行回执，原快照保持不变。')
        output_files = {item.path: item.model_dump(mode='json') for item in receipt.output_files}
        if set(output_files) != set(outputs):
            raise ReportingError('report_data_redraw_unverified', '重绘输出与声明图片不一致。')
        chart.update(image=output_files[outputs[0]], pages=[{'image': output_files[path]} for path in outputs[1:]],
            script=result.script_file.model_dump(mode='json'),
            executionReceipt=receipt.model_dump(mode='json', by_alias=True),
            visualReceipts=[review.model_dump(mode='json', by_alias=True) for review in result.visual_inspection_receipts],
            standardRenderProof=[record['proof'].model_dump(mode='json', by_alias=True)
                for record in getattr(result, 'standard_render_proofs', ())],
            sourceSnapshotId=snapshot['snapshotId'], chartRevision=snapshot['snapshotId'], status='ready')
        chart['warnings'] = [{'code': 'report_data_chart_plan_warning', 'chartId': chart_id,
            'message': warning} for warning in plan.warnings]
        for review in result.visual_inspection_receipts:
            notes = [issue.description for issue in review.issues] + list(review.warnings)
            if review.requires_revision or notes:
                chart['warnings'].append({'code': 'report_data_chart_review_required', 'chartId': chart_id,
                    'message': ('；'.join(notes) or '图表视觉审查仍建议修订，请人工复核。')[:2000]})
        return chart

    async def _verify_redraws(self, context, snapshot):
        if snapshot['parentSnapshotId'] is None:
            return
        parent = await self.read(context, snapshot['parentSnapshotId'])
        if set(snapshot['tables']) != set(parent['tables']) or set(snapshot['charts']) != set(parent['charts']):
            raise ReportingError('report_data_dependency_missing', '数据修订依赖集合不一致。')
        changed = {key for key, table in snapshot['tables'].items() if table['file'] != parent['tables'][key]['file']}
        affected = {key for key, chart in parent['charts'].items() if changed.intersection(chart['tableIds'])}
        if affected != set(snapshot['invalidatedChartIds']):
            raise ReportingError('report_data_dependency_missing', '受影响图表登记不完整。')
        for chart_id, chart in snapshot['charts'].items():
            if chart_id not in affected:
                if chart != parent['charts'][chart_id]:
                    raise ReportingError('report_data_redraw_unverified', '未受影响图表身份不得静默改变。')
                continue
            try:
                receipt = ExecutionReceipt.model_validate(chart['executionReceipt'])
                images = [FileIdentity.model_validate(chart['image']),
                    *(FileIdentity.model_validate(page['image']) for page in chart.get('pages', []))]
                reviews = [ChartVisualInspectionReceipt.model_validate(value) for value in chart['visualReceipts']]
                if (chart['sourceSnapshotId'] != snapshot['snapshotId'] or chart['chartRevision'] != snapshot['snapshotId']
                        or receipt.source_file != FileIdentity.model_validate(chart['script'])
                        or set(receipt.output_files) != set(images)):
                    raise ValueError('重绘身份不匹配')
                old_receipt = parent['charts'][chart_id].get('executionReceipt')
                if old_receipt and old_receipt['runId'] == receipt.run_id:
                    raise ValueError('不得复用旧执行回执')
                for image in images:
                    matches = [review for review in reviews if review.source_path == image.path
                        and review.sha256 == image.sha256 and review.reviewed and review.inspection_mode == 'vision']
                    if len(matches) != 1:
                        raise ValueError('缺少当前图片独立视觉回执')
                await self._read_file(context, chart['script'])
            except (ValueError, KeyError, TypeError) as error:
                raise ReportingError('report_data_redraw_unverified', '重绘图片或独立审查回执不匹配，原快照保持不变。') from error

    async def commit(self, expected, snapshot):
        context = await self.editor._restore(expected)
        if snapshot['status'] != 'ready' or any(chart['status'] != 'ready' for chart in snapshot['charts'].values()):
            raise ReportingError('report_data_redraw_pending', '受影响图尚未重绘完成，原快照保持不变。')
        if snapshot['reportId'] != context.report_id:
            raise ReportingError('report_data_revision_invalid', '数据快照不属于当前报告。')
        await self._verify_redraws(context, snapshot)
        await self._verify_files(context, snapshot)
        root = PurePosixPath(context.markdown_path).parent / '.data-revisions' / snapshot['snapshotId']
        identity = await self._write_file(context, str(root / 'manifest.json'), canonical_json_bytes(snapshot))
        record = ReportDataRevision(reportId=context.report_id, baseRevision=snapshot['baseRevision'],
            snapshotId=snapshot['snapshotId'], parentSnapshotId=snapshot['parentSnapshotId'], manifest=identity)
        await apply_editor_command(self.editor.state_repository, context.workflow_run_id, ReportingCommand(
            name='record_report_data_revision', commandId=f'data-revision:{snapshot["snapshotId"]}',
            payload={'expectedSnapshotId': snapshot['parentSnapshotId'], 'revision': record.model_dump(mode='json', by_alias=True)},
        ))
        return record

    async def read_export(self, expected, snapshot_id, export_id):
        """回读已登记的导出摘要；历史记录不代表文件仍可下载。"""
        context = await self.editor._restore(expected)
        history = await self._history(context)
        raw = history.get('exports', {}).get(export_id)
        if raw is None:
            raise ReportingError('report_data_export_unknown', '该快照没有登记此导出。')
        try:
            record = ReportDataExport.model_validate(raw)
        except ValueError as error:
            raise ReportingError('report_data_export_invalid', '导出登记身份无效。') from error
        if (record.report_id != context.report_id or record.base_revision != context.revision
                or record.export_id != export_id or record.snapshot_id != snapshot_id
                or snapshot_id not in history.get('revisions', {})):
            raise ReportingError('report_data_export_unknown', '该快照没有登记此导出。')
        try:
            manifest = json.loads(await self._read_file(context, record.manifest.model_dump()))
            fields = record.model_dump(mode='json', by_alias=True, exclude={'manifest'})
            if manifest.get('schema') != 'report-data-export/v1' or any(
                manifest.get(key) != value for key, value in fields.items()
            ):
                raise ValueError('export manifest identity mismatch')
            artifacts = {
                label: FileIdentity.model_validate(ref).model_dump(include={'size', 'sha256'})
                for label, ref in manifest['artifacts'].items() if label in ('pdf', 'word', 'pptx', 'xlsx')
            }
            return {'exportId': export_id, 'snapshotId': snapshot_id, 'revision': record.revision,
                'chartRevisions': manifest['chartRevisions'], 'artifacts': artifacts,
                'validation': manifest['validation']}
        except (AttributeError, KeyError, OSError, ValueError) as error:
            raise ReportingError('report_data_export_invalid', '历史导出清单不可读取或身份已变化。') from error

    async def export(self, expected, snapshot_id):
        """每次导出独立编号；快照历史只读，登记/验收失败不吞已核验产物。"""
        from ..reporting.delivery.office_engine import run_office_engine
        from ..reporting.delivery.publishing import (
            ReportArtifactSpec,
            ReportDownloadScope,
            publication_result,
        )
        from .data_revision_exports import render_data_revision_formats

        context = await self.editor._restore(expected)
        snapshot = await self.read(context, snapshot_id)
        if snapshot['status'] != 'ready':
            raise ReportingError('report_data_redraw_pending', '数据快照尚未完成重绘。')
        if self.editor.artifact_persistence is None or self.editor.download_grants is None:
            raise ReportingError('report_data_export_unavailable', '数据修订导出服务未配置。')
        revision, issues = await next_manual_revision(self.editor.state_repository, context)
        export_id = uuid4().hex
        output_root = str(PurePosixPath(context.markdown_path).parent / '.data-exports' / export_id)
        tables = {key: await self._read_file(context, table['file']) for key, table in snapshot['tables'].items()}
        result = await run_office_engine(render_data_revision_formats,
            root=self.editor.workspace_registry.get(context.scope['threadId']).root,
            snapshot=snapshot, tables=tables, job=context.job, output_root=output_root)
        validation = result['validation']
        issues.extend(validation.get('issues', []))
        if not validation.get('ok') and not validation.get('issues'):
            issues.append({'code': 'report_data_export_validation_failed', 'message': '导出验收未通过。'})
        identities = {}
        for label in ('pdf', 'word', 'pptx', 'xlsx'):
            identity = result['artifacts'].get(label)
            if identity is None:
                continue
            try:
                ref = FileIdentity.model_validate(identity)
                if PurePosixPath(ref.path).parent != PurePosixPath(output_root):
                    raise ValueError('artifact outside current export')
                identities[label] = ref.model_dump(mode='json')
                await self._read_file(context, identities[label])
            except Exception as error:
                identities.pop(label, None)
                logger.warning('report_data_export_identity_failed format={} error_type={}', label, type(error).__name__)
                issues.append({'code': f'report_data_{label}_identity_unavailable', 'message': f'{label}身份不可核验，未签发该格式。'})
        if not identities:
            raise ReportingError('report_artifact_unavailable', '没有可核验身份的导出文件。')
        chart_revisions = {key: chart['chartRevision'] for key, chart in snapshot['charts'].items()}
        manifest = {'schema': 'report-data-export/v1', 'exportId': export_id,
            'reportId': context.report_id, 'baseRevision': context.revision, 'revision': revision,
            'snapshotId': snapshot_id, 'chartRevisions': chart_revisions, 'artifacts': identities,
            'validation': {'ok': not issues, 'issues': list(issues)}}
        registered = False
        try:
            ref = await self._write_file(context, output_root + '/export-manifest.json', canonical_json_bytes(manifest))
            record = ReportDataExport(reportId=context.report_id, baseRevision=context.revision,
                snapshotId=snapshot_id, exportId=export_id, revision=revision, manifest=ref)
            await apply_editor_command(self.editor.state_repository, context.workflow_run_id, ReportingCommand(
                name='record_report_data_export', commandId=f'data-export:{export_id}',
                payload={'export': record.model_dump(mode='json', by_alias=True)}))
            registered = True
        except Exception as error:
            logger.warning('report_data_export_record_failed error_type={}', type(error).__name__)
            issues.append({'code': 'report_data_export_record_failed', 'message': '导出追溯登记失败，已核验文件继续交付。'})
        scope = ReportDownloadScope(database=context.scope['database'], user_id=context.scope['userId'],
            company_id=context.scope['companyId'], session_id=context.scope['sessionId'],
            thread_id=context.scope['threadId'], workflow_run_id=context.workflow_run_id)
        # Grant replace 会撤销同 report_id 的旧授权；共同数据导出拥有独立的交付身份。
        delivery_id = f'data-export:{export_id}'
        specs = tuple(ReportArtifactSpec(artifact=label, **identity) for label, identity in identities.items())
        try:
            stored = await self.editor.artifact_persistence.persist_available(scope=scope,
                report_id=delivery_id, revision=revision, artifacts=specs)
        except Exception as error:
            logger.warning('report_data_export_persistence_failed error_type={}', type(error).__name__)
            stored = ()
        # 下载端对未持久化的格式使用既有工作区回退，读取时再次校验字节身份。
        for label in sorted(identities.keys() - {spec.artifact for spec in stored}):
            issues.append({'code': f'report_data_{label}_persistence_failed', 'message': f'{label}下载副本保存失败，保留已核验的工作区文件。'})
        raw, grant = await self.editor.download_grants.issue(scope=scope, report_id=delivery_id,
            revision=revision, **{f'{label}_{field}': identity[field]
                for label, identity in identities.items() for field in ('path', 'size', 'sha256')})
        response = publication_result(report_id=context.report_id, revision=revision, raw_grant=raw,
            grant=grant, base_url=(self.editor.public_base_url or '').rstrip('/'),
            editor_raw_grant=None, editor_expires_at=None)
        for label in identities:
            response[label].pop('path', None)
        return {**response, 'exportId': export_id, 'snapshotId': snapshot_id,
            'chartRevisions': chart_revisions, 'exportRegistered': registered,
            'validation': {'ok': not issues, 'issues': issues}}
