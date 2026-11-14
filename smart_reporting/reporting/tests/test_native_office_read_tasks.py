"""XLSX/PPTX 阅读基于真实原件或引擎草稿，独立于编辑候选。"""

import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_models import (
    NATIVE_MEDIA,
    NativeEditorContext,
    NativeScope,
)
from smart_reporting.report_editor.native_office import inspect_office
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError


@pytest.fixture(params=['xlsx', 'pptx'])
async def office_sample(request, tmp_path):
    kind = request.param
    stream = BytesIO()
    if kind == 'xlsx':
        workbook = Workbook()
        workbook.active.title = '经营'
        workbook.active['A1'] = '收入42'
        workbook.active['B1'] = '未授权秘密'
        workbook.save(stream)
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for index, text in enumerate(['收入42', '未授权秘密']):
            slide.shapes.add_textbox(Inches(1), Inches(index + 1), Inches(4), Inches(1)).text = text
        deck.save(stream)
    content = stream.getvalue()
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret='w' * 32))
    scope = NativeScope(database='db', companyId='co', userId='u', threadId='office-read')
    context = NativeEditorContext(documentId='office', revision=1, format=kind, origin='upload', scope=scope,
        sourceFile=ArtifactFile(path='native/source.' + kind, size=len(content),
            sha256=hashlib.sha256(content).hexdigest(), mediaType=NATIVE_MEDIA[kind]))
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), context.source_file.path, content)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, SimpleNamespace(get_revision=AsyncMock(
        return_value=SimpleNamespace(status='saved', context=context))), grants, office_enabled=True)
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await grants.exchange(raw)
    model = inspect_office(kind, content)
    yield editor, context, session, model, content
    await workspace.registry.aclose()


async def read_all(*, reader, action, **kwargs):
    if hasattr(reader, 'get_workbook_context'):
        identities, parts = [], []
        for sheet in reader.get_workbook_context()['sheets']:
            addresses = sheet['knownAddresses']
            if not addresses:
                continue
            offset = 0
            while True:
                result = reader.read_cells(addresses, sheetId=sheet['name'], offset=offset)
                parts.append(result['content'])
                offset = result['nextOffset']
                if offset is None:
                    break
            identities.extend(sheet['name'] + '!' + address for address in addresses)
    else:
        identities, parts = [], []
        for slide in reader.get_presentation_context()['slides']:
            offset = 0
            while True:
                result = reader.read_slide(slide['slideIndex'], offset=offset)
                parts.append(result['content'])
                offset = result['nextOffset']
                if offset is None:
                    break
            identities.append(str(slide['slideIndex']))
    return reader.result('\n'.join(parts), identities, action=action)


def request_for(context, **kwargs):
    return {'client_request_id': 'read', 'expected_sha256': context.source_file.sha256,
        'operations': [], 'selection': None, 'action': 'summarize', 'instruction': '', **kwargs}


