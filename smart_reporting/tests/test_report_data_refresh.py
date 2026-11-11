"""固定原依据的重新取数：真实隔离PG回执与SQLite参数查询，不代替StarRocks验收。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from smart_reporting.management.models import ManagementError
from smart_reporting.management.report_bases import ReportBasisService
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.semantics.models import MetricRequest, MetricResult
from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    receipt_snapshot as receipt_snapshot,
)
from smart_reporting.tests.test_report_basis_persistence import (
    register_basis,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def refresh_context(basis_context, receipt_snapshot, monkeypatch, request):
    fixture_options = getattr(request, 'param', False)
    comparison = fixture_options is True
    outputs = fixture_options.get('outputs') if isinstance(fixture_options, dict) else None
    if comparison or outputs:
        from smart_reporting.tests.test_report_basis_persistence import (
            build_identity,
            request_summary,
        )
        basis = await ReportBasisService(basis_context['scopes']).register_report_basis(
            'run-basis', basis_context['scope'], user_id='7', thread_id='thread-basis',
            request_summary=request_summary(basis_context['scope_id'], **(
                {'comparisonPeriod': {'start': '2026-10-01', 'end': '2026-11-01'}} if comparison
                else {'requestedOutputs': outputs, **(
                    {'domains': fixture_options['domains']} if 'domains' in fixture_options else {})})),
            build_identity=build_identity())
    else:
        basis = await register_basis(basis_context)
    service = ReportBasisService(basis_context['scopes'])
    request = MetricRequest(metricVersion={'metricId': 'budget', 'revision': 1}, basisId=basis.id,
        period=basis.request_summary.period)
    original = await service.append_basis_receipt('run-basis', basis_context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='original-receipt', report_revision='initial', request=request,
        results=(MetricResult(metricVersion=request.metric_version, basisId=basis.id, calculationId='initial-calculation',
            factId='original-fact', period=request.period, value=Decimal(300), unit='CNY', status='computed',
            datasetIds=('dataset-budget01',)),), **receipt_snapshot[0])
    if comparison:
        baseline_request = request.model_copy(update={'period': basis.request_summary.comparison_period})
        baseline_result = original.results[0].model_copy(update={'period': baseline_request.period,
            'calculation_id': 'initial-baseline', 'fact_id': 'original-baseline'})
        await service.append_basis_receipt('run-basis', basis_context['scope'], user_id='7', thread_id='thread-basis',
            receipt_id='original-baseline', report_revision='initial', request=baseline_request,
            results=(baseline_result,), **receipt_snapshot[0])
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS test")
        connection.exec_driver_sql('CREATE TABLE test.budget(project_id TEXT, amount INTEGER, period DATE)')
        connection.exec_driver_sql("INSERT INTO test.budget VALUES ('A',100,'2026-11-02'),('B',200,'2026-11-20')")
    if comparison:
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO test.budget VALUES ('A',150,'2026-10-10')")
    queries = []

    @event.listens_for(engine, 'before_cursor_execute')
    def record(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            queries.append((statement, parameters))

    class Connection:
        def __enter__(self):
            self.connection = engine.connect()
            return self
        def __exit__(self, *_args):
            self.connection.close()
        def execute(self, statement, parameters=None):
            if str(statement).startswith('SET query_timeout'):
                return None
            return self.connection.execute(statement, parameters)
        def execution_options(self, **kwargs):
            self.connection = self.connection.execution_options(**kwargs)
            return self

    def init(adapter, config, *, allowed_tables):
        adapter.config, adapter.allowed_tables = config, tuple(allowed_tables)
        adapter._engine = SimpleNamespace(connect=Connection, dispose=lambda: None)

    monkeypatch.setattr(StarRocksDataSourceAdapter, '__init__', init)
    options = dict(user_id='7', thread_id='thread-basis', parent_report_revision='initial',
        parent_receipt_id=original.receipt_id, receipt_id='refresh-calculation-2',
        vault=basis_context['vault'], dataset_store=receipt_snapshot[0]['dataset_store'],
        run_context=receipt_snapshot[0]['run_context'], workflow_scope=receipt_snapshot[0]['workflow_scope'])
    try:
        yield service, basis_context, original, engine, queries, options
    finally:
        engine.dispose()


@pytest.mark.parametrize('factor', [1, 2])
async def test_refresh_uses_frozen_rules_but_new_dataset_and_fact_even_for_equal_value(refresh_context, factor):
    service, context, original, engine, queries, options = refresh_context
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE test.budget SET amount=amount*?', (factor,))
    refreshed = await service.refresh_calculation('run-basis', context['scope'], **options)
    assert refreshed.request == original.request
    assert refreshed.basis_id == original.basis_id
    assert refreshed.report_revision != original.report_revision
    assert refreshed.results[0].value == Decimal(300 * factor)
    assert refreshed.results[0].calculation_id == options['receipt_id']
    assert refreshed.results[0].fact_id != original.results[0].fact_id
    assert refreshed.results[0].dataset_ids != original.results[0].dataset_ids
    assert len(queries) == 1
    assert '2026-11' not in queries[0][0]  # 日期仍通过原生参数传递。
    assert await service.refresh_calculation('run-basis', context['scope'], **options) == refreshed
    assert len(queries) == 1
    assert await service.load_basis_receipts('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        report_revision='initial') == (original,)
    assert original.datasets[0].file.path != refreshed.datasets[0].file.path
    old, _ = await options['dataset_store'].service.afile_bytes(options['run_context'].session_id,
        original.datasets[0].file.path)
    assert b'300.00' in old


@pytest.mark.parametrize('fault', ['user', 'organization', 'parent', 'parent_revision', 'overwrite'])
async def test_refresh_rejects_foreign_or_overwriting_identity_before_business_query(refresh_context, fault):
    service, context, _, _, queries, options = refresh_context
    scope = context['scope']
    if fault == 'user':
        options = {**options, 'user_id': 'foreign'}
    elif fault == 'organization':
        scope = context['other_scope']
    elif fault == 'parent':
        options = {**options, 'parent_receipt_id': 'missing-parent'}
    elif fault == 'parent_revision':
        options = {**options, 'parent_report_revision': 'foreign-revision'}
    else:
        options = {**options, 'receipt_id': 'original-receipt'}
    with pytest.raises(ManagementError):
        await service.refresh_calculation('run-basis', scope, **options)
    assert queries == []


@pytest.mark.parametrize('stage', ['before_commit', 'after_commit'])
async def test_refresh_never_requeries_when_result_commit_is_unknown(refresh_context, monkeypatch, stage):
    service, context, _, _, queries, options = refresh_context
    append = service.append_basis_receipt

    async def lose_response(*args, **kwargs):
        if stage == 'after_commit':
            await append(*args, **kwargs)
        raise OSError('receipt response unavailable')

    monkeypatch.setattr(service, 'append_basis_receipt', lose_response)
    with pytest.raises(OSError):
        await service.refresh_calculation('run-basis', context['scope'], **options)
    assert len(queries) == 1
    monkeypatch.setattr(service, 'append_basis_receipt', append)
    if stage == 'before_commit':
        with pytest.raises(ManagementError, match='management_refresh_outcome_unknown'):
            await service.refresh_calculation('run-basis', context['scope'], **options)
    else:
        recovered = await service.refresh_calculation('run-basis', context['scope'], **options)
        assert recovered.results[0].value == Decimal(300)
    assert len(queries) == 1


async def test_concurrent_refresh_claims_one_intent_and_does_not_duplicate_query(refresh_context, monkeypatch):
    import asyncio

    service, context, _, _, queries, options = refresh_context
    started, release = asyncio.Event(), asyncio.Event()
    materialize = StarRocksDataSourceAdapter.materialize_bound

    async def pause(adapter, *args, **kwargs):
        started.set()
        await release.wait()
        return await materialize(adapter, *args, **kwargs)

    monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', pause)
    first = asyncio.create_task(service.refresh_calculation('run-basis', context['scope'], **options))
    try:
        await asyncio.wait_for(started.wait(), 10)
        with pytest.raises(ManagementError, match='management_refresh_outcome_unknown'):
            await service.refresh_calculation('run-basis', context['scope'], **options)
        assert queries == []
    finally:
        release.set()
        result = await first
    assert len(queries) == 1
    assert await service.refresh_calculation('run-basis', context['scope'], **options) == result
    assert len(queries) == 1


async def test_refresh_does_not_replace_original_session_handles_or_accept_damaged_readback(refresh_context):
    service, context, original, _, queries, options = refresh_context
    import copy

    options['run_context'].session_state['original-only'] = ['frozen-handle']
    before = copy.deepcopy(options['run_context'].session_state)
    result = await service.refresh_calculation('run-basis', context['scope'], **options)
    assert options['run_context'].session_state == before
    assert original.datasets[0].to_handle().dataset_id not in result.results[0].dataset_ids
    snapshot = result.datasets[0]
    await options['dataset_store'].service.awrite_bytes(options['run_context'].session_id, snapshot.file.path,
        b'changed-result', overwrite=True)
    with pytest.raises(ManagementError, match='management_basis_snapshot_unavailable'):
        await service.refresh_calculation('run-basis', context['scope'], **options)
    assert len(queries) == 1


async def test_refresh_missing_data_remains_unavailable_instead_of_becoming_zero(refresh_context):
    service, context, original, engine, queries, options = refresh_context
    with engine.begin() as connection:
        connection.exec_driver_sql('DELETE FROM test.budget')
    refreshed = await service.refresh_calculation('run-basis', context['scope'], **options)
    value = refreshed.results[0]
    assert value.value is None and value.status == 'unavailable'
    assert 'missing_data' in value.issue_codes
    assert value.calculation_id != original.results[0].calculation_id
    assert original.results[0].value == Decimal(300)
    assert len(queries) == 1


async def test_refresh_id_cannot_be_rebound_to_equal_request_from_another_parent_receipt(refresh_context):
    service, context, original, _, queries, options = refresh_context
    refreshed = await service.refresh_calculation('run-basis', context['scope'], **options)
    await service.append_basis_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='another-parent', report_revision='initial', request=original.request, results=original.results,
        dataset_handles=tuple(item.to_handle() for item in original.datasets), dataset_store=options['dataset_store'],
        run_context=options['run_context'], workflow_scope=options['workflow_scope'])
    with pytest.raises(ManagementError, match='management_basis_receipt_conflict'):
        await service.refresh_calculation('run-basis', context['scope'], **{**options, 'parent_receipt_id': 'another-parent'})
    assert len(queries) == 1
    assert await service.refresh_calculation('run-basis', context['scope'], **options) == refreshed


async def test_refresh_audit_failure_rolls_back_intent_before_query(refresh_context, monkeypatch):
    service, context, _, _, queries, options = refresh_context
    audit = service._audit

    async def unavailable(*args, **kwargs):
        raise OSError('audit unavailable')

    monkeypatch.setattr(service, '_audit', unavailable)
    with pytest.raises(OSError):
        await service.refresh_calculation('run-basis', context['scope'], **options)
    assert queries == []
    monkeypatch.setattr(service, '_audit', audit)
    result = await service.refresh_calculation('run-basis', context['scope'], **options)
    assert result.results[0].value == Decimal(300)
    assert len(queries) == 1


async def test_two_equal_refreshes_keep_same_csv_hash_but_distinct_fact_and_batch_identity(refresh_context):
    service, context, _, _, queries, options = refresh_context
    first = await service.refresh_calculation('run-basis', context['scope'], **options)
    second = await service.refresh_calculation('run-basis', context['scope'], **{**options,
        'parent_report_revision': first.report_revision, 'parent_receipt_id': first.receipt_id,
        'receipt_id': 'refresh-calculation-3'})
    assert first.request == second.request
    assert first.results[0].value == second.results[0].value == Decimal(300)
    assert first.datasets[0].file.sha256 == second.datasets[0].file.sha256
    assert first.datasets[0].file.path != second.datasets[0].file.path
    assert first.results[0].fact_id != second.results[0].fact_id
    assert first.results[0].dataset_ids != second.results[0].dataset_ids
    assert first.report_revision != second.report_revision
    assert len(queries) == 2


async def test_refresh_enters_native_facts_and_tables_from_durable_receipts(refresh_context):
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.semantics.tables import build_registered_result_tables
    from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs

    service, context, original, engine, queries, options = refresh_context
    await service.append_selection_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='initial-metric-selection', report_revision='initial', vault=context['vault'],
        requests=({'questionId': 'q-rate', 'explicit': original.request.metric_version.model_dump()},))
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE test.budget SET amount=amount*2')
    refreshed = await service.refresh_calculation('run-basis', context['scope'], **options)
    # 重建服务，读取PG及实际CSV，不能依赖调用方持有的结果对象或旧会话句柄。
    recovered = ReportBasisService(context['scopes'])
    view = await recovered.load_refresh_planning_context('run-basis', context['scope'],
        user_id='7', thread_id='thread-basis', parent_report_revision='initial', report_revision='revision-2',
        receipt_ids=(refreshed.receipt_id,), vault=context['vault'], dataset_store=options['dataset_store'],
        run_context=options['run_context'], workflow_scope=options['workflow_scope'])
    analysis, _, _ = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, (), report_revision='revision-2')
    tables = build_registered_result_tables(bundle, fact_file_resource_id='trf-' + 'b' * 20)
    assert bundle.metric_context.calculations[0].results == refreshed.results
    assert '| 600 |' in tables[0][1]
    ref = tables[0][0].cells[0].fact_refs[0]
    assert ref.fact_key == refreshed.results[0].fact_id
    assert ref.fact_key != original.results[0].fact_id
    assert ref.json_pointer == '/metricContext/calculations/0/results/0'
    assert len(queries) == 1
    await options['dataset_store'].service.awrite_bytes(options['run_context'].session_id,
        refreshed.datasets[0].file.path, b'changed after refresh', overwrite=True)
    with pytest.raises(ManagementError, match='management_basis_snapshot_unavailable'):
        await recovered.load_refresh_planning_context('run-basis', context['scope'],
            user_id='7', thread_id='thread-basis', parent_report_revision='initial', report_revision='revision-2',
            receipt_ids=(refreshed.receipt_id,), vault=context['vault'], dataset_store=options['dataset_store'],
            run_context=options['run_context'], workflow_scope=options['workflow_scope'])
    assert len(queries) == 1


@pytest.mark.parametrize('fault', ['extra_missing_id', 'wrong_user', 'wrong_workspace'])
async def test_refresh_planning_read_rejects_foreign_or_unresolved_identity(refresh_context, fault):
    service, context, _, _, queries, options = refresh_context
    refreshed = await service.refresh_calculation('run-basis', context['scope'], **options)
    kwargs = dict(user_id='7', thread_id='thread-basis', parent_report_revision='initial', report_revision='revision-2',
        receipt_ids=(refreshed.receipt_id,), vault=context['vault'], dataset_store=options['dataset_store'],
        run_context=options['run_context'], workflow_scope=options['workflow_scope'])
    await service.append_selection_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='initial-metric-selection', report_revision='initial', vault=context['vault'],
        requests=({'questionId': 'q-rate', 'explicit': refreshed.request.metric_version.model_dump()},))
    if fault == 'extra_missing_id':
        kwargs['receipt_ids'] += ('not-registered',)
    elif fault == 'wrong_user':
        kwargs['user_id'] = 'other'
    else:
        from agno.run import RunContext
        kwargs['run_context'] = RunContext(run_id='foreign', session_id='foreign', session_state={})
    with pytest.raises(ManagementError):
        await service.load_refresh_planning_context('run-basis', context['scope'], **kwargs)
    assert len(queries) == 1


async def selected_refresh(refresh_context):
    service, context, original, _, _, options = refresh_context
    await service.append_selection_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='initial-metric-selection', report_revision='initial', vault=context['vault'],
        requests=({'questionId': 'q-rate', 'explicit': original.request.metric_version.model_dump()},))
    fresh = await service.refresh_calculation('run-basis', context['scope'], **options)
    common = dict(user_id='7', thread_id='thread-basis', vault=context['vault'],
        dataset_store=options['dataset_store'], run_context=options['run_context'], workflow_scope=options['workflow_scope'])
    return fresh, common


async def test_refresh_revision_manifest_survives_reconstruction_and_continuous_refresh(refresh_context):
    service, context, original, engine, queries, options = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    saved = await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    rebuilt = ReportBasisService(context['scopes'])
    view = await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='revision-2')
    assert view.report_revision == 'revision-2'
    assert view.calculations[0].receipt_id == fresh.receipt_id
    assert view.calculations[0].results == fresh.results
    assert saved.calculation_receipt_ids == (fresh.receipt_id,)
    assert await rebuilt.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,)) == saved
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE test.budget SET amount=amount*2')
    second = await rebuilt.refresh_calculation('run-basis', context['scope'], **{
        **options, 'parent_report_revision': 'revision-2', 'parent_receipt_id': fresh.receipt_id,
        'receipt_id': 'refresh-calculation-3'})
    next_saved = await rebuilt.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='revision-2', report_revision='revision-3', receipt_ids=(second.receipt_id,))
    assert next_saved.parent_report_revision == 'revision-2'
    third_service = ReportBasisService(context['scopes'])
    final = await third_service.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='revision-3')
    assert final.calculations[0].results[0].value == Decimal(600)
    assert final.calculations[0].results[0].fact_id != original.results[0].fact_id
    assert len(queries) == 2
    # 旧修订恢复仍选原批次，不随新数据或后续登记漂移。
    assert await third_service.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='revision-2') == view
    initial = await third_service.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='initial')
    assert initial.calculations[0].results == original.results


async def test_refresh_revision_cannot_rebind_or_overwrite_old_revision(refresh_context):
    service, context, _, _, queries, options = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    another = await service.refresh_calculation('run-basis', context['scope'], **{
        **options, 'receipt_id': 'another-refresh'})
    with pytest.raises(ManagementError, match='management_basis_receipt_conflict'):
        await service.register_refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='revision-2', receipt_ids=(another.receipt_id,))
    with pytest.raises(ManagementError):
        await service.register_refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='initial', receipt_ids=(fresh.receipt_id,))
    assert len(queries) == 2


async def test_refresh_revision_concurrent_registration_is_single_immutable_choice(refresh_context):
    import asyncio

    service, context, _, _, queries, options = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    another = await service.refresh_calculation('run-basis', context['scope'], **{**options, 'receipt_id': 'competing-refresh'})
    async def register(receipt_id):
        try:
            return await service.register_refresh_revision('run-basis', context['scope'], **common,
                parent_report_revision='initial', report_revision='revision-2', receipt_ids=(receipt_id,))
        except ManagementError as error:
            return error
    outcomes = await asyncio.gather(register(fresh.receipt_id), register(another.receipt_id))
    successes = [item for item in outcomes if not isinstance(item, ManagementError)]
    assert len(successes) == 1
    assert [item.code for item in outcomes if isinstance(item, ManagementError)] == ['management_basis_receipt_conflict']
    view = await service.load_revision_planning_context('run-basis', context['scope'], **common, report_revision='revision-2')
    assert tuple(item.receipt_id for item in view.calculations) == successes[0].calculation_receipt_ids
    assert len(queries) == 2


@pytest.mark.parametrize('fault', ['hash', 'cycle'])
async def test_refresh_revision_restore_rejects_damaged_manifest(refresh_context, monkeypatch, fault):
    service, context, _, _, queries, _ = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    saved = await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    read = service.load_basis_receipts
    async def damaged(*args, **kwargs):
        receipts = await read(*args, **kwargs)
        if kwargs['report_revision'] == 'revision-2':
            mutation = {'planning_hash': '0' * 64} if fault == 'hash' else {'parent_report_revision': 'revision-2'}
            return tuple(saved.model_copy(update=mutation) if item.receipt_id == saved.receipt_id else item for item in receipts)
        return receipts
    monkeypatch.setattr(service, 'load_basis_receipts', damaged)
    with pytest.raises(ManagementError, match='management_basis_identity_invalid'):
        await service.load_revision_planning_context('run-basis', context['scope'], **common, report_revision='revision-2')
    assert len(queries) == 1


async def test_refresh_revision_audit_rollback_and_lost_response_readback(refresh_context, monkeypatch):
    from smart_reporting.management.report_refresh_revisions import register_refresh_revision

    service, context, _, _, queries, _ = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    audit = service._audit
    async def unavailable(*args, **kwargs):
        raise OSError('audit not committed')
    monkeypatch.setattr(service, '_audit', unavailable)
    kwargs = dict(**common, parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    with pytest.raises(OSError):
        await service.register_refresh_revision('run-basis', context['scope'], **kwargs)
    assert await service.load_basis_receipts('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        report_revision='revision-2') == ()
    monkeypatch.setattr(service, '_audit', audit)
    async def lost_response(*args, **kwargs):
        await register_refresh_revision(service, *args, **kwargs)
        raise OSError('committed response lost')
    monkeypatch.setattr(service, 'register_refresh_revision', lost_response)
    with pytest.raises(OSError):
        await service.register_refresh_revision('run-basis', context['scope'], **kwargs)
    rebuilt = ReportBasisService(context['scopes'])
    saved = await rebuilt.register_refresh_revision('run-basis', context['scope'], **kwargs)
    assert saved.calculation_receipt_ids == (fresh.receipt_id,)
    assert len(queries) == 1


async def test_refresh_revision_does_not_require_expired_ancestor_csv_but_checks_own(refresh_context):
    service, context, original, _, queries, options = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    await options['dataset_store'].service.awrite_bytes(options['run_context'].session_id,
        original.datasets[0].file.path, b'expired ancestor', overwrite=True)
    second = await service.refresh_calculation('run-basis', context['scope'], **{
        **options, 'parent_report_revision': 'revision-2', 'parent_receipt_id': fresh.receipt_id,
        'receipt_id': 'next-after-expiry'})
    await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='revision-2', report_revision='revision-3', receipt_ids=(second.receipt_id,))
    rebuilt = ReportBasisService(context['scopes'])
    view = await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common, report_revision='revision-3')
    assert view.calculations[0].results == second.results
    with pytest.raises(ManagementError, match='management_basis_snapshot_unavailable'):
        await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common, report_revision='initial')
    assert len(queries) == 2


async def test_refresh_revision_replay_keeps_later_knowledge_receipt_and_database_immutability(refresh_context):
    from sqlalchemy import select, update
    from sqlalchemy.exc import DBAPIError

    from smart_reporting.management.repository import report_basis_receipts
    from smart_reporting.reporting.business_knowledge.retrieval import ReportEvidenceSearchReceipt

    service, context, _, _, queries, _ = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    kwargs = dict(**common, parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    saved = await service.register_refresh_revision('run-basis', context['scope'], **kwargs)
    async def missing_background(*args, **kwargs):
        return ReportEvidenceSearchReceipt(basisId=fresh.basis_id, kind='background', issueCodes=('background_not_bound',))
    knowledge = await service.append_knowledge_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='revision-2-background', report_revision='revision-2', section_code='budget', kind='background',
        query='预算背景', evidence_service=SimpleNamespace(search_report=missing_background))
    assert await service.register_refresh_revision('run-basis', context['scope'], **kwargs) == saved
    receipts = await service.load_basis_receipts('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        report_revision='revision-2')
    assert knowledge in receipts
    for statement in (
        update(report_basis_receipts).where(report_basis_receipts.c.receipt_id == saved.receipt_id).values(content_hash='0' * 64),
        report_basis_receipts.delete().where(report_basis_receipts.c.receipt_id == saved.receipt_id),
    ):
        with pytest.raises(DBAPIError):
            async with service.repository.engine.begin() as connection:
                await connection.execute(statement)
    async with service.repository.transaction() as connection:
        assert await connection.scalar(select(report_basis_receipts.c.content_hash).where(
            report_basis_receipts.c.receipt_id == saved.receipt_id)) != '0' * 64
    assert len(queries) == 1


async def test_committed_revision_readback_does_not_claim_expired_csv_is_currently_verified(refresh_context):
    service, context, _, _, queries, options = refresh_context
    fresh, common = await selected_refresh(refresh_context)
    kwargs = dict(**common, parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    saved = await service.register_refresh_revision('run-basis', context['scope'], **kwargs)
    await options['dataset_store'].service.awrite_bytes(options['run_context'].session_id,
        fresh.datasets[0].file.path, b'expired latest snapshot', overwrite=True)
    rebuilt = ReportBasisService(context['scopes'])
    assert await rebuilt.register_refresh_revision('run-basis', context['scope'], **kwargs) == saved
    with pytest.raises(ManagementError, match='management_basis_snapshot_unavailable'):
        await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common, report_revision='revision-2')
    assert len(queries) == 1


async def test_native_fact_writer_uses_registered_revision_and_preserves_original_checkpoint(refresh_context):
    import asyncio
    import csv
    import hashlib
    import json
    import os
    from copy import deepcopy

    from smart_reporting.reporting.hospital_operation.detailed_analysis import (
        DatasetAnalysisContext,
        DetailedAnalysisPlan,
    )
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.state import ReportingRunState
    from smart_reporting.runtime.database import create_agent_database

    service, context, original, engine, queries, options = refresh_context
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE test.budget SET amount=amount*2')
    fresh, common = await selected_refresh(refresh_context)
    await service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='revision-2', receipt_ids=(fresh.receipt_id,))
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = context['provider']
    runtime.report_basis_service = ReportBasisService(context['scopes'])
    runtime.datasets = options['dataset_store']
    runtime.workspace_service = runtime.datasets.service
    runtime._scope = lambda _: options['workflow_scope'].as_state()
    runtime._durable_command_lock = asyncio.Lock()
    run_context = options['run_context']
    run_context.session_state['metricReportRevision'] = 'forged-session-revision'
    # 批次选择只来自服务端调用参数及可信回执，不采用会话里自报的修订。
    initial = await runtime._metric_planning_context(run_context)
    new = await runtime._metric_planning_context(run_context, report_revision='revision-2')
    assert initial.calculations[0].results == original.results
    assert new.calculations[0].results == fresh.results
    before_session = deepcopy(run_context.session_state)
    handles = await runtime._registered_metric_dataset_handles(run_context, report_revision='revision-2')
    assert tuple(item.dataset_id for item in handles) == tuple(item.dataset.dataset_id for item in fresh.datasets)
    assert run_context.session_state == before_session
    profile_path = 'profiles/revision-generation-fixture.json'
    await runtime.workspace_service.awrite_bytes(run_context.session_id, profile_path, b'{}')
    all_handles = (original.datasets[0].to_handle(), *handles)
    contexts = []
    for handle in all_handles:
        content, _ = await runtime.workspace_service.afile_bytes(run_context.session_id, handle.path)
        fields = tuple(next(csv.reader(content.decode().splitlines())))
        contexts.append(DatasetAnalysisContext(datasetId=handle.dataset_id, path=handle.path, size=handle.size,
            sha256=handle.sha256, rowCount=handle.row_count, columnCount=len(fields),
            profileFile={'path': profile_path, 'size': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()},
            profileModelView={}, profileEngineVersion='explicit-test-fixture', fields=fields,
            numericFields=fields, periodValues=()).model_dump(mode='json', by_alias=True))
    run_context.session_state['report_analysis_data_context'] = contexts
    analysis, _, _ = analysis_inputs()
    def plan(selected):
        ids = tuple(item.dataset_id for item in selected)
        return DetailedAnalysisPlan(analyses=(analysis.model_copy(update={'dataset_ids': ids}),), datasetIds=ids)
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    runtime.state_repository = ReportingStateRepository(database.async_db)
    try:
        await runtime.state_repository.initialize()
        await runtime.state_repository.create(ReportingRunState.initial(report_run_id='run-basis',
            external_run_id='external-basis', thread_id='thread-basis', owner_user_id='7',
            payload={'workflowCheckpoint': {'owner': 'original-running-report'}}))
        old_files = await runtime._prepare_deterministic_analysis_facts(run_context=run_context,
            thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
            detailed_plan=plan(all_handles[:1]), dataset_handles=all_handles[:1])
        old_identity = old_files[analysis.analysis_id]
        old_bytes, _ = await runtime.workspace_service.afile_bytes(run_context.session_id, old_identity.path)
        before = await runtime.state_repository.get('run-basis')
        new_files = await runtime._prepare_deterministic_analysis_facts(run_context=run_context,
            thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
            detailed_plan=plan(handles), dataset_handles=handles, metric_report_revision='revision-2')
        new_identity = new_files[analysis.analysis_id]
        assert old_identity.path != new_identity.path
        assert hashlib.sha256(b'revision-2').hexdigest() in new_identity.path
        raw, _ = await runtime.workspace_service.afile_bytes(run_context.session_id, new_identity.path)
        assert json.loads(raw)['metricContext']['calculations'][0]['results'][0] == fresh.results[0].model_dump(mode='json', by_alias=True)
        assert json.loads(raw)['metricContext']['reportRevision'] == 'revision-2'
        assert (await runtime.workspace_service.afile_bytes(run_context.session_id, old_identity.path))[0] == old_bytes
        graph_identity, citations = await runtime._prepare_registered_revision_findings(
            run_context=run_context, thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
            report_revision='revision-2', fact_files=new_files)
        from smart_reporting.reporting.hospital_operation.findings import FindingGraph
        graph = await runtime._read_identity_model(run_context.session_id, graph_identity, FindingGraph)
        assert graph.findings[0].fact_refs == (fresh.results[0].fact_id,)
        assert graph.findings[0].citation_ids == (citations[0].citation_id,)
        assert citations[0].dataset_id == handles[0].dataset_id
        assert citations[0].snapshot_hash == handles[0].sha256
        assert graph.question_coverage[0].status == 'partial'
        assert await runtime._prepare_registered_revision_findings(
            run_context=run_context, thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
            report_revision='revision-2', fact_files=new_files) == (graph_identity, citations)
        with pytest.raises(ReportingError, match='发现来源与本报告登记计算上下文不一致'):
            await runtime._prepare_registered_revision_findings(
                run_context=run_context, thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
                report_revision='revision-2', fact_files=old_files)
        after = await runtime.state_repository.get('run-basis')
        assert after.revision == before.revision and after.phase == before.phase
        assert after.payload['workflowCheckpoint'] == before.payload['workflowCheckpoint']
        assert new_identity.model_dump(mode='json', by_alias=True) in after.payload['artifacts']
        with pytest.raises(ReportingError):
            await runtime._metric_planning_context(run_context, report_revision='not-registered')
        await runtime.workspace_service.awrite_bytes(run_context.session_id, handles[0].path,
            b'changed before narrative generation', overwrite=True)
        with pytest.raises(ReportingError, match='management_basis_snapshot_unavailable'):
            await runtime._registered_metric_dataset_handles(run_context, report_revision='revision-2')
        with pytest.raises(ReportingError, match='management_basis_snapshot_unavailable'):
            await runtime._prepare_registered_revision_findings(
                run_context=run_context, thread_id=run_context.session_id, report_run_id='run-basis', revision=1,
                report_revision='revision-2', fact_files=new_files)
        assert (await runtime.state_repository.get('run-basis')).payload == after.payload
        assert len(queries) == 1
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def batch_options(refresh_context):
    service, context, original, _, _, options = refresh_context
    await service.append_selection_receipt('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='initial-metric-selection', report_revision='initial', vault=context['vault'],
        requests=({'questionId': 'q-rate', 'explicit': original.request.metric_version.model_dump()},))
    return {key: options[key] for key in ('user_id', 'thread_id', 'vault', 'dataset_store', 'run_context', 'workflow_scope')}


async def test_batch_refresh_claims_input_before_sql_and_restores_without_requery(refresh_context):
    from copy import deepcopy

    service, context, original, _, queries, options = refresh_context
    common = await batch_options(refresh_context)
    before = deepcopy(options['run_context'].session_state)
    saved = await service.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2')
    assert len(queries) == 1
    assert saved.parent_report_revision == 'initial'
    assert saved.calculation_receipt_ids != (original.receipt_id,)
    rebuilt = ReportBasisService(context['scopes'])
    assert await rebuilt.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2') == saved
    view = await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='batch-revision-2')
    assert view.calculations[0].results[0].value == Decimal(300)
    assert view.calculations[0].results[0].fact_id != original.results[0].fact_id
    assert len(queries) == 1
    assert options['run_context'].session_state == before
    next_saved = await rebuilt.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='batch-revision-2', report_revision='batch-revision-3')
    assert next_saved.parent_report_revision == 'batch-revision-2' and len(queries) == 2
    with pytest.raises(ManagementError):
        await rebuilt.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='batch-revision-3', report_revision='batch-revision-2')
    assert len(queries) == 2


async def test_batch_refresh_resumes_after_manifest_failure_and_preserves_unknown_sql(refresh_context, monkeypatch):
    service, context, _, _, queries, _ = refresh_context
    common = await batch_options(refresh_context)
    register = service.register_refresh_revision
    async def failed_manifest(*args, **kwargs):
        raise OSError('manifest not committed')
    monkeypatch.setattr(service, 'register_refresh_revision', failed_manifest)
    with pytest.raises(OSError):
        await service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='batch-revision-2')
    assert len(queries) == 1
    monkeypatch.setattr(service, 'register_refresh_revision', register)
    await service.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2')
    assert len(queries) == 1
    async def failed_receipt(*args, **kwargs):
        raise OSError('calculation result not committed')
    monkeypatch.setattr(service, 'append_basis_receipt', failed_receipt)
    with pytest.raises(OSError):
        await service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='batch-revision-2', report_revision='batch-revision-3')
    assert len(queries) == 2
    rebuilt = ReportBasisService(context['scopes'])
    with pytest.raises(ManagementError, match='management_refresh_outcome_unknown'):
        await rebuilt.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='batch-revision-2', report_revision='batch-revision-3')
    assert len(queries) == 2


async def test_batch_refresh_does_not_query_before_atomic_intent_and_rejects_foreign_scope(refresh_context, monkeypatch):
    service, context, _, _, queries, _ = refresh_context
    common = await batch_options(refresh_context)
    async def failed_audit(*args, **kwargs):
        raise OSError('intent audit rollback')
    audit = service._audit
    monkeypatch.setattr(service, '_audit', failed_audit)
    with pytest.raises(OSError):
        await service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='batch-revision-2')
    assert queries == []
    assert await service.load_basis_receipts('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        report_revision='batch-revision-2') == ()
    monkeypatch.setattr(service, '_audit', audit)
    for scope, kwargs in ((context['other_scope'], common), (context['scope'], {**common, 'user_id': 'foreign'})):
        with pytest.raises(ManagementError):
            await service.refresh_revision('run-basis', scope, **kwargs,
                parent_report_revision='initial', report_revision='batch-revision-2')
    with pytest.raises(ManagementError):
        await service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='initial')
    assert queries == []


async def test_batch_intent_cannot_be_rebound_by_inflight_manual_manifest(refresh_context, monkeypatch):
    import asyncio

    service, context, _, _, queries, options = refresh_context
    common = await batch_options(refresh_context)
    competitor = await service.refresh_calculation('run-basis', context['scope'], **options)
    load = service.load_refresh_planning_context
    manual_ready, release_manual, batch_ready, release_batch = (asyncio.Event() for _ in range(4))
    async def delayed_load(*args, **kwargs):
        view = await load(*args, **kwargs)
        if kwargs['receipt_ids'] == (competitor.receipt_id,):
            manual_ready.set()
            await release_manual.wait()
        return view
    monkeypatch.setattr(service, 'load_refresh_planning_context', delayed_load)
    manual = asyncio.create_task(service.register_refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2', receipt_ids=(competitor.receipt_id,)))
    async def pause_after_claim(*args, **kwargs):
        batch_ready.set()
        await release_batch.wait()
        raise OSError('explicit pause before SQL')
    try:
        await asyncio.wait_for(manual_ready.wait(), timeout=5)
        monkeypatch.setattr(service, 'refresh_calculation', pause_after_claim)
        batch = asyncio.create_task(service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='batch-revision-2'))
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=5)
            release_manual.set()
            with pytest.raises(ManagementError, match='management_basis_receipt_conflict'):
                await asyncio.wait_for(manual, timeout=5)
        finally:
            release_batch.set()
            with pytest.raises(OSError):
                await batch
    finally:
        release_manual.set()
        if not manual.done():
            await manual
    assert len(queries) == 1


@pytest.mark.parametrize('refresh_context', [True], indirect=True)
async def test_batch_refresh_recovers_partial_current_and_comparison_without_mixing_old_results(refresh_context, monkeypatch):
    service, context, _, _, queries, _ = refresh_context
    common = await batch_options(refresh_context)
    refresh = service.refresh_calculation
    calls = 0
    async def stop_before_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('process stopped before next calculation intent')
        return await refresh(*args, **kwargs)
    monkeypatch.setattr(service, 'refresh_calculation', stop_before_second)
    with pytest.raises(OSError):
        await service.refresh_revision('run-basis', context['scope'], **common,
            parent_report_revision='initial', report_revision='batch-revision-2')
    assert len(queries) == 1
    rebuilt = ReportBasisService(context['scopes'])
    saved = await rebuilt.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2')
    assert len(queries) == 2 and len(saved.calculation_receipt_ids) == 2
    view = await rebuilt.load_revision_planning_context('run-basis', context['scope'], **common,
        report_revision='batch-revision-2')
    assert {item.request.period.start.isoformat(): item.results[0].value for item in view.calculations} == {
        '2026-11-01': Decimal(300), '2026-10-01': Decimal(150)}
    assert all(result.fact_id not in {'original-fact', 'original-baseline'}
        for item in view.calculations for result in item.results)
    assert await rebuilt.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2') == saved
    assert len(queries) == 2


async def test_same_batch_concurrency_never_duplicates_business_query(refresh_context):
    import asyncio

    service, context, _, _, queries, _ = refresh_context
    common = await batch_options(refresh_context)
    async def start():
        try:
            return await service.refresh_revision('run-basis', context['scope'], **common,
                parent_report_revision='initial', report_revision='batch-revision-2')
        except ManagementError as error:
            return error
    outcomes = await asyncio.gather(start(), start())
    successes = [item for item in outcomes if not isinstance(item, ManagementError)]
    assert successes and len(queries) == 1
    assert all(item == successes[0] if not isinstance(item, ManagementError)
        else item.code == 'management_refresh_outcome_unknown' for item in outcomes)
    assert await service.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2') == successes[0]
    assert len(queries) == 1


@pytest.mark.parametrize('refresh_context', [{'outputs': ['pdf', 'docx'], 'domains': ['budget']},
    {'outputs': ['pptx'], 'domains': ['budget']}, {'outputs': ['xlsx'], 'domains': ['budget']}], indirect=True)
@pytest.mark.parametrize('recover_preparation', [False, True], ids=['initial', 'preparation_recovery'])
async def test_revision_execution_persists_native_checkpoint_without_touching_parent(refresh_context, monkeypatch, recover_preparation):
    import asyncio
    import hashlib
    import os
    from copy import deepcopy

    from smart_reporting.report_editor.revisions import next_manual_revision
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.revision_execution import prepare_revision_execution
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.state import ReportingRunState
    from smart_reporting.runtime.database import create_agent_database

    service, context, _, _, queries, options = refresh_context
    common = await batch_options(refresh_context)
    await service.refresh_revision('run-basis', context['scope'], **common,
        parent_report_revision='initial', report_revision='batch-revision-2')
    from agno.run import RunContext

    from smart_reporting.reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY
    run_context = RunContext(run_id='run-basis', session_id=options['workflow_scope'].session_id, user_id='7',
        session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: options['workflow_scope'].as_state()})
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service = service
    runtime.configuration_provider = SimpleNamespace(vault=context['vault'])
    runtime.datasets = options['dataset_store']
    runtime.workspace_service = options['dataset_store'].service
    runtime._durable_command_lock = asyncio.Lock()
    runtime._checkpoint_persist_lock = asyncio.Lock()
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    runtime.state_repository = ReportingStateRepository(database.async_db)
    refresh_workers = []
    scope = runtime._scope(run_context)
    original_checkpoint = {'owner': 'original-running-report'}
    from smart_reporting.reporting.tests.test_refresh_planning import detail_plan_inputs
    approved_plan, _, _ = detail_plan_inputs()
    approved_plan = approved_plan.model_copy(update={'dataset_ids': ('dataset-budget01',),
        'analyses': (approved_plan.analyses[0].model_copy(update={'dataset_ids': ('dataset-budget01',)}),)})
    try:
        await runtime.state_repository.register_run(report_run_id='run-basis', external_run_id=scope['externalRunId'],
            agno_session_id=scope['sessionId'], agno_run_id='run-basis', thread_id=scope['callerThreadId'],
            owner_user_id=scope['userId'], database=scope['database'], company_id=scope['companyId'], entrypoint='agentos')
        await runtime.state_repository.create(ReportingRunState.initial(report_run_id='run-basis',
            external_run_id=scope['externalRunId'], thread_id=scope['callerThreadId'], owner_user_id=scope['userId'],
            payload={'workflowCheckpoint': original_checkpoint, 'oldOnly': 'must not be copied',
                'detailedAnalysisPlan': approved_plan.model_dump(mode='json', by_alias=True),
                'analysisIds': ['analysis_001']}))
        parent = await runtime.state_repository.get('run-basis')
        before_session = deepcopy(run_context.session_state)
        from smart_reporting.reporting.workflow.revision_execution import continue_revision_delivery

        async def check_http_publication(published, *, editor_available=True):
            from urllib.parse import urlsplit

            from fastapi import FastAPI
            from httpx import ASGITransport, AsyncClient

            from smart_reporting.report_editor import (
                InMemoryReportEditorRepository,
                ReportEditorGrantService,
                ReportEditorService,
            )
            from smart_reporting.reporting.delivery.publishing import (
                ReportArtifactPersistenceService,
                ReportDownloadGrantService,
                ReportDownloadHttpService,
                create_report_download_router,
            )
            from smart_reporting.reporting.tests.delivery_fakes import (
                InMemoryDownloadGrantRepository,
                InMemoryReportArtifactRepository,
            )
            from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY

            artifacts = InMemoryReportArtifactRepository()
            runtime.artifact_persistence = ReportArtifactPersistenceService(artifacts, runtime.workspace_service)
            runtime.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
            runtime.editor_grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
            runtime.report_public_base_url = 'http://reports.test'
            output = await runtime.issue_http_publication(thread_id=scope['threadId'],
                caller_thread_id=scope['callerThreadId'], user_id=scope['userId'],
                workflow_session_id=scope['sessionId'], workflow_run_id='run-basis',
                dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                    **scope, 'threadId': scope['callerThreadId']}}, output=published)
            app = FastAPI()
            app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
                for output_format in next_execution.requested_outputs:
                    label = 'word' if output_format == 'docx' else output_format
                    response = await client.get(output[label]['downloadUrl'])
                    assert response.status_code == 200
                    assert hashlib.sha256(response.content).hexdigest() == published.content[f'{label}Sha256']
            if not editor_available:
                assert 'editor' not in output
                return
            assert output['editor']['openUrl']
            raw_grant = urlsplit(output['editor']['openUrl']).path.rsplit('/', 1)[-1]
            _, session = await runtime.editor_grants.exchange(raw_grant)
            editor = ReportEditorService(state_repository=runtime.state_repository,
                workspace_registry=runtime.workspace_service.registry, workspace=runtime.workspace_service,
                report_basis_service=runtime.report_basis_service, recalculation_runtime=runtime)
            editor_context = await editor.context_for_session(session)
            assert editor_context.revision == next_execution.output_revision
            assert editor_context.workflow_run_id == 'run-basis'
            assert editor_context.artifact_manifest is not None
            index = await editor.trace.require_index(editor_context)
            assert index.report_basis_id == next_execution.basis_id
            from smart_reporting.report_editor.recalculation import resolve_refresh_parent
            parent_planning = await resolve_refresh_parent(editor, editor_context, vault=context['vault'])
            assert parent_planning.report_revision == next_execution.report_revision
            assert parent_planning.basis_id == next_execution.basis_id
            assert parent_planning.report_revision != str(editor_context.revision)
            document = await editor.read_document(editor_context)
            from smart_reporting.report_editor.recalculation import (
                RecalculationRequest,
                register_refresh_request,
            )
            request = RecalculationRequest(requestId='next-refresh-from-editor', parentRevision=editor_context.revision,
                expectedSha256=document.sha256, operation='refresh_data')
            registered_refresh = await register_refresh_request(editor, editor_context, request, vault=context['vault'])
            assert registered_refresh.refresh_binding.parent_report_revision == next_execution.report_revision
            assert registered_refresh.basis_id == next_execution.basis_id
            assert registered_refresh.status == 'pending'
            assert '300' in document.markdown
            analysis_context = await editor._registered_analysis_context_file(editor_context)
            child = await runtime.state_repository.get(next_execution.execution_run_id)
            assert analysis_context == next(item for item in child.payload['artifacts']
                if item['path'].endswith('/dataset-contexts.json'))
            assert run_context.session_state == before_session
        async def exercise_refresh_task():
            nonlocal next_execution, next_plan
            from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
            from smart_reporting.report_editor.recalculation import (
                read_recalculation_run,
                read_refresh_delivery,
                read_task,
                run_refresh_request,
                task_identity,
            )
            editor = ReportEditorService(state_repository=runtime.state_repository,
                workspace_registry=runtime.workspace_service.registry, workspace=runtime.workspace_service,
                report_basis_service=runtime.report_basis_service, recalculation_runtime=runtime,
                recalculation_database=database.async_db)
            from agno.os.job_queue import QueueWorker, resolve_queue_store

            from smart_reporting.report_editor.recalculation import (
                create_refresh_workflow,
                recalculation_queue_config,
            )

            config = recalculation_queue_config()
            config.poll_interval = 0.05
            editor.recalculation_durable = True
            worker = QueueWorker(store=resolve_queue_store(config, database.async_db), config=config,
                resolve_component=lambda kind, component_id: create_refresh_workflow(editor,
                    runtime=runtime, database=database.async_db) if (kind, component_id) == (
                        'workflow', 'report-editor-refresh') else None)
            await worker.start()
            refresh_workers.append(worker)
            editor.recalculation_queue_worker = worker
            original_context = ReportEditorContext.model_validate(
                (await rebuilt.get('run-basis')).payload['reportEditorContexts'][str(next_execution.output_revision)])
            task = await read_task(editor, original_context, 'next-refresh-from-editor')
            public_request = task.request.model_copy(update={'request_id': 'public-refresh-from-editor'})
            public_task_id = task_identity(original_context, public_request.request_id)
            parent_execution = next_execution
            from agno.run import RunStatus
            from fastapi import FastAPI
            from httpx import ASGITransport, AsyncClient

            from smart_reporting.report_editor.api import (
                EDITOR_SESSION_COOKIE,
                create_report_editor_router,
            )
            assert await read_task(editor, original_context, public_request.request_id) is None
            assert len(queries) == 2
            source = await rebuilt.get('run-basis')
            for child_id in source.payload['reportEditorRevisionReservations']:
                child = await rebuilt.get(child_id)
                if child and 'reportRevisionExecution' in child.payload:
                    assert child.payload['reportRevisionExecution']['reportRevision'] != (
                        'editor-refresh-' + public_task_id.removeprefix('recalc-'))
            request_app = FastAPI()
            request_app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor,
                cookie_secure=False))
            request_grant, _ = await runtime.editor_grants.issue(original_context)
            request_url = (f'/reports/v1/editor/{original_context.report_id}/{original_context.revision}'
                '/api/recalculations')
            async with AsyncClient(transport=ASGITransport(app=request_app), base_url='http://reports.test') as client:
                await client.get(f'/reports/v1/editor/open/{request_grant}', follow_redirects=False)
                headers = {'origin': 'http://reports.test',
                    'x-csrf-token': runtime.editor_grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
                response = await client.post(request_url, json=public_request.model_dump(mode='json', by_alias=True),
                    headers=headers)
                assert response.status_code == 202
                assert response.headers['cache-control'] == 'no-store'
                submitted = response.json()
            task = await read_task(editor, original_context, public_request.request_id)
            async def await_delivery():
                while True:
                    registered = await read_recalculation_run(editor, original_context, task.task_id,
                        database=database.async_db)
                    assert registered.run_id == submitted['execution']['runId']
                    assert registered.status not in {RunStatus.error, RunStatus.cancelled}
                    if registered.status == RunStatus.completed:
                        return registered
                    await asyncio.sleep(0.05)
            completed_run = await asyncio.wait_for(await_delivery(), timeout=120)
            persisted_task = await read_task(editor, original_context, task.request.request_id)
            assert persisted_task.status == 'completed'
            assert completed_run.content == persisted_task.model_dump(mode='json', by_alias=True)
            completed_refresh, refreshed_publication = await run_refresh_request(editor, original_context,
                task.task_id, runtime=runtime)
            assert completed_refresh == persisted_task
            assert completed_refresh.status == 'completed'
            assert completed_refresh.result.execution == next_execution
            assert completed_refresh.result.business_approval == 'not_performed'
            assert refreshed_publication.content['revision'] == next_execution.output_revision
            assert next_execution.output_revision > parent_execution.output_revision
            from smart_reporting.report_editor import recalculation
            from smart_reporting.reporting.workflow import revision_execution as execution_module
            async def no_computation(*args, **kwargs):
                pytest.fail('读取刷新交付不能触发计算或交付续跑')
            before_delivery_queries = len(queries)
            with monkeypatch.context() as read_only:
                read_only.setattr(execution_module, 'prepare_refresh_delivery', no_computation)
                read_only.setattr(execution_module, 'continue_revision_delivery', no_computation)
                restored_task, restored_delivery = await read_refresh_delivery(
                    editor, original_context, task.task_id, runtime=runtime)
                assert restored_task == completed_refresh
                async def pending_receipt(*args):
                    return task
                read_only.setattr(recalculation, 'read_task_by_id', pending_receipt)
                pending_task, pending_delivery = await read_refresh_delivery(
                    editor, original_context, task.task_id, runtime=runtime)
                assert pending_task.status == 'pending'
                assert 'refresh_completion_record_unavailable' in {
                    issue['code'] for issue in pending_delivery.content['validation']['issues']}
            assert len(queries) == before_delivery_queries
            for label in ('pdf', 'word', 'pptx', 'xlsx'):
                if refreshed_publication.content.get(f'{label}Path'):
                    assert restored_delivery.content[f'{label}Sha256'] == refreshed_publication.content[f'{label}Sha256']
                    assert pending_delivery.content[f'{label}Sha256'] == refreshed_publication.content[f'{label}Sha256']
            await check_http_publication(pending_delivery)
            await check_http_publication(refreshed_publication)
            delivery = await editor.recalculation_delivery(original_context, task.task_id)
            assert delivery['task'] == completed_refresh.model_dump(mode='json', by_alias=True)
            for output_format in next_execution.requested_outputs:
                label = 'word' if output_format == 'docx' else output_format
                assert delivery['delivery'][label]['downloadUrl']
            delivery_app = FastAPI()
            delivery_app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor,
                cookie_secure=False))
            raw_grant, _ = await runtime.editor_grants.issue(original_context)
            delivery_url = (f'/reports/v1/editor/{original_context.report_id}/{original_context.revision}'
                f'/api/recalculations/{task.task_id}/delivery')
            with monkeypatch.context() as no_execution:
                no_execution.setattr(execution_module, 'prepare_refresh_delivery', no_computation)
                no_execution.setattr(execution_module, 'continue_revision_delivery', no_computation)
                async with AsyncClient(transport=ASGITransport(app=delivery_app), base_url='http://reports.test') as client:
                    assert (await client.get(delivery_url)).status_code == 404
                    await client.get(f'/reports/v1/editor/open/{raw_grant}', follow_redirects=False)
                    response = await client.get(delivery_url)
                    assert response.status_code == 200
                    assert response.headers['cache-control'] == 'no-store'
                    assert response.json()['task'] == delivery['task']
                    for output_format in next_execution.requested_outputs:
                        label = 'word' if output_format == 'docx' else output_format
                        assert response.json()['delivery'][label]['downloadUrl']
            assert len(queries) == before_delivery_queries
            return parent_execution

        create = runtime.state_repository.get_or_create
        async def committed_response_lost(*args, **kwargs):
            await create(*args, **kwargs)
            raise OSError('child state committed but response lost')
        monkeypatch.setattr(runtime.state_repository, 'get_or_create', committed_response_lost)
        with pytest.raises(OSError):
            await prepare_revision_execution(runtime, run_context, report_revision='batch-revision-2')
        monkeypatch.setattr(runtime.state_repository, 'get_or_create', create)
        execution = await prepare_revision_execution(runtime, run_context, report_revision='batch-revision-2')
        assert execution.source_scope.run_id == 'run-basis' and execution.output_revision == 2
        expected_outputs = tuple((await runtime._metric_planning_context(run_context, report_revision='batch-revision-2')).request.requested_outputs)
        assert execution.requested_outputs == expected_outputs
        assert execution.execution_run_id != 'run-basis'
        child = await runtime.state_repository.get(execution.execution_run_id)
        assert 'workflowCheckpoint' not in child.payload and 'oldOnly' not in child.payload
        manual_revision, issues = await next_manual_revision(runtime.state_repository,
            SimpleNamespace(workflow_run_id='run-basis', revision=1))
        assert manual_revision == 3 and issues == []
        assert await prepare_revision_execution(runtime, run_context, report_revision='batch-revision-2') == execution
        assert run_context.session_state == before_session
        handle, = await runtime._registered_metric_dataset_handles(run_context, report_revision='batch-revision-2')
        profile = {'path': 'profiles/explicit-fixture.json', 'size': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()}
        checkpoint = ReportingCheckpoint(revision=execution.output_revision, phase='analysis', outlineHash='a' * 64,
            profileCoverage={'authorizedDatasetCount': 1, 'coveredDatasetCount': 1, 'datasets': [{
                'datasetId': handle.dataset_id, 'datasetPath': handle.path, 'datasetSize': handle.size,
                'datasetSnapshotHash': handle.sha256, 'profileFile': profile, 'rowCount': handle.row_count,
                'fieldCount': 1, 'fields': ['value']}]})
        from smart_reporting.reporting.models import ReportingError
        from smart_reporting.reporting.workflow.checkpoint import FileIdentity
        old_fact = FileIdentity(path='facts/original.json', size=1, sha256='f' * 64)
        with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
            await runtime._persist_reporting_checkpoint(run_context,
                checkpoint.model_copy(update={'deterministic_fact_files': {'analysis_001': old_fact}}), execution=execution)
        from smart_reporting.reporting.workflow.revision_execution import (
            prepare_revision_dataset_contexts,
            restore_refresh_analysis_plan,
        )
        from smart_reporting.reporting.workflow.runtime import datasets as dataset_runtime
        original_write = runtime._write_immutable_artifact
        async def stop_before_context_manifest(thread_id, path, content):
            if path.endswith('/dataset-contexts.json'):
                raise OSError('stopped after durable dataset profile')
            return await original_write(thread_id, path, content)
        monkeypatch.setattr(runtime, '_write_immutable_artifact', stop_before_context_manifest)
        with pytest.raises(OSError):
            await prepare_revision_dataset_contexts(runtime, run_context, execution)
        monkeypatch.setattr(runtime, '_write_immutable_artifact', original_write)
        original_profile = dataset_runtime._run_profile_job
        async def must_not_reprofile(*args, **kwargs):
            raise AssertionError('completed profile must be restored without rerunning engine')
        monkeypatch.setattr(dataset_runtime, '_run_profile_job', must_not_reprofile)
        contexts = await prepare_revision_dataset_contexts(runtime, run_context, execution)
        monkeypatch.setattr(dataset_runtime, '_run_profile_job', original_profile)
        assert len(contexts) == 1
        assert contexts[0].profile_engine_version != 'explicit-test-fixture'
        assert contexts[0].sha256 == handle.sha256 and contexts[0].row_count == handle.row_count
        assert run_context.session_state == before_session
        cached = await prepare_revision_dataset_contexts(runtime, run_context, execution)
        assert cached == contexts
        profile_raw = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
            contexts[0].profile_file.path, max_bytes=contexts[0].profile_file.size)
        await runtime.workspace_service.awrite_bytes(scope['threadId'], contexts[0].profile_file.path, b'changed', overwrite=True)
        with pytest.raises(ReportingError, match='report_analysis_profile_changed'):
            await prepare_revision_dataset_contexts(runtime, run_context, execution)
        await runtime.workspace_service.awrite_bytes(scope['threadId'], contexts[0].profile_file.path, profile_raw, overwrite=True)
        plan = await restore_refresh_analysis_plan(runtime, run_context, execution)
        assert plan.dataset_ids == (handle.dataset_id,)
        assert plan.analyses[0].management_question == approved_plan.analyses[0].management_question
        assert plan.analyses[0].actions == approved_plan.analyses[0].actions
        get_state = runtime.state_repository.get
        async def source_without_approved_plan(run_id):
            saved = await get_state(run_id)
            if run_id == 'run-basis':
                saved = saved.model_copy(update={'payload': {
                    key: value for key, value in saved.payload.items() if key != 'detailedAnalysisPlan'}})
            return saved
        monkeypatch.setattr(runtime.state_repository, 'get', source_without_approved_plan)
        with pytest.raises(ReportingError, match='report_refresh_analysis_plan_unavailable'):
            await restore_refresh_analysis_plan(runtime, run_context, execution)
        monkeypatch.setattr(runtime.state_repository, 'get', get_state)
        run_context.session_state['report_detailed_analysis_plan'] = {'forged': True}
        assert await restore_refresh_analysis_plan(runtime, run_context, execution) == plan
        run_context.session_state = deepcopy(before_session)
        with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
            await runtime._prepare_deterministic_analysis_facts(run_context=run_context,
                thread_id=scope['threadId'], report_run_id='run-basis', revision=execution.output_revision,
                detailed_plan=plan, dataset_handles=(handle,), metric_report_revision=execution.report_revision,
                execution=execution, dataset_contexts=(contexts[0].model_copy(update={'profile_engine_version': 'forged'}),))
        fact_files = await runtime._prepare_deterministic_analysis_facts(run_context=run_context,
            thread_id=scope['threadId'], report_run_id='run-basis', revision=execution.output_revision,
            detailed_plan=plan, dataset_handles=(handle,), metric_report_revision=execution.report_revision,
            execution=execution, dataset_contexts=contexts)
        graph, _ = await runtime._prepare_registered_revision_findings(run_context=run_context,
            thread_id=scope['threadId'], report_run_id='run-basis', revision=execution.output_revision,
            report_revision=execution.report_revision, fact_files=fact_files, execution=execution)
        from smart_reporting.reporting.hospital_operation.outline import (
            ReportOutline,
            ReportOutlineSection,
        )
        from smart_reporting.reporting.workflow.revision_execution import prepare_revision_analysis
        outline = ReportOutline(reportType='topic', title='新数据分析', sections=(ReportOutlineSection(
            code='section_001', sectionNumber='1', title='预算核对', analysisIds=('analysis_001',)),))
        with pytest.raises(ReportingError, match='report_refresh_outline_unavailable'):
            await prepare_revision_analysis(runtime, run_context, execution)
        from smart_reporting.reporting.workflow.state import ReportingCommand
        await runtime._apply_durable_command(run_context, ReportingCommand(name='freeze_report_outline',
            commandId='original-approved-outline', payload={'outline': outline.model_dump(mode='json', by_alias=True)}))
        run_context.session_state['report_outline'] = {'title': 'forged request outline'}
        from smart_reporting.reporting.workflow.revision_execution import prepare_refresh_delivery
        prepared_execution = await prepare_refresh_delivery(runtime, run_context,
            parent_report_revision='initial', report_revision=execution.report_revision)
        assert prepared_execution == execution
        checkpoint = ReportingCheckpoint.model_validate((await runtime.state_repository.get(
            execution.execution_run_id)).payload['workflowCheckpoint'])
        assert await prepare_refresh_delivery(runtime, run_context,
            parent_report_revision='initial', report_revision=execution.report_revision) == execution
        run_context.session_state = deepcopy(before_session)
        assert checkpoint.deterministic_fact_files == fact_files
        assert checkpoint.finding_graph_file == graph
        assert checkpoint.profile_coverage.datasets[0].profile_file.path == contexts[0].profile_file.path
        assert await prepare_revision_analysis(runtime, run_context, execution,
            detailed_plan=plan, outline=outline) == checkpoint
        changed_plan = plan.model_copy(update={'report_goal': 'unapproved different plan'})
        with pytest.raises(ReportingError, match='report_artifact_file_changed'):
            await prepare_revision_analysis(runtime, run_context, execution,
                detailed_plan=changed_plan, outline=outline)
        foreign_plan = plan.model_copy(update={'dataset_ids': ('foreign-dataset',),
            'analyses': tuple(item.model_copy(update={'dataset_ids': ('foreign-dataset',)}) for item in plan.analyses)})
        with pytest.raises(ReportingError):
            await prepare_revision_analysis(runtime, run_context, execution,
                detailed_plan=foreign_plan, outline=outline)

        rebuilt = ReportingStateRepository(database.async_db)
        child = await rebuilt.get(execution.execution_run_id)
        assert ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint']) == checkpoint
        after = await rebuilt.get('run-basis')
        assert after.phase == parent.phase and after.revision == parent.revision
        assert after.payload['workflowCheckpoint'] == original_checkpoint
        assert after.payload['artifacts'] == parent.payload['artifacts']
        assert graph.model_dump(mode='json', by_alias=True) in child.payload['artifacts']
        assert all(file.model_dump(mode='json', by_alias=True) in child.payload['artifacts'] for file in fact_files.values())
        assert run_context.session_state == before_session and len(queries) == 1
        from smart_reporting.reporting.workflow.revision_execution import require_revision_execution
        changed_outputs = execution.model_copy(update={'requested_outputs': ('xlsx',) if execution.requested_outputs != ('xlsx',) else ('pptx',)})
        with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
            await require_revision_execution(runtime, run_context, changed_outputs)
        foreign = execution.model_copy(update={'output_revision': 4})
        from smart_reporting.reporting.models import ReportingError
        with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
            await runtime._persist_reporting_checkpoint(run_context, checkpoint.model_copy(update={'revision': 4}), execution=foreign)
        assert (await rebuilt.get(execution.execution_run_id)).payload == child.payload
        csv_raw = await runtime.workspace_service.read_limited_regular_file(scope['threadId'], handle.path, max_bytes=handle.size)
        await runtime.workspace_service.awrite_bytes(scope['threadId'], handle.path, b'tampered', overwrite=True)
        with pytest.raises(ReportingError, match='management_basis_snapshot_unavailable'):
            await prepare_revision_execution(runtime, run_context, report_revision=execution.report_revision)
        assert (await rebuilt.get('run-basis')).payload == after.payload
        assert len(queries) == 1
        await runtime.workspace_service.awrite_bytes(scope['threadId'], handle.path, csv_raw, overwrite=True)

        # 连续刷新从父执行的不可变完整计划恢复，不依赖原session或已过期父CSV。
        await runtime.workspace_service.awrite_bytes(scope['threadId'], handle.path, b'expired parent csv', overwrite=True)
        next_execution = await prepare_refresh_delivery(runtime, run_context,
            parent_report_revision=execution.report_revision, report_revision='batch-revision-3')
        assert next_execution.output_revision == 4 and next_execution.requested_outputs == execution.requested_outputs
        next_plan = await restore_refresh_analysis_plan(runtime, run_context, next_execution)
        assert next_plan.dataset_ids != plan.dataset_ids
        assert next_plan.analyses[0].management_question == approved_plan.analyses[0].management_question
        next_checkpoint = await prepare_revision_analysis(runtime, run_context, next_execution)
        assert next_checkpoint.revision == 4 and len(queries) == 2
        next_state = await rebuilt.get(next_execution.execution_run_id)
        assert next_state.payload['detailedAnalysisPlan'] == next_plan.model_dump(mode='json', by_alias=True)
        assert next_state.payload['deliveryFormat'] == ('pptx' if next_execution.requested_outputs == ('pptx',)
            else 'xlsx' if next_execution.requested_outputs == ('xlsx',) else 'document')
        from smart_reporting.reporting.delivery.artifacts_v1 import Citation
        from smart_reporting.reporting.workflow.revision_execution import (
            freeze_revision_analysis_artifact,
        )
        next_handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=next_execution.report_revision)
        citations = tuple(Citation(citationId=f'citation_{index:03d}', datasetId=item.dataset_id,
            requirementId=item.requirement_id, snapshotHash=item.sha256)
            for index, item in enumerate(sorted(next_handles, key=lambda item: (item.requirement_id, item.dataset_id)), 1))
        build_options = dict(analysis_ids=('analysis_001',), detailed_plan=next_plan,
            fact_files=next_checkpoint.deterministic_fact_files, citation_bindings=citations,
            execution=next_execution, outline=outline)
        with pytest.raises(ReportingError, match='report_analysis_evidence_incomplete'):
            await runtime._build_reporting_artifact(run_context, **build_options)
        from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
        from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
        from smart_reporting.reporting.workflow.revision_execution import (
            run_revision_analysis_items,
        )
        from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
            AnalysisEvidenceDecision,
            AnalysisSummaryDraft,
        )
        from smart_reporting.task_execution import (
            TaskExecutionKernel,
            TaskExecutionRepository,
            TaskState,
        )

        task_repository = TaskExecutionRepository(database.async_db)
        await task_repository.initialize()
        coordinator = ReportingTaskCoordinator(task_repository,
            TaskExecutionKernel(runtime.workspace_service, task_repository), model_profiles=DEFAULT_MODEL_PROFILES)
        task_runs, planner_calls = [], []
        async def run_planner(agent, payload, context, **kwargs):
            planner_calls.append(agent)
            if agent is runtime._analysis_evidence_agent:
                return AnalysisEvidenceDecision(requiresSupplementalEvidence=False,
                    reason='此测试问题只核对已登记指标结果；不需要额外取数。', missingFacts=(), codingRequirements=())
            assert agent is runtime._analysis_summary_agent
            return AnalysisSummaryDraft(summary='新计算事实已登记；业务问题完成状态仍待逐项核对。',
                warnings=('业务核对尚未完成。',))
        runtime._analysis_evidence_agent = SimpleNamespace(model=None)
        runtime._analysis_summary_agent = SimpleNamespace(model=None)
        runtime._analysis_thinking_budget_cap = 1024
        runtime._analysis_script_agent_factory = lambda *args: pytest.fail('本测试不允许运行补证脚本')
        runtime.code_mode_runtime = object()
        runtime.coding_task_registry = None
        monkeypatch.setattr(runtime, '_run_planner', run_planner)
        first_response = True
        async def run_task(task_scope, *, parent_run_id, executor):
            nonlocal first_response, next_execution, next_plan
            if parent_run_id != next_execution.execution_run_id:
                from smart_reporting.reporting.workflow.revision_execution import (
                    ReportRevisionExecution,
                )
                child = await rebuilt.get(parent_run_id)
                next_execution = ReportRevisionExecution.model_validate(child.payload['reportRevisionExecution'])
                assert next_execution.parent_report_revision == 'batch-revision-3'
                assert next_execution.report_revision.startswith('editor-refresh-')
                next_plan = await restore_refresh_analysis_plan(runtime, run_context, next_execution)
            assert parent_run_id == next_execution.execution_run_id
            async def invoke(invocation):
                import json
                data = json.loads(invocation.instruction)
                assert data['deterministicFacts']['metricContext']['reportRevision'] == next_execution.report_revision
                assert data['datasets'][0]['datasetId'] in next_plan.dataset_ids
                task_runs.append(parent_run_id)
                return await executor(invocation)
            receipt = await coordinator.run(task_scope, parent_run_id=parent_run_id, executor=invoke)
            task = await task_repository.get_task_snapshot(task_scope.external_run_id)
            assert task.state is TaskState.COMPLETED
            if first_response:
                first_response = False
                raise OSError('completed analysis task response lost')
            return receipt
        runtime.task_runner = SimpleNamespace(repository=task_repository, start=coordinator.start, run=run_task)
        runtime._analysis_thinking_enabled = False
        with pytest.raises(OSError, match='response lost'):
            await run_revision_analysis_items(runtime, run_context, next_execution)
        next_checkpoint = await run_revision_analysis_items(runtime, run_context, next_execution)
        assert len(task_runs) == 1 and next_checkpoint.trace[-1].status == 'completed'
        assert planner_calls == [runtime._analysis_evidence_agent, runtime._analysis_summary_agent]
        saved_analysis = (await rebuilt.get(next_execution.execution_run_id)).payload['analysisItems']['analysis_001']
        assert saved_analysis['datasetIds'] == list(next_plan.dataset_ids)
        assert saved_analysis['evidenceFiles'] == [item.model_dump(mode='json', by_alias=True)
            for item in next_checkpoint.deterministic_fact_files.values()]
        assert await run_revision_analysis_items(runtime, run_context, next_execution) == next_checkpoint
        assert len(task_runs) == 1
        artifact = await runtime._build_reporting_artifact(run_context, **build_options)
        with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
            await runtime._build_reporting_artifact(run_context, **{**build_options,
                'outline': outline.model_copy(update={'title': '未批准的替换大纲'})})
        assert artifact.evidence_manifest.metric_definitions[0].code == 'budget'
        assert '@1' in artifact.evidence_manifest.metric_definitions[0].definition
        assert artifact.report_brief.objective == (await runtime._metric_planning_context(
            run_context, report_revision=next_execution.report_revision)).request.goal
        assert artifact.evidence_manifest.evidence[0].dataset_ids == next_plan.dataset_ids
        with pytest.raises(ReportingError):
            await runtime._build_reporting_artifact(run_context, **{**build_options,
                'fact_files': checkpoint.deterministic_fact_files})
        with pytest.raises(ReportingError):
            await runtime._build_reporting_artifact(run_context, **{**build_options,
                'citation_bindings': tuple(item.model_copy(update={'snapshot_hash': 'f' * 64}) for item in citations)})
        frozen = await freeze_revision_analysis_artifact(runtime, run_context, next_execution, outline=outline)
        assert frozen.evidence_manifest == artifact.evidence_manifest
        assert frozen.report_brief == artifact.report_brief
        assert await freeze_revision_analysis_artifact(runtime, run_context, next_execution, outline=outline) == frozen
        from smart_reporting.reporting.workflow.checkpoint import AnalysisArtifact
        assert await runtime._read_identity_model(scope['threadId'], frozen.analysis_manifest_file, AnalysisArtifact) == artifact
        from smart_reporting.reporting.workflow.revision_execution import load_revision_outline
        assert await load_revision_outline(runtime, run_context, next_execution) == outline
        with pytest.raises(ReportingError, match='report_artifact_file_changed'):
            await prepare_revision_analysis(runtime, run_context, next_execution,
                outline=outline.model_copy(update={'title': '不得替换已冻结大纲'}))
        outline_path = (f'报表/智能分析/run-basis/revision-executions/'
            f'{next_execution.execution_run_id}/approved-outline.json')
        outline_identity = next(item for item in (await rebuilt.get(next_execution.execution_run_id)).payload['artifacts']
            if item['path'] == outline_path)
        outline_bytes = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
            outline_path, max_bytes=outline_identity['size'])
        await runtime.workspace_service.awrite_bytes(scope['threadId'], outline_path, b'{}', overwrite=True)
        with pytest.raises(ReportingError):
            await run_revision_analysis_items(runtime, run_context, next_execution)
        with pytest.raises(ReportingError):
            await freeze_revision_analysis_artifact(runtime, run_context, next_execution, outline=outline)
        assert len(task_runs) == 1
        await runtime.workspace_service.awrite_bytes(scope['threadId'], outline_path, outline_bytes, overwrite=True)
        assert await load_revision_outline(runtime, run_context, next_execution) == outline
        from agno.workflow.types import StepInput

        from smart_reporting.reporting.hospital_operation.narrative_outline import (
            freeze_narrative_outline,
        )
        from smart_reporting.reporting.hospital_operation.narrative_planner import (
            build_fallback_narrative_candidate,
        )
        narrative_calls = []
        async def plan_narrative(**kwargs):
            narrative_calls.append(kwargs['graph'].snapshot_hash)
            assert kwargs['report_goal'] == artifact.report_brief.objective
            candidate = build_fallback_narrative_candidate(kwargs['graph'], kwargs['title'], analyses=kwargs['analyses'])
            return freeze_narrative_outline(candidate, graph=kwargs['graph'], analyses=kwargs['analyses']), (
                {'code': 'report_narrative_fixture_warning', 'message': '测试发现仍需业务复核。'},)
        monkeypatch.setattr(runtime, '_plan_narrative_outline', plan_narrative)
        persist_checkpoint = runtime._persist_reporting_checkpoint
        interrupted = 0
        async def narrative_checkpoint_response_lost(context, value, **kwargs):
            nonlocal interrupted
            if value.narrative_outline_file is not None:
                interrupted += 1
                if interrupted == 1:
                    raise OSError('narrative checkpoint before commit')
            saved = await persist_checkpoint(context, value, **kwargs)
            if value.narrative_outline_file is not None and interrupted == 2:
                raise OSError('narrative checkpoint response lost')
            return saved
        monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', narrative_checkpoint_response_lost)
        with pytest.raises(OSError, match='narrative checkpoint before commit'):
            await runtime.generate_narrative_outline(StepInput(input='新修订'), run_context, execution=next_execution)
        with pytest.raises(OSError, match='narrative checkpoint response lost'):
            await runtime.generate_narrative_outline(StepInput(input='恢复'), run_context, execution=next_execution)
        monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
        result = await runtime.generate_narrative_outline(StepInput(input='恢复'), run_context, execution=next_execution)
        assert result.content['status'] == 'completed'
        planned_state = await rebuilt.get(next_execution.execution_run_id)
        planned_checkpoint = ReportingCheckpoint.model_validate(planned_state.payload['workflowCheckpoint'])
        assert planned_checkpoint.narrative_outline_file.model_dump(mode='json', by_alias=True) in planned_state.payload['artifacts']
        current_outline = await load_revision_outline(runtime, run_context, next_execution)
        assert planned_checkpoint.pending_sections == tuple(section.code for section in current_outline.sections)
        assert any(issue.get('code') == 'report_narrative_fixture_warning' for issue in planned_checkpoint.warnings)
        assert len(narrative_calls) == 1
        assert await runtime.generate_narrative_outline(StepInput(input='恢复'), run_context, execution=next_execution) == result
        assert len(narrative_calls) == 1 and run_context.session_state == before_session
        narrative_identity = planned_checkpoint.narrative_outline_file
        narrative_bytes = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
            narrative_identity.path, max_bytes=narrative_identity.size)
        await runtime.workspace_service.awrite_bytes(scope['threadId'], narrative_identity.path, b'{}', overwrite=True)
        with pytest.raises(ReportingError):
            await runtime.generate_narrative_outline(StepInput(input='恢复'), run_context, execution=next_execution)
        assert len(narrative_calls) == 1
        await runtime.workspace_service.awrite_bytes(scope['threadId'], narrative_identity.path, narrative_bytes, overwrite=True)
        assert (await rebuilt.get(execution.execution_run_id)).payload == child.payload
        if set(next_execution.requested_outputs) <= {'pdf', 'docx'}:
            from smart_reporting.reporting.workflow.revision_execution import run_revision_section
            from smart_reporting.reporting.workflow.runtime import sections as section_runtime
            from smart_reporting.reporting.workflow.runtime.phase_models import (
                SectionSemanticReview,
            )

            runtime.section_generator = SimpleNamespace(model=None)
            runtime.business_evidence_service = context['policy_service'].evidence
            runtime.section_recovery = None
            runtime.section_whole_generation = True
            runtime._planner_reasoning_effort = None
            section_stages, section_task_runs = [], []
            async def section_stage(_agent, schema, stage, payload, **kwargs):
                section_stages.append(stage)
                assert kwargs['scope'].owner_user_id == scope['userId']
                if stage == 'semantics':
                    return SectionSemanticReview(interpretations=())
                if stage == 'plan':
                    fact, = payload['factCatalog']
                    assert fact['kind'] == 'registered_metric_result'
                    assert fact['reportBasisId'] == next_execution.basis_id
                    assert fact['reportRevision'] == next_execution.report_revision
                    assert fact['factId'] != 'original-fact' and Decimal(fact['value']) == 300
                    assert fact['metricVersion'] == {'metricId': 'budget', 'revision': 1}
                    assert fact['period'] == {'start': '2026-11-01', 'end': '2026-12-01'}
                    assert fact['periodBoundary'] == 'half_open'
                    assert payload['sectionWorkItem']['metricDefinitions'][0]['code'] == 'budget'
                    return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                        'blocks': [{'blockId': 'block-budget', 'objective': '核对预算计算与数据限制', 'claimIds': ['claim-budget']}],
                        'claims': [{'claimId': 'claim-budget', 'metricCode': 'budget', 'value': '300',
                            'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                            'citationIds': ['citation_001'], 'factIds': [fact['factId']],
                            'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
                assert stage == 'content'
                fact_id = payload['sectionPlan']['claims'][0]['factIds'][0]
                return schema.model_validate({'blocks': [{'blockId': 'block-budget',
                    'markdown': '本次预算额为{{value:' + fact_id + ':value:CNY}}，正式计算结果见下表；完整性证据尚缺，暂不判断预算执行情况。'}]})
            monkeypatch.setattr(section_runtime, '_run_section_stage', section_stage)
            section_response_lost = True
            async def run_section_task(task_scope, *, parent_run_id, executor):
                nonlocal section_response_lost
                if task_scope.executor_id == 'reporting-analysis-workflow':
                    return await run_task(task_scope, parent_run_id=parent_run_id, executor=executor)
                assert parent_run_id == next_execution.execution_run_id
                async def invoke(invocation):
                    import json
                    instruction = json.loads(invocation.instruction)
                    assert instruction['businessKnowledge']['reportBasisId'] == next_execution.basis_id
                    section_task_runs.append(parent_run_id)
                    return await executor(invocation)
                receipt = await coordinator.run(task_scope, parent_run_id=parent_run_id, executor=invoke)
                if section_response_lost:
                    section_response_lost = False
                    raise OSError('completed section Task response lost')
                return receipt
            runtime.task_runner = SimpleNamespace(repository=task_repository, start=coordinator.start, run=run_section_task)
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await run_revision_section(runtime, run_context, next_execution, section_code='foreign-section')
            section_command = runtime._apply_durable_command
            async def section_completion_response_lost(context, command, **kwargs):
                saved = await section_command(context, command, **kwargs)
                if command.name == 'complete_section':
                    raise OSError('section completion registration response lost')
                return saved
            monkeypatch.setattr(runtime, '_apply_durable_command', section_completion_response_lost)
            with pytest.raises(OSError, match='completed section Task response lost'):
                await run_revision_section(runtime, run_context, next_execution, section_code=current_outline.sections[0].code)
            with pytest.raises(OSError, match='section completion registration response lost'):
                await run_revision_section(runtime, run_context, next_execution, section_code=current_outline.sections[0].code)
            monkeypatch.setattr(runtime, '_apply_durable_command', section_command)
            document_checkpoint = planned_checkpoint
            for section in current_outline.sections:
                document_checkpoint, section_artifact, rework = await run_revision_section(
                    runtime, run_context, next_execution, section_code=section.code)
                assert rework is None and section_artifact.section_code == section.code
                assert section_artifact.blocks[0].markdown.startswith('本次预算额')
                assert section_artifact.blocks[0].number_references
                assert '数值待核实' not in section_artifact.blocks[0].markdown
                assert (await run_revision_section(runtime, run_context, next_execution,
                    section_code=section.code)) == (document_checkpoint, section_artifact, rework)
            assert document_checkpoint.completed_sections and not document_checkpoint.pending_sections
            from smart_reporting.reporting.semantics.basis import BasisKnowledgeReceipt
            knowledge_receipts = tuple(item for item in await service.load_basis_receipts('run-basis', context['scope'],
                user_id='7', thread_id='thread-basis', report_revision=next_execution.report_revision)
                if isinstance(item, BasisKnowledgeReceipt))
            assert knowledge_receipts and all(item.report_revision == next_execution.report_revision
                and item.section_code in {section.code for section in current_outline.sections} for item in knowledge_receipts)
            assert section_task_runs == [next_execution.execution_run_id]
            assert section_stages[:2] == ['plan', 'content']
            completed_identity = document_checkpoint.completed_sections[0].artifact_file
            section_bytes = await runtime._read_identity_bytes(scope['threadId'], completed_identity)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], completed_identity.path, b'{}', overwrite=True)
            with pytest.raises(ReportingError):
                await run_revision_section(runtime, run_context, next_execution, section_code=current_outline.sections[0].code)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], completed_identity.path, section_bytes, overwrite=True)
            assert section_task_runs == [next_execution.execution_run_id]
            from smart_reporting.reporting.workflow.query_pipeline import DatasetLineage
            document_handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=next_execution.report_revision)
            document_lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
                requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
                size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
                for item in document_handles)
            root = f'报表/智能分析/{next_execution.execution_run_id}/document/revision-{next_execution.output_revision}'
            finalize_options = dict(checkpoint=document_checkpoint, revision=next_execution.output_revision,
                markdown_path=f'{root}/report.md', manifest_path=f'{root}/report.manifest.json',
                lineage=document_lineage, citation_bindings=citations, source_warnings=(), execution=next_execution)
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime._finalize_reporting_sections(run_context, **{
                    **finalize_options, 'markdown_path': 'original/report.md'})
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime._finalize_reporting_sections(run_context, **{
                    **finalize_options, 'citation_bindings': ()})
            document_writes = 0
            async def document_checkpoint_response_lost(context, value, **kwargs):
                nonlocal document_writes
                if value.phase == 'completed':
                    document_writes += 1
                    if document_writes == 1:
                        raise OSError('document checkpoint before commit')
                await persist_checkpoint(context, value, **kwargs)
                if value.phase == 'completed':
                    raise OSError('document checkpoint response lost')
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', document_checkpoint_response_lost)
            with pytest.raises(OSError, match='document checkpoint before commit'):
                await runtime._finalize_reporting_sections(run_context, **finalize_options)
            with pytest.raises(OSError, match='document checkpoint response lost'):
                await runtime._finalize_reporting_sections(run_context, **finalize_options)
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
            finished_checkpoint, manifest = await runtime._finalize_reporting_sections(run_context, **finalize_options)
            assert finished_checkpoint.phase == 'completed'
            assert manifest.report_id == 'run-basis' and manifest.revision == next_execution.output_revision
            assert manifest.report_basis_id == next_execution.basis_id
            assert manifest.markdown.path == finalize_options['markdown_path']
            markdown = (await runtime._read_identity_bytes(scope['threadId'], FileIdentity(
                path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256))).decode()
            assert '300' in markdown and '正式计算结果见下表' in markdown
            assert manifest.trace_index is not None
            from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
            index = await runtime._read_identity_model(scope['threadId'], FileIdentity(
                path=manifest.trace_index.path, size=manifest.trace_index.size,
                sha256=manifest.trace_index.sha256), RevisionTraceIndexV1)
            assert index.report_basis_id == next_execution.basis_id
            assert {item.dataset_id for item in index.datasets} == {item.dataset_id for item in document_handles}
            assert index.tables
            assert all(item.fact_key != 'original-fact' for table in index.tables for cell in table.cells for item in cell.fact_refs)
            child_document = await rebuilt.get(next_execution.execution_run_id)
            assert child_document.payload['result']['markdown']['sha256'] == manifest.markdown.sha256
            assert await runtime._finalize_reporting_sections(run_context, **finalize_options) == (finished_checkpoint, manifest)
            assert (await rebuilt.get(next_execution.execution_run_id)).payload == child_document.payload
            await runtime.workspace_service.awrite_bytes(scope['threadId'], manifest.markdown.path, b'changed', overwrite=True)
            with pytest.raises(ReportingError):
                await runtime._finalize_reporting_sections(run_context, **finalize_options)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], manifest.markdown.path, markdown.encode(), overwrite=True)
            from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
            from smart_reporting.reporting.workspace import WorkspaceReportService

            runtime.delivery_settings = ReportDeliverySettings()
            runtime.report_public_base_url = ''
            runtime.report_tools = WorkspaceReportService(runtime.workspace_service)
            native_document_render = runtime.report_tools._render_report_pair
            document_render_calls = 0
            async def document_render_response_lost(*args, **kwargs):
                nonlocal document_render_calls
                document_render_calls += 1
                await native_document_render(*args, **kwargs)
                raise OSError('native document render response lost after atomic publication')
            monkeypatch.setattr(runtime.report_tools, '_render_report_pair', document_render_response_lost)
            apply_document_command = runtime._apply_durable_command
            async def document_completion_response_lost(context, command, **kwargs):
                saved = await apply_document_command(context, command, **kwargs)
                if command.command_id.startswith('revision-document-render-complete:'):
                    raise OSError('document completion response lost')
                return saved
            monkeypatch.setattr(runtime, '_apply_durable_command', document_completion_response_lost)
            uncertain_document = await runtime._render_and_validate(run_context, execution=next_execution)
            assert uncertain_document['validation']['ok'] is False
            assert any(issue['code'] == 'document_result_checkpoint_unavailable'
                for issue in uncertain_document['validationIssues'])
            assert any(issue['code'] == 'document_validation_receipt_unavailable'
                for issue in uncertain_document['validationIssues'])
            monkeypatch.setattr(runtime, '_apply_durable_command', apply_document_command)
            rendered_document = await runtime._render_and_validate(run_context, execution=next_execution)
            assert rendered_document['revision'] == next_execution.output_revision
            assert rendered_document['jobId'] not in before_session.get('report_jobs', {})
            for label, suffix in (('pdf', '.pdf'), ('word', '.docx')):
                path = rendered_document[f'{label}Path']
                assert path.endswith(suffix) and next_execution.execution_run_id in path
                actual = await runtime.workspace_service.ahash_file(scope['threadId'], path)
                assert actual['sha256'] == rendered_document[f'{label}Sha256']
            from io import BytesIO

            from docx import Document
            from pypdf import PdfReader

            pdf, _ = await runtime.workspace_service.afile_bytes(scope['threadId'], rendered_document['pdfPath'])
            word, _ = await runtime.workspace_service.afile_bytes(scope['threadId'], rendered_document['wordPath'])
            assert PdfReader(BytesIO(pdf)).pages
            document = Document(BytesIO(word))
            assert any('300' in cell.text for table in document.tables for row in table.rows for cell in row.cells)
            assert run_context.session_state == before_session
            original_render = runtime.report_tools._render_report_pair
            async def must_not_render_again(*args, **kwargs):
                raise AssertionError('registered document must restore without rendering or source reads')
            monkeypatch.setattr(runtime.report_tools, '_render_report_pair', must_not_render_again)
            target_csv = document_handles[0]
            csv_bytes, _ = await runtime.workspace_service.afile_bytes(scope['threadId'], target_csv.path)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, b'changed', overwrite=True)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], manifest.markdown.path, b'changed', overwrite=True)
            assert await runtime._render_and_validate(run_context, execution=next_execution) == rendered_document
            get_document_state = runtime.state_repository.get
            for bad_receipt in (None, {**rendered_document, 'jobId': 'foreign-document-job'}):
                async def document_without_receipt(run_id):
                    state = await get_document_state(run_id)
                    if run_id == next_execution.execution_run_id:
                        state = state.model_copy(update={'payload': {**state.payload, 'result': {
                            **state.payload['result'], 'renderedDocument': bad_receipt}}})
                    return state
                monkeypatch.setattr(runtime.state_repository, 'get', document_without_receipt)
                degraded = await runtime._render_and_validate(run_context, execution=next_execution)
                assert degraded['validation']['ok'] is False
                assert degraded['validationIssues'][0]['code'] == 'document_validation_receipt_unavailable'
                assert degraded['pdfSha256'] == rendered_document['pdfSha256']
                assert degraded['wordSha256'] == rendered_document['wordSha256']
            monkeypatch.setattr(runtime.state_repository, 'get', get_document_state)
            async def unregistered_document_outputs(run_id):
                state = await get_document_state(run_id)
                if run_id == next_execution.execution_run_id:
                    state = state.model_copy(update={'payload': {**state.payload, 'artifacts': [
                        item for item in state.payload['artifacts'] if item['path'] not in {
                            rendered_document['pdfPath'], rendered_document['wordPath']}],
                        'result': {key: value for key, value in state.payload['result'].items()
                            if key != 'renderedDocument'}}})
                return state
            monkeypatch.setattr(runtime.state_repository, 'get', unregistered_document_outputs)
            with pytest.raises(ReportingError, match='report_revision_document_outcome_unknown'):
                await runtime._render_and_validate(run_context, execution=next_execution)
            monkeypatch.setattr(runtime.state_repository, 'get', get_document_state)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered_document['pdfPath'], b'changed', overwrite=True)
            isolated_document = await runtime._render_and_validate(run_context, execution=next_execution)
            assert 'pdfPath' not in isolated_document
            assert isolated_document['wordSha256'] == rendered_document['wordSha256']
            assert isolated_document['validation']['ok'] is False
            assert any(issue['code'] == 'report_pdf_artifact_unavailable' for issue in isolated_document['validationIssues'])
            await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered_document['pdfPath'], pdf, overwrite=True)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, csv_bytes, overwrite=True)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], manifest.markdown.path, markdown.encode(), overwrite=True)
            monkeypatch.setattr(runtime.report_tools, '_render_report_pair', original_render)
            resumed_document = await continue_revision_delivery(runtime, run_context, next_execution)
            assert resumed_document.content['pdfSha256'] == rendered_document['pdfSha256']
            assert resumed_document.content['wordSha256'] == rendered_document['wordSha256']
            assert document_render_calls == 1
            publication = await runtime.publish_report(StepInput(input='发布新修订'), run_context, execution=next_execution)
            assert publication.content['revision'] == next_execution.output_revision
            assert publication.content['reportId'] == 'run-basis'
            assert publication.content['pdfSha256'] == rendered_document['pdfSha256']
            assert publication.content['wordSha256'] == rendered_document['wordSha256']
            assert publication.content['artifactManifest']['sha256'] == (await rebuilt.get(next_execution.execution_run_id)).payload['result']['manifest']['sha256']
            assert publication.content['editorJob']['jobId'] == rendered_document['jobId']
            assert publication.content['editorAvailable'] is True
            assert run_context.session_state == before_session and document_render_calls == 1
            await check_http_publication(publication)
            counter_before_replay = (await rebuilt.get('run-basis')).payload['reportEditorRevisionCounter']
            assert await runtime.publish_report(StepInput(input='读回发布'), run_context, execution=next_execution) == publication
            await check_http_publication(publication)
            assert (await rebuilt.get('run-basis')).payload['reportEditorRevisionCounter'] == counter_before_replay
            document_state = await rebuilt.get(next_execution.execution_run_id)
            for suffix, expected_issue in (
                ('.job.json', 'revision_publication_editor_job_unavailable'),
                ('/dataset-contexts.json', 'revision_publication_editor_job_unavailable'),
                ('/report.manifest.json', 'revision_publication_manifest_unavailable'),
            ):
                file = next(FileIdentity.model_validate(item) for item in document_state.payload['artifacts']
                    if item['path'].endswith(suffix))
                original_bytes = await runtime._read_identity_bytes(scope['threadId'], file)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], file.path, b'changed', overwrite=True)
                unavailable = await runtime.publish_report(StepInput(input='恢复故障'), run_context, execution=next_execution)
                assert unavailable.content['editorAvailable'] is False
                assert unavailable.content['pdfSha256'] == rendered_document['pdfSha256']
                assert any(item['code'] == expected_issue for item in unavailable.content['publicationGate']['issues'])
                await check_http_publication(unavailable, editor_available=False)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], file.path, original_bytes, overwrite=True)
            assert document_render_calls == 1
            monkeypatch.setattr(runtime.report_tools, '_render_report_pair', native_document_render)
            parent_execution = await exercise_refresh_task()
        if next_execution.requested_outputs == ('pptx',):
            from smart_reporting.reporting.workflow.runtime.slides import SlideOutline
            async def slide_checkpoint_response_lost(context, value, **kwargs):
                await persist_checkpoint(context, value, **kwargs)
                if value.slide_outline_file is not None:
                    raise OSError('slide checkpoint response lost')
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', slide_checkpoint_response_lost)
            with pytest.raises(OSError, match='slide checkpoint response lost'):
                await runtime.generate_slide_outline(StepInput(input='幻灯片'), run_context, execution=next_execution)
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
            slide_result = await runtime.generate_slide_outline(StepInput(input='恢复幻灯片'), run_context, execution=next_execution)
            assert slide_result.content['slideCount'] > 0
            slide_state = await rebuilt.get(next_execution.execution_run_id)
            slide_checkpoint = ReportingCheckpoint.model_validate(slide_state.payload['workflowCheckpoint'])
            slide_outline = await runtime._read_identity_model(scope['threadId'], slide_checkpoint.slide_outline_file, SlideOutline)
            assert slide_outline.snapshot_hash == planned_checkpoint.finding_graph_hash
            assert all(set(slide.evidence_ids) <= {'analysis_001', *(item.citation_id for item in citations)}
                for slide in slide_outline.slides)
            assert slide_checkpoint.slide_outline_file.model_dump(mode='json', by_alias=True) in slide_state.payload['artifacts']
            assert await runtime.generate_slide_outline(StepInput(input='恢复幻灯片'), run_context, execution=next_execution) == slide_result
            from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
            from smart_reporting.reporting.delivery.draft_v1 import HeadingNumber
            from smart_reporting.reporting.workflow.query_pipeline import DatasetLineage
            next_handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=next_execution.report_revision)
            next_lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
                requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
                size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
                for item in next_handles)
            markdown_identity = await runtime._write_immutable_artifact(scope['threadId'],
                f'报表/智能分析/{next_execution.execution_run_id}/manifest-contract/revision-{next_execution.output_revision}/report.md', b'# Refreshed report\n\n## 1 Results\n')
            manifest_path = f'报表/智能分析/{next_execution.execution_run_id}/manifest-contract/revision-{next_execution.output_revision}/report.manifest.json'
            manifest = await runtime._build_and_write_artifact_manifest(manifest_path,
                accepted_artifacts=[markdown_identity.model_dump(mode='json', by_alias=True)],
                handles=next_handles, fact_files={key: ArtifactFile(**item.model_dump(), mediaType='application/json')
                    for key, item in planned_checkpoint.deterministic_fact_files.items()},
                markdown_path=markdown_identity.path, lineage=next_lineage, revision=next_execution.output_revision,
                task_key='refreshed-pptx', section_numbers=tuple(item.section_number for item in current_outline.sections),
                heading_numbers=tuple(HeadingNumber(level=2, number=item.section_number, title=item.title,
                    sectionCode=item.code, anchor=f'report-section-{item.code}') for item in current_outline.sections),
                run_context=run_context, execution=next_execution)
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime._build_and_write_artifact_manifest('original/report.manifest.json',
                    accepted_artifacts=[markdown_identity.model_dump(mode='json', by_alias=True)],
                    handles=next_handles, fact_files={key: ArtifactFile(**item.model_dump(), mediaType='application/json')
                        for key, item in planned_checkpoint.deterministic_fact_files.items()},
                    markdown_path=markdown_identity.path, lineage=next_lineage, revision=next_execution.output_revision,
                    task_key='refreshed-pptx', section_numbers=(), heading_numbers=(),
                    run_context=run_context, execution=next_execution)
            assert manifest.report_id == 'run-basis' and manifest.revision == next_execution.output_revision
            assert manifest.report_basis_id == next_execution.basis_id
            assert manifest.trace_index is not None
            from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
            trace_identity = FileIdentity(path=manifest.trace_index.path, size=manifest.trace_index.size,
                sha256=manifest.trace_index.sha256)
            index = await runtime._read_identity_model(scope['threadId'], trace_identity, RevisionTraceIndexV1)
            assert index.report_id == 'run-basis' and index.revision == next_execution.output_revision
            assert index.report_basis_id == next_execution.basis_id
            assert {item.dataset_id for item in index.datasets} == {item.dataset_id for item in next_handles}
            slide_bytes = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                slide_checkpoint.slide_outline_file.path, max_bytes=slide_checkpoint.slide_outline_file.size)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], slide_checkpoint.slide_outline_file.path,
                b'{}', overwrite=True)
            with pytest.raises(ReportingError):
                await runtime.generate_slide_outline(StepInput(input='损坏幻灯片'), run_context, execution=next_execution)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], slide_checkpoint.slide_outline_file.path,
                slide_bytes, overwrite=True)
            async def assembled_checkpoint_response_lost(context, value, **kwargs):
                await persist_checkpoint(context, value, **kwargs)
                if value.phase == 'completed':
                    raise OSError('assembled checkpoint response lost')
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', assembled_checkpoint_response_lost)
            with pytest.raises(OSError, match='assembled checkpoint response lost'):
                await runtime.assemble_slides(StepInput(input='组装新幻灯片'), run_context, execution=next_execution)
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
            assembled = await runtime.assemble_slides(StepInput(input='恢复组装'), run_context, execution=next_execution)
            assert next_execution.execution_run_id in assembled.content['markdownPath']
            assembled_state = await rebuilt.get(next_execution.execution_run_id)
            assert assembled_state.payload['result']['markdown']['path'] == assembled.content['markdownPath']
            assert await runtime.assemble_slides(StepInput(input='恢复组装'), run_context, execution=next_execution) == assembled
            from io import BytesIO

            from pptx import Presentation

            from smart_reporting.reporting.workflow.runtime import publication

            native_command = runtime._apply_durable_command
            render_calls = []
            native_build = publication.build_editable_pptx
            def counted_build(**kwargs):
                render_calls.append(kwargs)
                return native_build(**kwargs)
            monkeypatch.setattr(publication, 'build_editable_pptx', counted_build)
            async def rendered_response_lost(context, command, **kwargs):
                saved = await native_command(context, command, **kwargs)
                if command.command_id.startswith('revision-pptx-complete:'):
                    raise OSError('render completion response lost')
                return saved
            monkeypatch.setattr(runtime, '_apply_durable_command', rendered_response_lost)
            rendered = (await runtime.validate_slides(StepInput(input='渲染新PPTX'), run_context,
                execution=next_execution)).content
            assert rendered['status'] == 'validation_failed'
            assert rendered['pptxSize'] > 0
            assert rendered['validation']['claimSupport']
            assert not any(item['code'] == 'native_claim_support_unavailable' for item in rendered['validation']['issues'])
            assert next_execution.execution_run_id in rendered['pptxPath']
            content = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                rendered['pptxPath'], max_bytes=rendered['pptxSize'])
            deck = Presentation(BytesIO(content))
            assert len(deck.slides) == slide_result.content['slideCount'] + 1  # 原生引擎包含封面
            notes = '\n'.join(slide.notes_slide.notes_text_frame.text for slide in deck.slides)
            assert 'analysis_001' in notes
            assert all(item.citation_id in notes for item in citations)
            assert '[2026-11-01, 2026-12-01)' in '\n'.join(
                shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
            monkeypatch.setattr(runtime, '_apply_durable_command', native_command)
            recovered = (await runtime.validate_slides(StepInput(input='恢复新PPTX'), run_context,
                execution=next_execution)).content
            assert recovered['pptxSha256'] == rendered['pptxSha256']
            assert recovered['validation']['ok'] is True
            published = await continue_revision_delivery(runtime, run_context, next_execution)
            assert published.content['revision'] == next_execution.output_revision
            assert published.content['reportId'] == 'run-basis'
            assert published.content['pptxSha256'] == recovered['pptxSha256']
            assert published.content['artifactManifest']['sha256'] == assembled_state.payload['result']['manifest']['sha256']
            assert published.content['editorAvailable'] is True
            await check_http_publication(published)
            assert run_context.session_state == before_session
            assert len(render_calls) == 1
            assert (await rebuilt.get(next_execution.execution_run_id)).payload['result']['renderedPptx'] == recovered
            target_csv = next_handles[0]
            original_csv = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                target_csv.path, max_bytes=target_csv.size)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, b'changed', overwrite=True)
            with pytest.raises(ReportingError):
                await runtime._metric_planning_context(run_context, report_revision=next_execution.report_revision)
            frozen_markdown = assembled_state.payload['result']['markdown']
            original_markdown = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                frozen_markdown['path'], max_bytes=frozen_markdown['size'])
            await runtime.workspace_service.awrite_bytes(scope['threadId'], frozen_markdown['path'], b'changed', overwrite=True)
            source_unavailable = (await runtime.validate_slides(StepInput(input='恢复已生成文件'), run_context,
                execution=next_execution)).content
            assert source_unavailable['pptxSha256'] == rendered['pptxSha256']
            assert len(render_calls) == 1
            await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, original_csv, overwrite=True)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], frozen_markdown['path'], original_markdown, overwrite=True)
            from smart_reporting.reporting.workflow import revision_execution as execution_module
            require_execution = execution_module.require_revision_execution
            async def missing_render_receipt(*args, **kwargs):
                stored = await require_execution(*args, **kwargs)
                payload = {**stored.payload, 'result': {key: value for key, value in stored.payload['result'].items()
                    if key != 'renderedPptx'}}
                return stored.model_copy(update={'payload': payload})
            monkeypatch.setattr(execution_module, 'require_revision_execution', missing_render_receipt)
            unavailable = (await runtime.validate_slides(StepInput(input='恢复缺失验收记录'), run_context,
                execution=next_execution)).content
            assert unavailable['pptxSha256'] == rendered['pptxSha256']
            assert unavailable['validation']['ok'] is False
            assert unavailable['validationIssues'][0]['code'] == 'pptx_validation_receipt_unavailable'
            async def foreign_render_receipt(*args, **kwargs):
                stored = await require_execution(*args, **kwargs)
                return stored.model_copy(update={'payload': {**stored.payload,
                    'result': {**stored.payload['result'], 'renderedPptx': {
                        **recovered, 'pptxPath': 'foreign/report.pptx'}}}})
            monkeypatch.setattr(execution_module, 'require_revision_execution', foreign_render_receipt)
            invalid_receipt = (await runtime.validate_slides(StepInput(input='拒绝串用验收回执'), run_context,
                execution=next_execution)).content
            assert invalid_receipt['pptxPath'] == rendered['pptxPath']
            assert invalid_receipt['pptxSha256'] == rendered['pptxSha256']
            assert invalid_receipt['validation']['ok'] is False
            async def unregistered_render_file(*args, **kwargs):
                stored = await require_execution(*args, **kwargs)
                return stored.model_copy(update={'payload': {**stored.payload,
                    'artifacts': [item for item in stored.payload['artifacts'] if item.get('path') != rendered['pptxPath']]}})
            monkeypatch.setattr(execution_module, 'require_revision_execution', unregistered_render_file)
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime.validate_slides(StepInput(input='拒绝覆盖未知PPTX'), run_context, execution=next_execution)
            assert len(render_calls) == 1
            monkeypatch.setattr(execution_module, 'require_revision_execution', require_execution)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered['pptxPath'], b'changed', overwrite=True)
            with pytest.raises(ReportingError):
                await runtime.validate_slides(StepInput(input='拒绝已替换PPTX'), run_context, execution=next_execution)
            await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered['pptxPath'], content, overwrite=True)
            parent_execution = await exercise_refresh_task()
        elif next_execution.requested_outputs == ('xlsx',):
            import json
            import subprocess
            import sys
            import zipfile
            from io import BytesIO

            from openpyxl import load_workbook

            from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
            from smart_reporting.reporting.code_mode import ScriptProcessResult
            from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
                ToolkitRuntime,
            )

            class LocalWorkbookRuntime(ToolkitRuntime):
                def __init__(self):
                    super().__init__()
                    self.executions = []
                async def execute_script_process(self, session_id, host, path, **_kwargs):
                    self.executions.append(session_id)
                    process = subprocess.run([sys.executable, path], cwd=host.identity.root,
                        capture_output=True, text=True)
                    return ScriptProcessResult(SimpleNamespace(
                        status='ok' if process.returncode == 0 else 'error', stdout=process.stdout,
                        stderr=process.stderr, traceback=None), process.returncode)
            local_runtime = LocalWorkbookRuntime()
            runtime.code_mode_runtime = local_runtime
            monkeypatch.setattr(runtime, '_run_workspace', lambda _context: runtime.workspace_service.workspace(scope['threadId']))
            manager = ReportingLspProcessManager(command=('false',), request_timeout_seconds=0.2)
            runtime.lsp_manager = manager
            from smart_reporting.reporting.workflow import revision_execution as execution_module
            from smart_reporting.reporting.workflow.revision_execution import (
                assemble_revision_workbook,
                continue_revision_delivery,
            )

            apply_command = execution_module.apply_revision_execution_command
            async def assembly_complete_response_lost(*args, **kwargs):
                result = await apply_command(*args, **kwargs)
                if args[3].name == 'complete':
                    raise OSError('workbook completion committed but response lost')
                return result
            monkeypatch.setattr(execution_module, 'apply_revision_execution_command', assembly_complete_response_lost)
            with pytest.raises(OSError, match='workbook completion committed'):
                await continue_revision_delivery(runtime, run_context, next_execution)
            monkeypatch.setattr(execution_module, 'apply_revision_execution_command', apply_command)
            async def assembly_checkpoint_unavailable(*args, **kwargs):
                raise OSError('workbook checkpoint before commit')
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', assembly_checkpoint_unavailable)
            with pytest.raises(OSError, match='workbook checkpoint before commit'):
                await continue_revision_delivery(runtime, run_context, next_execution)
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
            workbook_checkpoint, workbook_manifest = await assemble_revision_workbook(runtime, run_context, next_execution)
            assert workbook_checkpoint.phase == 'completed'
            assert not workbook_checkpoint.completed_sections
            assert workbook_checkpoint.workbook_summary_files
            from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
            workbook_index = await runtime._read_identity_model(scope['threadId'],
                workbook_manifest.trace_index, RevisionTraceIndexV1)
            assert any(item.narrative_reference and item.narrative_reference.analysis_id == 'analysis_001'
                for item in workbook_index.subject_bindings)
            assert workbook_manifest.report_basis_id == next_execution.basis_id
            assert workbook_manifest.revision == next_execution.output_revision
            assert await assemble_revision_workbook(runtime, run_context, next_execution) == (workbook_checkpoint, workbook_manifest)
            request_result = {'revision': next_execution.output_revision,
                'datasets': [{'datasetId': 'original-forged'}], 'workbookSources': [{'factId': 'original-forged'}]}
            async def workbook_checkpoint_response_lost(context, value, **kwargs):
                await persist_checkpoint(context, value, **kwargs)
                if any(item.path.endswith('.xlsx.receipt.json') for item in value.files):
                    raise OSError('workbook checkpoint response lost')
            monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', workbook_checkpoint_response_lost)
            try:
                delivery = await continue_revision_delivery(runtime, run_context, next_execution)
                rendered = delivery.content
                assert rendered['status'] == 'validation_failed'
                assert rendered['xlsxSize'] > 0
                assert rendered['validation']['claimSupport']
                assert not any(item['code'] == 'native_claim_support_unavailable' for item in rendered['validation']['issues'])
                assert next_execution.execution_run_id in rendered['xlsxPath']
                content = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                    rendered['xlsxPath'], max_bytes=rendered['xlsxSize'])
                book = load_workbook(BytesIO(content), data_only=True)
                assert book['汇总']['D2'].value == 300
                section_sheet = book.worksheets[1]
                assert section_sheet['C2'].value == 300
                assert section_sheet['H2'].value == '已计算'
                assert section_sheet['E2'].value == '[2026-11-01, 2026-12-01)'
                book.close()
                with zipfile.ZipFile(BytesIO(content)) as package:
                    mapping = json.loads(package.read('smart-reporting/source-mapping.json'))['sources']
                target_handles = await runtime._registered_metric_dataset_handles(run_context, report_revision=next_execution.report_revision)
                assert set(mapping['datasets']) == {item.dataset_id for item in target_handles}
                assert {item['basisId'] for item in mapping['cells']} == {next_execution.basis_id}
                assert all(item['factId'] != 'original-fact' for item in mapping['cells'])
                assert all(mapping['datasets'][item.dataset_id]['sha256'] == item.sha256 for item in target_handles)
                monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist_checkpoint)
                recovered = await runtime._render_xlsx(run_context, dict(request_result), current_outline, execution=next_execution)
                assert recovered['xlsxSha256'] == rendered['xlsxSha256']
                assert recovered['validation']['ok'] is True
                published = await continue_revision_delivery(runtime, run_context, next_execution)
                assert published.content['xlsxSha256'] == recovered['xlsxSha256']
                assert published.content['revision'] == next_execution.output_revision
                assert published.content['editorJob']['workbookSources'] == recovered['workbookSources']
                await check_http_publication(published)
                assert len(local_runtime.executions) == 1
                assert next_execution.execution_run_id in local_runtime.executions[0]
                assert local_runtime.shutdowns == local_runtime.executions
                target_csv = target_handles[0]
                original_csv = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                    target_csv.path, max_bytes=target_csv.size)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, b'changed', overwrite=True)
                with pytest.raises(ReportingError):
                    await runtime._metric_planning_context(run_context, report_revision=next_execution.report_revision)
                source_unavailable = (await continue_revision_delivery(runtime, run_context, next_execution)).content
                assert source_unavailable['xlsxSha256'] == rendered['xlsxSha256']
                assert len(local_runtime.executions) == 1
                restored_checkpoint, restored_manifest = await assemble_revision_workbook(runtime, run_context, next_execution)
                assert restored_checkpoint.phase == 'completed' and restored_manifest == workbook_manifest
                await runtime.workspace_service.awrite_bytes(scope['threadId'], target_csv.path, original_csv, overwrite=True)
                child_state = await rebuilt.get(next_execution.execution_run_id)
                files = child_state.payload['artifacts']
                assert any(item['path'] == rendered['xlsxPath'] for item in files)
                assert any(item['path'].endswith('.xlsx.receipt.json') for item in files)
                assert all(item.get('datasetId') != 'original-forged' for item in recovered.get('datasets', ()))
                from smart_reporting.reporting.workflow import (
                    revision_execution as execution_module,
                )
                require_execution = execution_module.require_revision_execution
                async def missing_workbook_receipt(*args, **kwargs):
                    stored = await require_execution(*args, **kwargs)
                    return stored.model_copy(update={'payload': {**stored.payload,
                        'artifacts': [item for item in stored.payload['artifacts']
                            if not item.get('path', '').endswith('.xlsx.receipt.json')]}})
                monkeypatch.setattr(execution_module, 'require_revision_execution', missing_workbook_receipt)
                unavailable = await runtime._render_xlsx(run_context, dict(request_result), current_outline, execution=next_execution)
                assert unavailable['xlsxSha256'] == rendered['xlsxSha256']
                assert unavailable['validation']['ok'] is False
                assert unavailable['validationIssues'][0]['code'] == 'xlsx_validation_receipt_unavailable'
                assert not unavailable.get('workbookSources') and not unavailable.get('datasets')
                unavailable_publication = await runtime.publish_report(StepInput(input='回执缺失仍下载'), run_context, execution=next_execution)
                assert unavailable_publication.content['editorAvailable'] is False
                assert unavailable_publication.content['xlsxSha256'] == rendered['xlsxSha256']
                await check_http_publication(unavailable_publication, editor_available=False)
                async def unknown_workbook_file(*args, **kwargs):
                    stored = await require_execution(*args, **kwargs)
                    return stored.model_copy(update={'payload': {**stored.payload,
                        'artifacts': [item for item in stored.payload['artifacts'] if item.get('path') != rendered['xlsxPath']]}})
                monkeypatch.setattr(execution_module, 'require_revision_execution', unknown_workbook_file)
                with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                    await runtime._render_xlsx(run_context, dict(request_result), current_outline, execution=next_execution)
                monkeypatch.setattr(execution_module, 'require_revision_execution', require_execution)
                receipt_file = next(item for item in files if item['path'].endswith('.xlsx.receipt.json'))
                receipt_bytes = await runtime.workspace_service.read_limited_regular_file(scope['threadId'],
                    receipt_file['path'], max_bytes=receipt_file['size'])
                await runtime.workspace_service.awrite_bytes(scope['threadId'], receipt_file['path'], b'changed', overwrite=True)
                changed_receipt = await runtime._render_xlsx(run_context, dict(request_result), current_outline, execution=next_execution)
                assert changed_receipt['xlsxSha256'] == rendered['xlsxSha256']
                assert changed_receipt['validation']['ok'] is False and not changed_receipt.get('workbookSources')
                changed_publication = await runtime.publish_report(StepInput(input='回执损坏仍下载'), run_context, execution=next_execution)
                assert changed_publication.content['editorAvailable'] is False
                assert changed_publication.content['xlsxSha256'] == rendered['xlsxSha256']
                await check_http_publication(changed_publication, editor_available=False)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], receipt_file['path'], receipt_bytes, overwrite=True)
                with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                    await runtime._draft_workbook(run_context, spec_path='original/spec.json',
                        output_path='original/report.xlsx', execution=next_execution)
                with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                    await runtime._render_xlsx(run_context, {'revision': next_execution.output_revision + 1},
                        current_outline, execution=next_execution)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered['xlsxPath'], b'changed', overwrite=True)
                with pytest.raises(ReportingError):
                    await runtime._render_xlsx(run_context, dict(request_result), current_outline, execution=next_execution)
                await runtime.workspace_service.awrite_bytes(scope['threadId'], rendered['xlsxPath'], content, overwrite=True)
                assert len(local_runtime.executions) == 1
                parent_execution = await exercise_refresh_task()
                assert len(local_runtime.executions) == 2
            finally:
                await manager.aclose()
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime.generate_slide_outline(StepInput(input='错误格式'), run_context, execution=next_execution)
        else:
            with pytest.raises(ReportingError, match='report_revision_execution_mismatch'):
                await runtime.generate_slide_outline(StepInput(input='错误格式'), run_context, execution=next_execution)
        delivered_checkpoint = (await rebuilt.get(next_execution.execution_run_id)).payload['workflowCheckpoint']
        assert await prepare_refresh_delivery(runtime, run_context,
            parent_report_revision=next_execution.parent_report_revision, report_revision=next_execution.report_revision) == next_execution
        assert (await rebuilt.get(next_execution.execution_run_id)).payload['workflowCheckpoint'] == delivered_checkpoint
        assert run_context.session_state == before_session
        assert (await rebuilt.get('run-basis')).payload['workflowCheckpoint'] == original_checkpoint
        plan_parent = parent_execution
        plan_path = f'报表/智能分析/run-basis/revision-executions/{plan_parent.execution_run_id}/detailed-plan.json'
        await runtime.workspace_service.awrite_bytes(scope['threadId'], plan_path, b'{}', overwrite=True)
        with pytest.raises(ReportingError):
            await restore_refresh_analysis_plan(runtime, run_context, next_execution)
        assert len(queries) == 3
        for worker in refresh_workers:
            await worker.stop()
        from smart_reporting.tests.policy_adoption_public_flow import (
            exercise_public_policy_adoption,
        )

        source_editor = (await rebuilt.get('run-basis')).payload['reportEditorContexts'][str(next_execution.output_revision)]
        await exercise_public_policy_adoption(runtime, database, context, source_editor,
            refresh_context[3], queries, monkeypatch, recover_preparation=recover_preparation)

    finally:
        from sqlalchemy import delete, or_, select
        for worker in refresh_workers:
            await worker.stop()
        repository = runtime.state_repository
        original = await repository.get('run-basis')
        if original:
            for task_id in original.payload.get('reportEditorRecalculations', {}):
                await database.async_db.delete_session('report-editor-' + task_id)
        jobs = await database.async_db._get_table(table_type='jobs')
        async with database.async_engine.begin() as connection:
            if original and jobs is not None:
                session_ids = ['report-editor-' + task_id for task_id in original.payload.get('reportEditorRecalculations', {})]
                await connection.execute(delete(jobs).where(jobs.c.session_id.in_(session_ids)))
            ids = tuple((await connection.scalars(select(repository.runs.c.report_run_id).where(or_(
                repository.runs.c.report_run_id == 'run-basis', repository.runs.c.caller_run_id == 'run-basis')))).all())
            await connection.execute(delete(repository.command_receipts).where(repository.command_receipts.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.states).where(repository.states.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.runs).where(repository.runs.c.report_run_id.in_(ids)))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.parametrize('refresh_context', [{'outputs': ['pdf', 'docx']}, {'outputs': ['pptx']},
    {'outputs': ['xlsx']}], indirect=True)
async def test_policy_adoption_prepares_new_run_scope_without_old_results(refresh_context, monkeypatch):
    import os
    from copy import deepcopy

    from agno.run import RunContext
    from sqlalchemy import delete, update

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.basis import BasisSelectionReceipt
    from smart_reporting.reporting.workflow.policy_adoption import (
        policy_adoption_run_context,
        prepare_policy_adoption_execution,
        require_policy_adoption_execution,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY
    from smart_reporting.reporting.workflow.state import ReportingRunState
    from smart_reporting.runtime.database import create_agent_database
    from smart_reporting.tests.test_report_basis_persistence import build_identity

    service, context, _, _, queries, options = refresh_context
    policies = context['policy_service']
    current = await policies.get(context['token'], context['scope'], 'monthly-budget')
    changed = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    await policies.save_draft(context['token'], context['scope'], {**changed, 'name': '新口径执行准备'}, expected_version=1)
    await policies.publish(context['token'], context['scope'], 'monthly-budget', expected_version=2)
    preview = await service.preview_policy_adoption('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        policy_version={'policyId': 'monthly-budget', 'revision': 2})
    receipt = await service.register_policy_adoption('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        confirmation={'requestId': 'prepare-adoption', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
            'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
                'metricVersion': {'metricId': 'budget', 'revision': 1}, 'reason': '明确采用预算指标，不认定已回答完整执行率。'}]},
        build_identity=build_identity())
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    repository = ReportingStateRepository(database.async_db)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository, runtime.report_basis_service = repository, service
    runtime.workspace_service = options['dataset_store'].service
    runtime.workspace_registry = runtime.workspace_service.registry
    scope = options['workflow_scope']
    run_context = RunContext(run_id='run-basis', session_id=scope.session_id, user_id='7',
        session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: scope.as_state(), 'oldDatasets': ['forbidden-old-id']})
    before_session = deepcopy(run_context.session_state)
    try:
        await repository.register_run(report_run_id='run-basis', external_run_id=scope.external_run_id,
            agno_session_id=scope.session_id, agno_run_id='run-basis', thread_id=scope.caller_thread_id,
            owner_user_id='7', database=scope.database, company_id=scope.company_id, entrypoint='agentos')
        checkpoint = {'owner': 'original-report'}
        await repository.create(ReportingRunState.initial(report_run_id='run-basis', external_run_id=scope.external_run_id,
            thread_id=scope.caller_thread_id, owner_user_id='7', payload={'workflowCheckpoint': checkpoint,
                'oldOnly': 'must not be copied'}))
        outputs = (await service.load_report_basis(receipt.target_run_id, context['scope'], user_id='7',
            thread_id='thread-basis')).request_summary.requested_outputs
        create_state, audit = repository.get_or_create, service._audit
        if outputs == ('xlsx',):
            async def fail_selection_audit(connection, basis, action, **details):
                if action == 'report_adoption_selection_registered':
                    raise OSError('adoption preparation interrupted')
                return await audit(connection, basis, action, **details)
            monkeypatch.setattr(service, '_audit', fail_selection_audit)
        else:
            async def fail_state_response(**kwargs):
                if outputs == ('pptx',):
                    await create_state(**kwargs)
                raise OSError('adoption preparation interrupted')
            monkeypatch.setattr(repository, 'get_or_create', fail_state_response)
        with pytest.raises(OSError, match='adoption preparation interrupted'):
            await prepare_policy_adoption_execution(runtime, run_context, request_id='prepare-adoption')
        assert ((await repository.get(receipt.target_run_id)) is not None) == (outputs == ('pptx',))
        if outputs == ('xlsx',):
            assert await service.load_basis_receipts(receipt.target_run_id, context['scope'], user_id='7',
                thread_id='thread-basis', report_revision='initial') == ()
        monkeypatch.setattr(repository, 'get_or_create', create_state)
        monkeypatch.setattr(service, '_audit', audit)
        execution = await prepare_policy_adoption_execution(runtime, run_context, request_id='prepare-adoption')
        assert execution.basis_id == receipt.basis_id and execution.scope.run_id == receipt.target_run_id
        assert execution.scope.workspace_key != scope.workspace_key
        assert execution.scope.session_id != scope.session_id and execution.scope.user_id == scope.user_id
        assert execution.output_revision == 2
        adopted = await service.load_report_basis(receipt.target_run_id, context['scope'], user_id='7', thread_id='thread-basis')
        assert execution.requested_outputs == adopted.request_summary.requested_outputs
        child = await repository.get(receipt.target_run_id)
        assert child.payload['reportPolicyAdoptionExecution'] == execution.model_dump(mode='json', by_alias=True)
        assert 'oldOnly' not in child.payload and 'workflowCheckpoint' not in child.payload
        selections = await service.load_basis_receipts(receipt.target_run_id, context['scope'], user_id='7',
            thread_id='thread-basis', report_revision='initial')
        assert len(selections) == 1 and isinstance(selections[0], BasisSelectionReceipt)
        assert selections[0].receipt_id == 'initial-metric-selection' and selections[0].selections == receipt.selections
        runtime.state_repository = ReportingStateRepository(database.async_db)
        runtime.report_basis_service = ReportBasisService(context['scopes'])
        restored = await prepare_policy_adoption_execution(runtime, run_context, request_id='prepare-adoption')
        assert restored == execution
        fresh_context = policy_adoption_run_context(restored)
        assert set(fresh_context.session_state) == {REPORT_WORKFLOW_SCOPE_STATE_KEY}
        assert runtime._scope(fresh_context) == execution.scope.as_state()
        for changed_execution in (execution.model_copy(update={'basis_id': receipt.parent_basis_id}),
                execution.model_copy(update={'output_revision': execution.output_revision + 1}),
                execution.model_copy(update={'requested_outputs': ('pptx',) if outputs != ('pptx',) else ('xlsx',)})):
            with pytest.raises(ReportingError, match='report_policy_adoption_mismatch'):
                await require_policy_adoption_execution(runtime, run_context, changed_execution)
        async with database.async_engine.begin() as connection:
            await connection.execute(update(repository.runs).where(repository.runs.c.report_run_id == execution.scope.run_id)
                .values(owner_user_id='foreign-owner'))
        with pytest.raises(ReportingError, match='report_policy_adoption_mismatch'):
            await require_policy_adoption_execution(runtime, run_context, execution)
        assert run_context.session_state == before_session
        assert (await repository.get('run-basis')).payload['workflowCheckpoint'] == checkpoint
        assert queries == []
    finally:
        ids = ('run-basis', receipt.target_run_id)
        async with database.async_engine.begin() as connection:
            await connection.execute(delete(repository.command_receipts).where(repository.command_receipts.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.states).where(repository.states.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.runs).where(repository.runs.c.report_run_id.in_(ids)))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.fixture
async def adoption_calculation_context(refresh_context, request):
    from agno.run import RunContext

    from smart_reporting.reporting.workflow.policy_adoption import _target_scope
    from smart_reporting.tests.test_report_basis_persistence import build_identity

    service, context, original, engine, queries, options = refresh_context
    policies = context['policy_service']
    current = await policies.get(context['token'], context['scope'], 'monthly-budget')
    changed = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    await policies.save_draft(context['token'], context['scope'], {**changed, 'name': '新口径正式取数',
        'filters': [{'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A']}]}, expected_version=1)
    await policies.publish(context['token'], context['scope'], 'monthly-budget', expected_version=2)
    preview = await service.preview_policy_adoption('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        policy_version={'policyId': 'monthly-budget', 'revision': 2})
    adoption = await service.register_policy_adoption('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        confirmation={'requestId': 'calculate-adoption', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
            'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
                'metricVersion': None if getattr(request, 'param', '') == 'unavailable' else {'metricId': 'budget', 'revision': 1},
                'reason': '明确采用预算指标或明确暂无可用指标，不能认定已回答执行率。'}]},
        build_identity=build_identity())
    await service.register_adoption_selections('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        request_id='calculate-adoption')
    target = _target_scope(options['workflow_scope'], adoption.target_run_id)
    tool_context = RunContext(run_id=target.run_id, session_id=target.workspace_key, user_id='7', session_state={})
    kwargs = dict(user_id='7', thread_id='thread-basis', vault=context['vault'],
        dataset_store=options['dataset_store'], run_context=tool_context, workflow_scope=target)
    with engine.begin() as connection:
        connection.exec_driver_sql('UPDATE test.budget SET amount=amount*2')
    return service, context, original, queries, options, adoption, target, tool_context, kwargs


@pytest.mark.parametrize('refresh_context', [True], indirect=True)
@pytest.mark.parametrize('fault', ['none', 'before_result', 'after_result', 'intent_audit', 'second_before_result'])
async def test_adoption_calculates_fresh_selected_periods_without_unknown_requery(adoption_calculation_context, monkeypatch, fault):
    from smart_reporting.reporting.semantics.basis import BasisCalculationReceipt
    from smart_reporting.reporting.semantics.planning import build_metric_planning_context

    service, context, original, queries, options, adoption, target, tool_context, kwargs = adoption_calculation_context
    append, audit = service.append_basis_receipt, service._audit
    if fault in ('before_result', 'after_result', 'second_before_result'):
        async def lose_result(*args, **kw):
            if fault == 'second_before_result' and len(queries) == 1:
                return await append(*args, **kw)
            if fault == 'after_result':
                await append(*args, **kw)
            raise OSError('calculation response lost')
        monkeypatch.setattr(service, 'append_basis_receipt', lose_result)
    elif fault == 'intent_audit':
        async def lose_audit(connection, basis, action, **details):
            if action == 'report_adoption_calculation_requested':
                raise OSError('intent audit failed')
            return await audit(connection, basis, action, **details)
        monkeypatch.setattr(service, '_audit', lose_audit)
    if fault != 'none':
        with pytest.raises(OSError):
            await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
        assert len(queries) == (0 if fault == 'intent_audit' else 2 if fault == 'second_before_result' else 1)
        monkeypatch.setattr(service, 'append_basis_receipt', append)
        monkeypatch.setattr(service, '_audit', audit)
    service = ReportBasisService(context['scopes'])  # 新服务不能丢失已经提交的查询意图。
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.datasets import RuntimeDatasetsMixin

    async def load_execution(_context):
        return await service.load_execution_context(target.run_id, context['scope'], user_id='7',
            thread_id='thread-basis', vault=context['vault'])
    native = SimpleNamespace(report_basis_service=service, datasets=options['dataset_store'],
        configuration_provider=SimpleNamespace(vault=context['vault']),
        _basis_execution_context=load_execution, _scope=lambda _: target.as_state(), _tool_context=lambda _: tool_context)
    if fault in ('before_result', 'second_before_result'):
        with pytest.raises(ReportingError, match='management_adoption_outcome_unknown'):
            await RuntimeDatasetsMixin.calculate_report_metrics(native, None, tool_context)
        for _ in range(2):
            with pytest.raises(ManagementError) as unknown:
                await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
            assert unknown.value.code == 'management_adoption_outcome_unknown'
        assert len(queries) == (2 if fault == 'second_before_result' else 1)
        return
    if fault == 'none':
        await RuntimeDatasetsMixin.calculate_report_metrics(native, None, tool_context)
    results = await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
    assert len(results) == 2 and all(isinstance(item, BasisCalculationReceipt) for item in results)
    assert [item.results[0].value for item in results] == [Decimal(200), Decimal(300)]
    assert len(queries) == 2
    assert all(item.basis_id == adoption.basis_id and item.report_revision == 'initial' for item in results)
    assert all(item.results[0].fact_id != original.results[0].fact_id for item in results)
    assert all(item.datasets[0].file.path != original.datasets[0].file.path for item in results)
    assert await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs) == results
    assert len(queries) == 2
    execution = await service.load_execution_context(target.run_id, context['scope'], user_id='7', thread_id='thread-basis',
        vault=context['vault'])
    receipts = await service.load_basis_receipts(target.run_id, context['scope'], user_id='7', thread_id='thread-basis',
        report_revision='initial')
    planning = build_metric_planning_context(execution, receipts, report_revision='initial')
    assert len(planning.calculations) == 2 and planning.basis_id == adoption.basis_id
    assert original in await service.load_basis_receipts('run-basis', context['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')
    with pytest.raises(ManagementError):
        await service.calculate_adoption_metrics(target.run_id, context['other_scope'], **kwargs)
    with pytest.raises(ManagementError):
        await service.calculate_adoption_metrics(target.run_id, context['scope'], **{**kwargs, 'user_id': 'foreign'})
    with pytest.raises(ManagementError):
        await service.calculate_adoption_metrics(target.run_id, context['scope'], **{**kwargs,
            'run_context': options['run_context'], 'workflow_scope': options['workflow_scope']})
    assert len(queries) == 2
    native_result = await RuntimeDatasetsMixin.calculate_report_metrics(native, None, tool_context)
    assert native_result.content['calculations'] == [item.model_dump(mode='json', by_alias=True) for item in results]
    assert len(queries) == 2


@pytest.mark.parametrize('refresh_context', [True], indirect=True)
async def test_concurrent_adoption_does_not_repeat_started_query(adoption_calculation_context, monkeypatch):
    import asyncio

    service, context, _, queries, _, _, target, _, kwargs = adoption_calculation_context
    started, release = asyncio.Event(), asyncio.Event()
    materialize = StarRocksDataSourceAdapter.materialize_bound

    async def pause(adapter, *args, **options):
        started.set()
        await release.wait()
        return await materialize(adapter, *args, **options)

    monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', pause)
    first = asyncio.create_task(service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs))
    try:
        await asyncio.wait_for(started.wait(), 10)
        with pytest.raises(ManagementError, match='management_adoption_outcome_unknown'):
            await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
        assert queries == []
    finally:
        release.set()
        results = await first
    assert len(results) == 2 and len(queries) == 2
    snapshot = results[0].datasets[0]
    await kwargs['dataset_store'].service.awrite_bytes(target.workspace_key, snapshot.file.path,
        b'changed csv', overwrite=True)
    with pytest.raises(ManagementError, match='management_basis_snapshot_unavailable'):
        await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
    assert len(queries) == 2


@pytest.mark.parametrize('refresh_context', [True], indirect=True)
@pytest.mark.parametrize('adoption_calculation_context', ['unavailable'], indirect=True)
async def test_adoption_without_confirmed_metric_keeps_question_unavailable(adoption_calculation_context):
    from smart_reporting.reporting.semantics.planning import build_metric_planning_context

    service, context, _, queries, _, _, target, _, kwargs = adoption_calculation_context
    assert await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs) == ()
    execution = await service.load_execution_context(target.run_id, context['scope'], user_id='7',
        thread_id='thread-basis', vault=context['vault'])
    receipts = await service.load_basis_receipts(target.run_id, context['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')
    planning = build_metric_planning_context(execution, receipts, report_revision='initial')
    assert planning.calculations == ()
    assert len(planning.selections) == 1 and planning.selections[0].status == 'unavailable'
    assert queries == []


@pytest.mark.parametrize('refresh_context', [True], indirect=True)
async def test_adoption_query_failure_is_unavailable_and_not_silently_retried(adoption_calculation_context, monkeypatch):
    from smart_reporting.reporting.models import ReportingError

    service, context, _, queries, _, _, target, _, kwargs = adoption_calculation_context

    async def unavailable(*_args, **_kwargs):
        raise ReportingError('test_source_unavailable', '合成数据源读取失败')

    monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', unavailable)
    results = await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs)
    assert len(results) == 2
    assert all(item.results[0].value is None and item.results[0].status == 'unavailable' for item in results)
    assert all('metric_query_failed' in item.results[0].issue_codes for item in results)
    assert await service.calculate_adoption_metrics(target.run_id, context['scope'], **kwargs) == results
    assert queries == []


@pytest.mark.parametrize('refresh_context', [{'outputs': ['pdf', 'docx'], 'domains': ['budget']},
    {'outputs': ['pptx'], 'domains': ['budget']}, {'outputs': ['xlsx'], 'domains': ['budget']}], indirect=True)
async def test_adoption_replans_from_new_csv_and_restores_registered_preparation(adoption_calculation_context, monkeypatch):
    import asyncio
    import os
    from copy import deepcopy

    from agno.run import RunContext
    from sqlalchemy import delete

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.policy_adoption import prepare_policy_adoption_execution
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        prepare_policy_adoption_analysis,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.models import (
        AnalysisBundle,
        DataUnderstandingPlan,
    )
    from smart_reporting.reporting.workflow.state import ReportingRunState
    from smart_reporting.runtime.database import create_agent_database

    service, context, original, queries, options, adoption, _, _, _ = adoption_calculation_context
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service = service
    runtime.configuration_provider = SimpleNamespace(vault=context['vault'])
    runtime.datasets = options['dataset_store']
    runtime.workspace_service = runtime.datasets.service
    runtime.workspace_registry = runtime.workspace_service.registry
    runtime.state_repository = ReportingStateRepository(database.async_db)
    runtime._durable_command_lock = asyncio.Lock()
    runtime._data_understanding_agent = SimpleNamespace(id='new-scope-planner')
    runtime._analysis_agent = SimpleNamespace(id='new-analysis-planner')
    source = options['workflow_scope']
    original_context = RunContext(run_id=source.run_id, session_id=source.session_id, user_id='7',
        session_state={'report_workflow_scope': source.as_state(), 'oldPlan': {'value': 300}})
    before = deepcopy(original_context.session_state)
    calls = []

    async def planner(agent, payload, new_context, **_options):
        assert new_context.run_id == adoption.target_run_id
        assert 'oldPlan' not in new_context.session_state
        assert payload['domains'] == ['budget']
        calls.append(agent.id)
        if agent.id == 'new-scope-planner':
            return DataUnderstandingPlan.model_validate({'tables': [{'sourceId': 'warehouse', 'table': 'test.budget',
                'periodColumn': 'period', 'periodGranularity': 'date', 'role': '预算期间'}]})
        metric_context = payload['metricContext']
        assert metric_context['basisId'] == adoption.basis_id
        assert Decimal(metric_context['calculations'][0]['results'][0]['value']) == Decimal(200)
        assert metric_context['calculations'][0]['results'][0]['factId'] != original.results[0].fact_id
        return AnalysisBundle.model_validate({'analyses': [{'code': 'new_budget', 'domain': 'budget',
            'description': '新口径已登记预算值核对', 'managementQuestion': '新口径的预算是多少？',
            'primaryMetricFamily': '预算', 'requirementIds': ['new-budget-details'],
            'analysisName': '新口径预算核对', 'periodRoles': ['current'], 'seriesGranularity': None}],
            'requirements': [{'requirementId': 'new-budget-details', 'sourceId': 'warehouse',
                'tables': [{'table': 'test.budget', 'periodColumn': 'period',
                    'periodGranularity': 'date', 'measureColumns': ['amount']}],
                'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []}]})

    runtime._run_planner = planner
    repository = runtime.state_repository
    try:
        await repository.register_run(report_run_id=source.run_id, external_run_id=source.external_run_id,
            agno_session_id=source.session_id, agno_run_id=source.run_id, thread_id=source.caller_thread_id,
            owner_user_id='7', database=source.database, company_id=source.company_id, entrypoint='agentos')
        await repository.create(ReportingRunState.initial(report_run_id=source.run_id, external_run_id=source.external_run_id,
            thread_id=source.caller_thread_id, owner_user_id='7', payload={'workflowCheckpoint': {'owner': 'old-report'},
                'approvedOutline': {'reportType': 'topic', 'title': '原报告', 'sections': [
                    {'code': 'section_001', 'sectionNumber': '1', 'title': '原预算', 'analysisIds': ['analysis_001']}]}}))
        execution = await prepare_policy_adoption_execution(runtime, original_context, request_id='calculate-adoption')
        from smart_reporting.reporting.workflow.policy_adoption_recovery import (
            inspect_policy_adoption_preparation,
        )

        pending_state = (await repository.get(execution.scope.run_id)).model_dump()
        initial_inspection = await inspect_policy_adoption_preparation(runtime, original_context, execution)
        assert initial_inspection['analysis']['status'] == 'not_generated'
        assert initial_inspection['document']['status'] == (
            'not_generated' if set(execution.requested_outputs) <= {'pdf', 'docx'} else 'not_applicable')
        assert (await repository.get(execution.scope.run_id)).model_dump() == pending_state
        assert not calls and not queries
        hash_files = runtime.workspace_service.abatch_hash_files
        async def incomplete_hashes(*_args, **_kwargs):
            return []
        monkeypatch.setattr(runtime.workspace_service, 'abatch_hash_files', incomplete_hashes)
        failed_inspection = await inspect_policy_adoption_preparation(runtime, original_context, execution)
        assert failed_inspection['analysis']['status'] == 'unverifiable'
        assert 'identity' not in failed_inspection['analysis']
        assert (await repository.get(execution.scope.run_id)).model_dump() == pending_state
        monkeypatch.setattr(runtime.workspace_service, 'abatch_hash_files', hash_files)
        apply_command = runtime._apply_durable_command
        captured = {}
        if execution.requested_outputs == ('pptx',):
            async def lose_preparation_response(new_context, command, **kwargs):
                result = await apply_command(new_context, command, **kwargs)
                if command.command_id.startswith('adoption-analysis-preparation:'):
                    captured['state'] = deepcopy(new_context.session_state)
                    raise OSError('preparation committed but response lost')
                return result
            monkeypatch.setattr(runtime, '_apply_durable_command', lose_preparation_response)
            with pytest.raises(OSError, match='preparation committed'):
                await prepare_policy_adoption_analysis(runtime, original_context, execution)
            monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
        if execution.requested_outputs == ('xlsx',):
            from hashlib import sha256

            from smart_reporting.reporting.workflow.checkpoint import FileIdentity

            async def lose_registration(new_context, command, **kwargs):
                if command.command_id.startswith('adoption-analysis-preparation:'):
                    captured['identity'] = FileIdentity.model_validate(command.payload['artifact'])
                    raise OSError('preparation file written without registration')
                return await apply_command(new_context, command, **kwargs)

            monkeypatch.setattr(runtime, '_apply_durable_command', lose_registration)
            with pytest.raises(OSError, match='without registration'):
                await prepare_policy_adoption_analysis(runtime, original_context, execution)
            monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
            with pytest.raises(ReportingError, match='report_policy_adoption_preparation_unknown'):
                await prepare_policy_adoption_analysis(runtime, original_context, execution)
            identity = captured.pop('identity')
            pending = await repository.get(execution.scope.run_id)
            inspected = await inspect_policy_adoption_preparation(runtime, original_context, execution)
            assert inspected['analysis']['status'] == 'awaiting_confirmation'
            assert inspected['analysis']['identity'] == identity.model_dump(mode='json', by_alias=True)
            assert inspected['document']['status'] == 'not_applicable'
            assert (await repository.get(execution.scope.run_id)).payload == pending.payload
            assert calls == ['new-scope-planner', 'new-analysis-planner'] and len(queries) == 1
            raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity.path)
            # 确认错误的路径、字节身份或执行内容，均不能补登记。
            for invalid in (identity.model_copy(update={'path': identity.path + '.foreign'}),
                    identity.model_copy(update={'sha256': '0' * 64}),
                    identity.model_copy(update={'size': identity.size + 1})):
                with pytest.raises(ReportingError):
                    await prepare_policy_adoption_analysis(runtime, original_context, execution,
                        confirmed_preparation=invalid)
                assert (await repository.get(execution.scope.run_id)).payload == pending.payload
            for field in ('execution_sha256', 'planning_sha256'):
                import json

                changed = json.loads(raw)
                changed[field] = '0' * 64
                changed_bytes = json.dumps(changed, ensure_ascii=False).encode()
                await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key,
                    identity.path, changed_bytes, overwrite=True)
                invalid = identity.model_copy(update={'sha256': sha256(changed_bytes).hexdigest(),
                    'size': len(changed_bytes)})
                with pytest.raises(ReportingError, match='report_policy_adoption_mismatch'):
                    await prepare_policy_adoption_analysis(runtime, original_context, execution,
                        confirmed_preparation=invalid)
                assert (await repository.get(execution.scope.run_id)).payload == pending.payload
            await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, raw, overwrite=True)
            from smart_reporting.reporting.workflow.policy_adoption_recovery import (
                confirm_policy_adoption_preparation,
            )

            with pytest.raises(ReportingError, match='report_editor_conflict'):
                await confirm_policy_adoption_preparation(runtime, original_context, execution,
                    kind='analysis', identity=identity, expected_state_version=pending.state_version - 1)
            for invalid in (identity.model_copy(update={'path': identity.path + '.foreign'}),
                    identity.model_copy(update={'sha256': '0' * 64})):
                with pytest.raises(ReportingError, match='report_editor_conflict'):
                    await confirm_policy_adoption_preparation(runtime, original_context, execution,
                        kind='analysis', identity=invalid, expected_state_version=pending.state_version)
                assert (await repository.get(execution.scope.run_id)).payload == pending.payload
            repository_apply = repository.apply
            from smart_reporting.reporting.workflow.state import ReportingCommand

            async def concurrent_update(run_id, command, **kwargs):
                await repository_apply(run_id, ReportingCommand(name='record_warnings',
                    commandId='concurrent-preparation-confirmation',
                    payload={'warnings': [{'code': 'test_concurrent_update'}]}), **kwargs)
                return await repository_apply(run_id, command, **kwargs)
            monkeypatch.setattr(repository, 'apply', concurrent_update)
            with pytest.raises(ReportingError, match='report_editor_conflict'):
                await confirm_policy_adoption_preparation(runtime, original_context, execution,
                    kind='analysis', identity=identity, expected_state_version=pending.state_version)
            monkeypatch.setattr(repository, 'apply', repository_apply)
            pending = await repository.get(execution.scope.run_id)
            assert not any(item['path'] == identity.path for item in pending.payload['artifacts'])
            async def lose_confirmation_response(run_id, command, **kwargs):
                result = await repository_apply(run_id, command, **kwargs)
                if command.command_id.startswith('adoption-analysis-preparation:'):
                    raise OSError('confirmation committed but response lost')
                return result
            monkeypatch.setattr(repository, 'apply', lose_confirmation_response)
            with pytest.raises(OSError, match='confirmation committed'):
                await confirm_policy_adoption_preparation(runtime, original_context, execution,
                    kind='analysis', identity=identity, expected_state_version=pending.state_version)
            monkeypatch.setattr(repository, 'apply', repository_apply)
            assert (await inspect_policy_adoption_preparation(runtime, original_context, execution))['analysis']['status'] == 'registered'
            confirmed = await confirm_policy_adoption_preparation(runtime, original_context, execution,
                kind='analysis', identity=identity, expected_state_version=pending.state_version)
            assert confirmed['executionResumed'] is False
            assert confirmed['analysis']['status'] == 'registered'
            assert confirmed['stateVersion'] > pending.state_version
            repeated = await confirm_policy_adoption_preparation(runtime, original_context, execution,
                kind='analysis', identity=identity, expected_state_version=pending.state_version)
            assert repeated == confirmed
            assert calls == ['new-scope-planner', 'new-analysis-planner'] and len(queries) == 1
        new_context = await prepare_policy_adoption_analysis(runtime, original_context, execution)
        if captured:
            assert new_context.session_state == captured['state']
        assert calls == ['new-scope-planner', 'new-analysis-planner']
        assert len(queries) == 1
        detailed = new_context.session_state['report_detailed_analysis_plan']
        assert detailed['analyses'][0]['analysisName'] == '新口径预算核对'
        assert original.results[0].dataset_ids[0] not in detailed['datasetIds']
        assert set(detailed['datasetIds']) == {item['datasetId'] for item in new_context.session_state['report_analysis_data_context']}
        child = await repository.get(execution.scope.run_id)
        assert new_context.session_state['report_workflow_input']['reportType'] == 'topic'
        assert new_context.session_state['report_workflow_input']['domains'] == ['budget']
        assert child.payload['deliveryFormat'] == new_context.session_state['report_workflow_input']['deliveryFormat']
        assert child.payload['detailedAnalysisPlan'] == detailed
        assert child.revision == execution.output_revision
        assert original_context.session_state == before
        assert (await repository.get(source.run_id)).payload['workflowCheckpoint'] == {'owner': 'old-report'}
        async def no_planner(*_args, **_kwargs):
            pytest.fail('恢复已登记的新计划不应再次调用模型')
        runtime._run_planner = no_planner
        runtime.report_basis_service = ReportBasisService(context['scopes'])
        runtime.state_repository = ReportingStateRepository(database.async_db)
        restored = await prepare_policy_adoption_analysis(runtime, original_context, execution)
        assert restored.session_state == new_context.session_state
        assert len(queries) == 1
        await check_adoption_evidence_task(runtime, original_context, execution, database,
            queries=queries, monkeypatch=monkeypatch)
        await check_adoption_narrative_recovery(runtime, original_context, execution, database,
            queries=queries, monkeypatch=monkeypatch)
        if set(execution.requested_outputs) <= {'pdf', 'docx'}:
            runtime.business_evidence_service = context['policy_service'].evidence
            await check_adoption_document_job(runtime, original_context, execution, database,
                queries=queries, monkeypatch=monkeypatch)
        elif execution.requested_outputs == ('pptx',):
            await check_adoption_slides(runtime, original_context, execution, database,
                queries=queries, monkeypatch=monkeypatch)
        elif execution.requested_outputs == ('xlsx',):
            await check_adoption_workbook(runtime, original_context, execution, database,
                queries=queries, monkeypatch=monkeypatch)
        await check_adoption_publication(runtime, original_context, execution, queries=queries)
        assert original_context.session_state == before
        profile = restored.session_state['report_analysis_data_context'][0]['profileFile']
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, profile['path'], b'changed', overwrite=True)
        with pytest.raises(ReportingError):
            await prepare_policy_adoption_analysis(runtime, original_context, execution)
        assert len(queries) == 1
    finally:
        ids = (source.run_id, adoption.target_run_id)
        async with database.async_engine.begin() as connection:
            await connection.execute(delete(repository.command_receipts).where(repository.command_receipts.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.states).where(repository.states.c.report_run_id.in_(ids)))
            await connection.execute(delete(repository.runs).where(repository.runs.c.report_run_id.in_(ids)))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def check_adoption_publication(runtime, source_context, execution, *, queries):
    import hashlib

    from agno.workflow.types import StepInput

    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        continue_policy_adoption_delivery,
    )

    published = await continue_policy_adoption_delivery(runtime, source_context, execution)
    content = published.content
    assert content['reportId'] == execution.scope.run_id and content['revision'] == execution.output_revision
    assert content['editorAvailable'] is True and content['artifactManifest']
    assert content['formalReleaseAllowed'] is False
    for output in execution.requested_outputs:
        label = 'word' if output == 'docx' else output
        assert content[f'{label}Path'] and content[f'{label}Sha256']
    from urllib.parse import urlsplit

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
        ReportEditorService,
    )
    from smart_reporting.reporting.delivery.publishing import (
        ReportArtifactPersistenceService,
        ReportDownloadGrantService,
        ReportDownloadHttpService,
        create_report_download_router,
    )
    from smart_reporting.reporting.tests.delivery_fakes import (
        InMemoryDownloadGrantRepository,
        InMemoryReportArtifactRepository,
    )
    from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY

    artifacts = InMemoryReportArtifactRepository()
    runtime.artifact_persistence = ReportArtifactPersistenceService(artifacts, runtime.workspace_service)
    runtime.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    runtime.editor_grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    runtime.report_public_base_url = 'http://reports.test'
    scope = execution.scope
    async def issue(output):
        return await runtime.issue_http_publication(thread_id=scope.workspace_key,
            caller_thread_id=scope.caller_thread_id, user_id=scope.user_id,
            workflow_session_id=scope.session_id, workflow_run_id=scope.run_id,
            dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                **scope.as_state(), 'threadId': scope.caller_thread_id}}, output=output)
    signed = await issue(published)
    replayed = (await runtime.publish_report(StepInput(input='签发后再次恢复'), source_context, execution=execution)).content
    assert replayed['editorAvailable'] is True and replayed['artifactManifest']
    grant = urlsplit(signed['editor']['openUrl']).path.rsplit('/', 1)[-1]
    _, session = await runtime.editor_grants.exchange(grant)
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_service.registry, workspace=runtime.workspace_service,
        report_basis_service=runtime.report_basis_service)
    editor_context = await editor.context_for_session(session)
    assert editor_context.workflow_run_id == scope.run_id and editor_context.revision == execution.output_revision
    assert (await editor.trace.require_index(editor_context)).report_basis_id == execution.basis_id
    assert '200' in (await editor.read_document(editor_context)).markdown
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async def check_downloads(output):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
            for requested in execution.requested_outputs:
                label = 'word' if requested == 'docx' else requested
                downloaded = await client.get(output[label]['downloadUrl'])
                assert downloaded.status_code == 200
                assert hashlib.sha256(downloaded.content).hexdigest() == content[f'{label}Sha256']
    await check_downloads(signed)
    child = await runtime.state_repository.get(execution.scope.run_id)
    preparation = next(item for item in child.payload['artifacts'] if item['path'].endswith('/analysis-preparation.json'))
    for identity, issue_code in ((content['artifactManifest'], 'revision_publication_manifest_unavailable'),
            (preparation, 'revision_publication_editor_job_unavailable')):
        raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity['path'])
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity['path'], b'changed', overwrite=True)
        degraded = (await runtime.publish_report(StepInput(input='恢复来源失效交付'), source_context, execution=execution)).content
        assert degraded['editorAvailable'] is False
        assert issue_code in {item['code'] for item in degraded['publicationGate']['issues']}
        if identity == content['artifactManifest']:
            assert not degraded.get('artifactManifest')
        for output in execution.requested_outputs:
            label = 'word' if output == 'docx' else output
            assert degraded[f'{label}Sha256'] == content[f'{label}Sha256']
        degraded_signed = await issue(type(published)(content=degraded))
        assert 'editor' not in degraded_signed
        await check_downloads(degraded_signed)
        runtime.workspace_service.registry.resolve(scope)
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity['path'], raw, overwrite=True)
    assert len(queries) == 1


async def check_adoption_slides(runtime, source_context, execution, database, *, queries, monkeypatch):
    from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        assemble_policy_adoption_slides,
        continue_policy_adoption_delivery,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime.slides import SlideOutline

    apply_command = runtime._apply_durable_command
    async def lose_completion(context, command, **kwargs):
        result = await apply_command(context, command, **kwargs)
        if command.name == 'complete':
            raise OSError('adoption slides assembly committed but response lost')
        return result
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_completion)
    with pytest.raises(OSError, match='adoption slides assembly committed'):
        await continue_policy_adoption_delivery(runtime, source_context, execution)
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    context = await assemble_policy_adoption_slides(runtime, source_context, execution)
    child = await runtime.state_repository.get(execution.scope.run_id)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    assert checkpoint.phase == 'completed' and checkpoint.revision == execution.output_revision
    slides = await runtime._read_identity_model(execution.scope.workspace_key, checkpoint.slide_outline_file, SlideOutline)
    assert slides.slides and any('200' in bullet for page in slides.slides for bullet in page.bullets)
    manifest = await runtime._read_identity_model(execution.scope.workspace_key,
        next(item for item in checkpoint.files if item.path == child.payload['result']['manifest']['path']),
        ReportArtifactManifest)
    assert manifest.report_id == execution.scope.run_id and manifest.report_basis_id == execution.basis_id
    assert manifest.revision == execution.output_revision and manifest.trace_index is not None
    assert context.run_id == execution.scope.run_id and len(queries) == 1

    from io import BytesIO
    from zipfile import ZipFile

    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.workflow.runtime import publication

    build = publication.build_editable_pptx
    rendered = []
    def counted_build(**kwargs):
        rendered.append(kwargs['title'])
        return build(**kwargs)
    monkeypatch.setattr(publication, 'build_editable_pptx', counted_build)
    outline = ReportOutline.model_validate(context.session_state['report_outline'])
    assert outline.title == slides.title
    async def lose_render_completion(context, command, **kwargs):
        result = await apply_command(context, command, **kwargs)
        if command.command_id.startswith('revision-pptx-complete:'):
            raise OSError('adoption pptx completed but response lost')
        return result
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_render_completion)
    first = (await continue_policy_adoption_delivery(runtime, source_context, execution)).content
    assert first['pptxPath'] and first['validation']['ok'] is False
    assert 'pptx_generation_failed' in {item['code'] for item in first['validation']['issues']}
    content, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, first['pptxPath'])
    with ZipFile(BytesIO(content)) as archive:
        slides_xml = ''.join(archive.read(name).decode() for name in archive.namelist()
            if name.startswith('ppt/slides/slide') and name.endswith('.xml'))
    assert '200' in slides_xml and '预算' in slides_xml
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    recovered = await runtime._render_pptx(source_context, {'revision': execution.output_revision}, None, execution=execution)
    assert recovered['pptxSha256'] == first['pptxSha256'] and len(rendered) == 1
    dataset = (await runtime._registered_metric_dataset_handles(context))[0]
    original_csv, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, dataset.path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, dataset.path, b'changed', overwrite=True)
    assert (await runtime._render_pptx(source_context, {'revision': execution.output_revision}, None,
        execution=execution))['pptxSha256'] == recovered['pptxSha256']
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, dataset.path, original_csv, overwrite=True)
    slide_bytes, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, checkpoint.slide_outline_file.path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, checkpoint.slide_outline_file.path,
        b'changed', overwrite=True)
    with pytest.raises(ReportingError):
        await assemble_policy_adoption_slides(runtime, source_context, execution)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, checkpoint.slide_outline_file.path,
        slide_bytes, overwrite=True)
    assert len(rendered) == 1 and len(queries) == 1


async def check_adoption_workbook(runtime, source_context, execution, database, *, queries, monkeypatch):
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        continue_policy_adoption_delivery,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.revision_execution import assemble_revision_workbook

    apply_command = runtime._apply_durable_command
    async def lose_completion(context, command, **kwargs):
        result = await apply_command(context, command, **kwargs)
        if command.name == 'complete':
            raise OSError('adoption workbook assembly committed but response lost')
        return result
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_completion)
    with pytest.raises(OSError, match='adoption workbook assembly committed'):
        await continue_policy_adoption_delivery(runtime, source_context, execution)
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    checkpoint, manifest = await assemble_revision_workbook(runtime, source_context, execution)
    assert checkpoint.phase == 'completed' and checkpoint.revision == execution.output_revision
    assert manifest.report_id == execution.scope.run_id and manifest.report_basis_id == execution.basis_id
    assert manifest.trace_index is not None and manifest.revision == execution.output_revision
    markdown, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, manifest.markdown.path)
    assert '200' in markdown.decode() and '不代表管理问题已回答' in markdown.decode()
    assert await assemble_revision_workbook(runtime, source_context, execution) == (checkpoint, manifest)
    assert len(queries) == 1

    import json
    import subprocess
    import sys
    from io import BytesIO
    from zipfile import ZipFile

    from openpyxl import load_workbook

    from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
    from smart_reporting.reporting.code_mode import ScriptProcessResult
    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import ToolkitRuntime
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        prepare_policy_adoption_narrative,
    )

    class WorkbookRuntime(ToolkitRuntime):
        def __init__(self):
            super().__init__()
            self.executions = []
        async def execute_script_process(self, session_id, host, path, **kwargs):
            self.executions.append(session_id)
            process = subprocess.run([sys.executable, path], cwd=host.identity.root, capture_output=True, text=True)
            return ScriptProcessResult(SimpleNamespace(status='ok' if process.returncode == 0 else 'error',
                stdout=process.stdout, stderr=process.stderr, traceback=None), process.returncode)

    local = WorkbookRuntime()
    runtime.code_mode_runtime = local
    monkeypatch.setattr(runtime, '_run_workspace', lambda _: runtime.workspace_service.workspace(execution.scope.workspace_key))
    manager = ReportingLspProcessManager(command=('false',), request_timeout_seconds=0.2)
    runtime.lsp_manager = manager
    context = await prepare_policy_adoption_narrative(runtime, source_context, execution)
    outline = ReportOutline.model_validate(context.session_state['report_outline'])
    persist = runtime._persist_reporting_checkpoint
    async def lose_workbook_checkpoint(context, checkpoint, **kwargs):
        result = await persist(context, checkpoint, **kwargs)
        if any(item.path.endswith('.xlsx.receipt.json') for item in checkpoint.files):
            raise OSError('adoption workbook checkpoint response lost')
        return result
    monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', lose_workbook_checkpoint)
    try:
        rendered = (await continue_policy_adoption_delivery(runtime, source_context, execution)).content
        assert rendered['xlsxSize'] > 0 and execution.scope.run_id in rendered['xlsxPath']
        assert rendered['validation']['ok'] is False
        assert any(item['code'] == 'xlsx_generation_failed' for item in rendered['validationIssues'])
        monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist)
        content, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, rendered['xlsxPath'])
        book = load_workbook(BytesIO(content), data_only=True)
        assert book['汇总']['D2'].value == 200 and book.worksheets[1]['C2'].value == 200
        assert book.worksheets[1]['E2'].value == '[2026-11-01, 2026-12-01)'
        book.close()
        with ZipFile(BytesIO(content)) as package:
            mapping = json.loads(package.read('smart-reporting/source-mapping.json'))['sources']
        assert {cell['basisId'] for cell in mapping['cells']} == {execution.basis_id}
        view = await runtime._metric_planning_context(context)
        expected = {(item.fact_id, item.calculation_id, item.basis_id)
            for calculation in view.calculations for item in calculation.results}
        assert {(cell['factId'], cell['calculationId'], cell['basisId']) for cell in mapping['cells']} == expected
        runtime.state_repository = ReportingStateRepository(database.async_db)
        restored = await runtime._render_xlsx(source_context, {'revision': execution.output_revision}, outline, execution=execution)
        assert restored['xlsxSha256'] == rendered['xlsxSha256'] and len(local.executions) == 1
        assert len(queries) == 1
        csv_path = context.session_state['report_workflow_result']['datasets'][0]['path']
        csv, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, csv_path)
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, csv_path, b'changed', overwrite=True)
        assert (await runtime._render_xlsx(source_context, {'revision': execution.output_revision}, outline,
            execution=execution))['xlsxSha256'] == rendered['xlsxSha256']
        child = await runtime.state_repository.get(execution.scope.run_id)
        receipt = next(item for item in child.payload['artifacts'] if item['path'].endswith('.xlsx.receipt.json'))
        raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, receipt['path'])
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, receipt['path'], b'changed', overwrite=True)
        unknown = await runtime._render_xlsx(source_context, {'revision': execution.output_revision}, outline, execution=execution)
        assert unknown['xlsxSha256'] == rendered['xlsxSha256'] and unknown['validation']['ok'] is False
        assert not unknown.get('workbookSources') and not unknown.get('datasets')
        assert unknown['validationIssues'][0]['code'] == 'xlsx_validation_receipt_unavailable'
        assert len(local.executions) == 1 and len(queries) == 1
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, csv_path, csv, overwrite=True)
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, receipt['path'], raw, overwrite=True)
    finally:
        await manager.aclose()


async def check_adoption_evidence_task(runtime, source_context, execution, database, *, queries, monkeypatch):
    import asyncio
    import json

    from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        continue_policy_adoption_delivery,
        run_policy_adoption_evidence,
    )
    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        AnalysisEvidenceDecision,
        AnalysisSummaryDraft,
    )
    from smart_reporting.task_execution import (
        TaskExecutionKernel,
        TaskExecutionRepository,
        TaskState,
    )

    tasks = TaskExecutionRepository(database.async_db)
    await tasks.initialize()
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(runtime.workspace_service, tasks),
        model_profiles=DEFAULT_MODEL_PROFILES)
    runs, planner_calls = [], []
    runtime._checkpoint_persist_lock = asyncio.Lock()
    runtime._analysis_evidence_agent = SimpleNamespace(model=None)
    runtime._analysis_summary_agent = SimpleNamespace(model=None)
    runtime._analysis_thinking_enabled = False
    runtime._analysis_thinking_budget_cap = 1024
    runtime.code_mode_runtime = object()
    runtime.coding_task_registry = None
    runtime._analysis_script_agent_factory = lambda *args: pytest.fail('已登记事实足够，本用例不应执行补证脚本')

    async def planner(agent, _payload, context, **_kwargs):
        planner_calls.append(agent)
        assert context.run_id == execution.scope.run_id
        if agent is runtime._analysis_evidence_agent:
            return AnalysisEvidenceDecision(requiresSupplementalEvidence=False,
                reason='已登记的新口径预算值足以完成本次核对，不推断执行率。', missingFacts=(), codingRequirements=())
        assert agent is runtime._analysis_summary_agent
        return AnalysisSummaryDraft(summary='新口径预算额为200，执行率问题仍缺实际发生额。',
            warnings=('执行率尚未回答，不代表业务验收通过。',))

    monkeypatch.setattr(runtime, '_run_planner', planner)
    first_response = True
    async def run_task(scope, *, parent_run_id, executor):
        nonlocal first_response
        assert parent_run_id == execution.scope.run_id
        async def invoke(invocation):
            data = json.loads(invocation.instruction)
            calculations = data['deterministicFacts']['metricContext']['calculations']
            assert data['deterministicFacts']['metricContext']['basisId'] == execution.basis_id
            assert Decimal(calculations[0]['results'][0]['value']) == Decimal(200)
            runs.append(parent_run_id)
            return await executor(invocation)
        result = await coordinator.run(scope, parent_run_id=parent_run_id, executor=invoke)
        assert (await tasks.get_task_snapshot(scope.external_run_id)).state is TaskState.COMPLETED
        if first_response:
            first_response = False
            raise OSError('adoption analysis completed but response lost')
        return result
    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=run_task)
    with pytest.raises(OSError, match='completed but response lost'):
        await continue_policy_adoption_delivery(runtime, source_context, execution)
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository

    runtime.state_repository = ReportingStateRepository(database.async_db)
    tasks = TaskExecutionRepository(database.async_db)
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(runtime.workspace_service, tasks),
        model_profiles=DEFAULT_MODEL_PROFILES)
    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=run_task)
    output = await run_policy_adoption_evidence(runtime, source_context, execution)
    assert output.content['status'] == 'evidence_frozen'
    assert len(runs) == 1 and len(planner_calls) == 2 and len(queries) == 1
    child = await runtime.state_repository.get(execution.scope.run_id)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    assert checkpoint.revision == execution.output_revision
    assert checkpoint.trace[-1].status == 'completed'
    assert checkpoint.deterministic_fact_files and checkpoint.finding_graph_file is not None
    graph_raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key,
        checkpoint.finding_graph_file.path)
    graph = json.loads(graph_raw)
    assert graph['questionCoverage'][0]['questionId'] == 'q-rate'
    assert graph['questionCoverage'][0]['status'] == 'partial'
    assert all('original-fact' not in item['factRefs'] for item in graph['findings'])
    assert (await runtime.state_repository.get(execution.source_scope.run_id)).payload['workflowCheckpoint'] == {'owner': 'old-report'}


async def check_adoption_document_job(runtime, source_context, execution, database, *, queries, monkeypatch):
    from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        prepare_policy_adoption_document,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workspace import WorkspaceReportService

    runtime.delivery_settings = ReportDeliverySettings()
    runtime.report_tools = WorkspaceReportService(runtime.workspace_service, data_sources=runtime.datasets)
    prepare = runtime.report_tools.report_prepare_dataset
    prepared = []
    async def create_job(*args, **kwargs):
        result = await prepare(*args, **kwargs)
        prepared.append(result['jobId'])
        return result
    monkeypatch.setattr(runtime.report_tools, 'report_prepare_dataset', create_job)
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    apply_command = runtime._apply_durable_command
    captured = {}
    async def lose_response(context, command, **kwargs):
        if command.command_id.startswith('adoption-document-job:'):
            captured['identity'] = FileIdentity.model_validate(command.payload['artifact'])
            raise OSError('document job written but not registered')
        return await apply_command(context, command, **kwargs)
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_response)
    with pytest.raises(OSError, match='document job written'):
        await prepare_policy_adoption_document(runtime, source_context, execution)
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    with pytest.raises(ReportingError, match='report_policy_adoption_preparation_unknown'):
        await prepare_policy_adoption_document(runtime, source_context, execution)
    pending = await runtime.state_repository.get(execution.scope.run_id)
    identity = captured['identity']
    from smart_reporting.reporting.workflow.policy_adoption_recovery import (
        inspect_policy_adoption_preparation,
    )

    inspected = await inspect_policy_adoption_preparation(runtime, source_context, execution)
    assert inspected['analysis']['status'] == 'registered'
    assert inspected['document']['status'] == 'awaiting_confirmation', inspected
    assert inspected['document']['identity'] == identity.model_dump(mode='json', by_alias=True)
    assert (await runtime.state_repository.get(execution.scope.run_id)).payload == pending.payload
    assert len(prepared) == 1 and len(queries) == 1
    for invalid in (identity.model_copy(update={'path': identity.path + '.foreign'}),
            identity.model_copy(update={'sha256': '0' * 64})):
        with pytest.raises(ReportingError):
            await prepare_policy_adoption_document(runtime, source_context, execution, confirmed_job=invalid)
        assert (await runtime.state_repository.get(execution.scope.run_id)).payload == pending.payload
    import json
    from hashlib import sha256

    raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity.path)
    for field in ('execution_sha256', 'outline_sha256', 'source'):
        changed = json.loads(raw)
        if field == 'source':
            changed['job']['sources'][0]['sha256'] = '0' * 64
        else:
            changed[field] = '0' * 64
        changed_bytes = json.dumps(changed, ensure_ascii=False).encode()
        await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key,
            identity.path, changed_bytes, overwrite=True)
        invalid = identity.model_copy(update={'sha256': sha256(changed_bytes).hexdigest(),
            'size': len(changed_bytes)})
        inspected = await inspect_policy_adoption_preparation(runtime, source_context, execution)
        assert inspected['document']['status'] == 'unverifiable'
        assert 'identity' not in inspected['document']
        with pytest.raises(ReportingError, match='report_policy_adoption_mismatch'):
            await prepare_policy_adoption_document(runtime, source_context, execution, confirmed_job=invalid)
        assert (await runtime.state_repository.get(execution.scope.run_id)).payload == pending.payload
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, raw, overwrite=True)
    from smart_reporting.reporting.workflow.policy_adoption_recovery import (
        confirm_policy_adoption_preparation,
    )

    repository_apply = runtime.state_repository.apply
    async def lose_committed_response(run_id, command, **kwargs):
        result = await repository_apply(run_id, command, **kwargs)
        if command.command_id.startswith('adoption-document-job:'):
            raise OSError('document job committed but response lost')
        return result
    monkeypatch.setattr(runtime.state_repository, 'apply', lose_committed_response)
    with pytest.raises(OSError, match='document job committed'):
        await confirm_policy_adoption_preparation(runtime, source_context, execution, kind='document',
            identity=identity, expected_state_version=pending.state_version)
    monkeypatch.setattr(runtime.state_repository, 'apply', repository_apply)
    confirmed = await confirm_policy_adoption_preparation(runtime, source_context, execution, kind='document',
        identity=identity, expected_state_version=pending.state_version)
    assert confirmed['document']['status'] == 'registered' and confirmed['executionResumed'] is False
    context = await prepare_policy_adoption_document(runtime, source_context, execution)
    assert prepared == [context.session_state['report_workflow_result']['jobId']]
    assert context.session_state['report_workflow_result']['revision'] == execution.output_revision
    job = runtime.report_tools._load_job(prepared[0], runtime._tool_context(context))
    assert job['_documentContext']['title'] == '新口径预算分析'
    assert {item['sha256'] for item in job['sources']} == {
        item['sha256'] for item in context.session_state['report_workflow_result']['datasets']}
    assert job['_pageLayout'] == runtime.delivery_settings.page_layout.model_dump(mode='json', by_alias=True)
    restored = await prepare_policy_adoption_document(runtime, source_context, execution)
    assert restored.session_state == context.session_state and len(prepared) == 1 and len(queries) == 1
    child = await runtime.state_repository.get(execution.scope.run_id)
    identity = next(item for item in child.payload['artifacts'] if item['path'].endswith('/document-job.json'))
    raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity['path'])
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity['path'], b'changed', overwrite=True)
    with pytest.raises(ReportingError):
        await prepare_policy_adoption_document(runtime, source_context, execution)
    assert len(prepared) == 1 and len(queries) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity['path'], raw, overwrite=True)
    await check_adoption_section(runtime, source_context, execution, database, queries=queries, monkeypatch=monkeypatch)


async def check_adoption_section(runtime, source_context, execution, database, *, queries, monkeypatch):
    from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        run_policy_adoption_section,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime import sections as section_runtime
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview
    from smart_reporting.task_execution import TaskExecutionKernel, TaskExecutionRepository

    runtime.section_generator = SimpleNamespace(model=None)
    runtime.section_recovery = None
    runtime.section_whole_generation = True
    runtime._planner_reasoning_effort = None
    stages, runs = [], []
    async def stage(_agent, schema, name, payload, **kwargs):
        stages.append(name)
        if name == 'semantics':
            return SectionSemanticReview(interpretations=())
        if name == 'plan':
            fact, = payload['factCatalog']
            assert fact['reportBasisId'] == execution.basis_id and Decimal(fact['value']) == 200
            assert fact['reportRevision'] == 'initial'
            return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                'blocks': [{'blockId': 'new-budget', 'objective': '核对新口径预算与限制', 'claimIds': ['new-budget']}],
                'claims': [{'claimId': 'new-budget', 'metricCode': 'budget', 'value': '200',
                    'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                    'citationIds': ['citation_001'], 'factIds': [fact['factId']],
                    'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
        assert name == 'content'
        fact_id = payload['sectionPlan']['claims'][0]['factIds'][0]
        return schema.model_validate({'blocks': [{'blockId': 'new-budget',
            'markdown': '新口径预算额为{{value:' + fact_id + ':value:CNY}}；缺少实际发生额，暂不判断执行率。'}]})
    monkeypatch.setattr(section_runtime, '_run_section_stage', stage)
    tasks = TaskExecutionRepository(database.async_db)
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(runtime.workspace_service, tasks), model_profiles=DEFAULT_MODEL_PROFILES)
    lost = True
    async def run_task(scope, *, parent_run_id, executor):
        nonlocal lost
        assert parent_run_id == execution.scope.run_id
        async def invoke(invocation):
            runs.append(parent_run_id)
            return await executor(invocation)
        receipt = await coordinator.run(scope, parent_run_id=parent_run_id, executor=invoke)
        if lost:
            lost = False
            raise OSError('adoption section Task response lost')
        return receipt
    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=run_task)
    with pytest.raises(ReportingError, match='report_policy_adoption_mismatch'):
        await run_policy_adoption_section(runtime, source_context, execution, section_code='foreign-section')
    assert not runs
    apply_command = runtime._apply_durable_command
    async def lose_completion(context, command, **kwargs):
        result = await apply_command(context, command, **kwargs)
        if command.name == 'complete_section':
            raise OSError('adoption section registration response lost')
        return result
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_completion)
    with pytest.raises(OSError, match='adoption section Task response lost'):
        await run_policy_adoption_section(runtime, source_context, execution, section_code='section_001')
    runtime.state_repository = ReportingStateRepository(database.async_db)
    tasks = TaskExecutionRepository(database.async_db)
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(runtime.workspace_service, tasks), model_profiles=DEFAULT_MODEL_PROFILES)
    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=run_task)
    with pytest.raises(OSError, match='adoption section registration response lost'):
        await run_policy_adoption_section(runtime, source_context, execution, section_code='section_001')
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    checkpoint, artifact, rework = await run_policy_adoption_section(runtime, source_context, execution, section_code='section_001')
    assert rework is None and artifact.blocks[0].number_references
    assert '200' in artifact.blocks[0].markdown and '数值待核实' not in artifact.blocks[0].markdown
    assert not checkpoint.pending_sections and len(runs) == 1 and stages[:2] == ['plan', 'content']
    assert await run_policy_adoption_section(runtime, source_context, execution, section_code='section_001') == (checkpoint, artifact, rework)
    assert len(runs) == 1 and len(queries) == 1
    identity = checkpoint.completed_sections[0].artifact_file
    raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity.path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, b'{}', overwrite=True)
    with pytest.raises(ReportingError):
        await run_policy_adoption_section(runtime, source_context, execution, section_code='section_001')
    assert len(runs) == 1 and len(queries) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, raw, overwrite=True)

    from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        assemble_policy_adoption_document,
        continue_policy_adoption_delivery,
    )

    apply_command = runtime._apply_durable_command
    async def lose_assembly_response(context, command, **kwargs):
        result = await apply_command(context, command, **kwargs)
        if command.name == 'complete':
            raise OSError('adoption assembly completion response lost')
        return result
    monkeypatch.setattr(runtime, '_apply_durable_command', lose_assembly_response)
    with pytest.raises(OSError, match='adoption assembly completion response lost'):
        await continue_policy_adoption_delivery(runtime, source_context, execution)
    monkeypatch.setattr(runtime, '_apply_durable_command', apply_command)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    context = await assemble_policy_adoption_document(runtime, source_context, execution)
    result = context.session_state['report_workflow_result']
    child = await runtime.state_repository.get(execution.scope.run_id)
    completed = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    assert completed.phase == 'completed' and completed.revision == execution.output_revision
    manifest_file = next(item for item in completed.files if item.path == result['artifactManifestPath'])
    manifest = await runtime._read_identity_model(execution.scope.workspace_key, manifest_file, ReportArtifactManifest)
    assert manifest.report_basis_id == execution.basis_id and manifest.revision == execution.output_revision
    assert manifest.report_id == execution.scope.run_id and manifest.trace_index is not None
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    index = await runtime._read_identity_model(execution.scope.workspace_key,
        FileIdentity(path=manifest.trace_index.path, size=manifest.trace_index.size,
            sha256=manifest.trace_index.sha256), RevisionTraceIndexV1)
    assert index.report_basis_id == execution.basis_id and not index.drilldown_metrics
    assert index.tables and index.fact_files and index.subject_bindings
    assert {item.dataset_id for item in index.datasets} == {item['datasetId'] for item in result['datasets']}
    markdown, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, result['markdownPath'])
    assert b'200' in markdown and '新口径预算分析' in markdown.decode()
    job = runtime.report_tools._load_job(result['jobId'], runtime._tool_context(context))
    assert job['_documentContext']['headingNumbers'] == [item.model_dump(mode='json', by_alias=True) for item in manifest.heading_numbers]
    runtime.state_repository = ReportingStateRepository(database.async_db)
    restored = await assemble_policy_adoption_document(runtime, source_context, execution)
    for key in ('report_workflow_result', 'report_artifacts', 'report_jobs', 'report_outline_hash'):
        assert restored.session_state[key] == context.session_state[key]
    assert restored.session_state.get('report_quality_issues', []) == context.session_state.get('report_quality_issues', [])
    assert len(runs) == 1 and len(queries) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, result['markdownPath'], b'changed', overwrite=True)
    with pytest.raises(ReportingError):
        await assemble_policy_adoption_document(runtime, source_context, execution)
    assert len(runs) == 1 and len(queries) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, result['markdownPath'], markdown, overwrite=True)
    identity = next(iter(completed.deterministic_fact_files.values()))
    raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity.path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, b'{}', overwrite=True)
    with pytest.raises(ReportingError):
        await assemble_policy_adoption_document(runtime, source_context, execution)
    assert len(runs) == 1 and len(queries) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, raw, overwrite=True)

    native_render = runtime.report_tools._render_report_pair
    render_calls = []
    async def lose_render_response(*args, **kwargs):
        render_calls.append(args)
        await native_render(*args, **kwargs)
        raise OSError('adoption native render response lost')
    monkeypatch.setattr(runtime.report_tools, '_render_report_pair', lose_render_response)
    rendered = (await continue_policy_adoption_delivery(runtime, source_context, execution)).content
    assert rendered['validation']['ok'] is False
    assert any(item['code'] == 'document_validation_receipt_unavailable' for item in rendered['validationIssues'])
    from io import BytesIO

    from docx import Document
    from pypdf import PdfReader
    for label in ('pdf', 'word'):
        actual = await runtime.workspace_service.ahash_file(execution.scope.workspace_key, rendered[f'{label}Path'])
        assert actual['sha256'] == rendered[f'{label}Sha256'] and actual['size'] == rendered[f'{label}Size']
    pdf, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, rendered['pdfPath'])
    word, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, rendered['wordPath'])
    assert PdfReader(BytesIO(pdf)).pages
    assert any('200' in cell.text for table in Document(BytesIO(word)).tables for row in table.rows for cell in row.cells)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    csv_path = result['datasets'][0]['path']
    csv, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, csv_path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, csv_path, b'changed', overwrite=True)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, result['markdownPath'], b'changed', overwrite=True)
    recovered = await runtime._render_and_validate(source_context, execution=execution)
    assert all(rendered[key] == value for key, value in recovered.items())
    assert len(render_calls) == 1 and len(queries) == 1 and len(runs) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, rendered['pdfPath'], b'changed', overwrite=True)
    partial = await runtime._render_and_validate(source_context, execution=execution)
    assert partial['validation']['ok'] is False and not partial.get('pdfPath')
    assert partial['wordSha256'] == rendered['wordSha256']
    assert any(item['code'] == 'report_pdf_artifact_unavailable' for item in partial['validationIssues'])
    assert len(render_calls) == 1 and len(queries) == 1 and len(runs) == 1
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, csv_path, csv, overwrite=True)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, result['markdownPath'], markdown, overwrite=True)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, rendered['pdfPath'], pdf, overwrite=True)

async def check_adoption_narrative_recovery(runtime, source_context, execution, database, *, queries, monkeypatch):
    import json

    from smart_reporting.reporting.hospital_operation.narrative_outline import (
        NarrativeOutlineCandidate,
    )
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.policy_adoption_analysis import (
        prepare_policy_adoption_narrative,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository

    child = await runtime.state_repository.get(execution.scope.run_id)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    graph_raw, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, checkpoint.finding_graph_file.path)
    graph = json.loads(graph_raw)
    planned = []
    runtime._narrative_outline_agent = SimpleNamespace(model=None)

    async def planner(agent, payload, context, **_kwargs):
        assert agent is runtime._narrative_outline_agent and context.run_id == execution.scope.run_id
        assert payload['planningContext']['snapshotHash'] == graph['snapshotHash']
        planned.append(payload)
        return NarrativeOutlineCandidate(title='新口径预算分析', snapshotHash=graph['snapshotHash'],
            sections=[{'title': '新口径预算核对与证据限制',
                'findingIds': [item['findingId'] for item in graph['findings']],
                'objective': '解释新计算结果及执行率尚缺的证据', 'groupingReason': '同一问题的已知事实与限制'}])
    monkeypatch.setattr(runtime, '_run_planner', planner)
    persist = runtime._persist_reporting_checkpoint
    interrupted = 0
    async def lose_checkpoint(context, value, **kwargs):
        nonlocal interrupted
        if value.narrative_outline_file is not None:
            interrupted += 1
            if interrupted == 1:
                raise OSError('adoption narrative checkpoint before commit')
        result = await persist(context, value, **kwargs)
        if value.narrative_outline_file is not None and interrupted == 2:
            raise OSError('adoption narrative checkpoint response lost')
        return result
    monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', lose_checkpoint)
    with pytest.raises(OSError, match='checkpoint before commit'):
        await prepare_policy_adoption_narrative(runtime, source_context, execution)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    with pytest.raises(OSError, match='checkpoint response lost'):
        await prepare_policy_adoption_narrative(runtime, source_context, execution)
    runtime.state_repository = ReportingStateRepository(database.async_db)
    monkeypatch.setattr(runtime, '_persist_reporting_checkpoint', persist)
    result = await prepare_policy_adoption_narrative(runtime, source_context, execution)
    assert len(planned) == 1 and len(queries) == 1
    assert result.session_state['report_outline']['title'] == '新口径预算分析'
    child = await runtime.state_repository.get(execution.scope.run_id)
    checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
    assert checkpoint.revision == execution.output_revision
    identity = checkpoint.narrative_outline_file
    assert identity.model_dump(mode='json', by_alias=True) in child.payload['artifacts']
    assert checkpoint.pending_sections == tuple(section['code'] for section in result.session_state['report_outline']['sections'])
    restored = await prepare_policy_adoption_narrative(runtime, source_context, execution)
    assert restored.session_state == result.session_state and len(planned) == 1
    original_bytes, _ = await runtime.workspace_service.afile_bytes(execution.scope.workspace_key, identity.path)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, b'changed', overwrite=True)
    with pytest.raises(ReportingError):
        await prepare_policy_adoption_narrative(runtime, source_context, execution)
    assert len(planned) == 1 and len(queries) == 1
    assert (await runtime.state_repository.get(execution.scope.run_id)).payload['workflowCheckpoint'] == checkpoint.model_dump(mode='json', by_alias=True)
    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, identity.path, original_bytes, overwrite=True)
