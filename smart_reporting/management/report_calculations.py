"""从可信旧回执重新取数；沿用原依据，查询和CSV写入不占用管理事务。"""

import hashlib

from agno.run import RunContext
from loguru import logger
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..reporting.data_source.starrocks import StarRocksDataSourceAdapter
from ..reporting.models import ReportingError
from ..reporting.semantics.basis import (
    BasisCalculationReceipt,
    BasisRefreshIntent,
    BasisRefreshRevisionReceipt,
)
from ..reporting.semantics.compiler import compile_metric
from ..reporting.semantics.execution import execute_metric
from ..reporting.semantics.models import Identity, RunIdentity
from .business_documents import _digest
from .models import ManagementError
from .repository import report_basis_receipts


async def refresh_calculation(service, run_id, scope, *, user_id, thread_id, parent_report_revision,
    parent_receipt_id, receipt_id, vault, dataset_store, run_context, workflow_scope):
    """同一刷新意图至多发起一次查询；提交丢失先查回执，未登记结果保持未知。"""
    try:
        parent_receipt_id = TypeAdapter(Identity).validate_python(parent_receipt_id)
        receipt_id = TypeAdapter(Identity).validate_python(receipt_id)
        parent_report_revision = TypeAdapter(RunIdentity).validate_python(parent_report_revision)
        report_revision = 'refresh-' + hashlib.sha256(receipt_id.encode()).hexdigest()
        if receipt_id == parent_receipt_id or report_revision == parent_report_revision:
            raise ValueError('刷新目标必须与原回执及修订不同')
    except (ValidationError, ValueError):
        raise ManagementError('management_refresh_invalid', '刷新回执或修订身份无效。', 422) from None
    execution = await service.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
    binding = service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    parent_view = None
    parent_receipts = await service.load_basis_receipts(run_id, scope, user_id=user_id, thread_id=thread_id,
        report_revision=parent_report_revision)
    if any(isinstance(item, BasisRefreshRevisionReceipt) for item in parent_receipts):
        from .report_refresh_revisions import _revision_context

        parent_view, _ = await _revision_context(service, execution, run_id, scope, user_id, thread_id,
            parent_report_revision)
    intent_id = 'refresh-intent-' + hashlib.sha256(receipt_id.encode()).hexdigest()
    async with service.repository.transaction() as connection:
        await service._identity(connection, run_id, scope, user_id, thread_id)
        rows = (await connection.execute(select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == execution.basis.scope_id,
            report_basis_receipts.c.basis_id == execution.basis.id,
            report_basis_receipts.c.receipt_id.in_((parent_receipt_id, receipt_id, intent_id)),
        ))).mappings().all()
        receipts = {row['receipt_id']: service._receipt(row, execution.basis.id) for row in rows}
        parent = receipts.get(parent_receipt_id)
        member = next((item for item in parent_view.calculations if item.receipt_id == parent_receipt_id), None) if parent_view else None
        if (not isinstance(parent, BasisCalculationReceipt)
                or (parent_view is None and parent.report_revision != parent_report_revision)
                or (parent_view is not None and (member is None or member.request != parent.request
                    or member.results != parent.results or member.readiness != parent.readiness))):
            raise ManagementError('management_refresh_parent_missing', '原计算回执不属于指定报告修订。', 404)
        intent = BasisRefreshIntent(receipt_id=intent_id, basis_id=execution.basis.id, report_revision=report_revision,
            target_receipt_id=receipt_id, parent_receipt_id=parent_receipt_id,
            parent_report_revision=parent_report_revision, request=parent.request, created_at=service.scopes.auth.clock())
        previous = receipts.get(intent_id)
        if previous is not None and previous.model_dump(exclude={'created_at'}) != intent.model_dump(exclude={'created_at'}):
            raise ManagementError('management_basis_receipt_conflict', '刷新身份已绑定其他父回执或输入。', 409)
        if receipt_id in receipts and previous is None:
            raise ManagementError('management_basis_receipt_conflict', '目标回执已被其他计算占用。', 409)
        try:
            plan = compile_metric(parent.request, execution.policy, execution.metrics,
                tuple(table for metadata in execution.metadata.values() for table in metadata.tables))
        except ReportingError as error:
            raise ManagementError(error.code, error.message, 422) from error
        body = intent.model_dump(mode='json', by_alias=True)
        inserted = await connection.scalar(insert(report_basis_receipts).values(
            scope_id=execution.basis.scope_id, basis_id=execution.basis.id, receipt_id=intent_id,
            report_revision=report_revision, document=body, content_hash=_digest(body), created_at=intent.created_at,
        ).on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))
        if inserted:
            await service._audit(connection, execution.basis, 'report_data_refresh_requested',
                receiptId=receipt_id, parentReceiptId=parent_receipt_id, reportRevision=report_revision)
    if not inserted:
        # 并发登记或提交响应丢失都只读回耐久事实；不把观察超时当作未执行。
        saved = {item.receipt_id: item for item in await service.load_basis_receipts(run_id, scope,
            user_id=user_id, thread_id=thread_id, report_revision=report_revision)}
        previous = saved.get(intent_id)
        if previous is None or previous.model_dump(exclude={'created_at'}) != intent.model_dump(exclude={'created_at'}):
            raise ManagementError('management_basis_receipt_conflict', '刷新意图与原请求不一致。', 409)
        result = saved.get(receipt_id)
        if result is None:
            raise ManagementError('management_refresh_outcome_unknown', '原刷新已登记，结果尚未确认；请核对原任务，不得自动重新取数。', 409)
        if (not isinstance(result, BasisCalculationReceipt) or result.request != parent.request
                or result.report_revision != report_revision or any(item.calculation_id != receipt_id for item in result.results)
                or (result.datasets and result.workspace != binding)):
            raise ManagementError('management_basis_identity_invalid', '刷新回执身份与原请求不一致。', 409)
        await service._verify_snapshots(result.datasets, dataset_store, binding)
        return result
    # 使用独立会话句柄集合；刷新数据不能替换运行中原报告的探索/恢复句柄。
    tool_context = RunContext(run_id=run_context.run_id, session_id=run_context.session_id, session_state={})
    adapters = {}
    try:
        for source_id in dict.fromkeys(query.source_id for query in (*plan.checks, *plan.queries)):
            allowed = tuple(dict.fromkeys(table for query in (*plan.checks, *plan.queries)
                if query.source_id == source_id for table in query.allowed_tables))
            adapters[source_id] = StarRocksDataSourceAdapter(execution.sources[source_id], allowed_tables=allowed)
        calculated = await execute_metric(plan, adapters, datasets=dataset_store, run_context=tool_context, calculation_id=receipt_id)
        result = await service.append_basis_receipt(run_id, scope, user_id=user_id, thread_id=thread_id,
            receipt_id=receipt_id, report_revision=report_revision, request=parent.request, results=calculated.results,
            readiness=calculated.readiness, dataset_handles=calculated.datasets, dataset_store=dataset_store,
            run_context=tool_context, workflow_scope=workflow_scope)
        logger.info('report_data_refresh_recorded run_id={} receipt_id={}', run_id, receipt_id)
        return result
    finally:
        for adapter in adapters.values():
            await adapter.aclose()


