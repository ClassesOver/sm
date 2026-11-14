"""管理草稿与真实报告的短期双权限交接；不是全局偏好应用批准。"""

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from loguru import logger
from sqlalchemy import and_, delete, insert, or_, select, update

from ..report_editor.capabilities import EditorCapabilities
from ..report_editor.repository import report_editor_sessions_v1
from .models import ManagementError
from .preference_evidence import PreferenceEvidenceService, executor_manifest
from .preference_report_preflight import _RegisteredEditorSession
from .repository import accounts, sessions, token_hash
from .repository import preference_verification_handoffs as handoffs


class PreferenceVerificationHandoffService:
    def __init__(self, *, preferences, bound):
        self.preferences, self.bound = preferences, bound
        self.repository, self.auth = preferences.repository, preferences.auth
        self.evidence = PreferenceEvidenceService(self)

    async def _draft(self, connection, version, digest):
        row = await self.preferences._draft(connection)
        if row['version'] != version or row['content_hash'] != digest:
            raise ManagementError('management_version_conflict', '草稿已变化，请重新保存并关联报告。', 409)

    async def _record(self, connection, token, *, completed=False):
        row = (await connection.execute(select(handoffs).where(
            handoffs.c.token_hash == token_hash(token)))).mappings().one_or_none()
        now = self.auth.clock()
        if row is None or not completed and row['expires_at'] <= now:
            raise ManagementError('management_preference_handoff_expired', '报告关联已过期，请重新关联。', 409)
        # 编辑路径收不到管理Cookie；只核挑战已绑定的服务端管理会话，不续期该会话。
        session = (await connection.execute(select(sessions).where(
            sessions.c.token_hash == row['admin_session_hash']))).mappings().one_or_none()
        version = (await connection.execute(select(accounts.c.auth_version).where(accounts.c.id == 1))).scalar_one_or_none()
        if (not session or version != row['admin_auth_version']
            or session['auth_version'] != version or session['expires_at'] <= now
            or session['last_seen_at'] <= now - timedelta(minutes=30)):
            raise ManagementError('management_preference_handoff_revoked', '管理授权已失效，请重新登录并关联报告。', 403)
        if not completed:
            await self._draft(connection, row['draft_version'], row['draft_hash'])
        return row

    async def create(self, admin_session, *, expected_version, expected_hash):
        token, now = token_urlsafe(32), self.auth.clock()
        async with self.repository.transaction() as connection:
            actor = await self.repository.authenticate_in_transaction(connection, admin_session, now)
            await self._draft(connection, expected_version, expected_hash)
            await connection.execute(delete(handoffs).where(or_(
                and_(handoffs.c.expires_at <= now, handoffs.c.consumed_at.is_(None)),
                handoffs.c.consumed_at <= now - timedelta(days=1))))
            await connection.execute(insert(handoffs).values(token_hash=token_hash(token),
                admin_session_hash=token_hash(admin_session), admin_auth_version=actor.auth_version,
                draft_version=expected_version, draft_hash=expected_hash, expires_at=now + timedelta(minutes=5)))
        return {'handoffToken': token, 'expiresAt': (now + timedelta(minutes=5)).isoformat()}

    async def confirm(self, token, editor_session, *, report_id, revision):
        session = await self.bound.grants.lookup_session(editor_session)
        if not EditorCapabilities.of(session.capabilities).full:
            raise ManagementError('management_preference_full_editor_required', '需要此修订的完整编辑权限，分享会话不能用于偏好验收。', 403)
        context = await self.bound.editor.context_for_session(session)
        if session.report_id != report_id or session.revision != revision:
            raise ManagementError('management_preference_report_mismatch', '当前编辑会话与所选报告修订不一致。', 403)
        async with self.repository.transaction() as connection:
            row = await self._record(connection, token)
            if row['editor_session_hash'] is not None or row['consumed_at'] is not None:
                raise ManagementError('management_preference_handoff_used', '报告关联已确认，请发起新的关联。', 409)
            await connection.execute(update(handoffs).where(handoffs.c.token_hash == row['token_hash']).values(
                editor_session_hash=token_hash(editor_session), context_hash=context.digest(),
                report_id=context.report_id, revision=context.revision))
        return {'reportId': context.report_id, 'revision': context.revision}

    async def _check_editor(self, row):
        session = await self.bound.grants.lookup_registered_session(row['editor_session_hash'])
        if (not EditorCapabilities.of(session.capabilities).full or session.report_id != row['report_id']
            or session.revision != row['revision'] or session.context_sha256 != row['context_hash']):
            raise ManagementError('management_preference_handoff_revoked', '报告授权已变化，请重新打开报告并关联。', 403)
        context = await self.bound.editor.context_for_session(session)
        if context.digest() != row['context_hash']:
            raise ManagementError('management_preference_report_changed', '报告修订已变化，请重新关联。', 409)

    async def _check_editor_in_transaction(self, connection, row, *, workflow_run_id=None):
        # 与管理表共用数据库连接；持管理锁时不能另取连接以免池耗尽自锁。
        session = (await connection.execute(select(report_editor_sessions_v1).where(
            report_editor_sessions_v1.c.session_hash == row['editor_session_hash']).with_for_update(read=True))).mappings().one_or_none()
        if (not session or session['expires_at'] <= datetime.now(UTC)
            or not EditorCapabilities.of(session['capabilities']).full
            or workflow_run_id is not None and session['workflow_run_id'] != workflow_run_id
            or any(session[key] != row[target] for key, target in (
                ('report_id', 'report_id'), ('revision', 'revision'), ('context_sha256', 'context_hash')))):
            raise ManagementError('management_preference_handoff_revoked', '报告授权已变化，请重新打开报告并关联。', 403)

    async def _final_authority(self, admin_session, row, *, workflow_run_id=None):
        await self._check_editor(row)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, admin_session, self.auth.clock())
            final = await self._record(connection, row['_token'], completed=True)
            if any(final[key] != row[key] for key in ('admin_session_hash', 'admin_auth_version',
                'editor_session_hash', 'context_hash', 'report_id', 'revision', 'draft_version', 'draft_hash', 'consumed_at')):
                raise ManagementError('management_preference_handoff_changed', '验收期间报告关联发生变化。', 409)
            await self._check_editor_in_transaction(connection, final, workflow_run_id=workflow_run_id)

    async def run(self, admin_session, token, *, expected_version, expected_hash):
        async with self.repository.transaction() as connection:
            actor = await self.repository.authenticate_in_transaction(connection, admin_session, self.auth.clock())
            row = dict(await self._record(connection, token))
            if row['admin_session_hash'] != token_hash(admin_session) or actor.auth_version != row['admin_auth_version']:
                raise ManagementError('management_preference_handoff_owner', '请在发起关联的管理会话中验收。', 403)
            if row['draft_version'] != expected_version or row['draft_hash'] != expected_hash:
                raise ManagementError('management_version_conflict', '关联与当前草稿不一致，请重新关联。', 409)
            if row['consumed_at'] is not None or not row['editor_session_hash']:
                raise ManagementError('management_preference_handoff_used', '报告关联未确认或已使用，请重新关联。', 409)
            await self._check_editor_in_transaction(connection, row)
            row['consumed_at'] = self.auth.clock()
            await connection.execute(update(handoffs).where(handoffs.c.token_hash == row['token_hash']).values(consumed_at=row['consumed_at']))
        row['_token'] = token  # 仅本次请求闭包使用，禁止写入验收记录。
        await self._check_editor(row)
        manifest = None
        try:
            manifest = executor_manifest()
        except Exception:
            logger.warning('preference_executor_identity_unavailable stage=before_generation')
        # 不在管理事务或来源锁内等待Office生成；binder前后会再次读取两种授权及材料身份。
        result = await self.bound.run(admin_session=admin_session,
            editor_session=_RegisteredEditorSession(row['editor_session_hash']),
            expected_draft_version=expected_version, expected_draft_hash=expected_hash,
            expected_context_hash=row['context_hash'])
        workflow_run_id = result['binding']['workflowRunId']
        await self._final_authority(admin_session, row, workflow_run_id=workflow_run_id)
        current_manifest = None
        if manifest is not None:
            try:
                current_manifest = executor_manifest()
            except Exception:
                logger.warning('preference_executor_identity_unavailable stage=after_generation')
        identity_issue = None
        if manifest is None or current_manifest is None:
            identity_issue = {'code': 'management_preference_executor_identity_unavailable',
                'message': '无法读取生成前后的执行器身份；本次已生成且身份可读的文件保留，请重新验收，不能据此批准。'}
        elif manifest != current_manifest:
            logger.warning('preference_executor_changed stage=after_generation')
            identity_issue = {'code': 'management_preference_executor_changed',
                'message': '验收期间执行器发生变化；本次已生成且身份可读的文件保留，请重新验收，不能据此批准。'}
        if identity_issue is not None:
            result.setdefault('issues', []).append(identity_issue)
            result['status'], result['canApply'] = 'failed', False
        else:
            try:
                receipt, issues = await self.evidence.record_result(result, row, manifest)
                result['verificationReceipt'] = receipt
                if issues:
                    result.setdefault('issues', []).extend(issues)
                    result['status'], result['canApply'] = 'failed', False
            except Exception as error:
                logger.warning('preference_evidence_persistence_failed error_type={}', type(error).__name__)
                result.setdefault('issues', []).append({'code': 'management_preference_evidence_persistence_failed',
                    'message': '验收记录或独立留存回读失败；本次已生成且身份可读的文件保留，不能据此批准。'})
                result['status'], result['canApply'] = 'failed', False
        # 留证会等待工作区和数据库；兜底之外再次核授权，撤权不能当存储告警放行。
        await self._final_authority(admin_session, row, workflow_run_id=workflow_run_id)
        # 此处独立重验双会话及报告作用域已通过。草稿/材料验收失败仍返回已生成产物，
        # 保留binder的具体失败原因及canApply=False；只有撤权才在上面拒绝来源载荷。
        # 完整材料绑定供服务端留证；浏览器只获本报告所需展示，不提供内部workspace/身份清单。
        return {key: value for key, value in result.items() if key != 'binding'} | {
            'report': {'reportId': row['report_id'], 'revision': row['revision']},
            'bindingHash': result['binding']['bindingHash'], 'bindingValid': result['binding']['valid'], 'canApply': False}
