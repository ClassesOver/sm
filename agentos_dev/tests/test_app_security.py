import base64
import hashlib
import hmac
import json
import time
from dataclasses import replace
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
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

from agentos_dev import app as app_module

SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(monkeypatch):
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
    message="编辑",
    *,
    tools=(app_module.EDIT_MODE_TOOL,),
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
    for agent_id in ("odoo-assistant", "report-agent"):
        response = await client.post(f"/agents/{agent_id}/runs", json={})

        assert response.status_code == 404
        assert response.json() == {"error": "agent_run_route_disabled"}


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
        "workspace_upload_request_bytes": 12 * 1024 * 1024,
        "workspace_file_bytes": 10 * 1024 * 1024,
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
    monkeypatch.setattr(app_module, "WORKSPACE_FILE_BYTES", 10 * 1024 * 1024)
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
async def test_chunked_request_limits_return_413(client):
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


@pytest.mark.parametrize(
    "message",
    [
        "编辑",
        "修改",
        "进入编辑模式",
        "编辑当前表单",
        "编辑当前单据",
        "修改当前表单",
        "修改当前单据",
        "  编辑。！  ",
    ],
)
def test_explicit_edit_mode_intent_matches_only_complete_short_commands(message):
    assert app_module._is_explicit_edit_mode_request(run_input(message))


@pytest.mark.parametrize(
    "message",
    [
        "修改电话为 13800000000",
        "如何编辑",
        "编辑张三的单据",
        "请编辑",
        "进入编辑模式后修改名称",
    ],
)
def test_explicit_edit_mode_intent_rejects_extended_requests(message):
    assert not app_module._is_explicit_edit_mode_request(run_input(message))


def test_edit_mode_agent_has_isolated_tool_choice_and_shared_resources():
    assert app_module.assistant.tool_choice == "auto"
    assert app_module.edit_mode_assistant.tool_choice == {
        "type": "function",
        "function": {"name": "odoo.enter_edit_mode"},
    }
    assert app_module.edit_mode_assistant is not app_module.assistant
    assert app_module.edit_mode_assistant.model is app_module.assistant.model
    assert app_module.edit_mode_assistant.db is app_module.assistant.db


def test_menu_agent_has_isolated_tool_choice_and_shared_resources():
    assert app_module.menu_navigation_assistant.tool_choice == {
        "type": "function",
        "function": {"name": "odoo.navigate_menu"},
    }
    assert app_module.menu_navigation_assistant is not app_module.assistant
    assert app_module.menu_navigation_assistant.model is app_module.assistant.model
    assert app_module.menu_navigation_assistant.db is app_module.assistant.db


@pytest.mark.anyio
async def test_explicit_edit_request_routes_to_forced_agent(monkeypatch):
    calls = []

    async def fake_run(entity, _run_input, user_id=None):
        calls.append((entity, user_id))
        yield RunStartedEvent(thread_id="thread-1", run_id="run-1")
        yield ToolCallStartEvent(
            tool_call_id="call-1",
            tool_call_name=app_module.EDIT_MODE_TOOL,
        )
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    response = await app_module.run_agui(direct_request(), run_input())

    body = await response_body(response)

    assert len(calls) == 1
    assert calls[0][0] is app_module.edit_mode_assistant
    assert "odoo.enter_edit_mode" in body
    assert "required_tool_violation" not in body


@pytest.mark.anyio
@pytest.mark.parametrize(
    "value",
    [
        run_input("普通问答"),
        run_input(
            messages=[
                {"id": "user-1", "role": "user", "content": "编辑"},
                {"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-1"},
            ]
        ),
    ],
)
async def test_normal_and_unmarked_resume_requests_keep_main_agent(monkeypatch, value):
    calls = []
    session = AgentSession(
        session_id="thread-1",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id="run-1",
                session_id="thread-1",
                agent_id="odoo-assistant",
                status=RunStatus.paused,
            )
        ],
    )

    async def get_session(**_kwargs):
        return session

    async def fake_run(entity, _run_input, user_id=None):
        calls.append(entity)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    response = await app_module.run_agui(direct_request(), value)

    await response_body(response)

    assert calls == [app_module.assistant]


