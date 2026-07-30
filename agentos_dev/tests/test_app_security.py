import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from ag_ui.core import (
    EventType,
    RawEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningStartEvent,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession

from agentos_dev import app as app_module
from agentos_dev.coding.repository import CodingTaskRepository, utcnow
from agentos_dev.database import create_agent_database
from agentos_dev.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    service,
)
from agentos_dev.workspace import WorkspaceService

SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_coding_repository(monkeypatch, tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    context = replace(
        app_module.application_context,
        database=database,
        coding_repository=CodingTaskRepository(database.async_db),
    )
    monkeypatch.setattr(app_module, "application_context", context)
    monkeypatch.setattr(app_module.base_app.state, "agentos_context", context)

    yield context
    database.sync_engine.dispose()


@pytest.fixture
async def client(monkeypatch, isolated_coding_repository):
    context = app_module.base_app.state.agentos_context
    test_context = replace(
        context,
        settings=replace(context.settings, workspace_hmac_secret=SECRET),
    )
    monkeypatch.setattr(app_module.base_app.state, "agentos_context", test_context)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_module.app),
        base_url="http://testserver",
    ) as value:
        yield value


def capability(thread="thread-1", **overrides):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "AGUI-CAP"}
    claims = {
        "aud": "agui-agentos-workspace",
        "database": "odoo",
        "user": 7,
        "company": 3,
        "odoo_session": "a" * 64,
        "thread": thread,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)

    def segment(value):
        return (
            base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            )
            .rstrip(b"=")
            .decode()
        )

    signing_input = f"{segment(header)}.{segment(claims)}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(
                SECRET.encode(),
                signing_input.encode(),
                hashlib.sha256,
            ).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    return f"{signing_input}.{signature}"


def run_input(
    message="普通问答",
    *,
    tools=(),
    context=(),
    messages=None,
    state=None,
):
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": state or {},
            "messages": messages or [{"id": "user-1", "role": "user", "content": message}],
            "tools": [
                {"name": name, "description": "页面工具", "parameters": {"type": "object"}}
                for name in tools
            ],
            "context": list(context),
            "forwardedProps": {},
        }
    )


def direct_request(branch=None):
    claims = SimpleNamespace(
        database="odoo",
        user=7,
        company=3,
        odoo_session="a" * 64,
    )
    return SimpleNamespace(
        state=SimpleNamespace(capability=claims, branch=branch),
        headers={},
        app=SimpleNamespace(
            state=SimpleNamespace(agentos_context=app_module.application_context),
        ),
    )


async def response_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
    return b"".join(chunks).decode()


@pytest.mark.anyio
async def test_direct_agent_run_routes_are_disabled(client):
    for agent_id in (
        app_module.assistant.id,
        app_module.coding_agent.id,
        app_module.report_agent.id,
    ):
        response = await client.post(f"/agents/{agent_id}/runs", json={})

        assert response.status_code == 404
        assert response.json() == {"error": "agent_run_route_disabled"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/run-1/continue",
        "/run-1/cancel",
        "/run-1/resume",
    ],
)
async def test_direct_team_run_routes_are_disabled(client, suffix):
    response = await client.post(
        f"/teams/{app_module.assistant_team.id}/runs{suffix}",
        json={},
    )

    assert response.status_code == 404
    assert response.json() == {"error": "team_run_route_disabled"}


class ClosingEventStream:
    def __init__(self, events):
        self.events = iter(events)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.events)
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_public_config_and_protected_routes(client):
    config = await client.get("/config")
    assert config.status_code == 200
    assert set(config.json()) == {
        "protocol",
        "bundle_version",
        "command_catalog_hash",
        "skills",
        "limits",
    }
    assert config.json()["limits"] == {
        "run_request_bytes": 2 * 1024 * 1024,
        "workspace_upload_request_bytes": 202 * 1024 * 1024,
        "workspace_file_bytes": 200 * 1024 * 1024,
        "json_mutation_request_bytes": 64 * 1024,
    }

    workspace = await client.get(
        "/workspace/files",
        params={"threadId": "thread-1"},
        headers={"X-AGUI-Thread": "thread-1"},
    )
    assert workspace.status_code == 401

    run = await client.post(
        "/agui",
        json={"threadId": "body-thread"},
        headers={
            "X-AGUI-Thread": "header-thread",
            "X-AGUI-Capability": capability("header-thread"),
        },
    )
    assert run.status_code == 403
    assert run.json() == {"error": "capability_thread_mismatch"}

    missing_thread = await client.post(
        "/agui",
        json={"threadId": "thread-1"},
        headers={"X-AGUI-Capability": capability()},
    )
    assert missing_thread.status_code == 400
    assert missing_thread.json() == {"error": "thread_header_required"}


