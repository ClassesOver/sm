"""本报告计算依据只从可信运行身份解析一次，之后按不可变版本读回。"""

import pytest

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_evidence_publication import (
    approved_document,
    evidence_service,
    publish,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def request_summary(scope_id, *, goal="检查本月预算执行", **changes):
    return {
        "goal": goal,
        "scenario": "budget_execution",
        "organization": scope_id,
        "period": {"start": "2026-11-01", "end": "2026-12-01"},
        "displayUnit": "CNY",
        "requestedOutputs": ["pdf"],
        "questions": [{"id": "q-rate", "text": "本月预算执行率是多少？"}],
        **changes,
    }


@pytest.fixture
async def basis_context(document_context, index_context):
    from cryptography.fernet import Fernet
    from sqlalchemy import insert, update

    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.repository import (
        catalog_versions,
        tenant_settings,
    )
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.reporting.contract import (
        ModelColumn,
        ModelTable,
        ModelTermsResponse,
        RawDdlModel,
        SourceRef,
        schema_hash,
    )

    documents, token, scope, other_scope, _, _ = document_context
    scopes = documents.scopes
    repository = scopes.repository
    evidence_docs = document_context
    await approved_document(evidence_docs)
    evidence = evidence_service(evidence_docs, index_context)
    rules = await publish(evidence, evidence_docs)

    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.statistical_policies import StatisticalPolicyService
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload, policy_payload

    metrics = MetricService(scopes)
    body = metric_payload()
    body.pop("scopeId")
    body.pop("revision")
    await metrics.save_draft(token, scope, body, 0)
    await metrics.publish(token, scope, "budget", expected_version=1)
    policy_service = StatisticalPolicyService(scopes, evidence)
    policy = policy_payload(evidenceReleaseId=rules.release_id)
    policy.pop("scopeId")
    policy.pop("revision")
    await policy_service.save_draft(token, scope, policy, expected_version=0)
    await policy_service.publish(token, scope, "monthly-budget", expected_version=1)
    await policy_service.set_default(
        token,
        scope,
        "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": 1},
        expected_version=0,
    )

    vault = CredentialVault(f"key-a:{Fernet.generate_key().decode()}")
    # 通过新连接服务发布，合成目录不依赖旧Profile。
    table = ModelTable(sourceId="warehouse", database="test", name="budget", columns=(
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=False),
        ModelColumn(name="period", dataType="DATE", nullable=False),
        ModelColumn(name="project_id", dataType="VARCHAR(20)", nullable=False),
    ))
    model = ModelTermsResponse(revision="catalog-1", schemaHash=schema_hash((table,)),
        sourceRefs=(SourceRef(sourceId="warehouse"),), tables=(table,),
        ddlModels=(RawDdlModel(id=1, modelName="预算", ddl="CREATE TABLE test.budget (amount DECIMAL(18,2) NOT NULL, period DATE NOT NULL, project_id VARCHAR(20) NOT NULL)"),))
    catalog_body = {"metadata": model.model_dump(mode="json", by_alias=True),
        "tables": [table.model_dump(mode="json", by_alias=True)]}
    from smart_reporting.management.data_sources.models import SourceDraftInput
    source_service = SourceService(scopes, vault)
    await source_service.create_draft(token, scope, "warehouse", SourceDraftInput(
        name="合成数据源", database="test", metadataVersionId="warehouse:1",
        dsn="starrocks://reporter:synthetic-only@localhost:9030/test"))
    async with repository.transaction() as connection:
        registered_scope = await scopes.require_registered(connection, scope)
        now = scopes.auth.clock()
        sid = registered_scope["id"]
        await connection.execute(insert(catalog_versions).values(scope_id=sid, source_id="warehouse",
            revision=1, status="published", catalog=catalog_body,
            content_hash=CatalogService._hash(catalog_body), synced_at=now))
        await connection.execute(update(tenant_settings).where(tenant_settings.c.id == sid)
            .values(default_source_ids=["warehouse"]))
    await source_service.publish(token, scope, "warehouse", 1)
    provider = ManagedConfigurationProvider(scopes, vault)
    await provider.register_run("run-basis", scope, user_id="7", thread_id="thread-basis", entrypoint="cli")
    await provider.register_run("run-other", other_scope, user_id="7", thread_id="thread-other", entrypoint="cli")
    return {
        "scopes": scopes,
        "repository": repository,
        "provider": provider,
        "policy_service": policy_service,
        "token": token,
        "scope": scope,
        "other_scope": other_scope,
        "scope_id": registered_scope["id"],
        "release_id": rules.release_id,
        "vault": vault,
    }


async def test_report_basis_pins_policy_metrics_source_catalog_and_restores_without_default_drift(basis_context):
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.semantics.models import BuildIdentity

    service = ReportBasisService(basis_context["scopes"])
    provider = basis_context["provider"]
    await provider.assert_identity("run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis")
    build = BuildIdentity(commit="a" * 40, sourceHash="b" * 64, dependencyHash="c" * 64, compilerVersion="semantic-v1")
    request = request_summary(basis_context["scope_id"])
    first = await service.register_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        request_summary=request, build_identity=build,
    )
    assert first.policy_version.revision == 1
    assert first.metric_versions[0].metric_id == "budget"
    assert first.source_versions[0].revision == 1
    assert first.catalog_refs[0].revision == 1

    policy_service = basis_context["policy_service"]
    original = await policy_service.get(basis_context["token"], basis_context["scope"], "monthly-budget")
    changed = {key: value for key, value in original["draft"]["document"].items() if key not in ("scopeId", "revision")}
    await policy_service.save_draft(basis_context["token"], basis_context["scope"], {
        **changed, "name": "第二版口径",
    }, expected_version=1)
    second = await policy_service.publish(
        basis_context["token"], basis_context["scope"], "monthly-budget", expected_version=2,
    )
    await policy_service.set_default(
        basis_context["token"], basis_context["scope"], "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": second["revision"]},
        expected_version=1,
    )

    restored = await ReportBasisService(basis_context["scopes"]).load_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
    )
    retried = await service.register_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        request_summary=request, build_identity=build,
    )
    assert restored == first == retried
    assert restored.policy_version.revision == 1
    assert (await policy_service.get_default(
        basis_context["token"], basis_context["scope"], "budget_execution",
    ))["policyVersion"]["revision"] == 2


async def test_unregistered_forged_and_cross_scope_run_cannot_create_basis(basis_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.semantics.models import BuildIdentity

    service = ReportBasisService(basis_context["scopes"])
    build = BuildIdentity(commit="a" * 40, sourceHash="b" * 64, dependencyHash="c" * 64, compilerVersion="semantic-v1")
    summary = request_summary(basis_context["scope_id"])
    with pytest.raises(ManagementError, match="management_run_identity_missing"):
        await service.register_report_basis(
            "unregistered", basis_context["scope"], user_id="7", thread_id="thread-basis",
            request_summary=summary, build_identity=build,
        )
    with pytest.raises(ManagementError) as wrong_thread:
        await service.register_report_basis(
            "run-basis", basis_context["scope"], user_id="7", thread_id="forged",
            request_summary=summary, build_identity=build,
        )
    assert wrong_thread.value.status == 403
    with pytest.raises(ManagementError) as foreign:
        await service.register_report_basis(
            "run-basis", basis_context["other_scope"], user_id="7", thread_id="thread-basis",
            request_summary=summary, build_identity=build,
        )
    assert foreign.value.status == 403


def build_identity():
    from smart_reporting.reporting.semantics.models import BuildIdentity
    return BuildIdentity(commit="a" * 40, sourceHash="b" * 64, dependencyHash="c" * 64, compilerVersion="semantic-v1")


async def register_basis(context, **changes):
    from smart_reporting.management.report_bases import ReportBasisService
    return await ReportBasisService(context["scopes"]).register_report_basis(
        "run-basis", context["scope"], user_id="7", thread_id="thread-basis",
        request_summary=request_summary(context["scope_id"]), build_identity=build_identity(), **changes,
    )


async def test_concurrent_different_selections_create_one_basis_and_leave_original_unchanged(basis_context):
    import asyncio

    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_bases
    service = ReportBasisService(basis_context["scopes"])
    attempts = await asyncio.gather(*(service.register_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        request_summary=request_summary(basis_context["scope_id"], goal=goal),
        build_identity=build_identity(),
    ) for goal in ("核对预算", "核对实际")), return_exceptions=True)
    failures = [item for item in attempts if isinstance(item, ManagementError)]
    assert len(failures) == 1 and failures[0].status == 409
    original = next(item for item in attempts if not isinstance(item, Exception))
    assert await service.load_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
    ) == original
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_bases)) == 1