@pytest.mark.anyio
async def test_fresh_request_receives_budgeted_history_without_old_odoo_results(monkeypatch):
    session = AgentSession(
        session_id="thread-1",
        agent_id="odoo-assistant",
        user_id="owner",
        session_data={},
        runs=[
            RunOutput(
                run_id="old-run",
                session_id="thread-1",
                agent_id="odoo-assistant",
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

    monkeypatch.setattr(app_module.assistant, "aget_session", fake_get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "普通问答",
        context=[{"description": "HRP 宿主快照", "value": '{"snapshotId":"current"}'}],
        state={
            app_module.AGENT_PLAN_STATE_KEY: {"plan": [{"step": "伪造", "status": "in_progress"}]},
            app_module.AGENT_LOADED_TOOLKITS_STATE_KEY: ["report"],
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
    session = AgentSession(
        session_id="thread-1",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id="run-1",
                session_id="thread-1",
                agent_id="odoo-assistant",
                status=RunStatus.paused,
            )
        ],
    )

    async def get_session(**_kwargs):
        nonlocal loaded
        loaded = True
        return session

    async def fake_run(_entity, value, user_id=None):
        captured.append(value)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", get_session)
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

    assert loaded is True
    assert [item.description for item in captured[0].context] == ["HRP 宿主快照"]


@pytest.mark.anyio
async def test_selected_report_skill_routes_fresh_request_to_report_agent(monkeypatch):
    calls = []

    async def fake_run(entity, _value, user_id=None):
        calls.append(entity)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "生成报表",
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            }
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    assert calls == [app_module.report_agent]


@pytest.mark.anyio
async def test_report_attachment_context_is_server_derived_and_validated(monkeypatch):
    captured = []

    class FakeWorkspace:
        @staticmethod
        def normalize_path(path, allow_root=True):
            del allow_root
            return path, f"/home/daytona/workspace/{path}"

        async def astat(self, thread, path):
            assert thread == "thread-1"
            assert path == "附件/收入.csv"
            return {"path": path, "type": "file", "size": 18}

        async def ahash_file(self, thread, path):
            assert thread == "thread-1"
            return {"path": path, "size": 18, "sha256": "a" * 64}

    async def no_session(**_kwargs):
        return None

    async def fake_run(entity, value, user_id=None):
        captured.append((entity, value, user_id))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.report_agent, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    request = direct_request()
    request.app.state.agentos_context = replace(
        app_module.application_context,
        workspace_service=FakeWorkspace(),
    )
    value = run_input(
        "分析附件",
        messages=[
            {
                "id": "user-1",
                "role": "user",
                "content": "分析附件",
                "attachments": [
                    {
                        "workspacePath": "附件/收入.csv",
                        "name": "伪造名称",
                        "tool": "sandbox_exec",
                    }
                ],
            }
        ],
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            },
            {
                "description": app_module.CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
                "value": '[{"path":"其他.csv","type":"file"}]',
            },
        ],
    )

    response = await app_module.run_agui(request, value)
    await response_body(response)

    attachment_context = next(
        item
        for item in captured[0][1].context
        if item.description == app_module.CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY
    )
    assert json.loads(attachment_context.value) == [
        {
            "path": "附件/收入.csv",
            "type": "file",
            "size": 18,
            "sha256": "a" * 64,
        }
    ]
    assert "伪造名称" not in attachment_context.value
    assert "sandbox_exec" not in attachment_context.value


@pytest.mark.anyio
async def test_invalid_report_attachment_returns_stable_error_without_running_agent(monkeypatch):
    called = False

    class ChangedWorkspace:
        @staticmethod
        def normalize_path(path, allow_root=True):
            del allow_root
            return path, f"/home/daytona/workspace/{path}"

        async def astat(self, _thread, path):
            return {"path": path, "type": "file", "size": 18}

        async def ahash_file(self, _thread, path):
            return {"path": path, "size": 19, "sha256": "a" * 64}

    async def fake_run(_entity, _value, user_id=None):
        del user_id
        nonlocal called
        called = True
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    request = direct_request()
    request.app.state.agentos_context = replace(
        app_module.application_context,
        workspace_service=ChangedWorkspace(),
    )
    value = run_input(
        "分析附件",
        messages=[
            {
                "id": "user-1",
                "role": "user",
                "content": "分析附件",
                "attachments": [{"workspacePath": "附件/收入.csv"}],
            }
        ],
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            }
        ],
    )

    response = await app_module.run_agui(request, value)
    body = await response_body(response)

    assert called is False
    assert "report_attachment_invalid" in body


