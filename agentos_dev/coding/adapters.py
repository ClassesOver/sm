from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agno.agent import Agent
from agno.run import RunContext
from agno.tools import Function

from ..workspace import WorkspaceService, _thread
from .models import CodingEvent, CodingScope, InstructionReceipt
from .supervisor import CodingTaskSupervisor


class SupervisorPort(Protocol):
    async def start_task(self, scope, initial_instruction, predecessor_task_id=None): ...

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
    ) -> AsyncIterator[CodingEvent]:
        await self.supervisor.start_task(scope, instruction, predecessor_task_id)
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
    async def run(self, scope: CodingScope, instruction: str) -> list[CodingEvent]:
        return [event async for event in self.start(scope, instruction)]


def create_team_coding_member(
    base_agent: Agent,
    supervisor: CodingTaskSupervisor,
    workspace_service: WorkspaceService,
) -> Agent:
    async def run_coding_task(instruction: str, run_context: RunContext) -> str:
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, dict) else {}
        )
        binding = dependencies.get("AgentOS 编码任务")
        external_run_id = binding.get("externalRunId") if isinstance(binding, dict) else None
        if not isinstance(external_run_id, str) or not external_run_id:
            raise ValueError("task_binding_missing")
        thread_id = _thread(run_context)
        async with workspace_service._async_client() as client:
            sandbox = await workspace_service._asandbox_for(client, thread_id)
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        scope = CodingScope(
            external_run_id,
            str(run_context.user_id),
            thread_id,
            sandbox_id,
            str(base_agent.id),
        )
        final = ""
        async for event in CodingMemberAdapter(supervisor).start(scope, instruction):
            if event.type == "final_message":
                final = str(event.data.get("content") or "")
            elif event.type == "terminal" and event.data.get("state") != "completed":
                raise RuntimeError(str(event.data.get("code") or "coding_task_failed"))
        return final

    function = Function(
        name="run_coding_task",
        description="把完整编码目标交给受控 CodingTaskSupervisor 执行并返回验收结果。",
        parameters={
            "type": "object",
            "properties": {"instruction": {"type": "string", "minLength": 1}},
            "required": ["instruction"],
            "additionalProperties": False,
        },
        entrypoint=run_coding_task,
        stop_after_tool_call=True,
    )
    member = base_agent.deep_copy(
        update={
            "instructions": [
                "必须把收到的完整用户编码目标原样传给 run_coding_task，并直接返回工具结果。"
            ],
            "tools": [function],
            "tool_choice": {"type": "function", "function": {"name": "run_coding_task"}},
            "skills": None,
        }
    )
    member.num_history_runs = None
    return member


__all__ = [
    "CliCodingAdapter",
    "CodingMemberAdapter",
    "create_team_coding_member",
]