def selection_and_change(context, model):
    if context.format == 'xlsx':
        return ({'sheetName': '经营', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
            [{'kind': 'applyCellEdits', 'edits': [{'sheetName': '经营', 'row': 0, 'column': 0,
                'writeValue': True, 'cell': {'value': '人工草稿73'}}]}])
    element = next(item for item in model['slides'][0]['elements'] if item.get('text') == '收入42')
    return ([{'slideIndex': 0, 'elementId': element['id']}],
        [{'kind': 'editSlides', 'edits': [{'slideIndex': 0, 'elementId': element['id'], 'text': '人工草稿73'}]}])


@pytest.mark.anyio
async def test_office_reads_source_without_editing_and_never_proposes(office_sample):
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    editor, context, session, _, original = office_sample
    editor.office_enabled = False
    service = NativeOfficeReadService(editor, planners={context.format: read_all}, enabled=True)
    try:
        job = await service.start(session, **request_for(context))
        job = await service.status(session, job['taskId'])
        assert job['status'] == 'completed', job
        assert '收入42' in job['result']['answer']
        assert job['result']['readingVersion'] == 'source'
        assert job['result']['coverage']['scopeReadComplete'] is True
        assert 'operations' not in job['result'] and 'proposal' not in job['result']
        assert await editor.read_file(context) == original
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_office_selected_real_draft_does_not_include_unselected_content(office_sample):
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    editor, context, session, model, original = office_sample
    selection, changes = selection_and_change(context, model)
    service = NativeOfficeReadService(editor, planners={context.format: read_all}, enabled=True)
    try:
        job = await service.start(session, **request_for(context, operations=changes, selection=selection))
        job = await service.status(session, job['taskId'])
        assert job['status'] == 'completed', job
        assert '人工草稿73' in job['result']['answer']
        assert '未授权秘密' not in str(job['result'])
        assert job['result']['coverage']['scope'] == 'selection'
        assert job['result']['readingVersion'] == 'draft'
        assert job['result']['effectiveSha256'] != job['result']['sourceSha256']
        assert await editor.read_file(context) == original
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_office_request_binds_snapshot_and_cancel_cannot_be_revived(office_sample):
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    editor, context, session, _, _ = office_sample
    service = NativeOfficeReadService(editor, planners={context.format: read_all}, enabled=True)
    try:
        stopped = await service.cancel_request(session, 'read')
        job = await service.start(session, **request_for(context))
        assert job['taskId'] == stopped['taskId'] and job['status'] == 'cancelled'
        job = await service.start(session, **request_for(context, client_request_id='next'))
        await service.status(session, job['taskId'])
        with pytest.raises(ReportingError, match='变化'):
            await service.start(session, **request_for(context, client_request_id='next', action='keyPoints'))
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_office_cancel_suppresses_a_planner_that_swallows_cancellation(office_sample):
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    editor, context, session, _, _ = office_sample
    entered = asyncio.Event()
    async def planner(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return await read_all(**kwargs)
    service = NativeOfficeReadService(editor, planners={context.format: planner}, enabled=True)
    try:
        job = await service.start(session, **request_for(context))
        await asyncio.wait_for(entered.wait(), 30)
        stopped = await service.cancel_request(session, 'read')
        assert stopped['status'] == 'cancelled' and 'result' not in stopped
        result = await service.status(session, job['taskId'])
        assert result['status'] == 'cancelled' and 'result' not in result
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_pptx_reorder_rebinds_selected_object_without_parse_id_collision():
    """解析ID随页序变化：原sp_9在草稿中可能已指向同页未授权对象。"""
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    deck = Presentation()
    for texts in ([f'原页对象{index}' for index in range(15)], ['另一页']):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for text in texts:
            slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = text
    stream = BytesIO()
    deck.save(stream)
    content = stream.getvalue()
    model = inspect_office('pptx', content)
    target = model['slides'][0]['elements'][9]
    scope = NativeScope(database='db', companyId='co', userId='u', threadId='reorder-read')
    context = NativeEditorContext(documentId='reorder', revision=1, format='pptx', origin='upload',
        scope=scope, sourceFile=ArtifactFile(path='native/reorder.pptx', size=len(content),
            sha256=hashlib.sha256(content).hexdigest(), mediaType=NATIVE_MEDIA['pptx']))
    editor = SimpleNamespace(context_for_session=AsyncMock(return_value=context),
        read_file=AsyncMock(return_value=content), require_enabled=lambda _format: None)
    service = NativeOfficeReadService(editor, planners={'pptx': read_all}, enabled=True)
    try:
        job = await service.start(None, **request_for(context,
            selection=[{'slideIndex': 0, 'elementId': target['id']}],
            operations=[{'kind': 'editSlides', 'edits': [], 'order': [1, 0]}]))
        job = await service.status(None, job['taskId'])
        assert job['status'] == 'completed', job
        assert '原页对象9' in job['result']['answer']
        assert '原页对象0' not in str(job['result'])
        assert job['result']['coverage']['scope'] == 'selection'
        assert job['result']['coverage']['scopeReadComplete'] is True
    finally:
        await service.aclose()


def test_pptx_header_footer_cannot_rebind_same_named_objects_by_ordinal():
    """页脚替换会删除后追加；同名对象即使数量和类型一致也不能按序授权。"""
    from smart_reporting.report_editor.native_office_read_tasks import _slides_selection

    original = {'slides': [{'slideIndex': 0, 'elements': [
        {'id': 'sp_0', 'type': 'text', 'name': '同名对象', 'text': '授权页脚'},
        {'id': 'sp_1', 'type': 'text', 'name': '同名对象', 'text': '未授权邻对象'},
    ]}]}
    effective = {'slides': [{'slideIndex': 0, 'elements': [
        {'id': 'sp_2', 'type': 'text', 'name': '同名对象', 'text': '未授权邻对象'},
        {'id': 'sp_3', 'type': 'text', 'name': '同名对象', 'text': '新页脚'},
    ]}]}
    base = [{'kind': 'editSlides', 'headerFooter': {
        'footer': '新页脚', 'slideNum': False, 'date': None, 'dateAuto': False}}]
    with pytest.raises(ReportingError, match='结构'):
        _slides_selection(original, effective, base, [{'slideIndex': 0, 'elementId': 'sp_0'}])


@pytest.mark.anyio
async def test_office_read_rejects_write_proposal_and_changed_source_after_planner(office_sample):
    from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService

    editor, context, session, _, _ = office_sample
    async def proposal(**kwargs):
        return {'answer': '不可展示的候选', 'operations': [{'kind': 'write'}]}
    service = NativeOfficeReadService(editor, planners={context.format: proposal}, enabled=True)
    try:
        job = await service.start(session, **request_for(context))
        job = await service.status(session, job['taskId'])
        assert job['status'] == 'failed' and 'result' not in job
        assert job['error']['code'] == 'native_ai_schema_invalid'
        original = editor.context_for_session
        async def changed(**kwargs):
            result = await read_all(**kwargs)
            editor.context_for_session = AsyncMock(return_value=context.model_copy(update={'revision': 2}))
            return result
        service.planners[context.format] = changed
        job = await service.start(session, **request_for(context, client_request_id='changed'))
        await job_task(service, job['taskId'])
        editor.context_for_session = original
        job = await service.status(session, job['taskId'])
        assert job['status'] == 'failed' and 'result' not in job
        assert job['error']['code'] == 'native_ai_snapshot_changed'
    finally:
        await service.aclose()


async def job_task(service, task_id):
    job = next(item for item in service._jobs.values() if item.task_id == task_id)
    await asyncio.wait_for(asyncio.shield(job.task), 30)