async def test_retirement_blocks_new_selection_but_registered_basis_keeps_exact_versions(basis_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    first = await register_basis(basis_context)
    await MetricService(basis_context["scopes"]).retire(
        basis_context["token"], basis_context["scope"], "budget", 1, reason="合成核对发现错误",
    )
    service = ReportBasisService(basis_context["scopes"])
    assert await service.load_report_basis(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
    ) == first
    await basis_context["provider"].register_run(
        "new-run", basis_context["scope"], user_id="7", thread_id="new-thread", entrypoint="cli",
    )
    with pytest.raises(ManagementError, match="management_semantic_asset_retired"):
        await service.register_report_basis(
            "new-run", basis_context["scope"], user_id="7", thread_id="new-thread",
            request_summary=request_summary(basis_context["scope_id"]), build_identity=build_identity(),
        )


async def test_runtime_reference_tampering_and_old_contract_are_rejected(basis_context):
    from sqlalchemy import update

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import runtime_snapshots
    await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    async with basis_context["repository"].transaction() as connection:
        await connection.execute(update(runtime_snapshots).where(runtime_snapshots.c.run_id == "run-basis")
            .values(reference_hash="0" * 64))
    with pytest.raises(ManagementError, match="management_basis_identity_invalid"):
        await service.load_report_basis(
            "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        )
    async with basis_context["repository"].transaction() as connection:
        await connection.execute(update(runtime_snapshots).where(runtime_snapshots.c.run_id == "run-basis")
            .values(references={"effectiveProfileHash": "a" * 64}))
    with pytest.raises(ManagementError, match="report_contract_retired"):
        await service.load_report_basis(
            "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        )


@pytest.fixture
async def receipt_snapshot(basis_context, tmp_path):
    import hashlib

    from agno.run import RunContext

    from smart_reporting.reporting.data_sources import DatasetHandle, ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.workflow.scope import (
        ReportingWorkflowScope,
        reporting_scope_keys,
    )
    keys = reporting_scope_keys(database=basis_context["scope"].database, company_id=basis_context["scope"].company_id,
        user_id="7", thread_id="thread-basis", run_id="run-basis")
    scope = ReportingWorkflowScope(run_id="run-basis", external_run_id="external-basis",
        session_id="session-basis", caller_thread_id="thread-basis", user_id="7",
        database=basis_context["scope"].database, company_id=basis_context["scope"].company_id,
        thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    registry = ReportingWorkspaceRegistry(tmp_path / "workspaces", secret="synthetic-workspace-secret-32bytes")
    identity = registry.resolve(scope)
    store = ReportDatasetStore(ReportingWorkspaceRouter(registry))
    content = b"value,observed_count,nonnull_count\n300.00,2,2\n"
    await store.service.awrite_bytes(keys.workspace_key, "datasets/budget.csv", content)
    from smart_reporting.reporting.workflow.query_pipeline import normalized_sql_hash
    sql = "SELECT SUM(amount) AS value FROM test.budget"
    handle = DatasetHandle(dataset_id="dataset-budget01", source_id="warehouse", path="datasets/budget.csv",
        row_count=1, size=len(content), sha256=hashlib.sha256(content).hexdigest(),
        requirement_id="metric-budget", sql_hash=normalized_sql_hash(sql), query_sql=sql,
        materialized_at="2026-11-09T00:00:00Z")
    return dict(dataset_handles=(handle,), dataset_store=store,
        run_context=RunContext(run_id="run-basis", session_id=keys.workspace_key, session_state={}),
        workflow_scope=scope), identity.root


async def test_calculation_receipt_is_typed_append_only_and_same_request_can_be_read_back(basis_context, receipt_snapshot):
    from decimal import Decimal

    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_basis_receipts
    from smart_reporting.reporting.semantics.models import MetricRequest, MetricResult
    basis = await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    request = MetricRequest(metricVersion={"metricId": "budget", "revision": 1},
        basisId=basis.id, period=basis.request_summary.period)
    result = MetricResult(metricVersion=request.metric_version, basisId=basis.id, calculationId="calc-1",
        factId="fact-1", period=request.period, value=Decimal(300), unit="CNY", status="computed", datasetIds=("dataset-budget01",))
    options = dict(user_id="7", thread_id="thread-basis", receipt_id="receipt-1",
        report_revision="revision-1", request=request, results=(result,), **receipt_snapshot[0])
    first = await service.append_basis_receipt("run-basis", basis_context["scope"], **options)
    assert first.results[0].value == Decimal(300)
    assert await service.append_basis_receipt("run-basis", basis_context["scope"], **options) == first
    with pytest.raises(ManagementError, match="management_basis_receipt_conflict"):
        await service.append_basis_receipt("run-basis", basis_context["scope"],
            **{**options, "results": (result.model_copy(update={"value": Decimal(301)}),)})
    with pytest.raises(ManagementError) as foreign_result:
        await service.append_basis_receipt("run-basis", basis_context["scope"],
            **{**options, "receipt_id": "receipt-2", "results": (result.model_copy(update={"basis_id": "foreign-basis"}),)})
    assert foreign_result.value.status in (403, 422)
    rows = await service.load_basis_receipts("run-basis", basis_context["scope"],
        user_id="7", thread_id="thread-basis", report_revision="revision-1")
    assert rows == (first,)
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_basis_receipts)) == 1


async def test_basis_registration_and_runtime_reference_roll_back_when_audit_fails(basis_context, monkeypatch):
    from sqlalchemy import func, select

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import audit_events, report_bases, runtime_snapshots
    service = ReportBasisService(basis_context["scopes"])
    async def broken_audit(*args, **kwargs):
        raise RuntimeError("synthetic basis audit failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "_audit", broken_audit)
        with pytest.raises(RuntimeError, match="synthetic basis audit failure"):
            await service.register_report_basis(
                "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
                request_summary=request_summary(basis_context["scope_id"]), build_identity=build_identity(),
            )
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_bases)) == 0
        assert await connection.scalar(select(runtime_snapshots.c.references).where(runtime_snapshots.c.run_id == "run-basis")) is None
    basis = await register_basis(basis_context)
    async with basis_context["repository"].engine.connect() as connection:
        events = (await connection.execute(select(audit_events).where(audit_events.c.action == "report_basis_registered"))).mappings().all()
    assert len(events) == 1
    assert events[0]["actor"] == "report-runtime"
    assert events[0]["details"]["basisId"] == basis.id
    assert "检查本月预算执行" not in str(events)


async def test_basis_restore_rejects_changed_catalog_and_source_revocation_without_rewriting_basis(basis_context):
    from sqlalchemy import select, update

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import catalog_versions, report_bases, sources
    basis = await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    async with basis_context["repository"].transaction() as connection:
        original_hash = await connection.scalar(select(catalog_versions.c.content_hash))
        await connection.execute(update(catalog_versions).values(content_hash="0" * 64))
    with pytest.raises(ManagementError, match="management_basis_identity_invalid"):
        await service.load_report_basis(
            "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        )
    async with basis_context["repository"].transaction() as connection:
        await connection.execute(update(catalog_versions).values(content_hash=original_hash))
        await connection.execute(update(sources).values(enabled=0))
    with pytest.raises(ManagementError, match="management_source_disabled"):
        await service.load_report_basis(
            "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        )
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(report_bases.c.document)) == basis.model_dump(mode="json", by_alias=True)


async def test_execution_context_restores_pinned_sources_and_catalog_without_profile(basis_context):
    from smart_reporting.management.report_bases import ReportBasisService
    service = ReportBasisService(basis_context["scopes"])
    basis = await register_basis(basis_context)
    restored = await service.load_execution_context(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        vault=basis_context["vault"],
    )
    assert restored.basis == basis
    assert restored.policy.id == "monthly-budget"
    assert [(metric.id, metric.revision) for metric in restored.metrics] == [("budget", 1)]
    assert list(restored.sources) == ["warehouse"]
    assert restored.sources["warehouse"].database == "test"
    assert not hasattr(restored.sources["warehouse"], "reporting_profile")
    assert restored.metadata["warehouse"].tables[0].name == "budget"
    assert restored.sources["warehouse"].connection_dsn().endswith("/test")
    assert "synthetic-only" not in repr(restored)


async def test_execution_context_rejects_corrupted_credential_identity(basis_context):
    from sqlalchemy import update

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import source_credentials
    await register_basis(basis_context)
    async with basis_context["repository"].transaction() as connection:
        await connection.execute(update(source_credentials).values(secret_hash="0" * 64))
    with pytest.raises(ManagementError, match="management_basis_identity_invalid"):
        await ReportBasisService(basis_context["scopes"]).load_execution_context(
            "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
            vault=basis_context["vault"],
        )


async def test_profile_bound_source_cannot_enter_new_report_basis(basis_context):
    from sqlalchemy import update

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import source_versions
    async with basis_context["repository"].transaction() as connection:
        await connection.execute(update(source_versions).values(profile_version_id="legacy:1"))
    with pytest.raises(ManagementError, match="management_source_contract_retired"):
        await register_basis(basis_context)


async def test_receipt_rejects_changed_units_and_undeclared_dimensions(basis_context, receipt_snapshot):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.semantics.models import MetricRequest, MetricResult
    basis = await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    request = MetricRequest(metricVersion={"metricId": "budget", "revision": 1},
        basisId=basis.id, period=basis.request_summary.period)
    result = MetricResult(metricVersion=request.metric_version, basisId=basis.id, calculationId="calc-1",
        factId="fact-1", period=request.period, value=300, unit="CNY", status="computed", datasetIds=("dataset-budget01",))
    for mutation in ({"unit": "万元"}, {"dimensions": [{"dimensionId": "department", "value": "A"}]}):
        changed = MetricResult.model_validate({**result.model_dump(), **mutation})
        with pytest.raises(ManagementError, match="management_basis_receipt_invalid"):
            await service.append_basis_receipt("run-basis", basis_context["scope"],
                user_id="7", thread_id="thread-basis", receipt_id="receipt-1",
                report_revision="revision-1", request=request, results=(changed,), **receipt_snapshot[0])


async def test_registered_basis_real_sql_csv_and_receipt_survive_service_restart(basis_context, tmp_path):
    from decimal import Decimal

    import duckdb
    from agno.run import RunContext
    from sqlglot import parse_one

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_source.materialization import CsvMaterializer
    from smart_reporting.reporting.data_sources import ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    from smart_reporting.reporting.semantics.models import MetricRequest
    from smart_reporting.reporting.workflow.scope import (
        ReportingWorkflowScope,
        reporting_scope_keys,
    )

    basis = await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    registered = await service.load_execution_context(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis", vault=basis_context["vault"],
    )
    request = MetricRequest(metricVersion={"metricId": "budget", "revision": 1},
        basisId=basis.id, period=basis.request_summary.period)
    plan = compile_metric(request, registered.policy, registered.metrics, registered.metadata["warehouse"].tables)
    registry = ReportingWorkspaceRegistry(tmp_path / "workspaces", secret="synthetic-workspace-secret-32bytes")
    keys = reporting_scope_keys(database=basis_context["scope"].database, company_id=basis_context["scope"].company_id,
        user_id="7", thread_id="thread-basis", run_id="run-basis")
    workflow_scope = ReportingWorkflowScope(run_id="run-basis", external_run_id="external-basis",
        session_id="session-basis", caller_thread_id="thread-basis", user_id="7",
        database=basis_context["scope"].database, company_id=basis_context["scope"].company_id,
        thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    registry.resolve(workflow_scope)
    store = ReportDatasetStore(ReportingWorkspaceRouter(registry))
    context = RunContext(run_id="run-basis", session_id=keys.workspace_key, session_state={})
    with duckdb.connect() as connection:
        connection.execute("CREATE SCHEMA test")
        connection.execute("CREATE TABLE test.budget(amount DECIMAL(18,2), period DATE, project_id VARCHAR)")
        connection.execute("INSERT INTO test.budget VALUES (100,'2026-11-01','A'),(200,'2026-11-30','B'),(999,'2026-12-01','A')")
        class RealSqlSource:
            config = registered.sources["warehouse"]
            async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                cursor = connection.execute(parse_one(sql, read="mysql").sql(dialect="duckdb"), parameters)
                writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
                writer.append(tuple(cursor.fetchall()))
                return writer.finish()
        calculated = await execute_metric(plan, {"warehouse": RealSqlSource()},
            datasets=store, run_context=context, calculation_id="calculation-actual")
        assert calculated.results[0].value == Decimal(300)
        await service.append_basis_receipt("run-basis", basis_context["scope"],
            user_id="7", thread_id="thread-basis", receipt_id="receipt-actual",
            report_revision="revision-actual", request=request, results=calculated.results, readiness=calculated.readiness,
            dataset_handles=calculated.datasets, dataset_store=store, run_context=context, workflow_scope=workflow_scope)
        connection.execute("UPDATE test.budget SET amount=1")
    restored = await ReportBasisService(basis_context["scopes"]).load_basis_receipts(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis", report_revision="revision-actual",
    )
    assert len(restored) == 1 and restored[0].results[0].value == Decimal(300)
    assert restored[0].readiness == calculated.readiness
    await registry.aclose()
    registry = ReportingWorkspaceRegistry(tmp_path / "workspaces", secret="synthetic-workspace-secret-32bytes")
    store = ReportDatasetStore(ReportingWorkspaceRouter(registry))
    context = RunContext(run_id="run-basis", session_id=keys.workspace_key, session_state={
        "report_dataset_handles": {"forged-dataset": {"path": "forged.csv"}},
    })
    handles = await ReportBasisService(basis_context["scopes"]).restore_receipt_datasets(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
        report_revision="revision-actual", dataset_store=store, run_context=context, workflow_scope=workflow_scope,
    )
    assert tuple(handle.dataset_id for handle in handles) == restored[0].results[0].dataset_ids
    assert "forged-dataset" not in context.session_state["report_dataset_handles"]
    paths = await store.resolve_dataset_paths(restored[0].results[0].dataset_ids, run_context=context)
    body, _ = await store.service.afile_bytes(keys.workspace_key, paths[0])
    assert b"300.00" in body and b"999" not in body
    original = body
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.data_sources import REPORT_DATASET_HANDLES_STATE_KEY
    for replacement in (b"value,observed_count,nonnull_count\n301.00,2,2\n", None):
        context.session_state.clear()
        path = registry.resolve(workflow_scope).root / paths[0]
        if replacement is None:
            path.unlink()
        else:
            path.write_bytes(replacement)
        with pytest.raises(ManagementError, match="management_basis_snapshot_unavailable"):
            await service.restore_receipt_datasets(
                "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis",
                report_revision="revision-actual", dataset_store=store, run_context=context, workflow_scope=workflow_scope,
            )
        assert REPORT_DATASET_HANDLES_STATE_KEY not in context.session_state
        path.write_bytes(original)


async def snapshot_receipt_options(basis_context, receipt_snapshot):
    from smart_reporting.reporting.semantics.models import MetricRequest, MetricResult
    basis = await register_basis(basis_context)
    request = MetricRequest(metricVersion={"metricId": "budget", "revision": 1},
        basisId=basis.id, period=basis.request_summary.period)
    result = MetricResult(metricVersion=request.metric_version, basisId=basis.id, calculationId="calc-snapshot",
        factId="fact-snapshot", period=request.period, value=300, unit="CNY", status="computed",
        datasetIds=("dataset-budget01",))
    return dict(user_id="7", thread_id="thread-basis", receipt_id="receipt-snapshot",
        report_revision="revision-snapshot", request=request, results=(result,), **receipt_snapshot[0])


async def test_receipt_rejects_missing_snapshots_foreign_sources_and_forged_workspaces(basis_context, receipt_snapshot):
    from dataclasses import replace

    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_basis_receipts
    options = await snapshot_receipt_options(basis_context, receipt_snapshot)
    handle = options["dataset_handles"][0]
    mutations = [
        {"dataset_handles": ()},
        {"dataset_handles": (replace(handle, source_id="foreign-source"),)},
        {"workflow_scope": replace(options["workflow_scope"], database="foreign-database")},
        {"workflow_scope": replace(options["workflow_scope"], run_id="foreign-run")},
        {"workflow_scope": replace(options["workflow_scope"], workspace_key="forged-workspace")},
        {"dataset_handles": (replace(handle, sha256="0" * 64),)},
    ]
    service = ReportBasisService(basis_context["scopes"])
    for mutation in mutations:
        with pytest.raises(ManagementError):
            await service.append_basis_receipt("run-basis", basis_context["scope"], **{**options, **mutation})
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_basis_receipts)) == 0


async def test_snapshot_receipt_audit_failure_rolls_back_and_lost_response_reads_original(basis_context, receipt_snapshot, monkeypatch):
    from sqlalchemy import func, select

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_basis_receipts
    options = await snapshot_receipt_options(basis_context, receipt_snapshot)
    service = ReportBasisService(basis_context["scopes"])
    async def broken_audit(*args, **kwargs):
        raise RuntimeError("synthetic receipt audit failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "_audit", broken_audit)
        with pytest.raises(RuntimeError, match="synthetic receipt audit failure"):
            await service.append_basis_receipt("run-basis", basis_context["scope"], **options)
    async with basis_context["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_basis_receipts)) == 0
    await service.append_basis_receipt("run-basis", basis_context["scope"], **options)
    restarted = ReportBasisService(basis_context["scopes"])
    readback = await restarted.load_basis_receipts("run-basis", basis_context["scope"],
        user_id="7", thread_id="thread-basis", report_revision="revision-snapshot")
    assert len(readback) == 1 and readback[0].results[0].value == 300
    assert readback[0].datasets[0].file.sha256 == options["dataset_handles"][0].sha256
    assert await restarted.append_basis_receipt("run-basis", basis_context["scope"], **options) == readback[0]


async def test_restore_rejects_changed_workspace_secret_before_using_session_handles(basis_context, receipt_snapshot, tmp_path):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_sources import ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    options = await snapshot_receipt_options(basis_context, receipt_snapshot)
    service = ReportBasisService(basis_context["scopes"])
    await service.append_basis_receipt("run-basis", basis_context["scope"], **options)
    options["run_context"].session_state.clear()
    changed = ReportDatasetStore(ReportingWorkspaceRouter(ReportingWorkspaceRegistry(
        tmp_path / "workspaces", secret="different-workspace-secret-32bytes")))
    with pytest.raises(ManagementError, match="management_basis_workspace_mismatch"):
        await service.restore_receipt_datasets("run-basis", basis_context["scope"],
            user_id="7", thread_id="thread-basis", report_revision="revision-snapshot",
            dataset_store=changed, run_context=options["run_context"], workflow_scope=options["workflow_scope"])
    assert not options["run_context"].session_state


async def test_metric_choices_are_registered_per_question_and_restored_without_reselecting(basis_context):
    from smart_reporting.management.report_bases import ReportBasisService
    service = ReportBasisService(basis_context["scopes"])
    basis = await service.register_report_basis("run-basis", basis_context["scope"],
        user_id="7", thread_id="thread-basis", build_identity=build_identity(),
        request_summary=request_summary(basis_context["scope_id"], questions=[
            {"id": "q1", "text": "预算是多少"}, {"id": "q2", "text": "未登记的预测"}]))
    options = dict(user_id="7", thread_id="thread-basis", receipt_id="selection-1",
        report_revision="revision-1", vault=basis_context["vault"], requests=[
            {"questionId": "q1", "explicit": {"metricId": "budget", "revision": 1}},
            {"questionId": "q2"}])
    first = await service.append_selection_receipt("run-basis", basis_context["scope"], **options)
    assert first.basis_id == basis.id
    assert [(item.question_id, item.status) for item in first.selections] == [("q1", "resolved"), ("q2", "unavailable")]
    assert first.selections[0].source == "explicit" and first.selections[0].selected.revision == 1
    assert first.selections[1].issue_codes == ("metric_no_match",)
    assert await service.append_selection_receipt("run-basis", basis_context["scope"], **options) == first
    restored = await ReportBasisService(basis_context["scopes"]).load_basis_receipts(
        "run-basis", basis_context["scope"], user_id="7", thread_id="thread-basis", report_revision="revision-1")
    assert restored == (first,)


async def test_metric_choice_receipt_cannot_drop_questions_or_accept_unknown_identity(basis_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.models import ReportingError
    await register_basis(basis_context)
    service = ReportBasisService(basis_context["scopes"])
    for requests in ([], [{"questionId": "forged"}],
        [{"questionId": "q-rate", "explicit": {"metricId": "budget", "revision": 2}}]):
        with pytest.raises((ManagementError, ReportingError)):
            await service.append_selection_receipt("run-basis", basis_context["scope"],
                user_id="7", thread_id="thread-basis", receipt_id="selection-1",
                report_revision="revision-1", requests=requests, vault=basis_context["vault"])
    assert await service.load_basis_receipts("run-basis", basis_context["scope"],
        user_id="7", thread_id="thread-basis", report_revision="revision-1") == ()



async def test_public_request_registers_basis_with_trusted_scope_and_exact_choices(basis_context):
    from smart_reporting.management.report_bases import ReportBasisService

    ctx = basis_context
    service = ReportBasisService(ctx['scopes'])
    request = {
        'reportGoal': '核对预算与解释差异', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'},
        'comparisonRoles': [], 'displayUnit': '万元',
        'statisticalPolicyVersion': {'policyId': 'monthly-budget', 'revision': 1},
        'questions': [{'id': 'q1', 'text': '预算是多少？'}, {'id': 'q2', 'text': '差异原因是什么？'}],
        'sourceIds': ['warehouse'],
    }
    basis = await service.register_request_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', request=request, build_identity=build_identity())
    assert basis.scope_id == basis.request_summary.organization == ctx['scope_id']
    assert basis.request_summary.period.model_dump(mode='json') == {
        'start': '2026-11-01', 'end': '2026-12-01'}
    assert [question.id for question in basis.request_summary.questions] == ['q1', 'q2']
    assert basis.policy_version.revision == 1
    assert basis.request_summary.display_unit == '万元'
    assert [source.source_id for source in basis.source_versions] == ['warehouse']
    assert await service.register_request_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', request=request, build_identity=build_identity()) == basis


async def test_public_request_rejects_foreign_source_without_partial_basis(basis_context):
    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_bases

    ctx = basis_context
    service = ReportBasisService(ctx['scopes'])
    request = {'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'},
        'comparisonRoles': [], 'sourceIds': ['foreign-source']}
    with pytest.raises(ManagementError):
        await service.register_request_basis('run-basis', ctx['scope'],
            user_id='7', thread_id='thread-basis', request=request, build_identity=build_identity())
    async with ctx['repository'].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_bases)) == 0
    request['sourceIds'] = ['warehouse']
    basis = await service.register_request_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', request=request, build_identity=build_identity())
    assert [item.source_id for item in basis.source_versions] == ['warehouse']
    request['sourceIds'] = ['foreign-source']
    with pytest.raises(ManagementError) as error:
        await service.register_request_basis('run-basis', ctx['scope'],
            user_id='7', thread_id='thread-basis', request=request, build_identity=build_identity())
    assert error.value.code == 'management_basis_selection_conflict'
    restored = await service.load_report_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis')
    assert restored == basis


async def test_scenario_candidates_require_trusted_run_and_only_include_its_scope(basis_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService

    ctx = basis_context
    service = ReportBasisService(ctx['scopes'])
    candidates = await service.scenario_candidates('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis')
    assert [(item.scenario, item.name) for item in candidates] == [('budget_execution', '合成预算执行')]
    assert await service.scenario_candidates('run-other', ctx['other_scope'],
        user_id='7', thread_id='thread-other') == ()
    with pytest.raises(ManagementError):
        await service.scenario_candidates('run-basis', ctx['scope'],
            user_id='forged', thread_id='thread-basis')


async def test_runtime_source_reads_use_registered_basis_without_old_profile_state(basis_context):
    from types import SimpleNamespace

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    ctx = basis_context
    service = ReportBasisService(ctx['scopes'])
    payload = {'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'}}
    await service.register_request_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', request=payload, build_identity=build_identity())
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = service
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    context = SimpleNamespace(run_id='run-basis', session_state={})
    sources = await runtime._sources(context)
    assert [(source.id, source.database) for source in sources] == [('warehouse', 'test')]
    assert (await runtime._source('warehouse', context)).id == 'warehouse'
    from smart_reporting.reporting.models import ReportingError
    with pytest.raises(ReportingError) as error:
        await runtime._source('foreign-source', context)
    assert error.value.code == 'report_source_not_allowed'
    execution = await service.load_execution_context('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', vault=ctx['vault'])
    from smart_reporting.reporting.contract import ReportRequestEnvelope
    from smart_reporting.reporting.workflow.query_pipeline import resolve_schema_snapshot
    envelope = ReportRequestEnvelope.model_validate({
        'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'},
    })
    metadata = execution.metadata['warehouse']
    snapshot = resolve_schema_snapshot(envelope, source=execution.sources['warehouse'],
        metadata=metadata, catalog=metadata.tables, preserve_metadata=True)
    context.session_state['report_workflow_input'] = envelope.model_dump(mode='json', by_alias=True, exclude_unset=True)
    context.session_state['report_schema_snapshots'] = [snapshot.model_dump(mode='json', by_alias=True)]
    assert (await runtime._sources(context))[0].id == 'warehouse'
    await runtime._ensure_managed_execution_state(context)
    context.session_state['report_schema_snapshots'][0]['tables'][0]['name'] = 'hidden_table'
    with pytest.raises(ReportingError) as error:
        await runtime._sources(context)
    assert error.value.code == 'management_runtime_execution_mismatch'
    context.session_state['report_schema_snapshots'] = [snapshot.model_dump(mode='json', by_alias=True)]
    context.session_state['report_workflow_input']['period']['end'] = '2026-11-29'
    with pytest.raises(ReportingError) as error:
        await runtime._ensure_managed_execution_state(context)
    assert error.value.code == 'management_runtime_request_mismatch'


