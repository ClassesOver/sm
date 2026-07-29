from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from ag_ui.core import RunAgentInput
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting.contract import (
    AgentQueryResponse,
    ModelColumn,
    ModelTable,
    ModelTerm,
    ModelTermsResponse,
    RawDdlModel,
    ReportRequestEnvelope,
    SourceSchemaSnapshot,
    schema_hash,
)
from agentos_dev.coding.reporting.data_source import CONFIG_FILE_NAME, load_report_source_registry
from agentos_dev.coding.reporting.entrypoints import prepare_agui_envelope
from agentos_dev.coding.reporting.metadata import ReportingMetadataClient, select_reporting_agent
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.profile import (
    ReportingProfileRegistry,
    resolve_capabilities,
    resolve_reporting_profile,
)
from agentos_dev.coding.reporting.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from agentos_dev.coding.reporting.runtime import (
    REPORT_CAPABILITIES_STATE_KEY,
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_RECONCILIATIONS_STATE_KEY,
    REPORT_SCHEMA_SNAPSHOTS_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    ReportOutline,
    ReportWorkflowRuntime,
)
from agentos_dev.coding.reporting.workflow import _requires_source_review
from agentos_dev.coding.reporting.workflow_v1 import (
    QueryRequirement,
    approve_query_batch,
    require_approved_sql,
    resolve_schema_snapshot,
)


def envelope(**updates):
    value = {
        "version": "1",
        "reportGoal": "分析经营情况",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "sourceIds": ["operations"],
    }
    value.update(updates)
    return ReportRequestEnvelope.from_untrusted(value)


def tables(*, nullable: bool = False):
    return (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name="income",
            columns=(ModelColumn(name="month", dataType="DATE", nullable=nullable),),
        ),
    )


def raw_ddl_models() -> tuple[RawDdlModel, ...]:
    return (
        RawDdlModel(
            id=1,
            modelName="income",
            modelDesc="收入模型",
            ddl="CREATE TABLE reporting.income (month DATE NOT NULL)",
        ),
    )


def source_config(tmp_path: Path):
    config = {
        "version": "1",
        "defaultSourceIds": ["operations"],
        "sources": [
            {
                "id": "operations",
                "type": "starrocks",
                "dsnEnv": "REPORT_DSN",
                "database": "reporting",
                "tables": ["reporting.income", "reporting.cost"],
                "periodColumns": {
                    "reporting.income": "month",
                    "reporting.cost": "month",
                },
            }
        ],
    }
    (tmp_path / CONFIG_FILE_NAME).write_text(json.dumps(config), encoding="utf-8")
    registry = load_report_source_registry(
        tmp_path,
        tmp_path,
        environ={"REPORT_DSN": "starrocks://reader:secret@db:9030/reporting"},
    )
    return registry.sources["operations"]


def approval_snapshots() -> tuple[SourceSchemaSnapshot, ...]:
    columns = (
        ModelColumn(name="month", dataType="DATE", nullable=False),
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ModelColumn(name="campus", dataType="VARCHAR(100)", nullable=True),
    )
    values = (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name=name,
            columns=columns,
        )
        for name in ("income", "cost")
    )
    model_tables = tuple(values)
    return (
        SourceSchemaSnapshot(
            source="metadata_api",
            revision="m1",
            schemaHash=schema_hash(model_tables),
            tables=model_tables,
        ),
    )


@pytest.mark.anyio
async def test_提纲要求使用领域无关的通用章节():
    captured: dict[str, object] = {}
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.update(payload)
        return ReportOutline(
            title="通用分析报告",
            sections=("执行摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
        )

    runtime._run_planner = run_planner
    profile_registry = ReportingProfileRegistry(documents={}, config_paths=())
    profile = resolve_reporting_profile(profile_registry, None)
    capabilities = resolve_capabilities(profile, (), ())
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={
            REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
                default_source_ids=("operations",)
            ),
            REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [],
            REPORT_DATA_SHAPES_STATE_KEY: [],
            REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
            REPORT_CAPABILITIES_STATE_KEY: capabilities.model_dump(mode="json", by_alias=True),
            REPORT_RECONCILIATIONS_STATE_KEY: [],
        },
    )

    await runtime.generate_outline(StepInput(input=envelope()), context)

    assert set(captured) == {"reportGoal", "period", "outlineContext", "schemas", "feedback"}
    outline_context = captured["outlineContext"]
    assert isinstance(outline_context, dict)
    assert captured["schemas"] == []
    sections = outline_context["profile"]["sections"]
    assert [item["title"] for item in sections] == [
        "执行摘要",
        "分析范围与方法",
        "关键发现",
        "局限性",
        "建议",
    ]
    required_sections = "\n".join(item["title"] for item in sections)
    assert all(term not in required_sections for term in ("院区", "科室", "预算", "收入"))


