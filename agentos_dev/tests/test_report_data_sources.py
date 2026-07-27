import copy
import json
import sqlite3
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from agno.run import RunContext

from agentos_dev import report_data_source_runtime, report_data_sources
from agentos_dev.report_data_sources import (
    CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
    MAX_DATASET_FILE_BYTES,
    MAX_DIRECTORY_ENTRIES,
    REPORT_DATA_RUNTIME_TIMEOUT_SECONDS,
    REPORT_DATASET_HANDLES_STATE_KEY,
    REPORT_SOURCE_BINDING_STATE_KEY,
    REPORT_SOURCE_INTAKE_DEPENDENCY,
    PostgresDataSource,
    PostgresSourceConfig,
    ReportDataSourceError,
    ReportDataSourceRegistry,
    ReportDataSourceToolkit,
    load_postgres_sources,
    validate_local_read_only_query,
    validate_read_only_query,
)
from agentos_dev.reporting import (
    ReportingError,
    TemporaryCredentialStore,
    TemporarySourceBindingService,
)
from agentos_dev.reporting.intake import ReportIntakeService
from agentos_dev.reporting.providers import SourceDescription, metadata_fingerprint


class FakeWorkspaceService:
    def __init__(self):
        self.entries = {
            "收入.csv": {"type": "file", "size": 12, "sha256": "a" * 64},
            "资料": {"type": "directory", "size": 0},
            "资料/明细.xlsx": {"type": "file", "size": 24, "sha256": "b" * 64},
            "附件/收入明细.csv": {"type": "file", "size": 18, "sha256": "d" * 64},
            "exports/员工.csv": {"type": "file", "size": 16, "sha256": "e" * 64},
        }

    async def astat(self, _thread, path=""):
        value = self.entries.get(path)
        if value is None:
            raise ValueError("not found")
        return {"path": path, "modifiedUnix": 1, "mode": "600", **value}

    async def ahash_file(self, _thread, path):
        value = self.entries[path]
        return {"path": path, "size": value["size"], "sha256": value["sha256"]}

    def list_files(self, _thread, path=""):
        prefix = f"{path}/" if path else ""
        result = []
        for candidate, value in self.entries.items():
            if not candidate.startswith(prefix):
                continue
            remainder = candidate[len(prefix) :]
            if not remainder or "/" in remainder:
                continue
            result.append(
                {
                    "path": candidate,
                    "name": remainder,
                    "isDirectory": value["type"] == "directory",
                    "size": value["size"],
                    "mimeType": "text/csv" if candidate.endswith(".csv") else False,
                    "modifiedAt": "2026-07-23T00:00:00Z",
                }
            )
        return result


def test_数据转换动作预算为600秒():
    assert MAX_DATASET_FILE_BYTES == 200 * 1024 * 1024
    assert report_data_source_runtime.MAX_PART_BYTES == 200 * 1024 * 1024
    assert REPORT_DATA_RUNTIME_TIMEOUT_SECONDS == 600


def context(references, attachments=None):
    dependencies = {"已选工作区引用": references}
    if attachments is not None:
        dependencies[CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY] = attachments
    return RunContext(
        run_id="run",
        session_id="thread",
        dependencies=dependencies,
        session_state={},
    )


class _FakeStarRocksClient:
    def __init__(self, *, read_only=True):
        self.read_only = read_only
        self.closed = False

    def verify_read_only(self, _allowed_tables):
        return self.read_only

    def describe(self, allowed_tables):
        tables = {table: ({"name": "month", "type": "DATE"},) for table in allowed_tables}
        return SourceDescription("hospital", tables, metadata_fingerprint(tables))

    def close(self):
        self.closed = True


def temporary_source_context(binding_service):
    intake = ReportIntakeService().parse(
        "类型: StarRocks\nhost: sr.internal\nport: 9030\nuser: report_reader\n"
        "pwd: secret\ndb: hospital\nCREATE TABLE hospital.revenue (month DATE);"
    )
    confirmation = binding_service.prepare(
        intake,
        user_id="user-1",
        thread_id="thread",
        session_id="thread",
    )
    dependency = {
        "confirmationId": confirmation.confirmation_id,
        "sourceMode": "temporary_database",
        "sourceType": "starrocks",
        "endpoint": confirmation.endpoint,
        "database": confirmation.database,
        "ddlTables": list(confirmation.allowed_tables),
        "expiresAt": confirmation.expires_at.isoformat(),
        "requiresConfirmation": True,
    }
    return confirmation, RunContext(
        run_id="run",
        session_id="thread",
        user_id="user-1",
        dependencies={
            REPORT_SOURCE_INTAKE_DEPENDENCY: json.dumps(
                dependency, ensure_ascii=True, separators=(",", ":")
            )
        },
        session_state={},
    )


