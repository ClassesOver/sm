"""读取显式新口径并在原报告目录中预检，不读凭据、不执行SQL、不改写依据。"""

import json

from sqlalchemy import and_, func, select

from ..reporting.models import ReportingError
from ..reporting.semantics.compiler import compile_metric
from ..reporting.semantics.models import MetricRequest, PolicyVersionRef, SemanticIssue
from ..reporting.semantics.policy_adoption import (
    PolicyAdoptionChange,
    PolicyAdoptionMetricOption,
    PolicyAdoptionPreview,
)
from .business_documents import _digest
from .catalog import CatalogService
from .models import ManagementError
from .repository import (
    catalog_versions,
    semantic_asset_retirements,
    source_versions,
    statistical_policy_versions,
)
from .semantic_retirements import require_active


async def policy_adoption_options(service, run_id, scope, *, user_id, thread_id, limit=50, after=None):
    """按可信报告场景浏览各口径最新发布版本；候选并非自动采用或可用性批准。"""
    if type(limit) is not int or not 1 <= limit <= 100 or (after is not None and (
            not isinstance(after, str) or not 1 <= len(after) <= 128)):
        raise ManagementError('management_policy_invalid', '口径候选分页参数无效。', 422)
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, run_id, scope, user_id, thread_id)
        row = await service._basis_row(connection, registered['id'], run_id)
        if row is None:
            raise ManagementError('management_basis_not_found', '运行尚未登记计算依据。', 404)
        basis = await service._restore(connection, identity, row)
        versions, retirements = statistical_policy_versions, semantic_asset_retirements
        latest = select(versions.c.policy_id, func.max(versions.c.revision).label('revision')).where(
            versions.c.scope_id == basis.scope_id).group_by(versions.c.policy_id).subquery()
        retired = select(retirements.c.revision).where(retirements.c.scope_id == basis.scope_id,
            retirements.c.asset_type == 'statistical_policy', retirements.c.asset_id == versions.c.policy_id,
            retirements.c.revision == versions.c.revision).exists()
        query = select(versions).join(latest, and_(latest.c.policy_id == versions.c.policy_id,
            latest.c.revision == versions.c.revision)).where(versions.c.scope_id == basis.scope_id,
            versions.c.document['scenario'].as_string() == basis.request_summary.scenario, ~retired,
            ~and_(versions.c.policy_id == basis.policy_version.policy_id,
                versions.c.revision == basis.policy_version.revision))
        if after is not None:
            query = query.where(versions.c.policy_id > after)
        rows = (await connection.execute(query.order_by(versions.c.policy_id).limit(limit + 1))).mappings().all()
        return {'parentBasisId': basis.id, 'items': [{'policyVersion': {'policyId': item['policy_id'],
            'revision': item['revision']}, 'name': item['document']['name']} for item in rows[:limit]],
            'nextCursor': rows[limit - 1]['policy_id'] if len(rows) > limit else None}


async def preview_policy_adoption(service, run_id, scope, *, user_id, thread_id, policy_version):
    selected = PolicyVersionRef.model_validate(policy_version)
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, run_id, scope, user_id, thread_id)
        row = await service._basis_row(connection, registered['id'], run_id)
        if row is None:
            raise ManagementError('management_basis_not_found', '运行尚未登记计算依据。', 404)
        basis = await service._restore(connection, identity, row)
        return await _preview(service, connection, basis, row, selected)


