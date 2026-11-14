"""在现有授权工作区与产物仓库中独立留存验收文件；不签发下载授权。"""

import base64
import hashlib
from copy import deepcopy
from uuid import UUID

from loguru import logger

from ..report_editor.capabilities import EditorCapabilities
from ..report_editor.service import ReportEditorContext
from ..reporting.delivery.publishing import (
    MAX_DOWNLOAD_BYTES,
    ReportArtifactSpec,
    ReportDownloadScope,
    _artifact_key,
)
from ..reporting.models import ReportingError
from ..reporting.workflow.scope import resolve_reporting_workflow_scope


class PreferenceArtifactRetention:
    def __init__(self, *, bound):
        self.bound = bound

    async def _scope(self, editor_session_hash, expected_context_sha256=None):
        editor = self.bound.editor
        # 授权失败不属于逐产物存储软失败；调用方交付前仍须再次复核双权限。
        session = await self.bound.grants.lookup_registered_session(editor_session_hash)
        if not EditorCapabilities.of(session.capabilities).full:
            raise ReportingError('dataset_access_denied', '偏好验收留存需要完整编辑权限。')
        # 先核验耐久context，再仅恢复真实存在的原工作区，不能因验收补建已回收目录。
        state = await editor.state_repository.get(session.workflow_run_id)
        contexts = state.payload.get('reportEditorContexts') if state is not None else None
        try:
            context = ReportEditorContext.model_validate(
                contexts.get(str(session.revision)) if isinstance(contexts, dict) else None)
        except Exception as error:
            raise ReportingError('report_editor_context_missing', '报告编辑上下文不存在。') from error
        if (context.report_id != session.report_id or context.revision != session.revision
            or context.workflow_run_id != session.workflow_run_id or context.digest() != session.context_sha256
            or expected_context_sha256 is not None and context.digest() != expected_context_sha256):
            raise ReportingError('report_editor_scope_mismatch', '验收记录与当前报告编辑上下文不一致。')
        scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
            session_id=context.scope['sessionId'], user_id=context.scope['userId'], stored_scope=context.scope)
        editor.workspace_registry.resolve(scope, create=False)
        return ReportDownloadScope(database=scope.database, company_id=scope.company_id,
            user_id=scope.user_id, session_id=scope.session_id, thread_id=scope.workspace_key,
            workflow_run_id=scope.run_id)

    async def _read_reference(self, scope, reference):
        persistence = self.bound.editor.artifact_persistence
        if persistence is None:
            raise ValueError('artifact persistence unavailable')
        key = reference['artifactKey']
        stored = await persistence.repository.get(key)
        if (stored is None or stored.artifact_key != key or stored.scope != scope
            or stored.report_id != reference['reportId'] or stored.revision != reference['revision']
            or stored.artifact != reference['artifact'] or stored.path != reference['path']
            or stored.size != reference['size'] or stored.sha256 != reference['sha256']):
            raise ValueError('retained artifact metadata mismatch')
        digest, total = hashlib.sha256(), 0
        async for chunk in persistence.repository.stream(key):
            if not isinstance(chunk, bytes):
                raise ValueError('retained artifact chunk invalid')
            total += len(chunk)
            if total > reference['size']:
                raise ValueError('retained artifact oversized')
            digest.update(chunk)
        if total != reference['size'] or digest.hexdigest() != reference['sha256']:
            raise ValueError('retained artifact bytes mismatch')

    async def recheck(self, retained, *, verification_id, editor_session_hash, expected_context_sha256):
        """消费证据前，按当前授权重读仓库；引用本身不能授予其他报告读取权。"""
        verification_id = str(UUID(verification_id))
        if not isinstance(expected_context_sha256, str) or len(expected_context_sha256) != 64:
            raise ReportingError('report_editor_scope_mismatch', '验收记录缺少报告编辑上下文身份。')
        scope = await self._scope(editor_session_hash, expected_context_sha256)
        checked = {'formats': {}, 'issues': deepcopy(retained.get('issues', []))}
        for format, entries in retained.get('formats', {}).items():
            for role, reference in entries.items():
                stage = 'reference'
                try:
                    if format not in ('md', 'pdf', 'word', 'xlsx', 'pptx') or role not in ('artifact', 'pdf'):
                        raise ValueError('unsupported artifact role')
                    artifact = 'pdf' if role == 'pdf' else format
                    extension = 'docx' if artifact == 'word' else artifact
                    path = f'reports/preference-verifications/{verification_id}/{format}/{role}.{extension}'
                    report_id = f'preference-verification:{verification_id}:{format}:{role}'
                    if (not isinstance(reference, dict) or type(reference.get('size')) is not int
                        or not 0 < reference['size'] <= MAX_DOWNLOAD_BYTES
                        or type(reference.get('revision')) is not int or reference['revision'] != 1
                        or reference.get('artifact') != artifact or reference.get('path') != path
                        or reference.get('reportId') != report_id
                        or not isinstance(reference.get('sha256'), str)
                        or len(reference['sha256']) != 64
                        or any(char not in '0123456789abcdef' for char in reference['sha256'])):
                        raise ValueError('retained artifact reference mismatch')
                    spec = ReportArtifactSpec(artifact=artifact, path=path, size=reference['size'],
                        sha256=reference['sha256'])
                    if reference.get('artifactKey') != _artifact_key(scope, report_id, 1, spec):
                        raise ValueError('retained artifact scope mismatch')
                    stage = 'readback'
                    await self._read_reference(scope, reference)
                    checked['formats'].setdefault(format, {})[role] = {
                        key: reference[key] for key in (
                            'artifactKey', 'reportId', 'revision', 'artifact', 'path', 'size', 'sha256')}
                except Exception as error:
                    logger.warning('preference_artifact_recheck_failed format={} role={} stage={} error_type={}',
                        format, role, stage, type(error).__name__)
                    checked['issues'].append({'code': 'management_preference_artifact_recheck_failed',
                        'message': f'{format}/{role} 验收留存文件复核失败（{stage}），请重新验收。',
                        'format': format, 'role': role, 'stage': stage})
        return checked

    async def retain(self, result, *, verification_id, editor_session_hash):
        """仅接收服务端结果；引用有效期由证据服务限制在现有授权与清理期限内。"""
        verification_id = str(UUID(verification_id))
        download_scope = await self._scope(editor_session_hash)
        editor = self.bound.editor
        retained = {'formats': {}, 'issues': []}
        persistence = editor.artifact_persistence
        for format in ('md', 'pdf', 'word', 'xlsx', 'pptx'):
            entry = result.get('formats', {}).get(format) or {}
            for role in ('artifact', 'pdf'):
                inline = entry.get(role)
                if inline is None:
                    continue
                stage = 'identity'
                try:
                    if (not isinstance(inline, dict) or type(inline.get('size')) is not int
                        or not 0 < inline['size'] <= MAX_DOWNLOAD_BYTES
                        or not isinstance(inline.get('base64'), str)
                        or len(inline['base64']) > 4 * ((MAX_DOWNLOAD_BYTES + 2) // 3)):
                        raise ValueError('invalid inline artifact identity')
                    content = base64.b64decode(inline['base64'], validate=True)
                    if len(content) != inline['size'] or hashlib.sha256(content).hexdigest() != inline.get('sha256'):
                        raise ValueError('inline artifact identity mismatch')
                    if persistence is None:
                        raise ValueError('artifact persistence unavailable')
                    artifact = 'pdf' if role == 'pdf' else format
                    extension = 'docx' if artifact == 'word' else artifact
                    path = f'reports/preference-verifications/{verification_id}/{format}/{role}.{extension}'
                    report_id = f'preference-verification:{verification_id}:{format}:{role}'
                    spec = ReportArtifactSpec(artifact=artifact, path=path,
                        size=inline['size'], sha256=inline['sha256'])
                    stage = 'workspace_write'
                    await editor.workspace.awrite_bytes(download_scope.thread_id, path, content, overwrite=False)
                    stage = 'persist'
                    await persistence.persist(scope=download_scope, report_id=report_id, revision=1, artifacts=(spec,))
                    stage = 'readback'
                    key = _artifact_key(download_scope, report_id, 1, spec)
                    reference = {'artifactKey': key,
                        'reportId': report_id, 'revision': 1, 'artifact': artifact,
                        'path': path, 'size': spec.size, 'sha256': spec.sha256}
                    await self._read_reference(download_scope, reference)
                    retained['formats'].setdefault(format, {})[role] = reference
                except Exception as error:
                    logger.warning('preference_artifact_retention_failed format={} role={} stage={} error_type={}',
                        format, role, stage, type(error).__name__)
                    retained['issues'].append({'code': 'management_preference_artifact_retention_failed',
                        'message': f'{format}/{role} 验收产物留存失败（{stage}）；实际生成文件仍保留，不能据此批准。',
                        'format': format, 'role': role, 'stage': stage})
        return retained
