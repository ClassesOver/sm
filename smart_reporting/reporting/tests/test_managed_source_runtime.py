from __future__ import annotations

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)
from smart_reporting.tests.test_management_runtime_persistence import (
    pinned_context as pinned_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def managed_report(pinned_context, monkeypatch, tmp_path):
    from agno.run import RunContext

    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
    )
    from smart_reporting.tests.management_fixtures import physical_catalog

    provider, *_ = pinned_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = provider
    runtime.registry = None
    runtime.profiles = None
    runtime.workspace_registry = ReportingWorkspaceRegistry(
        tmp_path, secret="managed-runtime-test-secret-32-bytes"
    )
    runtime.workspace_service = ReportingWorkspaceRouter(runtime.workspace_registry)
    from smart_reporting.reporting.data_sources import ReportDatasetStore

    runtime.datasets = ReportDatasetStore(runtime.workspace_service)

    class ReportTools:
        async def report_prepare_dataset(self, dataset_ids, *, run_context):
            return {"jobId": "managed-job"}

        async def bind_page_layout(self, *args, **kwargs):
            return None

    runtime.report_tools = ReportTools()
    with bind_verified_reporting_identity(
        VerifiedReportingIdentity("warehouse", "100", "7", "thread-1", "cli")
    ):
        state = runtime.prepare_run(
            run_id="run-1",
            session_id="thread-1",
            user_id="7",
            dependencies={
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": "warehouse", "companyId": "100"}
            },
        )
    context = RunContext(run_id="run-1", session_id="thread-1", user_id="7", session_state=state)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    request = {
        "reportGoal": "核对版本",
        "reportType": "comprehensive",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
    }
    return runtime, context, request


@pytest.fixture
async def scoped_report(managed_report, pinned_context, monkeypatch):
    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.profiles import ProfileService
    from smart_reporting.reporting.contract import (
        ModelColumn,
        ModelTermsResponse,
        RawDdlModel,
        schema_hash,
    )
    from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import business_metadata

    _, service, scopes, _, token, scope = pinned_context
    metadata = business_metadata()
    table = metadata.tables[0].model_copy(
        update={
            "columns": (
                *metadata.tables[0].columns,
                ModelColumn(name="company_id", dataType="VARCHAR(32)", nullable=False),
                ModelColumn(name="report_year", dataType="INT", nullable=False),
            )
        }
    )
    metadata = ModelTermsResponse.model_validate(
        metadata.model_dump(mode="json", by_alias=True)
        | {
            "tables": [table.model_dump(mode="json", by_alias=True)],
            "schemaHash": schema_hash((table,)),
            "ddlModels": [
                RawDdlModel(
                    id=1,
                    modelName="订单",
                    ddl="CREATE TABLE warehouse.orders (amount DECIMAL(18,2) NOT NULL, company_id VARCHAR(32) NOT NULL, report_year INT NOT NULL)",
                ).model_dump(mode="json", by_alias=True)
            ],
            "measureSemantics": [
                metadata.measure_semantics[0].model_dump(mode="json", by_alias=True)
                | {"additiveAcross": ["report_year"]}
            ],
        }
    )
    catalog = (
        CatalogTable(
            "operations",
            "warehouse",
            "orders",
            tuple(
                CatalogColumn(c.name, c.data_type, c.nullable, c.description) for c in table.columns
            ),
        ),
    )
    catalogs = CatalogService(scopes)
    synced = await catalogs.sync(token, scope, "operations", 1, catalog, metadata=metadata)
    await catalogs.publish(token, scope, "operations", synced["revision"])
    profiles = ProfileService(scopes)
    draft = await profiles.save_draft(
        token,
        scope,
        {
            "profileId": "base",
            "revision": "r2",
            "dimensions": [],
            "scopeFilters": [
                {
                    "code": "company",
                    "fieldRefs": ["operations.warehouse.orders.company_id"],
                    "value": "100",
                    "requiredForAllTables": True,
                }
            ],
        },
        1,
    )
    await profiles.publish(token, scope, "base", draft["version"])
    source = await service.save_draft(
        token,
        scope,
        "operations",
        SourceDraftInput.model_validate(
            {
                "name": "组织限定源",
                "database": "warehouse",
                "dsn": "starrocks://reporter:test-secret@localhost:9030/warehouse",
                "reportingProfileVersionId": "base:2",
                "metadataVersionId": f"operations:{synced['revision']}",
            }
        ),
        1,
    )
    await service.publish(token, scope, "operations", source["version"])
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: catalog)
    return managed_report