def _change_description(policy, field):
    value = getattr(policy, field)
    if field == 'metric_versions':
        return '、'.join(f'{ref.metric_id} v{ref.revision}' for ref in value)
    if field == 'filters':
        operators = {'eq': '等于', 'ne': '不等于', 'lt': '小于', 'le': '小于等于',
            'gt': '大于', 'ge': '大于等于', 'in': '属于', 'is_null': '为空'}
        return '；'.join(f'{item.field_ref} {operators[item.operator]} '
            + '、'.join(json.dumps(part, ensure_ascii=False) for part in item.model_dump(mode='json')['values'])
            for item in value) or '无附加过滤条件'
    if field == 'joins':
        return '；'.join('、'.join(f'{left} = {right}' for left, right in zip(item.left_keys, item.right_keys))
            + '（多对一；输出粒度：' + '、'.join(item.output_grain) + '）' for item in value) or '无关联规则'
    if field == 'readiness_policy':
        return json.dumps(value.model_dump(mode='json', by_alias=True), ensure_ascii=False, sort_keys=True)
    return str(value) if value is not None and value != '' else '未设置'


async def _preview(service, connection, basis, row, selected):
    if selected == basis.policy_version:
        raise ManagementError('management_policy_unchanged', '所选口径与原报告相同，请使用原口径刷新。', 409)
    target = await service._policy(connection, basis.scope_id, selected)
    if target.scenario != basis.request_summary.scenario:
        raise ManagementError('management_policy_scenario_mismatch', '新口径与原报告场景不一致，请重新确认报告请求。', 422)
    await require_active(connection, basis.scope_id, 'statistical_policy', selected.policy_id, selected.revision)
    graph = await service.policies._metric_graph(connection, basis.scope_id, target)
    await service._release(connection, basis.scope_id, target.evidence_release_id, 'rule_evidence')
    original = await service._policy(connection, basis.scope_id, basis.policy_version)
    metadata = await _catalog_metadata(connection, basis)
    tables = tuple(table for model in metadata.values() for table in model.tables)
    issues = []
    periods = (basis.request_summary.period,) + ((basis.request_summary.comparison_period,)
        if basis.request_summary.comparison_period is not None else ())
    for period in periods:
        for ref in target.metric_versions:
            try:
                plan = compile_metric(MetricRequest(metric_version=ref, basis_id=basis.id, period=period),
                    target, tuple(graph.values()), tuple(tables))
                issues.extend(plan.issues)
            except ReportingError as error:
                if error.code != 'metric_field_denied':
                    raise
                issues.append(SemanticIssue(code=error.code, object_id=f'{ref.metric_id}:{ref.revision}',
                    message='新指标引用的字段不在原报告目录中，预检不会扩大访问范围。', impact='unavailable'))
    changed_fields = tuple(name for name in ('name', 'metric_versions', 'filters', 'joins', 'valid_from',
        'valid_to', 'evidence_release_id', 'readiness_policy', 'decision_notes')
        if getattr(original, name) != getattr(target, name))
    before, after = set(basis.metric_versions), set(graph)
    def order(ref):
        return ref.metric_id, ref.revision
    return PolicyAdoptionPreview(parent_basis_id=basis.id, parent_basis_hash=row['content_hash'],
        original_policy_version=basis.policy_version, target_policy_version=selected,
        target_policy_hash=_digest(target.model_dump(mode='json', by_alias=True)),
        questions=basis.request_summary.questions,
        metric_options=tuple(PolicyAdoptionMetricOption(metric_version=ref, name=graph[ref].name,
            unit=graph[ref].unit) for ref in target.metric_versions),
        source_versions=basis.source_versions, catalog_refs=basis.catalog_refs,
        metric_versions_added=tuple(sorted(after - before, key=order)),
        metric_versions_removed=tuple(sorted(before - after, key=order)), changed_fields=changed_fields,
        changes=tuple(PolicyAdoptionChange(field=field, before=_change_description(original, field),
            after=_change_description(target, field)) for field in changed_fields),
        issues=tuple({(issue.code, issue.object_id, issue.message, issue.impact): issue
            for issue in issues}.values()))


