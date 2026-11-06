from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr
from sqlalchemy import insert, select, update

from ..reporting.contract import ModelTermsResponse
from ..reporting.data_source.starrocks import StarRocksSourceConfig, parse_starrocks_source
from ..reporting.profile.models import EffectiveReportingProfile
from ..reporting.profile.registry import bind_reporting_profile_sources
from .catalog import CatalogService
from .data_sources.models import SourceDraftInput
from .data_sources.releases import require_release_dependencies
from .data_sources.secrets import CredentialVault
from .data_sources.service import SourceService
from .models import ManagementError, ManagementScope
from .repository import runtime_snapshots, source_versions, sources
from .scopes import ScopeService


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ManagedRunSnapshot:
    scope: ManagementScope
    sources: dict[str, StarRocksSourceConfig] = field(repr=False)
    source_versions: dict[str, int]
    source_hashes: dict[str, str]
    profile: EffectiveReportingProfile
    metadata: dict[str, ModelTermsResponse]
    references: dict[str, Any]

    def public_state(self) -> dict[str, Any]:
        return {
            "database": self.scope.database,
            "companyId": self.scope.company_id,
            "references": deepcopy(self.references),
            "effectiveProfileHash": self.profile.effective_profile_hash,
        }


class ManagedConfigurationProvider:
    def __init__(self, scope_service: ScopeService, vault: CredentialVault):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.vault = vault

    async def register_run(
        self, run_id: str, scope: ManagementScope, *, user_id: str, thread_id: str, entrypoint: str
    ) -> None:
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
                return
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
                "management_run_identity_missing", "运行尚未登记可信组织身份。", 403
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
    ) -> ManagedRunSnapshot:
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            row = await self._run(connection, registered["id"], run_id)
            if row["references"] is not None:
                if source_ids is not None and set(source_ids) != {
                    item["sourceId"] for item in row["references"]["sources"]
                }:
                    raise ManagementError(
                        "management_source_selection_conflict",
                        "运行已固定其他数据源，不能改写。",
                        409,
                    )
                return await self._restore(
                    connection, scope, registered["id"], row, row["references"]
                )
            requested = tuple(
                source_ids if source_ids is not None else registered["default_source_ids"]
            )
            if not requested or len(set(requested)) != len(requested):
                raise ManagementError(
                    "management_default_source_missing", "组织未配置有效的选用数据源。", 422
                )
            pinned = []
            for source_id in requested:
                revision = await connection.scalar(
                    select(sources.c.published_revision).where(
                        sources.c.scope_id == registered["id"],
                        sources.c.source_id == source_id,
                    )
                )
                if revision is None:
                    raise ManagementError(
                        "management_source_version_not_found", "数据源没有已发布版本。", 422
                    )
                pinned.append((source_id, revision))
            snapshot = await self._build(connection, scope, registered["id"], run_id, pinned)
            await connection.execute(
                update(runtime_snapshots)
                .where(
                    runtime_snapshots.c.scope_id == registered["id"],
                    runtime_snapshots.c.run_id == run_id,
                )
                .values(references=snapshot.references, reference_hash=_hash(snapshot.references))
            )
            return snapshot

    async def load_pinned(self, scope: ManagementScope, references: dict) -> ManagedRunSnapshot:
        async with self.repository.transaction() as connection:
            registered = await ScopeService.require_registered(connection, scope)
            if not isinstance(references, dict) or not isinstance(references.get("runId"), str):
                raise ManagementError(
                    "management_runtime_reference_mismatch", "运行配置引用无效。", 422
                )
            row = await self._run(connection, registered["id"], references["runId"])
            return await self._restore(connection, scope, registered["id"], row, references)

    async def _restore(self, connection, scope, scope_id, row, references):
        if row["references"] != references or row["reference_hash"] != _hash(references):
            raise ManagementError(
                "management_runtime_reference_mismatch", "运行配置引用与服务端记录不一致。", 422
            )
        pinned = [(item["sourceId"], item["revision"]) for item in references["sources"]]
        snapshot = await self._build(connection, scope, scope_id, row["run_id"], pinned)
        if snapshot.references != references:
            raise ManagementError(
                "management_runtime_reference_mismatch", "冻结版本内容或哈希不一致。", 503
            )
        return snapshot

    async def _build(self, connection, scope, scope_id, run_id, pinned):
        configs, revisions, hashes, metadata, references = {}, {}, {}, {}, []
        profile = None
        profile_binding = None
        for source_id, revision in sorted(pinned):
            enabled = await connection.scalar(
                select(sources.c.enabled).where(
                    sources.c.scope_id == scope_id,
                    sources.c.source_id == source_id,
                )
            )
            if enabled != 1:
                raise ManagementError(
                    "management_source_disabled", "选用数据源已停用或组织不可用。", 422
                )
            row = (
                (
                    await connection.execute(
                        select(source_versions).where(
                            source_versions.c.scope_id == scope_id,
                            source_versions.c.source_id == source_id,
                            source_versions.c.revision == revision,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ManagementError(
                    "management_source_version_not_found", "冻结的数据源版本不存在。", 503
                )
            if row["execution_parameters"] is None:
                raise ManagementError(
                    "management_source_reimport_required",
                    "旧配置缺少执行参数快照，请从原配置文件重新导入并对账。", 422,
                )
            profile_row, catalog_row, credential = await require_release_dependencies(
                connection, scope_id, source_id, row
            )
            if profile_binding is not None and profile_binding != row["profile_version_id"]:
                raise ManagementError(
                    "management_profile_conflict", "本次数据源须绑定同一 Profile 发布版本。", 422
                )
            profile_binding = row["profile_version_id"]
            profile = EffectiveReportingProfile.model_validate(profile_row["effective_profile"])
            if profile.effective_profile_hash != profile_row["effective_profile_hash"]:
                raise ManagementError(
                    "management_runtime_reference_mismatch", "Profile 哈希不一致。", 503
                )
            if CatalogService._hash(catalog_row["catalog"]) != catalog_row["content_hash"]:
                raise ManagementError(
                    "management_runtime_reference_mismatch", "目录哈希不一致。", 503
                )
            dsn = self.vault.decrypt(
                credential["key_id"], json.loads(credential["ciphertext"]).encode()
            )
            if hashlib.sha256(dsn.encode()).hexdigest() != credential["secret_hash"]:
                raise ManagementError(
                    "management_runtime_reference_mismatch", "凭据身份不一致。", 503
                )
            payload = SourceDraftInput(
                name=row["name"],
                database=row["database"],
                dsn=SecretStr(dsn),
                reportingProfileVersionId=row["profile_version_id"],
                metadataVersionId=row["metadata_version_id"],
            )
            digest = SourceService._config_hash(
                payload.model_dump(mode="json", by_alias=True, exclude={"dsn"}),
                row["credential_revision"],
                row["execution_parameters"],
            )
            if digest != row["content_hash"]:
                raise ManagementError(
                    "management_runtime_reference_mismatch", "数据源配置哈希不一致。", 503
                )
            configs[source_id] = parse_starrocks_source(
                {
                    "id": source_id,
                    "type": "starrocks",
                    "name": row["name"],
                    "database": row["database"],
                    "dsnEnv": "MANAGED_DSN",
                    "reportingProfile": profile.profile_id,
                    **row["execution_parameters"],
                },
                {"MANAGED_DSN": dsn},
            )
            revisions[source_id], hashes[source_id] = revision, row["content_hash"]
            metadata[source_id] = CatalogService.validate_snapshot(
                catalog_row["catalog"], source_id, row["database"]
            )
            references.append(
                {
                    "sourceId": source_id,
                    "revision": revision,
                    "contentHash": row["content_hash"],
                    "credentialRevision": row["credential_revision"],
                    "profileVersionId": row["profile_version_id"],
                    "profileHash": profile.effective_profile_hash,
                    "profileParents": profile_row["parent_versions"],
                    "metadataVersionId": row["metadata_version_id"],
                    "metadataHash": catalog_row["content_hash"],
                }
            )
        if profile is None:
            raise ManagementError("management_profile_missing", "运行没有有效 Profile。", 422)
        profile = bind_reporting_profile_sources(
            profile, {key: value.database for key, value in configs.items()}
        )
        public = {
            "runId": run_id,
            "database": scope.database,
            "companyId": scope.company_id,
            "sources": references,
            "effectiveProfileHash": profile.effective_profile_hash,
        }
        return ManagedRunSnapshot(scope, configs, revisions, hashes, profile, metadata, public)
