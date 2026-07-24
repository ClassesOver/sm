from collections.abc import AsyncIterator

import pytest

from agentos_dev.coding import (
    AguiCodingAdapter,
    CodingEvent,
    CodingScope,
    InstructionReceipt,
    InstructionState,
)
from agentos_dev.coding.adapters import CodingMemberAdapter


class FakeSupervisor:
    def __init__(self):
        self.calls = []

    async def start_task(self, scope, instruction, predecessor_task_id=None):
        self.calls.append(("start", scope, instruction, predecessor_task_id))

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
