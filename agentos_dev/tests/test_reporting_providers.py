from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agentos_dev.report_data_sources import DatasetHandle
from agentos_dev.reporting import (
    DataRequirement,
    ReportingError,
    ReportIntakeService,
    ReportSourceBinding,
    SourceMode,
    TemporaryCredentialStore,
    TemporarySourceBindingService,
)
from agentos_dev.reporting.providers import (
    QueryResult,
    SourceDescription,
    SourceProfile,
    SqlGenerationRouter,
    StarRocksProvider,
    metadata_fingerprint,
    validate_network_target,
    validate_starrocks_read_only_sql,
)

SCHEMA = {
    "hospital.revenue": (
        {"name": "month", "type": "DATE", "nullable": False},
        {"name": "amount", "type": "DECIMAL(18,2)", "nullable": True},
    )
}


def binding(mode=SourceMode.TEMPORARY_DATABASE, *, binding_id="binding-1"):
    return ReportSourceBinding(
        bindingId=binding_id,
        sourceMode=mode,
        database="hospital",
        allowedTables=("hospital.revenue",),
        metadataFingerprint=metadata_fingerprint(SCHEMA),
        threadId="thread-1",
        userId="user-1",
        sessionId="session-1",
        expiresAt=datetime.now(UTC) + timedelta(hours=2),
    )


def requirement(binding_id="binding-1"):
    return DataRequirement(
        requirementId="req-1",
        bindingId=binding_id,
        metric="收入",
        dimensions=("科室",),
        grain="月",
        period="2025-01 至 2025-12",
        comparisonPeriod="2024 可比期间",
        purpose="收入同比",
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM hospital.revenue",
        "SELECT * FROM hospital.revenue; SELECT 1",
        "SELECT * FROM other.revenue",
        "SELECT * FROM hospital.private_table",
        "SELECT load_file('/etc/passwd')",
        "SELECT sleep(10)",
    ],
)
def test_starrocks_sql拒绝写入多语句跨库越权和危险函数(sql):
    with pytest.raises(ReportingError):
        validate_starrocks_read_only_sql(
            sql, database="hospital", allowed_tables=("hospital.revenue",)
        )


def test_starrocks_sql接受允许表的_select和只读_cte():
    sql = (
        "WITH monthly AS (SELECT month, amount FROM hospital.revenue) "
        "SELECT month, sum(amount) FROM monthly GROUP BY month"
    )
    assert (
        validate_starrocks_read_only_sql(
            sql, database="hospital", allowed_tables=("hospital.revenue",)
        )
        == sql
    )


def test_临时主机必须命中服务端_allowlist():
    validate_network_target("10.20.1.8", "10.20.0.0/16")
    validate_network_target("sr.internal", "sr.internal,10.20.0.0/16")
    with pytest.raises(ReportingError) as denied:
        validate_network_target("10.30.1.8", "10.20.0.0/16")
    with pytest.raises(ReportingError):
        validate_network_target("sr.internal", None)
    assert denied.value.code == "source_host_denied"


class FakeClient:
    def __init__(self, *, read_only=True, byte_count=8):
        self.read_only = read_only
        self.byte_count = byte_count
        self.closed = False

    def verify_read_only(self, allowed_tables):
        assert allowed_tables == ("hospital.revenue",)
        return self.read_only

    def describe(self, allowed_tables):
        return SourceDescription("hospital", SCHEMA, metadata_fingerprint(SCHEMA))

    def profile(self, allowed_tables, *, timeout_seconds):
        return SourceProfile({"hospital.revenue": {"rowCount": 1}})

    def query(self, sql, *, timeout_seconds, max_rows):
        return QueryResult(("amount",), ((100,),), self.byte_count)

    def close(self):
        self.closed = True


