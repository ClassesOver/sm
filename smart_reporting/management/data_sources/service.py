from __future__ import annotations

import hashlib
import json
import re
import uuid

from sqlalchemy import insert, select, update

from ..models import ManagementError, ManagementScope
from ..scopes import ScopeService
from ..repository import source_credentials, source_drafts, source_versions, sources
from .models import SourceDraftInput
from .repository import SourceRepository
from .secrets import CredentialVault
from ...reporting.data_source.starrocks import parse_starrocks_source


_SOURCE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


class SourceService:
    def __init__(self, scope_service: ScopeService, vault: CredentialVault):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.auth = scope_service.auth
        self.sources = SourceRepository()
        self.vault = vault

    @staticmethod
    def _validate_payload(source_id: str, payload: SourceDraftInput) -> None:
        try:
            parsed = parse_starrocks_source({
                'id': source_id, 'type': 'starrocks', 'name': payload.name,
                'dsnEnv': 'MANAGEMENT_DSN', 'database': payload.database,
            }, {'MANAGEMENT_DSN': payload.dsn.get_secret_value()})
        except Exception as error:
            if isinstance(error, ManagementError):
                raise
            raise ManagementError('management_source_config_invalid', 'StarRocks 连接配置无效。', 422) from error
        if parsed.database != payload.database.lower():
            raise ManagementError('management_source_config_invalid', 'StarRocks 连接数据库与声明不一致。', 422)

    @staticmethod
    def _config_hash(payload: dict, credential_revision: int) -> str:
        public = {key: value for key, value in payload.items() if key != 'dsn'}
        public['credentialRevision'] = credential_revision
        encoded = json.dumps(public, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def create_draft(self, raw_session: str, scope: ManagementScope,
                           source_id: str, payload: SourceDraftInput) -> dict:
        if not _SOURCE_ID.fullmatch(source_id):
            raise ManagementError('management_source_id_invalid', '数据源标识格式无效。', 422)
        self._validate_payload(source_id, payload)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(connection, raw_session, now)
            await ScopeService.require_registered(connection, scope)
            scope_id = await self.sources.scope_id(connection, scope)
            exists = await connection.scalar(select(sources.c.source_id).where(
                sources.c.scope_id == scope_id, sources.c.source_id == source_id))
            if exists:
                raise ManagementError('management_source_exists', '数据源标识已存在。', 409)
            credential_ref = str(uuid.uuid4())
            content = payload.model_dump(mode='json', by_alias=True, exclude={'dsn'})
            digest = self._config_hash(content, 1)
            values = dict(scope_id=scope_id, source_id=source_id, version=1,
                          name=payload.name.strip(), source_type=payload.source_type,
                          database=payload.database.lower(), credential_ref=credential_ref,
                          credential_revision=1,
                          profile_version_id=payload.profile_version_id,
                          metadata_version_id=payload.metadata_version_id,
                          content_hash=digest)
            await connection.execute(insert(sources).values(scope_id=scope_id, source_id=source_id,
                enabled=1, draft_version=1, published_revision=None, created_at=now, updated_at=now))
            await connection.execute(insert(source_drafts).values(**values))
            await self.vault.store(connection, scope_id, source_id, credential_ref, 1,
                                   payload.dsn.get_secret_value())
            from ..models import ManagementActor
            actor = ManagementActor(account.account_id, account.username, scope, account.auth_version, raw_session)
            await self.scope_service.audit(connection, actor, 'source_draft_created', {'sourceId': source_id})
            return self.public_draft({'source_id': source_id, **values})

    async def save_draft(self, raw_session: str, scope: ManagementScope,
                         source_id: str, payload: SourceDraftInput, expected_version: int) -> dict:
        if not _SOURCE_ID.fullmatch(source_id):
            raise ManagementError('management_source_id_invalid', '数据源标识格式无效。', 422)
        self._validate_payload(source_id, payload)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(connection, raw_session, now)
            await ScopeService.require_registered(connection, scope)
            scope_id = await self.sources.scope_id(connection, scope)
            current = await self.sources.get_draft(connection, scope_id, source_id)
            if current['version'] != expected_version:
                raise ManagementError('management_version_conflict', '草稿已被其他操作更新，请重新载入。', 409)
            credential_ref = str(uuid.uuid4())
            credential_revision = current['credential_revision'] + 1
            content = payload.model_dump(mode='json', by_alias=True, exclude={'dsn'})
            digest = self._config_hash(content, credential_revision)
            values = dict(version=expected_version + 1, name=payload.name.strip(),
                          source_type=payload.source_type, database=payload.database.lower(),
                          credential_ref=credential_ref, credential_revision=credential_revision,
                          profile_version_id=payload.profile_version_id,
                          metadata_version_id=payload.metadata_version_id,
                          content_hash=digest)
            await connection.execute(insert(source_credentials).values(
                scope_id=scope_id, source_id=source_id, credential_ref=credential_ref,
                revision=credential_revision, key_id=self.vault.active_key_id,
                ciphertext=json.dumps(self.vault.encrypt(payload.dsn.get_secret_value()).decode()),
                secret_hash=hashlib.sha256(payload.dsn.get_secret_value().encode()).hexdigest()))
            statement = update(source_drafts).where(
                source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id,
                source_drafts.c.version == expected_version).values(**values).returning(source_drafts.c.version)
            result = await connection.execute(statement)
            if result.scalar_one_or_none() is None:
                raise ManagementError('management_version_conflict', '草稿已被其他操作更新。', 409)
            await connection.execute(update(sources).where(sources.c.scope_id == scope_id,
                sources.c.source_id == source_id).values(draft_version=expected_version + 1, updated_at=now))
            from ..models import ManagementActor
            actor = ManagementActor(account.account_id, account.username, scope, account.auth_version, raw_session)
            await self.scope_service.audit(connection, actor, 'source_draft_saved', {'sourceId': source_id, 'version': expected_version + 1})
            return self.public_draft({'source_id': source_id, **values})

    async def publish(self, raw_session: str, scope: ManagementScope,
                      source_id: str, expected_version: int) -> dict:
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(connection, raw_session, now)
            await ScopeService.require_registered(connection, scope)
            scope_id = await self.sources.scope_id(connection, scope)
            draft = await self.sources.get_draft(connection, scope_id, source_id)
            if draft['version'] != expected_version:
                raise ManagementError('management_version_conflict', '草稿已被其他操作更新。', 409)
            published = (await connection.execute(select(source_versions.c.revision).where(
                source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id
            ).order_by(source_versions.c.revision.desc()).limit(1))).scalar_one_or_none()
            revision = (published or 0) + 1
            await connection.execute(insert(source_versions).values(
                scope_id=scope_id, source_id=source_id, revision=revision,
                content_hash=draft['content_hash'], published_at=now,
                name=draft['name'], source_type=draft['source_type'], database=draft['database'],
                credential_ref=draft['credential_ref'], credential_revision=draft['credential_revision'],
                profile_version_id=draft['profile_version_id'], metadata_version_id=draft['metadata_version_id']))
            await connection.execute(update(sources).where(sources.c.scope_id == scope_id,
                sources.c.source_id == source_id).values(published_revision=revision, enabled=1, updated_at=now))
            from ..models import ManagementActor
            actor = ManagementActor(account.account_id, account.username, scope, account.auth_version, raw_session)
            await self.scope_service.audit(connection, actor, 'source_version_published', {'sourceId': source_id, 'revision': revision})
            return {'sourceId': source_id, 'revision': revision, 'contentHash': draft['content_hash'],
                    'publishedAt': now.isoformat(), 'name': draft['name'], 'type': draft['source_type'],
                    'database': draft['database'], 'reportingProfileVersionId': draft['profile_version_id'],
                    'metadataVersionId': draft['metadata_version_id']}

    async def resolve_credentials(self, scope: ManagementScope, source_id: str, revision: int) -> str:
        async with self.repository.transaction() as connection:
            scope_id = await self.sources.scope_id(connection, scope)
            await self.sources.get_published(connection, scope_id, source_id, revision)
            row = (await connection.execute(select(source_versions.c.credential_ref).where(
                source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id,
                source_versions.c.revision == revision))).scalar_one()
            return await self.vault.resolve(connection, scope_id, source_id, row)

    @staticmethod
    def public_draft(row: dict) -> dict:
        return {key: row[key] for key in ('source_id', 'version', 'name', 'source_type', 'database',
                'profile_version_id', 'metadata_version_id', 'content_hash')}