@pytest.mark.anyio
async def test_report_resume_uses_agent_from_stored_run(monkeypatch):
    session = AgentSession(
        session_id="thread-1",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id="run-1",
                session_id="thread-1",
                agent_id="report-agent",
                status=RunStatus.paused,
            )
        ],
    )
    calls = []

    async def get_session(**_kwargs):
        return session

    async def fake_run(entity, _value, user_id=None):
        calls.append(entity)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        messages=[
            {"id": "user-1", "role": "user", "content": "生成报表"},
            {"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-1"},
        ]
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    assert calls == [app_module.report_agent]


@pytest.mark.anyio
async def test_resume_fails_closed_when_stored_run_agent_cannot_be_resolved(monkeypatch):
    called = False

    async def no_session(**_kwargs):
        return None

    async def fake_run(_entity, _value, user_id=None):
        del user_id
        nonlocal called
        called = True
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", no_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        messages=[
            {"id": "user-1", "role": "user", "content": "生成报表"},
            {"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-1"},
        ]
    )

    response = await app_module.run_agui(direct_request(), value)
    body = await response_body(response)

    assert called is False
    assert "run_agent_not_found" in body


@pytest.mark.anyio
async def test_report_resume_ignores_fresh_request_menu_routing(monkeypatch):
    session = AgentSession(
        session_id="thread-1",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id="run-1",
                session_id="thread-1",
                agent_id="report-agent",
                status=RunStatus.paused,
            )
        ],
    )
    calls = []

    async def get_session(**_kwargs):
        return session

    async def fake_run(entity, _value, user_id=None):
        calls.append(entity)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", get_session)
    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        messages=[
            {"id": "user-1", "role": "user", "content": "生成报表"},
            {"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-1"},
        ],
        context=[
            {
                "description": app_module.MENU_NAVIGATION_CONTEXT,
                "value": json.dumps({"requiredFirstTool": app_module.MENU_NAVIGATION_TOOL}),
            },
            {
                "description": "已选 HRP 菜单",
                "value": json.dumps({"navigationRequired": True}),
            },
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    await response_body(response)

    assert calls == [app_module.report_agent]


@pytest.mark.anyio
async def test_report_analysis_traceback_is_redacted_from_agui_stream(monkeypatch):
    async def fake_run(entity, _value, user_id=None):
        assert entity is app_module.report_agent
        yield ToolCallStartEvent(
            tool_call_id="analysis-call",
            tool_call_name="report_analyze_dataset",
        )
        yield ToolCallResultEvent(
            message_id="tool-message",
            tool_call_id="analysis-call",
            content=json.dumps(
                {
                    "ok": False,
                    "status": "analysis_failed",
                    "exitCode": 1,
                    "output": "Traceback (most recent call last): secret-path",
                }
            ),
            raw_event={"output": "Traceback: secret-path"},
        )
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "生成报表",
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            }
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    body = await response_body(response)

    assert "Traceback" not in body
    assert "secret-path" not in body
    assert "outputRedacted" in body
    assert "analysis_failed" in body