class FakeMaterializer:
    def __init__(self):
        self.provenance = None

    def write_query_result(self, result, *, source_id, provenance):
        self.provenance = dict(provenance)
        return DatasetHandle(
            dataset_id="dataset-1",
            source_id=source_id,
            source_type="starrocks",
            path="datasets/dataset-1/part-0001.parquet",
            format="parquet",
            schema={"columns": list(result.columns)},
            row_count=len(result.rows),
            size=result.byte_count,
            sha256="a" * 64,
            sampled=False,
            provenance=dict(provenance),
        )


def provider(*, username="reader", read_only=True, max_bytes=1024):
    intake = ReportIntakeService().parse(
        "类型: StarRocks\nhost: sr.internal\nuser: "
        f"{username}\npwd: private-password\ndb: hospital\n"
    )
    assert intake.source_request is not None
    store = TemporaryCredentialStore()
    reference, _ = store.put(
        intake.source_request,
        user_id="user-1",
        thread_id="thread-1",
        session_id="session-1",
    )
    client = FakeClient(read_only=read_only, byte_count=max_bytes + 1)
    materializer = FakeMaterializer()
    current_binding = binding(binding_id=reference)
    return (
        lambda: StarRocksProvider(
            current_binding,
            store,
            lambda credentials: client,
            materializer,
            user_id="user-1",
            thread_id="thread-1",
            session_id="session-1",
            network_allowlist="sr.internal",
            max_bytes=max_bytes,
        ),
        client,
        materializer,
    )


@pytest.mark.parametrize("username", ["root", "admin", "administrator"])
def test_starrocks_provider拒绝管理员账号(username):
    factory, _client, _materializer = provider(username=username)
    with pytest.raises(ReportingError) as captured:
        factory()
    assert captured.value.code == "source_account_privileged"


def test_starrocks_provider无法证明只读时关闭连接并拒绝():
    factory, client, _materializer = provider(read_only=False)
    with pytest.raises(ReportingError) as captured:
        factory()
    assert captured.value.code == "source_account_not_read_only"
    assert client.closed is True


def test_starrocks_provider执行前重验sql并拒绝超量结果():
    factory, _client, _materializer = provider(max_bytes=8)
    current = factory()
    candidate = SimpleNamespace(
        binding_id=current.binding.binding_id,
        requirement_id="req-1",
        sql="SELECT amount FROM hospital.revenue",
        generator="agent",
    )
    with pytest.raises(ReportingError) as captured:
        current.materialize(candidate)
    assert captured.value.code == "query_result_too_large"


class FakeGenerator:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def generate_sql(self, requirement, current_binding):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def test_vanna成功时不调用_agent且无需逐条审批():
    vanna = FakeGenerator(["SELECT amount FROM hospital.revenue"])
    agent = FakeGenerator([AssertionError("不应调用 Agent SQL")])

    candidate = SqlGenerationRouter(agent, vanna).generate(requirement(), binding())

    assert candidate.generator == "vanna"
    assert candidate.requires_approval is False
    assert vanna.calls == 1
    assert agent.calls == 0


def test_vanna连续失败三次后临时源使用_agent_sql且不换源():
    vanna = FakeGenerator([RuntimeError("failed")])
    agent = FakeGenerator(["SELECT amount FROM hospital.revenue"])

    candidate = SqlGenerationRouter(agent, vanna).generate(requirement(), binding())

    assert vanna.calls == 3
    assert candidate.generator == "agent"
    assert candidate.binding_id == "binding-1"
    assert candidate.requires_approval is False


def test_无vanna时受管源_agent_sql仍需单独审批():
    agent = FakeGenerator(["SELECT amount FROM hospital.revenue"])
    managed = binding(SourceMode.MANAGED_QUERY)

    candidate = SqlGenerationRouter(agent).generate(requirement(), managed)

    assert candidate.generator == "agent"
    assert candidate.requires_approval is True


def test_非sql来源禁止静默改走sql():
    agent = FakeGenerator(["SELECT 1"])
    dataset = binding(SourceMode.PROVIDED_DATASET)
    with pytest.raises(ReportingError) as captured:
        SqlGenerationRouter(agent).generate(requirement(), dataset)
    assert captured.value.code == "sql_not_applicable"
    assert agent.calls == 0


