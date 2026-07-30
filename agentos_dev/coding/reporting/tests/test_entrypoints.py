import importlib
import inspect

import pytest
from agno.run import RunContext

from agentos_dev.coding.reporting import agentos as report_agentos
from agentos_dev.coding.reporting.contract import ReportRequestEnvelope
from agentos_dev.coding.reporting.controller import ReportWorkflowToolkit
from agentos_dev.coding.reporting.entrypoints import bind_server_envelope
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.settings import AgentSettings


def test_report_entrypoints_import_independently():
    for name in (
        "agentos_dev.coding.reporting",
        "agentos_dev.coding.reporting.cli",
        "agentos_dev.coding.reporting.agentos",
        "agentos_dev.coding.reporting.__main__",
    ):
        if name.endswith(".__main__"):
            continue
        assert importlib.import_module(name) is not None


def test_report_agentos_registers_only_facade(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    database = object()
    context = type(
        "Context",
        (),
        {
            "database": database,
            "workspace_service": object(),
            "coding_repository": object(),
        },
    )()
    coding_worker = type("Agent", (), {"skills": object()})()
    report_worker = type("Agent", (), {"skills": object()})()
    facade = object()
    captured = {}

    class FakeRuntime:
        workflow = object()
        cleanup_cancelled = object()

        def __init__(self, **_kwargs):
            pass

    class FakeAgentOS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(report_agentos, "create_cli_context", lambda _settings: context)
    monkeypatch.setattr(report_agentos, "create_cli_agent", lambda _context: coding_worker)
    monkeypatch.setattr(
        report_agentos, "create_report_worker", lambda *_args, **_kwargs: report_worker
    )
    monkeypatch.setattr(report_agentos, "CodingTaskSupervisor", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(report_agentos, "CodingExecutionKernel", lambda *_args: object())
    monkeypatch.setattr(report_agentos, "ReportWorkflowRuntime", FakeRuntime)
    monkeypatch.setattr(
        report_agentos, "ReportWorkflowController", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(report_agentos, "create_report_agent", lambda *_args: facade)
    monkeypatch.setattr(
        report_agentos,
        "load_configured_report_source_registry",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        report_agentos.SkillValidatorRegistry,
        "from_skills",
        lambda _skills: object(),
    )
    monkeypatch.setattr(report_agentos, "AgentOS", FakeAgentOS)
    monkeypatch.setattr(report_agentos, "ReportAGUI", lambda **kwargs: kwargs)

    report_agentos.create_agentos(settings)

    assert captured["agents"] == [facade]
    assert report_worker not in captured["agents"]
    assert coding_worker not in captured["agents"]
    assert captured["interfaces"] == [{"agent": facade}]


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
async def test_report_workflow自然语言由模型参数转换且保留输入原文():
    captured = {}

    class FakeController:
        async def start(self, envelope, run_context):
            captured["envelope"] = envelope
            captured["run_context"] = run_context
            return {"status": "paused"}

    toolkit = ReportWorkflowToolkit(FakeController())
    goal = "出一份瑞金医院2025年整体运营分析报告，涵盖收入，预算，成本，工作量的分析"
    run_context = RunContext(run_id="run-text", session_id="thread-text", session_state={})

    result = await toolkit.report_workflow_start_from_text(
        report_goal=goal,
        period_start="2025-01-01",
        period_end="2025-12-31",
        run_context=run_context,
    )

    assert result == {"status": "paused"}
    assert captured["envelope"].report_goal == goal
    assert captured["envelope"].period.model_dump(mode="json") == {
        "start": "2025-01-01",
        "end": "2025-12-31",
    }
    assert captured["envelope"].source_ids is None
    assert captured["run_context"] is run_context
