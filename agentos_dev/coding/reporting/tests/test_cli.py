from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agno.run.base import RunStatus
from agno.workflow import OnReject
from pydantic import BaseModel

from agentos_dev.coding.reporting import cli as cli_module
from agentos_dev.coding.reporting.cli import (
    drive_workflow,
    main,
    parse_report_input,
    read_report_input,
    resolve_requirement,
    run_cli,
)
from agentos_dev.coding.reporting.contract import ReportingWorkflowInput
from agentos_dev.coding.reporting.models import ReportingError


class Requirement:
    def __init__(self, *, step_id: str, content: object):
        self.step_id = step_id
        self.step_name = step_id
        self.output_review_message = "请审核"
        self.step_output = SimpleNamespace(content=content)
        self.confirmed = None
        self.rejection_feedback = None
        self.on_reject = OnReject.retry

    @property
    def is_resolved(self) -> bool:
        return self.confirmed is not None

    def confirm(self) -> None:
        self.confirmed = True

    def reject(self, feedback: str | None = None) -> None:
        self.confirmed = False
        self.rejection_feedback = feedback


def test_report_cli使用run行提交多行输入():
    values = iter(["生成经营分析", "期间：2025年", "/run"])

    assert read_report_input(read=lambda _prompt: next(values)) == "生成经营分析\n期间：2025年"


@pytest.mark.anyio
async def test_report_cli在创建执行上下文前拒绝非法输入(monkeypatch):
    values = iter(["[]", "/run"])
    monkeypatch.setattr(
        cli_module,
        "create_execution_context",
        lambda *_args, **_kwargs: pytest.fail("不得在输入校验前初始化执行上下文"),
    )

    with pytest.raises(ReportingError, match="v1 契约"):
        await run_cli(read=lambda _prompt: next(values), write=lambda _value: None)


def test_report_cli拒绝命令行参数():
    with pytest.raises(SystemExit, match="agentos_dev.coding.reporting.cli"):
        main(["report"])


def test_parse_report_input_accepts_prompt_and_envelope():
    assert parse_report_input("分析2025年经营情况") == {
        "version": "1",
        "prompt": "分析2025年经营情况",
    }


def test_workflow输入默认dump可由agno_session直接序列化():
    value = ReportingWorkflowInput.model_validate(
        {
            "version": "1",
            "reportGoal": "分析2025年经营情况",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
        }
    )

    dumped = value.model_dump(by_alias=True, exclude_none=True)

    assert json.loads(json.dumps(dumped)) == {
        "version": "1",
        "reportGoal": "分析2025年经营情况",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
    }
    assert parse_report_input(
        '{"version":"1","reportGoal":"经营分析","period":{"start":"2025-01-01","end":"2025-12-31"}}'
    ) == {
        "version": "1",
        "reportGoal": "经营分析",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
    }


def test_parse_report_input_rejects_non_object_json():
    with pytest.raises(ReportingError, match="v1 契约"):
        parse_report_input("[]")


def test_resolve_requirement_submits_clarification_as_rejection_feedback():
    requirement = Requirement(
        step_id="normalize-report-request",
        content={"clarificationQuestion": "请明确分析期间。"},
    )

    action = resolve_requirement(
        requirement,
        read=lambda _prompt: "分析2025年",
        write=lambda _value: None,
    )

    assert action == "continue"
    assert requirement.confirmed is False
    assert requirement.rejection_feedback == "分析2025年"


def test_resolve_requirement_selects_agent_with_existing_retry_semantics():
    requirement = Requirement(
        step_id="confirm-source",
        content={"agents": [{"code": "finance", "name": "财务分析"}]},
    )

    action = resolve_requirement(
        requirement,
        read=lambda _prompt: "finance",
        write=lambda _value: None,
    )

    assert action == "continue"
    assert requirement.rejection_feedback == "agentId:finance"


def test_resolve_requirement_cancel_changes_on_reject_mode():
    class Outline(BaseModel):
        title: str

    requirement = Requirement(step_id="generate-outline", content=Outline(title="经营分析"))
    written: list[str] = []

    action = resolve_requirement(
        requirement,
        read=lambda _prompt: "c",
        write=written.append,
    )

    assert action == "cancel"
    assert requirement.on_reject == OnReject.cancel
    assert requirement.confirmed is False
    assert '"title": "经营分析"' in written[1]


@pytest.mark.anyio
async def test_drive_workflow_continues_with_complete_requirements_and_publishes():
    resolved = Requirement(step_id="older-review", content={})
    resolved.confirm()
    active = Requirement(step_id="generate-outline", content={"title": "经营分析"})
    paused = SimpleNamespace(
        status=RunStatus.paused,
        step_requirements=[resolved, active],
        content=None,
    )
    completed = SimpleNamespace(
        status=RunStatus.completed,
        step_requirements=[resolved, active],
        content={"path": "reports/report.pdf", "size": 10, "sha256": "a" * 64},
    )

    class Workflow:
        async def arun(self, report_input, **kwargs):
            assert report_input["prompt"] == "分析2025年经营情况"
            assert kwargs["run_id"] == "run-1"
            return paused

        async def acontinue_run(self, **kwargs):
            assert kwargs["run_response"] is paused
            assert kwargs["step_requirements"] == [resolved, active]
            assert active.confirmed is True
            return completed

    class Runtime:
        async def cleanup_cancelled(self, *_args):
            raise AssertionError("完成状态不应清理取消任务")

    values = iter(["a"])
    result = await drive_workflow(
        Workflow(),
        Runtime(),
        {"version": "1", "prompt": "分析2025年经营情况"},
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        read=lambda _prompt: next(values),
        write=lambda _value: None,
    )

    assert result == {
        "status": "completed",
        "runId": "run-1",
        "sessionId": "session-1",
        "content": {"path": "reports/report.pdf", "size": 10, "sha256": "a" * 64},
    }


@pytest.mark.anyio
async def test_drive_workflow除提纲外自动批准普通审核():
    active = Requirement(step_id="generate-query-candidates", content={"queries": []})
    paused = SimpleNamespace(
        status=RunStatus.paused,
        step_requirements=[active],
        content=None,
    )
    completed = SimpleNamespace(
        status=RunStatus.completed,
        step_requirements=[active],
        content={"path": "reports/report.pdf"},
    )

    class Workflow:
        async def arun(self, _report_input, **_kwargs):
            return paused

        async def acontinue_run(self, **_kwargs):
            assert active.confirmed is True
            return completed

    class Runtime:
        async def cleanup_cancelled(self, *_args):
            raise AssertionError("完成状态不应清理取消任务")

    result = await drive_workflow(
        Workflow(),
        Runtime(),
        {"version": "1", "prompt": "分析2025年经营情况"},
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        read=lambda _prompt: (_ for _ in ()).throw(AssertionError("不应请求人工批准")),
        write=lambda _value: None,
    )

    assert result["status"] == "completed"