@pytest.mark.parametrize("field", ["host", "username", "password", "dsn", "databaseUrl"])
def test_envelope任何层级出现连接字段均返回稳定错误(field: str):
    with pytest.raises(ReportingError) as captured:
        envelope(schemaInput={field: "secret"})
    assert captured.value.code == "report_connection_input_forbidden"


def test_agui提取envelope和ddl后从模型上下文删除():
    ddl = "CREATE TABLE reporting.income (month DATE NOT NULL);"
    run_input = RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
            "messages": [
                {
                    "id": "message-1",
                    "role": "user",
                    "content": f"```json\n{envelope().model_dump_json(by_alias=True)}\n```\n```sql\n{ddl}\n```",
                }
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )

    prepared = prepare_agui_envelope(run_input)

    assert prepared.envelope.schema_input is not None
    assert prepared.envelope.schema_input.ddl == ddl
    assert ddl not in repr(prepared.run_input)
    assert "分析经营情况" in str(prepared.run_input.messages[-1].content)


def test_agent分流覆盖零个一个多个和显式选择():
    empty = AgentQueryResponse(agents=())
    assert select_reporting_agent(empty, None) is None
    one = AgentQueryResponse.model_validate(
        {
            "agents": [
                {
                    "code": "1",
                    "name": "A",
                    "description": "",
                    "enabled": True,
                }
            ],
        }
    )
    assert select_reporting_agent(one, None).code == "1"  # type: ignore[union-attr]
    multiple = AgentQueryResponse(
        agents=one.agents + (one.agents[0].model_copy(update={"code": "2", "name": "B"}),),
    )
    selected = select_reporting_agent(multiple, "2")
    assert selected.code == "2"  # type: ignore[union-attr]
    pending = select_reporting_agent(multiple, None)
    assert isinstance(pending, tuple) and len(pending) == 2


def test_来源唯一时不审核仅多个agent时审核():
    assert (
        _requires_source_review(StepOutput(content={"sources": [{"sourceId": "operations"}]}))
        is False
    )
    assert _requires_source_review(StepOutput(content={"agents": [{"code": "1"}]})) is False
    assert (
        _requires_source_review(StepOutput(content={"agents": [{"code": "1"}, {"code": "2"}]}))
        is True
    )


@pytest.mark.anyio
async def test_metadata故障不会降级为零agent():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://metadata.internal"
    )
    service = ReportingMetadataClient("https://metadata.internal", client_factory=lambda: client)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_agents(("operations",))
        assert captured.value.code == "report_metadata_unavailable"
    finally:
        await client.aclose()


def test_api与ddl冲突以及catalog漂移都失败关闭(tmp_path: Path):
    source = source_config(tmp_path)
    api_tables = tables(nullable=False)
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash(api_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=api_tables,
        terms=(),
    )
    conflicting = envelope(schemaInput={"ddl": "CREATE TABLE reporting.income (month DATE);"})
    with pytest.raises(ReportingError) as conflict:
        resolve_schema_snapshot(
            conflicting,
            source=source,
            metadata=metadata,
            catalog=api_tables,
        )
    assert conflict.value.code == "report_schema_conflict"

    valid = envelope()
    with pytest.raises(ReportingError) as drift:
        resolve_schema_snapshot(
            valid,
            source=source,
            metadata=metadata,
            catalog=tables(nullable=True),
        )
    assert drift.value.code == "report_catalog_drift"

    catalog_with_extra = (
        api_tables[0].model_copy(
            update={
                "columns": api_tables[0].columns
                + (ModelColumn(name="unexpected", dataType="INT", nullable=True),)
            }
        ),
    )
    with pytest.raises(ReportingError) as extra:
        resolve_schema_snapshot(
            valid,
            source=source,
            metadata=metadata,
            catalog=catalog_with_extra,
        )
    assert extra.value.code == "report_catalog_drift"