@pytest.mark.parametrize("change", ["profile", "semantic", "sql"])
async def test_recovery_cannot_remove_published_company_filter(scoped_report, monkeypatch, change):
    from copy import deepcopy

    from agno.workflow.types import StepInput

    from smart_reporting.reporting.data_source.models import MaterializedQueryResult
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.profile.models import effective_profile_hash
    from smart_reporting.reporting.workflow.query_pipeline import ApprovedQuery, normalized_sql_hash

    runtime, context, request = scoped_report
    await runtime.confirm_source(StepInput(input=request), context)
    state = context.session_state
    state["report_data_requirements"] = [
        {
            "requirementId": "income",
            "sourceId": "operations",
            "dimensionColumns": [],
            "grainColumns": [],
            "comparisonRoles": [],
            "tables": [
                {
                    "table": "warehouse.orders",
                    "periodColumn": "report_year",
                    "periodGranularity": "year",
                    "measureColumns": ["amount"],
                }
            ],
        }
    ]
    sql = "SELECT SUM(amount) AS amount FROM warehouse.orders WHERE report_year = 2025 AND company_id = '100'"
    window_id = (
        runtime._envelope(context).period_windows(granularity="year").windows[0].query_window_id
    )

    def approve(text):
        return [
            ApprovedQuery(
                requirementId="income",
                sourceId="operations",
                sql=text,
                sqlHash=normalized_sql_hash(text),
                queryWindowId=window_id,
            ).model_dump(mode="json", by_alias=True)
        ]

    state["report_approved_queries"] = approve(sql)
    original = deepcopy(state)
    if change == "profile":
        profile = state["report_effective_profile"]
        profile["scopeFilters"] = []
        profile["effectiveProfileHash"] = effective_profile_hash(
            {key: value for key, value in profile.items() if key != "effectiveProfileHash"}
        )
    elif change == "semantic":
        state["report_schema_snapshots"][0]["measureSemantics"][0]["exclusiveScope"] = {}
    else:
        state["report_approved_queries"] = approve(sql.replace(" AND company_id = '100'", ""))
    executed = []

    def materialize(adapter, text, *, max_bytes=None):
        executed.append(text)
        return MaterializedQueryResult(b"amount\n100\n", 1)

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_materialize", materialize)
    with pytest.raises(ReportingError):
        await runtime.materialize_datasets(StepInput(), context)
    assert executed == []
    context.session_state = original
    result = await runtime.materialize_datasets(StepInput(), context)
    assert result.content["datasets"][0]["rowCount"] == 1
    assert executed == [sql]


@pytest.mark.parametrize(
    "attribute,current",
    [("data_type", "VARCHAR(32)"), ("nullable", True), ("description", "实时字段说明")],
)
async def test_live_catalog_drift_keeps_published_metadata_and_reports_reason(
    managed_report, monkeypatch, attribute, current
):
    from dataclasses import replace

    from agno.workflow.types import StepInput

    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import physical_catalog

    runtime, context, request = managed_report
    await runtime.confirm_source(StepInput(input=request), context)
    original = context.session_state["report_schema_snapshots"][0]
    table = physical_catalog()[0]
    changed = replace(table, columns=(replace(table.columns[0], **{attribute: current}),))
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: (changed,))
    result = await runtime.confirm_source(StepInput(input=request), context)
    actual = context.session_state["report_schema_snapshots"][0]
    assert actual == original
    assert actual["tables"][0]["columns"][0] == {
        "name": "amount",
        "dataType": "DECIMAL(18,2)",
        "nullable": False,
        "description": "",
    }
    assert result.content["configurationWarnings"][0]["code"] == "report_catalog_drift"
    assert "warehouse.orders.amount" in result.content["configurationWarnings"][0]["message"]
    assert (
        context.session_state["report_configuration_warnings"]
        == result.content["configurationWarnings"]
    )


