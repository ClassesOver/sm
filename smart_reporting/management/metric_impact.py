"""按组织和精确版本读取指标依赖影响，不扫描业务数据。"""

from sqlalchemy import Integer, String, and_, cast, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB

from .models import ManagementError
from .repository import (
    metric_dependencies,
    metric_versions,
    report_bases,
    reporting_policy_defaults,
    statistical_policy_metrics,
    statistical_policy_versions,
)


async def read_metric_impact(service, token, scope, metric_id, *, revision, limit=50, after=None):
    if (type(revision) is not int or revision < 1 or type(limit) is not int or not 1 <= limit <= 100
        or (after is not None and (not isinstance(after, str) or len(after) > 300))):
        raise ManagementError('management_metric_invalid', '影响查询版本或分页条件无效。', 422)
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        scope_id = (await service.scopes.require_registered(connection, scope))['id']
        root = select(metric_versions.c.metric_id, metric_versions.c.revision).where(
            metric_versions.c.scope_id == scope_id, metric_versions.c.metric_id == metric_id, metric_versions.c.revision == revision)
        if await connection.scalar(root) is None:
            raise ManagementError('management_metric_not_found', '该组织不存在所选已发布指标版本。', 404)
        # UNION去重：同一派生版本经多条依赖路径到达时只返回一次。
        affected = root.cte('affected_metric_versions', recursive=True)
        affected = affected.union(select(metric_dependencies.c.metric_id, metric_dependencies.c.revision).join(affected,
            and_(metric_dependencies.c.dependency_metric_id == affected.c.metric_id,
                metric_dependencies.c.dependency_revision == affected.c.revision)).where(metric_dependencies.c.scope_id == scope_id))
        policies = select(statistical_policy_metrics.c.policy_id, statistical_policy_metrics.c.policy_revision).join(affected,
            and_(statistical_policy_metrics.c.metric_id == affected.c.metric_id,
                statistical_policy_metrics.c.metric_revision == affected.c.revision)).where(
                    statistical_policy_metrics.c.scope_id == scope_id).distinct().cte('affected_policy_versions')
        null_text, null_int = cast(literal(None), String), cast(literal(None), Integer)
        metrics = select(literal('metric').label('kind'), metric_versions.c.metric_id.label('reference_id'),
            metric_versions.c.revision, metric_versions.c.document['name'].as_string().label('name'),
            null_text.label('policy_id'), null_int.label('policy_revision'), null_text.label('basis_id'),
            (literal('metric:') + metric_versions.c.metric_id + ':' + cast(metric_versions.c.revision, String)).label('cursor')).join(
                affected, and_(metric_versions.c.metric_id == affected.c.metric_id, metric_versions.c.revision == affected.c.revision)).where(
                    metric_versions.c.scope_id == scope_id, or_(metric_versions.c.metric_id != metric_id, metric_versions.c.revision != revision))
        policy = select(literal('policy'), statistical_policy_versions.c.policy_id, statistical_policy_versions.c.revision,
            statistical_policy_versions.c.document['name'].as_string(), statistical_policy_versions.c.policy_id,
            statistical_policy_versions.c.revision, null_text,
            literal('policy:') + statistical_policy_versions.c.policy_id + ':' + cast(statistical_policy_versions.c.revision, String)).join(
                policies, and_(statistical_policy_versions.c.policy_id == policies.c.policy_id,
                    statistical_policy_versions.c.revision == policies.c.policy_revision)).where(statistical_policy_versions.c.scope_id == scope_id)
        defaults = select(literal('default'), reporting_policy_defaults.c.scenario, null_int, reporting_policy_defaults.c.scenario,
            reporting_policy_defaults.c.policy_id, reporting_policy_defaults.c.policy_revision, null_text,
            literal('default:') + reporting_policy_defaults.c.scenario).join(policies,
                and_(reporting_policy_defaults.c.policy_id == policies.c.policy_id,
                    reporting_policy_defaults.c.policy_revision == policies.c.policy_revision)).where(reporting_policy_defaults.c.scope_id == scope_id)
        # ReportBasis冻结完整依赖图；不从当前政策反推历史报告用过哪些指标。
        reports = select(literal('report'), report_bases.c.run_id, null_int, report_bases.c.run_id,
            report_bases.c.policy_id, report_bases.c.policy_revision, report_bases.c.basis_id,
            literal('report:') + report_bases.c.run_id).where(report_bases.c.scope_id == scope_id,
                cast(report_bases.c.document, JSONB)['metricVersions'].contains([{'metricId': metric_id, 'revision': revision}]))
        references = union_all(metrics, policy, defaults, reports).subquery()
        query = select(references)
        if after is not None:
            query = query.where(references.c.cursor > after)
        rows = (await connection.execute(query.order_by(references.c.cursor).limit(limit + 1))).mappings().all()
        return {'metricVersion': {'metricId': metric_id, 'revision': revision}, 'items': [
            {'kind': row['kind'], 'referenceId': row['reference_id'], 'revision': row['revision'], 'name': row['name'],
                'policyVersion': {'policyId': row['policy_id'], 'revision': row['policy_revision']} if row['policy_id'] else None,
                'basisId': row['basis_id']} for row in rows[:limit]],
            'nextCursor': rows[limit - 1]['cursor'] if len(rows) > limit else None}
