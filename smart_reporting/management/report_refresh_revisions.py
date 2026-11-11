"""在既有不可变回执表登记分析修订；不把分析清单冒充已生成的报告。"""

from hashlib import sha256

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..reporting.models import ReportingError
from ..reporting.semantics.basis import (
    BasisCalculationReceipt,
    BasisKnowledgeReceipt,
    BasisRefreshRevisionIntent,
    BasisRefreshRevisionReceipt,
)
from ..reporting.semantics.models import Identity, RunIdentity
from ..reporting.semantics.planning import (
    build_metric_planning_context,
    build_refreshed_planning_from_parent,
)
from .business_documents import _digest
from .models import ManagementError
from .repository import report_basis_receipts


def revision_receipt_id(revision):
    return 'refresh-revision-' + sha256(revision.encode()).hexdigest()


async def _lock_revision(connection, basis_id, revision):
    key = int.from_bytes(sha256(f'report-refresh:{basis_id}:{revision}'.encode()).digest()[:8], signed=True)
    await connection.execute(select(func.pg_advisory_xact_lock(key)))


async def _refresh_receipts(service, execution, run_id, scope, user_id, thread_id, receipt_ids):
    keys = tuple(key for receipt_id in receipt_ids for key in (
        receipt_id, 'refresh-intent-' + sha256(receipt_id.encode()).hexdigest()))
    async with service.repository.transaction() as connection:
        await service._identity(connection, run_id, scope, user_id, thread_id)
        rows = (await connection.execute(select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == execution.basis.scope_id,
            report_basis_receipts.c.basis_id == execution.basis.id,
            report_basis_receipts.c.receipt_id.in_(keys),
        ))).mappings().all()
        if {row['receipt_id'] for row in rows} != set(keys):
            raise ManagementError('management_refresh_outcome_unknown', '指定刷新意图或结果尚未登记，不能生成新分析。', 409)
        return tuple(service._receipt(row, execution.basis.id) for row in rows)


async def _revision_context(service, execution, run_id, scope, user_id, thread_id, report_revision):
    """逐个读取可达父清单；核验历史身份，历史CSV过期不阻止采用新的取数结果。"""
    manifests, visited = [], set()
    current = report_revision
    while True:
        if current in visited:
            raise ManagementError('management_basis_identity_invalid', '分析修订父链存在循环。', 409)
        visited.add(current)
        receipts = await service.load_basis_receipts(run_id, scope, user_id=user_id, thread_id=thread_id,
            report_revision=current)
        manifests_here = tuple(item for item in receipts if isinstance(item, BasisRefreshRevisionReceipt))
        if not manifests_here:
            if any(isinstance(item, BasisRefreshRevisionIntent) for item in receipts):
                raise ManagementError('management_refresh_outcome_unknown', '整批刷新尚未登记完整结果。', 409)
            try:
                view = build_metric_planning_context(execution, receipts, report_revision=current)
            except ReportingError as error:
                raise ManagementError(error.code, error.message, 409) from error
            calculations = tuple(item for item in receipts if isinstance(item, BasisCalculationReceipt))
            break
        if (len(manifests_here) != 1 or manifests_here[0].receipt_id != revision_receipt_id(current)
                or any(not isinstance(item, (BasisRefreshRevisionReceipt, BasisKnowledgeReceipt, BasisRefreshRevisionIntent)) for item in receipts)):
            raise ManagementError('management_basis_identity_invalid', '分析修订清单身份不一致。', 409)
        batch = next((item for item in receipts if isinstance(item, BasisRefreshRevisionIntent)), None)
        if batch and (batch.parent_report_revision != manifests_here[0].parent_report_revision
                or batch.calculation_receipt_ids != manifests_here[0].calculation_receipt_ids):
            raise ManagementError('management_basis_identity_invalid', '整批刷新意图与分析清单不一致。', 409)
        manifests.append((manifests_here[0], batch))
        current = manifests_here[0].parent_report_revision
    for manifest, batch in reversed(manifests):
        if batch and (batch.parent_planning_hash != _digest(view.model_dump(mode='json', by_alias=True))
                or batch.parent_calculation_receipt_ids != tuple(item.receipt_id for item in view.calculations)):
            raise ManagementError('management_basis_identity_invalid', '整批刷新意图与父分析不一致。', 409)
        refreshed = await _refresh_receipts(service, execution, run_id, scope, user_id, thread_id,
            manifest.calculation_receipt_ids)
        try:
            view = build_refreshed_planning_from_parent(execution, view, refreshed,
                report_revision=manifest.report_revision)
        except ReportingError as error:
            raise ManagementError(error.code, error.message, 409) from error
        if (_digest(view.model_dump(mode='json', by_alias=True)) != manifest.planning_hash
                or tuple(item.receipt_id for item in view.calculations) != manifest.calculation_receipt_ids):
            raise ManagementError('management_basis_identity_invalid', '分析修订清单与实际计算不一致。', 409)
        by_id = {item.receipt_id: item for item in refreshed if isinstance(item, BasisCalculationReceipt)}
        calculations = tuple(by_id[item.receipt_id] for item in view.calculations)
    return view, calculations


