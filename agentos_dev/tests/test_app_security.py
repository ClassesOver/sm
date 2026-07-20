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
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageStartEvent,
    ToolCallStartEvent,
)

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
):
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
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


def test_menu_agents_have_isolated_tool_choices_and_shared_resources():
    assert app_module.search_menu_assistant.tool_choice == {
        "type": "function",
        "function": {"name": "odoo.search_menu"},
    }
    assert app_module.open_menu_assistant.tool_choice == {
        "type": "function",
        "function": {"name": "odoo.open_menu"},
    }
    assert app_module.search_menu_assistant is not app_module.assistant
    assert app_module.open_menu_assistant is not app_module.assistant
    assert app_module.search_menu_assistant.model is app_module.assistant.model
    assert app_module.open_menu_assistant.db is app_module.assistant.db


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

    async def fake_run(entity, _run_input, user_id=None):
        calls.append(entity)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    response = await app_module.run_agui(direct_request(), value)

    await response_body(response)

    assert calls == [app_module.assistant]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "context", "expected_agent"),
    [
        (
            "odoo.search_menu",
            {
                "description": "HRP 菜单导航请求",
                "value": json.dumps({"phase": "search", "requiredFirstTool": "odoo.search_menu"}),
            },
            "search_menu_assistant",
        ),
        (
            "odoo.open_menu",
            {
                "description": "HRP 菜单导航请求",
                "value": json.dumps({"phase": "open", "requiredFirstTool": "odoo.open_menu"}),
            },
            "open_menu_assistant",
        ),
        (
            "odoo.open_menu",
            {
                "description": "已选 HRP 菜单",
                "value": json.dumps({"navigationRequired": True}),
            },
            "open_menu_assistant",
        ),
    ],
)
async def test_menu_navigation_routes_to_forced_agent(
    monkeypatch, tool_name, context, expected_agent
):
    calls = []

    async def fake_run(entity, _run_input, user_id=None):
        calls.append(entity)
        yield RunStartedEvent(thread_id="thread-1", run_id="run-1")
        yield ToolCallStartEvent(tool_call_id="call-1", tool_call_name=tool_name)
        yield RunFinishedEvent(thread_id="thread-1", run_id="run-1")

    monkeypatch.setattr(app_module, "run_entity", fake_run)
    messages = None
    if tool_name == "odoo.open_menu" and context["description"] == "HRP 菜单导航请求":
        messages = [{"id": "tool-1", "role": "tool", "content": "{}", "toolCallId": "call-0"}]
    value = run_input(
        "打开报销单查询",
        tools=(tool_name,),
        context=[context],
        messages=messages,
    )
    response = await app_module.run_agui(direct_request(), value)

    body = await response_body(response)

    assert calls == [getattr(app_module, expected_agent)]
    assert tool_name in body
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
            tools=("odoo.open_menu",),
            context=[
                {
                    "description": "HRP 菜单导航请求",
                    "value": json.dumps(
                        {"phase": "search", "requiredFirstTool": "odoo.search_menu"}
                    ),
                }
            ],
        ),
    )

    body = await response_body(response)

    assert "required_tool_unavailable" in body
    assert "odoo.search_menu" in body


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
        run_input(tools=("odoo.open_menu",)),
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
@pytest.mark.parametrize(
    "first_executable",
    [
        TextMessageStartEvent(message_id="message-1"),
        ToolCallStartEvent(tool_call_id="call-1", tool_call_name="odoo.open_menu"),
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