async def _catalog_metadata(connection, basis):
    metadata = {}
    source_revisions = {ref.source_id: ref.revision for ref in basis.source_versions}
    for ref in basis.catalog_refs:
        catalog = await connection.scalar(select(catalog_versions.c.catalog).where(
            catalog_versions.c.scope_id == basis.scope_id, catalog_versions.c.source_id == ref.source_id,
            catalog_versions.c.revision == ref.revision))
        database = await connection.scalar(select(source_versions.c.database).where(
            source_versions.c.scope_id == basis.scope_id, source_versions.c.source_id == ref.source_id,
            source_versions.c.revision == source_revisions[ref.source_id]))
        metadata[ref.source_id] = CatalogService.validate_snapshot(catalog, ref.source_id, database)
    return metadata


async def register_policy_adoption(service, run_id, scope, *, user_id, thread_id, confirmation, build_identity):
    """确认后原子登记独立依据与父链；不执行取数，也不改写原运行。"""
    from uuid import NAMESPACE_URL, uuid5

    from pydantic import ValidationError
    from sqlalchemy import insert

    from ..reporting.semantics.basis import BasisExecutionContext
    from ..reporting.semantics.models import BuildIdentity, ReportBasis
    from ..reporting.semantics.policy_adoption import (
        BasisPolicyAdoptionReceipt,
        PolicyAdoptionConfirmation,
        policy_adoption_id,
    )
    from ..reporting.semantics.selection import select_metric_candidates
    from ..reporting.trace.contracts_v1 import canonical_sha256
    from .repository import report_bases, report_basis_receipts, runtime_snapshots

    try:
        request = PolicyAdoptionConfirmation.model_validate(confirmation)
        build = BuildIdentity.model_validate(build_identity)
    except ValidationError:
        raise ManagementError('management_adoption_invalid', '确认须包含精确目标、预检摘要及完整问题选择。', 422) from None
    input_hash = canonical_sha256({'confirmation': request.model_dump(mode='json', by_alias=True),
        'buildIdentity': build.model_dump(mode='json', by_alias=True)})
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, run_id, scope, user_id, thread_id)
        # 同一原运行的确认登记串行提交；锁内无业务查询、模型或凭据操作。
        await connection.execute(select(runtime_snapshots.c.run_id).where(
            runtime_snapshots.c.scope_id == registered['id'], runtime_snapshots.c.run_id == run_id).with_for_update())
        row = await service._basis_row(connection, registered['id'], run_id)
        if row is None:
            raise ManagementError('management_basis_not_found', '运行尚未登记计算依据。', 404)
        basis = await service._restore(connection, identity, row)
        target_run_id = policy_adoption_id(basis.id, request.request_id)
        receipt_id = target_run_id
        receipt = await _read_registered_adoption(service, connection, basis, row, scope,
            user_id, thread_id, target_run_id)
        if receipt is not None:
            if receipt.input_hash != input_hash or receipt.confirmation != request:
                raise ManagementError('management_adoption_conflict', '同一确认请求已登记其他输入，请读取原结果。', 409)
            return receipt
        preview = await _preview(service, connection, basis, row, request.target_policy_version)
        if preview.digest() != request.preview_hash:
            raise ManagementError('management_adoption_preview_changed', '新口径预检已变化，请重新核对后确认。', 409)
        question_ids = tuple(question.id for question in basis.request_summary.questions)
        choices = {choice.question_id: choice for choice in request.question_choices}
        if len(choices) != len(request.question_choices) or set(choices) != set(question_ids):
            raise ManagementError('management_adoption_questions_invalid', '每个原报告问题须有且只有一项显式选择。', 422)
        policy = await service._policy(connection, basis.scope_id, request.target_policy_version)
        if any(choice.metric_version is not None and choice.metric_version not in policy.metric_versions
                for choice in choices.values()):
            raise ManagementError('management_adoption_questions_invalid', '问题只能选择目标口径的精确指标版本。', 422)
        graph = await service.policies._metric_graph(connection, basis.scope_id, policy)
        now = service.scopes.auth.clock()
        adopted = ReportBasis.model_validate({**basis.model_dump(),
            'id': str(uuid5(NAMESPACE_URL, f'report-basis:{basis.scope_id}:{target_run_id}')),
            'run_id': target_run_id, 'policy_version': request.target_policy_version,
            'metric_versions': tuple(sorted(graph, key=lambda ref: (ref.metric_id, ref.revision))),
            'evidence_release_id': policy.evidence_release_id, 'build_identity': build,
            'knowledge_as_of': basis.knowledge_as_of if any(item.field == 'knowledgeAsOf' and item.source == 'explicit'
                for item in basis.request_summary.assumptions) else now, 'registered_at': now, 'reproducible_until': None, 'status': 'registered'})
        execution = BasisExecutionContext(adopted, policy, tuple(graph.values()), {},
            await _catalog_metadata(connection, basis))
        selections = tuple(select_metric_candidates(question_id, execution,
            explicit=choices[question_id].metric_version) for question_id in question_ids)
        body = adopted.model_dump(mode='json', by_alias=True)
        digest = _digest(body)
        reference = service._reference(adopted, digest)
        receipt = BasisPolicyAdoptionReceipt(receipt_id=receipt_id, basis_id=adopted.id,
            target_run_id=target_run_id, target_basis_hash=digest, parent_run_id=run_id,
            parent_basis_id=basis.id, parent_basis_hash=row['content_hash'], input_hash=input_hash,
            confirmation=request, preview=preview, selections=selections, created_at=now)
        await connection.execute(insert(runtime_snapshots).values(scope_id=basis.scope_id, run_id=target_run_id,
            user_id=user_id, thread_id=thread_id, entrypoint=identity['entrypoint'],
            references=reference, reference_hash=_digest(reference), created_at=now))
        await connection.execute(insert(report_bases).values(scope_id=basis.scope_id, run_id=target_run_id,
            basis_id=adopted.id, policy_id=policy.id, policy_revision=policy.revision,
            evidence_release_id=adopted.evidence_release_id, background_release_id=adopted.background_release_id,
            document=body, content_hash=digest, registered_at=now))
        receipt_body = receipt.model_dump(mode='json', by_alias=True)
        await connection.execute(insert(report_basis_receipts).values(scope_id=basis.scope_id, basis_id=adopted.id,
            receipt_id=receipt.receipt_id, report_revision=receipt.report_revision, document=receipt_body,
            content_hash=_digest(receipt_body), created_at=now))
        await service._audit(connection, adopted, 'report_policy_adoption_registered', parentRunId=run_id,
            parentBasisId=basis.id, requestId=request.request_id, receiptId=receipt.receipt_id)
        return receipt


