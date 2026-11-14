"""精确草稿、完整批准与有效版本的同事务CAS；不在应用时重新生成报告。"""

import re
from contextlib import AsyncExitStack
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)
from ..report_editor.trace_retention import source_lifecycle_lock
from ..reporting.workflow.state import ReportingStateError
from .configuration_store import configuration_hash
from .models import ManagementError
from .preference_evidence import executor_manifest
from .repository import (
    configuration_versions,
    preference_approval_receipts,
    preference_verification_results,
    token_hash,
)


class PreferenceApprovalService:
    def __init__(self, *, evidence):
        self.evidence, self.handoff = evidence, evidence.handoff
        self.preferences = evidence.preferences
        self.repository, self.auth = evidence.repository, evidence.auth
        self.preferences.approval_service = self

    def _unavailable(self, message='批准记录与当前草稿、合同、执行器或授权不一致，请重新验收。'):
        return ManagementError('management_preference_approval_stale', message, 409)

    def _identity(self, document, expected_version, expected_hash, contract_hash, manifest_hash):
        if (document.get('draft') != {'version': expected_version, 'contentHash': expected_hash}
            or document.get('contractHash') != contract_hash
            or document.get('executorManifestHash') != manifest_hash):
            raise self._unavailable()

    def _deadline(self, value):
        try:
            deadline = datetime.fromisoformat(value)
            if deadline <= self.auth.clock():
                raise self._unavailable('批准记录或依赖授权已过期，请重新验收。')
        except (TypeError, ValueError):
            raise self._unavailable('批准期限无效，请重新验收。') from None

    async def _lock_state_reads(self, guard, connection=None):
        try:
            await guard.lock(connection)
        except ReportingStateError:
            raise self._unavailable('批准依赖的工作流状态已变化或未完整读取，请重新验收。') from None
        except SQLAlchemyError:
            raise ManagementError('management_preference_state_unavailable',
                '无法稳定核验工作流状态，请稍后重新验收。', 503) from None

    async def apply(self, raw_session, *, expected_version, expected_hash,
        expected_effective_revision, approval_id, expected_approval_hash):
        actor = await self.auth.authenticate(raw_session)
        if (type(expected_version) is not int or expected_version < 1
            or type(expected_effective_revision) is not int or expected_effective_revision < 0
            or any(not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None
                for value in (expected_hash, expected_approval_hash))):
            raise ManagementError('management_input_invalid', '批准应用参数无效。', 422)
        receipt = await self.evidence._load(preference_approval_receipts, approval_id)
        document = receipt['document']
        if receipt['content_hash'] != expected_approval_hash:
            raise self._unavailable('批准记录摘要与请求不一致，请回读后重新确认。')
        contract = approval_contract()
        manifest = executor_manifest()
        contract_hash, manifest_hash = approval_contract_hash(contract), configuration_hash(manifest)
        self._identity(document, expected_version, expected_hash, contract_hash, manifest_hash)
        if self.evidence._runtime_identity_gaps(manifest):
            raise ManagementError('management_preference_executor_identity_unavailable',
                '验收执行器的必需资源身份未确认，请在验收汇总查看具体资源缺项。', 409)
        self._deadline(document.get('expiresAt'))
        if document.get('actorAuthVersion') != actor.auth_version:
            raise self._unavailable()
        if document.get('status') != 'ready' or document.get('canApply') is not True:
            raise ManagementError('management_preference_approval_incomplete',
                '当前批准仍有未覆盖要求，请在验收汇总中查看具体缺项。', 409)
        references = document.get('evidenceReferences')
        if not isinstance(references, list) or not references or len(references) > 20:
            raise self._unavailable('批准没有完整的服务端验收记录引用。')
        records, contexts, evidence = [], {}, []
        for reference in references:
            row = await self.evidence._load(preference_verification_results, reference['id'])
            if row['content_hash'] != reference['contentHash']:
                raise self._unavailable('批准依赖的验收记录摘要不一致。')
            item = await self.evidence._authorized(raw_session, row)
            self._identity(item, expected_version, expected_hash, contract_hash, manifest_hash)
            self._deadline(item['authBinding']['expiresAt'])
            records.append((reference, item))
            session = await self.handoff.bound.grants.lookup_registered_session(item['authBinding']['editorSessionHash'])
            context = await self.handoff.bound.editor.context_for_session(session)
            workspace = self.handoff.bound.editor.workspace_registry.get(context.scope['threadId'])
            contexts.setdefault(str(workspace.root), context)
        runtime_contract = {**contract, 'expectedBinding': {'draftVersion': expected_version,
            'draftHash': expected_hash, 'contractHash': contract_hash, 'executorManifestHash': manifest_hash}}
        # 核验至提交排他持有既有来源生命周期锁，避免共享来源操作在中途改动材料。
        # 固定顺序避免多个工作区互相等待，同任务的来源回读继续重入。
        # 此锁不能宣称为外部工作流数据库的分布式事务。
        async with AsyncExitStack() as locks:
            for _, context in sorted(contexts.items()):
                await locks.enter_async_context(source_lifecycle_lock(self.handoff.bound.editor, context, exclusive=True))
            capture = getattr(self.handoff.bound.editor.state_repository, 'capture_read_dependencies', None)
            if not callable(capture):
                raise ManagementError('management_preference_state_unavailable',
                    '当前工作流存储不支持稳定依赖核验，不能应用此批准。', 503)
            state_reads = await locks.enter_async_context(capture())
            for reference, item in records:
                await self.evidence._current_materials(raw_session, item)
                checked = await self.evidence._current_artifacts(item, reference['id'])
                evidence.extend(self.evidence._qualified_evidence(item, checked))
            if evaluate_required_coverage(runtime_contract, evidence):
                raise ManagementError('management_preference_approval_incomplete',
                    '批准依赖的完整证据不再覆盖当前合同，请重新验收。', 409)
            if (approval_contract_hash(approval_contract()) != contract_hash
                or configuration_hash(executor_manifest()) != manifest_hash):
                raise self._unavailable('验收执行器或合同在应用期间变化，请重新验收。')
            shared_pool = state_reads.shares_pool(self.repository.engine)
            if not shared_pool:
                await self._lock_state_reads(state_reads)
            async with self.repository.transaction() as connection:
                if shared_pool:
                    await self._lock_state_reads(state_reads, connection)
                current_actor = await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
                if current_actor.auth_version != document['actorAuthVersion']:
                    raise self._unavailable()
                self._deadline(document['expiresAt'])
                # 不在持管理事务时调用grants或另取连接，支持单连接池。
                for reference, item in records:
                    stored = (await connection.execute(select(preference_verification_results).where(
                        preference_verification_results.c.id == reference['id']))).mappings().one_or_none()
                    if (stored is None or stored['content_hash'] != reference['contentHash']
                        or configuration_hash(stored['document']) != reference['contentHash']):
                        raise self._unavailable()
                    authority, binding = item['authBinding'], item['binding']
                    if (authority['adminSessionHash'] != token_hash(raw_session)
                        or authority['adminAuthVersion'] != current_actor.auth_version):
                        raise self._unavailable()
                    self._deadline(authority['expiresAt'])
                    # 同连接helper持编辑会话共享行锁，与撤权删除串行化到提交。
                    await self.handoff._check_editor_in_transaction(connection,
                        {'editor_session_hash': authority['editorSessionHash'], 'report_id': binding['reportId'],
                            'revision': binding['revision'], 'context_hash': binding['contextSha256']},
                        workflow_run_id=binding['workflowRunId'])
                stored_receipt = (await connection.execute(select(preference_approval_receipts).where(
                    preference_approval_receipts.c.id == approval_id))).mappings().one_or_none()
                if (stored_receipt is None or stored_receipt['content_hash'] != expected_approval_hash
                    or configuration_hash(stored_receipt['document']) != expected_approval_hash):
                    raise self._unavailable()
                self._deadline(document['expiresAt'])
                for _, item in records:
                    self._deadline(item['authBinding']['expiresAt'])
                draft = await self.preferences._draft(connection)
                if draft['version'] != expected_version or draft['content_hash'] != expected_hash:
                    raise ManagementError('management_version_conflict', '草稿已变化，请重新保存并验收。', 409)
                latest = await self.preferences._latest(connection)
                if latest:
                    self.preferences._verified(latest['document'], latest['content_hash'])
                effective_revision = latest['revision'] if latest else 0
                if latest and latest['preference_approval_id'] == approval_id:
                    # 只回放同一批准、原始CAS期望且仍为latest的精确已提交结果。
                    if (latest['draft_version'] != expected_version or latest['content_hash'] != expected_hash
                        or expected_effective_revision != latest['revision'] - 1):
                        raise self._unavailable('此批准已被消费，当前请求不是同一次应用重试。')
                    published = self.preferences._version_payload(latest)
                else:
                    if effective_revision != expected_effective_revision:
                        raise ManagementError('management_effective_version_conflict', '有效偏好版本已变化，请回读后比较。', 409)
                    used = await connection.scalar(select(configuration_versions.c.revision).where(
                        configuration_versions.c.preference_approval_id == approval_id))
                    if used is not None:
                        raise self._unavailable('此批准已发布过一个版本，不能再次使用。')
                    published = await self.preferences._publish_in_transaction(connection, draft, latest,
                        approval_id=approval_id)
        # 只有提交后的独立回读身份匹配，才返回应用结果；响应丢失可用同请求重试。
        readback = await self.preferences.version(raw_session, published['revision'])
        if (readback['approvalId'] != approval_id or readback['contentHash'] != expected_hash
            or readback['draftVersion'] != expected_version):
            raise self._unavailable('应用已提交但独立回读身份不一致，请回读有效版本。')
        return readback