@pytest.mark.anyio
async def test_临时来源必须通过原生工具确认后才写入会话绑定(monkeypatch):
    clients = []

    def client_factory(_credentials):
        client = _FakeStarRocksClient()
        clients.append(client)
        return client

    store = TemporaryCredentialStore()
    binding_service = TemporarySourceBindingService(
        store,
        client_factory,
        network_allowlist="sr.internal",
    )
    confirmation, run_context = temporary_source_context(binding_service)
    toolkit = ReportDataSourceToolkit(
        FakeWorkspaceService(),
        temporary_source_bindings=binding_service,
        temporary_report_credentials=store,
    )

    async def inline_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(report_data_sources.asyncio, "to_thread", inline_to_thread)

    assert toolkit.async_functions["report_confirm_temporary_source"].requires_confirmation is True
    pending = await toolkit.report_list_data_sources(run_context=run_context)
    assert pending["sources"][-1]["sourceType"] == "temporary_database_pending"
    assert clients == []

    result = await toolkit.report_confirm_temporary_source(
        confirmation.confirmation_id,
        run_context=run_context,
    )

    assert result["source"]["bindingId"].startswith("src_")
    assert run_context.session_state[REPORT_SOURCE_BINDING_STATE_KEY] == result["source"]
    assert clients[0].closed is True
    sources = await toolkit.report_list_data_sources(run_context=run_context)
    assert sources["sources"][-1]["sourceType"] == "starrocks"
    assert all(
        source["sourceType"] != "temporary_database_pending" for source in sources["sources"]
    )
    serialized = json.dumps(run_context.session_state)
    assert "secret" not in serialized
    assert "connectionRef" not in serialized


@pytest.mark.anyio
async def test_临时来源确认拒绝串用id和非只读账号(monkeypatch):
    store = TemporaryCredentialStore()
    clients = []

    def client_factory(_credentials):
        client = _FakeStarRocksClient(read_only=False)
        clients.append(client)
        return client

    binding_service = TemporarySourceBindingService(
        store,
        client_factory,
        network_allowlist="sr.internal",
    )
    confirmation, run_context = temporary_source_context(binding_service)
    toolkit = ReportDataSourceToolkit(
        FakeWorkspaceService(),
        temporary_source_bindings=binding_service,
        temporary_report_credentials=store,
    )

    async def inline_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(report_data_sources.asyncio, "to_thread", inline_to_thread)

    with pytest.raises(ReportDataSourceError) as mismatch:
        await toolkit.report_confirm_temporary_source("confirm_other", run_context=run_context)
    assert mismatch.value.code == "source_confirmation_scope_mismatch"
    assert clients == []

    with pytest.raises(ReportDataSourceError) as denied:
        await toolkit.report_confirm_temporary_source(
            confirmation.confirmation_id,
            run_context=run_context,
        )
    assert denied.value.code == "source_account_not_read_only"
    assert REPORT_SOURCE_BINDING_STATE_KEY not in run_context.session_state
    assert clients[0].closed is True