async def _verify_calculations(service, calculations, binding, dataset_store):
    for receipt in calculations:
        if receipt.datasets and receipt.workspace != binding:
            raise ManagementError('management_basis_identity_invalid', '刷新CSV不属于当前报告工作区。', 409)
        await service._verify_snapshots(receipt.datasets, dataset_store, binding)


async def _verified_revision_inputs(service, run_id, scope, *, user_id, thread_id, report_revision,
    vault, dataset_store, run_context, workflow_scope):
    try:
        TypeAdapter(RunIdentity).validate_python(report_revision)
    except ValidationError:
        raise ManagementError('management_refresh_invalid', '分析修订身份无效。', 422) from None
    execution = await service.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
    binding = service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    view, calculations = await _revision_context(service, execution, run_id, scope, user_id, thread_id, report_revision)
    await _verify_calculations(service, calculations, binding, dataset_store)
    return view, calculations


async def load_revision_planning_context(service, run_id, scope, **options):
    view, _ = await _verified_revision_inputs(service, run_id, scope, **options)
    return view


async def load_registered_revision_planning_context(service, run_id, scope, *, user_id, thread_id,
    report_revision, vault):
    """只恢复历史登记身份供计划承接，不代表历史CSV当前可复现或可再次用于分析。"""
    TypeAdapter(RunIdentity).validate_python(report_revision)
    execution = await service.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
    view, _ = await _revision_context(service, execution, run_id, scope, user_id, thread_id, report_revision)
    return view


async def load_revision_dataset_handles(service, run_id, scope, **options):
    _, calculations = await _verified_revision_inputs(service, run_id, scope, **options)
    snapshots = {}
    for receipt in calculations:
        for snapshot in receipt.datasets:
            previous = snapshots.get(snapshot.dataset.dataset_id)
            if previous is not None and previous != snapshot:
                raise ManagementError('management_basis_identity_invalid', '分析修订中的数据集身份冲突。', 409)
            snapshots[snapshot.dataset.dataset_id] = snapshot
    return tuple(item.to_handle() for item in snapshots.values())