@pytest.mark.parametrize("missing", ["table", "column"])
async def test_missing_published_structure_fails_before_data_queries(
    managed_report, monkeypatch, missing
):
    from dataclasses import replace

    from agno.workflow.types import StepInput

    from smart_reporting.reporting.data_source.models import CatalogColumn
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import physical_catalog

    runtime, context, request = managed_report
    catalog = (
        ()
        if missing == "table"
        else (replace(physical_catalog()[0], columns=(CatalogColumn("other", "INT", True),)),)
    )
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: catalog)
    with pytest.raises(ReportingError, match="report_catalog_drift"):
        await runtime.confirm_source(StepInput(input=request), context)


@pytest.mark.parametrize("change", ["table", "column", "profile", "semantic"])
async def test_edited_session_execution_state_cannot_expand_published_scope(
    managed_report, tmp_path, change
):
    from copy import deepcopy

    import httpx
    from agno.db.sqlite import SqliteDb
    from agno.os.routers.session.session import get_session_router
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import StepInput
    from fastapi import FastAPI

    runtime, context, request = managed_report
    await runtime.confirm_source(StepInput(input=request), context)
    original = deepcopy(context.session_state)
    db = SqliteDb(id="sessions", db_file=str(tmp_path / "sessions.db"))
    db.upsert_session(
        WorkflowSession(
            session_id="thread-1", user_id="7", session_data={"session_state": original}
        )
    )
    app = FastAPI()
    app.include_router(get_session_router({"sessions": [db]}))
    changed = deepcopy(original)
    snapshot = changed["report_schema_snapshots"][0]
    if change == "table":
        snapshot["tables"][0]["name"] = "payroll"
        snapshot["terms"] = []
        snapshot["measureSemantics"] = []
    elif change == "column":
        snapshot["tables"][0]["columns"].append(
            {"name": "salary", "dataType": "DECIMAL(18,2)", "nullable": False}
        )
    elif change == "profile":
        from smart_reporting.reporting.profile.models import effective_profile_hash

        profile = changed["report_effective_profile"]
        profile["revision"] = "forged-profile"
        profile["effectiveProfileHash"] = effective_profile_hash(
            {key: value for key, value in profile.items() if key != "effectiveProfileHash"}
        )
    else:
        snapshot["measureSemantics"][0]["aggregation"] = "max"
    # references 保持真实；通过项目实际使用的 Agno session PATCH 写入并读回。
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/sessions/thread-1?type=workflow&user_id=7", json={"session_state": changed}
        )
    assert response.status_code == 200, response.text
    restored = db.get_session("thread-1", session_type="workflow", user_id="7")
    context.session_state = restored.session_data["session_state"]
    assert (
        context.session_state["report_managed_configuration"]
        == original["report_managed_configuration"]
    )
    with pytest.raises(ReportingError, match="management_runtime_execution_mismatch"):
        await runtime._sources(context)
    # 原合法状态在新 provider 加载后仍可用，不能以禁用恢复代替权限核对。
    context.session_state = original
    assert (await runtime._sources(context))[0].id == "operations"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(salary) FROM warehouse.orders WHERE amount = 2025",
        "SELECT SUM(amount) FROM warehouse.payroll WHERE amount = 2025",
        "SELECT SUM(amount), * FROM warehouse.orders WHERE amount = 2025",
        "SELECT SUM(amount), orders.* FROM warehouse.orders WHERE amount = 2025",
    ],
)
async def test_edited_approved_sql_cannot_query_unpublished_columns_or_tables(
    managed_report, monkeypatch, sql
):
    from agno.workflow.types import StepInput

    from smart_reporting.reporting.data_source.models import MaterializedQueryResult
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.workflow.query_pipeline import ApprovedQuery, normalized_sql_hash

    runtime, context, request = managed_report
    await runtime.confirm_source(StepInput(input=request), context)
    context.session_state["report_data_requirements"] = [
        {
            "requirementId": "income",
            "sourceId": "operations",
            "dimensionColumns": [],
            "grainColumns": [],
            "comparisonRoles": [],
            "tables": [
                {
                    "table": "warehouse.orders",
                    "periodColumn": "amount",
                    "periodGranularity": "year",
                    "measureColumns": ["amount"],
                }
            ],
        }
    ]
    window_id = (
        runtime._envelope(context).period_windows(granularity="year").windows[0].query_window_id
    )
    context.session_state["report_approved_queries"] = [
        ApprovedQuery(
            requirementId="income",
            sourceId="operations",
            sql=sql,
            sqlHash=normalized_sql_hash(sql),
            queryWindowId=window_id,
        ).model_dump(mode="json", by_alias=True)
    ]
    executed = []

    def materialize(adapter, sql, *, max_bytes=None):
        executed.append(sql)
        return MaterializedQueryResult(b"amount\n100\n", 1)

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_materialize", materialize)
    with pytest.raises(ReportingError):
        await runtime.materialize_datasets(StepInput(), context)
    assert executed == []