async def test_runtime_normalization_uses_only_authenticated_scenario_candidates(basis_context):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt

    ctx = basis_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service = ReportBasisService(ctx['scopes'])
    runtime._request_normalizer = object()
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
        reportType='topic', domains=['budget'], scenario='budget_execution',
        period={'start': '2026-11-01', 'end': '2026-11-30'}))
    context = SimpleNamespace(session_state={}, run_id='run-basis')
    output = await runtime.normalize_report_request(
        SimpleNamespace(input='核对2026年11月预算执行', additional_data=None), context)
    prompt = runtime._run_planner.await_args.args[1]
    assert prompt['scenarioCandidates'] == [{'scenario': 'budget_execution', 'name': '合成预算执行'}]
    assert output.content['scenario'] == 'budget_execution'
    runtime._run_planner.return_value = NormalizedReportPrompt(
        reportType='topic', domains=['budget'], scenario='foreign-scenario',
        period={'start': '2026-11-01', 'end': '2026-11-30'})
    output = await runtime.normalize_report_request(
        SimpleNamespace(input='核对2026年11月预算执行', additional_data=None), context)
    assert 'clarificationQuestion' in output.content
    assert 'scenario' not in output.content


async def test_confirm_source_registers_new_basis_and_exposes_only_published_catalog(basis_context, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    ctx = basis_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = ReportBasisService(ctx['scopes'])
    runtime.report_build_identity = build_identity()
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    reads = []

    async def catalog(adapter):
        reads.append(adapter.config.id)
        return (CatalogTable(source_id='warehouse', database='test', name='budget', columns=(
            CatalogColumn('amount', 'DECIMAL(18,2)', False),
            CatalogColumn('period', 'DATE', False),
            CatalogColumn('project_id', 'VARCHAR(20)', False),
        )),)

    monkeypatch.setattr(StarRocksDataSourceAdapter, 'catalog', catalog)
    context = SimpleNamespace(run_id='run-basis', session_state={})
    payload = {'reportGoal': '核对预算', 'scenario': 'budget_execution',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'}, 'comparisonRoles': []}
    output = await runtime.confirm_source(
        SimpleNamespace(input=payload, previous_step_content=None), context)
    basis = await runtime.report_basis_service.load_report_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis')
    assert output.content['basisId'] == basis.id
    assert output.content['sources'][0]['allowedTables'] == ['test.budget']
    assert reads == ['warehouse']
    assert 'report_effective_profile' not in context.session_state
    assert runtime._snapshots(context)[0].tables[0].name == 'budget'
    await runtime._ensure_managed_execution_state(context)


async def test_runtime_metric_selection_registers_all_questions_and_recovers_without_reselection(basis_context):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    ctx = basis_context
    service = ReportBasisService(ctx['scopes'])
    await service.register_request_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', build_identity=build_identity(), request={
            'reportGoal': '核对预算并说明未登记预测', 'scenario': 'budget_execution',
            'period': {'start': '2026-11-01', 'end': '2026-11-30'}, 'comparisonRoles': [],
            'questions': [{'id': 'q1', 'text': '预算是多少？'}, {'id': 'q2', 'text': '预测是多少？'}],
        })
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = service
    runtime._metric_selection_agent = object()
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    runtime._run_planner = AsyncMock(return_value={
        'questions': [{'questionId': 'q1', 'candidates': [{
            'metricVersion': {'metricId': 'budget', 'revision': 1}, 'reason': '预算问题',
        }]}, {'questionId': 'q2', 'candidates': []}],
    })
    context = SimpleNamespace(run_id='run-basis', session_state={})
    output = await runtime.select_report_metrics(SimpleNamespace(), context)
    assert [(item['questionId'], item['status']) for item in output.content['selections']] == [
        ('q1', 'resolved'), ('q2', 'unavailable'),
    ]
    prompt = runtime._run_planner.await_args.args[1]
    assert [item['id'] for item in prompt['questions']] == ['q1', 'q2']
    assert [(item['id'], item['revision']) for item in prompt['metrics']] == [('budget', 1)]
    runtime._run_planner = AsyncMock(side_effect=AssertionError('恢复不应重新选择指标'))
    context.session_state.clear()
    restored = await runtime.select_report_metrics(SimpleNamespace(), context)
    assert restored.content == output.content