async def _read_registered_adoption(service, connection, parent, parent_row, scope, user_id, thread_id, target_run_id):
    from ..reporting.semantics.policy_adoption import BasisPolicyAdoptionReceipt
    from ..reporting.trace.contracts_v1 import canonical_sha256
    from .repository import report_basis_receipts

    row = await service._basis_row(connection, parent.scope_id, target_run_id)
    if row is None:
        return None
    _, identity = await service._identity(connection, target_run_id, scope, user_id, thread_id)
    adopted = await service._restore(connection, identity, row)
    stored = (await connection.execute(select(report_basis_receipts).where(
        report_basis_receipts.c.scope_id == parent.scope_id, report_basis_receipts.c.basis_id == adopted.id,
        report_basis_receipts.c.receipt_id == target_run_id))).mappings().one_or_none()
    if stored is None:
        raise ManagementError('management_basis_identity_invalid', '新依据缺少确认父链回执。', 409)
    receipt = service._receipt(stored, adopted.id)
    if not isinstance(receipt, BasisPolicyAdoptionReceipt):
        raise ManagementError('management_basis_identity_invalid', '新依据确认回执类型无效。', 409)
    if (receipt.parent_run_id, receipt.parent_basis_id, receipt.parent_basis_hash,
        receipt.target_run_id, receipt.target_basis_hash) != (
            parent.run_id, parent.id, parent_row['content_hash'], target_run_id, row['content_hash']) or (
            receipt.preview.target_policy_version != adopted.policy_version
            or receipt.preview.source_versions != adopted.source_versions
            or receipt.preview.catalog_refs != adopted.catalog_refs
            or receipt.input_hash != canonical_sha256({
                'confirmation': receipt.confirmation.model_dump(mode='json', by_alias=True),
                'buildIdentity': adopted.build_identity.model_dump(mode='json', by_alias=True)})):
        raise ManagementError('management_basis_identity_invalid', '新依据确认父链身份不一致。', 409)
    return receipt


