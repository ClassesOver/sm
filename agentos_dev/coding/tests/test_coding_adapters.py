from collections.abc import AsyncIterator

import pytest
from ag_ui.core import EventType
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    RunContentEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)

from agentos_dev.coding import (
    AguiCodingAdapter,
    CliCodingAdapter,
    CodingEvent,
    CodingScope,
    InstructionReceipt,
    InstructionState,
)
from agentos_dev.coding.adapters import CodingMemberAdapter


class FakeSupervisor:
    def __init__(self):
        self.calls = []

    async def start_task(
        self,
        scope,
        instruction,
        predecessor_task_id=None,
        *,
        acceptance_contract=None,
    ):
        self.calls.append(("start", scope, instruction, predecessor_task_id, acceptance_contract))

    async def run_task(self, scope) -> AsyncIterator[CodingEvent]:
        self.calls.append(("run", scope))
        yield CodingEvent(f"{scope.external_run_id}:final", "final_message", {"content": "完成"})
        yield CodingEvent(f"{scope.external_run_id}:terminal", "terminal", {"state": "completed"})

    async def resume_task(self, scope) -> AsyncIterator[CodingEvent]:
        self.calls.append(("resume", scope))
        yield CodingEvent(f"{scope.external_run_id}:terminal", "terminal", {"state": "failed"})

    async def submit_instruction(self, scope, instruction_id, content):
        self.calls.append(("instruction", scope, instruction_id, content))
        return InstructionReceipt(instruction_id, 2, InstructionState.PENDING)

    async def cancel_task(self, scope):
        self.calls.append(("cancel", scope))


def scope():
    return CodingScope("run", "user", "thread", "sandbox", "coding-agent")


@pytest.mark.anyio
async def test_member_adapter_only_calls_supervisor_public_api():
    supervisor = FakeSupervisor()
    adapter = CodingMemberAdapter(supervisor)  # type: ignore[arg-type]

    events = [event async for event in adapter.start(scope(), "实现目标")]
    receipt = await adapter.instruct(scope(), "i-1", "补充测试")
    await adapter.cancel(scope())

    assert [call[0] for call in supervisor.calls] == ["start", "run", "instruction", "cancel"]
    assert receipt.state is InstructionState.PENDING
    assert events[-1].event_id == "run:terminal"


@pytest.mark.anyio
async def test_member_adapter_forwards_server_acceptance_contract():
    supervisor = FakeSupervisor()
    adapter = CodingMemberAdapter(supervisor)  # type: ignore[arg-type]
    acceptance_contract = {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }

    _events = [
        event
        async for event in adapter.start(
            scope(),
            "实现目标",
            acceptance_contract=acceptance_contract,
        )
    ]

    assert supervisor.calls[0] == (
        "start",
        scope(),
        "实现目标",
        None,
        acceptance_contract,
    )


@pytest.mark.anyio
async def test_agui_adapter_uses_deterministic_final_and_terminal_ids():
    supervisor = FakeSupervisor()
    adapter = AguiCodingAdapter(supervisor)  # type: ignore[arg-type]

    events = [event async for event in adapter.start_events(scope(), "实现目标")]

    assert [getattr(event, "message_id", None) for event in events[:3]] == [
        "run:final",
        "run:final",
        "run:final",
    ]
    assert events[-1].run_id == "run"


def test_agui_adapter_converts_suspension_to_connection_error():
    adapter = AguiCodingAdapter(FakeSupervisor())  # type: ignore[arg-type]
    converted = adapter.convert(
        CodingEvent(
            "run:suspended:2",
            "suspended",
            {"state": "suspended", "code": "model_insufficient_quota"},
        ),
        scope(),
    )

    assert len(converted) == 1
    assert converted[0].code == "model_insufficient_quota"


def tool_event(phase: str) -> CodingEvent:
    return CodingEvent(
        f"run:0:{phase}",
        "agno_event",
        {
            "event": f"ToolCall{phase.title()}",
            "phase": phase,
            "tool": "terminal",
            "call_id": "run:0:internal:call-1",
            "arguments": '{"command":"pytest -q"}',
            "duration_seconds": 1.25,
        },
    )


def test_cli_adapter_converts_internal_tools_to_agno_tool_call_events():
    adapter = CliCodingAdapter(FakeSupervisor())  # type: ignore[arg-type]

    started = adapter.convert(tool_event("started"), scope())
    completed = adapter.convert(tool_event("completed"), scope())
    final = adapter.convert(CodingEvent("run:final", "final_message", {"content": "完成"}), scope())

    assert isinstance(started[0], ToolCallStartedEvent)
    assert started[0].tool.tool_name == "terminal"
    assert started[0].tool.tool_args == {"command": "pytest -q"}
    assert isinstance(completed[0], ToolCallCompletedEvent)
    assert completed[0].tool is started[0].tool
    assert completed[0].tool.tool_call_error is False
    assert isinstance(final[0], RunContentEvent)
    assert final[0].content == "完成"


def test_cli_adapter_converts_reasoning_to_official_stream_events():
    adapter = CliCodingAdapter(FakeSupervisor())  # type: ignore[arg-type]
    events = [
        CodingEvent("run:0:1", "agno_event", {"event": "ReasoningStarted"}),
        CodingEvent(
            "run:0:2",
            "agno_event",
            {"event": "ReasoningContentDelta", "reasoning_content": "先检查"},
        ),
        CodingEvent(
            "run:0:3",
            "agno_event",
            {"event": "ReasoningContentDelta", "reasoning_content": "，再修改"},
        ),
        CodingEvent(
            "run:0:4",
            "agno_event",
            {"event": "ReasoningContentDelta", "reasoning_content": ""},
        ),
        CodingEvent("run:0:5", "agno_event", {"event": "ReasoningCompleted"}),
    ]

    converted = [item for event in events for item in adapter.convert(event, scope())]

    assert [type(event) for event in converted] == [
        ReasoningStartedEvent,
        ReasoningContentDeltaEvent,
        ReasoningContentDeltaEvent,
        ReasoningCompletedEvent,
    ]
    assert [event.run_id for event in converted] == ["run"] * 4
    assert isinstance(converted[1], ReasoningContentDeltaEvent)
    assert converted[1].reasoning_content == "先检查"
    assert isinstance(converted[2], ReasoningContentDeltaEvent)
    assert converted[2].reasoning_content == "，再修改"


def test_agui_adapter_converts_internal_tools_to_standard_tool_call_events():
    adapter = AguiCodingAdapter(FakeSupervisor())  # type: ignore[arg-type]

    started = adapter.convert(tool_event("started"), scope())
    completed = adapter.convert(tool_event("completed"), scope())

    assert [event.type for event in started] == [
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
    ]
    assert started[0].tool_call_id == "run:0:internal:call-1"
    assert started[1].delta == '{"command":"pytest -q"}'
    assert [event.type for event in completed] == [EventType.TOOL_CALL_RESULT]
    assert completed[0].tool_call_id == "run:0:internal:call-1"
    assert completed[0].content == '{"ok":true,"internal":true,"durationSeconds":1.25}'
