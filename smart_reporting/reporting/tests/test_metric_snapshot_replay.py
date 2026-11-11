"""回归复算只读已登记CSV；真实合成SQL/独立预期，不访问业务库。"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from smart_reporting.reporting.tests.test_metric_compilation import (
    catalog,
    definitions,
    policy,
    request,
)
from smart_reporting.reporting.tests.test_metric_compilation import warehouse as warehouse
from smart_reporting.reporting.tests.test_metric_execution import (
    execution_context as execution_context,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def calculated(execution_context):
    from smart_reporting.reporting.semantics.basis import (
        BasisCalculationReceipt,
        BasisDatasetSnapshot,
        BasisWorkspaceBinding,
    )
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric

    adapters, store, context = execution_context
    plan = compile_metric(request('rate'), policy('rate'), definitions(), catalog())
    result = await execute_metric(plan, adapters, datasets=store, run_context=context, calculation_id='calculation-1')
    identity = store.service.registry.get(context.session_id)
    binding = BasisWorkspaceBinding(workspace_key=identity.workspace_key, session_id=identity.workflow_session_id,
        scope_fingerprint=identity.scope_fingerprint)
    receipt = BasisCalculationReceipt(receipt_id='calculation-receipt', basis_id=plan.request.basis_id,
        report_revision='initial', request=plan.request, results=result.results, readiness=result.readiness,
        datasets=tuple(BasisDatasetSnapshot.from_handle(handle) for handle in result.datasets), workspace=binding,
        created_at=datetime.now(UTC))
    return plan, receipt


async def test_native_replay_uses_only_frozen_csv_and_matches_independent_ratio(execution_context, warehouse, monkeypatch):
    from smart_reporting.reporting.semantics.snapshot_replay import replay_metric_calculation

    adapters, store, context = execution_context
    plan, receipt = await calculated(execution_context)
    warehouse.execute('UPDATE test.actual SET amount=1')

    async def no_materialize(*args, **kwargs):
        pytest.fail('快照回归不得查询数据库或生成新数据集')

    monkeypatch.setattr(store, 'materialize_batch', no_materialize)
    for source in adapters.values():
        monkeypatch.setattr(source, 'materialize_bound', no_materialize)
    replayed = await replay_metric_calculation(plan, receipt, {key: item.config for key, item in adapters.items()},
        datasets=store, run_context=context)
    assert replayed.results == receipt.results
    rate = next(item for item in replayed.results if item.metric_version.metric_id == 'rate')
    assert rate.value == Decimal(190) / Decimal(300) * 100
    assert rate.value.quantize(Decimal('.01')) == Decimal('63.33')
    assert rate.value != Decimal(70)
    assert replayed.datasets == tuple(item.to_handle() for item in receipt.datasets)


@pytest.mark.parametrize('mutation', ['value', 'fact', 'query', 'workspace', 'bytes', 'extra'])
async def test_replay_rejects_forged_fact_query_workspace_or_changed_csv(execution_context, mutation):
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.snapshot_replay import replay_metric_calculation

    adapters, store, context = execution_context
    plan, receipt = await calculated(execution_context)
    if mutation in ('value', 'fact'):
        results = list(receipt.results)
        results[-1] = results[-1].model_copy(update={'value': Decimal(70)} if mutation == 'value' else {'fact_id': 'forged-fact'})
        receipt = receipt.model_copy(update={'results': tuple(results)})
    elif mutation == 'query':
        snapshots = list(receipt.datasets)
        snapshots[0] = snapshots[0].model_copy(update={'dataset': snapshots[0].dataset.model_copy(update={'requirement_id': 'foreign-query'})})
        receipt = receipt.model_copy(update={'datasets': tuple(snapshots)})
    elif mutation == 'workspace':
        receipt = receipt.model_copy(update={'workspace': receipt.workspace.model_copy(update={'scope_fingerprint': '0' * 64})})
    elif mutation == 'bytes':
        await store.service.awrite_bytes(context.session_id, receipt.datasets[0].file.path, b'value\nforged\n',
            overwrite=True, expected_sha256=receipt.datasets[0].file.sha256)
    else:
        snapshot = receipt.datasets[0]
        extra = snapshot.model_copy(update={'dataset': snapshot.dataset.model_copy(update={'dataset_id': 'extra', 'requirement_id': 'extra-query'})})
        receipt = receipt.model_copy(update={'datasets': (*receipt.datasets, extra)})
    with pytest.raises(ReportingError):
        await replay_metric_calculation(plan, receipt, {key: item.config for key, item in adapters.items()},
            datasets=store, run_context=context)