@pytest.mark.parametrize("tamper", [False, True])
async def test_native_workflow_pause_session_patch_and_resume_keeps_scope(
    scoped_report, monkeypatch, tmp_path, tamper
):
    from copy import deepcopy

    import httpx
    from agno.db.sqlite import SqliteDb
    from agno.os.routers.session.session import get_session_router
    from agno.run import RunStatus
    from agno.workflow import Step
    from agno.workflow.types import HumanReview, OnError, StepOutput
    from fastapi import FastAPI

    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.reporting.data_source.models import MaterializedQueryResult
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.tests.test_reporting_workflow_lifecycle import Repository
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
    )
    from smart_reporting.reporting.workflow.managed import ManagedReportingWorkflow
    from smart_reporting.reporting.workflow.query_pipeline import ApprovedQuery, normalized_sql_hash

    runtime, _, request = scoped_report
    runtime.state_repository = Repository()

    async def cleanup(*args):
        pass

    runtime.cleanup_terminal = cleanup
    db = SqliteDb(id="native", db_file=str(tmp_path / "native.db"))
    executed = []
    sql = "SELECT SUM(amount) AS amount FROM warehouse.orders WHERE report_year = 2025 AND company_id = '100'"

    def materialize(adapter, text, *, max_bytes=None):
        executed.append(text)
        return MaterializedQueryResult(b"amount\n100\n", 1)

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_materialize", materialize)

    async def confirm(step_input, run_context):
        await runtime.confirm_source(step_input, run_context)
        run_context.session_state["report_data_requirements"] = [
            {
                "requirementId": "income",
                "sourceId": "operations",
                "dimensionColumns": [],
                "grainColumns": [],
                "comparisonRoles": [],
                "tables": [
                    {
                        "table": "warehouse.orders",
                        "periodColumn": "report_year",
                        "periodGranularity": "year",
                        "measureColumns": ["amount"],
                    }
                ],
            }
        ]
        window_id = (
            runtime._envelope(run_context)
            .period_windows(granularity="year")
            .windows[0]
            .query_window_id
        )
        run_context.session_state["report_approved_queries"] = [
            ApprovedQuery(
                requirementId="income",
                sourceId="operations",
                sql=sql,
                sqlHash=normalized_sql_hash(sql),
                queryWindowId=window_id,
            ).model_dump(mode="json", by_alias=True)
        ]
        return StepOutput(content="确认取数")

    def workflow():
        return ManagedReportingWorkflow(
            id="enterprise-reporting-workflow-v1",
            db=db,
            lifecycle=runtime,
            overwrite_db_session_state=True,
            telemetry=False,
            steps=[
                Step(
                    name="confirm-source",
                    executor=confirm,
                    human_review=HumanReview(requires_output_review=True),
                ),
                Step(
                    name="materialize",
                    executor=runtime.materialize_datasets,
                    max_retries=0,
                    human_review=HumanReview(on_error=OnError.fail),
                ),
            ],
        )

    identity = VerifiedReportingIdentity("warehouse", "100", "7", "thread-1", "cli")
    dependencies = {REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": "warehouse", "companyId": "100"}}
    with bind_verified_reporting_identity(identity):
        output = await workflow().arun(
            request,
            run_id="native-run",
            session_id="thread-1",
            user_id="7",
            dependencies=dependencies,
            stream=False,
        )
    assert output.status is RunStatus.paused
    assert executed == []
    stored = db.get_session("thread-1", session_type="workflow", user_id="7")
    state = deepcopy(stored.session_data["session_state"])
    if tamper:
        state["report_schema_snapshots"][0]["tables"][0]["name"] = "payroll"
        state["report_schema_snapshots"][0]["terms"] = []
        state["report_schema_snapshots"][0]["measureSemantics"] = []
    app = FastAPI()
    app.include_router(get_session_router({"native": [db]}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/sessions/thread-1?type=workflow&user_id=7", json={"session_state": state}
        )
    assert response.status_code == 200, response.text
    # 重建 Workflow/provider，排除沿用内存会话掩盖 PATCH 或重启问题。
    provider = runtime.configuration_provider
    runtime.configuration_provider = ManagedConfigurationProvider(
        provider.scope_service, provider.vault
    )
    requirements = output.step_requirements
    requirements[-1].confirm()
    with bind_verified_reporting_identity(identity):
        if tamper:
            with pytest.raises(ReportingError, match="management_runtime_execution_mismatch"):
                await workflow().acontinue_run(
                    run_id="native-run",
                    session_id="thread-1",
                    step_requirements=requirements,
                    dependencies=dependencies,
                    stream=False,
                )
            assert executed == []
        else:
            result = await workflow().acontinue_run(
                run_id="native-run",
                session_id="thread-1",
                step_requirements=requirements,
                dependencies=dependencies,
                stream=False,
            )
            assert result.status is RunStatus.completed
            assert result.content["datasets"][0]["rowCount"] == 1
            assert executed == [sql]


async def test_edited_profile_plan_is_rejected_before_catalog_io(managed_report, monkeypatch):
    from agno.workflow.types import StepInput

    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter

    runtime, context, request = managed_report
    await runtime.confirm_source(StepInput(input=request), context)
    context.session_state["report_data_understanding"] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "warehouse.payroll",
                "role": "画像",
                "periodColumn": "amount",
                "periodGranularity": "year",
            }
        ]
    }
    calls = []

    def catalog(adapter):
        calls.append(adapter.allowed_tables)
        return ()

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", catalog)
    with pytest.raises(ReportingError, match="report_data_understanding_invalid"):
        await runtime.profile_source(StepInput(), context)
    assert calls == []