@pytest.mark.parametrize("proposal", [
    {"questions": [{"questionId": "forged", "candidates": []}]},
    {"questions": [{"questionId": "q-rate", "candidates": [{
        "metricVersion": {"metricId": "budget", "revision": 2}, "reason": "伪造版本",
    }]}]},
    {"questions": [{"questionId": "q-rate", "candidates": [],
        "explicit": {"metricId": "budget", "revision": 1}}]},
    {"questions": [{"questionId": "q-rate", "candidates": []},
        {"questionId": "q-rate", "candidates": []}]},
])
async def test_runtime_invalid_metric_proposal_cannot_register_selection(basis_context, proposal):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pydantic import ValidationError

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    ctx = basis_context
    await register_basis(ctx)
    service = ReportBasisService(ctx['scopes'])
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = service
    runtime._metric_selection_agent = object()
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    runtime._run_planner = AsyncMock(return_value=proposal)
    with pytest.raises((ReportingError, ValidationError)):
        await runtime.select_report_metrics(SimpleNamespace(),
            SimpleNamespace(run_id='run-basis', session_state={}))
    assert await service.load_basis_receipts('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis', report_revision='initial') == ()


async def test_runtime_executes_selected_metrics_and_recovers_verified_csv(basis_context, tmp_path, monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import duckdb
    from agno.run import RunContext
    from sqlglot import parse_one

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_source.materialization import CsvMaterializer
    from smart_reporting.reporting.data_sources import ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.scope import (
        ReportingWorkflowScope,
        reporting_scope_keys,
    )

    ctx = basis_context
    await ReportBasisService(ctx['scopes']).register_report_basis('run-basis', ctx['scope'],
        user_id='7', thread_id='thread-basis',
        request_summary=request_summary(ctx['scope_id'], requestedOutputs=['pdf', 'docx'], domains=['budget']),
        build_identity=build_identity())
    service = ReportBasisService(ctx['scopes'])
    await service.append_selection_receipt('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
        report_revision='initial', receipt_id='initial-metric-selection', vault=ctx['vault'],
        requests=[{'questionId': 'q-rate', 'explicit': {'metricId': 'budget', 'revision': 1}}])
    keys = reporting_scope_keys(database=ctx['scope'].database, company_id=ctx['scope'].company_id,
        user_id='7', thread_id='thread-basis', run_id='run-basis')
    workflow_scope = ReportingWorkflowScope(run_id='run-basis', external_run_id='external-basis',
        session_id='session-basis', caller_thread_id='thread-basis', user_id='7',
        database=ctx['scope'].database, company_id=ctx['scope'].company_id,
        thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    registry = ReportingWorkspaceRegistry(tmp_path / 'workspaces', secret='synthetic-workspace-secret-32bytes')
    registry.resolve(workflow_scope)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = service
    runtime.datasets = ReportDatasetStore(ReportingWorkspaceRouter(registry))
    runtime._scope = lambda context: workflow_scope.as_state()
    runtime._run_planner = AsyncMock(side_effect=AssertionError('正式指标不能由模型SQL计算'))
    context = RunContext(run_id='run-basis', session_id='session-basis', user_id='7', session_state={})
    queries = []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(amount DECIMAL(18,2), period DATE, project_id VARCHAR)')
        connection.execute("INSERT INTO test.budget VALUES (100,'2026-11-01','A'),(200,'2026-11-30','B'),(999,'2026-12-01','A')")
        class SqlSource:
            def __init__(self, config, *, allowed_tables):
                self.config = config
                self.allowed_tables = allowed_tables
                assert allowed_tables == ('test.budget',)
            async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                queries.append(sql)
                cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
                writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
                writer.append(tuple(cursor.fetchall()))
                return writer.finish()
            async def aclose(self):
                pass
        monkeypatch.setattr('smart_reporting.reporting.workflow.runtime.datasets.StarRocksDataSourceAdapter', SqlSource, raising=False)
        output = await runtime.calculate_report_metrics(SimpleNamespace(), context)
        assert len(output.content['calculations']) == 1
        result = output.content['calculations'][0]['results'][0]
        assert Decimal(result['value']) == Decimal(300)
        assert result['metricVersion'] == {'metricId': 'budget', 'revision': 1}
        assert len(queries) == 1
        connection.execute('UPDATE test.budget SET amount=1')
        context.session_state.clear()
        restored = await runtime.calculate_report_metrics(SimpleNamespace(), context)
        assert restored.content == output.content
        assert len(queries) == 1
        paths = await runtime.datasets.resolve_dataset_paths(tuple(result['datasetIds']), run_context=runtime._tool_context(context))
        body, _ = await runtime.datasets.service.afile_bytes(keys.workspace_key, paths[0])
        assert b'300.00' in body and b'999' not in body
        from smart_reporting.reporting.contract import ReportRequestEnvelope
        from smart_reporting.reporting.workflow.query_pipeline import resolve_schema_snapshot
        from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle
        execution = await runtime._basis_execution_context(context)
        envelope = ReportRequestEnvelope.model_validate({
            'reportGoal': '检查本月预算执行', 'scenario': 'budget_execution',
            'period': {'start': '2026-11-01', 'end': '2026-11-30'},
            'questions': [{'id': 'q-rate', 'text': '本月预算执行率是多少？'}],
            'displayUnit': 'CNY', 'domains': ['budget'], 'comparisonRoles': [],
        })
        context.session_state['report_workflow_input'] = envelope.model_dump(mode='json', by_alias=True)
        context.session_state['report_schema_snapshots'] = [resolve_schema_snapshot(envelope,
            source=execution.sources['warehouse'], metadata=execution.metadata['warehouse'],
            catalog=execution.metadata['warehouse'].tables, preserve_metadata=True).model_dump(mode='json', by_alias=True)]
        context.session_state['report_data_shapes'] = []
        context.session_state['report_data_understanding'] = {'tables': [
            {'sourceId': 'warehouse', 'table': 'test.budget', 'periodColumn': 'period',
             'periodGranularity': 'date', 'role': '预算期间'}]}
        async def plan(agent, payload, run_context, **kwargs):
            metric_context = payload['metricContext']
            assert metric_context['selections'][0]['questionId'] == 'q-rate'
            assert Decimal(metric_context['calculations'][0]['results'][0]['value']) == Decimal(300)
            assert metric_context['calculations'][0]['results'][0]['factId'] == result['factId']
            return AnalysisBundle.model_validate({'analyses': [{'code': 'budget_total', 'domain': 'budget',
                'description': '核对已登记预算值', 'managementQuestion': '预算是多少？',
                'primaryMetricFamily': '预算', 'requirementIds': ['budget-details'],
                'analysisName': '预算核对', 'periodRoles': ['current'], 'seriesGranularity': None}],
                'requirements': [{'requirementId': 'budget-details', 'sourceId': 'warehouse',
                    'tables': [{'table': 'test.budget', 'periodColumn': 'period',
                        'periodGranularity': 'date', 'measureColumns': ['amount']}],
                    'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []}]})
        runtime._run_planner = plan
        runtime._analysis_agent = SimpleNamespace(id='analysis-planner')
        planned = await runtime.generate_analysis_plan(SimpleNamespace(), context)
        assert planned.content.analyses[0].code == 'budget_total'
        assert 'report_effective_profile' not in context.session_state
        assert len(queries) == 1
        from copy import deepcopy
        context.session_state['report_dataset_handles']['exploration-sentinel'] = {'kind': 'unrelated-exploration'}
        previous_handles = deepcopy(context.session_state['report_dataset_handles'])
        verified = await runtime._metric_planning_context(context)
        assert verified.calculations[0].results[0].value == Decimal(300)
        assert context.session_state['report_dataset_handles'] == previous_handles
        from hashlib import sha256

        from smart_reporting.reporting.hospital_operation.detailed_analysis import (
            DatasetAnalysisContext,
        )
        from smart_reporting.reporting.workflow.checkpoint import build_profile_coverage_manifest

        handle = verified.calculations[0].results[0].dataset_ids[0]
        stored = next(item for item in await service.load_basis_receipts('run-basis', ctx['scope'], user_id='7',
            thread_id='thread-basis', report_revision='initial') if item.kind == 'metric_calculation')
        snapshot = stored.datasets[0].to_handle()
        dataset_context = DatasetAnalysisContext(datasetId=handle, path=snapshot.path,
            size=snapshot.size, sha256=snapshot.sha256, rowCount=1, columnCount=3,
            profileFile={'path': 'profiles/formal-budget.json', 'size': 2, 'sha256': sha256(b'{}').hexdigest()},
            profileModelView={}, profileEngineVersion='test-fixture',
            fields=('value', 'observed_count', 'nonnull_count'),
            numericFields=('value', 'observed_count', 'nonnull_count'), periodValues=())
        context.session_state['report_analysis_data_context'] = [dataset_context.model_dump(mode='json', by_alias=True)]
        context.session_state['report_workflow_result'] = {'datasets': [snapshot.public_dict()]}
        context.session_state['report_profile_coverage'] = build_profile_coverage_manifest(
            dataset_handles=[snapshot.public_dict()],
            dataset_contexts=context.session_state['report_analysis_data_context']).model_dump(mode='json', by_alias=True)
        context.session_state['report_analysis_plan'][0]['requirementIds'] = [snapshot.requirement_id]
        runtime.workspace_service = runtime.datasets.service
        runtime._apply_durable_command = AsyncMock()
        detailed = await runtime.generate_detailed_analysis_plan(SimpleNamespace(), context)
        assert detailed.content.analyses[0].allowed_metric_codes == ('budget',)
        assert detailed.content.analyses[0].metrics == ()
        detail_file = context.session_state['report_analysis_context_file']
        raw, _ = await runtime.datasets.service.afile_bytes(keys.workspace_key, detail_file['path'])
        import json
        saved = json.loads(raw)['metricContext']
        assert saved['calculations'][0]['results'][0]['factId'] == result['factId']
        assert saved['calculations'][0]['results'][0]['value'] == result['value']
        assert context.session_state['report_request_context']['questionSpecs']['requiredQuestionIds'] == ['q-rate']
        from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
        from smart_reporting.reporting.workflow.runtime.models import GeneratedQueryBatch

        async def sql_plan(agent, payload, run_context, **kwargs):
            assert payload['metricContext']['calculations'][0]['results'][0]['factId'] == result['factId']
            return GeneratedQueryBatch.model_validate({'queries': [{'requirementId': 'budget-details',
                'sourceId': 'warehouse', 'sql': "SELECT period AS report_date, project_id AS project, SUM(amount) AS budget_total FROM test.budget "
                    "WHERE period BETWEEN '2026-11-01' AND '2026-11-30' GROUP BY period, project_id"}]})

        runtime._sql_agent = SimpleNamespace(id='sql-planner')
        runtime._run_planner = sql_plan
        await runtime.generate_query_candidates(SimpleNamespace(additional_data=None), context)
        runtime.delivery_settings = ReportDeliverySettings()
        runtime.report_tools = SimpleNamespace(
            report_prepare_dataset=AsyncMock(return_value={'jobId': 'exploration-test-job'}),
            bind_page_layout=AsyncMock())
        materialized = await runtime.materialize_datasets(SimpleNamespace(), context)
        exploration = materialized.content['datasets']
        assert len(exploration) == 2 and len(queries) == 2
        assert result['datasetIds'][0] in {item['datasetId'] for item in exploration}
        content, _ = await runtime.datasets.service.afile_bytes(keys.workspace_key, exploration[0]['path'])
        assert b'999' not in content and b'2026-12-01' not in content
        assert b'2026-11-01' in content and b'2026-11-30' in content
        assert (await runtime._metric_planning_context(context)).calculations[0].results[0].value == Decimal(300)
        context.session_state['report_effective_profile'] = {'dimensions': [
            {'code': 'month', 'kind': 'time', 'fieldRefs': ['warehouse.test.budget.period']}],
            'metrics': [{'code': 'forged', 'fieldRef': 'warehouse.test.budget.amount'}]}
        prepared_context = await runtime.prepare_analysis_context(SimpleNamespace(), context)
        dataset_view = prepared_context.content['datasetContexts'][0]
        assert dataset_view['periodGranularities'] == {'report_date': 'date'}
        assert dataset_view['organizationGrain'] == ['report_date', 'project']
        assert dataset_view['periodValues'] == ['2026-11-01', '2026-11-30']
        assert dataset_view['metricBindings'][0]['metricVersion'] == {'metricId': 'budget', 'revision': 1}
        assert dataset_view['metricBindings'][0]['measure']['datasetField'] == 'budget_total'
        assert dataset_view['metricSemantics'] == []
        cached = context.session_state['report_analysis_data_context'][0]
        cached['periodGranularities']['report_date'] = 'month'
        cached['metricBindings'][0]['metricVersion']['revision'] = 2
        restored_context = await runtime.prepare_analysis_context(SimpleNamespace(), context)
        restored_view = restored_context.content['datasetContexts'][0]
        assert restored_view['periodGranularities'] == {'report_date': 'date'}
        assert restored_view['metricBindings'][0]['metricVersion']['revision'] == 1
        assert len(queries) == 2
        context.session_state.pop('report_effective_profile')
        context.session_state['report_analysis_plan'][0]['requirementIds'] = ['budget-details']
        detailed_with_bindings = await runtime.generate_detailed_analysis_plan(SimpleNamespace(), context)
        assert detailed_with_bindings.content.analyses[0].metrics == ('budget_total',)
        from smart_reporting.reporting.data_sources import DatasetHandle
        fact_files = await runtime._prepare_deterministic_analysis_facts(run_context=context,
            thread_id=keys.workspace_key, report_run_id='semantic-report', revision=0,
            detailed_plan=detailed_with_bindings.content,
            dataset_handles=tuple(DatasetHandle.from_state(item) for item in exploration))
        facts_raw, _ = await runtime.datasets.service.afile_bytes(keys.workspace_key, fact_files['analysis_001'].path)
        facts_payload = json.loads(facts_raw)
        frozen_result = facts_payload['metricContext']['calculations'][0]['results'][0]
        assert frozen_result['factId'] == result['factId']
        assert Decimal(frozen_result['value']) == Decimal(300)
        assert facts_payload['metrics'] == []
        assert len(queries) == 2
        from smart_reporting.reporting.delivery.artifacts_v1 import authoritative_citations
        from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
        from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
        from smart_reporting.reporting.workflow.query_pipeline import DatasetLineage
        runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda _context, checkpoint: checkpoint)
        graph_checkpoint = await runtime._restore_or_create_finding_graph(run_context=context,
            checkpoint=ReportingCheckpoint(revision=1, phase='analysis', outlineHash='a' * 64, profileCoverage=_coverage()),
            thread_id=keys.workspace_key, report_run_id='semantic-report', revision=1, fact_files=fact_files,
            analysis_items={'analysis_001': {'analysisId': 'analysis_001',
                'datasetIds': [item['datasetId'] for item in exploration], 'evidenceFiles': []}},
            citation_bindings=authoritative_citations(tuple(DatasetLineage.model_validate(item)
                for item in context.session_state['report_dataset_lineage'])))
        graph_raw, _ = await runtime.datasets.service.afile_bytes(keys.workspace_key, graph_checkpoint.finding_graph_file.path)
        graph_payload = json.loads(graph_raw)
        assert graph_payload['findings'][0]['factRefs'] == [result['factId']]
        assert graph_payload['claimSupport'][0]['supportStatus'] == 'supported'
        assert graph_payload['questionCoverage'][0]['status'] == 'partial'
        assert 'report_effective_profile' not in context.session_state
        server_tables, table_traces, fact_directory, fact_values = await runtime._build_server_tables(
            context, checkpoint=graph_checkpoint.model_copy(update={'deterministic_fact_files': fact_files}),
            outline=SimpleNamespace(sections=(SimpleNamespace(code='budget', analysis_ids=('analysis_001',)),)))
        assert len(server_tables) == len(table_traces) == 1
        assert table_traces[0].cells[0].fact_refs[0].fact_key == result['factId']
        assert fact_directory[result['factId']] == ('analysis_001', '/metricContext/calculations/0/results/0')
        assert Decimal(fact_values[result['factId']][0]) == Decimal(300)
        assert '预算额' in server_tables[0].markdown
        # 实际服务端清单读取PG登记依据，不使用会话Profile或模型提供的ID。
        from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
        from smart_reporting.reporting.delivery.draft_v1 import HeadingNumber
        from smart_reporting.reporting.workflow.runtime import publication as publication_module

        markdown_path = 'reports/basis-publication.md'
        await runtime.workspace_service.awrite_text(keys.workspace_key, markdown_path, '# 正式指标核对\n\n' + server_tables[0].markdown)
        markdown_identity = await runtime.workspace_service.ahash_file(keys.workspace_key, markdown_path)
        runtime.trace_registration_enabled = False
        monkeypatch.setattr(publication_module, '_frozen_outline', lambda _state:
            SimpleNamespace(sections=(SimpleNamespace(code='budget'),)))
        manifest = await runtime._build_and_write_artifact_manifest('reports/basis-publication.manifest.json',
            accepted_artifacts=[markdown_identity], markdown_path=markdown_path,
            lineage=tuple(DatasetLineage.model_validate(item) for item in context.session_state['report_dataset_lineage']),
            revision=1, task_key='basis-publication', section_numbers=('1',),
            heading_numbers=(HeadingNumber(level=2, number='1', title='预算核对', sectionCode='budget', anchor='report-section-budget'),),
            run_context=context)
        assert manifest.report_basis_id == execution.basis.id
        assert 'effectiveProfileHash' not in manifest.model_dump(by_alias=True)
        raw_manifest, _ = await runtime.workspace_service.afile_bytes(keys.workspace_key, 'reports/basis-publication.manifest.json')
        assert ReportArtifactManifest.model_validate_json(raw_manifest).report_basis_id == execution.basis.id
        from smart_reporting.reporting.models import ReportingError
        (registry.resolve(workflow_scope).root / paths[0]).write_bytes(b'value,observed_count,nonnull_count\n301,2,2\n')
        with pytest.raises(ReportingError, match='management_basis_snapshot_unavailable'):
            await runtime.generate_analysis_plan(SimpleNamespace(), context)
        context.session_state.clear()
        with pytest.raises(ReportingError, match='management_basis_snapshot_unavailable'):
            await runtime.calculate_report_metrics(SimpleNamespace(), context)
        assert len(queries) == 2
    await registry.aclose()


@pytest.mark.parametrize('invalid_filter', [False, True])
async def test_runtime_profiles_registered_basis_without_old_business_profile(basis_context, monkeypatch, invalid_filter):
    from types import SimpleNamespace

    import duckdb
    import sqlglot

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_source.models import (
        CatalogColumn,
        CatalogTable,
        QueryResult,
    )
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime, planning

    ctx = basis_context
    if invalid_filter:
        service = ctx['policy_service']
        current = await service.get(ctx['token'], ctx['scope'], 'monthly-budget')
        body = {key: value for key, value in current['draft']['document'].items()
            if key not in ('scopeId', 'revision')}
        body['filters'] = [{'fieldRef': 'warehouse.test.budget.amount', 'operator': 'eq', 'values': [None]}]
        await service.save_draft(ctx['token'], ctx['scope'], body, expected_version=1)
        await service.publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=2)
        await service.set_default(ctx['token'], ctx['scope'], 'budget_execution',
            policy_version={'policyId': 'monthly-budget', 'revision': 2}, expected_version=1)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = ReportBasisService(ctx['scopes'])
    runtime.report_build_identity = build_identity()
    runtime._scope = lambda context: {'database': ctx['scope'].database,
        'companyId': ctx['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    catalog = (CatalogTable('warehouse', 'test', 'budget', (
        CatalogColumn('amount', 'DECIMAL(18,2)', False), CatalogColumn('period', 'DATE', False),
        CatalogColumn('project_id', 'VARCHAR(20)', False))),)
    queries = []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE MACRO percentile_approx(value, fraction) AS quantile_cont(value, fraction)')
        connection.execute('CREATE TABLE test.budget(amount DECIMAL(18,2), period DATE, project_id VARCHAR)')
        connection.execute("INSERT INTO test.budget VALUES (100,'2026-11-01','A'),(200,'2026-11-30','B'),(999,'2026-12-01','A')")

        class Adapter:
            def __init__(self, config, *, allowed_tables):
                self.config, self.allowed_tables = config, allowed_tables

            async def catalog(self):
                return catalog

            async def query_bound(self, sql, parameters):
                queries.append(sql)
                cursor = connection.execute(sqlglot.transpile(sql, read='starrocks', write='duckdb')[0], parameters)
                return QueryResult(tuple(item[0] for item in cursor.description), cursor.fetchall(), 0)

            async def query(self, sql):
                return await self.query_bound(sql, {})

            async def aclose(self):
                pass

        monkeypatch.setattr(planning, 'StarRocksDataSourceAdapter', Adapter)
        context = SimpleNamespace(run_id='run-basis', session_state={})
        payload = {'reportGoal': '核对预算', 'scenario': 'budget_execution',
            'period': {'start': '2026-11-01', 'end': '2026-11-30'}, 'comparisonRoles': []}
        await runtime.confirm_source(SimpleNamespace(input=payload, previous_step_content=None), context)
        context.session_state['report_data_understanding'] = {'tables': [
            {'sourceId': 'warehouse', 'table': 'test.budget', 'periodColumn': 'period',
             'periodGranularity': 'date', 'role': '已登记预算期间'}]}
        result = await runtime.profile_source(SimpleNamespace(), context)
    assert 'report_effective_profile' not in context.session_state
    if invalid_filter:
        assert result.content['dataShapes'] == []
        assert [(item['code'], item['objectId'], item['impact']) for item in result.content['issues']] == [
            ('metric_filter_null_comparison', 'warehouse', 'unavailable')]
        assert context.session_state['report_data_shape_issues'] == result.content['issues']
        assert queries == []
        return
    shape = result.content['dataShapes'][0]['tables'][0]
    assert (shape['totalRowCount'], shape['periodRowCount'], shape['outsidePeriodRowCount']) == (3, 2, 1)
    amount = next(item for item in shape['columns'] if item['name'] == 'amount')
    assert str(amount['maximum']) in ('200.0', '200.00', '200')


async def test_exploration_adapter_uses_registered_policy_instead_of_session_filters(basis_context, monkeypatch):
    from types import SimpleNamespace

    import duckdb
    import sqlglot

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.data_source.materialization import CsvMaterializer
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    ctx = basis_context
    policies = ctx['policy_service']
    current = await policies.get(ctx['token'], ctx['scope'], 'monthly-budget')
    body = {key: value for key, value in current['draft']['document'].items()
        if key not in ('scopeId', 'revision')}
    body['filters'] = [{'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A']}]
    await policies.save_draft(ctx['token'], ctx['scope'], body, expected_version=1)
    await policies.publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=2)
    await policies.set_default(ctx['token'], ctx['scope'], 'budget_execution',
        policy_version={'policyId': 'monthly-budget', 'revision': 2}, expected_version=1)
    await register_basis(ctx)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = ctx['provider']
    runtime.report_basis_service = ReportBasisService(ctx['scopes'])
    runtime._scope = lambda context: {'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
        'userId': '7', 'callerThreadId': 'thread-basis'}
    context = SimpleNamespace(run_id='run-basis', session_state={'report_effective_profile': {'filters': []}})
    executed = []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(project_id VARCHAR, amount INTEGER)')
        connection.execute("INSERT INTO test.budget VALUES ('A',10),('A',20),('B',900)")

        class Adapter:
            allowed_tables = ('test.budget',)

            def __init__(self, config, **kwargs):
                self.config = config

            async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                executed.append((sql, parameters))
                cursor = connection.execute(sqlglot.transpile(sql, read='starrocks', write='duckdb')[0], parameters)
                writer = CsvMaterializer(tuple(item[0] for item in cursor.description), max_bytes=max_bytes)
                writer.append(tuple(cursor.fetchall()))
                return writer.finish()

            async def aclose(self):
                pass

        monkeypatch.setattr('smart_reporting.reporting.workflow.runtime.datasets.StarRocksDataSourceAdapter', Adapter)
        adapters = await runtime._policy_query_adapters(context)
        try:
            result = await adapters['warehouse'].materialize('SELECT SUM(amount) AS total FROM test.budget', max_bytes=4096)
            assert result.content.splitlines()[1] == b'30'
            assert len(executed) == 1 and list(executed[0][1].values()) == ['A']
            from smart_reporting.reporting.models import ReportingError
            with pytest.raises(ReportingError):
                await adapters['warehouse'].materialize('SELECT SUM(amount) FROM test.hidden', max_bytes=4096)
            assert len(executed) == 1
        finally:
            for adapter in adapters.values():
                await adapter.aclose()


@pytest.mark.parametrize('case', ['available', 'outside_catalog', 'outside_period'])
async def test_policy_adoption_preview_is_explicit_read_only_and_uses_original_catalog(basis_context, case):
    from sqlalchemy import func, select

    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import (
        audit_events,
        report_bases,
        report_basis_receipts,
    )
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload

    service = ReportBasisService(basis_context['scopes'])
    original = await service.register_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_summary=request_summary(basis_context['scope_id']),
        build_identity={'commit': 'a' * 40, 'sourceHash': 'b' * 64,
            'dependencyHash': 'c' * 64, 'compilerVersion': 'semantic-v1'})
    metrics = MetricService(basis_context['scopes'])
    body = metric_payload(kind='count', unit='count')
    body.pop('scopeId')
    body.pop('revision')
    if case == 'outside_catalog':
        body['fieldRef'] = 'warehouse.test.hidden.amount'
    await metrics.save_draft(basis_context['token'], basis_context['scope'], body, 1)
    await metrics.publish(basis_context['token'], basis_context['scope'], 'budget', expected_version=2)
    policies = basis_context['policy_service']
    current = await policies.get(basis_context['token'], basis_context['scope'], 'monthly-budget')
    changed = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    changed['metricVersions'] = [{'metricId': 'budget', 'revision': 2}]
    if case == 'outside_period':
        changed['validFrom'] = '2026-11-15'
    await policies.save_draft(basis_context['token'], basis_context['scope'], changed, expected_version=1)
    await policies.publish(basis_context['token'], basis_context['scope'], 'monthly-budget', expected_version=2)
    async def counts():
        async with basis_context['repository'].transaction() as connection:
            return tuple([await connection.scalar(select(func.count()).select_from(table))
                for table in (report_bases, report_basis_receipts, audit_events)])
    before = await counts()
    choices = await service.policy_adoption_options('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', limit=1)
    assert choices['parentBasisId'] == original.id
    assert choices['items'] == [{'policyVersion': {'policyId': 'monthly-budget', 'revision': 2},
        'name': changed['name']}]
    assert choices['nextCursor'] is None
    preview = await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    assert preview.parent_basis_id == original.id
    assert preview.target_policy_version.revision == 2
    assert preview.metric_versions_added[0].revision == 2
    assert preview.metric_versions_removed[0].revision == 1
    assert preview.requires_question_confirmation is True
    assert preview.questions == original.request_summary.questions
    assert [(item.metric_version.metric_id, item.metric_version.revision, item.name, item.unit)
        for item in preview.metric_options] == [('budget', 2, body['name'], body['unit'])]
    assert preview.calculation_status == 'not_recalculated'
    assert preview.source_versions == original.source_versions and preview.catalog_refs == original.catalog_refs
    assert ('metric_field_denied' in {issue.code for issue in preview.issues}) == (case == 'outside_catalog')
    assert ('policy_period_not_applicable' in {issue.code for issue in preview.issues}) == (case == 'outside_period')
    assert preview.changed_fields == (('metric_versions', 'valid_from') if case == 'outside_period' else ('metric_versions',))
    assert preview.changes[0].field == 'metric_versions'
    assert preview.changes[0].before == 'budget v1'
    assert preview.changes[0].after == 'budget v2'
    assert await counts() == before
    assert await service.load_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis') == original
    # 最新发布不是隐式目标；显式读回仍是同一个不可变版本及预检摘要。
    repeated = await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    assert repeated == preview
    assert repeated.digest() == preview.digest() and len(preview.digest()) == 64
    from smart_reporting.management.models import ManagementError
    for target, expected_code in (({'policyId': 'monthly-budget', 'revision': 1}, 'management_policy_unchanged'),
            ({'policyId': 'monthly-budget', 'revision': 99}, 'management_policy_not_found')):
        with pytest.raises(ManagementError) as caught:
            await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
                thread_id='thread-basis', policy_version=target)
        assert caught.value.code == expected_code
    with pytest.raises(ManagementError) as caught:
        await service.preview_policy_adoption('run-basis', basis_context['other_scope'], user_id='7',
            thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    assert caught.value.status == 403
    with pytest.raises(ManagementError) as caught:
        await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='forged-user',
            thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    assert caught.value.code == 'management_run_identity_conflict'
    await policies.retire(basis_context['token'], basis_context['scope'], 'monthly-budget', 2,
        reason='测试显式退役新候选，不改变原报告')
    assert (await service.policy_adoption_options('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis'))['items'] == []
    with pytest.raises(ManagementError):
        await service.policy_adoption_options('run-basis', basis_context['other_scope'], user_id='7',
            thread_id='thread-basis')
    with pytest.raises(ManagementError):
        await service.policy_adoption_options('run-basis', basis_context['scope'], user_id='forged-user',
            thread_id='thread-basis')
    with pytest.raises(ManagementError) as caught:
        await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
            thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    assert caught.value.code == 'management_semantic_asset_retired'
    assert await service.load_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis') == original


async def test_policy_adoption_registration_is_atomic_idempotent_and_keeps_parent(basis_context, monkeypatch):
    import asyncio

    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import (
        report_bases,
        report_basis_receipts,
        runtime_snapshots,
    )

    service = ReportBasisService(basis_context['scopes'])
    build = {'commit': 'a' * 40, 'sourceHash': 'b' * 64, 'dependencyHash': 'c' * 64,
        'compilerVersion': 'semantic-v1'}
    original = await service.register_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_summary=request_summary(basis_context['scope_id']), build_identity=build)
    policies = basis_context['policy_service']
    current = await policies.get(basis_context['token'], basis_context['scope'], 'monthly-budget')
    changed = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    changed['name'] = '明确采用的新口径'
    await policies.save_draft(basis_context['token'], basis_context['scope'], changed, expected_version=1)
    await policies.publish(basis_context['token'], basis_context['scope'], 'monthly-budget', expected_version=2)
    preview = await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', policy_version={'policyId': 'monthly-budget', 'revision': 2})
    confirmation = {'requestId': 'adopt-confirmed', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
        'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
            'metricVersion': {'metricId': 'budget', 'revision': 1}, 'reason': '明确保留本问题的预算额指标，执行率仍缺实际额。'}]}
    async def counts():
        async with basis_context['repository'].transaction() as connection:
            return tuple([await connection.scalar(select(func.count()).select_from(table))
                for table in (report_bases, report_basis_receipts, runtime_snapshots)])
    before = await counts()
    audit = service._audit
    async def fail_audit(*args, **kwargs):
        raise OSError('adoption audit write failed')
    monkeypatch.setattr(service, '_audit', fail_audit)
    with pytest.raises(OSError, match='adoption audit'):
        await service.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
            thread_id='thread-basis', confirmation=confirmation, build_identity=build)
    assert await counts() == before
    monkeypatch.setattr(service, '_audit', audit)
    receipt, concurrent = await asyncio.gather(*(service.register_policy_adoption('run-basis', basis_context['scope'],
        user_id='7', thread_id='thread-basis', confirmation=confirmation, build_identity=build) for _ in range(2)))
    assert concurrent == receipt
    assert receipt.parent_basis_id == original.id and receipt.parent_run_id == original.run_id
    adopted = await service.load_report_basis(receipt.target_run_id, basis_context['scope'], user_id='7',
        thread_id='thread-basis')
    assert adopted.id == receipt.basis_id and adopted.run_id != original.run_id
    assert adopted.policy_version.revision == 2
    assert adopted.request_summary == original.request_summary
    assert adopted.source_versions == original.source_versions and adopted.catalog_refs == original.catalog_refs
    assert adopted.background_release_id == original.background_release_id
    assert receipt.selections[0].selected.metric_id == 'budget'
    assert receipt.selections[0].source == 'explicit'
    from pydantic import ValidationError
    for changed_field in ({'parentBasisId': 'foreign-basis'}, {'targetRunId': original.run_id},
            {'confirmation': {**confirmation, 'previewHash': '0' * 64}}, {'selections': []}):
        with pytest.raises(ValidationError):
            type(receipt).model_validate({**receipt.model_dump(mode='json', by_alias=True), **changed_field})
    assert await service.load_basis_receipts(receipt.target_run_id, basis_context['scope'], user_id='7',
        thread_id='thread-basis', report_revision='policy-adoption-registration') == (receipt,)
    # 提交响应丢失后重建服务，按同一请求恢复完全一致的依据/确认回执。
    rebuilt = ReportBasisService(basis_context['scopes'])
    again = await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', confirmation=confirmation, build_identity=build)
    assert again == receipt
    assert await rebuilt.read_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_id='adopt-confirmed') == receipt
    assert await rebuilt.read_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_id='not-submitted') is None
    assert await counts() == tuple(value + 1 for value in before)
    assert await rebuilt.load_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis') == original
    changed_confirmation = {**confirmation, 'previewHash': '0' * 64}
    with pytest.raises(ManagementError) as caught:
        await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
            thread_id='thread-basis', confirmation=changed_confirmation, build_identity=build)
    assert caught.value.code == 'management_adoption_conflict'
    new_request = {**changed_confirmation, 'requestId': 'stale-preview'}
    with pytest.raises(ManagementError) as caught:
        await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
            thread_id='thread-basis', confirmation=new_request, build_identity=build)
    assert caught.value.code == 'management_adoption_preview_changed'
    assert await counts() == tuple(value + 1 for value in before)
    for selected_scope, selected_user in ((basis_context['other_scope'], '7'), (basis_context['scope'], 'forged-user')):
        with pytest.raises(ManagementError) as caught:
            await rebuilt.register_policy_adoption('run-basis', selected_scope, user_id=selected_user,
                thread_id='thread-basis', confirmation=confirmation, build_identity=build)
        assert caught.value.status == 403
        with pytest.raises(ManagementError) as caught:
            await rebuilt.read_policy_adoption('run-basis', selected_scope, user_id=selected_user,
                thread_id='thread-basis', request_id='adopt-confirmed')
        assert caught.value.status == 403
    for index, choices in enumerate(([], confirmation['questionChoices'] * 2,
            [{'questionId': 'unknown-question', 'metricVersion': None, 'reason': '没有依据'}],
            [{'questionId': 'q-rate', 'metricVersion': {'metricId': 'budget', 'revision': 99}, 'reason': '伪造版本'}])):
        with pytest.raises(ManagementError) as caught:
            await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
                thread_id='thread-basis', confirmation={**confirmation, 'requestId': f'invalid-choices-{index}',
                    'questionChoices': choices}, build_identity=build)
        assert caught.value.code in {'management_adoption_invalid', 'management_adoption_questions_invalid'}
    assert await counts() == tuple(value + 1 for value in before)
    unresolved = await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', confirmation={**confirmation, 'requestId': 'explicitly-unavailable',
            'questionChoices': [{'questionId': 'q-rate', 'metricVersion': None, 'reason': '执行率仍缺实际额，不冒充已回答。'}]},
        build_identity=build)
    assert unresolved.selections[0].status == 'unavailable' and unresolved.selections[0].selected is None
    assert await counts() == tuple(value + 2 for value in before)
    await policies.retire(basis_context['token'], basis_context['scope'], 'monthly-budget', 2,
        reason='测试新请求停用，已登记新依据继续固定版本')
    assert await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', confirmation=confirmation, build_identity=build) == receipt
    with pytest.raises(ManagementError) as caught:
        await rebuilt.register_policy_adoption('run-basis', basis_context['scope'], user_id='7',
            thread_id='thread-basis', confirmation={**confirmation, 'requestId': 'retired-new-request'}, build_identity=build)
    assert caught.value.code == 'management_semantic_asset_retired'