@pytest.mark.anyio
async def test_branch_requires_controlled_props_and_matching_source_capability(client):
    base_payload = {
        "threadId": "target-thread",
        "runId": "request-run",
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    headers = {
        "X-AGUI-Thread": "target-thread",
        "X-AGUI-Capability": capability("target-thread"),
    }

    arbitrary = await client.post(
        "/agui",
        json={**base_payload, "forwardedProps": {"user_id": "admin"}},
        headers=headers,
    )
    assert arbitrary.status_code == 403
    assert arbitrary.json() == {"error": "forwarded_props_invalid"}

    branch_payload = {
        **base_payload,
        "forwardedProps": {
            "branch": {
                "sourceThreadId": "source-thread",
                "sourceRunId": "source-run",
                "targetMessageId": "answer-1",
            }
        },
    }
    missing_source = await client.post("/agui", json=branch_payload, headers=headers)
    assert missing_source.status_code == 401

    mismatched = await client.post(
        "/agui",
        json=branch_payload,
        headers={
            **headers,
            "X-AGUI-Source-Capability": capability("source-thread", user=8),
        },
    )
    assert mismatched.status_code == 403
    assert mismatched.json() == {"error": "branch_identity_mismatch"}


@pytest.mark.anyio
async def test_limited_json_body_is_replayed_to_workspace_route(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module.workspace_service, "destroy", lambda _thread: False)

    response = await client.request(
        "DELETE",
        "/workspace/sandbox",
        json={"threadId": "thread-1"},
        headers={
            "X-AGUI-Thread": "thread-1",
            "X-AGUI-Capability": capability(),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"ok": True, "deleted": False}


@pytest.mark.anyio
async def test_http_上传保持覆盖路径的兼容调用语义(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    calls = []

    def upload(thread, path, content):
        calls.append((thread, path, content))
        return {"path": path, "size": len(content), "status": "synced"}

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module.workspace_service, "upload", upload)
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    first = await client.post(
        "/workspace/upload",
        data={"threadId": "thread-1", "path": "报告.txt"},
        files={"file": ("报告.txt", b"first", "text/plain")},
        headers=headers,
    )
    second = await client.post(
        "/workspace/upload",
        data={"threadId": "thread-1", "path": "报告.txt"},
        files={"file": ("报告.txt", b"second", "text/plain")},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [
        ("thread-1", "报告.txt", b"first"),
        ("thread-1", "报告.txt", b"second"),
    ]


@pytest.mark.anyio
async def test_workspace_files_post_creates_without_overwrite(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    calls = []

    def create_file(thread, path, content):
        calls.append((thread, path, content))
        return {"path": path, "size": len(content), "status": "synced"}

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module.workspace_service, "create_file_locked", create_file)
    response = await client.post(
        "/workspace/files",
        data={"threadId": "thread-1", "path": "exports/员工.csv"},
        files={"file": ("员工.csv", b"name\nAlice\n", "text/csv")},
        headers={
            "X-AGUI-Thread": "thread-1",
            "X-AGUI-Capability": capability(),
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "ok": True,
        "entry": {"path": "exports/员工.csv", "size": 11, "status": "synced"},
    }
    assert calls == [("thread-1", "exports/员工.csv", b"name\nAlice\n")]


@pytest.mark.anyio
async def test_workspace_files_post_maps_conflict_size_and_backend_errors(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    monkeypatch.setattr(
        app_module.workspace_service,
        "create_file_locked",
        lambda *_args: (_ for _ in ()).throw(app_module.WorkspacePathConflict()),
    )
    conflict = await client.post(
        "/workspace/files",
        data={"threadId": "thread-1", "path": "exports/员工.csv"},
        files={"file": ("员工.csv", b"content", "text/csv")},
        headers=headers,
    )

    monkeypatch.setattr(app_module, "WORKSPACE_FILE_BYTES", 4)
    too_large = await client.post(
        "/workspace/files",
        data={"threadId": "thread-1", "path": "exports/员工.csv"},
        files={
            "file": (
                "员工.csv",
                b"12345",
                "text/csv",
            )
        },
        headers=headers,
    )

    monkeypatch.setattr(
        app_module.workspace_service,
        "create_file_locked",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("daytona unavailable")),
    )
    monkeypatch.setattr(app_module, "WORKSPACE_FILE_BYTES", 200 * 1024 * 1024)
    failed = await client.post(
        "/workspace/files",
        data={"threadId": "thread-1", "path": "exports/员工.csv"},
        files={"file": ("员工.csv", b"content", "text/csv")},
        headers=headers,
    )

    assert conflict.status_code == 409
    assert conflict.json() == {"error": "workspace_path_conflict"}
    assert too_large.status_code == 413
    assert too_large.json() == {"error": "export_file_too_large"}
    assert failed.status_code == 502
    assert failed.json() == {"error": "workspace_upload_failed"}


@pytest.mark.anyio
async def test_workspace_delete_requires_a_strict_recursive_boolean(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    calls = []
    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(
        app_module.workspace_service,
        "delete_file",
        lambda thread, path, recursive: calls.append((thread, path, recursive)),
    )
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    invalid = await client.request(
        "DELETE",
        "/workspace/file",
        json={"threadId": "thread-1", "path": "资料", "recursive": "false"},
        headers=headers,
    )
    extra = await client.request(
        "DELETE",
        "/workspace/file",
        json={"threadId": "thread-1", "path": "资料", "recursive": False, "force": True},
        headers=headers,
    )
    valid = await client.request(
        "DELETE",
        "/workspace/file",
        json={"threadId": "thread-1", "path": "资料", "recursive": False},
        headers=headers,
    )

    assert invalid.status_code == 422
    assert extra.status_code == 422
    assert valid.status_code == 200
    assert calls == [("thread-1", "资料", False)]


@pytest.mark.anyio
async def test_workspace_download_encodes_a_unicode_filename(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(
        app_module.workspace_service,
        "file_bytes",
        lambda _thread, _path: (b"content", "text/plain"),
    )

    response = await client.get(
        "/workspace/file",
        params={"threadId": "thread-1", "path": "资料/报告.txt", "download": "true"},
        headers={
            "X-AGUI-Thread": "thread-1",
            "X-AGUI-Capability": capability(),
        },
    )

    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == (
        "attachment; filename=\"download.txt\"; filename*=UTF-8''%E6%8A%A5%E5%91%8A.txt"
    )


@pytest.mark.anyio
async def test_invalid_capability_is_rejected_before_large_run_body(client):

    response = await client.post(
        "/agui",
        content=b"x" * (app_module.MAX_RUN_REQUEST_BYTES + 1),
        headers={"X-AGUI-Thread": "thread-1", "X-AGUI-Capability": "invalid"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_chunked_request_limits_return_413(client, monkeypatch):
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    async def chunks():
        yield b"x" * app_module.MAX_RUN_REQUEST_BYTES
        yield b"x"

    response = await client.post(
        "/agui",
        content=chunks(),
        headers=headers,
    )
    mutation = await client.request(
        "DELETE",
        "/workspace/file",
        content=b"x" * (app_module.MAX_JSON_MUTATION_REQUEST_BYTES + 1),
        headers=headers,
    )

    monkeypatch.setattr(app_module, "MAX_WORKSPACE_UPLOAD_REQUEST_BYTES", 4)

    async def upload_chunks():
        yield b"x" * app_module.MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
        yield b"x"

    upload = await client.post(
        "/workspace/upload",
        content=upload_chunks(),
        headers=headers,
    )

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}
    assert mutation.status_code == 413
    assert upload.status_code == 413


@pytest.mark.anyio
async def test_ready_reports_all_required_checks(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(
        app_module,
        "_readiness_checks",
        lambda _context: {
            "postgresql": True,
            "sandbox_registry": True,
            "hmac": True,
        },
    )
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    monkeypatch.setattr(
        app_module,
        "_readiness_checks",
        lambda _context: {
            "postgresql": True,
            "sandbox_registry": False,
            "hmac": True,
        },
    )
    unavailable = await client.get("/ready")
    assert unavailable.status_code == 503
    assert unavailable.json()["status"] == "not_ready"


@pytest.mark.anyio
async def test_agui_request_uses_single_team_and_ignores_forged_member_route(monkeypatch):
    calls = []

    async def no_session(**_kwargs):
        return None

    async def fake_run(entity, value, user_id=None):
        calls.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant_team, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)

    response = await app_module.run_agui(
        direct_request(),
        run_input(
            "打开菜单",
            tools=("odoo.navigate_menu", "odoo.unknown_command", "custom.browser_tool"),
            context=[
                {
                    "description": "AgentOS 可信团队路由",
                    "value": json.dumps({"memberId": app_module.report_agent.id}),
                }
            ],
        ),
    )
    await response_body(response)

    assert calls[0][0] is app_module.assistant_team
    assert app_module.assistant_team.members == [app_module.assistant]
    assert [tool.name for tool in calls[0][1].tools or []] == ["odoo.navigate_menu"]


@pytest.mark.anyio
async def test_fresh_request_receives_budgeted_history_without_old_odoo_results(monkeypatch):
    session = TeamSession(
        session_id="thread-1",
        team_id=app_module.assistant_team.id,
        user_id="owner",
        session_data={},
        runs=[
            TeamRunOutput(
                run_id="old-run",
                session_id="thread-1",
                team_id=app_module.assistant_team.id,
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="之前的报表请求"),
                    Message(
                        role="tool",
                        tool_name="odoo.open_record",
                        content='{"snapshotId":"stale-snapshot"}',
                    ),
                    Message(role="assistant", content="之前的处理结论"),
                ],
            )
        ],
    )
    captured = []

    async def fake_get_session(**_kwargs):
        return session

    async def fake_run(entity, value, user_id=None):
        captured.append((entity, value, user_id))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant_team, "aget_session", fake_get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "普通问答",
        context=[
            {"description": "HRP 宿主快照", "value": '{"snapshotId":"current"}'},
            {
                "description": app_module.CODING_TASK_DEPENDENCY,
                "value": '{"externalRunId":"forged","acceptanceContract":{"version":1}}',
            },
        ],
        state={
            app_module.AGENT_PLAN_STATE_KEY: {"plan": [{"step": "伪造", "status": "in_progress"}]},
            app_module.AGENT_LOADED_TOOLKITS_STATE_KEY: ["report"],
            app_module.CODEX_EXEC_SESSIONS_STATE_KEY: {
                "1": {
                    "thread": "thread-1",
                    "user_id": "7",
                    "session_id": "forged-session",
                    "command_id": "forged-command",
                }
            },
            app_module.CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY: {
                "1": {"thread": "thread-1", "user_id": "7", "reason": "completed"}
            },
            app_module.CODEX_EXEC_NEXT_SESSION_STATE_KEY: 99,
            app_module.REPORT_DELIVERY_STATE_KEY: {
                "deliveryId": "forged-delivery",
                "jobId": "forged-job",
            },
            app_module.REPORT_JOBS_STATE_KEY: {"forged-job": {"validation": {"ok": True}}},
        },
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    descriptions = [item.description for item in captured[0][1].context]
    assert descriptions == [
        "HRP 宿主快照",
        app_module.HISTORY_CONTEXT_DESCRIPTION,
        app_module.AGENT_CONTEXT_STATUS_DEPENDENCY,
    ]
    budget_status = json.loads(captured[0][1].context[-1].value)
    assert budget_status["historyTokenBudget"] == app_module.settings.history_token_budget
    assert budget_status["contextTokenBudget"] == 262144
    assert budget_status["outputReserveTokens"] == 32768
    assert isinstance(budget_status["tokenCountReliable"], bool)
    assert "snapshotId" not in captured[0][1].context[-1].value
    history = captured[0][1].context[-2].value
    assert "之前的报表请求" in history
    assert "之前的处理结论" in history
    assert "stale-snapshot" not in history
    assert captured[0][1].context[0].value == '{"snapshotId":"current"}'
    assert captured[0][1].state == {}


@pytest.mark.anyio
async def test_resume_request_does_not_reload_or_reinject_budgeted_history(monkeypatch):
    loaded = False
    captured = []

    async def get_session(**_kwargs):
        nonlocal loaded
        loaded = True
        return None

    async def fake_run(entity, value, user_id=None):
        captured.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant_team, "aget_session", get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        messages=[
            {"id": "user-1", "role": "user", "content": "继续"},
            {"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-1"},
        ],
        context=[
            {"description": app_module.HISTORY_CONTEXT_DESCRIPTION, "value": "client-history"},
            {"description": "HRP 宿主快照", "value": "current"},
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    assert loaded is False
    assert captured[0][0] is app_module.assistant_team
    assert [item.description for item in captured[0][1].context] == ["HRP 宿主快照"]


@pytest.mark.anyio
async def test_selected_report_skill_routes_to_report_agent(monkeypatch):
    calls = []

    async def fake_run(entity, value, user_id=None):
        calls.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        json.dumps(
            {
                "version": "1",
                "reportGoal": "生成报表",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ),
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            }
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    assert calls[0][0] is app_module.report_agent
    assert app_module.assistant_team.members == [app_module.assistant]
    assert calls[0][1].messages[-1].content == "生成报表"


@pytest.mark.anyio
async def test_selected_report_skill_keeps_report_streaming_events(monkeypatch):
    async def fake_run(_entity, _value, user_id=None):
        yield TextMessageStartEvent(message_id="candidate")
        yield TextMessageContentEvent(message_id="candidate", delta="unaccepted report")
        yield TextMessageEndEvent(message_id="candidate")
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    response = await app_module.run_agui(
        direct_request(),
        run_input(
            json.dumps(
                {
                    "version": "1",
                    "reportGoal": "生成报表",
                    "period": {"start": "2025-01-01", "end": "2025-12-31"},
                }
            ),
            context=[
                {
                    "description": "已选智能体技能",
                    "value": '[{"id":"report","name":"report"}]',
                }
            ],
        ),
    )

    body = await response_body(response)

    assert "unaccepted report" in body


@pytest.mark.anyio
async def test_sse_heartbeat_is_emitted_while_source_is_idle(monkeypatch):
    monkeypatch.setattr(app_module, "SSE_HEARTBEAT_SECONDS", 0.01)

    async def delayed_source():
        await asyncio.sleep(0.025)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    events = [event async for event in app_module._with_sse_heartbeats(delayed_source())]

    assert events[:-1] == [None, None]
    assert events[-1].type == EventType.RUN_FINISHED


@pytest.mark.anyio
async def test_cancel_endpoint_is_capability_bound_and_idempotent(
    client,
    monkeypatch,
    tmp_path,
):
    context = app_module.base_app.state.agentos_context
    current = service(tmp_path)
    sandbox = current.sandbox_for("thread-1")
    workspace = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    test_context = replace(context, workspace_service=workspace)
    workflow_probes = []

    async def cancel_report(**kwargs):
        workflow_probes.append(kwargs["probe_storage"])
        return None

    monkeypatch.setattr(
        test_context.report_workflow_controller,
        "cancel_external",
        cancel_report,
    )
    monkeypatch.setattr(app_module.base_app.state, "agentos_context", test_context)
    owner = app_module.capability_user_id(
        SimpleNamespace(
            database="odoo",
            user=7,
            company=3,
            odoo_session="a" * 64,
        )
    )
    task = await test_context.coding_repository.create_task(
        external_run_id="cancel-run",
        owner_user_id=owner,
        thread_id="thread-1",
        agent_id="coding-agent",
        sandbox_id=sandbox.id,
        deadline_at=utcnow() + timedelta(hours=24),
    )
    task = await test_context.coding_repository.bind_initial_run(
        task.external_run_id,
        "internal-0",
    )
    daytona_session_id = f"agui-exec-{'a' * 32}"
    sandbox.process.create_session(daytona_session_id)
    await test_context.coding_repository.reserve_execution(
        execution_id="a" * 32,
        external_run_id=task.external_run_id,
        internal_run_id="internal-0",
        owner_user_id=owner,
        thread_id="thread-1",
        sandbox_id=sandbox.id,
        daytona_session_id=daytona_session_id,
        mutation_sequence=0,
    )

    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }
    cancelled = await client.post(
        "/agui/cancel",
        json={"threadId": "thread-1", "runId": "cancel-run"},
        headers=headers,
    )
    repeated = await client.post(
        "/agui/cancel",
        json={"threadId": "thread-1", "runId": "cancel-run"},
        headers=headers,
    )
    missing_capability = await client.post(
        "/agui/cancel",
        json={"threadId": "thread-1", "runId": "cancel-run"},
        headers={"X-AGUI-Thread": "thread-1"},
    )

    assert cancelled.json() == {"ok": True, "status": "cancelled"}
    assert repeated.json() == {
        "ok": True,
        "status": "cancelled",
        "status_is_cached": True,
    }
    assert missing_capability.status_code == 401
    execution = await test_context.coding_repository.get_execution("a" * 32)
    assert execution is not None and execution.status == "terminated"
    assert daytona_session_id not in sandbox.process.sessions

    mismatched = await test_context.coding_repository.create_task(
        external_run_id="mismatched-cancel-run",
        owner_user_id=owner,
        thread_id="thread-1",
        agent_id="coding-agent",
        sandbox_id="different-sandbox",
        deadline_at=utcnow() + timedelta(hours=24),
    )
    mismatch_response = await client.post(
        "/agui/cancel",
        json={"threadId": "thread-1", "runId": mismatched.external_run_id},
        headers=headers,
    )

    assert mismatch_response.status_code == 409
    unchanged = await test_context.coding_repository.get_task(mismatched.external_run_id)
    assert unchanged is not None and unchanged.status == "pending"
    assert workflow_probes == [False, False, False]


@pytest.mark.anyio
async def test_non_report_route_keeps_streaming_text_unchanged(monkeypatch):
    async def no_session(**_kwargs):
        return None

    async def fake_run(entity, value, user_id=None):
        assert entity is app_module.assistant_team
        assert app_module.REPORT_DELIVERY_STATE_KEY not in value.state
        yield TextMessageStartEvent(message_id="assistant-1")
        yield TextMessageContentEvent(message_id="assistant-1", delta="普通回答")
        yield TextMessageEndEvent(message_id="assistant-1")
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant_team, "aget_session", no_session)
    monkeypatch.setattr(app_module.assistant, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)

    response = await app_module.run_agui(direct_request(), run_input("普通问答"))
    body = await response_body(response)

    assert "普通回答" in body


@pytest.mark.anyio
async def test_report_skill_does_not_expose_odoo_client_tools(monkeypatch):
    calls = []

    async def fake_run(entity, value, user_id=None):
        calls.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    response = await app_module.run_agui(
        direct_request(),
        run_input(
            json.dumps(
                {
                    "version": "1",
                    "reportGoal": "生成当前页面报表",
                    "period": {"start": "2025-01-01", "end": "2025-12-31"},
                }
            ),
            tools=("odoo.navigate_menu", "odoo.export_current_view"),
            context=[
                {
                    "description": "已选智能体技能",
                    "value": '[{"id":"report","name":"report"}]',
                }
            ],
        ),
    )
    await response_body(response)

    assert calls[0][0] is app_module.report_agent
    assert app_module.assistant_team.members == [app_module.assistant]
    assert calls[0][1].tools == []


@pytest.mark.anyio
async def test_active_report_workflow_routes_without_repeating_envelope(monkeypatch):
    calls = []

    async def active_session(**_kwargs):
        return AgentSession(
            session_id="thread-1",
            agent_id=app_module.report_agent.id,
            session_data={
                "session_state": {
                    app_module.REPORT_WORKFLOW_CONTROL_STATE_KEY: {"status": "paused"}
                }
            },
        )

    async def fake_run(entity, value, user_id=None):
        calls.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.report_agent, "aget_session", active_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)

    response = await app_module.run_agui(direct_request(), run_input("批准"))
    await response_body(response)

    assert calls[0][0] is app_module.report_agent
    assert calls[0][1].messages[-1].content == "批准"


@pytest.mark.anyio
async def test_raw_reasoning_content_is_not_forwarded_to_sse(monkeypatch):
    async def no_session(**_kwargs):
        return None

    async def fake_run(_entity, _value, user_id=None):
        yield RunStartedEvent(thread_id="thread-1", run_id="run-1")
        yield ReasoningStartEvent(message_id="reasoning-1")
        yield ReasoningMessageContentEvent(
            message_id="reasoning-1",
            delta="raw chain of thought",
        )
        yield RawEvent(event={"reasoning_content": "raw provider reasoning"}, source="agno")
        yield ReasoningEndEvent(message_id="reasoning-1")
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)

    response = await app_module.run_agui(direct_request(), run_input("普通问答"))
    body = await response_body(response)

    assert "REASONING_START" in body
    assert "REASONING_END" in body
    assert "raw chain of thought" not in body
    assert "raw provider reasoning" not in body


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tools", "expected_tools"),
    [
        ((), []),
        (
            ("odoo.navigate_menu", "odoo.apply_filter", "odoo.export_current_view"),
            ["odoo.navigate_menu", "odoo.apply_filter", "odoo.export_current_view"],
        ),
        (
            ("odoo.business.expense.submit",),
            ["odoo.business.expense.submit"],
        ),
        (("odoo.unknown_command",), []),
        (("odoo.business.",), []),
        (("odoo.business.invalid",), []),
        (("custom.browser_tool",), []),
    ],
)
async def test_fresh_request_filters_team_client_tools(monkeypatch, tools, expected_tools):
    calls = []

    async def no_session(**_kwargs):
        return None

    async def fake_run(entity, value, user_id=None):
        calls.append((entity, value))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant_team, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input("处理这个请求", tools=tools)
    response = await app_module.run_agui(direct_request(), value)

    await response_body(response)

    assert calls[0][0] is app_module.assistant_team
    assert [tool.name for tool in calls[0][1].tools or []] == expected_tools


def test_team_client_tool_filter_rejects_unknown_and_custom_tools():
    value = run_input(
        tools=(
            "odoo.navigate_menu",
            "odoo.export_current_view",
            "odoo.business.expense.submit",
            "odoo.business.invalid",
            "odoo.unknown_command",
            "custom.browser_tool",
        )
    )

    filtered = app_module._filter_odoo_client_tools(value)

    assert [tool.name for tool in filtered.tools or []] == [
        "odoo.navigate_menu",
        "odoo.export_current_view",
        "odoo.business.expense.submit",
    ]


@pytest.mark.anyio
async def test_branch_request_keeps_original_branch_path(monkeypatch):
    branch = object()
    calls = []

    async def fake_branch(entity, workspace, value, spec, user_id):
        calls.append((entity, workspace, value, spec, user_id))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    async def unexpected_run(*_args, **_kwargs):
        raise AssertionError("分支请求不应进入普通运行路径")
        yield

    monkeypatch.setattr(app_module, "run_branch", fake_branch)
    monkeypatch.setattr(app_module, "run_entity", unexpected_run)
    value = run_input()
    response = await app_module.run_agui(direct_request(branch), value)

    await response_body(response)

    assert calls[0][:4] == (
        app_module.assistant_team,
        app_module.workspace_service,
        value,
        branch,
    )


@pytest.mark.anyio
async def test_team_delegation_events_are_hidden():
    stream = ClosingEventStream(
        [
            RunStartedEvent(thread_id="thread-1", run_id="run-1"),
            ToolCallStartEvent(
                tool_call_id="delegate-1",
                tool_call_name="delegate_task_to_member",
            ),
            ToolCallArgsEvent(tool_call_id="delegate-1", delta="{}"),
            ToolCallEndEvent(tool_call_id="delegate-1"),
            ToolCallResultEvent(
                message_id="delegate-1",
                tool_call_id="delegate-1",
                content="done",
            ),
            ToolCallStartEvent(
                tool_call_id="menu-1",
                tool_call_name="odoo.navigate_menu",
            ),
            RunFinishedEvent(thread_id="thread-1", run_id="run-1"),
        ]
    )

    events = [event async for event in app_module._hide_team_delegation_events(stream)]

    assert [event.type for event in events] == [
        EventType.RUN_STARTED,
        EventType.TOOL_CALL_START,
        EventType.RUN_FINISHED,
    ]
