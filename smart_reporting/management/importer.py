from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import insert, select, update

from .data_sources.secrets import CredentialVault
from .models import ManagementError, ManagementScope
from .repository import profile_drafts, profile_versions, source_drafts, source_credentials, sources, tenant_settings
from .scopes import ScopeService
from .data_sources.service import SourceService
from ..reporting.data_source.registry import load_report_source_registry
from ..reporting.profile.registry import load_configured_reporting_profiles, resolve_reporting_profile
from ..reporting.profile.models import ReportingProfileRegistry
from ..reporting.data_source.starrocks import parse_starrocks_source
from .data_sources.models import SourceDraftInput


class ConfigurationImporter:
    def __init__(self, scopes: ScopeService, vault: CredentialVault):
        self.scopes = scopes
        self.repository = scopes.repository
        self.auth = scopes.auth
        self.vault = vault

    @staticmethod
    def _config_path(directory: Path) -> Path:
        path = directory / "report-data-sources.json"
        if not path.is_file():
            raise ManagementError("management_import_invalid", "缺少 report-data-sources.json。", 422)
        return path

    async def import_configuration(self, raw_session: str, scope: ManagementScope,
                                   directory: str | Path, dry_run: bool,
                                   environ: Mapping[str, str]) -> dict:
        root = Path(directory).resolve(strict=True)
        config_path = self._config_path(root)
        try:
            registry = load_report_source_registry(root, root, environ=environ)
            profiles = load_configured_reporting_profiles(root)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as error:
            raise ManagementError("management_import_invalid", "配置导入预检失败。", 422) from error
        for source_id, parsed in registry.sources.items():
            raw_source = next(item for item in raw["sources"] if item.get("id") == source_id)
            profile_id = raw_source.get("reportingProfile")
            if profile_id is not None:
                try:
                    resolve_reporting_profile(profiles, profile_id)
                except Exception as error:
                    raise ManagementError("management_import_invalid", "数据源引用的 Profile 无效。", 422) from error
            if not hasattr(parsed, "dsn"):
                raise ManagementError("management_import_invalid", "数据源凭据无法解析。", 422)
        if dry_run:
            return {"dryRun": True, "createdSources": len(registry.sources),
                    "profiles": len(profiles.documents), "credentials": "redacted", "changed": True}
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(connection, raw_session, now)
            scope_row = await self.scopes.require_registered(connection, scope)
            scope_id = scope_row["id"]
            changed = False
            profile_versions_by_id: dict[str, int] = {}
            for profile_id, document in profiles.documents.items():
                existing = (await connection.execute(select(profile_versions.c.revision).where(
                    profile_versions.c.scope_id == scope_id, profile_versions.c.profile_id == profile_id,
                ).order_by(profile_versions.c.revision.desc()).limit(1))).scalar_one_or_none()
                if existing is None:
                    effective = resolve_reporting_profile(profiles, profile_id)
                    await connection.execute(insert(profile_versions).values(
                        scope_id=scope_id, profile_id=profile_id, revision=1,
                        document=document.model_dump(mode="json", by_alias=True, exclude_none=True),
                        effective_profile=effective.model_dump(mode="json", by_alias=True),
                        effective_profile_hash=effective.effective_profile_hash,
                        parent_versions=[], published_at=now,
                    ))
                    profile_versions_by_id[profile_id] = 1
                    changed = True
                else:
                    profile_versions_by_id[profile_id] = existing
            for source_id, parsed in registry.sources.items():
                raw_source = next(item for item in raw["sources"] if item.get("id") == source_id)
                source_input = SourceDraftInput(
                    name=parsed.name, type="starrocks", database=parsed.database,
                    dsn=parsed.dsn,
                    reportingProfileVersionId=(profile_versions_by_id.get(raw_source.get("reportingProfile"))
                                               and str(profile_versions_by_id[raw_source["reportingProfile"]])),
                )
                existing = (await connection.execute(select(source_drafts).where(
                    source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id,
                ))).mappings().one_or_none()
                if existing is not None:
                    continue
                credential_ref = str(uuid.uuid4())
                content = source_input.model_dump(mode="json", by_alias=True, exclude={"dsn"})
                digest = SourceService._config_hash(content, 1)
                await connection.execute(insert(sources).values(
                    scope_id=scope_id, source_id=source_id, enabled=1, draft_version=1,
                    published_revision=None, created_at=now, updated_at=now,
                ))
                await connection.execute(insert(source_drafts).values(
                    scope_id=scope_id, source_id=source_id, version=1, name=parsed.name,
                    source_type="starrocks", database=parsed.database, credential_ref=credential_ref,
                    credential_revision=1, profile_version_id=source_input.profile_version_id,
                    metadata_version_id=None, content_hash=digest,
                ))
                await self.vault.store(connection, scope_id, source_id, credential_ref, 1,
                                       parsed.dsn.get_secret_value())
                changed = True
            await connection.execute(update(tenant_settings).where(tenant_settings.c.id == scope_id)
                                     .values(default_source_ids=raw.get("defaultSourceIds", [])))
            return {"dryRun": False, "changed": changed, "createdSources": len(registry.sources),
                    "profiles": len(profiles.documents), "credentials": "redacted", "actor": account.username}