async def test_policy_adoption_options_paginate_latest_published_without_draft_or_retirement_fallback(basis_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService

    service = ReportBasisService(basis_context['scopes'])
    await service.register_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_summary=request_summary(basis_context['scope_id']),
        build_identity=build_identity())
    policies = basis_context['policy_service']
    current = await policies.get(basis_context['token'], basis_context['scope'], 'monthly-budget')
    template = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    for policy_id in ('alternate-a', 'alternate-b', 'other-scenario', 'draft-only'):
        document = {**template, 'id': policy_id, 'name': policy_id,
            'scenario': 'other' if policy_id == 'other-scenario' else template['scenario']}
        await policies.save_draft(basis_context['token'], basis_context['scope'], document, expected_version=0)
        if policy_id != 'draft-only':
            await policies.publish(basis_context['token'], basis_context['scope'], policy_id, expected_version=1)
    await policies.save_draft(basis_context['token'], basis_context['scope'],
        {**template, 'id': 'alternate-a', 'name': '最新发布名称',
            'filters': [{'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A']}]},
        expected_version=1)
    await policies.publish(basis_context['token'], basis_context['scope'], 'alternate-a', expected_version=2)
    options = dict(user_id='7', thread_id='thread-basis', limit=1)
    first = await service.policy_adoption_options('run-basis', basis_context['scope'], **options)
    assert first['items'] == [{'policyVersion': {'policyId': 'alternate-a', 'revision': 2}, 'name': '最新发布名称'}]
    assert first['nextCursor'] == 'alternate-a'
    preview = await service.preview_policy_adoption('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', policy_version=first['items'][0]['policyVersion'])
    scope_change = next(change for change in preview.changes if change.field == 'filters')
    assert scope_change.before == '无附加过滤条件'
    assert scope_change.after == 'warehouse.test.budget.project_id 等于 "A"'
    second = await service.policy_adoption_options('run-basis', basis_context['scope'], **options, after=first['nextCursor'])
    assert second['items'] == [{'policyVersion': {'policyId': 'alternate-b', 'revision': 1}, 'name': 'alternate-b'}]
    assert second['nextCursor'] is None
    await policies.retire(basis_context['token'], basis_context['scope'], 'alternate-a', 2, reason='最新版本明确退役')
    remaining = await service.policy_adoption_options('run-basis', basis_context['scope'], **options)
    assert remaining['items'] == second['items'] and remaining['nextCursor'] is None
    for limit in (0, 101, True):
        with pytest.raises(ManagementError) as caught:
            await service.policy_adoption_options('run-basis', basis_context['scope'], user_id='7',
                thread_id='thread-basis', limit=limit)
        assert caught.value.status == 422