@pytest.mark.parametrize(
    "dependency",
    [
        {"database": "warehouse", "companyId": "100", "verified": True},
        {},
    ],
)
async def test_database_report_rejects_unverified_scope_even_with_registered_provider(
    pinned_context, dependency
):
    provider, *_ = pinned_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = provider
    with pytest.raises(ReportingError, match="report_verified_identity_required"):
        runtime.prepare_run(
            run_id="forged",
            session_id="thread-1",
            user_id="7",
            dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: dependency},
        )


async def test_trusted_report_registers_run_and_resume_checks_current_identity(pinned_context):
    from smart_reporting.reporting.tests.test_reporting_workflow_lifecycle import Repository
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
    )

    provider, *_ = pinned_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = provider
    runtime.state_repository = Repository()
    identity = VerifiedReportingIdentity("warehouse", "100", "7", "thread-1", "http-capability")
    with bind_verified_reporting_identity(identity):
        state = runtime.prepare_run(
            run_id="trusted",
            session_id="thread-1",
            user_id="7",
            dependencies={
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": "warehouse", "companyId": "100"},
            },
        )
        await runtime.start_run("trusted", state)
        frozen = await provider.freeze("trusted", identity_to_scope(identity))
        assert frozen.source_versions == {"operations": 1}
        await runtime.state_repository.update_run_status("trusted", status="paused")
        await runtime.assert_resumable("trusted")
    with bind_verified_reporting_identity(
        VerifiedReportingIdentity("warehouse", "100", "8", "thread-1", "http-capability")
    ):
        with pytest.raises(ReportingError, match="report_workflow_scope_mismatch"):
            await runtime.assert_resumable("trusted")


