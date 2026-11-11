"""核对问题关联的正式修复版本；登记关联不代表回归通过或问题解决。"""

from sqlalchemy import and_, select

from ..reporting.business_knowledge.models import ParsedDocument
from ..reporting.semantics.models import MetricVersionRef, PolicyVersionRef
from .business_documents import _digest
from .models import ManagementError
from .repository import (
    business_document_revisions as revisions,
)
from .repository import (
    business_evidence_release_documents as members,
)
from .repository import (
    business_evidence_releases as releases,
)
from .repository import (
    business_revision_states as states,
)
from .repository import runtime_snapshots
from .semantic_retirements import require_active


async def _document(connection, scope_id, document_id, revision):
    row = (await connection.execute(select(revisions, states.c.review_status,
        states.c.ingestion_status, states.c.parse_receipt).join(states, and_(
            states.c.scope_id == revisions.c.scope_id, states.c.document_id == revisions.c.document_id,
            states.c.revision == revisions.c.revision)).where(revisions.c.scope_id == scope_id,
            revisions.c.document_id == document_id, revisions.c.revision == revision))).mappings().one_or_none()
    if row is None:
        raise ManagementError('management_issue_fix_missing', '该组织不存在所选原件修订。', 409)
    if row['review_status'] != 'approved' or row['ingestion_status'] != 'ready' or not row['parse_receipt']:
        raise ManagementError('management_issue_fix_unavailable', '修复原件须已发布、完整解析且审核可用。', 409)
    parsed = ParsedDocument.model_validate(row['parse_receipt'])
    if (_digest(row['document']) != row['content_hash'] or row['document']['metadata']['id'] != document_id
            or parsed.original_hash != row['original_hash']):
        raise ManagementError('management_issue_fix_identity_invalid', '修复原件的登记与解析身份不一致。', 409)
    published = await connection.scalar(select(members.c.release_id).where(members.c.scope_id == scope_id,
        members.c.document_id == document_id, members.c.revision == revision).limit(1))
    if published is None:
        raise ManagementError('management_issue_fix_unavailable', '修复原件尚未进入已发布证据集合。', 409)


async def _release(service, connection, scope_id, release_id):
    kind = await connection.scalar(select(releases.c.kind).where(releases.c.scope_id == scope_id,
        releases.c.release_id == release_id))
    if kind is None:
        raise ManagementError('management_issue_fix_missing', '该组织不存在所选已发布证据集合。', 409)
    release = await service.bases._release(connection, scope_id, release_id, kind)
    for document in release.documents:
        await _document(connection, scope_id, document.reference.document_id, document.reference.revision)
    return release


async def validate_fix_versions(service, connection, scope, basis_id, record, references):
    if not references:
        return
    if len({(ref.asset_type, ref.asset_id) for ref in references}) != len(references):
        raise ManagementError('management_issue_invalid', '同一修复对象只能关联一个精确版本。', 422)
    scope_id = (await service.scopes.require_registered(connection, scope))['id']
    thread_id = await connection.scalar(select(runtime_snapshots.c.thread_id).where(
        runtime_snapshots.c.scope_id == scope_id, runtime_snapshots.c.run_id == record.run_id,
        runtime_snapshots.c.user_id == record.submitted_by))
    if thread_id is None:
        raise ManagementError('management_issue_fix_identity_invalid', '原问题的可信运行身份不可读取。', 409)
    basis, _ = await service._report_binding(connection, run_id=record.run_id, scope=scope,
        user_id=record.submitted_by, thread_id=thread_id,
        basis_id=basis_id, report_id=record.report_id, revision=record.revision)
    original = await basis_version_references(connection, basis)
    fixed_metrics = set()
    policy_metrics = set()
    has_policy = False
    for ref in references:
        if (ref.asset_type, ref.asset_id, ref.revision) in original:
            raise ManagementError('management_issue_fix_unchanged', '原报告已采用该精确版本，不能作为新修复版本。', 409)
        if ref.asset_type == 'metric':
            version = MetricVersionRef(metric_id=ref.asset_id, revision=ref.revision)
            await service.bases.policies._metric_refs(connection, basis.scope_id, (version,))
            fixed_metrics.add(version)
        elif ref.asset_type == 'statistical_policy':
            version = PolicyVersionRef(policy_id=ref.asset_id, revision=ref.revision)
            await require_active(connection, basis.scope_id, ref.asset_type, ref.asset_id, ref.revision)
            policy = await service.bases._policy(connection, basis.scope_id, version)
            policy_metrics.update(await service.bases.policies._metric_graph(connection, basis.scope_id, policy))
            await _release(service, connection, basis.scope_id, policy.evidence_release_id)
            has_policy = True
        elif ref.asset_type == 'document':
            await _document(connection, basis.scope_id, ref.asset_id, ref.revision)
        else:
            await _release(service, connection, basis.scope_id, ref.asset_id)
    if has_policy and not fixed_metrics <= policy_metrics:
        raise ManagementError('management_issue_fix_dependency_mismatch', '所选修复口径未引用所关联的精确修复指标版本。', 409)


async def basis_version_references(connection, basis):
    references = {('metric', ref.metric_id, ref.revision) for ref in basis.metric_versions}
    references.add(('statistical_policy', basis.policy_version.policy_id, basis.policy_version.revision))
    for release_id in (basis.evidence_release_id, basis.background_release_id):
        if release_id is None:
            continue
        references.add(('evidence_release', release_id, None))
        rows = (await connection.execute(select(members.c.document_id, members.c.revision).where(
            members.c.scope_id == basis.scope_id, members.c.release_id == release_id))).all()
        references.update(('document', row.document_id, row.revision) for row in rows)
    return references
