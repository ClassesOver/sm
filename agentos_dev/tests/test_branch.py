import asyncio
from types import SimpleNamespace

import pytest
from ag_ui.core import EventType, RunFinishedEvent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

from agentos_dev import branch as branch_module
from agentos_dev.branch import (
    BranchError,
    BranchSpec,
    _copy_session_through_run,
    parse_forwarded_props,
    prepare_branch,
    run_branch,
    validate_branch_identity,
)
from agentos_dev.security import CapabilityClaims


def claims(thread, user=7):
    return CapabilityClaims(
        database="odoo",
        user=user,
        company=3,
        odoo_session="a" * 64,
        thread=thread,
        issued_at=1000,
        expires_at=1600,
    )


def source_session():
    return AgentSession(
        session_id="source-thread",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id=f"run-{index}",
                session_id="source-thread",
                agent_id="odoo-assistant",
                status=RunStatus.completed,
                content=f"answer-{index}",
            )
            for index in range(1, 4)
        ],
    )


def test_forwarded_props_only_accepts_controlled_branch_data():
    assert parse_forwarded_props({"forwardedProps": {}}) is None
    spec = parse_forwarded_props(
        {
            "forwardedProps": {
                "branch": {
                    "sourceThreadId": "source-thread",
                    "sourceRunId": "run-1",
                    "targetMessageId": "answer-1",
                }
            }
        }
    )
    assert spec == BranchSpec("source-thread", "run-1", "answer-1")

    with pytest.raises(BranchError, match="forwarded_props_invalid"):
        parse_forwarded_props({"forwardedProps": {"user_id": "admin"}})
    with pytest.raises(BranchError, match="branch_payload_invalid"):
        parse_forwarded_props(
            {
                "forwardedProps": {
                    "branch": {
                        "sourceThreadId": "source-thread",
                        "sourceRunId": "run-1",
                        "targetMessageId": "answer-1",
                        "model": "other",
                    }
                }
            }
        )


def test_branch_capabilities_require_the_same_odoo_identity():
    validate_branch_identity(claims("target"), claims("source"))
    with pytest.raises(BranchError, match="identity_mismatch"):
        validate_branch_identity(claims("target"), claims("source", user=8))


def test_agent_history_is_truncated_and_every_copied_run_gets_a_new_id():
    source = source_session()
    source.runs[1].forked_from_run_id = "run-1"
    source.runs[1].regenerated_from = "run-1"

    target, mapping, copied_target = _copy_session_through_run(
        source,
        "target-thread",
        "run-2",
        "owner",
    )

    assert [run.run_id for run in source.runs] == ["run-1", "run-2", "run-3"]
    assert len(target.runs) == 2
    assert target.runs[1].run_id == mapping["run-2"] == copied_target
    assert target.runs[1].forked_from_run_id == mapping["run-1"]
    assert target.runs[1].regenerated_from == mapping["run-1"]
    assert target.runs[0].session_id == "target-thread"
    assert target.runs[0].forked_from_session_id == "source-thread"
    assert target.summary is None


class FakeAgent:
    def __init__(self, first_run_id="generated-run", fail_stream=False):
        self.source = source_session()
        self.saved = []
        self.deleted = []
        self.db = object()
        self.first_run_id = first_run_id
        self.fail_stream = fail_stream
        self.continue_kwargs = None

    async def aget_session(self, session_id=None, user_id=None):
        if session_id == "source-thread" and user_id == "owner":
            return self.source
        return None

    async def asave_session(self, session):
        self.saved.append(session)

    async def adelete_session(self, session_id, user_id=None):
        self.deleted.append((session_id, user_id))

    def acontinue_run(self, **kwargs):
        self.continue_kwargs = kwargs

        async def stream():
            if self.fail_stream:
                raise RuntimeError("model unavailable")
            kwargs["run_context"].session_state["current_run_id"] = kwargs["run_id"]
            yield SimpleNamespace(run_id=self.first_run_id)

        return stream()


class FakeWorkspace:
    def __init__(self):
        self.copied = []
        self.destroyed = []

    async def acopy_branch(self, source, target):
        self.copied.append((source, target))
        return {"files": 2, "bytes": 10}

    async def adestroy(self, thread):
        self.destroyed.append(thread)


def run_input():
    return SimpleNamespace(
        thread_id="target-thread",
        state={"protocol": "agui.odoo.v2", "host": {}, "agent": {}},
        context=[],
        tools=[],
    )