def test_metadata术语保存在通用结构快照(tmp_path: Path):
    source = source_config(tmp_path)
    api_tables = tables()
    term = ModelTerm(
        code="actual_amount",
        name="实际金额",
        kind="measure",
        fieldRefs=("operations.reporting.income.month",),
    )
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash(api_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=api_tables,
        terms=(term,),
    )

    snapshot = resolve_schema_snapshot(
        envelope(),
        source=source,
        metadata=metadata,
        catalog=api_tables,
    )

    assert snapshot.terms == (term,)


@pytest.mark.anyio
async def test_ddl解析后不进入workflow_state(tmp_path: Path, monkeypatch):
    source = source_config(tmp_path)
    ddl = "CREATE TABLE reporting.income (month DATE NOT NULL);"

    class FakeAdapter:
        def __init__(self, _source):
            pass

        async def verify_read_only(self):
            return None

        async def catalog(self):
            return (
                SimpleNamespace(
                    source_id="operations",
                    database="reporting",
                    name="income",
                    columns=(SimpleNamespace(name="month", data_type="DATE", nullable=False),),
                ),
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "agentos_dev.coding.reporting.runtime.StarRocksDataSourceAdapter", FakeAdapter
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(
        sources={"operations": source}, default_source_ids=("operations",)
    )
    runtime.profiles = ReportingProfileRegistry(documents={}, config_paths=())
    runtime.metadata_client = None
    state = {}
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )

    await runtime.confirm_source(
        StepInput(input=envelope(schemaInput={"ddl": ddl})),
        context,
    )

    assert "schemaInput" not in state[REPORT_WORKFLOW_INPUT_STATE_KEY]
    assert REPORT_SCHEMA_SNAPSHOTS_STATE_KEY in state
    assert "CREATE TABLE" not in repr(state)


@pytest.mark.anyio
async def test_多个metadata_agent先暂停展示再在同一步继续(tmp_path: Path, monkeypatch):
    source = source_config(tmp_path)
    model_tables = tables()
    agents = AgentQueryResponse.model_validate(
        {
            "agents": [
                {
                    "code": code,
                    "name": name,
                    "description": "",
                    "enabled": True,
                }
                for code, name in (("1", "Agent A"), ("2", "Agent B"))
            ],
        }
    )
    metadata = ModelTermsResponse(
        revision="model-r1",
        schemaHash=schema_hash(model_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=model_tables,
        terms=(),
    )

    class FakeMetadata:
        async def query_agents(self, _source_ids):
            return agents

        async def query_model(self, *, agent_id, sources):
            assert agent_id == "2"
            assert tuple(item.id for item in sources) == ("operations",)
            return metadata

    class FakeAdapter:
        def __init__(self, _source):
            pass

        async def verify_read_only(self):
            return None

        async def catalog(self):
            return (
                SimpleNamespace(
                    source_id="operations",
                    database="reporting",
                    name="income",
                    columns=(SimpleNamespace(name="month", data_type="DATE", nullable=False),),
                ),
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "agentos_dev.coding.reporting.runtime.StarRocksDataSourceAdapter", FakeAdapter
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(
        sources={"operations": source}, default_source_ids=("operations",)
    )
    runtime.profiles = ReportingProfileRegistry(documents={}, config_paths=())
    runtime.metadata_client = FakeMetadata()
    state = {}
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )

    pending = await runtime.confirm_source(StepInput(input=envelope()), context)
    confirmed = await runtime.confirm_source(
        StepInput(
            input=envelope(),
            additional_data={"rejection_feedback": "agentId:2"},
        ),
        context,
    )

    assert [item["code"] for item in pending.content["agents"]] == ["1", "2"]
    assert confirmed.content["sources"][0]["sourceId"] == "operations"
    assert state[REPORT_WORKFLOW_INPUT_STATE_KEY]["agentId"] == "2"


def test_sql审核后只允许执行完全相同的原文(tmp_path: Path):
    source = source_config(tmp_path)
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month"],
            "grainColumns": ["month"],
        }
    )
    (approved,) = approve_query_batch(
        [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "sql": (
                    "SELECT month, SUM(amount) AS amount FROM reporting.income "
                    "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                ),
            }
        ],
        sources={"operations": source},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert require_approved_sql(approved, approved.sql) == approved.sql
    with pytest.raises(ReportingError) as changed:
        require_approved_sql(approved, f"{approved.sql};")
    assert changed.value.code == "report_sql_hash_mismatch"


def test_sql审核年度期间使用完整整数年份边界(tmp_path: Path):
    source = replace(
        source_config(tmp_path),
        tables=("reporting.income",),
        period_columns={"reporting.income": "period_year"},
        period_granularities={"reporting.income": "year"},
    )
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_year", dataType="INT", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "annual-income",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "period_year",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["period_year"],
            "grainColumns": ["period_year"],
        }
    )
    annual_envelope = envelope(period={"start": "2024-06-01", "end": "2025-03-31"})

    (approved,) = approve_query_batch(
        [
            {
                "requirementId": "annual-income",
                "sourceId": "operations",
                "sql": (
                    "SELECT period_year, SUM(amount) AS amount FROM reporting.income "
                    "WHERE period_year BETWEEN 2024 AND 2025 GROUP BY period_year"
                ),
            }
        ],
        sources={"operations": source},
        snapshots=(snapshot,),
        envelope=annual_envelope,
        requirements=(requirement,),
    )

    assert "BETWEEN 2024 AND 2025" in approved.sql


