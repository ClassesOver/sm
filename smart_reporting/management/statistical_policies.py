"""统计口径草稿、不可变发布和显式默认选择。"""

from pydantic import ValidationError
from sqlalchemy import String, and_, cast, func, insert, literal, select, union, union_all, update

from ..reporting.semantics.models import MetricDefinition, PolicyVersionRef, StatisticalPolicy
from ..reporting.semantics.validation import validate_policy
from .business_documents import _digest
from .models import ManagementError
from .repository import metric_versions, report_bases
from .repository import reporting_policy_defaults as defaults
from .repository import statistical_policy_drafts as drafts
from .repository import statistical_policy_metrics as dependencies
from .repository import statistical_policy_versions as versions
from .semantic_retirements import read_retirement, require_active, retire_version


class StatisticalPolicyService:
    def __init__(self, scopes, evidence):
        self.scopes, self.repository, self.evidence = scopes, scopes.repository, evidence

    async def retire(self, token, scope, policy_id, revision, *, reason, replacement=None):
        return await retire_version(self.scopes, token, scope, "statistical_policy", policy_id, revision, reason=reason, replacement=replacement)

    @staticmethod
    def _definition(payload, scope_id, revision):
        if {"scopeId", "scope_id", "revision"}.intersection(payload):
            raise ManagementError("management_policy_invalid", "组织与发布版本由服务端登记。", 422)
        try:
            return StatisticalPolicy.model_validate({**payload, "scopeId": scope_id, "revision": revision})
        except ValidationError:
            raise ManagementError("management_policy_invalid", "统计口径结构无效。", 422) from None

    @staticmethod
    def _public(row):
        return {"revision": row["revision"], "document": row["document"], "contentHash": row["content_hash"]} if row else None

    async def _scope(self, connection, token, scope):
        await self.repository.authenticate_in_transaction(connection, token, self.scopes.auth.clock())
        return (await self.scopes.require_registered(connection, scope))["id"]

    async def _latest(self, connection, scope_id, policy_id):
        return (await connection.execute(select(versions).where(versions.c.scope_id == scope_id,
            versions.c.policy_id == policy_id).order_by(versions.c.revision.desc()).limit(1))).mappings().one_or_none()

    async def list(self, token, scope, *, limit=50, after=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ManagementError("management_policy_invalid", "分页大小无效。", 422)
        async with self.repository.transaction() as connection:
            scope_id = await self._scope(connection, token, scope)
            identities = union(select(drafts.c.policy_id).where(drafts.c.scope_id == scope_id),
                select(versions.c.policy_id).where(versions.c.scope_id == scope_id)).subquery()
            latest = select(versions.c.policy_id, func.max(versions.c.revision).label("revision")).where(
                versions.c.scope_id == scope_id).group_by(versions.c.policy_id).subquery()
            query = select(identities.c.policy_id, drafts.c.version, drafts.c.document.label("draft"),
                versions.c.revision, versions.c.document.label("published")).select_from(identities
                .outerjoin(drafts, and_(drafts.c.scope_id == scope_id, drafts.c.policy_id == identities.c.policy_id))
                .outerjoin(latest, latest.c.policy_id == identities.c.policy_id)
                .outerjoin(versions, and_(versions.c.scope_id == scope_id, versions.c.policy_id == latest.c.policy_id,
                    versions.c.revision == latest.c.revision)))
            if after is not None:
                query = query.where(identities.c.policy_id > after)
            rows = (await connection.execute(query.order_by(identities.c.policy_id).limit(limit + 1))).mappings().all()
            return {"items": [{"policyId": row["policy_id"], "name": (row["draft"] or row["published"])["name"],
                "draftVersion": row["version"], "publishedRevision": row["revision"]} for row in rows[:limit]],
                "nextCursor": rows[limit - 1]["policy_id"] if len(rows) > limit else None}

    async def impact(self, token, scope, policy_id, *, revision=None, limit=50, after=None):
        if type(limit) is not int or not 1 <= limit <= 100 or (revision is not None and (type(revision) is not int or revision < 1)):
            raise ManagementError("management_policy_invalid", "影响查询版本或分页大小无效。", 422)
        async with self.repository.transaction() as connection:
            scope_id = await self._scope(connection, token, scope)
            identity = select(versions.c.revision).where(versions.c.scope_id == scope_id, versions.c.policy_id == policy_id)
            if revision is not None:
                identity = identity.where(versions.c.revision == revision)
            if await connection.scalar(identity.limit(1)) is None:
                raise ManagementError("management_policy_not_found", "该组织不存在所选已发布口径。", 404)
            default_query = select(literal("default").label("kind"), defaults.c.scenario.label("reference_id"),
                defaults.c.policy_revision, cast(literal(None), String).label("basis_id"),
                (literal("default:") + defaults.c.scenario).label("cursor")).where(
                    defaults.c.scope_id == scope_id, defaults.c.policy_id == policy_id)
            report_query = select(literal("report").label("kind"), report_bases.c.run_id.label("reference_id"),
                report_bases.c.policy_revision, report_bases.c.basis_id,
                (literal("report:") + report_bases.c.run_id).label("cursor")).where(
                    report_bases.c.scope_id == scope_id, report_bases.c.policy_id == policy_id)
            if revision is not None:
                default_query = default_query.where(defaults.c.policy_revision == revision)
                report_query = report_query.where(report_bases.c.policy_revision == revision)
            references = union_all(default_query, report_query).subquery()
            query = select(references)
            if after is not None:
                query = query.where(references.c.cursor > after)
            rows = (await connection.execute(query.order_by(references.c.cursor).limit(limit + 1))).mappings().all()
            return {"items": [{"kind": row["kind"], "referenceId": row["reference_id"],
                "policyRevision": row["policy_revision"], "basisId": row["basis_id"]} for row in rows[:limit]],
                "nextCursor": rows[limit - 1]["cursor"] if len(rows) > limit else None}

    async def get(self, token, scope, policy_id, *, revision=None):
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ManagementError("management_policy_invalid", "发布版本无效。", 422)
        async with self.repository.transaction() as connection:
            scope_id = await self._scope(connection, token, scope)
            draft = (await connection.execute(select(drafts).where(drafts.c.scope_id == scope_id, drafts.c.policy_id == policy_id))).mappings().one_or_none()
            published = await self._latest(connection, scope_id, policy_id)
            if revision is not None:
                published = (await connection.execute(select(versions).where(versions.c.scope_id == scope_id,
                    versions.c.policy_id == policy_id, versions.c.revision == revision))).mappings().one_or_none()
            if published is None and (draft is None or revision is not None):
                raise ManagementError("management_policy_not_found", "该组织未登记此统计口径。", 404)
            return {"draft": {"version": draft["version"], "document": draft["document"], "contentHash": draft["content_hash"]} if draft else None,
                "published": self._public(published),
                "retirement": await read_retirement(connection, scope_id, "statistical_policy", policy_id, published["revision"]) if published else None}

    async def save_draft(self, token, scope, payload, *, expected_version):
        if type(expected_version) is not int or expected_version < 0:
            raise ManagementError("management_policy_invalid", "草稿版本无效。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            policy = self._definition(payload, scope_id, 1)
            current = (await connection.execute(select(drafts).where(drafts.c.scope_id == scope_id, drafts.c.policy_id == policy.id))).mappings().one_or_none()
            if (current["version"] if current else 0) != expected_version:
                raise ManagementError("management_version_conflict", "统计口径草稿已变化，请核对。", 409)
            next_revision = 1 + (await connection.scalar(select(func.max(versions.c.revision)).where(
                versions.c.scope_id == scope_id, versions.c.policy_id == policy.id)) or 0)
            policy = policy.model_copy(update={"revision": next_revision})
            body = policy.model_dump(mode="json", by_alias=True)
            values = {"version": expected_version + 1, "document": body, "content_hash": _digest(body)}
            if current:
                await connection.execute(update(drafts).where(drafts.c.scope_id == scope_id, drafts.c.policy_id == policy.id,
                    drafts.c.version == expected_version).values(**values))
            else:
                await connection.execute(insert(drafts).values(scope_id=scope_id, policy_id=policy.id, **values))
            await self.scopes.audit(connection, actor, "statistical_policy_draft_saved", {"policyId": policy.id, "version": values["version"]})
            return {"version": values["version"], "document": body, "contentHash": values["content_hash"]}

    async def _resolve(self, connection, scope_id, policy):
        release = await self.evidence._existing(connection, scope_id, policy.evidence_release_id)
        if release is None or release.kind != "rule_evidence":
            raise ManagementError("management_policy_evidence_missing", "口径须引用该组织已发布的制度依据集合。", 409)
        rows = await self.evidence._rows(connection, scope_id, tuple(doc.reference for doc in release.documents))
        if any(row["review_status"] != "approved" or row["ingestion_status"] != "ready" for row in rows):
            raise ManagementError("management_policy_evidence_unavailable", "所选制度依据已撤销或尚未就绪。", 409)
        resolved = await self._metric_graph(connection, scope_id, policy)
        return validate_policy(policy, tuple(resolved.values()))

    async def _background(self, connection, scope_id, release_id):
        background = await self.evidence._existing(connection, scope_id, release_id)
        if background is None or background.kind != "background":
            raise ManagementError("management_policy_background_missing", "须显式选择该组织已发布的背景集合。", 409)
        rows = await self.evidence._rows(connection, scope_id, tuple(doc.reference for doc in background.documents))
        if any(row["review_status"] != "approved" or row["ingestion_status"] != "ready" for row in rows):
            raise ManagementError("management_policy_background_unavailable", "所选背景依据已撤销或尚未就绪。", 409)

    async def _metric_graph(self, connection, scope_id, policy, *, require_available=True):
        return await self._metric_refs(connection, scope_id, policy.metric_versions, require_available=require_available)

    async def _metric_refs(self, connection, scope_id, references, *, require_available=True):
        resolved = {}
        pending = list(references)
        while pending:
            ref = pending.pop()
            if ref in resolved:
                continue
            if require_available:
                await require_active(connection, scope_id, "metric", ref.metric_id, ref.revision)
            row = (await connection.execute(select(metric_versions).where(metric_versions.c.scope_id == scope_id,
                metric_versions.c.metric_id == ref.metric_id, metric_versions.c.revision == ref.revision))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_policy_metric_missing", "口径须引用该组织已发布的精确指标版本。", 409)
            metric = MetricDefinition.model_validate(row["document"])
            if metric.scope_id != scope_id or metric.version_ref() != ref or _digest(row["document"]) != row["content_hash"]:
                raise ManagementError("management_policy_identity_invalid", "指标版本身份不一致。", 409)
            resolved[ref] = metric
            if len(resolved) > 200:
                raise ManagementError("management_policy_metric_limit", "指标依赖超过首期支持范围。", 422)
            pending.extend(item for item in (metric.numerator_version, metric.denominator_version) if item is not None)
        return resolved

    @staticmethod
    def _calculation_signature(policy, graph):
        memo = {}
        def signature(ref, visiting):
            if ref in memo:
                return memo[ref]
            if ref in visiting:
                return _digest({"cycle": ref.metric_id})
            metric = graph[ref]
            body = metric.model_dump(mode="json", by_alias=True,
                exclude={"revision", "scope_id", "name", "aliases", "numerator_version", "denominator_version"})
            for key, dependency in (("numerator", metric.numerator_version), ("denominator", metric.denominator_version)):
                if dependency is not None:
                    body[key] = signature(dependency, visiting | {ref})
            memo[ref] = _digest(body)
            return memo[ref]
        return tuple(sorted((ref.metric_id, signature(ref, set())) for ref in policy.metric_versions))

    async def publish(self, token, scope, policy_id, *, expected_version):
        if type(expected_version) is not int or expected_version < 1:
            raise ManagementError("management_policy_invalid", "草稿版本无效。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            draft = (await connection.execute(select(drafts).where(drafts.c.scope_id == scope_id, drafts.c.policy_id == policy_id))).mappings().one_or_none()
            if draft is None:
                raise ManagementError("management_policy_not_found", "该组织不存在此口径草稿。", 404)
            if draft["version"] != expected_version:
                raise ManagementError("management_version_conflict", "口径草稿已有更新，请核对。", 409)
            policy = StatisticalPolicy.model_validate(draft["document"])
            if policy.scope_id != scope_id or policy.id != policy_id or _digest(draft["document"]) != draft["content_hash"]:
                raise ManagementError("management_policy_identity_invalid", "口径身份不一致。", 409)
            await require_active(connection, scope_id, "statistical_policy", policy_id, policy.revision)
            issues = await self._resolve(connection, scope_id, policy)
            current = (await connection.execute(select(versions).where(versions.c.scope_id == scope_id,
                versions.c.policy_id == policy_id, versions.c.revision == policy.revision))).mappings().one_or_none()
            if current is not None and current["content_hash"] != draft["content_hash"]:
                raise ManagementError("management_version_conflict", "该发布版本已有其他内容，请核对。", 409)
            if current is None:
                await connection.execute(insert(versions).values(scope_id=scope_id, policy_id=policy_id, revision=policy.revision,
                    document=draft["document"], content_hash=draft["content_hash"], evidence_release_id=policy.evidence_release_id,
                    published_at=self.scopes.auth.clock()))
                for ref in policy.metric_versions:
                    await connection.execute(insert(dependencies).values(scope_id=scope_id, policy_id=policy_id,
                        policy_revision=policy.revision, metric_id=ref.metric_id, metric_revision=ref.revision))
                await self.scopes.audit(connection, actor, "statistical_policy_published", {"policyId": policy_id, "revision": policy.revision})
            return {"revision": policy.revision, "document": draft["document"], "contentHash": draft["content_hash"],
                "issues": [issue.model_dump(mode="json", by_alias=True) for issue in issues]}

    async def preview(self, token, scope, payload):
        async with self.repository.transaction() as connection:
            scope_id = await self._scope(connection, token, scope)
            policy = self._definition(payload, scope_id, 1)
            previous = await self._latest(connection, scope_id, policy.id)
            issues = await self._resolve(connection, scope_id, policy)
            body = policy.model_dump(mode="json", by_alias=True)
            fields = ("filters", "joins", "readinessPolicy", "validFrom", "validTo", "scenario")
            old = previous["document"] if previous else {}
            changed = [field for field in fields if old.get(field) != body.get(field)]
            current_metrics = await self._metric_graph(connection, scope_id, policy)
            old_signature = None
            if previous:
                old_policy = StatisticalPolicy.model_validate(old)
                old_metrics = await self._metric_graph(connection, scope_id, old_policy, require_available=False)
                old_signature = self._calculation_signature(old_policy, old_metrics)
            if old_signature != self._calculation_signature(policy, current_metrics):
                changed.append("metrics")
            return {"calculationChanged": bool(changed), "changedFields": changed,
                "metricVersionsChanged": old.get("metricVersions") != body.get("metricVersions"),
                "evidenceChanged": old.get("evidenceReleaseId") != policy.evidence_release_id,
                "issues": [issue.model_dump(mode="json", by_alias=True) for issue in issues]}

    @staticmethod
    def _default(row):
        return {"version": row["version"] if row else 0,
            "policyVersion": {"policyId": row["policy_id"], "revision": row["policy_revision"]} if row else None,
            "backgroundReleaseId": row["background_release_id"] if row else None}

    async def get_default(self, token, scope, scenario):
        async with self.repository.transaction() as connection:
            scope_id = await self._scope(connection, token, scope)
            row = (await connection.execute(select(defaults).where(defaults.c.scope_id == scope_id, defaults.c.scenario == scenario))).mappings().one_or_none()
            result = self._default(row)
            result["issues"] = []
            if row:
                policy_row = (await connection.execute(select(versions).where(versions.c.scope_id == scope_id,
                    versions.c.policy_id == row["policy_id"], versions.c.revision == row["policy_revision"]))).mappings().one()
                try:
                    await require_active(connection, scope_id, "statistical_policy", row["policy_id"], row["policy_revision"])
                    issues = await self._resolve(connection, scope_id, StatisticalPolicy.model_validate(policy_row["document"]))
                    result["issues"].extend(issue.model_dump(mode="json", by_alias=True) for issue in issues)
                except ManagementError as error:
                    if error.code not in ("management_semantic_asset_retired", "management_policy_evidence_unavailable"):
                        raise
                    result["issues"].append({"code": error.code.removeprefix("management_"), "impact": "unavailable",
                        "message": error.message})
                if row["background_release_id"] is not None:
                    try:
                        await self._background(connection, scope_id, row["background_release_id"])
                    except ManagementError as error:
                        if error.code != "management_policy_background_unavailable":
                            raise
                        result["issues"].append({"code": "policy_background_unavailable", "impact": "warning", "message": error.message})
            return result

    async def set_default(self, token, scope, scenario, *, policy_version, expected_version, background_release_id=None):
        policy_version = PolicyVersionRef.model_validate(policy_version)
        if type(expected_version) is not int or expected_version < 0:
            raise ManagementError("management_policy_invalid", "默认绑定版本无效。", 422)
        actor = await self.scopes.actor(token, scope)
        async with self.scopes.write_transaction(actor) as connection:
            scope_id = (await self.scopes.require_registered(connection, scope))["id"]
            row = (await connection.execute(select(defaults).where(defaults.c.scope_id == scope_id, defaults.c.scenario == scenario))).mappings().one_or_none()
            if (row["version"] if row else 0) != expected_version:
                raise ManagementError("management_version_conflict", "默认绑定已变化，请读回核对。", 409)
            selected = (await connection.execute(select(versions).where(versions.c.scope_id == scope_id,
                versions.c.policy_id == policy_version.policy_id, versions.c.revision == policy_version.revision))).mappings().one_or_none()
            if selected is None:
                raise ManagementError("management_policy_not_found", "该组织不存在所选已发布口径。", 404)
            await require_active(connection, scope_id, "statistical_policy", policy_version.policy_id, policy_version.revision)
            policy = StatisticalPolicy.model_validate(selected["document"])
            if policy.scenario != scenario or policy.scope_id != scope_id:
                raise ManagementError("management_policy_scenario_mismatch", "口径与报告场景不一致。", 422)
            await self._resolve(connection, scope_id, policy)
            if background_release_id is not None:
                await self._background(connection, scope_id, background_release_id)
            values = {"version": expected_version + 1, "policy_id": policy.id, "policy_revision": policy.revision,
                "background_release_id": background_release_id}
            if row:
                await connection.execute(update(defaults).where(defaults.c.scope_id == scope_id, defaults.c.scenario == scenario,
                    defaults.c.version == expected_version).values(**values))
            else:
                await connection.execute(insert(defaults).values(scope_id=scope_id, scenario=scenario, **values))
            await self.scopes.audit(connection, actor, "report_policy_default_set", {"scenario": scenario, "policyId": policy.id,
                "revision": policy.revision, "version": values["version"]})
            return self._default(values)
