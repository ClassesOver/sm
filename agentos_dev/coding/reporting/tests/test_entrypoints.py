import importlib
import inspect
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from fastapi import APIRouter
from fastapi.exceptions import HTTPException

from agentos_dev.coding.reporting import agentos as report_agentos
from agentos_dev.coding.reporting.contract import ReportRequestEnvelope
from agentos_dev.coding.reporting.controller import ReportWorkflowController, ReportWorkflowToolkit
from agentos_dev.coding.reporting.entrypoints import bind_server_envelope
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.settings import AgentSettings


def test_report_entrypoints_import_independently():
    for name in (
        "agentos_dev.coding.reporting",
        "agentos_dev.coding.reporting.cli",
        "agentos_dev.coding.reporting.cli_v2",
        "agentos_dev.coding.reporting.agentos",
        "agentos_dev.coding.reporting.__main__",
    ):
        if name.endswith(".__main__"):
            continue
        assert importlib.import_module(name) is not None


def test_report_entrypoints_do_not_import_coding_product_entrypoints():
    script = """
import json
import sys
import agentos_dev.coding.reporting.cli
import agentos_dev.coding.reporting.agentos
print(json.dumps(sorted(
    name for name in sys.modules
    if name in {
        'agentos_dev.coding.agent',
        'agentos_dev.coding.cli',
        'agentos_dev.coding.agentos',
        'agentos_dev.coding.supervisor',
        'agentos_dev.coding.executor',
    }
)))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_report_agentos_registers_reporting_agent_and_shared_workflow(monkeypatch):
    settings = AgentSettings.from_environment(
        {
            "AGENT_CODING_ENABLE_THINKING": "true",
            "AGENT_REPORT_CODING_ENABLE_THINKING": "false",
            "AGENT_REPORT_ENABLE_THINKING": "true",
            "JWT_VERIFICATION_KEY": "test-key",
        },
        load_env_file=False,
    )
    database = SimpleNamespace(db_engine=object())
    context = type(
        "Context",
        (),
        {
            "database": database,
            "workspace_service": object(),
        },
    )()
    report_worker = type("Agent", (), {"skills": object()})()
    reporting_agent = object()
    workflows = []
    controllers = []
    captured = {}
    worker_kwargs = {}

    class FakeRuntime:
        cleanup_cancelled = object()

        def __init__(self, **_kwargs):
            pass

        def workflow(self):
            workflow = object()
            workflows.append(workflow)
            return workflow

    class FakeAgentOS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(report_agentos, "create_execution_context", lambda _settings: context)
    monkeypatch.setattr(report_agentos, "close_execution_resources", lambda *_args: None)

    def create_report_worker(*_args, **kwargs):
        worker_kwargs.update(kwargs)
        return report_worker

    monkeypatch.setattr(report_agentos, "create_report_worker", create_report_worker)
    monkeypatch.setattr(
        report_agentos, "create_report_agent", lambda _worker, _controller: reporting_agent
    )

    def create_controller(*_args, **_kwargs):
        controller = object()
        controllers.append(controller)
        return controller

    monkeypatch.setattr(report_agentos, "ReportWorkflowController", create_controller)
    monkeypatch.setattr(report_agentos, "TaskExecutionRepository", lambda _db: object())
    monkeypatch.setattr(report_agentos, "TaskExecutionKernel", lambda *_args: object())
    monkeypatch.setattr(report_agentos, "ReportTaskRunner", lambda *_args: object())
    monkeypatch.setattr(report_agentos, "ReportWorkflowRuntime", FakeRuntime)
    monkeypatch.setattr(
        report_agentos,
        "SqlAlchemyDownloadGrantRepository",
        lambda _engine: SimpleNamespace(create_schema=lambda: None),
    )
    monkeypatch.setattr(report_agentos, "ReportDownloadGrantService", lambda _repository: object())
    monkeypatch.setattr(
        report_agentos, "WorkspaceReportDownloadHttpService", lambda *_args: object()
    )
    monkeypatch.setattr(
        report_agentos,
        "create_workspace_report_download_router",
        lambda *_args, **_kwargs: APIRouter(),
    )
    monkeypatch.setattr(
        report_agentos,
        "load_configured_report_source_registry",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(report_agentos, "AgentOS", FakeAgentOS)
    monkeypatch.setattr(report_agentos, "ReportAGUI", lambda **kwargs: kwargs)

    report_agentos.create_agentos(settings)

    assert captured["agents"] == [reporting_agent]
    assert captured["workflows"] == [workflows[0]]
    assert report_worker not in captured["agents"]
    assert captured["interfaces"] == [{"agent": reporting_agent}]
    assert worker_kwargs["report_coding_enable_thinking"] is False
    assert captured["authorization"] is True
    assert captured["authorization_config"].user_isolation is True
    assert len(controllers) == 1
    included_routes = [
        route
        for item in captured["base_app"].routes
        for route in getattr(getattr(item, "original_router", None), "routes", ())
    ]
    assert any(route.path == "/agui/cancel" for route in included_routes)


@pytest.mark.anyio
async def test_report_agentos取消路由按jwt用户和thread取消持久化workflow(monkeypatch):
    captured = {}

    class Controller:
        async def cancel_external(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True, "status": "cancelled"}

    monkeypatch.setattr(report_agentos, "resolve_run_user_id", lambda _request: "user-1")
    router = report_agentos._standalone_cancel_router(Controller())
    route = next(item for item in router.routes if item.path == "/agui/cancel")

    result = await route.endpoint(
        SimpleNamespace(),
        report_agentos.ReportCancelPayload(threadId="thread-1", runId="run-1"),
    )

    assert result == {"ok": True, "status": "cancelled"}
    assert captured == {
        "external_run_id": "run-1",
        "thread_id": "thread-1",
        "user_id": "user-1",
        "probe_storage": True,
    }


@pytest.mark.anyio
async def test_report_agentos取消路由缺少认证用户时返回401(monkeypatch):
    class Controller:
        async def cancel_external(self, **_kwargs):
            raise AssertionError("缺少认证用户时不应查询 Workflow。")

    monkeypatch.setattr(report_agentos, "resolve_run_user_id", lambda _request: None)
    router = report_agentos._standalone_cancel_router(Controller())
    route = next(item for item in router.routes if item.path == "/agui/cancel")

    with pytest.raises(HTTPException) as captured:
        await route.endpoint(
            SimpleNamespace(),
            report_agentos.ReportCancelPayload(threadId="thread-1", runId="run-1"),
        )

    assert captured.value.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("controller_result", "controller_error", "status_code", "detail"),
    [
        (None, None, 404, "report_workflow_not_found"),
        (
            None,
            ReportingError("report_workflow_cancel_failed", "取消失败。"),
            409,
            "report_workflow_cancel_failed",
        ),
    ],
)
async def test_report_agentos取消路由映射持久化结果(
    monkeypatch,
    controller_result,
    controller_error,
    status_code,
    detail,
):
    class Controller:
        async def cancel_external(self, **_kwargs):
            if controller_error is not None:
                raise controller_error
            return controller_result

    monkeypatch.setattr(report_agentos, "resolve_run_user_id", lambda _request: "user-1")
    router = report_agentos._standalone_cancel_router(Controller())
    route = next(item for item in router.routes if item.path == "/agui/cancel")

    with pytest.raises(HTTPException) as captured:
        await route.endpoint(
            SimpleNamespace(),
            report_agentos.ReportCancelPayload(threadId="thread-1", runId="run-1"),
        )

    assert captured.value.status_code == status_code
    assert captured.value.detail == detail


def test_report_agentos_components为controller按运行创建workflow(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = SimpleNamespace(database=object(), workspace_service=object())
    created = []
    captured = {}

    class FakeRuntime:
        cleanup_cancelled = None

        def __init__(self, **_kwargs):
            pass

        def workflow(self):
            value = object()
            created.append(value)
            return value

    monkeypatch.setattr(
        report_agentos,
        "create_report_worker",
        lambda *_args, **_kwargs: SimpleNamespace(skills=object()),
    )
    monkeypatch.setattr(report_agentos, "TaskExecutionRepository", lambda _db: object())
    monkeypatch.setattr(report_agentos, "TaskExecutionKernel", lambda *_args: object())
    monkeypatch.setattr(report_agentos, "ReportTaskRunner", lambda *_args: object())
    monkeypatch.setattr(report_agentos, "ReportWorkflowRuntime", FakeRuntime)
    monkeypatch.setattr(
        report_agentos, "load_configured_report_source_registry", lambda *_args: object()
    )
    monkeypatch.setattr(
        report_agentos, "load_configured_reporting_profiles", lambda *_args: object()
    )

    def controller(factory, **_kwargs):
        captured["factory"] = factory
        return object()

    monkeypatch.setattr(report_agentos, "ReportWorkflowController", controller)
    monkeypatch.setattr(report_agentos, "create_report_agent", lambda *_args: object())

    _agent, prototype, _worker, _runtime, controller_instance = (
        report_agentos.create_report_agentos_components(context, settings)
    )

    first = captured["factory"]()
    second = captured["factory"]()
    assert prototype is created[0]
    assert first is created[1]
    assert second is created[2]
    assert first is not second
    assert controller_instance is not None


def test_report_agentos缺少jwt密钥时拒绝启动():
    settings = AgentSettings.from_environment({}, load_env_file=False)

    with pytest.raises(ValueError, match="JWT_VERIFICATION_KEY"):
        report_agentos.create_agentos(settings)


def test_report_agentos_main_uses_import_string_for_workers_and_reload(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    captured = {}

    class FakeAgentOS:
        def serve(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        report_agentos.AgentSettings,
        "from_environment",
        lambda: settings,
    )
    monkeypatch.setattr(report_agentos, "create_agentos", lambda _settings: FakeAgentOS())

    report_agentos.main()

    assert captured["app"] == "agentos_dev.coding.reporting.server:app"
    assert captured["workers"] == settings.workers
    assert captured["reload"] == settings.reload


@pytest.mark.anyio
async def test_report_workflow_start只消费服务端绑定envelope():
    captured = {}

    class FakeController:
        async def start(self, envelope, run_context):
            captured["envelope"] = envelope
            captured["run_context"] = run_context
            return {"status": "paused"}

    toolkit = ReportWorkflowToolkit(FakeController())
    signature = inspect.signature(toolkit.report_workflow_start)
    assert set(signature.parameters) == {"run_context"}

    envelope = ReportRequestEnvelope.from_untrusted(
        {
            "version": "1",
            "reportGoal": "分析经营情况",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["operations"],
        }
    )
    run_context = RunContext(run_id="run-1", session_id="thread-1", session_state={})

    with bind_server_envelope(envelope):
        result = await toolkit.report_workflow_start(run_context=run_context)

    assert result == {"status": "paused"}
    assert captured == {"envelope": envelope, "run_context": run_context}


@pytest.mark.anyio
async def test_report_workflow_start缺少服务端绑定envelope时返回稳定错误():
    toolkit = ReportWorkflowToolkit(object())

    with pytest.raises(ReportingError) as captured:
        await toolkit.report_workflow_start(
            run_context=RunContext(run_id="run-1", session_id="thread-1", session_state={})
        )

    assert captured.value.code == "report_request_invalid"
    assert captured.value.message == "当前消息缺少报表 Envelope。"


@pytest.mark.anyio
async def test_report_workflow自然语言原样交给workflow首步():
    captured = {}

    class FakeController:
        async def start(self, envelope, run_context):
            captured["envelope"] = envelope
            captured["run_context"] = run_context
            return {"status": "paused"}

    toolkit = ReportWorkflowToolkit(FakeController())
    goal = "出一份瑞金医院2025年整体运营分析报告，涵盖收入，预算，成本，工作量的分析"
    run_context = RunContext(run_id="run-text", session_id="thread-text", session_state={})

    result = await toolkit.report_workflow_start_from_prompt(prompt=goal, run_context=run_context)

    assert result == {"status": "paused"}
    assert captured["envelope"].model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "version": "1",
        "prompt": goal,
    }
    assert captured["run_context"] is run_context


def test_controller将期间补充识别为request审核阶段():
    requirement = SimpleNamespace(
        step_name="规范化报表请求",
        confirmation_message=None,
        output_review_message="请补充报表分析期间。",
        step_output=SimpleNamespace(content={"clarificationQuestion": "请明确唯一的分析期间。"}),
        is_resolved=False,
    )
    output = SimpleNamespace(
        active_step_requirements=[requirement],
        step_requirements=[requirement],
    )

    review = ReportWorkflowController(lambda: None)._review(output)

    assert review.stage == "request"
    assert review.preview == {"clarificationQuestion": "请明确唯一的分析期间。"}
