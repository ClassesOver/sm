from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, select, update

from ..reporting.data_source.registry import load_report_source_registry
from ..reporting.data_source.starrocks import StarRocksSourceConfig
from ..reporting.metadata import ReportingMetadataClient
from ..reporting.profile.registry import (
    load_configured_reporting_profiles,
    resolve_reporting_profile,
)
from .catalog import CatalogService
from .data_sources.models import SourceDraftInput
from .data_sources.secrets import CredentialVault
from .data_sources.service import SourceService
from .models import ManagementError, ManagementScope
from .profiles import ProfileService
from .repository import (
    catalog_versions,
    profile_drafts,
    profile_versions,
    source_credentials,
    source_drafts,
    source_versions,
    sources,
    tenant_settings,
)
from .scopes import ScopeService


class ConfigurationImporter:
    """先完成外部预检，再在一个管理事务内发布整批配置。"""

    def __init__(
        self,
        scopes: ScopeService,
        vault: CredentialVault,
        *,
        metadata_client: ReportingMetadataClient | None = None,
    ):
        self.scopes = scopes
        self.repository = scopes.repository
        self.auth = scopes.auth
        self.vault = vault
        self.catalogs = CatalogService(scopes, vault=vault, metadata_client=metadata_client)

    @staticmethod
    async def _baseline(connection, scope_id):
        # 外部预检期间有人编辑/发布时，整批导入要求重试，避免覆盖管理页面中的新草稿。
        result = []
        for table, columns in (
            (
                sources,
                (
                    sources.c.source_id,
                    sources.c.draft_version,
                    sources.c.published_revision,
                    sources.c.enabled,
                ),
            ),
            (profile_drafts, (profile_drafts.c.profile_id, profile_drafts.c.version)),
            (profile_versions, (profile_versions.c.profile_id, profile_versions.c.revision)),
            (
                catalog_versions,
                (
                    catalog_versions.c.source_id,
                    catalog_versions.c.revision,
                    catalog_versions.c.status,
                ),
            ),
        ):
            result.append(
                (
                    await connection.execute(
                        select(*columns).where(table.c.scope_id == scope_id).order_by(*columns)
                    )
                ).all()
            )
        result.append(
            await connection.scalar(
                select(tenant_settings.c.version).where(tenant_settings.c.id == scope_id)
            )
        )
        return result

    async def import_configuration(
        self,
        raw_session: str,
        scope: ManagementScope,
        directory: str | Path,
        dry_run: bool,
        environ: Mapping[str, str],
    ) -> dict:
        actor = await self.scopes.actor(raw_session, scope)
        try:
            root = Path(directory).resolve(strict=True)
            if not (root / "report-data-sources.json").is_file():
                raise ValueError("missing configuration")
            registry = load_report_source_registry(root, root, environ=environ)
            profiles = load_configured_reporting_profiles(root)
            effective = {
                key: resolve_reporting_profile(profiles, key) for key in profiles.documents
            }
            configured: dict[str, StarRocksSourceConfig] = {}
            for source in registry.sources.values():
                if (
                    not isinstance(source, StarRocksSourceConfig)
                    or source.reporting_profile not in effective
                ):
                    raise ValueError("source must bind a configured Profile")
                self.vault.encrypt(source.dsn.get_secret_value())
                configured[source.id] = source
        except ManagementError:
            raise
        except Exception as error:
            raise ManagementError(
                "management_import_invalid", "配置、Profile 继承或凭据预检失败。", 422
            ) from error
        async with self.scopes.write_transaction(actor) as connection:
            scope_row = await self.scopes.require_registered(connection, scope)
            baseline = await self._baseline(connection, scope_row["id"])
        fetched = {}
        for source_id, source in configured.items():
            fetched[source_id] = await self.catalogs.fetch(source)

        now = self.auth.clock()
        async with self.scopes.write_transaction(actor) as connection:
            scope_row = await self.scopes.require_registered(connection, scope)
            scope_id = scope_row["id"]
            if await self._baseline(connection, scope_id) != baseline:
                raise ManagementError(
                    "management_version_conflict", "预检期间配置已变化，请重新预览导入。", 409
                )
            # 仅提示本次导入资源当前依赖的旧快照；已修复源的历史 NULL 不重复告警。
            legacy_source_ids = set(
                (
                    await connection.scalars(
                        select(source_drafts.c.source_id).where(
                            source_drafts.c.scope_id == scope_id,
                            source_drafts.c.source_id.in_(configured),
                            source_drafts.c.execution_parameters.is_(None),
                        )
                    )
                ).all()
            )
            legacy_source_ids.update(
                (
                    await connection.scalars(
                        select(source_versions.c.source_id)
                        .join(
                            sources,
                            (
                                (sources.c.scope_id == source_versions.c.scope_id)
                                & (sources.c.source_id == source_versions.c.source_id)
                                & (sources.c.published_revision == source_versions.c.revision)
                            ),
                        )
                        .where(
                            source_versions.c.scope_id == scope_id,
                            source_versions.c.source_id.in_(configured),
                            source_versions.c.execution_parameters.is_(None),
                        )
                    )
                ).all()
            )
            refs: dict[str, int] = {}
            changed_profiles = 0
            # resolver 的 layers 已提供父先子后的顺序，仍使用原有继承语义。
            ordered = dict.fromkeys(
                layer.profile_id for model in effective.values() for layer in model.layers
            )
            for profile_id in ordered:
                document = profiles.documents[profile_id]
                model = effective[profile_id]
                body = ProfileService._json(document)
                parents = [
                    {"profileId": layer.profile_id, "revision": refs[layer.profile_id]}
                    for layer in model.layers
                    if layer.profile_id != profile_id
                ]
                previous = (
                    (
                        await connection.execute(
                            select(profile_versions)
                            .where(
                                profile_versions.c.scope_id == scope_id,
                                profile_versions.c.profile_id == profile_id,
                            )
                            .order_by(profile_versions.c.revision.desc())
                            .limit(1)
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    previous
                    and previous["document"] == body
                    and previous["parent_versions"] == parents
                    and previous["effective_profile_hash"] == model.effective_profile_hash
                ):
                    refs[profile_id] = previous["revision"]
                    continue
                revision = previous["revision"] + 1 if previous else 1
                refs[profile_id] = revision
                changed_profiles += 1
                if not dry_run:
                    draft = (
                        (
                            await connection.execute(
                                select(profile_drafts).where(
                                    profile_drafts.c.scope_id == scope_id,
                                    profile_drafts.c.profile_id == profile_id,
                                )
                            )
                        )
                        .mappings()
                        .first()
                    )
                    values = dict(
                        scope_id=scope_id,
                        profile_id=profile_id,
                        version=draft["version"] + 1 if draft else 1,
                        document=body,
                        content_hash=ProfileService._hash(body),
                    )
                    if draft:
                        await connection.execute(
                            update(profile_drafts)
                            .where(
                                profile_drafts.c.scope_id == scope_id,
                                profile_drafts.c.profile_id == profile_id,
                            )
                            .values(**values)
                        )
                    else:
                        await connection.execute(insert(profile_drafts).values(**values))
                    await connection.execute(
                        insert(profile_versions).values(
                            scope_id=scope_id,
                            profile_id=profile_id,
                            revision=revision,
                            document=body,
                            effective_profile=model.model_dump(mode="json", by_alias=True),
                            effective_profile_hash=model.effective_profile_hash,
                            parent_versions=parents,
                            published_at=now,
                        )
                    )
            changed_sources = created_sources = 0
            for source_id, source in configured.items():
                metadata, catalog = fetched[source_id]
                assert source.reporting_profile is not None  # 已经由文件预检约束。
                changed, created = await self._import_source(
                    connection,
                    scope_id,
                    source,
                    refs[source.reporting_profile],
                    metadata,
                    catalog,
                    now,
                    dry_run,
                )
                changed_sources += changed
                created_sources += created
            defaults = list(registry.default_source_ids)
            defaults_changed = defaults != scope_row["default_source_ids"]
            changed = bool(changed_sources or changed_profiles or defaults_changed)
            if changed and not dry_run:
                await connection.execute(
                    update(tenant_settings)
                    .where(tenant_settings.c.id == scope_id)
                    .values(
                        default_source_ids=defaults,
                        version=scope_row["version"] + 1,
                    )
                )
                await self.scopes.audit(
                    connection,
                    actor,
                    "configuration_imported",
                    {
                        "sourceIds": sorted(registry.sources),
                        "changedSources": changed_sources,
                        "changedProfiles": changed_profiles,
                        "defaultSourceIds": defaults,
                    },
                )
            return {
                "dryRun": dry_run,
                "changed": changed,
                "createdSources": created_sources,
                "changedSources": changed_sources,
                "profiles": len(effective),
                "changedProfiles": changed_profiles,
                "credentials": "redacted",
                "legacySourceIds": sorted(legacy_source_ids),
            }

    async def _import_source(
        self, connection, scope_id, source, profile_revision, model, catalog, now, dry_run
    ):
        source_id = source.id
        current = (
            (
                await connection.execute(
                    select(source_drafts).where(
                        source_drafts.c.scope_id == scope_id,
                        source_drafts.c.source_id == source_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        current_source = (
            (
                await connection.execute(
                    select(sources).where(
                        sources.c.scope_id == scope_id,
                        sources.c.source_id == source_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        draft_version = current["version"] + 1 if current else 1
        snapshot = {
            "tables": self.catalogs._payload(catalog),
            "metadata": model.model_dump(mode="json", by_alias=True),
            "sourceDraftVersion": draft_version,
        }
        catalog_hash = self.catalogs._hash(snapshot)
        previous_catalog = (
            (
                await connection.execute(
                    select(catalog_versions)
                    .where(
                        catalog_versions.c.scope_id == scope_id,
                        catalog_versions.c.source_id == source_id,
                    )
                    .order_by(catalog_versions.c.revision.desc())
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        reuse_catalog = (
            previous_catalog
            and previous_catalog["status"] == "published"
            and previous_catalog["content_hash"] == catalog_hash
        )
        catalog_revision = (
            previous_catalog["revision"]
            if reuse_catalog
            else (previous_catalog["revision"] + 1 if previous_catalog else 1)
        )
        secret = source.dsn.get_secret_value()
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        old_credential = None
        if current:
            old_credential = (
                (
                    await connection.execute(
                        select(source_credentials).where(
                            source_credentials.c.scope_id == scope_id,
                            source_credentials.c.source_id == source_id,
                            source_credentials.c.credential_ref == current["credential_ref"],
                        )
                    )
                )
                .mappings()
                .first()
            )
        reuse_credential = old_credential and old_credential["secret_hash"] == secret_hash
        credential_ref = current["credential_ref"] if reuse_credential else str(uuid4())
        credential_revision = (
            current["credential_revision"]
            if reuse_credential
            else (current["credential_revision"] + 1 if current else 1)
        )
        payload = SourceDraftInput(
            name=source.name,
            database=source.database,
            dsn=source.dsn,
            reportingProfileVersionId=f"{source.reporting_profile}:{profile_revision}",
            metadataVersionId=f"{source_id}:{catalog_revision}",
        )
        content_hash = SourceService._config_hash(
            payload.model_dump(mode="json", by_alias=True, exclude={"dsn"}),
            credential_revision,
            source.limits.public_dict(),
        )
        published = (
            (
                await connection.execute(
                    select(source_versions)
                    .where(
                        source_versions.c.scope_id == scope_id,
                        source_versions.c.source_id == source_id,
                    )
                    .order_by(source_versions.c.revision.desc())
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        if (
            current
            and current["content_hash"] == content_hash
            and current["execution_parameters"] == source.limits.public_dict()
            and published
            and published["content_hash"] == content_hash
            and published["execution_parameters"] == source.limits.public_dict()
            and current_source["enabled"]
            and current_source["published_revision"] == published["revision"]
        ):
            return False, False
        if dry_run:
            return True, current is None
        if not reuse_catalog:
            await connection.execute(
                insert(catalog_versions).values(
                    scope_id=scope_id,
                    source_id=source_id,
                    revision=catalog_revision,
                    status="published",
                    catalog=snapshot,
                    content_hash=catalog_hash,
                    synced_at=now,
                )
            )
        if not reuse_credential:
            await self.vault.store(
                connection, scope_id, source_id, credential_ref, credential_revision, secret
            )
        values = dict(
            scope_id=scope_id,
            source_id=source_id,
            version=draft_version,
            name=payload.name.strip(),
            source_type="starrocks",
            database=source.database,
            credential_ref=credential_ref,
            credential_revision=credential_revision,
            profile_version_id=payload.profile_version_id,
            metadata_version_id=payload.metadata_version_id,
            content_hash=content_hash,
            execution_parameters=source.limits.public_dict(),
        )
        revision = published["revision"] + 1 if published else 1
        if current:
            await connection.execute(
                update(source_drafts)
                .where(
                    source_drafts.c.scope_id == scope_id,
                    source_drafts.c.source_id == source_id,
                )
                .values(**values, requires_table_discovery=0)
            )
            await connection.execute(
                update(sources)
                .where(
                    sources.c.scope_id == scope_id,
                    sources.c.source_id == source_id,
                )
                .values(
                    enabled=1,
                    draft_version=draft_version,
                    published_revision=revision,
                    updated_at=now,
                )
            )
        else:
            await connection.execute(
                insert(sources).values(
                    scope_id=scope_id,
                    source_id=source_id,
                    enabled=1,
                    draft_version=draft_version,
                    published_revision=revision,
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(insert(source_drafts).values(**values, requires_table_discovery=0))
        await connection.execute(
            insert(source_versions).values(
                **{key: value for key, value in values.items() if key != "version"},
                revision=revision,
                published_at=now,
            )
        )
        return True, current is None
