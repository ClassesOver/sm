"""原生工作簿与演示文稿只读任务：实际引擎草稿、授权读取、共享任务生命周期。"""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from functools import partial
from time import monotonic
from uuid import uuid4

from loguru import logger

from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.models import ReportingError
from .agent_event_streams import bind_agent_event_log
from .native_ai import _copy_operations
from .native_models import native_digest
from .native_office import inspect_office, patch_office
from .native_pdf_ai_tasks import NativePDFReadService, _ReadJob

_ACTIONS = {'ask', 'summarize', 'keyPoints'}
_RANGE_KEYS = {'sheetName', 'startRow', 'endRow', 'startColumn', 'endColumn'}
_SLIDES_IDENTITY_PRESERVING = {
    'kind', 'edits', 'textFormatting', 'paragraphFormatting', 'order', 'theme', 'slideSize',
    'hiddenSlides', 'transitions', 'animations', 'animationSequences', 'backgrounds',
    'sections', 'commentEdits',
}


def _selection(format, selection):
    """None表示整份；非空选区须保留其语义，禁止失效后回退全文。"""
    if selection is None:
        return None
    if format == 'xlsx':
        valid = (isinstance(selection, dict) and set(selection) == _RANGE_KEYS
            and isinstance(selection['sheetName'], str) and bool(selection['sheetName'])
            and all(type(selection[key]) is int for key in _RANGE_KEYS - {'sheetName'})
            and 0 <= selection['startRow'] <= selection['endRow'] < 1048576
            and 0 <= selection['startColumn'] <= selection['endColumn'] < 16384)
    else:
        valid = (isinstance(selection, list) and 0 < len(selection) <= 100
            and all(isinstance(item, dict) and set(item) == {'slideIndex', 'elementId'}
                and type(item['slideIndex']) is int and item['slideIndex'] >= 0
                and isinstance(item['elementId'], str) and 0 < len(item['elementId']) <= 256
                for item in selection))
    if not valid:
        raise ReportingError('native_ai_selection_invalid', '阅读选区已失效，不能扩大为整份文件。')
    return deepcopy(selection)


def _slides_selection(original, effective, base, selection):
    """解析ID不是持久身份；只在已核验的原页内拓扑上按来源对象序重绑。"""
    if any(set(op) - _SLIDES_IDENTITY_PRESERVING for op in base):
        raise ReportingError('native_ai_selection_invalid', 'PPTX 对象结构已变化，请保存后选择或改用整稿阅读。')
    source_slides = {slide['slideIndex']: slide for slide in original['slides']}
    draft_slides = {slide['slideIndex']: slide for slide in effective['slides']}
    order = next((op['order'] for op in base if op.get('order')), list(source_slides))
    if len(order) != len(source_slides) or set(order) != set(source_slides):
        raise ReportingError('native_ai_selection_invalid', 'PPTX 草稿页序无法核验。')
    result, seen = [], set()
    for item in selection:
        key = (item['slideIndex'], item['elementId'])
        if key in seen or item['slideIndex'] not in source_slides:
            raise ReportingError('native_ai_selection_invalid', 'PPTX 阅读选区重复或已失效。')
        seen.add(key)
        old = source_slides[item['slideIndex']]['elements']
        target_index = order.index(item['slideIndex'])
        current = draft_slides.get(target_index, {}).get('elements', [])
        matches = [index for index, element in enumerate(old) if element['id'] == item['elementId']]
        if (len(matches) != 1 or len(old) != len(current) or any(
            (before.get('type'), before.get('name')) != (after.get('type'), after.get('name'))
            for before, after in zip(old, current, strict=True)
        )):
            raise ReportingError('native_ai_selection_invalid', 'PPTX 草稿对象身份无法核验，不能读取相邻对象。')
        result.append({'slideIndex': target_index, 'elementId': current[matches[0]]['id']})
    return result