@pytest.mark.anyio
async def test_starrocks物化校验表范围且血缘不含凭据(monkeypatch):
    store = TemporaryCredentialStore()
    binding_service = TemporarySourceBindingService(
        store,
        lambda _credentials: _FakeStarRocksClient(),
        network_allowlist="sr.internal",
    )
    confirmation, run_context = temporary_source_context(binding_service)
    workspace = _FakePostgresWorkspace()
    toolkit = ReportDataSourceToolkit(
        workspace,
        temporary_source_bindings=binding_service,
        temporary_report_credentials=store,
    )

    async def inline_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(report_data_sources.asyncio, "to_thread", inline_to_thread)
    confirmed = await toolkit.report_confirm_temporary_source(
        confirmation.confirmation_id,
        run_context=run_context,
    )
    source_id = confirmed["source"]["bindingId"]
    query_client = SimpleNamespace(
        query=lambda *_args, **_kwargs: SimpleNamespace(
            columns=("month", "amount"),
            rows=(("2026-01-01", 100),),
            byte_count=32,
        ),
        close=lambda: None,
    )
    captured = {}

    async def store_handles(**values):
        captured.update(values)
        return {"datasets": [{"datasetId": "dataset-1"}]}

    monkeypatch.setattr(toolkit, "_temporary_client", lambda *_args: query_client)
    monkeypatch.setattr(toolkit, "_store_materialized_handles", store_handles)

    with pytest.raises(ReportingError) as denied:
        await toolkit.report_materialize_dataset(
            source_id,
            sql="SELECT * FROM hospital.cost",
            output_format="csv",
            run_context=run_context,
        )
    assert getattr(denied.value, "code", None) == "sql_table_denied"

    result = await toolkit.report_materialize_dataset(
        source_id,
        sql="SELECT month, amount FROM hospital.revenue",
        output_format="csv",
        run_context=run_context,
    )

    assert result == {"datasets": [{"datasetId": "dataset-1"}]}
    assert captured["source_type"] == "starrocks_materialized"
    assert set(captured["provenance"]) == {
        "bindingId",
        "querySha256",
        "metadataFingerprint",
    }
    assert "secret" not in json.dumps(captured["provenance"])
    assert len(workspace.fs.uploads) == 1


@pytest.mark.anyio
async def test_工作区文件引用解析为不可变数据集句柄():
    toolkit = ReportDataSourceToolkit(FakeWorkspaceService())
    run_context = context([{"path": "收入.csv", "type": "file", "tool": "untrusted"}])

    sources = await toolkit.report_list_data_sources(run_context=run_context)
    materialized = await toolkit.report_materialize_dataset(
        sources["sources"][1]["sourceId"],
        run_context=run_context,
    )

    assert sources["sources"][0]["sourceId"] == "workspace"
    assert sources["sources"][1]["path"] == "收入.csv"
    assert sources["sources"][1]["capabilities"] == ["describe", "materialize"]
    handle = materialized["datasets"][0]
    assert handle["sourceType"] == "workspace_file"
    assert handle["path"] == "收入.csv"
    assert handle["sha256"] == "a" * 64
    assert handle["provenance"] == {"workspacePath": "收入.csv"}
    assert run_context.session_state[REPORT_DATASET_HANDLES_STATE_KEY][handle["datasetId"]]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "suffix",
    [
        "csv",
        "tsv",
        "xls",
        "xlsx",
        "json",
        "jsonl",
        "parquet",
        "pdf",
        "md",
        "markdown",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "sqlite",
        "sqlite3",
        "db",
        "duckdb",
    ],
)
async def test_声明的工作区文件格式均可登记为数据集句柄(suffix):
    service = FakeWorkspaceService()
    path = f"数据/输入.{suffix}"
    service.entries[path] = {"type": "file", "size": 8, "sha256": "f" * 64}
    toolkit = ReportDataSourceToolkit(service)
    run_context = context([{"path": path, "type": "file"}])

    source = (await toolkit.report_list_data_sources(run_context=run_context))["sources"][1]
    materialized = await toolkit.report_materialize_dataset(
        source["sourceId"], run_context=run_context
    )

    assert materialized["datasets"][0]["format"] == suffix
    expected_type = (
        "workspace_database"
        if suffix in {"sqlite", "sqlite3", "db", "duckdb"}
        else "workspace_file"
    )
    assert materialized["datasets"][0]["sourceType"] == expected_type


@pytest.mark.anyio
async def test_工作区根目录描述限制返回数量():
    service = FakeWorkspaceService()
    service.entries = {
        f"输入/{index:03d}.csv": {"type": "file", "size": 1, "sha256": "a" * 64}
        for index in range(MAX_DIRECTORY_ENTRIES + 5)
    }
    service.entries.update(
        {
            f"{index:03d}.csv": {"type": "file", "size": 1, "sha256": "a" * 64}
            for index in range(MAX_DIRECTORY_ENTRIES + 5)
        }
    )
    toolkit = ReportDataSourceToolkit(service)

    result = await toolkit.report_describe_data_source("workspace", run_context=context([]))

    assert len(result["entries"]) == MAX_DIRECTORY_ENTRIES
    assert result["truncated"] is True


