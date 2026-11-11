"""PDF 表单候选绑定冻结字段身份，真实预览后仅显式返回草稿。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from loguru import logger

from ..reporting.models import ReportingError
from .agent_event_streams import bind_agent_event_log
from .native_ai import _copy_operations
from .native_models import native_digest
from .native_pdf_ai_tasks import _ReadJob
from .native_pdf_form_ai import selected_pdf_form_fields, validate_pdf_form_operations
from .native_pdf_review_ai_tasks import NativePDFReviewService


class NativePDFFormService(NativePDFReviewService):
    async def start(self, session, *, client_request_id, expected_sha256, operations,
                    selection, instruction):
        context = await self._context(session)
        if self._closed:
            raise ReportingError('native_ai_closed', '表单 AI 服务已关闭。')
        self.editor.require_enabled('pdf')
        request_id = self._request_id(client_request_id)
        if expected_sha256 != context.source_file.sha256:
            raise ReportingError('native_ai_snapshot_changed', 'PDF 来源已变化，请重新打开。')
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
            raise ReportingError('native_ai_instruction_invalid', '请输入有效表单填写要求。')
        if (not isinstance(selection, list) or not 1 <= len(selection) <= 100
                or any(not isinstance(item, dict) or set(item) != {'fieldId'}
                       or not isinstance(item['fieldId'], str) or len(item['fieldId']) != 64
                       for item in selection)
                or len({item['fieldId'] for item in selection}) != len(selection)):
            raise ReportingError('native_ai_selection_invalid', '请明确选择要填写的表单字段。')
        base = _copy_operations(operations)
        selected = deepcopy(selection)
        snapshot = native_digest({'context': context.digest(), 'operations': base,
                                  'selection': selected, 'instruction': instruction, 'action': 'fillForm'})
        self._prune()
        key = (context.digest(), request_id)
        previous = self._jobs.get(key)
        if previous:
            if previous.snapshot_sha256 is not None and previous.snapshot_sha256 != snapshot:
                raise ReportingError('native_ai_snapshot_changed', '相同 AI 请求内容已变化，请重新发起。')
            return self._serialize(previous)
        self._reserve()
        job = _ReadJob(uuid4().hex, request_id, context.digest(), monotonic(), snapshot)
        job.base = deepcopy(base)
        self._jobs[key] = job
        job.task = asyncio.create_task(self._run_form(job, session, context, base, selected, instruction))
        return self._serialize(job)

    async def _run_form(self, job, session, context, base, selection, instruction):
        deadline = monotonic() + self.timeout_seconds
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.editor.read_file(context)
                original = await self.editor.preview(context, expected_sha256=context.source_file.sha256, operations=[])
                # 草稿先经真实引擎确认；字段选择与写入身份始终取自原件。
                if base:
                    receipt = await self.editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=base)
                    manifest = self._receipt(receipt, context.source_file.sha256, len(base))
                    if manifest['skippedOperations']:
                        raise ReportingError('native_ai_selection_invalid', '草稿包含未应用修改，请先核对并保存后重新填写。')
                selected = selected_pdf_form_fields(original['model'], base, selection)
                frozen = deepcopy(selected)
                if job.status != 'running':
                    return
                await job.event_log.emit('phase', label='正在读取并填写授权表单字段')
                async with bind_agent_event_log(job.event_log):
                    result = await self.planner(selected=deepcopy(selected), instruction=instruction,
                                                session_id=f'native-pdf-forms:{job.task_id}',
                                                user_id=context.scope.user_id)
                if job.status != 'running':
                    return
                if monotonic() >= deadline:
                    raise TimeoutError
                if (not isinstance(result, dict) or not isinstance(result.get('answer'), str)
                        or not result['answer'].strip() or not isinstance(result.get('summary', ''), str)):
                    raise ReportingError('native_ai_output_empty', '未生成有效表单填写结果。')
                additions = validate_pdf_form_operations(result.get('operations'), frozen)
                if not additions:
                    raise ReportingError('native_ai_output_empty', '未生成可填写的授权字段候选。')
                replaced = {operation['fieldId'] for operation in additions}
                operations = [deepcopy(op) for op in base
                              if not (op.get('kind') == 'setFormValue' and op.get('fieldId') in replaced)]
                if len(operations) + len(additions) > 500:
                    raise ReportingError('native_ai_schema_invalid', '完整草稿不能超过500项操作。')
                changes = []
                fields = {field['fieldId']: field for field in frozen}
                for operation in additions:
                    field = fields[operation['fieldId']]
                    value_key = 'checked' if field['kind'] == 'checkbox' else 'value'
                    changes.append({'fieldId': field['fieldId'], 'name': field['name'], 'fieldKind': field['kind'],
                                    'before': deepcopy(field.get('value')), 'after': deepcopy(operation.get(value_key)),
                                    'operationIndex': len(operations)})
                    operations.append(operation)
                preview = await self.editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=operations)
                manifest = self._receipt(preview, context.source_file.sha256, len(operations))
                current = await self.editor.context_for_session(session)
                if current.digest() != job.context_sha256:
                    raise ReportingError('native_ai_snapshot_changed', 'PDF 会话来源已变化。')
                if monotonic() >= deadline:
                    raise TimeoutError
                applied = set(manifest['appliedOperationIndices'])
                for change in changes:
                    change['status'] = 'previewApplied' if change['operationIndex'] in applied else 'skipped'
                if job.status == 'running':
                    job.result = {'answer': result['answer'], 'summary': result.get('summary', ''),
                                  'operations': operations, 'changes': changes, **manifest,
                                  'sourceSha256': context.source_file.sha256, 'baseSnapshotSha256': native_digest(base),
                                  'coverage': deepcopy(result.get('coverage', {})),
                                  'toolEvents': deepcopy(result.get('toolEvents', [])), 'needsVerification': True}
                    job.status = 'succeeded'
        except asyncio.CancelledError:
            job.status, job.result = 'cancelled', None
            raise
        except Exception as error:
            if job.status == 'cancelled':
                return
            code, message = ((error.code, error.message) if isinstance(error, ReportingError) else
                             ('native_ai_timeout', '表单填写超时，请重试。') if isinstance(error, TimeoutError) else
                             ('native_ai_form_failed', '表单填写失败，来源与草稿保持原样。'))
            logger.warning('native_pdf_form_failed edit_id={} error_type={}', job.task_id, type(error).__name__)
            job.status, job.result, job.error = 'failed', None, {'code': code, 'message': message}
        finally:
            await job.event_log.finish(job.status)

    async def accept(self, session, edit_id, *, expected_sha256, operations, snapshot_sha256):
        context = await self._context(session)
        self.editor.require_enabled('pdf')
        self._prune()
        base = _copy_operations(operations)
        job = next((job for (digest, _), job in self._jobs.items()
                    if digest == context.digest() and job.task_id == edit_id), None)
        if job is None:
            raise ReportingError('native_ai_job_missing', '表单填写任务不存在或已过期。')
        if (expected_sha256 != context.source_file.sha256 or snapshot_sha256 != job.snapshot_sha256
                or base != getattr(job, 'base', None)):
            raise ReportingError('native_ai_snapshot_changed', '完整草稿或来源已变化，请重新填写。')
        proposal = job.result
        if job.status != 'succeeded' or proposal is None or self._closed:
            raise ReportingError('native_ai_candidate_unavailable', '候选已取消或尚不可采纳。')
        preview = await self.editor.preview_file(context, expected_sha256=expected_sha256,
                                                operations=deepcopy(proposal['operations']),
                                                expected_preview_digest=proposal['previewDigest'])
        manifest = self._receipt(preview, expected_sha256, len(proposal['operations']))
        current = await self.editor.context_for_session(session)
        if job.status != 'succeeded' or job.result is not proposal or self._closed:
            raise ReportingError('native_ai_candidate_unavailable', '候选已取消，不能采纳。')
        if current.digest() != job.context_sha256 or manifest != {key: proposal[key] for key in manifest}:
            raise ReportingError('native_ai_preview_changed', '实际预览已变化，请重新填写。')
        return {'operations': deepcopy(proposal['operations']), 'changes': deepcopy(proposal['changes']),
                **manifest, 'needsVerification': True}

    @staticmethod
    def _serialize(job):
        return {'editId': job.task_id, 'clientRequestId': job.client_request_id, 'status': job.status,
                'snapshotSha256': job.snapshot_sha256,
                **({'result': {'answer': job.result['answer'], 'proposal': deepcopy(job.result)}} if job.result is not None else {}),
                **({'error': deepcopy(job.error)} if job.error else {})}
