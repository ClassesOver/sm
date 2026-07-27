from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agno.metrics import ToolCallMetrics
from agno.models.response import ToolExecution
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)

from .models import CodingEvent, CodingScope, InstructionReceipt
from .supervisor import CodingTaskSupervisor


class SupervisorPort(Protocol):
    async def start_task(
        self,
        scope,
        initial_instruction,
        predecessor_task_id=None,
        *,
        acceptance_contract=None,
    ): ...

    def run_task(self, scope) -> AsyncIterator[CodingEvent]: ...

    def resume_task(self, scope) -> AsyncIterator[CodingEvent]: ...

    async def submit_instruction(self, scope, instruction_id, content) -> InstructionReceipt: ...

    async def cancel_task(self, scope): ...


class CodingMemberAdapter:
    def __init__(self, supervisor: CodingTaskSupervisor):
        self.supervisor = supervisor

    async def start(
        self,
        scope: CodingScope,
        instruction: str,
        *,
        predecessor_task_id: str | None = None,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> AsyncIterator[CodingEvent]:
        await self.supervisor.start_task(
            scope,
            instruction,
            predecessor_task_id,
            acceptance_contract=acceptance_contract,
        )
        async for event in self.supervisor.run_task(scope):
            yield event

    async def resume(self, scope: CodingScope) -> AsyncIterator[CodingEvent]:
        async for event in self.supervisor.resume_task(scope):
            yield event

    async def instruct(
        self, scope: CodingScope, instruction_id: str, content: str
    ) -> InstructionReceipt:
        return await self.supervisor.submit_instruction(scope, instruction_id, content)

    async def cancel(self, scope: CodingScope):
        return await self.supervisor.cancel_task(scope)


class CliCodingAdapter(CodingMemberAdapter):
    def __init__(self, supervisor: CodingTaskSupervisor):
        super().__init__(supervisor)
        self._tools: dict[str, ToolExecution] = {}
        self._terminal_calls: set[str] = set()

    async def start_events(
        self,
        scope: CodingScope,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> AsyncIterator[RunOutputEvent]:
        async for event in self.start(
            scope,
            instruction,
            acceptance_contract=acceptance_contract,
        ):
            if event.type == "terminal" and event.data.get("state") != "completed":
                raise RuntimeError(str(event.data.get("code") or "coding_task_failed"))
            if event.type == "suspended":
                raise RuntimeError(str(event.data.get("code") or "coding_task_suspended"))
            for converted in self.convert(event, scope):
                yield converted

    def convert(self, event: CodingEvent, scope: CodingScope) -> list[RunOutputEvent]:
        if event.type == "final_message":
            return [
                RunContentEvent(
                    run_id=scope.external_run_id,
                    content=str(event.data.get("content") or ""),
                )
            ]
        if event.type == "agno_event":
            event_type = str(event.data.get("event") or "")
            if event_type == "ReasoningStarted":
                return [ReasoningStartedEvent(run_id=scope.external_run_id)]
            if event_type == "ReasoningContentDelta":
                reasoning_content = event.data.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content:
                    return [
                        ReasoningContentDeltaEvent(
                            run_id=scope.external_run_id,
                            reasoning_content=reasoning_content,
                        )
                    ]
                return []
            if event_type == "ReasoningCompleted":
                return [ReasoningCompletedEvent(run_id=scope.external_run_id)]
        tool_data = _tool_event_data(event)
        if tool_data is None:
            return []
        call_id, tool_name, phase, arguments, duration = tool_data
        if phase == "started":
            tool = ToolExecution(
                tool_call_id=call_id,
                tool_name=tool_name,
                tool_args=_tool_arguments(arguments),
            )
            self._tools[call_id] = tool
            return [ToolCallStartedEvent(run_id=scope.external_run_id, tool=tool)]
        if call_id in self._terminal_calls:
            return []
        self._terminal_calls.add(call_id)
        tool = self._tools.setdefault(
            call_id,
            ToolExecution(tool_call_id=call_id, tool_name=tool_name),
        )
        if duration is not None:
            tool.metrics = ToolCallMetrics(duration=duration)
        tool.tool_call_error = phase == "error"
        tool.result = json.dumps(
            {"ok": phase == "completed", "internal": True}, separators=(",", ":")
        )
        completed = ToolCallCompletedEvent(run_id=scope.external_run_id, tool=tool)
        if phase == "completed":
            return [completed]
        return [
            completed,
            ToolCallErrorEvent(
                run_id=scope.external_run_id,
                tool=tool,
                error="internal_tool_failed",
            ),
        ]


class AguiCodingAdapter(CodingMemberAdapter):
    def __init__(self, supervisor: CodingTaskSupervisor):
        super().__init__(supervisor)
        self._terminal_calls: set[str] = set()

    async def start_events(
        self,
        scope: CodingScope,
        instruction: str,
        *,
        predecessor_task_id: str | None = None,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        async for event in self.start(
            scope,
            instruction,
            predecessor_task_id=predecessor_task_id,
            acceptance_contract=acceptance_contract,
        ):
            for converted in self.convert(event, scope):
                yield converted

    async def resume_events(self, scope: CodingScope) -> AsyncIterator[BaseEvent]:
        async for event in self.resume(scope):
            for converted in self.convert(event, scope):
                yield converted

    def convert(self, event: CodingEvent, scope: CodingScope) -> list[BaseEvent]:
        tool_data = _tool_event_data(event)
        if tool_data is not None:
            call_id, tool_name, phase, arguments, duration = tool_data
            if phase == "started":
                return [
                    ToolCallStartEvent(tool_call_id=call_id, tool_call_name=tool_name),
                    ToolCallArgsEvent(tool_call_id=call_id, delta=arguments or "{}"),
                    ToolCallEndEvent(tool_call_id=call_id),
                ]
            if call_id in self._terminal_calls:
                return []
            self._terminal_calls.add(call_id)
            content: dict[str, Any] = {"ok": phase == "completed", "internal": True}
            if duration is not None:
                content["durationSeconds"] = duration
            if phase == "error":
                content["code"] = "internal_tool_failed"
            return [
                ToolCallResultEvent(
                    message_id=f"{call_id}:result",
                    tool_call_id=call_id,
                    content=json.dumps(content, separators=(",", ":")),
                    role="tool",
                )
            ]
        if event.type == "final_message":
            return [
                TextMessageStartEvent(message_id=event.event_id, role="assistant"),
                TextMessageContentEvent(
                    message_id=event.event_id, delta=str(event.data.get("content") or "")
                ),
                TextMessageEndEvent(message_id=event.event_id),
            ]
        if event.type == "terminal" and event.data.get("state") == "completed":
            return [
                RunFinishedEvent(
                    type=EventType.RUN_FINISHED,
                    thread_id=scope.thread_id,
                    run_id=scope.external_run_id,
                )
            ]
        if event.type == "terminal":
            return [
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message=str(event.data.get("message") or "编码任务未完成。"),
                    code=str(event.data.get("code") or "coding_task_failed"),
                )
            ]
        if event.type == "suspended":
            return [
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message="编码任务已暂停，请在外部依赖恢复后继续。",
                    code=str(event.data.get("code") or "coding_task_suspended"),
                )
            ]
        return []


def _tool_event_data(
    event: CodingEvent,
) -> tuple[str, str, str, str, float | None] | None:
    if event.type != "agno_event":
        return None
    phase = event.data.get("phase")
    tool_name = event.data.get("tool")
    call_id = event.data.get("call_id")
    if (
        phase not in {"started", "completed", "error"}
        or not isinstance(tool_name, str)
        or not tool_name
        or not isinstance(call_id, str)
        or not call_id
    ):
        return None
    arguments = str(event.data.get("arguments") or "")
    duration_value = event.data.get("duration_seconds")
    duration = float(duration_value) if isinstance(duration_value, int | float) else None
    return call_id, tool_name, phase, arguments, duration


def _tool_arguments(arguments: str) -> dict[str, Any]:
    if not arguments:
        return {}
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return {"summary": arguments}
    return value if isinstance(value, dict) else {"summary": arguments}


__all__ = [
    "AguiCodingAdapter",
    "CliCodingAdapter",
    "CodingMemberAdapter",
]
