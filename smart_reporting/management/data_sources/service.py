from __future__ import annotations

import hashlib
import json
import re
import uuid

from sqlalchemy import String, cast, func, insert, or_, select, update

from ...reporting.data_source.starrocks import parse_starrocks_source
from ..models import ManagementError, ManagementScope
from ..repository import (
    catalog_versions,
    source_credentials,
    source_drafts,
    source_versions,
    sources,
)
from ..scopes import ScopeService
from .models import SourceDraftInput
from .repository import SourceRepository
from .secrets import CredentialVault

_SOURCE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


class SourceService:
    def __init__(self, scope_service: ScopeService, vault: CredentialVault):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.auth = scope_service.auth
        self.sources = SourceRepository()
        self.vault = vault

    @staticmethod
    def _validate_payload(source_id: str, payload: SourceDraftInput):
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
        return parsed

    @staticmethod
    def _config_hash(payload: dict, credential_revision: int, execution_parameters: dict) -> str:
        public = {key: value for key, value in payload.items() if key != 'dsn'}
        public['credentialRevision'] = credential_revision
        public['executionParameters'] = execution_parameters
        encoded = json.dumps(public, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def list(self, raw_session: str, scope: ManagementScope,
                   limit: int = 50, after: str | None = None, q: str = "", publication_state: str = "all") -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            scope_id = await self.sources.scope_id(connection, scope)
            query = select(
                source_drafts.c.source_id, source_drafts.c.version, source_drafts.c.name,
                source_drafts.c.source_type, source_drafts.c.database,
                source_drafts.c.profile_version_id, source_drafts.c.metadata_version_id,
                source_drafts.c.content_hash, sources.c.enabled, sources.c.published_revision,
            ).join(sources, (sources.c.scope_id == source_drafts.c.scope_id)
                   & (sources.c.source_id == source_drafts.c.source_id)).where(
                sources.c.scope_id == scope_id
            ).order_by(source_drafts.c.source_id)
            query = query.outerjoin(source_versions,
                (source_versions.c.scope_id == sources.c.scope_id)
                & (source_versions.c.source_id == sources.c.source_id)
                & (source_versions.c.revision == sources.c.published_revision))
            query = query.outerjoin(catalog_versions,
                (catalog_versions.c.scope_id == sources.c.scope_id)
                & (catalog_versions.c.source_id == sources.c.source_id)
                & (source_versions.c.metadata_version_id == catalog_versions.c.source_id + ':' + cast(catalog_versions.c.revision, String)))
            query = query.add_columns(source_versions.c.content_hash.label("published_hash"),
                func.coalesce(func.json_array_length(catalog_versions.c.catalog['tables']), 0).label('published_table_count'))
            if q:
                escaped = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                query = query.where(or_(source_drafts.c.name.ilike(f"%{escaped}%", escape="!"),
                                           source_drafts.c.source_id.ilike(f"%{escaped}%", escape="!")))
            if publication_state == "unpublished":
                query = query.where(sources.c.published_revision.is_(None))
            elif publication_state == "published":
                query = query.where(sources.c.published_revision.is_not(None))
            elif publication_state == "changed":
                query = query.where(source_versions.c.content_hash != source_drafts.c.content_hash)
            if after is not None:
                query = query.where(source_drafts.c.source_id > after)
            rows = (await connection.execute(query.limit(limit + 1))).mappings().all()
            return {
                'items': [{**self.public_draft(row), 'enabled': bool(row['enabled']),
                           'publishedRevision': row['published_revision'],
                           'publishedTableCount': row['published_table_count'],
                           'hasUnpublishedChanges': bool(row['published_hash'] and row['published_hash'] != row['content_hash'])}
                          for row in rows[:limit]],
                'nextCursor': rows[limit - 1]['source_id'] if len(rows) > limit else None,
            }

    async def create_draft(self, raw_session: str, scope: ManagementScope,
                           source_id: str, payload: SourceDraftInput) -> dict:
        if not _SOURCE_ID.fullmatch(source_id):
            raise ManagementError('management_source_id_invalid', '数据源标识格式无效。', 422)
        if payload.dsn is None:
            raise ManagementError('management_source_config_invalid', '创建数据源必须提供连接地址。', 422)
        parsed = self._validate_payload(source_id, payload)
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
            execution_parameters = parsed.limits.public_dict()
            digest = self._config_hash(content, 1, execution_parameters)
            values = dict(scope_id=scope_id, source_id=source_id, version=1,
                          name=payload.name.strip(), source_type=payload.source_type,
                          database=payload.database.lower(), credential_ref=credential_ref,
                          credential_revision=1,
                          profile_version_id=payload.profile_version_id,
                          metadata_version_id=payload.metadata_version_id,
                          content_hash=digest, execution_parameters=execution_parameters)
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
        if payload.dsn is not None:
            self._validate_payload(source_id, payload)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(connection, raw_session, now)
            await ScopeService.require_registered(connection, scope)
            scope_id = await self.sources.scope_id(connection, scope)
            current = await self.sources.get_draft(connection, scope_id, source_id)
            if current['version'] != expected_version:
                raise ManagementError('management_version_conflict', '草稿已被其他操作更新，请重新载入。', 409)
            execution_parameters = current['execution_parameters']
            if execution_parameters is None:
                raise ManagementError('management_source_reimport_required', '旧配置缺少执行参数快照，请从原配置文件重新导入并对账。', 422)
            if payload.dsn is None and payload.database != current['database']:
                raise ManagementError('management_source_config_invalid', '更改数据库时必须提供新的连接地址。', 422)
            credential_ref = str(uuid.uuid4()) if payload.dsn is not None else current['credential_ref']
            credential_revision = current['credential_revision'] + (1 if payload.dsn is not None else 0)
            content = payload.model_dump(mode='json', by_alias=True, exclude={'dsn'})
            if payload.dsn is not None:
                content['metadataVersionId'] = None
            digest = self._config_hash(content, credential_revision, execution_parameters)
            values = dict(version=expected_version + 1, name=payload.name.strip(),
                          source_type=payload.source_type, database=payload.database.lower(),
                          credential_ref=credential_ref, credential_revision=credential_revision,
                          profile_version_id=payload.profile_version_id,
                          metadata_version_id=content['metadataVersionId'],
                          requires_table_discovery=1 if payload.dsn is not None else current['requires_table_discovery'],
                          content_hash=digest)
            if payload.dsn is not None:
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
            if draft['execution_parameters'] is None:
                raise ManagementError('management_source_reimport_required', '旧配置缺少执行参数快照，请从原配置文件重新导入并对账。', 422)
            from .releases import require_release_dependencies
            await require_release_dependencies(connection, scope_id, source_id, draft)
            current = (await connection.execute(select(source_versions).join(sources,
                (sources.c.scope_id == source_versions.c.scope_id)
                & (sources.c.source_id == source_versions.c.source_id)
                & (sources.c.published_revision == source_versions.c.revision),
            ).where(source_versions.c.scope_id == scope_id,
                    source_versions.c.source_id == source_id))).mappings().one_or_none()
            if current and current['content_hash'] == draft['content_hash']:
                return self.sources.version_model(current).public_dict()
            published = (await connection.execute(select(source_versions.c.revision).where(
                source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id
            ).order_by(source_versions.c.revision.desc()).limit(1))).scalar_one_or_none()
            revision = (published or 0) + 1
            await connection.execute(insert(source_versions).values(
                scope_id=scope_id, source_id=source_id, revision=revision,
                content_hash=draft['content_hash'], published_at=now,
                name=draft['name'], source_type=draft['source_type'], database=draft['database'],
                credential_ref=draft['credential_ref'], credential_revision=draft['credential_revision'],
                profile_version_id=draft['profile_version_id'], metadata_version_id=draft['metadata_version_id'],
                execution_parameters=draft['execution_parameters']))
            await connection.execute(update(sources).where(sources.c.scope_id == scope_id,
                sources.c.source_id == source_id).values(published_revision=revision, enabled=1, updated_at=now))
            from ..models import ManagementActor
            actor = ManagementActor(account.account_id, account.username, scope, account.auth_version, raw_session)
            await self.scope_service.audit(connection, actor, 'source_version_published', {'sourceId': source_id, 'revision': revision})
            return {'sourceId': source_id, 'revision': revision, 'contentHash': draft['content_hash'],
                    'publishedAt': now.isoformat(), 'name': draft['name'], 'type': draft['source_type'],
                    'database': draft['database'], 'reportingProfileVersionId': draft['profile_version_id'],
                    'metadataVersionId': draft['metadata_version_id']}

    async def _read_detail(self, connection, scope_id: str, source_id: str):
        draft = await self.sources.get_draft(connection, scope_id, source_id)
        source = (await connection.execute(select(sources).where(
            sources.c.scope_id == scope_id, sources.c.source_id == source_id))).mappings().one()
        published = (await connection.execute(select(source_versions).where(
            source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id,
            source_versions.c.revision == source['published_revision']))).mappings().one_or_none()
        return draft, source, published

    async def detail(self, raw_session: str, scope: ManagementScope, source_id: str) -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            scope_id = await self.sources.scope_id(connection, scope)
            draft, source, published = await self._read_detail(connection, scope_id, source_id)
            return {'draft': self.public_draft(draft),
                    'published': self.sources.version_model(published).public_dict() if published else None,
                    'enabled': bool(source['enabled']),
                    'hasUnpublishedChanges': bool(published and published['content_hash'] != draft['content_hash'])}

    async def release_check(self, raw_session: str, scope: ManagementScope,
                            source_id: str, expected_version: int) -> dict:
        from .releases import require_release_dependencies
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            scope_id = await self.sources.scope_id(connection, scope)
            draft, source, published = await self._read_detail(connection, scope_id, source_id)
            if draft['version'] != expected_version:
                raise ManagementError('management_version_conflict', '草稿已被其他操作更新。', 409)
            issues = []
            warnings = []
            if draft['execution_parameters'] is None:
                issues.append({'code': 'management_source_reimport_required',
                               'message': '旧配置缺少执行参数快照，请从原配置文件重新导入并对账。'})
            else:
                try:
                    _, catalog, _ = await require_release_dependencies(connection, scope_id, source_id, draft)
                    warnings = catalog["catalog"].get("warnings", [])
                except ManagementError as error:
                    if error.status != 422:
                        raise
                    issues.append({'code': error.code, 'message': error.message})
            fields = []
            for public, key in (('name', 'name'), ('type', 'source_type'), ('database', 'database'),
                                ('reportingProfileVersionId', 'profile_version_id'),
                                ('metadataVersionId', 'metadata_version_id')):
                before = published[key] if published else None
                if before != draft[key]:
                    fields.append({'field': public, 'before': before, 'after': draft[key]})
            connection_changed = not published or published['credential_revision'] != draft['credential_revision']
            changed = not published or published['content_hash'] != draft['content_hash']
            from ..table_access import TableAccessService
            before = await TableAccessService.bound_tables(connection, scope_id, source_id, published['metadata_version_id'] if published else None)
            after = await TableAccessService.bound_tables(connection, scope_id, source_id, draft['metadata_version_id'])
            before_names = {t['database'] + '.' + t['name'] for t in before}
            after_names = {t['database'] + '.' + t['name'] for t in after}
            return {'tableAccessChanges': {'added': sorted(after_names - before_names), 'removed': sorted(before_names - after_names), 'beforeCount': len(before), 'afterCount': len(after)}, 'expectedVersion': expected_version, 'currentPublishedRevision': source['published_revision'],
                    'changedFields': fields, 'connectionChanged': connection_changed,
                    'hasUnpublishedChanges': changed, 'canPublish': not issues and changed, 'issues': issues, 'warnings': warnings}

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