@pytest.mark.anyio
async def test_report_analysis_traceback_is_redacted_without_start_event(monkeypatch):
    async def fake_run(entity, _value, user_id=None):
        assert entity is app_module.report_agent
        yield ToolCallResultEvent(
            message_id="analysis-call",
            tool_call_id="analysis-call",
            content=json.dumps(
                {
                    "ok": False,
                    "jobId": "job-1",
                    "status": "analysis_failed",
                    "roundCount": 1,
                    "successfulRoundCount": 0,
                    "exitCode": 1,
                    "output": "Traceback (most recent call last): secret-path",
                    "truncated": False,
                }
            ),
            raw_event={"output": "Traceback: secret-path"},
        )
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "生成报表",
        context=[
            {
                "description": "已选智能体技能",
                "value": '[{"id":"report","name":"report"}]',
            }
        ],
    )

    response = await app_module.run_agui(direct_request(), value)
    body = await response_body(response)

    assert "Traceback" not in body
    assert "secret-path" not in body
    assert "outputRedacted" in body
    assert "analysis_failed" in body


@pytest.mark.anyio
async def test_branch_uses_source_run_agent_instead_of_session_agent(monkeypatch):
    branch = SimpleNamespace(source_thread_id="source-thread", source_run_id="source-run")
    session = AgentSession(
        session_id="source-thread",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id="source-run",
                session_id="source-thread",
                agent_id="report-agent",
                status=RunStatus.completed,
            )
        ],
    )
    calls = []

    async def get_session(**_kwargs):
        return session

    async def fake_branch(entity, workspace, value, spec, user_id):
        calls.append((entity, workspace, value, spec, user_id))
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module.assistant, "aget_session", get_session)
    monkeypatch.setattr(app_module, "run_branch", fake_branch)
    request = direct_request(branch)

    response = await app_module.run_agui(request, run_input())
    await response_body(response)

    assert calls[0][0] is app_module.report_agent


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "tools", "extra_context", "expected_agent", "expected_tool"),
    [
        (
            "编辑",
            (app_module.EDIT_MODE_TOOL,),
            (),
            app_module.edit_mode_assistant,
            app_module.EDIT_MODE_TOOL,
        ),
        (
            "打开报销单查询",
            (app_module.MENU_NAVIGATION_TOOL,),
            (
                {
                    "description": "HRP 菜单导航请求",
                    "value": json.dumps({"requiredFirstTool": app_module.MENU_NAVIGATION_TOOL}),
                },
            ),
            app_module.menu_navigation_assistant,
            app_module.MENU_NAVIGATION_TOOL,
        ),
    ],
)
async def test_menu_and_edit_routes_take_priority_over_report_skill(
    monkeypatch,
    message,
    tools,
    extra_context,
    expected_agent,
    expected_tool,
):
    calls = []

    async def fake_run(entity, _value, user_id=None):
        calls.append(entity)
        yield ToolCallStartEvent(tool_call_id="call-1", tool_call_name=expected_tool)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    contexts = [
        {
            "description": "已选智能体技能",
            "value": '[{"id":"report","name":"report"}]',
        },
        *extra_context,
    ]

    response = await app_module.run_agui(
        direct_request(),
        run_input(message, tools=tools, context=contexts),
    )
    await response_body(response)

    assert calls == [expected_agent]


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
    "context",
    [
        {
            "description": "HRP 菜单导航请求",
            "value": json.dumps({"requiredFirstTool": "odoo.navigate_menu"}),
        },
        {
            "description": "已选 HRP 菜单",
            "value": json.dumps({"navigationRequired": True}),
        },
    ],
)
async def test_menu_navigation_routes_to_forced_agent(monkeypatch, context):
    calls = []

    async def fake_run(entity, _run_input, user_id=None):
        calls.append(entity)
        yield RunStartedEvent(thread_id="thread-1", run_id="run-1")
        yield ToolCallStartEvent(
            tool_call_id="call-1", tool_call_name=app_module.MENU_NAVIGATION_TOOL
        )
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    value = run_input(
        "打开报销单查询",
        tools=(app_module.MENU_NAVIGATION_TOOL,),
        context=[context],
    )
    response = await app_module.run_agui(direct_request(), value)

    body = await response_body(response)

    assert calls == [app_module.menu_navigation_assistant]
    assert app_module.MENU_NAVIGATION_TOOL in body
    assert "required_tool_violation" not in body


