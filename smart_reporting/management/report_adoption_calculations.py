"""按新依据确认选择正式取数；耐久意图阻止未知结果被自动重查。"""

from hashlib import sha256

from agno.run import RunContext
from loguru import logger
from sqlalchemy.dialects.postgresql import insert

from ..reporting.data_source.starrocks import StarRocksDataSourceAdapter
from ..reporting.models import ReportingError
from ..reporting.semantics.basis import (
    BasisAdoptionCalculationIntent,
    BasisCalculationReceipt,
    BasisSelectionReceipt,
)
from ..reporting.semantics.compiler import compile_metric
from ..reporting.semantics.execution import execute_metric
from ..reporting.semantics.models import MetricRequest
from ..reporting.semantics.policy_adoption import BasisPolicyAdoptionReceipt
from ..reporting.trace.contracts_v1 import canonical_sha256
from .business_documents import _digest
from .models import ManagementError
from .repository import report_basis_receipts


async def calculate_adoption_metrics(service, run_id, scope, *, user_id, thread_id,
    vault, dataset_store, run_context, workflow_scope):
    """只计算确认的新指标及原请求期间；不接受调用方另传表、指标或SQL。"""
    identity = dict(user_id=user_id, thread_id=thread_id)
    registrations = await service.load_basis_receipts(run_id, scope, **identity,
        report_revision='policy-adoption-registration')
    if len(registrations) != 1 or not isinstance(registrations[0], BasisPolicyAdoptionReceipt):
        raise ManagementError('management_adoption_missing', '新运行缺少明确的新口径确认。', 409)
    adoption = registrations[0]
    trusted = await service.read_policy_adoption(adoption.parent_run_id, scope, **identity,
        request_id=adoption.confirmation.request_id)
    if trusted != adoption or adoption.target_run_id != run_id:
        raise ManagementError('management_basis_identity_invalid', '新口径确认父链不一致。', 409)
    execution = await service.load_execution_context(run_id, scope, **identity, vault=vault)
    binding = service._workspace_binding(run_id, scope, user_id, thread_id, dataset_store, run_context, workflow_scope)
    receipts = await service.load_basis_receipts(run_id, scope, **identity, report_revision='initial')
    selections = [item for item in receipts if isinstance(item, BasisSelectionReceipt)]
    if (len(selections) != 1 or selections[0].receipt_id != 'initial-metric-selection'
            or selections[0].selections != adoption.selections):
        raise ManagementError('management_adoption_conflict', '初始选择与明确确认不一致。', 409)
    selection = selections[0]
    selected = tuple(dict.fromkeys(item.selected for item in selection.selections if item.status == 'resolved'))
    periods = tuple(dict.fromkeys(period for period in (execution.basis.request_summary.period,
        execution.basis.request_summary.comparison_period) if period is not None))
    catalog = tuple(table for metadata in execution.metadata.values() for table in metadata.tables)
    results = []
    for metric in selected:
        for period in periods:
            request = MetricRequest(metric_version=metric, basis_id=execution.basis.id, period=period)
            target = 'initial-' + sha256(request.model_dump_json().encode()).hexdigest()
            intent = BasisAdoptionCalculationIntent(
                receipt_id='adoption-intent-' + sha256(target.encode()).hexdigest(),
                basis_id=execution.basis.id, target_receipt_id=target, request=request, workspace=binding,
                adoption_sha256=canonical_sha256(adoption.model_dump(mode='json', by_alias=True)),
                selection_sha256=canonical_sha256(selection.model_dump(mode='json', by_alias=True)),
                created_at=service.scopes.auth.clock())
            try:
                plan = compile_metric(request, execution.policy, execution.metrics, catalog)
            except ReportingError as error:
                raise ManagementError(error.code, error.message, 422) from error
            async with service.repository.transaction() as connection:
                await service._identity(connection, run_id, scope, user_id, thread_id)
                body = intent.model_dump(mode='json', by_alias=True)
                inserted = await connection.scalar(insert(report_basis_receipts).values(
                    scope_id=execution.basis.scope_id, basis_id=execution.basis.id,
                    receipt_id=intent.receipt_id, report_revision='initial', document=body,
                    content_hash=_digest(body), created_at=intent.created_at,
                ).on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))
                if inserted:
                    await service._audit(connection, execution.basis, 'report_adoption_calculation_requested',
                        receiptId=target, adoptionReceiptId=adoption.receipt_id)
            if not inserted:
                saved = {item.receipt_id: item for item in await service.load_basis_receipts(
                    run_id, scope, **identity, report_revision='initial')}
                previous = saved.get(intent.receipt_id)
                if previous is None or previous.model_dump(exclude={'created_at'}) != intent.model_dump(exclude={'created_at'}):
                    raise ManagementError('management_adoption_conflict', '新口径计算意图与原输入不一致。', 409)
                stored = saved.get(target)
                if stored is None:
                    raise ManagementError('management_adoption_outcome_unknown',
                        '新口径取数已登记，结果尚未确认；请核对原任务，不得自动重新取数。', 409)
                if (not isinstance(stored, BasisCalculationReceipt) or stored.request != request
                        or (stored.datasets and stored.workspace != binding)
                        or any(item.calculation_id != target for item in stored.results)):
                    raise ManagementError('management_basis_identity_invalid', '新口径计算结果身份不一致。', 409)
                await service._verify_snapshots(stored.datasets, dataset_store, binding)
                results.append(stored)
                continue
            tool_context = RunContext(run_id=run_id, session_id=binding.workspace_key, session_state={})
            adapters = {}
            try:
                for source_id in dict.fromkeys(query.source_id for query in (*plan.checks, *plan.queries)):
                    allowed = tuple(dict.fromkeys(table for query in (*plan.checks, *plan.queries)
                        if query.source_id == source_id for table in query.allowed_tables))
                    adapters[source_id] = StarRocksDataSourceAdapter(execution.sources[source_id], allowed_tables=allowed)
                calculated = await execute_metric(plan, adapters, datasets=dataset_store,
                    run_context=tool_context, calculation_id=target)
                stored = await service.append_basis_receipt(run_id, scope, **identity,
                    receipt_id=target, report_revision='initial', request=request, results=calculated.results,
                    readiness=calculated.readiness, dataset_handles=calculated.datasets, dataset_store=dataset_store,
                    run_context=tool_context, workflow_scope=workflow_scope)
                results.append(stored)
                logger.info('report_adoption_calculation_recorded run_id={} receipt_id={}', run_id, target)
            finally:
                for adapter in adapters.values():
                    await adapter.aclose()
    return tuple(results)