def query_requirement(*, tables=None, grain_columns=("month",)):
    table_values = [
        dict(item) for item in (tables or [{"table": "reporting.income", "periodColumn": "month"}])
    ]
    for item in table_values:
        item.setdefault("measureColumns", ["amount"])
    relations = [
        {
            "leftTable": table_values[index - 1]["table"],
            "rightTable": table_values[index]["table"],
            "joinColumns": grain_columns,
        }
        for index in range(1, len(table_values))
    ]
    return QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": table_values,
            "dimensionColumns": grain_columns,
            "grainColumns": grain_columns,
            "relations": relations,
        }
    )


def approve_sql(tmp_path: Path, sql: str, *, requirement=None):
    return approve_query_batch(
        [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "sql": sql,
            }
        ],
        sources={"operations": source_config(tmp_path)},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement or query_requirement(),),
    )


@pytest.mark.parametrize(
    ("requirement", "sql"),
    [
        (
            query_requirement(
                tables=[
                    {
                        "table": "reporting.cost",
                        "periodColumn": "month",
                        "measureColumns": ["amount"],
                    }
                ]
            ),
            "SELECT month, SUM(amount) FROM reporting.cost "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
        ),
        (
            query_requirement(
                tables=[
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "measureColumns": ["amount"],
                    }
                ]
            ),
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
        ),
    ],
)
def test_sql审核拒绝服务端白名单内但结构快照外的表和字段(
    tmp_path: Path, requirement: QueryRequirement, sql: str
):
    snapshot_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(ModelColumn(name="month", dataType="DATE", nullable=False),),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((snapshot_table,)),
        tables=(snapshot_table,),
    )

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": requirement.requirement_id,
                    "sourceId": "operations",
                    "sql": sql,
                }
            ],
            sources={"operations": source_config(tmp_path)},
            snapshots=(snapshot,),
            envelope=envelope(),
            requirements=(requirement,),
        )

    assert captured.value.code == "report_query_scope_invalid"


@pytest.mark.parametrize(
    "sql, code",
    [
        (
            "SELECT month, SUM(amount) FROM reporting.income GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month >= '2025-01-01' GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' "
            "AND month >= '2025-06-01' GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
            "report_query_grain_invalid",
        ),
    ],
)
def test_sql审核验证完整期间和requirement粒度(tmp_path: Path, sql: str, code: str):
    requirement = query_requirement(grain_columns=("month", "campus"))

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == code


