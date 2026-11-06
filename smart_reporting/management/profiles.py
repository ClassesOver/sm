from __future__ import annotations

import hashlib
import json

from sqlalchemy import insert, select, update

from ..reporting.profile.models import (
    ReportingProfileDocument,
    ReportingProfileRegistry,
)
from ..reporting.profile.registry import resolve_reporting_profile
from .models import ManagementActor, ManagementError, ManagementScope
from .repository import profile_drafts, profile_versions
from .scopes import ScopeService


class ProfileService:
    def __init__(self, scope_service: ScopeService):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.auth = scope_service.auth

    @staticmethod
    def _document(payload: dict) -> ReportingProfileDocument:
        try:
            return ReportingProfileDocument.model_validate(payload)
        except Exception as error:
            raise ManagementError(
                "management_profile_invalid", "Profile JSON 不符合现有契约。", 422
            ) from error

    @staticmethod
    def _json(document: ReportingProfileDocument) -> dict:
        return document.model_dump(mode="json", by_alias=True, exclude_none=True)

    @staticmethod
    def _hash(payload: dict) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def _scope_id(self, connection, scope: ManagementScope) -> str:
        row = await ScopeService.require_registered(connection, scope)
        return row["id"]

    async def _published_documents(
        self, connection, scope_id: str, document: ReportingProfileDocument
    ) -> dict[str, tuple[int, ReportingProfileDocument]]:
        result: dict[str, tuple[int, ReportingProfileDocument]] = {}
        chosen: dict[str, int] = {}

        async def visit(profile_id: str, revision: int | None = None):
            query = select(profile_versions).where(
                profile_versions.c.scope_id == scope_id,
                profile_versions.c.profile_id == profile_id,
            )
            if revision is not None:
                query = query.where(profile_versions.c.revision == revision)
            row = (
                (
                    await connection.execute(
                        query.order_by(profile_versions.c.revision.desc()).limit(1)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ManagementError(
                    "management_profile_parent_missing", "Profile 父版本尚未发布。", 422
                )
            if profile_id in chosen:
                if chosen[profile_id] != row["revision"]:
                    raise ManagementError(
                        "management_profile_parent_conflict",
                        "多个父版本依赖不同的祖先版本，请显式重新发布父版本。",
                        422,
                    )
                return
            chosen[profile_id] = row["revision"]
            parent = self._document(row["document"])
            pinned = {item["profileId"]: item["revision"] for item in row["parent_versions"]}
            if any(key not in pinned for key in parent.extends):
                raise ManagementError(
                    "management_profile_parent_incomplete",
                    "父版本缺少继承引用，请重新发布该版本。",
                    422,
                )
            for key in parent.extends:
                await visit(key, pinned[key])
            result[profile_id] = (row["revision"], parent)

        for key in document.extends:
            await visit(key)
        return result

    def _effective(
        self,
        document: ReportingProfileDocument,
        published: dict[str, tuple[int, ReportingProfileDocument]],
    ):
        documents = {key: value[1] for key, value in published.items()}
        documents[document.profile_id] = document
        try:
            return resolve_reporting_profile(
                ReportingProfileRegistry(documents=documents, config_paths=()), document.profile_id
            )
        except Exception as error:
            raise ManagementError(
                "management_profile_invalid", "Profile 继承关系或字段引用无效。", 422
            ) from error

    @staticmethod
    def _parents(
        document: ReportingProfileDocument,
        published: dict[str, tuple[int, ReportingProfileDocument]],
    ) -> list[dict]:
        missing = [parent for parent in document.extends if parent not in published]
        if missing:
            raise ManagementError(
                "management_profile_parent_missing", "Profile 父版本尚未发布。", 422
            )
        return [{"profileId": key, "revision": value[0]} for key, value in published.items()]

    async def preview(self, raw_session: str, scope: ManagementScope, payload: dict) -> dict:
        document = self._document(payload)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            scope_id = await self._scope_id(connection, scope)
            published = await self._published_documents(connection, scope_id, document)
        effective = self._effective(document, published)
        return effective.model_dump(mode="json", by_alias=True)

    async def save_draft(
        self, raw_session: str, scope: ManagementScope, payload: dict, expected_version: int
    ) -> dict:
        document = self._document(payload)
        body = self._json(document)
        digest = self._hash(body)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, now
            )
            scope_id = await self._scope_id(connection, scope)
            current = (
                (
                    await connection.execute(
                        select(profile_drafts).where(
                            profile_drafts.c.scope_id == scope_id,
                            profile_drafts.c.profile_id == document.profile_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            current_version = current["version"] if current else 0
            if current_version != expected_version:
                raise ManagementError(
                    "management_version_conflict", "Profile 草稿已被其他操作更新。", 409
                )
            version = expected_version + 1
            if current is None:
                await connection.execute(
                    insert(profile_drafts).values(
                        scope_id=scope_id,
                        profile_id=document.profile_id,
                        version=version,
                        document=body,
                        content_hash=digest,
                    )
                )
            else:
                await connection.execute(
                    update(profile_drafts)
                    .where(
                        profile_drafts.c.scope_id == scope_id,
                        profile_drafts.c.profile_id == document.profile_id,
                        profile_drafts.c.version == expected_version,
                    )
                    .values(version=version, document=body, content_hash=digest)
                )
            await self.scope_service.audit(
                connection,
                ManagementActor(
                    account.account_id,
                    account.username,
                    scope,
                    account.auth_version,
                    raw_session,
                ),
                "profile_draft_saved",
                {"profileId": document.profile_id, "version": version},
            )
            return {"profileId": document.profile_id, "version": version, "contentHash": digest}

    async def publish(
        self, raw_session: str, scope: ManagementScope, profile_id: str, expected_version: int
    ) -> dict:
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, now
            )
            scope_id = await self._scope_id(connection, scope)
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
                .one_or_none()
            )
            if draft is None:
                raise ManagementError("management_profile_not_found", "Profile 草稿不存在。", 404)
            if draft["version"] != expected_version:
                raise ManagementError(
                    "management_version_conflict", "Profile 草稿已被其他操作更新。", 409
                )
            document = self._document(draft["document"])
            published = await self._published_documents(connection, scope_id, document)
            parents = self._parents(document, published)
            effective = self._effective(document, published)
            previous = (
                await connection.execute(
                    select(profile_versions.c.revision)
                    .where(
                        profile_versions.c.scope_id == scope_id,
                        profile_versions.c.profile_id == profile_id,
                    )
                    .order_by(profile_versions.c.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            revision = (previous or 0) + 1
            effective_json = effective.model_dump(mode="json", by_alias=True)
            await connection.execute(
                insert(profile_versions).values(
                    scope_id=scope_id,
                    profile_id=profile_id,
                    revision=revision,
                    document=draft["document"],
                    effective_profile=effective_json,
                    effective_profile_hash=effective.effective_profile_hash,
                    parent_versions=parents,
                    published_at=now,
                )
            )
            await self.scope_service.audit(
                connection,
                ManagementActor(
                    account.account_id,
                    account.username,
                    scope,
                    account.auth_version,
                    raw_session,
                ),
                "profile_version_published",
                {"profileId": profile_id, "revision": revision, "parentVersions": parents},
            )
            return {
                "profileId": profile_id,
                "revision": revision,
                "effectiveProfileHash": effective.effective_profile_hash,
                "parentVersions": parents,
                "publishedAt": now.isoformat(),
            }

    async def get_version(
        self, raw_session: str, scope: ManagementScope, profile_id: str, revision: int
    ) -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            scope_id = await self._scope_id(connection, scope)
            row = (
                (
                    await connection.execute(
                        select(profile_versions).where(
                            profile_versions.c.scope_id == scope_id,
                            profile_versions.c.profile_id == profile_id,
                            profile_versions.c.revision == revision,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ManagementError(
                    "management_profile_version_not_found", "Profile 发布版本不存在。", 404
                )
            return {
                "profileId": profile_id,
                "revision": revision,
                "document": row["document"],
                "effectiveProfile": row["effective_profile"],
                "effectiveProfileHash": row["effective_profile_hash"],
                "parentVersions": row["parent_versions"],
                "publishedAt": row["published_at"].isoformat(),
            }
