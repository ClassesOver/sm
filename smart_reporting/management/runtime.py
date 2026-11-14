from __future__ import annotations

from sqlalchemy import insert, select

from .data_sources.secrets import CredentialVault
from .models import ManagementError, ManagementScope
from .repository import runtime_snapshots
from .run_preferences import freeze_run_preferences, read_run_preferences
from .scopes import ScopeService


class ManagedConfigurationProvider:
    def __init__(self, scope_service: ScopeService, vault: CredentialVault, *, startup_settings=None):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.vault = vault
        self.startup_settings = startup_settings

    async def register_run(
        self, run_id: str, scope: ManagementScope, *, user_id: str, thread_id: str, entrypoint: str
    ) -> dict | None:
        """仅供服务端已核验入口调用；不注册为 HTTP 或模型工具。"""
        if entrypoint not in {"http-capability", "mcp", "cli"} or any(
            not item or len(item) > 256 for item in (run_id, user_id, thread_id)
        ):
            raise ManagementError("management_run_identity_invalid", "缺少可信报告入口身份。", 403)
        async with self.repository.transaction() as connection:
            scope_row = await ScopeService.require_registered(connection, scope)
            current = (
                (
                    await connection.execute(
                        select(runtime_snapshots).where(
                            runtime_snapshots.c.scope_id == scope_row["id"],
                            runtime_snapshots.c.run_id == run_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if current:
                if (current["user_id"], current["thread_id"], current["entrypoint"]) != (
                    user_id,
                    thread_id,
                    entrypoint,
                ):
                    raise ManagementError(
                        "management_run_identity_conflict", "运行身份与已登记记录不一致。", 403
                    )
                return await read_run_preferences(connection, scope_row["id"], run_id)
            await connection.execute(
                insert(runtime_snapshots).values(
                    scope_id=scope_row["id"],
                    run_id=run_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    entrypoint=entrypoint,
                    references=None,
                    reference_hash=None,
                    created_at=self.scope_service.auth.clock(),
                )
            )
            if self.startup_settings is not None:
                return await freeze_run_preferences(connection, auth=self.scope_service.auth, startup=self.startup_settings,
                    scope_id=scope_row["id"], run_id=run_id)
            return None

    async def load_run_preferences(self, run_id, scope, *, user_id, thread_id):
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            row = await self._run(connection, registered["id"], run_id)
            if (row["user_id"], row["thread_id"]) != (user_id, thread_id):
                raise ManagementError("management_run_identity_conflict", "运行身份与已登记记录不一致。", 403)
            return await read_run_preferences(connection, registered["id"], run_id)

    async def load_run_system_settings(self, run_id, scope, *, user_id, thread_id, startup_settings=None):
        """执行前按可信入口身份恢复系统值；不供模型工具或下载签发调用。"""
        from dataclasses import replace

        from .configuration_store import configuration_hash
        from .repository import configuration_versions, system_credentials
        from .run_system_settings import (
            invalid_run_system_configuration,
            resolve_run_system_settings,
        )
        from .system_configuration import CREDENTIAL_ATTRIBUTES, validate_system_document

        startup = startup_settings if startup_settings is not None else self.startup_settings
        if startup is None:
            raise ValueError('恢复任务系统配置需要当前启动设置')
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            row = await self._run(connection, registered['id'], run_id)
            if (row['user_id'], row['thread_id']) != (user_id, thread_id):
                raise ManagementError('management_run_identity_conflict', '运行身份与已登记记录不一致。', 403)
            snapshot = await read_run_preferences(connection, registered['id'], run_id)
            resolved = resolve_run_system_settings(startup, snapshot)
            if snapshot is None or snapshot.get('systemRevision') is None:
                return resolved
            record = (await connection.execute(select(configuration_versions).where(
                configuration_versions.c.kind == 'system',
                configuration_versions.c.revision == snapshot['systemRevision'],
            ))).mappings().one_or_none()
            try:
                valid = record is not None and record['content_hash'] == snapshot['systemHash']
                valid = valid and configuration_hash(record['document']) == record['content_hash']
                valid = valid and validate_system_document(resolved.settings, record['document']) == record['document']
                valid = valid and all((snapshot.get('systemValues') or {}).get(key, value) == value
                    for key, value in record['document']['values'].items())
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise invalid_run_system_configuration()
            references = record['document'].get('credentials', {})
            if not references:
                return resolved
            secrets = {}
            for key, reference in references.items():
                credential = (await connection.execute(select(system_credentials).where(
                    system_credentials.c.key == key, system_credentials.c.reference == reference,
                ))).mappings().one_or_none()
                if credential is None:
                    raise ManagementError('management_run_system_credential_unavailable',
                        '本运行冻结的系统凭据无法读取，未使用当前凭据替代。', 503)
                try:
                    secrets[CREDENTIAL_ATTRIBUTES[key]] = self.vault.decrypt(credential['key_id'], credential['ciphertext'].encode())
                except ManagementError:
                    raise ManagementError('management_run_system_credential_unavailable',
                        '本运行冻结的系统凭据无法解密，请检查历史密钥；未使用当前凭据替代。', 503) from None
            current = [key for key, attribute in CREDENTIAL_ATTRIBUTES.items()
                if key not in references and getattr(startup, attribute) is not None]
            issues = tuple(issue for issue in resolved.issues
                if issue['code'] != 'management_run_system_credentials_current')
            if current:
                issues += ({'code': 'management_run_system_credentials_current',
                    'message': '部分系统凭据没有历史引用，所列字段使用当前启动凭据；其余已核验引用按历史版本恢复。',
                    'keys': current},)
            return replace(resolved, settings=replace(resolved.settings, **secrets), issues=issues,
                credential_source='mixed' if current else 'historical_reference')

    async def inherit_run_preferences(self, parent_run_id, run_id, scope, *, user_id, thread_id, entrypoint):
        """派生执行继承可信来源，禁止读取后来更新的全局默认。"""
        from zoneinfo import ZoneInfo

        from .configuration_store import configuration_hash
        from .repository import run_configuration_snapshots

        if (entrypoint not in {'report_revision', 'policy_adoption'} or parent_run_id == run_id
                or any(not value or len(value) > 256 for value in (parent_run_id, run_id, user_id, thread_id))):
            raise ManagementError('management_run_identity_invalid', '派生运行身份无效。', 403)
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            scope_id = registered['id']
            parent = await self._run(connection, scope_id, parent_run_id)
            if (parent['user_id'], parent['thread_id']) != (user_id, thread_id):
                raise ManagementError('management_run_identity_conflict', '来源运行身份不一致。', 403)
            snapshot = await read_run_preferences(connection, scope_id, parent_run_id)
            current = (await connection.execute(select(runtime_snapshots).where(
                runtime_snapshots.c.scope_id == scope_id, runtime_snapshots.c.run_id == run_id,
            ))).mappings().one_or_none()
            if current is not None:
                saved = await read_run_preferences(connection, scope_id, run_id)
                if ((current['user_id'], current['thread_id'], current['entrypoint']) != (user_id, thread_id, entrypoint)
                        or (snapshot is None) != (saved is None)
                        or snapshot is not None and (saved.get('parentRunId'), saved.get('parentConfigurationHash')) != (
                            parent_run_id, snapshot['contentHash'])):
                    raise ManagementError('management_run_identity_conflict', '派生运行已绑定其他配置来源。', 403)
                return saved
            now = self.scope_service.auth.clock()
            await connection.execute(insert(runtime_snapshots).values(scope_id=scope_id, run_id=run_id,
                user_id=user_id, thread_id=thread_id, entrypoint=entrypoint, references=None,
                reference_hash=None, created_at=now))
            if snapshot is None:
                return None
            document = {key: value for key, value in snapshot.items() if key != 'contentHash'}
            document.update(runId=run_id, parentRunId=parent_run_id, parentConfigurationHash=snapshot['contentHash'])
            document['generatedDate'] = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            digest = configuration_hash(document)
            await connection.execute(insert(run_configuration_snapshots).values(scope_id=scope_id, run_id=run_id,
                document=document, content_hash=digest, created_at=now))
            return {**document, 'contentHash': digest}

    @staticmethod
    async def _run(connection, scope_id, run_id):
        row = (
            (
                await connection.execute(
                    select(runtime_snapshots).where(
                        runtime_snapshots.c.scope_id == scope_id,
                        runtime_snapshots.c.run_id == run_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ManagementError(
                "management_run_identity_missing", "运行尚未登记可信运行身份。", 403
            )
        return row

    async def assert_identity(
        self, run_id: str, scope: ManagementScope, *, user_id: str, thread_id: str
    ):
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            row = await self._run(connection, registered["id"], run_id)
            if row["user_id"] != user_id or row["thread_id"] != thread_id:
                raise ManagementError(
                    "management_run_identity_conflict", "运行身份与已登记记录不一致。", 403
                )

    async def freeze(
        self, run_id: str, scope: ManagementScope, source_ids: tuple[str, ...] | None = None
    ):
        raise ManagementError(
            'report_contract_retired',
            '旧业务Profile执行契约已停用，请按新统计口径创建报告。',
            409,
        )

    async def load_pinned(self, scope: ManagementScope, references: dict):
        raise ManagementError(
            'report_contract_retired',
            '旧业务Profile运行不支持恢复，请按新统计口径创建报告。',
            409,
        )