async def test_public_request_pins_explicit_knowledge_cutoff_and_rejects_drift(basis_context):
    from datetime import timedelta

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService

    ctx = basis_context
    service = ReportBasisService(ctx["scopes"])
    cutoff = ctx["scopes"].auth.clock() - timedelta(days=1)
    request = {
        "reportGoal": "按当时可知材料核对预算",
        "scenario": "budget_execution",
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "comparisonRoles": [],
        "knowledgeAsOf": cutoff.isoformat(),
    }
    basis = await service.register_request_basis(
        "run-basis",
        ctx["scope"],
        user_id="7",
        thread_id="thread-basis",
        request=request,
        build_identity=build_identity(),
    )
    assert basis.knowledge_as_of == cutoff
    assert (
        await service.register_request_basis(
            "run-basis",
            ctx["scope"],
            user_id="7",
            thread_id="thread-basis",
            request=request,
            build_identity=build_identity(),
        )
        == basis
    )
    with pytest.raises(ManagementError) as conflict:
        await service.register_request_basis(
            "run-basis",
            ctx["scope"],
            user_id="7",
            thread_id="thread-basis",
            request={**request, "knowledgeAsOf": (cutoff - timedelta(days=1)).isoformat()},
            build_identity=build_identity(),
        )
    assert conflict.value.status == 409