@pytest.mark.anyio
async def test_当前消息附件与odoo导出复用工作区数据源链路():
    toolkit = ReportDataSourceToolkit(FakeWorkspaceService())
    run_context = context(
        [],
        attachments=[
            {
                "path": "附件/收入明细.csv",
                "type": "file",
                "size": 18,
                "sha256": "d" * 64,
                "tool": "untrusted",
            }
        ],
    )

    sources = await toolkit.report_list_data_sources(run_context=run_context)
    attachment = next(
        item for item in sources["sources"] if item.get("path") == "附件/收入明细.csv"
    )
    exported = await toolkit.report_materialize_dataset(
        "workspace",
        paths=["exports/员工.csv"],
        run_context=run_context,
    )

    assert attachment["size"] == 18
    assert attachment["sha256"] == "d" * 64
    assert "tool" not in attachment
    assert exported["datasets"][0]["sourceType"] == "odoo_export"
    assert exported["datasets"][0]["provenance"] == {
        "workspacePath": "exports/员工.csv",
        "origin": "odoo_export",
    }


@pytest.mark.anyio
async def test_目录引用只描述直接子项并限制物化范围():
    toolkit = ReportDataSourceToolkit(FakeWorkspaceService())
    run_context = context([{"path": "资料", "type": "directory"}])
    sources = await toolkit.report_list_data_sources(run_context=run_context)
    directory = sources["sources"][1]

    description = await toolkit.report_describe_data_source(
        directory["sourceId"], run_context=run_context
    )
    selected = await toolkit.report_materialize_dataset(
        directory["sourceId"], paths=["资料/明细.xlsx"], run_context=run_context
    )

    assert [item["path"] for item in description["entries"]] == ["资料/明细.xlsx"]
    assert selected["datasets"][0]["path"] == "资料/明细.xlsx"
    with pytest.raises(ReportDataSourceError, match="不在所选目录"):
        await toolkit.report_materialize_dataset(
            directory["sourceId"], paths=["收入.csv"], run_context=run_context
        )


@pytest.mark.anyio
async def test_目录物化在去重前限制原始路径数量():
    toolkit = ReportDataSourceToolkit(FakeWorkspaceService())
    run_context = context([{"path": "资料", "type": "directory"}])
    source = (await toolkit.report_list_data_sources(run_context=run_context))["sources"][1]

    with pytest.raises(ReportDataSourceError) as error:
        await toolkit.report_materialize_dataset(
            source["sourceId"],
            paths=["资料/明细.xlsx"] * 21,
            run_context=run_context,
        )

    assert error.value.code == "invalid_dataset_count"


@pytest.mark.anyio
async def test_目录引用的汇总大小不套用单文件上限():
    toolkit = ReportDataSourceToolkit(FakeWorkspaceService())
    run_context = context([{"path": "资料", "type": "directory", "size": 30 * 1024 * 1024}])

    sources = await toolkit.report_list_data_sources(run_context=run_context)

    assert sources["sources"][1]["path"] == "资料"
    assert sources["sources"][1]["sourceType"] == "workspace_directory"


@pytest.mark.anyio
async def test_工作区文件变化后旧句柄失效():
    service = FakeWorkspaceService()
    toolkit = ReportDataSourceToolkit(service)
    run_context = context([{"path": "收入.csv", "type": "file"}])
    sources = await toolkit.report_list_data_sources(run_context=run_context)
    materialized = await toolkit.report_materialize_dataset(
        sources["sources"][1]["sourceId"], run_context=run_context
    )
    dataset_id = materialized["datasets"][0]["datasetId"]
    service.entries["收入.csv"]["sha256"] = "c" * 64

    with pytest.raises(ReportDataSourceError) as error:
        await toolkit.resolve_dataset_paths([dataset_id], run_context=run_context)

    assert error.value.code == "stale_dataset"


@pytest.mark.anyio
async def test_数据集句柄不能由其他thread直接复用():
    service = FakeWorkspaceService()
    toolkit = ReportDataSourceToolkit(service)
    source_context = context([{"path": "收入.csv", "type": "file"}])
    sources = await toolkit.report_list_data_sources(run_context=source_context)
    materialized = await toolkit.report_materialize_dataset(
        sources["sources"][1]["sourceId"], run_context=source_context
    )
    dataset_id = materialized["datasets"][0]["datasetId"]
    other_context = RunContext(
        run_id="other-run",
        session_id="other-thread",
        dependencies={},
        session_state=copy.deepcopy(source_context.session_state),
    )

    with pytest.raises(ReportDataSourceError) as error:
        await toolkit.resolve_dataset_paths([dataset_id], run_context=other_context)

    assert error.value.code == "stale_dataset"