@pytest.mark.anyio
async def test_menu_navigation_without_required_tool_fails_closed(monkeypatch):
    async def unexpected_run(*_args, **_kwargs):
        raise AssertionError("缺少必需菜单工具时不应调用模型")
        yield

    monkeypatch.setattr(app_module, "run_entity", unexpected_run)
    response = await app_module.run_agui(
        direct_request(),
        run_input(
            "打开报销单查询",
            tools=("odoo.open_record",),
            context=[
                {
                    "description": "HRP 菜单导航请求",
                    "value": json.dumps({"requiredFirstTool": "odoo.navigate_menu"}),
                }
            ],
        ),
    )

    body = await response_body(response)

    assert "required_tool_unavailable" in body
    assert "odoo.navigate_menu" in body


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
        app_module.assistant,
        app_module.workspace_service,
        value,
        branch,
    )


@pytest.mark.anyio
async def test_edit_request_without_declared_tool_fails_closed(monkeypatch):
    async def unexpected_run(*_args, **_kwargs):
        raise AssertionError("缺少必需工具时不应调用模型")
        yield

    monkeypatch.setattr(app_module, "run_entity", unexpected_run)
    response = await app_module.run_agui(
        direct_request(),
        run_input(tools=("odoo.navigate_menu",)),
    )

    body = await response_body(response)

    assert "required_tool_unavailable" in body
    assert "odoo.enter_edit_mode" in body


@pytest.mark.anyio
async def test_required_tool_guard_accepts_status_and_expected_tool():
    stream = ClosingEventStream(
        [
            RunStartedEvent(thread_id="thread-1", run_id="run-1"),
            StateSnapshotEvent(snapshot={}),
            ToolCallStartEvent(
                tool_call_id="call-1",
                tool_call_name=app_module.EDIT_MODE_TOOL,
            ),
            RunFinishedEvent(thread_id="thread-1", run_id="run-1"),
        ]
    )

    events = [
        event
        async for event in app_module._guard_required_tool(
            stream,
            app_module.EDIT_MODE_TOOL,
        )
    ]

    assert [event.type for event in events] == [
        EventType.RUN_STARTED,
        EventType.STATE_SNAPSHOT,
        EventType.TOOL_CALL_START,
        EventType.RUN_FINISHED,
    ]
    assert not stream.closed


@pytest.mark.anyio
async def test_required_tool_guard_accepts_agno_preamble_before_expected_tool():
    stream = ClosingEventStream(
        [
            RunStartedEvent(thread_id="thread-1", run_id="run-1"),
            StateSnapshotEvent(snapshot={}),
            RawEvent(event={"event": "RunStarted"}),
            TextMessageStartEvent(message_id="message-1"),
            TextMessageEndEvent(message_id="message-1"),
            RawEvent(event={"event": "RunContent"}),
            ToolCallStartEvent(
                tool_call_id="call-1",
                tool_call_name=app_module.MENU_NAVIGATION_TOOL,
            ),
            RunFinishedEvent(thread_id="thread-1", run_id="run-1"),
        ]
    )

    events = [
        event
        async for event in app_module._guard_required_tool(
            stream,
            app_module.MENU_NAVIGATION_TOOL,
        )
    ]

    assert [event.type for event in events] == [
        EventType.RUN_STARTED,
        EventType.STATE_SNAPSHOT,
        EventType.RAW,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_END,
        EventType.RAW,
        EventType.TOOL_CALL_START,
        EventType.RUN_FINISHED,
    ]
    assert not stream.closed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "first_executable",
    [
        TextMessageContentEvent(message_id="message-1", delta="先输出文字"),
        ToolCallStartEvent(tool_call_id="call-1", tool_call_name="odoo.open_record"),
        None,
    ],
)
async def test_required_tool_guard_replaces_violations_and_closes_source(first_executable):
    source_events = [RunStartedEvent(thread_id="thread-1", run_id="run-1")]
    if first_executable is not None:
        source_events.append(first_executable)
    stream = ClosingEventStream(source_events)

    events = [
        event
        async for event in app_module._guard_required_tool(
            stream,
            app_module.EDIT_MODE_TOOL,
        )
    ]

    assert [event.type for event in events] == [EventType.RUN_STARTED, EventType.RUN_ERROR]
    assert events[-1].code == "required_tool_violation"
    assert stream.closed
