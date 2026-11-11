"""原件精确修订的登记关联；只读管理库，不把集合成员等同实际引用。"""

from sqlalchemy import Integer, String, and_, cast, literal, or_, select, union_all

from .models import ManagementError
from .repository import (
    business_document_revisions,
    business_evidence_release_documents,
    business_evidence_releases,
    report_bases,
    reporting_policy_defaults,
    statistical_policy_versions,
)


async def read_document_impact(
    service, token, scope, document_id, revision, *, limit=50, after=None
):
    if (
        type(revision) is not int
        or revision < 1
        or type(limit) is not int
        or not 1 <= limit <= 100
        or (after is not None and (not isinstance(after, str) or len(after) > 400))
    ):
        raise ManagementError("management_document_invalid", "影响查询版本或分页条件无效。", 422)
    async with service.repository.transaction() as connection:
        scope_id = (await service._scope_row(connection, token, scope))["id"]
        exists = await connection.scalar(
            select(business_document_revisions.c.revision).where(
                business_document_revisions.c.scope_id == scope_id,
                business_document_revisions.c.document_id == document_id,
                business_document_revisions.c.revision == revision,
            )
        )
        if exists is None:
            raise ManagementError("management_document_not_found", "该组织不存在此原件修订。", 404)
        members = business_evidence_release_documents
        releases = (
            select(members.c.release_id)
            .where(
                members.c.scope_id == scope_id,
                members.c.document_id == document_id,
                members.c.revision == revision,
            )
            .cte("document_releases")
        )
        policies = statistical_policy_versions
        affected_policies = (
            select(policies.c.policy_id, policies.c.revision)
            .where(
                policies.c.scope_id == scope_id,
                policies.c.evidence_release_id.in_(select(releases.c.release_id)),
            )
            .cte("document_policies")
        )
        null_text, null_int = cast(literal(None), String), cast(literal(None), Integer)
        evidence = business_evidence_releases
        release_rows = select(
            literal("evidence_release").label("kind"),
            evidence.c.release_id.label("reference_id"),
            null_int.label("revision"),
            evidence.c.release_id.label("name"),
            null_text.label("policy_id"),
            null_int.label("policy_revision"),
            null_text.label("basis_id"),
            evidence.c.kind.label("evidence_kind"),
            (literal("release:") + evidence.c.release_id).label("cursor"),
        ).where(
            evidence.c.scope_id == scope_id,
            evidence.c.release_id.in_(select(releases.c.release_id)),
        )
        policy_rows = select(
            literal("policy"),
            policies.c.policy_id,
            policies.c.revision,
            policies.c.document["name"].as_string(),
            policies.c.policy_id,
            policies.c.revision,
            null_text,
            null_text,
            literal("policy:") + policies.c.policy_id + ":" + cast(policies.c.revision, String),
        ).where(
            policies.c.scope_id == scope_id,
            policies.c.evidence_release_id.in_(select(releases.c.release_id)),
        )
        defaults = reporting_policy_defaults
        default_rows = select(
            literal("default"),
            defaults.c.scenario,
            defaults.c.version,
            defaults.c.scenario,
            defaults.c.policy_id,
            defaults.c.policy_revision,
            null_text,
            null_text,
            literal("default:") + defaults.c.scenario,
        ).where(
            defaults.c.scope_id == scope_id,
            or_(
                defaults.c.background_release_id.in_(select(releases.c.release_id)),
                select(affected_policies.c.policy_id)
                .where(
                    and_(
                        affected_policies.c.policy_id == defaults.c.policy_id,
                        affected_policies.c.revision == defaults.c.policy_revision,
                    )
                )
                .exists(),
            ),
        )
        # 历史报告直接读取已登记制度/背景集合，不能用当前默认或口径反推。
        reports = select(
            literal("report"),
            report_bases.c.run_id,
            null_int,
            report_bases.c.run_id,
            report_bases.c.policy_id,
            report_bases.c.policy_revision,
            report_bases.c.basis_id,
            null_text,
            literal("report:") + report_bases.c.run_id,
        ).where(
            report_bases.c.scope_id == scope_id,
            or_(
                report_bases.c.evidence_release_id.in_(select(releases.c.release_id)),
                report_bases.c.background_release_id.in_(select(releases.c.release_id)),
            ),
        )
        references = union_all(release_rows, policy_rows, default_rows, reports).subquery()
        query = select(references)
        if after is not None:
            query = query.where(references.c.cursor > after)
        rows = (
            (await connection.execute(query.order_by(references.c.cursor).limit(limit + 1)))
            .mappings()
            .all()
        )
        return {
            "documentRevision": {"documentId": document_id, "revision": revision},
            "items": [
                {
                    "kind": row["kind"],
                    "referenceId": row["reference_id"],
                    "revision": row["revision"],
                    "name": row["name"],
                    "policyVersion": {
                        "policyId": row["policy_id"],
                        "revision": row["policy_revision"],
                    }
                    if row["policy_id"]
                    else None,
                    "basisId": row["basis_id"],
                    "evidenceKind": row["evidence_kind"],
                }
                for row in rows[:limit]
            ],
            "nextCursor": rows[limit - 1]["cursor"] if len(rows) > limit else None,
        }