@pytest.mark.anyio
async def test_解析数据集句柄时再次执行单文件大小边界():
    service = FakeWorkspaceService()
    toolkit = ReportDataSourceToolkit(service)
    run_context = context([{"path": "收入.csv", "type": "file"}])
    sources = await toolkit.report_list_data_sources(run_context=run_context)
    materialized = await toolkit.report_materialize_dataset(
        sources["sources"][1]["sourceId"], run_context=run_context
    )
    dataset_id = materialized["datasets"][0]["datasetId"]
    stored = run_context.session_state[REPORT_DATASET_HANDLES_STATE_KEY][dataset_id]
    stored["size"] = MAX_DATASET_FILE_BYTES + 1
    service.entries["收入.csv"]["size"] = MAX_DATASET_FILE_BYTES + 1

    with pytest.raises(ReportDataSourceError) as error:
        await toolkit.resolve_dataset_paths([dataset_id], run_context=run_context)

    assert error.value.code == "dataset_too_large"


def test_postgres_注册配置只引用凭据环境变量(tmp_path):
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "finance",
                        "name": "财务只读库",
                        "type": "postgresql",
                        "dsnEnv": "REPORT_FINANCE_DSN",
                        "schemas": ["reporting"],
                        "tables": ["reporting.revenue"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sources = load_postgres_sources(
        str(config),
        environ={"REPORT_FINANCE_DSN": "postgresql://report@db/reporting"},
        excluded_database_url="postgresql://agent@db/agentos",
    )

    assert sources["finance"].name == "财务只读库"
    assert sources["finance"].dsn == "postgresql://report@db/reporting"
    assert "postgresql://" not in sources["finance"].public_dict()["name"]

    registry = ReportDataSourceRegistry(
        FakeWorkspaceService(),
        config_path=str(config),
        environ={"REPORT_FINANCE_DSN": "postgresql://report@db/reporting"},
        excluded_database_url="postgresql://agent@db/agentos",
    )
    adapter = registry.postgres_sources["finance"]
    assert isinstance(adapter, PostgresDataSource)
    assert adapter.config == sources["finance"]
    assert "dsn" not in adapter.public_dict()


def test_postgres_注册拒绝_agentos_自身数据库(tmp_path):
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "agentos",
                        "type": "postgresql",
                        "dsnEnv": "REPORT_DSN",
                        "schemas": ["public"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    dsn = "postgresql://agent@db/agentos"

    with pytest.raises(ValueError, match="AgentOS"):
        load_postgres_sources(str(config), environ={"REPORT_DSN": dsn}, excluded_database_url=dsn)


def test_postgres_注册按默认端口拒绝_agentos_自身数据库(tmp_path):
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "agentos",
                        "type": "postgresql",
                        "dsnEnv": "REPORT_DSN",
                        "schemas": ["public"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="AgentOS"):
        load_postgres_sources(
            str(config),
            environ={"REPORT_DSN": "postgresql://report@db/agentos"},
            excluded_database_url="postgresql://agent@db:5432/agentos",
        )


def test_postgres_注册拒绝_query参数指定的_agentos_自身数据库(tmp_path):
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "agentos",
                        "type": "postgresql",
                        "dsnEnv": "REPORT_DSN",
                        "schemas": ["public"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="AgentOS"):
        load_postgres_sources(
            str(config),
            environ={"REPORT_DSN": "postgresql://report@db/?dbname=agentos"},
            excluded_database_url="postgresql+psycopg://agent@db:5432/agentos",
        )


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM reporting.revenue",
        "SELECT * FROM reporting.revenue; SELECT 1",
        "SELECT * INTO TEMP result FROM reporting.revenue",
        "SELECT * FROM private.revenue",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_cancel_backend(1)",
        "SELECT public.http_get('https://example.invalid')",
    ],
)
def test_sql_ast_拒绝非只读或越权查询(query):
    source = PostgresSourceConfig(
        id="finance",
        dsn_env="REPORT_DSN",
        dsn="postgresql://report@db/reporting",
        schemas=("reporting",),
        tables=("reporting.revenue",),
    )

    with pytest.raises(ReportDataSourceError):
        validate_read_only_query(query, source)