async def test_public_future_knowledge_cutoff_is_rejected_without_partial_basis(basis_context):
    from datetime import timedelta

    from sqlalchemy import func, select

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import report_bases

    ctx = basis_context
    service = ReportBasisService(ctx["scopes"])
    request = {
        "reportGoal": "核对预算",
        "scenario": "budget_execution",
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "comparisonRoles": [],
        "knowledgeAsOf": (ctx["scopes"].auth.clock() + timedelta(seconds=1)).isoformat(),
    }
    with pytest.raises(ManagementError) as error:
        await service.register_request_basis(
            "run-basis",
            ctx["scope"],
            user_id="7",
            thread_id="thread-basis",
            request=request,
            build_identity=build_identity(),
        )
    assert error.value.code == "management_knowledge_time_invalid" and error.value.status == 422
    async with ctx["repository"].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_bases)) == 0


async def test_new_policy_adoption_preserves_explicit_historical_knowledge_time(basis_context):
    from datetime import timedelta

    from smart_reporting.management.report_bases import ReportBasisService

    ctx = basis_context
    service = ReportBasisService(ctx["scopes"])
    cutoff = ctx["scopes"].auth.clock() - timedelta(days=1)
    request = {
        "reportGoal": "按当时可知材料核对预算",
        "scenario": "budget_execution",
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "comparisonRoles": [],
        "knowledgeAsOf": cutoff.isoformat(),
        "questions": [{"id": "q-rate", "text": "预算是多少？"}],
    }
    original = await service.register_request_basis(
        "run-basis",
        ctx["scope"],
        user_id="7",
        thread_id="thread-basis",
        request=request,
        build_identity=build_identity(),
    )
    policies = ctx["policy_service"]
    current = await policies.get(ctx["token"], ctx["scope"], "monthly-budget")
    definition = {
        key: value
        for key, value in current["draft"]["document"].items()
        if key not in ("scopeId", "revision")
    }
    await policies.save_draft(
        ctx["token"], ctx["scope"], {**definition, "name": "明确新口径"}, expected_version=1
    )
    await policies.publish(ctx["token"], ctx["scope"], "monthly-budget", expected_version=2)
    preview = await service.preview_policy_adoption(
        "run-basis",
        ctx["scope"],
        user_id="7",
        thread_id="thread-basis",
        policy_version={"policyId": "monthly-budget", "revision": 2},
    )
    receipt = await service.register_policy_adoption(
        "run-basis",
        ctx["scope"],
        user_id="7",
        thread_id="thread-basis",
        confirmation={
            "requestId": "adopt-historical",
            "previewHash": preview.digest(),
            "targetPolicyVersion": {"policyId": "monthly-budget", "revision": 2},
            "questionChoices": [
                {
                    "questionId": "q-rate",
                    "metricVersion": {"metricId": "budget", "revision": 1},
                    "reason": "明确预算指标",
                }
            ],
        },
        build_identity=build_identity(),
    )
    adopted = await service.load_report_basis(
        receipt.target_run_id, ctx["scope"], user_id="7", thread_id="thread-basis"
    )
    assert adopted.knowledge_as_of == original.knowledge_as_of == cutoff
    assert (
        adopted.request_summary == original.request_summary and adopted.policy_version.revision == 2
    )
