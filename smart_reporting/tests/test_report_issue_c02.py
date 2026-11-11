"""C02原始行到正式纠错回归；真实隔离PG/DuckDB，不冒充业务签认或整报告交付。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from smart_reporting.tests.test_report_basis_persistence import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    build_identity,
    request_summary,
)
from smart_reporting.tests.test_report_basis_persistence import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    receipt_snapshot as receipt_snapshot,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_application_exposes_published_metric_and_policy_lifecycle(basis_context, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from smart_reporting import app as application
    from smart_reporting.management.api import SESSION_COOKIE

    ctx = basis_context
    # 复用隔离库账号及其时钟；保留真实应用工厂、路由、鉴权和仓储。
    monkeypatch.setattr(application, 'AdminAuthService', lambda _: ctx['scopes'].auth)
    monkeypatch.setenv('AGENT_MANAGEMENT_PUBLIC_ORIGIN', 'https://reports.test')
    monkeypatch.setattr(application.report_runtime, 'business_evidence_service', application.report_runtime.business_evidence_service)
    monkeypatch.setattr(application.report_editor.trace, 'business_evidence_service', application.report_editor.trace.business_evidence_service)
    app = application.create_base_app(application.base_app.state.agentos_context)
    params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
    async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
        assert (await client.get('/management/api/v1/metrics', params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        metrics = await client.get('/management/api/v1/metrics', params=params)
        assert metrics.status_code == 200, metrics.text
        assert [item['metricId'] for item in metrics.json()['items']] == ['budget']
        impact = await client.get('/management/api/v1/statistical-policies/monthly-budget/impact', params={**params, 'revision': 1})
        assert impact.status_code == 200, impact.text
        assert impact.json()['items'][0]['referenceId'] == 'budget_execution'
        blocked = await client.post('/management/api/v1/metrics/budget/versions/1/retire',
            json={**params, 'reason': '缺少CSRF的请求不得退役。'})
        assert blocked.status_code == 403


async def publish_c02_definitions(ctx):
    """只追加新目录/指标/口径版本；不重写历史哈希。"""
    from sqlalchemy import insert

    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.repository import catalog_versions
    from smart_reporting.reporting.contract import (
        ModelColumn,
        ModelTable,
        ModelTermsResponse,
        RawDdlModel,
        SourceRef,
        schema_hash,
    )
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload, ratio_payload

    tables = tuple(ModelTable(sourceId='warehouse', database='test', name=name, columns=(
        ModelColumn(name=field, dataType='DECIMAL(18,8)', nullable=False),
        ModelColumn(name='period', dataType='DATE', nullable=False),
        ModelColumn(name='project_id', dataType='VARCHAR(20)', nullable=False),
    )) for name, field in (('budget', 'amount'), ('actual', 'amount'), ('project_rates', 'fraction')))
    metadata = ModelTermsResponse(revision='catalog-2', schemaHash=schema_hash(tables),
        sourceRefs=(SourceRef(sourceId='warehouse'),), tables=tables,
        ddlModels=tuple(RawDdlModel(id=index, modelName=table.name,
            ddl=f'CREATE TABLE test.{table.name} ({table.columns[0].name} DECIMAL(18,8) NOT NULL, '
                'period DATE NOT NULL, project_id VARCHAR(20) NOT NULL)') for index, table in enumerate(tables, 1)))
    body = {'metadata': metadata.model_dump(mode='json', by_alias=True),
        'tables': [table.model_dump(mode='json', by_alias=True) for table in tables]}
    async with ctx['repository'].transaction() as connection:
        await connection.execute(insert(catalog_versions).values(scope_id=ctx['scope_id'], source_id='warehouse',
            revision=2, status='published', catalog=body, content_hash=CatalogService._hash(body),
            synced_at=ctx['scopes'].auth.clock()))
    sources = SourceService(ctx['scopes'], ctx['vault'])
    await sources.save_draft(ctx['token'], ctx['scope'], 'warehouse', SourceDraftInput(
        name='C02隔离样例', database='test', metadataVersionId='warehouse:2'), 1)
    await sources.publish(ctx['token'], ctx['scope'], 'warehouse', 2)
    metrics = MetricService(ctx['scopes'])
    definitions = (
        metric_payload('actual', name='实际额', fieldRef='warehouse.test.actual.amount',
            timeField='warehouse.test.actual.period', dimensions=[{'id': 'project', 'fieldRef': 'warehouse.test.actual.project_id'}]),
        metric_payload('completion_equivalents', name='项目完成当量', unit='项目',
            fieldRef='warehouse.test.project_rates.fraction', timeField='warehouse.test.project_rates.period',
            dimensions=[{'id': 'project', 'fieldRef': 'warehouse.test.project_rates.project_id'}]),
        metric_payload('project_count', name='项目数', unit='项目', kind='count',
            fieldRef='warehouse.test.project_rates.project_id', timeField='warehouse.test.project_rates.period',
            dimensions=[{'id': 'project', 'fieldRef': 'warehouse.test.project_rates.project_id'}]),
        ratio_payload(name='预算执行率（原项目均值）', numerator='completion_equivalents', denominator='project_count',
            dimensions=[{'id': 'project', 'fieldRef': 'warehouse.test.project_rates.project_id'}]),
    )
    for definition in definitions:
        body = {key: value for key, value in definition.items() if key not in ('scopeId', 'revision')}
        await metrics.save_draft(ctx['token'], ctx['scope'], body, 0)
        await metrics.publish(ctx['token'], ctx['scope'], body['id'], expected_version=1)
    policies = ctx['policy_service']
    saved = await policies.get(ctx['token'], ctx['scope'], 'monthly-budget')
    policy = {key: value for key, value in saved['draft']['document'].items() if key not in ('scopeId', 'revision')}
    await policies.save_draft(ctx['token'], ctx['scope'], {**policy, 'name': 'C02原项目均值',
        'metricVersions': [{'metricId': 'rate', 'revision': 1}]}, expected_version=1)
    await policies.publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=2)
    await policies.set_default(ctx['token'], ctx['scope'], 'budget_execution',
        policy_version={'policyId': 'monthly-budget', 'revision': 2}, expected_version=1)
    return metrics, policy


@pytest.mark.parametrize('requested_outputs', [['pdf', 'docx'], ['pptx'], ['xlsx']], ids=['document', 'pptx', 'xlsx'])
async def test_c02_published_ratio_replaces_real_project_mean_and_rejects_70_expectation(basis_context, receipt_snapshot, monkeypatch, requested_outputs):
    import duckdb
    from agno.run import RunContext
    from sqlglot import parse_one

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.report_issue_regressions import read_regression
    from smart_reporting.management.report_issue_reviews import ReportIssueReviewService
    from smart_reporting.reporting.data_source.materialization import CsvMaterializer
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    from smart_reporting.reporting.semantics.issue_regression import BasisIssueRegressionReceipt
    from smart_reporting.reporting.semantics.models import MetricRequest
    from smart_reporting.reporting.tests.semantic_fixtures.oracle import execution_ratio
    from smart_reporting.reporting.tests.test_semantic_models import ratio_payload
    from smart_reporting.reporting.workflow.scope import (
        REPORT_WORKFLOW_SCOPE_DEPENDENCY,
        reporting_scope_keys,
        resolve_reporting_workflow_scope,
    )

    ctx = basis_context
    metrics, policy = await publish_c02_definitions(ctx)
    bases = ReportBasisService(ctx['scopes'])
    basis = await bases.register_report_basis('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
        request_summary=request_summary(ctx['scope_id'], displayUnit='%', domains=['budget'], requestedOutputs=requested_outputs),
        build_identity=build_identity(), policy_version={'policyId': 'monthly-budget', 'revision': 2})
    store = receipt_snapshot[0]['dataset_store']
    queries = []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period DATE)')
        connection.execute('CREATE TABLE test.actual(project_id VARCHAR, amount DECIMAL(18,2), period DATE)')
        # A实际额拆成两行，确保直接连接明细会把预算重复累计的错误也能被发现。
        connection.execute("INSERT INTO test.budget VALUES ('A',100,'2026-11-01'),('B',200,'2026-11-20')")
        connection.execute("INSERT INTO test.actual VALUES ('A',60,'2026-11-01'),('A',30,'2026-11-02'),('B',100,'2026-11-20')")
        connection.execute('CREATE VIEW test.project_rates AS SELECT b.project_id, b.period, '
            'CAST(a.amount/b.amount AS DECIMAL(18,8)) AS fraction FROM test.budget b JOIN '
            '(SELECT project_id,SUM(amount) AS amount FROM test.actual GROUP BY project_id) a USING(project_id)')
        budget_rows = connection.execute('SELECT project_id,amount FROM test.budget').fetchall()
        actual_rows = connection.execute('SELECT project_id,amount FROM test.actual').fetchall()
        budget = {key: amount for key, amount in budget_rows}
        actual = {key: sum(amount for project, amount in actual_rows if project == key) for key in budget}
        assert budget == {'A': Decimal(100), 'B': Decimal(200)}
        assert actual == {'A': Decimal(90), 'B': Decimal(100)}
        # 独立oracle不调用生产SQL、公式或结果；先固定业务预期，再执行目标计算。
        expected = execution_ratio(actual, budget)
        wrong_mean = sum(actual[key] / budget[key] * 100 for key in budget) / len(budget)
        assert expected == Decimal('63.33') and wrong_mean == Decimal('70')

        async def calculate(run_id, revision):
            execution = await bases.load_execution_context(run_id, ctx['scope'], user_id='7', thread_id='thread-basis', vault=ctx['vault'])
            keys = reporting_scope_keys(database=ctx['scope'].database, company_id=ctx['scope'].company_id,
                user_id='7', thread_id='thread-basis', run_id=run_id)
            scope = resolve_reporting_workflow_scope(run_id=run_id, session_id=run_id, user_id='7',
                dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'database': ctx['scope'].database,
                    'companyId': ctx['scope'].company_id, 'threadId': 'thread-basis', 'userId': '7'}})
            if run_id == 'run-basis':
                scope = receipt_snapshot[0]['workflow_scope']
            store.service.registry.resolve(scope)
            context = RunContext(run_id=run_id, session_id=keys.workspace_key, session_state={})
            request = MetricRequest(metricVersion={'metricId': 'rate', 'revision': revision},
                basisId=execution.basis.id, period=execution.basis.request_summary.period)
            plan = compile_metric(request, execution.policy, execution.metrics, execution.metadata['warehouse'].tables)
            assert not plan.issues
            class Source:
                config = execution.sources['warehouse']
                async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                    queries.append(sql)
                    cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
                    writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
                    writer.append(tuple(cursor.fetchall()))
                    return writer.finish()
            receipt_id = f'c02-rate-{revision}'
            computed = await execute_metric(plan, {'warehouse': Source()}, datasets=store, run_context=context, calculation_id=receipt_id)
            return await bases.append_basis_receipt(run_id, ctx['scope'], user_id='7', thread_id='thread-basis',
                receipt_id=receipt_id, report_revision='initial', request=request, results=computed.results,
                readiness=computed.readiness, dataset_handles=computed.datasets, dataset_store=store, run_context=context, workflow_scope=scope)

        original = await calculate('run-basis', 1)
        old_result = next(item for item in original.results if item.metric_version == original.request.metric_version)
        assert old_result.value == wrong_mean
        issues = ReportIssueReviewService(bases)
        binding = dict(run_id='run-basis', scope=ctx['scope'], user_id='7', thread_id='thread-basis',
            basis_id=basis.id, report_id='report-c02', revision=1)
        submitted = await issues.submit(**binding, allowed_object_refs=(old_result.fact_id,), payload={
            'issueId': 'issue-C02-real-ratio', 'objectRefs': [old_result.fact_id], 'category': 'calculation',
            'description': '项目均值70%不能表示总体执行率；按原始实际合计190除以预算合计300应为63.33%。'})
        assert submitted['review']['status'] == 'open'
        proposal = {'changeSummary': '总体执行率改为实际合计除以预算合计',
            'counterexample': '项目A预算100实际90、B预算200实际100；平均90%与50%为70%，总体190/300为63.33%。'}
        await issues.decide(ctx['token'], ctx['scope'], 'issue-C02-real-ratio', {'expectedVersion': 1,
            'status': 'accepted', 'decisionReason': '按独立原始行确认需要修正统计方式，尚未修复或签认。', 'proposal': proposal})
        fixed = ratio_payload(name='预算执行率（合计比率）')
        await metrics.save_draft(ctx['token'], ctx['scope'],
            {key: value for key, value in fixed.items() if key not in ('scopeId', 'revision')}, 1)
        await metrics.publish(ctx['token'], ctx['scope'], 'rate', expected_version=2)
        await ctx['policy_service'].save_draft(ctx['token'], ctx['scope'], {**policy, 'name': 'C02合计执行率',
            'metricVersions': [{'metricId': 'rate', 'revision': 2}]}, expected_version=2)
        await ctx['policy_service'].publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=3)
        fixed_refs = [{'assetType': 'metric', 'assetId': 'rate', 'revision': 2},
            {'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 3}]
        await issues.decide(ctx['token'], ctx['scope'], 'issue-C02-real-ratio', {'expectedVersion': 2,
            'status': 'accepted', 'decisionReason': '正式修复版本已发布，等待回归与报告交付。',
            'proposal': proposal, 'correctedVersions': fixed_refs})
        preview = await bases.preview_policy_adoption('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
            policy_version={'policyId': 'monthly-budget', 'revision': 3})
        adoption = await bases.register_policy_adoption('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
            confirmation={'requestId': 'C02-fix', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 3},
                'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
                    'metricVersion': {'metricId': 'rate', 'revision': 2}, 'reason': '总体执行率采用合计比率，不平均项目比率。'}]},
            build_identity=build_identity())
        from smart_reporting.management.report_adoption_calculations import (
            calculate_adoption_metrics,
        )
        from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter

        async def materialize(_adapter, sql, parameters, *, max_bytes=None):
            queries.append(sql)
            cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
            writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
            writer.append(tuple(cursor.fetchall()))
            return writer.finish()

        monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', materialize)
        await bases.register_adoption_selections('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis', request_id='C02-fix')
        target_scope = resolve_reporting_workflow_scope(run_id=adoption.target_run_id,
            session_id=adoption.target_run_id, user_id='7', dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
                'threadId': 'thread-basis', 'userId': '7'}})
        store.service.registry.resolve(target_scope)
        corrected, = await calculate_adoption_metrics(bases, adoption.target_run_id, ctx['scope'],
            user_id='7', thread_id='thread-basis', vault=ctx['vault'], dataset_store=store,
            run_context=RunContext(run_id=adoption.target_run_id, session_id=target_scope.workspace_key, session_state={}),
            workflow_scope=target_scope)
        by_metric = {item.metric_version.metric_id: item for item in corrected.results}
        assert by_metric['budget'].value == Decimal(300) and by_metric['actual'].value == Decimal(190)
        root = by_metric['rate']
        assert root.value == Decimal(190) / Decimal(300) * 100
        assert root.value.quantize(Decimal('0.01')) == expected and root.value != wrong_mean
        assert len(queries) == 4 and all('JOIN' not in sql.upper() for sql in queries)
        from smart_reporting.tests.c02_native_delivery import exercise_c02_native_delivery

        await exercise_c02_native_delivery(ctx, bases, store, receipt_snapshot[0]['workflow_scope'],
            adoption, corrected, monkeypatch)
        runtime = SimpleNamespace(datasets=store, configuration_provider=SimpleNamespace(vault=ctx['vault']),
            report_build_identity=build_identity(), business_evidence_service=ctx['policy_service'].evidence)
        request = {'expectedIssueVersion': 3, 'caseId': 'C02', 'targetRunId': adoption.target_run_id,
            'targetReportRevision': 'initial', 'calculationReceiptId': corrected.receipt_id,
            'expectationReason': '独立原始预算A100+B200=300，实际A60+30+B100=190，合计比率四舍五入两位为63.33%。',
            'assertions': [{'factId': root.fact_id, 'expectedStatus': 'computed', 'expectedValue': str(expected), 'unit': '%', 'decimalPlaces': 2}]}
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from smart_reporting.management.api import (
            SESSION_COOKIE,
            create_management_router,
            csrf_token,
        )
        from smart_reporting.management.metrics_api import create_metrics_router
        from smart_reporting.management.settings import ManagementSettings
        from smart_reporting.management.statistical_policy_api import (
            create_statistical_policy_router,
        )

        app = FastAPI()
        app.include_router(create_management_router(ctx['scopes'].auth,
            ManagementSettings(public_origin='https://reports.test'), report_runtime=runtime))
        app.include_router(create_metrics_router(metrics, ManagementSettings(public_origin='https://reports.test')))
        app.include_router(create_statistical_policy_router(ctx['policy_service'], ManagementSettings(public_origin='https://reports.test')))
        prefix = '/management/api/v1/report-issue-reviews/issue-C02-real-ratio'
        admin_scope = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
            headers = {'origin': 'https://reports.test', 'x-csrf-token': csrf_token(ctx['token'])}
            failed_response = await client.post(prefix + '/regressions', headers=headers, json={**admin_scope,
                **request, 'requestId': 'C02-wrong-mean', 'assertions': [{**request['assertions'][0], 'expectedValue': '70'}]})
            assert failed_response.status_code == 200, failed_response.text
            failed = BasisIssueRegressionReceipt.model_validate(failed_response.json())
            passed_response = await client.post(prefix + '/regressions', headers=headers, json={**admin_scope,
                **request, 'requestId': 'C02-ratio-of-totals'})
            assert passed_response.status_code == 200, passed_response.text
            passed = BasisIssueRegressionReceipt.model_validate(passed_response.json())
            readback = await client.get(prefix + '/regressions/' + passed.receipt_id, params=admin_scope)
            assert readback.status_code == 200 and readback.json() == passed_response.json()
            resolution = await client.post(prefix + '/resolution-evidence-check', headers=headers, json={**admin_scope,
                'expectedIssueVersion': 3, 'regressionReceiptIds': [passed.receipt_id]})
            assert resolution.status_code == 200, resolution.text
            evidence = resolution.json()
            assert evidence['regressionEvidenceReady'] and evidence['originalEvidenceReady']
            assert evidence['reportRelationships'][0]['status'] == 'verified'
            assert evidence['deliveryReady'] is False and evidence['factPresentationReady'] is False
            assert evidence['businessApproval'] == 'not_performed' and evidence['issueClosed'] is False
            # C37沿用同一真实反例：退役错误精确版本，不把最新发布当默认回退。
            impact = await client.get('/management/api/v1/statistical-policies/monthly-budget/impact',
                params={**admin_scope, 'revision': 2})
            assert impact.status_code == 200, impact.text
            assert {(item['kind'], item['referenceId'], item['policyRevision']) for item in impact.json()['items']} == {
                ('default', 'budget_execution', 2), ('report', 'run-basis', 2)}
            retirement = await client.post('/management/api/v1/metrics/rate/versions/1/retire', headers=headers,
                json={**admin_scope, 'reason': 'C02反例确认项目均值不适合作为总体执行率。',
                    'replacement': {'metricId': 'rate', 'revision': 2}})
            assert retirement.status_code == 200, retirement.text
            default = await client.get('/management/api/v1/report-policy-defaults/budget_execution', params=admin_scope)
            assert default.status_code == 200, default.text
            assert default.json()['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 2}
            assert any(item['code'] == 'semantic_asset_retired' and item['impact'] == 'unavailable'
                for item in default.json()['issues'])
            from smart_reporting.management.models import ManagementError

            await ctx['provider'].register_run('C37-new-run', ctx['scope'], user_id='7', thread_id='C37-new-thread', entrypoint='cli')
            with pytest.raises(ManagementError) as unavailable:
                await bases.register_report_basis('C37-new-run', ctx['scope'], user_id='7', thread_id='C37-new-thread',
                    request_summary=request_summary(ctx['scope_id']), build_identity=build_identity())
            assert unavailable.value.code == 'management_semantic_asset_retired'
        assert failed.status == 'failed'
        assert passed.status == 'passed' and passed.business_approval == 'not_performed'
        assert await read_regression(issues, ctx['token'], ctx['scope'], 'issue-C02-real-ratio', failed.receipt_id) == failed
        assert await read_regression(issues, ctx['token'], ctx['scope'], 'issue-C02-real-ratio', passed.receipt_id) == passed
        assert len(queries) == 4  # 回归复算冻结CSV，不新增业务SQL。
        restored = await bases.load_report_basis('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis')
        assert restored == basis
        assert await bases.load_basis_receipts('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis', report_revision='initial') == (original,)
        assert (await issues.report_list(**binding))['items'][0]['review']['status'] == 'accepted'
        # 将实际回执与字节独立留存；不把尚未生成的报告写入验收清单。
        import csv
        import hashlib
        import json
        import os
        import tempfile
        from pathlib import Path

        evidence_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c02-managed-{os.getpid()}-{"-".join(requested_outputs)}'
        evidence_dir.mkdir(exist_ok=True)
        for table in ('budget', 'actual'):
            with (evidence_dir / f'raw-{table}.csv').open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(('project_id', 'amount', 'period'))
                writer.writerows(connection.execute(f'SELECT project_id,amount,period FROM test.{table} ORDER BY project_id,period').fetchall())
        for label, calculation in (('original', original), ('corrected', corrected)):
            for index, snapshot in enumerate(calculation.datasets):
                raw, _ = await store.service.afile_bytes(calculation.workspace.workspace_key, snapshot.file.path)
                assert hashlib.sha256(raw).hexdigest() == snapshot.file.sha256 and len(raw) == snapshot.file.size
                (evidence_dir / f'{label}-{index + 1}.csv').write_bytes(raw)
            (evidence_dir / f'{label}.json').write_text(calculation.model_dump_json(by_alias=True, indent=2) + '\n')
            execution = await bases.load_execution_context('run-basis' if label == 'original' else adoption.target_run_id,
                ctx['scope'], user_id='7', thread_id='thread-basis', vault=ctx['vault'])
            (evidence_dir / f'{label}-rules.json').write_text(json.dumps({
                'basis': execution.basis.model_dump(mode='json', by_alias=True),
                'policy': execution.policy.model_dump(mode='json', by_alias=True),
                'metrics': [item.model_dump(mode='json', by_alias=True) for item in execution.metrics],
            }, ensure_ascii=False, indent=2) + '\n')
        for label, receipt in (('failed-70', failed), ('passed-63.33', passed)):
            (evidence_dir / f'{label}.json').write_text(receipt.model_dump_json(by_alias=True, indent=2) + '\n')
        (evidence_dir / 'resolution-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        (evidence_dir / 'adoption.json').write_text(adoption.model_dump_json(by_alias=True, indent=2) + '\n')
        (evidence_dir / 'issue.json').write_text(json.dumps((await issues.report_list(**binding))['items'][0], ensure_ascii=False, indent=2) + '\n')
        (evidence_dir / 'retirement-impact.json').write_text(json.dumps({'impact': impact.json(),
            'retirement': retirement.json(), 'default': default.json(),
            'newDefaultRunError': unavailable.value.code}, ensure_ascii=False, indent=2) + '\n')
        files = [{'file': path.name, 'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(evidence_dir.iterdir()) if path.name != 'manifest.json']
        (evidence_dir / 'manifest.json').write_text(json.dumps({'caseId': 'C02', 'oldValue': '70',
            'expectedValue': '63.33', 'decimalPlaces': 2, 'businessApproval': 'not_performed',
            'reportDeliveryVerified': False, 'issueClosed': False, 'businessQueries': len(queries),
            'files': files}, ensure_ascii=False, indent=2) + '\n')
