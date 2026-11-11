"""指标草稿CAS与已发布版本读取，沿用组织认证和事务审计。"""

import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import and_, func, insert, select, union, update

from ..reporting.semantics.models import MetricDefinition
from ..reporting.semantics.validation import validate_metric_graph
from .models import ManagementError, ManagementScope
from .repository import metric_dependencies, metric_drafts, metric_versions
from .scopes import ScopeService
from .semantic_retirements import read_retirement, require_active, retire_version


class MetricService:
    def __init__(self, scopes: ScopeService):
        self.scopes = scopes
        self.repository = scopes.repository

    async def retire(self, token, scope, metric_id, revision, *, reason, replacement=None):
        return await retire_version(self.scopes, token, scope, "metric", metric_id, revision, reason=reason, replacement=replacement)

    async def impact(self, token, scope, metric_id, *, revision, limit=50, after=None):
        from .metric_impact import read_metric_impact

        return await read_metric_impact(self, token, scope, metric_id, revision=revision, limit=limit, after=after)

    async def field_catalog(self, token, scope, source_id, source_revision, *, query='', limit=50, after=None):
        from .metric_field_catalog import read_field_catalog

        return await read_field_catalog(self, token, scope, source_id, source_revision, query=query, limit=limit, after=after)

    async def list(self, token: str, scope: ManagementScope, *, limit: int = 50, after: str | None = None) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ManagementError("management_metric_invalid", "分页大小无效。", 422)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, token, self.scopes.auth.clock())
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            identities = union(
                select(metric_drafts.c.metric_id).where(metric_drafts.c.scope_id == scope_id),
                select(metric_versions.c.metric_id).where(metric_versions.c.scope_id == scope_id),
            ).subquery()
            latest = select(metric_versions.c.metric_id, func.max(metric_versions.c.revision).label("revision")).where(
                metric_versions.c.scope_id == scope_id,
            ).group_by(metric_versions.c.metric_id).subquery()
            query = select(identities.c.metric_id, metric_drafts.c.version,
                metric_drafts.c.document.label("draft"), metric_versions.c.revision,
                metric_versions.c.document.label("published"),
            ).select_from(identities.outerjoin(metric_drafts, and_(metric_drafts.c.scope_id == scope_id,
                metric_drafts.c.metric_id == identities.c.metric_id)).outerjoin(latest, latest.c.metric_id == identities.c.metric_id)
                .outerjoin(metric_versions, and_(metric_versions.c.scope_id == scope_id,
                    metric_versions.c.metric_id == latest.c.metric_id, metric_versions.c.revision == latest.c.revision)))
            if after is not None:
                query = query.where(identities.c.metric_id > after)
            rows = (await connection.execute(query.order_by(identities.c.metric_id).limit(limit + 1))).mappings().all()
            return {"items": [{"metricId": row["metric_id"], "name": (row["draft"] or row["published"])["name"],
                "draftVersion": row["version"], "publishedRevision": row["revision"]} for row in rows[:limit]],
                "nextCursor": rows[limit - 1]["metric_id"] if len(rows) > limit else None}

    async def publish(self, token: str, scope: ManagementScope, metric_id: str, *, expected_version: int) -> dict:
        if type(expected_version) is not int or expected_version < 1:
            raise ManagementError("management_metric_invalid", "请提供有效草稿版本。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            draft = (await connection.execute(select(metric_drafts).where(
                metric_drafts.c.scope_id == scope_id, metric_drafts.c.metric_id == metric_id,
            ))).mappings().one_or_none()
            if draft is None:
                raise ManagementError("management_metric_not_found", "该组织未登记此指标草稿。", 404)
            if draft["version"] != expected_version:
                raise ManagementError("management_version_conflict", "指标草稿已变化，请先读回核对。", 409)
            definition = MetricDefinition.model_validate(draft["document"])
            digest = hashlib.sha256(json.dumps(draft["document"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if definition.scope_id != scope_id or definition.id != metric_id or digest != draft["content_hash"]:
                raise ManagementError("management_metric_identity_invalid", "指标草稿身份不一致。", 409)
            await require_active(connection, scope_id, "metric", metric_id, definition.revision)
            versions = {definition.version_ref(): definition}
            pending = [definition]
            while pending:
                current = pending.pop()
                for ref in (current.numerator_version, current.denominator_version):
                    if ref is None:
                        continue
                    await require_active(connection, scope_id, "metric", ref.metric_id, ref.revision)
                    if ref == definition.version_ref():
                        raise ManagementError("management_metric_dependency_invalid", "不能依赖待发布的自身版本。", 409)
                    if ref in versions:
                        continue
                    row = (await connection.execute(select(metric_versions).where(
                        metric_versions.c.scope_id == scope_id, metric_versions.c.metric_id == ref.metric_id,
                        metric_versions.c.revision == ref.revision,
                    ))).mappings().one_or_none()
                    if row is None:
                        raise ManagementError("management_metric_dependency_missing", "依赖的精确指标版本须已在该组织发布。", 409)
                    dependency = MetricDefinition.model_validate(row["document"])
                    if dependency.scope_id != scope_id or dependency.version_ref() != ref:
                        raise ManagementError("management_metric_identity_invalid", "依赖指标身份不一致。", 409)
                    versions[ref] = dependency
                    if len(versions) > 200:
                        raise ManagementError("management_metric_dependency_limit", "指标依赖超过首期支持范围。", 422)
                    pending.append(dependency)
            issues = validate_metric_graph(scope_id, (definition.version_ref(),), tuple(versions.values()))
            if any(issue.code == "metric_dependency_cycle" for issue in issues):
                raise ManagementError("management_metric_dependency_invalid", "指标依赖存在循环。", 409)
            published = (await connection.execute(select(metric_versions).where(
                metric_versions.c.scope_id == scope_id, metric_versions.c.metric_id == metric_id,
                metric_versions.c.revision == definition.revision,
            ))).mappings().one_or_none()
            if published is not None and published["content_hash"] != digest:
                raise ManagementError("management_version_conflict", "此发布版本已有其他内容，请核对。", 409)
            if published is None:
                await connection.execute(insert(metric_versions).values(scope_id=scope_id, metric_id=metric_id,
                    revision=definition.revision, document=draft["document"], content_hash=digest, published_at=self.scopes.auth.clock()))
                for ref in {definition.numerator_version, definition.denominator_version} - {None}:
                    await connection.execute(insert(metric_dependencies).values(scope_id=scope_id, metric_id=metric_id,
                        revision=definition.revision, dependency_metric_id=ref.metric_id, dependency_revision=ref.revision))
                await self.scopes.audit(connection, actor, "metric_published", {
                    "metricId": metric_id, "revision": definition.revision, "contentHash": digest,
                })
            return {"revision": definition.revision, "document": draft["document"], "contentHash": digest,
                "issues": [issue.model_dump(mode="json", by_alias=True) for issue in issues]}

    async def save_draft(
        self, token: str, scope: ManagementScope, payload: dict, expected_version: int,
    ) -> dict:
        if {"scopeId", "scope_id", "revision"}.intersection(payload) or type(expected_version) is not int or expected_version < 0:
            raise ManagementError("management_metric_invalid", "组织和发布版本由服务端登记。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            organization = await self.scopes.require_registered(connection, scope)
            scope_id = organization["id"]
            try:
                definition = MetricDefinition.model_validate({**payload, "scopeId": scope_id, "revision": 1})
            except ValidationError as error:
                raise ManagementError("management_metric_invalid", "指标结构不符合新业务契约。", 422) from error
            next_revision = 1 + (await connection.scalar(select(func.max(metric_versions.c.revision)).where(
                metric_versions.c.scope_id == scope_id, metric_versions.c.metric_id == definition.id,
            )) or 0)
            definition = definition.model_copy(update={"revision": next_revision})
            current = (await connection.execute(select(metric_drafts).where(
                metric_drafts.c.scope_id == scope_id, metric_drafts.c.metric_id == definition.id,
            ))).mappings().one_or_none()
            if (current["version"] if current else 0) != expected_version:
                raise ManagementError("management_version_conflict", "指标草稿已更新，请核对后保存。", 409)
            document = definition.model_dump(mode="json", by_alias=True)
            digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            values = {"version": expected_version + 1, "document": document, "content_hash": digest}
            if current:
                await connection.execute(update(metric_drafts).where(
                    metric_drafts.c.scope_id == scope_id, metric_drafts.c.metric_id == definition.id,
                    metric_drafts.c.version == expected_version,
                ).values(**values))
            else:
                await connection.execute(insert(metric_drafts).values(scope_id=scope_id, metric_id=definition.id, **values))
            await self.scopes.audit(connection, actor, "metric_draft_saved", {
                "metricId": definition.id, "version": values["version"], "contentHash": digest,
            })
            return {"version": values["version"], "document": document, "contentHash": digest}

    async def get(self, token: str, scope: ManagementScope, metric_id: str, *, revision: int | None = None) -> dict:
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ManagementError("management_metric_invalid", "发布版本无效。", 422)
        await self.scopes.actor(token, scope)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, token, self.scopes.auth.clock())
            organization = await self.scopes.require_registered(connection, scope)
            scope_id = organization["id"]
            draft = (await connection.execute(select(metric_drafts).where(
                metric_drafts.c.scope_id == scope_id, metric_drafts.c.metric_id == metric_id,
            ))).mappings().one_or_none()
            published_query = select(metric_versions).where(
                metric_versions.c.scope_id == scope_id, metric_versions.c.metric_id == metric_id,
            )
            if revision is not None:
                published_query = published_query.where(metric_versions.c.revision == revision)
            published = (await connection.execute(published_query.order_by(metric_versions.c.revision.desc()).limit(1))).mappings().one_or_none()
            if published is None and (draft is None or revision is not None):
                raise ManagementError("management_metric_not_found", "该组织未登记此指标。", 404)
            return {
                "draft": {"version": draft["version"], "document": draft["document"], "contentHash": draft["content_hash"]} if draft else None,
                "published": {"revision": published["revision"], "document": published["document"], "contentHash": published["content_hash"]} if published else None,
                "retirement": await read_retirement(connection, scope_id, "metric", metric_id, published["revision"]) if published else None,
            }