async def register_refresh_revision(service, run_id, scope, *, user_id, thread_id, parent_report_revision,
    report_revision, receipt_ids, vault, dataset_store, run_context, workflow_scope):
    try:
        TypeAdapter(RunIdentity).validate_python(parent_report_revision)
        TypeAdapter(RunIdentity).validate_python(report_revision)
        receipt_ids = TypeAdapter(tuple[Identity, ...]).validate_python(receipt_ids)
        if len(receipt_ids) > 100 or len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError('刷新计算身份重复或过多')
    except (ValidationError, ValueError):
        raise ManagementError('management_refresh_invalid', '分析修订身份无效。', 422) from None
    service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    previous = await service.load_basis_receipts(run_id, scope, user_id=user_id, thread_id=thread_id,
        report_revision=report_revision)
    saved = next((item for item in previous if item.receipt_id == revision_receipt_id(report_revision)), None)
    batch = next((item for item in previous if isinstance(item, BasisRefreshRevisionIntent)), None)
    if batch and (batch.parent_report_revision != parent_report_revision
            or set(batch.calculation_receipt_ids) != set(receipt_ids)):
        raise ManagementError('management_basis_receipt_conflict', '分析清单不得改变整批刷新意图。', 409)
    if saved is not None:
        if (not isinstance(saved, BasisRefreshRevisionReceipt) or saved.parent_report_revision != parent_report_revision
                or set(saved.calculation_receipt_ids) != set(receipt_ids)):
            raise ManagementError('management_basis_receipt_conflict', '该修订已登记其他父修订或计算。', 409)
        # 只读回不可变登记事实；当前可复现性仍由load_revision_planning_context逐次核验CSV。
        return saved
    view = await service.load_refresh_planning_context(run_id, scope, user_id=user_id, thread_id=thread_id,
        parent_report_revision=parent_report_revision, report_revision=report_revision, receipt_ids=receipt_ids,
        vault=vault, dataset_store=dataset_store, run_context=run_context, workflow_scope=workflow_scope)
    receipt = BasisRefreshRevisionReceipt(receiptId=revision_receipt_id(report_revision), basisId=view.basis_id,
        reportRevision=report_revision, parentReportRevision=parent_report_revision,
        calculationReceiptIds=tuple(item.receipt_id for item in view.calculations),
        planningHash=_digest(view.model_dump(mode='json', by_alias=True)), createdAt=service.scopes.auth.clock())
    async with service.repository.transaction() as connection:
        registered, identity = await service._identity(connection, run_id, scope, user_id, thread_id)
        row = await service._basis_row(connection, registered['id'], run_id)
        if row is None:
            raise ManagementError('management_basis_not_found', '运行尚未登记计算依据。', 404)
        basis = await service._restore(connection, identity, row)
        if basis.id != receipt.basis_id:
            raise ManagementError('management_basis_identity_invalid', '分析期间计算依据发生变化。', 409)
        await _lock_revision(connection, basis.id, report_revision)
        # 新修订不能占用旧计算/选择所属的修订标签。
        existing = (await connection.execute(select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == basis.scope_id,
            report_basis_receipts.c.basis_id == basis.id,
            report_basis_receipts.c.report_revision == report_revision,
        ))).mappings().all()
        if any(item['receipt_id'] != receipt.receipt_id
                and not isinstance(service._receipt(item, basis.id), (BasisKnowledgeReceipt, BasisRefreshRevisionIntent)) for item in existing):
            raise ManagementError('management_basis_receipt_conflict', '该修订标识已被其他回执使用。', 409)
        batch = next((service._receipt(item, basis.id) for item in existing
            if item['document'].get('kind') == 'metric_refresh_revision_intent'), None)
        if batch and (batch.parent_report_revision != parent_report_revision
                or batch.calculation_receipt_ids != receipt.calculation_receipt_ids):
            raise ManagementError('management_basis_receipt_conflict', '并发登记不得改变整批刷新意图。', 409)
        body = receipt.model_dump(mode='json', by_alias=True)
        claimed = await connection.scalar(insert(report_basis_receipts).values(scope_id=basis.scope_id,
            basis_id=basis.id, receipt_id=receipt.receipt_id, report_revision=report_revision,
            document=body, content_hash=_digest(body), created_at=receipt.created_at,
        ).on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))
        if not claimed:
            saved_row = (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == basis.scope_id,
                report_basis_receipts.c.basis_id == basis.id,
                report_basis_receipts.c.receipt_id == receipt.receipt_id,
            ))).mappings().one()
            saved = service._receipt(saved_row, basis.id)
            if saved.model_dump(exclude={'created_at'}) != receipt.model_dump(exclude={'created_at'}):
                raise ManagementError('management_basis_receipt_conflict', '该修订已登记其他父修订或计算。', 409)
            return saved
        await service._audit(connection, basis, 'report_refresh_revision_registered',
            receiptId=receipt.receipt_id, reportRevision=report_revision, parentReportRevision=parent_report_revision,
            calculationReceiptIds=list(receipt.calculation_receipt_ids))
        return receipt