def test_sql_ast_接受白名单内_select和只读_cte():
    source = PostgresSourceConfig(
        id="finance",
        dsn_env="REPORT_DSN",
        dsn="postgresql://report@db/reporting",
        schemas=("reporting",),
        tables=("reporting.revenue",),
    )

    assert validate_read_only_query(
        "WITH monthly AS (SELECT amount FROM reporting.revenue) SELECT sum(amount) FROM monthly",
        source,
    ).startswith("WITH monthly")


def test_sql校验器不可用时失败关闭(monkeypatch):
    source = PostgresSourceConfig(
        id="finance",
        dsn_env="REPORT_DSN",
        dsn="postgresql://report@db/reporting",
        schemas=("reporting",),
        tables=("reporting.revenue",),
    )
    monkeypatch.setattr(report_data_sources, "sqlglot", None)
    monkeypatch.setattr(report_data_sources, "exp", None)

    with pytest.raises(ReportDataSourceError) as postgres_error:
        validate_read_only_query("SELECT * FROM reporting.revenue", source)
    with pytest.raises(ReportDataSourceError) as local_error:
        validate_local_read_only_query("SELECT * FROM revenue", "duckdb")

    assert postgres_error.value.code == "sql_validator_unavailable"
    assert local_error.value.code == "sql_validator_unavailable"


def test_registry_未配置外部数据库时仍可使用工作区():
    registry = ReportDataSourceRegistry(
        FakeWorkspaceService(),
        config_path=None,
        environ={},
        excluded_database_url="postgresql://agent@db/agentos",
    )

    assert registry.postgres_sources == {}


def test_工作区数据库只接受只读查询():
    assert validate_local_read_only_query("SELECT * FROM revenue", "sqlite") == (
        "SELECT * FROM revenue"
    )
    assert validate_local_read_only_query("SELECT * FROM json_each('[1,2]')", "sqlite") == (
        "SELECT * FROM json_each('[1,2]')"
    )
    with pytest.raises(ReportDataSourceError):
        validate_local_read_only_query("ATTACH DATABASE '/tmp/other.db' AS other", "sqlite")
    with pytest.raises(ReportDataSourceError):
        validate_local_read_only_query("PRAGMA writable_schema = ON", "sqlite")
    with pytest.raises(ReportDataSourceError):
        validate_local_read_only_query("SELECT load_extension('unsafe')", "sqlite")
    with pytest.raises(ReportDataSourceError):
        validate_local_read_only_query("SELECT * FROM read_csv_auto('/tmp/other.csv')", "duckdb")


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM glob('/etc/*')",
        "SELECT * FROM http_get('http://example.com')",
        "SELECT * FROM sqlite_query('other.sqlite', 'SELECT * FROM secrets')",
        "SELECT * FROM postgres_query('other', 'SELECT * FROM secrets')",
        "SELECT * FROM parquet_scan('other.parquet')",
        "SELECT * FROM read_json_objects('/etc/passwd')",
        "SELECT * FROM read_json_objects_auto('/etc/passwd')",
        "SELECT * FROM read_ndjson_auto('/etc/passwd')",
        "SELECT * FROM read_ndjson_objects('/etc/passwd')",
        "SELECT * FROM read_ndjson_objects_auto('/etc/passwd')",
        "SELECT * FROM read_xml('/etc/passwd')",
        "SELECT * FROM read_xlsx('/tmp/other.xlsx')",
        "SELECT * FROM s3_scan('s3://private-bucket/data.parquet')",
        "SELECT * FROM st_read('/etc/passwd')",
    ],
)
def test_工作区数据库拒绝读取外部文件或其他数据库(query):
    with pytest.raises(ReportDataSourceError):
        validate_local_read_only_query(query, "duckdb")