def identity_to_scope(identity):
    from smart_reporting.management.models import ManagementScope

    return ManagementScope(identity.database, identity.company_id)


async def test_report_confirm_and_later_reads_keep_published_configuration_after_restart(
    pinned_context, monkeypatch, tmp_path
):
    from agno.run import RunContext
    from agno.workflow.types import StepInput

    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.reporting.contract import REPORT_WORKFLOW_SCOPE_STATE_KEY
    from smart_reporting.reporting.data_source.models import MaterializedQueryResult
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.reporting.data_sources import ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
    )
    from smart_reporting.reporting.workflow.query_pipeline import ApprovedQuery, normalized_sql_hash
    from smart_reporting.tests.management_fixtures import physical_catalog

    provider, service, scopes, _, token, scope = pinned_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = provider
    runtime.registry = None
    runtime.profiles = None

    class UnavailableMetadata:
        async def query_agent(self):
            raise AssertionError("database 模式必须使用已发布 metadata")

    runtime.metadata_client = UnavailableMetadata()
    runtime.workspace_registry = ReportingWorkspaceRegistry(
        tmp_path / "workspaces", secret="managed-runtime-test-secret-32-bytes"
    )
    runtime.workspace_service = ReportingWorkspaceRouter(runtime.workspace_registry)
    with bind_verified_reporting_identity(
        VerifiedReportingIdentity("warehouse", "100", "7", "thread-1", "cli")
    ):
        state = runtime.prepare_run(
            run_id="run-1",
            session_id="thread-1",
            user_id="7",
            dependencies={
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": "warehouse", "companyId": "100"},
            },
        )
    context = RunContext(run_id="run-1", session_id="thread-1", user_id="7", session_state=state)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    request = {
        "reportGoal": "核对版本",
        "reportType": "comprehensive",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
    }
    await runtime.confirm_source(StepInput(input=request), context)
    assert context.session_state["report_schema_snapshots"][0]["terms"][0]["name"] == "收入"
    first = await runtime._sources(context)
    old_dsn = first[0].connection_dsn()
    draft = await service.save_draft(
        token,
        scope,
        "operations",
        SourceDraftInput.model_validate(
            {
                "name": "新源",
                "database": "warehouse",
                "dsn": "starrocks://r:new-secret@localhost:9030/warehouse",
                "reportingProfileVersionId": "base:1",
                "metadataVersionId": "operations:1",
            }
        ),
        1,
    )
    await service.publish(token, scope, "operations", draft["version"])
    runtime.configuration_provider = ManagedConfigurationProvider(scopes, service.vault)
    restored = await runtime._sources(context)
    assert restored[0].connection_dsn() == old_dsn
    adapter = runtime._adapter(restored[0], context)
    assert adapter.config.connection_dsn() == old_dsn
    await adapter.aclose()

    # 实际 Workflow 物化路径继续使用冻结连接；只替换外部数仓 I/O。
    def materialize(adapter, sql, *, max_bytes=None):
        assert adapter.config.connection_dsn() == old_dsn
        assert "warehouse.orders" in sql
        return MaterializedQueryResult(b"amount\n100\n", 1)

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_materialize", materialize)

    class ReportTools:
        async def report_prepare_dataset(self, dataset_ids, *, run_context):
            assert len(dataset_ids) == 1
            return {"jobId": "managed-job"}

        async def bind_page_layout(self, *args, **kwargs):
            return None

    runtime.report_tools = ReportTools()
    runtime.datasets = ReportDatasetStore(runtime.workspace_service)
    sql = "SELECT SUM(amount) AS amount FROM warehouse.orders WHERE amount = 2025"
    context.session_state["report_data_requirements"] = [
        {
            "requirementId": "income",
            "sourceId": "operations",
            "dimensionColumns": [],
            "grainColumns": [],
            "comparisonRoles": [],
            "tables": [
                {
                    "table": "warehouse.orders",
                    "periodColumn": "amount",
                    "periodGranularity": "year",
                    "measureColumns": ["amount"],
                }
            ],
        }
    ]
    window_id = (
        runtime._envelope(context).period_windows(granularity="year").windows[0].query_window_id
    )
    context.session_state["report_approved_queries"] = [
        ApprovedQuery(
            requirementId="income",
            sourceId="operations",
            sql=sql,
            sqlHash=normalized_sql_hash(sql),
            queryWindowId=window_id,
        ).model_dump(mode="json", by_alias=True)
    ]
    output = await runtime.materialize_datasets(StepInput(), context)
    handle = output.content["datasets"][0]
    assert handle["rowCount"] == 1
    content, _ = await runtime.workspace_service.afile_bytes(
        runtime._scope(context)["threadId"], handle["path"]
    )
    assert content == b"amount\n100\n"
    assert "test-secret" not in str(context.session_state)
    assert "new-secret" not in str(context.session_state)
    context.session_state[REPORT_WORKFLOW_SCOPE_STATE_KEY]["companyId"] = "200"
    with pytest.raises(ReportingError, match="report_workflow_scope_mismatch"):
        await runtime._sources(context)


