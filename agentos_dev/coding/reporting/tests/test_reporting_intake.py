from datetime import UTC, datetime, timedelta

import pytest
from ag_ui.core import RunAgentInput
from pydantic import ValidationError

from agentos_dev.coding.reporting import (
    AnalysisMethodDecision,
    AnalysisPlan,
    ReportingError,
    ReportIntakeService,
    TemporaryCredentialStore,
    TemporarySourceBindingService,
)
from agentos_dev.coding.reporting.agui import (
    REPORT_SOURCE_INTAKE_DEPENDENCY,
    prepare_agui_report_intake,
    sanitized_intake_snapshot,
)

SAMPLE = """请生成瑞金医院运营分析报告。

类型: StarRocks
host: sr.internal
port: 9030
user: report_reader
pwd: exposed-secret
db: hospital

CREATE TABLE hospital.revenue_monthly (
  month DATE,
  department VARCHAR(100),
  amount DECIMAL(18, 2)
);
"""


def test_连接块解析后密码只进入临时请求():
    intake = ReportIntakeService().parse(SAMPLE)

    assert intake.source_request is not None
    assert intake.source_request.host == "sr.internal"
    assert intake.source_request.password.get_secret_value() == "exposed-secret"
    assert intake.ddl_tables == ("hospital.revenue_monthly",)
    assert "exposed-secret" not in intake.sanitized_text
    assert "password: [REDACTED]" in intake.sanitized_text
    assert repr(intake.source_request.password) == "SecretStr('**********')"
    with pytest.raises(TypeError, match="not_serializable"):
        intake.source_request.model_dump()
    with pytest.raises(TypeError, match="not_serializable"):
        intake.source_request.model_dump_json()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("类型: mysql\nhost: db\nuser: u\npwd: p\ndb: d\n", "source_type_unsupported"),
        ("类型: StarRocks\nhost: db\nuser: u\ndb: d\n", "source_connection_incomplete"),
        (
            "类型: StarRocks\nhost: one\nuser: u\npwd: p\ndb: d\n\n"
            "类型: StarRocks\nhost: two\nuser: u\npwd: p\ndb: d\n",
            "source_connection_ambiguous",
        ),
    ],
)
def test_连接块歧义或不完整时失败关闭且异常不泄露密码(text, code):
    with pytest.raises(ReportingError) as captured:
        ReportIntakeService().parse(text)

    assert captured.value.code == code
    assert "pwd: p" not in str(captured.value)


def test_临时引用绑定用户_thread_session并按无活动时间续期():
    request = ReportIntakeService().parse(SAMPLE).source_request
    assert request is not None
    store = TemporaryCredentialStore(idle_ttl=timedelta(hours=2))
    start = datetime(2026, 7, 27, 8, tzinfo=UTC)
    reference, initial_expiry = store.put(
        request,
        user_id="user-1",
        thread_id="thread-1",
        session_id="session-1",
        now=start,
    )

    resolved = store.resolve(
        reference,
        user_id="user-1",
        thread_id="thread-1",
        session_id="session-1",
        now=start + timedelta(hours=1),
    )

    assert resolved is request
    assert initial_expiry == start + timedelta(hours=2)
    for scope in (
        {"user_id": "other", "thread_id": "thread-1", "session_id": "session-1"},
        {"user_id": "user-1", "thread_id": "other", "session_id": "session-1"},
        {"user_id": "user-1", "thread_id": "thread-1", "session_id": "other"},
    ):
        with pytest.raises(ReportingError) as captured:
            store.resolve(reference, now=start + timedelta(hours=1), **scope)
        assert captured.value.code == "connection_ref_scope_mismatch"


def test_临时引用过期关闭和服务重启后不可使用():
    request = ReportIntakeService().parse(SAMPLE).source_request
    assert request is not None
    start = datetime(2026, 7, 27, 8, tzinfo=UTC)
    store = TemporaryCredentialStore(idle_ttl=timedelta(minutes=1))
    reference, _ = store.put(request, user_id="u", thread_id="t", session_id="s", now=start)

    with pytest.raises(ReportingError) as expired:
        store.resolve(
            reference,
            user_id="u",
            thread_id="t",
            session_id="s",
            now=start + timedelta(minutes=1),
        )
    assert expired.value.code == "connection_ref_expired"

    reference, _ = store.put(request, user_id="u", thread_id="t", session_id="s", now=start)
    with pytest.raises(ReportingError) as restarted:
        TemporaryCredentialStore().resolve(
            reference, user_id="u", thread_id="t", session_id="s", now=start
        )
    assert restarted.value.code == "connection_ref_invalid"


def test_分析计划要求逐项评估综合同比环比和归因():
    decisions = tuple(
        AnalysisMethodDecision(method=method, decision="execute", rationale="数据范围完整。")
        for method in (
            "comprehensive",
            "year_over_year",
            "month_over_month",
            "attribution",
        )
    )
    plan = AnalysisPlan(
        planId="plan-1",
        outlineId="outline-1",
        bindingId="binding-1",
        methods=decisions,
    )
    assert len(plan.methods) == 4

    with pytest.raises(ValidationError, match="month_over_month"):
        AnalysisPlan(
            planId="plan-2",
            outlineId="outline-1",
            bindingId="binding-1",
            methods=decisions[:2] + decisions[3:] + decisions[3:],
        )


def agui_input(message=SAMPLE, context=()):
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
            "messages": [{"id": "message-1", "role": "user", "content": message}],
            "tools": [],
            "context": list(context),
            "forwardedProps": {},
        }
    )


def binding_service(store, client_calls=None):
    calls = client_calls if client_calls is not None else []

    def client_factory(_credentials):
        calls.append(True)
        raise AssertionError("来源确认前不应连接 StarRocks")

    return TemporarySourceBindingService(
        store,
        client_factory,
        network_allowlist="sr.internal",
    )


def test_agui前置intake替换原消息且server_context不含凭据():
    store = TemporaryCredentialStore()
    client_calls = []

    prepared = prepare_agui_report_intake(
        agui_input(),
        user_id="user-1",
        service=ReportIntakeService(),
        binding_service=binding_service(store, client_calls),
    )

    snapshot = sanitized_intake_snapshot(prepared)
    assert snapshot is not None
    assert snapshot["sourceType"] == "starrocks"
    assert snapshot["ddlTables"] == ["hospital.revenue_monthly"]
    assert "password" not in snapshot
    assert "user" not in snapshot
    assert "connectionRef" not in snapshot
    assert "exposed-secret" not in prepared.messages[-1].content
    assert "exposed-secret" not in repr(prepared)
    assert snapshot["confirmationId"].startswith("confirm_")
    assert client_calls == []


def test_agui临时连接缺少ddl时拒绝且不生成来源context():
    value = agui_input(
        "类型: StarRocks\nhost: sr.internal\nuser: reader\npwd: secret\ndb: hospital\n"
    )
    with pytest.raises(ReportingError) as captured:
        prepare_agui_report_intake(
            value,
            user_id="user-1",
            service=ReportIntakeService(),
            binding_service=binding_service(TemporaryCredentialStore()),
        )
    assert captured.value.code == "source_tables_required"
    assert all(item.description != REPORT_SOURCE_INTAKE_DEPENDENCY for item in value.context)