def test_sqlite_只读物化生成受限_csv分片(tmp_path, monkeypatch):
    database = tmp_path / "revenue.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE revenue (month TEXT, amount INTEGER)")
    connection.executemany(
        "INSERT INTO revenue VALUES (?, ?)",
        [("2026-01", 100), ("2026-02", 120)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(report_data_source_runtime, "WORKSPACE_ROOT", tmp_path)

    result = report_data_source_runtime.materialize_local(
        {
            "source_path": "revenue.sqlite",
            "file_format": "sqlite",
            "query": "SELECT month, amount FROM revenue ORDER BY month",
            "output_format": "csv",
            "output_dir": "报表/数据集/test/分片",
            "max_rows": 10,
            "max_bytes": 1024 * 1024,
        }
    )

    assert result["rowCount"] == 2
    assert result["schema"] == {"columns": ["month", "amount"]}
    assert result["paths"] == ["报表/数据集/test/分片/part-0001.csv"]
    assert (tmp_path / result["paths"][0]).read_text(encoding="utf-8").splitlines() == [
        "month,amount",
        "2026-01,100",
        "2026-02,120",
    ]


def test_sqlite_特殊文件名仍按只读_uri打开(tmp_path, monkeypatch):
    database = tmp_path / "revenue?2026#final.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE revenue (amount INTEGER)")
    connection.execute("INSERT INTO revenue VALUES (100)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(report_data_source_runtime, "WORKSPACE_ROOT", tmp_path)

    result = report_data_source_runtime.materialize_local(
        {
            "source_path": database.name,
            "file_format": "sqlite",
            "query": "SELECT amount FROM revenue",
            "output_format": "csv",
            "output_dir": "报表/数据集/special/分片",
            "max_rows": 10,
            "max_bytes": 1024 * 1024,
        }
    )

    assert result["rowCount"] == 1
    assert result["paths"] == ["报表/数据集/special/分片/part-0001.csv"]


def test_sqlite_物化按实际文件大小拆分且列名唯一(tmp_path, monkeypatch):
    database = tmp_path / "revenue.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE revenue (month TEXT, amount TEXT)")
    connection.executemany(
        "INSERT INTO revenue VALUES (?, ?)",
        [(f"2026-{index:02d}", "x" * 24) for index in range(1, 9)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(report_data_source_runtime, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(report_data_source_runtime, "MAX_PART_BYTES", 96)

    result = report_data_source_runtime.materialize_local(
        {
            "source_path": "revenue.sqlite",
            "file_format": "sqlite",
            "query": "SELECT month AS value, amount AS value FROM revenue ORDER BY month",
            "output_format": "csv",
            "output_dir": "报表/数据集/split/分片",
            "max_rows": 20,
            "max_bytes": 1024 * 1024,
        }
    )

    assert result["rowCount"] == 8
    assert result["schema"] == {"columns": ["value", "value_2"]}
    assert len(result["paths"]) > 1
    assert all((tmp_path / path).stat().st_size <= 96 for path in result["paths"])


class _FakePostgresCursor:
    description = [SimpleNamespace(name="amount"), SimpleNamespace(name="amount")]

    def __init__(self):
        self._batches = [[(1, 2), (3, 4)], []]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _query):
        return None

    async def fetchmany(self, _size):
        return self._batches.pop(0)


class _FakePostgresConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def transaction(self):
        return self

    async def execute(self, _query):
        return None

    def cursor(self, **_kwargs):
        return _FakePostgresCursor()


class _FakePostgresFs:
    def __init__(self):
        self.uploads = []

    async def upload_file(self, content, path):
        self.uploads.append((path, content))

    async def delete_file(self, _path, recursive=False):
        assert recursive is True
        raise RuntimeError("cleanup failed")


class _FakePostgresWorkspace:
    def __init__(self):
        self.fs = _FakePostgresFs()

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client, _thread):
        return SimpleNamespace(fs=self.fs)

    @staticmethod
    def normalize_path(path, allow_root=True):
        del allow_root
        return path, f"/home/daytona/workspace/{path}"

    async def _aensure_directory(self, _sandbox, _path):
        return None


@pytest.mark.anyio
async def test_postgres_物化保留唯一列名且清理失败不覆盖成功(monkeypatch):
    workspace = _FakePostgresWorkspace()
    toolkit = ReportDataSourceToolkit(workspace)
    source = PostgresSourceConfig(
        id="finance",
        dsn_env="REPORT_DSN",
        dsn="postgresql://report@db/reporting",
        schemas=("reporting",),
    )
    captured = {}

    async def connect(_dsn):
        return _FakePostgresConnection()

    async def convert(_action, payload, _run_context):
        captured["convert"] = payload
        return {
            "paths": ["报表/数据集/result/part-0001.parquet"],
            "rowCount": 2,
            "schema": {"columns": ["amount", "amount_2"]},
        }

    async def store(**values):
        captured["store"] = values
        return {"datasets": [{"datasetId": "dataset-1"}]}

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect)),
    )
    monkeypatch.setattr(toolkit, "_run_data_source_runtime", convert)
    monkeypatch.setattr(toolkit, "_store_materialized_handles", store)

    result = await toolkit._materialize_postgres(
        source,
        "SELECT amount, amount FROM reporting.revenue",
        "parquet",
        context([]),
    )

    assert result == {"datasets": [{"datasetId": "dataset-1"}]}
    assert workspace.fs.uploads[0][1].splitlines()[0] == b"amount,amount_2"
    assert captured["store"]["row_count"] == 2