async def test_database_read_failure_never_uses_file_registry(pinned_context, monkeypatch):
    from contextlib import asynccontextmanager

    from agno.run import RunContext

    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.workflow.identity import (
        VerifiedReportingIdentity,
        bind_verified_reporting_identity,
    )

    provider, *_ = pinned_context
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.configuration_provider = provider

    class ForbiddenRegistry:
        @property
        def sources(self):
            raise AssertionError("数据库失败不能回退文件配置")

    runtime.registry = ForbiddenRegistry()
    with bind_verified_reporting_identity(
        VerifiedReportingIdentity("warehouse", "100", "7", "thread-1", "cli")
    ):
        state = runtime.prepare_run(
            run_id="run-1",
            session_id="thread-1",
            user_id="7",
            dependencies={
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": "warehouse", "companyId": "100"}
            },
        )

    @asynccontextmanager
    async def unavailable():
        raise ManagementError("management_unavailable", "管理存储暂时不可用。", 503)
        yield  # pragma: no cover

    monkeypatch.setattr(provider.repository, "transaction", unavailable)
    with pytest.raises(ReportingError, match="management_unavailable"):
        await runtime._sources(
            RunContext(run_id="run-1", session_id="thread-1", user_id="7", session_state=state)
        )


async def test_profile_receives_frozen_organization_filters(scoped_report, monkeypatch):
    from agno.workflow.types import StepInput

    from smart_reporting.reporting.workflow.runtime import planning

    runtime, context, request = scoped_report
    await runtime.confirm_source(StepInput(input=request), context)
    context.session_state["report_data_understanding"] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "warehouse.orders",
                "role": "画像",
                "periodColumn": "report_year",
                "periodGranularity": "year",
            }
        ]
    }
    captured = []

    async def collect(adapter, **kwargs):
        captured.append(kwargs["scope_filters"])
        raise ReportingError("profile_test_stop", "已检查画像边界。")

    monkeypatch.setattr(planning, "collect_data_shape", collect)
    with pytest.raises(ReportingError, match="profile_test_stop"):
        await runtime.profile_source(StepInput(), context)
    assert captured == [{"warehouse.orders": {"company_id": "100"}}]