async def load_refresh_planning_context(service, run_id, scope, *, user_id, thread_id,
    parent_report_revision, report_revision, receipt_ids, vault, dataset_store, run_context, workflow_scope):
    """只从管理库及核验后的真实CSV装配新分析，不恢复或修改原会话句柄。"""
    from ..reporting.semantics.planning import build_refreshed_planning_from_parent
    from .report_refresh_revisions import _refresh_receipts, _revision_context, _verify_calculations

    try:
        receipt_ids = TypeAdapter(tuple[Identity, ...]).validate_python(receipt_ids)
        TypeAdapter(RunIdentity).validate_python(parent_report_revision)
        TypeAdapter(RunIdentity).validate_python(report_revision)
        if len(receipt_ids) > 100 or len(set(receipt_ids)) != len(receipt_ids):
            raise ValueError('刷新回执重复或超出问题期间上限')
    except (ValidationError, ValueError):
        raise ManagementError('management_refresh_invalid', '刷新分析身份无效。', 422) from None
    execution = await service.load_execution_context(run_id, scope, user_id=user_id, thread_id=thread_id, vault=vault)
    binding = service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    parent, _ = await _revision_context(service, execution, run_id, scope, user_id, thread_id, parent_report_revision)
    refreshed = await _refresh_receipts(service, execution, run_id, scope, user_id, thread_id, receipt_ids)
    try:
        view = build_refreshed_planning_from_parent(execution, parent, refreshed, report_revision=report_revision)
    except ReportingError as error:
        raise ManagementError(error.code, error.message, 409) from error
    await _verify_calculations(service,
        tuple(item for item in refreshed if isinstance(item, BasisCalculationReceipt)), binding, dataset_store)
    return view
