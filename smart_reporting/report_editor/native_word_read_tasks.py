"""Word 纯阅读任务：复用任务生命周期，读取实际 DOCX 草稿，不生成编辑候选。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from loguru import logger

from ..reporting.delivery.docx_native import inspect_docx, patch_docx
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.models import ReportingError
from .agent_event_streams import bind_agent_event_log
from .native_ai import _copy_operations
from .native_models import native_digest
from .native_pdf_ai_tasks import NativePDFReadService, _ReadJob
from .native_word_read_ai import NativeWordReadTools

_INSTRUCTIONS = {
    'ask': '根据实际读取的授权 Word 内容回答问题，引用块身份；依据不足时明确澄清。',
    'summarize': '完整读取授权范围并总结主题、结论与重要数据；明确未覆盖范围，不补造事实。',
    'keyPoints': '完整读取授权范围，提炼关键要点、数值、日期及行动项，引用对应块。',
}
_BLOCK_STRUCTURE = {'insertParagraph', 'deleteParagraph', 'insertTable', 'insertCoverPage',
                    'insertParagraphImage', 'insertSectionBreak', 'resolveTextRevision'}
_CELL_STRUCTURE = {'insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn',
                   'restructureTable', 'reshapeTableCells'}


def _selection_for_draft(original, effective, base, selection):
    """仅在块序和单格坐标保持时重绑；实际文字始终取引擎草稿，不手工模拟。"""
    source = original['blocks']
    selected = []
    identities = set()
    for item in selection:
        matches = [(index, block) for index, block in enumerate(source) if block['blockId'] == item['blockId']]
        key = (item['blockId'], item.get('cellId'))
        if len(matches) != 1 or key in identities or any(
            old[0] == key[0] and (old[1] is None or key[1] is None) for old in identities
        ):
            raise ReportingError('native_ai_selection_invalid', 'Word 阅读选区重复、重叠或已失效。')
        identities.add(key)
        index, block = matches[0]
        if base and (any(op.get('kind') in _BLOCK_STRUCTURE for op in base)
                     or len(source) != len(effective['blocks'])
                     or any(old['type'] != new['type'] for old, new in zip(source, effective['blocks'], strict=True))):
            raise ReportingError('native_ai_selection_invalid', '草稿块结构已变化，请先保存重开再选择，或改用整篇阅读。')
        target = effective['blocks'][index]
        mapped = {'blockId': target['blockId']}
        if item.get('cellId') is not None:
            cells = [(row_index, column_index) for row_index, row in enumerate(block.get('cells', []))
                     for column_index, cell in enumerate(row) if cell['cellId'] == item['cellId']]
            if len(cells) != 1 or any(op.get('blockId') == block['blockId'] and op.get('kind') in _CELL_STRUCTURE for op in base):
                raise ReportingError('native_ai_selection_invalid', 'Word 单元格选区已变化，不能扩大读取范围。')
            row, column = cells[0]
            try:
                mapped['cellId'] = target['cells'][row][column]['cellId']
            except (KeyError, IndexError) as error:
                raise ReportingError('native_ai_selection_invalid', 'Word 单元格选区已失效。') from error
        selected.append(mapped)
    return selected


class NativeWordReadService(NativePDFReadService):
    """复用现有有界缓存、轮询、SSE、提前取消与关闭任务生命周期。"""

    async def _context(self, session):
        context = await self.editor.context_for_session(session)
        if not self.enabled:
            raise ReportingError('native_ai_disabled', 'Word AI 阅读尚未开放。')
        if context.format != 'docx':
            raise ReportingError('native_ai_format_unsupported', '此阅读任务仅支持 Word。')
        return context

    async def start(self, session, *, client_request_id, expected_sha256, operations,
                    selection=None, action='ask', instruction=''):
        context = await self._context(session)
        request_id = self._request_id(client_request_id)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError('native_ai_snapshot_changed', 'Word 来源已变化，请重新打开。')
        if (action not in _INSTRUCTIONS or not isinstance(instruction, str) or len(instruction) > 2000
                or action == 'ask' and not instruction.strip()):
            raise ReportingError('native_ai_instruction_invalid', 'Word 阅读任务要求无效，问答需要输入问题。')
        selected = deepcopy(selection) if selection is not None else []
        if (not isinstance(selected, list) or len(selected) > 100 or any(
            not isinstance(item, dict) or 'blockId' not in item or set(item) - {'blockId', 'cellId'}
            or any(not isinstance(value, str) or not value or len(value) > 256 for value in item.values())
            for item in selected
        )):
            raise ReportingError('native_ai_selection_invalid', 'Word 阅读选区身份无效。')
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
        job.task = asyncio.create_task(self._run_word(job, session, context, base, selected, action, instruction))
        return self._serialize(job)

    async def _run_word(self, job, session, context, base, selection, action, instruction):
        deadline = monotonic() + self.timeout_seconds
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await job.event_log.emit('phase', label='正在读取 Word 授权内容')
                content = await self.editor.read_file(context)
                original = await run_office_engine(inspect_docx, content)
                if job.status != 'running':
                    return
                if base:
                    self.editor.require_enabled('docx')
                    edited = await run_office_engine(patch_docx, content, base)
                    effective = await run_office_engine(inspect_docx, edited)
                else:
                    effective = original
                if job.status != 'running':
                    return
                mapped = _selection_for_draft(original, effective, base, selection)
                reader = NativeWordReadTools(effective, selection=mapped)
                async with bind_agent_event_log(job.event_log):
                    result = await self.planner(reader=reader, action=action,
                        instruction=_INSTRUCTIONS[action] + '\n用户要求：' + instruction,
                        session_id=f'native-word-read:{job.task_id}', user_id=context.scope.user_id)
                if job.status != 'running':
                    return
                current = await self.editor.context_for_session(session)
                if current.digest() != job.context_sha256:
                    raise ReportingError('native_ai_snapshot_changed', 'Word 会话来源已变化。')
                if monotonic() >= deadline:
                    raise TimeoutError
                if (not isinstance(result, dict) or not isinstance(result.get('answer'), str)
                        or not result['answer'].strip() or 'operations' in result or 'proposal' in result):
                    raise ReportingError('native_ai_schema_invalid', 'Word 只读任务不能返回可采纳修改，且必须包含有效回答。')
                if job.status == 'running':
                    job.result = {**result, 'readingVersion': 'draft' if base else 'source',
                                  'sourceSha256': context.source_file.sha256,
                                  'effectiveSha256': effective['sourceSha256']}
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
                code, message = 'native_ai_timeout', 'Word AI 阅读超时，请重试。'
            else:
                code, message = 'native_ai_read_failed', 'Word AI 阅读失败，文档与草稿保持原样。'
            logger.warning('native_word_ai_read_failed task_id={} error_type={}', job.task_id, type(error).__name__)
            job.status, job.error = 'failed', {'code': code, 'message': message}
        finally:
            await job.event_log.finish(job.status)
