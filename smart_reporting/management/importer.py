from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, select, update

from ..reporting.data_source.registry import load_report_source_registry
from ..reporting.data_source.starrocks import StarRocksSourceConfig
from ..reporting.metadata import ReportingMetadataClient
from .catalog import CatalogService
from .data_sources.models import SourceDraftInput
from .data_sources.secrets import CredentialVault
from .data_sources.service import SourceService
from .models import ManagementError, ManagementScope
from .repository import (
    catalog_versions,
    source_credentials,
    source_drafts,
    source_versions,
    sources,
    tenant_settings,
)
from .scopes import ScopeService


class ConfigurationImporter:
    """新连接文件预检后原子发布；业务规则独立登记，不读取旧Profile。"""

    def __init__(self, scopes: ScopeService, vault: CredentialVault, *,
                 metadata_client: ReportingMetadataClient | None = None):
        self.scopes = scopes
        self.repository = scopes.repository
        self.auth = scopes.auth
        self.vault = vault
        self.catalogs = CatalogService(scopes, vault=vault, metadata_client=metadata_client)

    @staticmethod
    async def _baseline(connection, scope_id):
        result = []
        for table, columns in (
            (sources, (sources.c.source_id, sources.c.draft_version,
                       sources.c.published_revision, sources.c.enabled)),
            (catalog_versions, (catalog_versions.c.source_id, catalog_versions.c.revision,
                                catalog_versions.c.status)),
        ):
            result.append((await connection.execute(
                select(*columns).where(table.c.scope_id == scope_id).order_by(*columns))).all())
        result.append(await connection.scalar(
            select(tenant_settings.c.version).where(tenant_settings.c.id == scope_id)))
        return result

    @staticmethod
    async def _require_new_sources(connection, scope_id, source_ids):
        archived = await connection.scalar(select(source_drafts.c.source_id).where(
            source_drafts.c.scope_id == scope_id, source_drafts.c.source_id.in_(source_ids),
            source_drafts.c.profile_version_id.is_not(None)).limit(1))
        if archived is not None:
            raise ManagementError('management_source_contract_retired',
                '旧业务Profile连接不支持导入转换，请按新契约重新登记连接与表范围。', 409)

    async def import_configuration(self, raw_session: str, scope: ManagementScope,
                                   directory: str | Path, dry_run: bool,
                                   environ: Mapping[str, str]) -> dict:
        actor = await self.scopes.actor(raw_session, scope)
        try:
            root = Path(directory).resolve(strict=True)
            if not (root / 'report-data-sources.json').is_file():
                raise ValueError('missing configuration')
            registry = load_report_source_registry(root, root, environ=environ)
            configured = {}
            for source in registry.sources.values():
                if not isinstance(source, StarRocksSourceConfig):
                    raise ValueError('unsupported source')
                self.vault.encrypt(source.dsn.get_secret_value())
                configured[source.id] = source
        except ManagementError:
            raise
        except Exception as error:
            raise ManagementError('management_import_invalid', '连接配置或凭据预检失败。', 422) from error
        async with self.scopes.write_transaction(actor) as connection:
            scope_row = await self.scopes.require_registered(connection, scope)
            await self._require_new_sources(connection, scope_row['id'], configured)
            baseline = await self._baseline(connection, scope_row['id'])
        fetched = {}
        for source_id, source in configured.items():
            fetched[source_id] = await self.catalogs.fetch(source)
        now = self.auth.clock()
        async with self.scopes.write_transaction(actor) as connection:
            scope_row = await self.scopes.require_registered(connection, scope)
            scope_id = scope_row['id']
            if await self._baseline(connection, scope_id) != baseline:
                raise ManagementError('management_version_conflict', '预检期间配置已变化，请重新预览导入。', 409)
            await self._require_new_sources(connection, scope_id, configured)
            changed_sources = created_sources = 0
            for source_id, source in configured.items():
                metadata, catalog = fetched[source_id]
                changed, created = await self._import_source(
                    connection, scope_id, source, metadata, catalog, now, dry_run)
                changed_sources += changed
                created_sources += created
            defaults = list(registry.default_source_ids)
            changed = bool(changed_sources or defaults != scope_row['default_source_ids'])
            if changed and not dry_run:
                await connection.execute(update(tenant_settings).where(tenant_settings.c.id == scope_id)
                    .values(default_source_ids=defaults, version=scope_row['version'] + 1))
                await self.scopes.audit(connection, actor, 'configuration_imported', {
                    'sourceIds': sorted(configured), 'changedSources': changed_sources,
                    'defaultSourceIds': defaults})
            return {'dryRun': dry_run, 'changed': changed, 'createdSources': created_sources,
                'changedSources': changed_sources, 'credentials': 'redacted'}

    async def _import_source(self, connection, scope_id, source, model, catalog, now, dry_run):
        source_id = source.id
        current = (await connection.execute(select(source_drafts).where(
            source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id))).mappings().first()
        current_source = (await connection.execute(select(sources).where(
            sources.c.scope_id == scope_id, sources.c.source_id == source_id))).mappings().first()
        draft_version = current['version'] + 1 if current else 1
        secret = source.dsn.get_secret_value()
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        old_credential = None
        if current:
            old_credential = (await connection.execute(select(source_credentials).where(
                source_credentials.c.scope_id == scope_id, source_credentials.c.source_id == source_id,
                source_credentials.c.credential_ref == current['credential_ref'],
                source_credentials.c.revision == current['credential_revision']))).mappings().first()
        reuse_credential = old_credential is not None and old_credential['secret_hash'] == secret_hash
        credential_ref = current['credential_ref'] if reuse_credential else str(uuid4())
        credential_revision = (current['credential_revision'] if reuse_credential
            else (current['credential_revision'] + 1 if current else 1))
        snapshot = {'tables': self.catalogs._payload(catalog),
            'metadata': model.model_dump(mode='json', by_alias=True),
            'sourceDraftVersion': draft_version, 'connectionIdentity': {
                'database': source.database, 'credentialRef': credential_ref,
                'credentialRevision': credential_revision}}
        self.catalogs.validate_snapshot(snapshot, source_id, source.database)
        catalog_hash = self.catalogs._hash(snapshot)
        previous_catalog = (await connection.execute(select(catalog_versions).where(
            catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id)
            .order_by(catalog_versions.c.revision.desc()).limit(1))).mappings().first()
        reuse_catalog = (previous_catalog is not None and previous_catalog['status'] == 'published'
            and previous_catalog['content_hash'] == catalog_hash)
        catalog_revision = (previous_catalog['revision'] if reuse_catalog
            else (previous_catalog['revision'] + 1 if previous_catalog else 1))
        payload = SourceDraftInput(name=source.name, database=source.database, dsn=source.dsn,
            metadataVersionId=f'{source_id}:{catalog_revision}')
        content_hash = SourceService._config_hash(
            payload.model_dump(mode='json', by_alias=True, exclude={'dsn'}),
            credential_revision, source.limits.public_dict())
        published = (await connection.execute(select(source_versions).where(
            source_versions.c.scope_id == scope_id, source_versions.c.source_id == source_id)
            .order_by(source_versions.c.revision.desc()).limit(1))).mappings().first()
        if (current and current['content_hash'] == content_hash
                and current['execution_parameters'] == source.limits.public_dict()
                and not current['requires_table_discovery']
                and published and published['profile_version_id'] is None
                and published['content_hash'] == content_hash
                and published['execution_parameters'] == source.limits.public_dict()
                and current_source['enabled']
                and current_source['published_revision'] == published['revision']):
            return False, False
        if dry_run:
            return True, current is None
        if not reuse_catalog:
            await connection.execute(insert(catalog_versions).values(scope_id=scope_id,
                source_id=source_id, revision=catalog_revision, status='published',
                catalog=snapshot, content_hash=catalog_hash, synced_at=now))
        if not reuse_credential:
            await self.vault.store(connection, scope_id, source_id, credential_ref, credential_revision, secret)
        values = dict(scope_id=scope_id, source_id=source_id, version=draft_version,
            name=payload.name.strip(), source_type='starrocks', database=source.database,
            credential_ref=credential_ref, credential_revision=credential_revision,
            profile_version_id=None, metadata_version_id=payload.metadata_version_id,
            content_hash=content_hash, execution_parameters=source.limits.public_dict())
        revision = published['revision'] + 1 if published else 1
        if current:
            await connection.execute(update(source_drafts).where(source_drafts.c.scope_id == scope_id,
                source_drafts.c.source_id == source_id).values(**values, requires_table_discovery=0))
            await connection.execute(update(sources).where(sources.c.scope_id == scope_id,
                sources.c.source_id == source_id).values(enabled=1, draft_version=draft_version,
                    published_revision=revision, updated_at=now))
        else:
            await connection.execute(insert(sources).values(scope_id=scope_id, source_id=source_id,
                enabled=1, draft_version=draft_version, published_revision=revision, created_at=now, updated_at=now))
            await connection.execute(insert(source_drafts).values(**values, requires_table_discovery=0))
        await connection.execute(insert(source_versions).values(
            **{key: value for key, value in values.items() if key != 'version'}, revision=revision, published_at=now))
        return True, current is None