def parsed_source(username="reader", ddl_database="hospital"):
    return ReportIntakeService().parse(
        "类型: StarRocks\nhost: sr.internal\nuser: "
        f"{username}\npwd: private-password\ndb: hospital\n\n"
        f"CREATE TABLE {ddl_database}.revenue (amount DECIMAL(18,2));\n"
    )


def binding_service(client):
    calls = []

    def factory(credentials):
        calls.append(dict(credentials))
        return client

    service = TemporarySourceBindingService(
        TemporaryCredentialStore(),
        factory,
        network_allowlist="sr.internal",
    )
    return service, calls


def test_来源准备阶段不连接批准后才验证并生成无密钥binding():
    client = FakeClient()
    service, calls = binding_service(client)
    confirmation = service.prepare(parsed_source(), user_id="u", thread_id="t", session_id="s")
    assert calls == []
    assert confirmation.public_dict()["endpoint"] == "sr.internal:9030"

    current = service.approve(
        confirmation.confirmation_id, user_id="u", thread_id="t", session_id="s"
    )

    assert len(calls) == 1
    assert current.allowed_tables == ("hospital.revenue",)
    assert "connectionRef" not in current.public_dict()
    assert "password" not in current.public_dict()
    assert client.closed is True
    with pytest.raises(ReportingError) as replay:
        service.approve(confirmation.confirmation_id, user_id="u", thread_id="t", session_id="s")
    assert replay.value.code == "source_confirmation_invalid"


def test_来源确认跨会话失败但不消耗合法确认():
    client = FakeClient()
    service, _calls = binding_service(client)
    confirmation = service.prepare(parsed_source(), user_id="u", thread_id="t", session_id="s")
    with pytest.raises(ReportingError) as mismatch:
        service.approve(
            confirmation.confirmation_id, user_id="other", thread_id="t", session_id="s"
        )
    assert mismatch.value.code == "source_confirmation_scope_mismatch"
    assert (
        service.approve(
            confirmation.confirmation_id, user_id="u", thread_id="t", session_id="s"
        ).user_id
        == "u"
    )


def test_来源准备拒绝管理员和跨库ddl且均不连接():
    service, calls = binding_service(FakeClient())
    with pytest.raises(ReportingError) as privileged:
        service.prepare(parsed_source("root"), user_id="u", thread_id="t", session_id="s")
    with pytest.raises(ReportingError) as mismatch:
        service.prepare(
            parsed_source(ddl_database="other"), user_id="u", thread_id="t", session_id="s"
        )
    assert privileged.value.code == "source_account_privileged"
    assert mismatch.value.code == "source_ddl_mismatch"
    assert calls == []


def test_批准时无法证明只读或实际元数据不一致均拒绝():
    read_write = FakeClient(read_only=False)
    service, _calls = binding_service(read_write)
    confirmation = service.prepare(parsed_source(), user_id="u", thread_id="t", session_id="s")
    with pytest.raises(ReportingError) as denied:
        service.approve(confirmation.confirmation_id, user_id="u", thread_id="t", session_id="s")
    assert denied.value.code == "source_account_not_read_only"

    mismatched = FakeClient()
    mismatched.describe = lambda _tables: SourceDescription(
        "hospital",
        {"hospital.other": SCHEMA["hospital.revenue"]},
        metadata_fingerprint({"hospital.other": SCHEMA["hospital.revenue"]}),
    )
    service, _calls = binding_service(mismatched)
    confirmation = service.prepare(parsed_source(), user_id="u", thread_id="t", session_id="s")
    with pytest.raises(ReportingError) as stale:
        service.approve(confirmation.confirmation_id, user_id="u", thread_id="t", session_id="s")
    assert stale.value.code == "source_ddl_mismatch"
