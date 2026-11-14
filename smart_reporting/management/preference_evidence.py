"""已授权真实验收的不可变留证与缺项汇总，不把采样自动提升为应用批准。"""

import tempfile
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import insert, select

from ..preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)
from ..report_editor.trace_retention import source_lifecycle_lock
from ..reporting.models import ReportingError
from .configuration_store import configuration_hash
from .models import ManagementError
from .preference_artifact_retention import PreferenceArtifactRetention
from .preference_executor import executor_manifest
from .preference_native_evidence import (
    map_native_chart_image_dpi_evidence,
    map_native_pptx_indent_evidence,
    map_native_signature_evidence,
)
from .preference_pptx_table_evidence import map_pptx_table_evidence
from .preference_report_preflight import _RegisteredEditorSession
from .preference_word_caption_evidence import map_word_caption_evidence
from .preference_word_table_evidence import map_word_table_evidence
from .preference_workbook_header_footer_evidence import map_workbook_header_footer_evidence
from .preference_workbook_number_evidence import map_workbook_number_evidence
from .preference_workbook_signature_evidence import map_workbook_signature_evidence
from .repository import (
    preference_approval_receipts,
    preference_verification_results,
    sessions,
    token_hash,
)


def _result_without_bytes(result):
    result = deepcopy({key: value for key, value in result.items() if key != 'binding'})
    for entry in result.get('formats', {}).values():
        for role in ('artifact', 'pdf'):
            if entry.get(role) is not None:
                entry[role] = {key: value for key, value in entry[role].items()
                    if key in {'filename', 'mediaType', 'size', 'sha256'}}
    return result