def test_sql审核拒绝未聚合声明指标字段(tmp_path: Path):
    sql = (
        "SELECT month, COUNT(*) FROM reporting.income "
        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
    )

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql)

    assert captured.value.code == "report_query_measure_invalid"


def test_sql审核按数据源年度粒度校验期间(tmp_path: Path):
    source = replace(
        source_config(tmp_path),
        period_columns={"reporting.income": "period_year"},
        period_granularities={"reporting.income": "year"},
    )
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_year", dataType="INT", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
    )
    requirement = query_requirement(
        tables=[
            {
                "table": "reporting.income",
                "periodColumn": "period_year",
                "measureColumns": ["amount"],
            }
        ],
        grain_columns=("period_year",),
    )
    sql = (
        "SELECT period_year, SUM(amount) FROM reporting.income "
        "WHERE period_year BETWEEN 2025 AND 2025 GROUP BY period_year"
    )

    approved = approve_query_batch(
        [{"requirementId": "income-monthly", "sourceId": "operations", "sql": sql}],
        sources={"operations": source},
        snapshots=(snapshot,),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert approved[0].sql == sql


def test_sql审核拒绝跨表明细连接放大(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ]
    )
    sql = (
        "SELECT i.month, SUM(i.amount), SUM(c.amount) "
        "FROM reporting.income i JOIN reporting.cost c ON i.month = c.month "
        "WHERE i.month BETWEEN '2025-01-01' AND '2025-12-31' "
        "AND c.month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY i.month"
    )

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == "report_query_join_grain_invalid"


def test_sql审核允许各表先聚合后按完整共同粒度连接(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
    )
    sql = """
        WITH income AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.income
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        ), cost AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.cost
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        )
        SELECT income.month, income.campus, income.amount, cost.amount
        FROM income JOIN cost
          ON income.month = cost.month AND income.campus = cost.campus
    """

    (approved,) = approve_sql(tmp_path, sql, requirement=requirement)

    assert approved.requirement_id == requirement.requirement_id


def test_sql审核拒绝聚合结果遗漏共同粒度连接键(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
    )
    sql = """
        WITH income AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.income
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        ), cost AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.cost
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        )
        SELECT income.month, income.campus, income.amount, cost.amount
        FROM income JOIN cost ON income.month = cost.month
    """

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == "report_query_join_grain_invalid"


@pytest.mark.anyio
async def test_download_grant绑定scope_revision和文件hash且cli不返回url():
    repository = InMemoryDownloadGrantRepository()
    service = ReportDownloadGrantService(repository)
    scope = ReportDownloadScope("db", "u", "c", "s", "t", "run")
    now = datetime(2026, 7, 28, tzinfo=UTC)
    raw, grant = await service.issue(
        scope=scope,
        report_id="report-1",
        revision=1,
        pdf_path="reports/result.pdf",
        pdf_size=100,
        pdf_sha256="a" * 64,
        now=now,
    )

    assert raw not in repository.records
    assert (
        await service.resolve(
            raw,
            scope=scope,
            current_pdf_sha256="a" * 64,
            current_revision=1,
            now=now,
        )
        == grant
    )
    for values, code in (
        (
            {"scope": ReportDownloadScope("db", "other", "c", "s", "t", "run")},
            "report_download_scope_mismatch",
        ),
        ({"current_revision": 2}, "report_download_revision_changed"),
        ({"current_pdf_sha256": "b" * 64}, "report_download_file_changed"),
        ({"now": now + timedelta(hours=24)}, "report_download_grant_expired"),
    ):
        arguments = {
            "scope": scope,
            "current_pdf_sha256": "a" * 64,
            "current_revision": 1,
            "now": now,
            **values,
        }
        with pytest.raises(ReportingError) as captured:
            await service.resolve(raw, **arguments)
        assert captured.value.code == code

    http = publication_result(report_id="report-1", revision=1, raw_grant=raw, grant=grant)
    cli = cli_result(path="/tmp/result.pdf", size=100, sha256="a" * 64)
    assert "downloadUrl" in http["pdf"]  # type: ignore[operator]
    assert "Url" not in repr(cli) and "url" not in repr(cli)