@pytest.mark.anyio
async def test_多分片句柄不把总行数标记为每片行数():
    service = FakeWorkspaceService()
    service.entries.update(
        {
            "报表/数据集/result/part-0001.csv": {
                "type": "file",
                "size": 10,
                "sha256": "1" * 64,
            },
            "报表/数据集/result/part-0002.csv": {
                "type": "file",
                "size": 11,
                "sha256": "2" * 64,
            },
        }
    )
    toolkit = ReportDataSourceToolkit(service)

    result = await toolkit._store_materialized_handles(
        source_id="finance",
        source_type="postgresql_materialized",
        paths=[
            "报表/数据集/result/part-0001.csv",
            "报表/数据集/result/part-0002.csv",
        ],
        file_format="csv",
        schema={"columns": ["amount"]},
        row_count=8,
        provenance={"dataSourceId": "finance"},
        run_context=context([]),
    )

    assert result["rowCount"] == 8
    assert [dataset["rowCount"] for dataset in result["datasets"]] == [None, None]


@pytest.mark.anyio
async def test_工作区数据库查询期间变化会清理生成目录(monkeypatch):
    service = FakeWorkspaceService()
    service.entries["收入.sqlite"] = {
        "type": "file",
        "size": 12,
        "sha256": "a" * 64,
    }
    toolkit = ReportDataSourceToolkit(service)
    source = (
        await toolkit.report_list_data_sources(
            run_context=context([{"path": "收入.sqlite", "type": "file"}])
        )
    )["sources"][1]
    resolved = await toolkit._resolve_source(
        source["sourceId"], context([{"path": "收入.sqlite", "type": "file"}])
    )
    hashes = iter(
        [
            {"size": 12, "sha256": "a" * 64},
            {"size": 12, "sha256": "b" * 64},
        ]
    )
    cleaned = []

    async def hash_file(_thread, _path):
        return next(hashes)

    async def materialize(_action, payload, _run_context):
        return {
            "paths": [f"{payload['output_dir']}/part-0001.csv"],
            "rowCount": 1,
            "schema": {"columns": ["amount"]},
        }

    async def cleanup(path, _run_context):
        cleaned.append(path)

    monkeypatch.setattr(service, "ahash_file", hash_file)
    monkeypatch.setattr(toolkit, "_run_data_source_runtime", materialize)
    monkeypatch.setattr(toolkit, "_delete_materialized_output", cleanup)

    with pytest.raises(ReportDataSourceError) as error:
        await toolkit._materialize_workspace_database(
            resolved,
            "SELECT amount FROM revenue",
            "csv",
            context([]),
        )

    assert error.value.code == "stale_dataset"
    assert len(cleaned) == 1
    assert cleaned[0].endswith("/分片")


@pytest.mark.anyio
async def test_工作区数据库物化超时会清理确定输出目录(monkeypatch):
    service = FakeWorkspaceService()
    service.entries["收入.sqlite"] = {
        "type": "file",
        "size": 12,
        "sha256": "a" * 64,
    }
    toolkit = ReportDataSourceToolkit(service)
    run_context = context([{"path": "收入.sqlite", "type": "file"}])
    source = (await toolkit.report_list_data_sources(run_context=run_context))["sources"][1]
    resolved = await toolkit._resolve_source(source["sourceId"], run_context)
    cleaned = []

    async def timeout(*_args, **_kwargs):
        raise TimeoutError

    async def cleanup(path, _run_context):
        cleaned.append(path)

    monkeypatch.setattr(toolkit, "_run_data_source_runtime", timeout)
    monkeypatch.setattr(toolkit, "_delete_materialized_output", cleanup)

    with pytest.raises(TimeoutError):
        await toolkit._materialize_workspace_database(
            resolved,
            "SELECT amount FROM revenue",
            "csv",
            run_context,
        )

    assert len(cleaned) == 1
    assert cleaned[0].endswith("/分片")
