from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from ag_ui.core import RunAgentInput
from agno.run import RunContext
from agno.workflow.types import StepInput

from agentos_dev.coding.reporting.contract import (
    AgentQueryResponse,
    ModelColumn,
    ModelTable,
    ModelTermsResponse,
    ReportRequestEnvelope,
    schema_hash,
)
from agentos_dev.coding.reporting.data_source import CONFIG_FILE_NAME, load_report_source_registry
from agentos_dev.coding.reporting.entrypoints import prepare_agui_envelope
from agentos_dev.coding.reporting.metadata import ReportingMetadataClient, select_reporting_agent
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from agentos_dev.coding.reporting.runtime import (
    REPORT_SCHEMA_SNAPSHOTS_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    ReportWorkflowRuntime,
)
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
    empty = AgentQueryResponse(revision="r1", agents=())
    assert select_reporting_agent(empty, None) is None
    one = AgentQueryResponse.model_validate(
        {
            "revision": "r1",
            "agents": [
                {
                    "code": "a",
                    "name": "A",
                    "description": "",
                    "enabled": True,
                    "modelRevision": "m1",
                }
            ],
        }
    )
    assert select_reporting_agent(one, None).code == "a"  # type: ignore[union-attr]
    multiple = AgentQueryResponse(
        revision="r1",
        agents=one.agents + (one.agents[0].model_copy(update={"code": "b", "name": "B"}),),
    )
    selected = select_reporting_agent(multiple, "b")
    assert selected.code == "b"  # type: ignore[union-attr]
    pending = select_reporting_agent(multiple, None)
    assert isinstance(pending, tuple) and len(pending) == 2


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
            "revision": "agents-r1",
            "agents": [
                {
                    "code": code,
                    "name": name,
                    "description": "",
                    "enabled": True,
                    "modelRevision": "model-r1",
                }
                for code, name in (("a", "Agent A"), ("b", "Agent B"))
            ],
        }
    )
    metadata = ModelTermsResponse(
        revision="model-r1",
        schemaHash=schema_hash(model_tables),
        sourceRefs=({"sourceId": "operations"},),
        tables=model_tables,
        terms=(),
    )

    class FakeMetadata:
        async def query_agents(self, _source_ids):
            return agents

        async def query_model(self, *, agent_id, source_ids, expected_revision):
            assert agent_id == "b"
            assert source_ids == ("operations",)
            assert expected_revision == "model-r1"
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
            additional_data={"rejection_feedback": "agentId:b"},
        ),
        context,
    )

    assert [item["code"] for item in pending.content["agents"]] == ["a", "b"]
    assert confirmed.content["sources"][0]["sourceId"] == "operations"
    assert state[REPORT_WORKFLOW_INPUT_STATE_KEY]["agentId"] == "b"


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
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert require_approved_sql(approved, approved.sql) == approved.sql
    with pytest.raises(ReportingError) as changed:
        require_approved_sql(approved, f"{approved.sql};")
    assert changed.value.code == "report_sql_hash_mismatch"


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
        envelope=envelope(),
        requirements=(requirement or query_requirement(),),
    )


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