async def read_policy_adoption(service, run_id, scope, *, user_id, thread_id, request_id):
    """未知响应只读恢复；不存在返回None，不创建新运行、依据或确认意图。"""
    from pydantic import TypeAdapter, ValidationError

    from ..reporting.semantics.policy_adoption import PolicyAdoptionRequestId, policy_adoption_id

    try:
        request_id = TypeAdapter(PolicyAdoptionRequestId).validate_python(request_id)
    except ValidationError:
        raise ManagementError('management_adoption_invalid', '确认请求身份无效。', 422) from None
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, run_id, scope, user_id, thread_id)
        row = await service._basis_row(connection, registered['id'], run_id)
        if row is None:
            raise ManagementError('management_basis_not_found', '运行尚未登记计算依据。', 404)
        basis = await service._restore(connection, identity, row)
        return await _read_registered_adoption(service, connection, basis, row, scope,
            user_id, thread_id, policy_adoption_id(basis.id, request_id))


async def register_adoption_selections(service, run_id, scope, *, user_id, thread_id, request_id):
    """从确认回执登记新运行初始选择，不重新召回候选或借用旧计算。"""
    from sqlalchemy import insert

    from ..reporting.semantics.basis import BasisSelectionReceipt
    from .repository import report_basis_receipts, runtime_snapshots

    adoption = await read_policy_adoption(service, run_id, scope, user_id=user_id, thread_id=thread_id,
        request_id=request_id)
    if adoption is None:
        raise ManagementError('management_adoption_missing', '尚未登记此新口径确认。', 404)
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, adoption.target_run_id, scope, user_id, thread_id)
        await connection.execute(select(runtime_snapshots.c.run_id).where(
            runtime_snapshots.c.scope_id == registered['id'], runtime_snapshots.c.run_id == adoption.target_run_id).with_for_update())
        row = await service._basis_row(connection, registered['id'], adoption.target_run_id)
        basis = await service._restore(connection, identity, row)
        if basis.id != adoption.basis_id or row['content_hash'] != adoption.target_basis_hash:
            raise ManagementError('management_basis_identity_invalid', '新口径选择与确认依据不一致。', 409)
        existing = (await connection.execute(select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == basis.scope_id, report_basis_receipts.c.basis_id == basis.id,
            report_basis_receipts.c.receipt_id == 'initial-metric-selection'))).mappings().one_or_none()
        if existing is not None:
            stored = service._receipt(existing, basis.id)
            if not isinstance(stored, BasisSelectionReceipt) or stored.report_revision != 'initial' or stored.selections != adoption.selections:
                raise ManagementError('management_adoption_conflict', '新运行已登记其他初始选择。', 409)
            return stored
        receipt = BasisSelectionReceipt(receipt_id='initial-metric-selection', basis_id=basis.id,
            report_revision='initial', selections=adoption.selections, created_at=service.scopes.auth.clock())
        body = receipt.model_dump(mode='json', by_alias=True)
        await connection.execute(insert(report_basis_receipts).values(scope_id=basis.scope_id, basis_id=basis.id,
            receipt_id=receipt.receipt_id, report_revision='initial', document=body, content_hash=_digest(body),
            created_at=receipt.created_at))
        await service._audit(connection, basis, 'report_adoption_selection_registered',
            parentBasisId=adoption.parent_basis_id, adoptionReceiptId=adoption.receipt_id)
        return receipt