async def refresh_revision(service, run_id, scope, *, user_id, thread_id, parent_report_revision,
    report_revision, vault, dataset_store, run_context, workflow_scope):
    """整批父计算串行刷新；已完成项只读回，未知项停止，不改原报告会话。"""
    try:
        TypeAdapter(RunIdentity).validate_python(parent_report_revision)
        TypeAdapter(RunIdentity).validate_python(report_revision)
        if parent_report_revision == report_revision:
            raise ValueError('目标必须是新修订')
    except (ValidationError, ValueError):
        raise ManagementError('management_refresh_invalid', '整批刷新修订身份无效。', 422) from None
    execution = await service.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
    service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    parent, _ = await _revision_context(service, execution, run_id, scope, user_id, thread_id, parent_report_revision)
    parent_ids = tuple(item.receipt_id for item in parent.calculations)
    if not parent_ids:
        raise ManagementError('management_refresh_invalid', '父修订没有已登记计算可刷新。', 422)
    target_ids = tuple('refresh-calc-' + _digest({'runId': run_id, 'target': report_revision, 'parent': parent_report_revision,
            'parentReceiptId': receipt_id}) for receipt_id in parent_ids)
    intent = BasisRefreshRevisionIntent(receiptId='refresh-revision-intent-' + sha256(report_revision.encode()).hexdigest(),
        basisId=execution.basis.id, reportRevision=report_revision, parentReportRevision=parent_report_revision,
        parentCalculationReceiptIds=parent_ids, calculationReceiptIds=target_ids,
        parentPlanningHash=_digest(parent.model_dump(mode='json', by_alias=True)), createdAt=service.scopes.auth.clock())
    # 在同一管理事务中争用目标修订并写入审计；事务外才允许执行业务查询。
    async with service.repository.transaction() as connection:
        await service._identity(connection, run_id, scope, user_id, thread_id)
        await _lock_revision(connection, execution.basis.id, report_revision)
        rows = (await connection.execute(select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == execution.basis.scope_id,
            report_basis_receipts.c.basis_id == execution.basis.id,
            report_basis_receipts.c.report_revision == report_revision,
        ))).mappings().all()
        existing = tuple(service._receipt(row, execution.basis.id) for row in rows)
        previous = next((item for item in existing if item.receipt_id == intent.receipt_id), None)
        if previous is None and any(not isinstance(item, BasisKnowledgeReceipt) for item in existing):
            raise ManagementError('management_basis_receipt_conflict', '目标修订已被其他分析占用。', 409)
        if previous is not None and previous.model_dump(exclude={'created_at'}) != intent.model_dump(exclude={'created_at'}):
            raise ManagementError('management_basis_receipt_conflict', '目标修订已绑定其他父分析或计算。', 409)
        body = intent.model_dump(mode='json', by_alias=True)
        claimed = await connection.scalar(insert(report_basis_receipts).values(
            scope_id=execution.basis.scope_id, basis_id=execution.basis.id, receipt_id=intent.receipt_id,
            report_revision=report_revision, document=body, content_hash=_digest(body), created_at=intent.created_at,
        ).on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))
        if not claimed:
            row = (await connection.execute(select(report_basis_receipts).where(
                report_basis_receipts.c.scope_id == execution.basis.scope_id,
                report_basis_receipts.c.basis_id == execution.basis.id,
                report_basis_receipts.c.receipt_id == intent.receipt_id,
            ))).mappings().one()
            saved = service._receipt(row, execution.basis.id)
            if saved.model_dump(exclude={'created_at'}) != intent.model_dump(exclude={'created_at'}):
                raise ManagementError('management_basis_receipt_conflict', '并发刷新已绑定其他父分析。', 409)
        else:
            await service._audit(connection, execution.basis, 'report_revision_refresh_requested',
                receiptId=intent.receipt_id, reportRevision=report_revision,
                parentReportRevision=parent_report_revision, calculationReceiptIds=list(target_ids))
    common = dict(user_id=user_id, thread_id=thread_id, vault=vault, dataset_store=dataset_store,
        run_context=run_context, workflow_scope=workflow_scope)
    for parent_id, target_id in zip(parent_ids, target_ids, strict=True):
        await service.refresh_calculation(run_id, scope, **common, parent_report_revision=parent_report_revision,
            parent_receipt_id=parent_id, receipt_id=target_id)
    return await service.register_refresh_revision(run_id, scope, **common,
        parent_report_revision=parent_report_revision, report_revision=report_revision, receipt_ids=target_ids)