class NativeOfficeReadService(NativePDFReadService):
    def __init__(self, editor, *, planners, enabled=False, timeout_seconds=120):
        super().__init__(editor, planner=None, enabled=enabled, timeout_seconds=timeout_seconds)
        self.planners = dict(planners)

    async def _context(self, session):
        context = await self.editor.context_for_session(session)
        if not self.enabled:
            raise ReportingError('native_ai_disabled', 'Office AI 阅读尚未开放。')
        if context.format not in {'xlsx', 'pptx'} or context.format not in self.planners:
            raise ReportingError('native_ai_format_unsupported', '此阅读任务仅支持 XLSX/PPTX。')
        return context

    async def start(self, session, *, client_request_id, expected_sha256, operations,
                    selection=None, action='ask', instruction=''):
        context = await self._context(session)
        request_id = self._request_id(client_request_id)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError('native_ai_snapshot_changed', 'Office 来源已变化，请重新打开。')
        if (action not in _ACTIONS or not isinstance(instruction, str) or len(instruction) > 2000
                or action == 'ask' and not instruction.strip()):
            raise ReportingError('native_ai_instruction_invalid', '阅读任务无效，问答需要输入问题。')
        selected = _selection(context.format, selection)
        base = _copy_operations(operations)
        snapshot = native_digest({'context': context.digest(), 'operations': base,
            'selection': selected, 'action': action, 'instruction': instruction})
        self._prune()
        key = (context.digest(), request_id)
        previous = self._jobs.get(key)
        if previous:
            if previous.snapshot_sha256 is not None and previous.snapshot_sha256 != snapshot:
                raise ReportingError('native_ai_snapshot_changed', '相同 AI 请求内容已变化，请重新发起。')
            return self._serialize(previous)
        self._reserve()
        job = _ReadJob(uuid4().hex, request_id, context.digest(), monotonic(), snapshot)
        self._jobs[key] = job
        job.task = asyncio.create_task(self._run_office(job, session, context, base, selected, action, instruction))
        return self._serialize(job)

    async def _run_office(self, job, session, context, base, selection, action, instruction):
        deadline = monotonic() + self.timeout_seconds
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await job.event_log.emit('phase', label='正在读取 ' + context.format.upper() + ' 授权内容')
                content = await self.editor.read_file(context)
                original = (await run_office_engine(partial(inspect_office, 'pptx'), content)
                    if context.format == 'pptx' and selection is not None else None)
                if base:
                    self.editor.require_enabled(context.format)
                    if context.format == 'pptx' and selection is not None and any(
                        key not in _SLIDES_IDENTITY_PRESERVING and value not in (None, [], {})
                        for operation in base for key, value in operation.items()
                    ):
                        raise ReportingError('native_ai_selection_invalid', 'PPTX 草稿对象结构已变化，请保存后选择或改用整稿阅读。')
                    content = await run_office_engine(partial(patch_office, context.format), content, base)
                if job.status != 'running':
                    return
                model = await run_office_engine(partial(inspect_office, context.format), content)
                if job.status != 'running':
                    return
                mapped = deepcopy(selection)
                if context.format == 'pptx' and mapped is not None:
                    mapped = _slides_selection(original, model,
                        [{key: value for key, value in op.items() if value not in (None, [], {})} for op in base], mapped)
                if context.format == 'xlsx':
                    from .native_workbook_read_ai import NativeWorkbookReadTools
                    reader = NativeWorkbookReadTools(model, selection=mapped)
                else:
                    from .native_slides_read_ai import NativeSlidesReadTools
                    reader = NativeSlidesReadTools(model, selection=mapped)
                async with bind_agent_event_log(job.event_log):
                    result = await self.planners[context.format](reader=reader, action=action,
                        instruction=instruction, session_id=f'native-office-read:{job.task_id}',
                        user_id=context.scope.user_id)
                if job.status != 'running':
                    return
                current = await self.editor.context_for_session(session)
                if current.digest() != job.context_sha256:
                    raise ReportingError('native_ai_snapshot_changed', 'Office 会话来源已变化。')
                if monotonic() >= deadline:
                    raise TimeoutError
                if (not isinstance(result, dict) or not isinstance(result.get('answer'), str)
                        or not result['answer'].strip() or 'operations' in result or 'proposal' in result):
                    raise ReportingError('native_ai_schema_invalid', '只读任务必须返回回答，不能返回可采纳修改。')
                if job.status == 'running':
                    job.result = {**result, 'readingVersion': 'draft' if base else 'source',
                        'sourceSha256': context.source_file.sha256,
                        'effectiveSha256': hashlib.sha256(content).hexdigest()}
                    job.status = 'completed'
        except asyncio.CancelledError:
            job.status, job.result = 'cancelled', None
            raise
        except Exception as error:
            if job.status != 'running':
                return
            if isinstance(error, ReportingError):
                code, message = error.code, error.message
            elif isinstance(error, TimeoutError):
                code, message = 'native_ai_timeout', 'Office AI 阅读超时，请重试。'
            else:
                code, message = 'native_ai_read_failed', 'Office AI 阅读失败，文档与草稿保持原样。'
            logger.warning('native_office_read_failed task_id={} error_type={}', job.task_id, type(error).__name__)
            job.status, job.error = 'failed', {'code': code, 'message': message}
        finally:
            await job.event_log.finish(job.status)