@pytest.mark.anyio
async def test_branch_sse_reports_mapping_and_uses_native_regenerate(monkeypatch):
    async def mapped(**kwargs):
        async for _event in kwargs["response_stream"]:
            pass
        yield RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id="target-thread",
            run_id="generated-run",
        )

    monkeypatch.setattr(branch_module, "validate_state", lambda state, _thread: state)
    monkeypatch.setattr(branch_module, "async_stream_agno_response_as_agui_events", mapped)
    agent = FakeAgent()
    workspace = FakeWorkspace()
    spec = BranchSpec("source-thread", "run-1", "answer-1")

    events = [
        event
        async for event in run_branch(
            agent,
            workspace,
            run_input(),
            spec,
            "owner",
        )
    ]

    assert [event.type for event in events[:3]] == [
        EventType.CUSTOM,
        EventType.RUN_STARTED,
        EventType.STATE_SNAPSHOT,
    ]
    assert events[0].name == "AGUI_BRANCH_PREPARED"
    assert events[0].value["runId"] == "generated-run"
    assert events[0].value["runIdMap"]["run-1"] != "run-1"
    assert agent.continue_kwargs["regenerate"] is True
    assert agent.continue_kwargs["replace_original"] is True
    assert agent.continue_kwargs["run_id"] == events[0].value["runIdMap"]["run-1"]
    assert agent.continue_kwargs["run_context"].run_id == "generated-run"
    assert events[2].snapshot == {
        "protocol": "agui.odoo.v2",
        "host": {},
        "agent": {},
    }
    assert [run.run_id for run in agent.source.runs] == ["run-1", "run-2", "run-3"]
    assert not workspace.destroyed


@pytest.mark.anyio
async def test_closing_after_run_started_keeps_prepared_branch(monkeypatch):
    monkeypatch.setattr(branch_module, "validate_state", lambda state, _thread: state)
    agent = FakeAgent()
    workspace = FakeWorkspace()
    events = run_branch(
        agent,
        workspace,
        run_input(),
        BranchSpec("source-thread", "run-1", "answer-1"),
        "owner",
    )

    assert (await anext(events)).type == EventType.CUSTOM
    assert (await anext(events)).type == EventType.RUN_STARTED
    await events.aclose()

    assert agent.deleted == []
    assert workspace.destroyed == []


@pytest.mark.anyio
async def test_failure_before_run_started_removes_agent_session_and_workspace(monkeypatch):
    monkeypatch.setattr(branch_module, "validate_state", lambda state, _thread: state)
    agent = FakeAgent(fail_stream=True)
    workspace = FakeWorkspace()

    events = [
        event
        async for event in run_branch(
            agent,
            workspace,
            run_input(),
            BranchSpec("source-thread", "run-1", "answer-1"),
            "owner",
        )
    ]

    assert [event.type for event in events] == [EventType.RUN_ERROR]
    assert events[0].code == "branch_failed"
    assert events[0].message == "分支创建失败，请稍后重试。"
    assert "model unavailable" not in events[0].message
    assert agent.deleted == [("target-thread", "owner")]
    assert workspace.destroyed == ["target-thread"]


@pytest.mark.anyio
async def test_cancelling_session_save_removes_target_session_and_workspace(monkeypatch):
    agent = FakeAgent()
    workspace = FakeWorkspace()
    save_started = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocking_save(_session):
        save_started.set()
        await never_complete.wait()

    monkeypatch.setattr(agent, "asave_session", blocking_save)
    prepare_task = asyncio.create_task(
        prepare_branch(
            agent,
            workspace,
            BranchSpec("source-thread", "run-1", "answer-1"),
            "target-thread",
            "owner",
        )
    )
    await save_started.wait()
    prepare_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await prepare_task

    assert agent.deleted == [("target-thread", "owner")]
    assert workspace.destroyed == ["target-thread"]


@pytest.mark.anyio
async def test_controlled_branch_failure_returns_stable_code_without_internal_message():
    agent = FakeAgent()
    agent.source.runs[0].status = RunStatus.error

    events = [
        event
        async for event in run_branch(
            agent,
            FakeWorkspace(),
            run_input(),
            BranchSpec("source-thread", "run-1", "answer-1"),
            "owner",
        )
    ]

    assert len(events) == 1
    assert events[0].type == EventType.RUN_ERROR
    assert events[0].code == "branch_source_run_not_completed"
    assert events[0].message == "无法基于所选消息创建分支。"