class PreferenceEvidenceService:
    def __init__(self, handoff):
        self.handoff, self.preferences = handoff, handoff.preferences
        self.repository, self.auth = handoff.repository, handoff.auth
        self.retention = PreferenceArtifactRetention(bound=handoff.bound)

    async def _insert(self, table, id, document):
        digest = configuration_hash(document)
        async with self.repository.transaction() as connection:
            await connection.execute(insert(table).values(id=id, document=document,
                content_hash=digest, created_at=self.auth.clock()))
        return digest

    async def _load(self, table, id):
        try:
            if str(UUID(id)) != id:
                raise ValueError('noncanonical id')
        except (ValueError, TypeError, AttributeError):
            raise ManagementError('management_preference_evidence_invalid', '验收记录标识无效。', 422) from None
        async with self.repository.engine.connect() as connection:
            row = (await connection.execute(select(table).where(table.c.id == id))).mappings().one_or_none()
        if row is None or configuration_hash(row['document']) != row['content_hash']:
            raise ManagementError('management_preference_evidence_invalid', '验收记录不存在或身份不一致。', 409)
        return dict(row)

    async def record_result(self, result, handoff_row, manifest):
        id = str(uuid4())
        contract = approval_contract()
        contract_hash, manifest_hash = approval_contract_hash(contract), configuration_hash(manifest)
        # 原始结果和独立存储回读都保留；不把持久化成功写成原生验收通过。
        retained = await self.retention.retain(result, verification_id=id,
            editor_session_hash=handoff_row['editor_session_hash'])
        async with self.repository.engine.connect() as connection:
            admin_expiry = await connection.scalar(select(sessions.c.expires_at).where(
                sessions.c.token_hash == handoff_row['admin_session_hash']))
        editor = await self.handoff.bound.grants.lookup_registered_session(handoff_row['editor_session_hash'])
        if admin_expiry is None:
            raise ManagementError('management_preference_evidence_revoked', '管理授权已失效。', 403)
        expires_at = min(admin_expiry, editor.expires_at, self.auth.clock() + timedelta(minutes=30))
        runtime_contract = {**contract, 'expectedBinding': {'draftVersion': handoff_row['draft_version'],
            'draftHash': handoff_row['draft_hash'], 'contractHash': contract_hash, 'executorManifestHash': manifest_hash}}
        evidence = map_native_signature_evidence(result, contract, runtime_contract['expectedBinding'], retained)
        evidence.extend(map_native_chart_image_dpi_evidence(
            result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_pptx_table_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_native_pptx_indent_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_word_caption_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_word_table_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_workbook_header_footer_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_workbook_signature_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        evidence.extend(map_workbook_number_evidence(result, contract, runtime_contract['expectedBinding'], retained))
        runtime_gaps = self._runtime_identity_gaps(manifest)
        if runtime_gaps:
            evidence = [row for row in evidence if row['status'] == 'failed']
        # 仅补已审查的严格内容字段；原生字段证据不能替代完整场景、视觉或生命周期验收。
        gaps = evaluate_required_coverage(runtime_contract, evidence) + runtime_gaps
        document = {'schemaVersion': 1,
            'draft': {'version': handoff_row['draft_version'], 'contentHash': handoff_row['draft_hash']},
            'contractHash': contract_hash, 'contractVersion': contract['contractVersion'],
            'executorManifestHash': manifest_hash, 'executorManifest': manifest,
            'authBinding': {'adminSessionHash': handoff_row['admin_session_hash'],
                'adminAuthVersion': handoff_row['admin_auth_version'],
                'editorSessionHash': handoff_row['editor_session_hash'], 'expiresAt': expires_at.isoformat()},
            'binding': deepcopy(result['binding']), 'result': _result_without_bytes(result), 'retained': retained,
            'evidence': evidence, 'assessment': {'status': 'incomplete' if gaps else 'ready',
                'canApply': not gaps, 'missingRequirements': gaps}}
        digest = await self._insert(preference_verification_results, id, document)
        stored = await self._load(preference_verification_results, id)
        if stored['content_hash'] != digest:
            raise ValueError('independent evidence readback mismatch')
        return {'id': id, 'contentHash': digest, 'contractHash': contract_hash,
            'executorManifestHash': manifest_hash, 'expiresAt': expires_at.isoformat()}, retained['issues']

    async def _authorized(self, raw_session, row):
        await self.auth.authenticate(raw_session)
        document = row['document']
        binding, authority = document['binding'], document['authBinding']
        if (token_hash(raw_session) != authority['adminSessionHash']
            or datetime.fromisoformat(authority['expiresAt']) <= self.auth.clock()):
            raise ManagementError('management_preference_evidence_expired', '此管理会话的验收记录已失效，请重新验收。', 403)
        expected = {'report_id': binding['reportId'], 'revision': binding['revision'],
            'editor_session_hash': authority['editorSessionHash'], 'context_hash': binding['contextSha256']}
        try:
            # 常规编辑恢复会登记工作区；消费留证前先确认原登记仍存在。
            await self.retention._scope(authority['editorSessionHash'], binding['contextSha256'])
            await self.handoff._check_editor(expected)
        except ReportingError as error:
            raise ManagementError(error.code, error.message, 403) from None
        return document

    async def read(self, raw_session, id):
        await self.auth.authenticate(raw_session)
        row = await self._load(preference_verification_results, id)
        document = await self._authorized(raw_session, row)
        # 不向浏览器提供内部工作区、材料清单、会话摘要或仓库读取键。
        return {'id': id, 'contentHash': row['content_hash'], 'draft': document['draft'],
            'contractHash': document['contractHash'], 'contractVersion': document['contractVersion'],
            'executorManifestHash': document['executorManifestHash'],
            'expiresAt': document['authBinding']['expiresAt'], 'assessment': document['assessment']}

    async def list_for_draft(self, raw_session, *, expected_version, expected_hash):
        await self.auth.authenticate(raw_session)
        draft = (await self.preferences.detail(raw_session))['draft']
        if (type(expected_version) is not int or draft['version'] != expected_version
            or draft['contentHash'] != expected_hash):
            raise ManagementError('management_version_conflict', '草稿已变化，请回读后重新加载验收记录。', 409)
        contract = approval_contract()
        manifest = executor_manifest()
        statement = (select(preference_verification_results)
            .where(preference_verification_results.c.document['authBinding']['adminSessionHash'].as_string()
                == token_hash(raw_session))
            .where(preference_verification_results.c.document['draft']['version'].as_integer() == expected_version)
            .where(preference_verification_results.c.document['draft']['contentHash'].as_string() == expected_hash)
            .where(preference_verification_results.c.document['contractHash'].as_string() == approval_contract_hash(contract))
            .where(preference_verification_results.c.document['executorManifestHash'].as_string()
                == configuration_hash(manifest))
            .order_by(preference_verification_results.c.created_at.desc()).limit(20))
        async with self.repository.engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        records = []
        for candidate in rows:
            try:
                row = await self._load(preference_verification_results, candidate['id'])
                document = await self._authorized(raw_session, row)
            except ManagementError as error:
                logger.info('preference_verification_record_not_listed id={} code={}', candidate['id'], error.code)
                continue
            binding = document['binding']
            records.append({'id': row['id'], 'contentHash': row['content_hash'],
                'contractHash': document['contractHash'], 'executorManifestHash': document['executorManifestHash'],
                'expiresAt': document['authBinding']['expiresAt'], 'createdAt': row['created_at'].isoformat(),
                'draft': document['draft'], 'report': {'reportId': binding['reportId'], 'revision': binding['revision']},
                'assessment': {'status': document['assessment']['status'], 'canApply': document['assessment']['canApply'],
                    'missingRequirementCount': len(document['assessment']['missingRequirements'])}})
        return records

    async def _current_materials(self, raw_session, document):
        authority, binding = document['authBinding'], document['binding']
        _, context, state = await self.handoff.bound._authorize(raw_session,
            _RegisteredEditorSession(authority['editorSessionHash']), binding['contextSha256'])
        with tempfile.TemporaryDirectory(prefix='preference-evidence-current-') as directory:
            async with source_lifecycle_lock(self.handoff.bound.editor, context):
                await self.handoff.bound.editor._ensure_sources_retained(context)
                state = await self.handoff.bound._state_for_context(context)
                _, _, current = await self.handoff.bound._snapshot(context, state, Path(directory))
        if not binding['valid'] or configuration_hash(current) != binding['bindingHash']:
            raise ManagementError('management_preference_materials_changed', '验收记录的报告材料已变化或未完成绑定。', 409)

    async def _current_artifacts(self, document, id):
        authority, binding = document['authBinding'], document['binding']
        checked = await self.retention.recheck(document['retained'], verification_id=id,
            editor_session_hash=authority['editorSessionHash'], expected_context_sha256=binding['contextSha256'])
        expected = {(format, role): inline
            for format, entry in document['result'].get('formats', {}).items()
            for role in ('artifact', 'pdf') if (inline := entry.get(role)) is not None}
        actual = {(format, role): reference for format, entry in checked['formats'].items()
            for role, reference in entry.items()}
        if (checked['issues'] or actual.keys() != expected.keys()
            or any(actual[key]['size'] != inline['size'] or actual[key]['sha256'] != inline['sha256']
                for key, inline in expected.items())):
            raise ManagementError('management_preference_retained_artifact_changed',
                '验收留存文件缺失、身份变化或未完成独立留存，请重新验收；此前已生成文件仍保留。', 409)
        return checked

    @staticmethod
    def _runtime_identity_gaps(manifest):
        issues = manifest.get('runtimeIdentityIssues')
        if manifest.get('runtimeIdentityComplete') is True and issues == []:
            return []
        resources = [item.get('resource', '未确认运行资源') for item in issues] if isinstance(issues, list) else []
        return [{'requirementId': 'native-editable-role-style', 'reason': 'executor_identity_unavailable',
            'missingDimensions': ['lifecycle'],
            'message': f'实际执行器资源身份未确认：{resource}；请修复部署资源后重新验收。'}
            for resource in resources or ['未确认运行资源']]

    @staticmethod
    def _qualified_evidence(document, checked):
        """每个V只引用本记录独立回读的实际文件，不能拿另一材料的摘要充数。"""
        evidence = document['evidence']
        for row in evidence:
            source, artifact = row.get('sourceArtifact', {}), row.get('artifact', {})
            reference = checked['formats'].get(source.get('format'), {}).get(source.get('role'))
            if (row.get('authorized') is not True or reference is None
                or row.get('format') in ('md', 'pdf', 'word', 'xlsx', 'pptx') and source.get('format') != row['format']
                or row.get('dimension') == 'native' and source.get('role') != 'artifact'
                or row.get('dimension') == 'visual' and not (source.get('role') == 'pdf'
                    or source.get('format') == 'pdf' and source.get('role') == 'artifact')
                or type(artifact.get('sizeBytes')) is not int or artifact['sizeBytes'] != reference['size']
                or artifact.get('sha256') != reference['sha256']):
                raise ManagementError('management_preference_evidence_artifact_mismatch',
                    '要求证据未绑定本次独立回读的实际文件，请重新验收。', 409)
        return evidence

    async def prepare(self, raw_session, *, expected_version, expected_hash, evidence_ids):
        if (not isinstance(evidence_ids, list) or not 1 <= len(evidence_ids) <= 20
            or len(set(evidence_ids)) != len(evidence_ids)):
            raise ManagementError('management_preference_evidence_invalid', '请选择1至20条不重复的验收记录。', 422)
        draft = (await self.preferences.detail(raw_session))['draft']
        if type(expected_version) is not int or draft['version'] != expected_version or draft['contentHash'] != expected_hash:
            raise ManagementError('management_version_conflict', '草稿已变化，请回读后重新汇总。', 409)
        contract = approval_contract()
        manifest = executor_manifest()
        contract_hash, manifest_hash = approval_contract_hash(contract), configuration_hash(manifest)
        evidence, references, deadlines = [], [], []
        for id in evidence_ids:
            row = await self._load(preference_verification_results, id)
            document = await self._authorized(raw_session, row)
            if (document['draft'] != {'version': expected_version, 'contentHash': expected_hash}
                or document['contractHash'] != contract_hash or document['executorManifestHash'] != manifest_hash):
                raise ManagementError('management_preference_evidence_stale', '验收记录与当前草稿、合同或执行器不一致，请重新验收。', 409)
            checked = await self._current_artifacts(document, id)
            await self._current_materials(raw_session, document)
            evidence.extend(self._qualified_evidence(document, checked))
            references.append({'id': id, 'contentHash': row['content_hash']})
            deadlines.append(document['authBinding']['expiresAt'])
        runtime_contract = {**contract, 'expectedBinding': {'draftVersion': expected_version,
            'draftHash': expected_hash, 'contractHash': contract_hash, 'executorManifestHash': manifest_hash}}
        gaps = evaluate_required_coverage(runtime_contract, evidence) + self._runtime_identity_gaps(manifest)
        # 局部字段证据不表示完整场景通过；只有服务端合格证据全部闭合才可就绪。
        document = {'schemaVersion': 1, 'draft': {'version': expected_version, 'contentHash': expected_hash},
            'contractHash': contract_hash, 'contractVersion': contract['contractVersion'],
            'requirementsVersion': contract['requirementsVersion'],
            'executorManifestHash': manifest_hash, 'evidenceReferences': references,
            'expiresAt': min(deadlines), 'actorAuthVersion': (await self.auth.authenticate(raw_session)).auth_version,
            'status': 'incomplete' if gaps else 'ready', 'canApply': not gaps, 'missingRequirements': gaps}
        id = str(uuid4())
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            await self.handoff._draft(connection, expected_version, expected_hash)
            if datetime.fromisoformat(document['expiresAt']) <= self.auth.clock():
                raise ManagementError('management_preference_evidence_expired', '验收记录已失效，请重新验收。', 409)
            for reference in references:
                item = (await connection.execute(select(preference_verification_results.c.document).where(
                    preference_verification_results.c.id == reference['id']))).scalar_one()
                binding, authority = item['binding'], item['authBinding']
                await self.handoff._check_editor_in_transaction(connection,
                    {'editor_session_hash': authority['editorSessionHash'], 'report_id': binding['reportId'],
                        'revision': binding['revision'], 'context_hash': binding['contextSha256']},
                    workflow_run_id=binding['workflowRunId'])
            digest = configuration_hash(document)
            await connection.execute(insert(preference_approval_receipts).values(id=id, document=document,
                content_hash=digest, created_at=self.auth.clock()))
        stored = await self._load(preference_approval_receipts, id)
        if stored['content_hash'] != digest:
            raise ValueError('approval summary readback mismatch')
        return {'id': id, 'contentHash': digest, **document}
