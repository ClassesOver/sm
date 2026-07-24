from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from agno.agent import Agent
from agno.run.base import RunStatus

from .models import AttemptSnapshot, CodingScope


@dataclass(frozen=True)
class AgnoRunState:
    exists: bool
    status: str | None = None
    terminal: bool = False
    checkpoint_recoverable: bool = False
    output: str = ""


class AgnoCodingExecutor:
    """Coding 域内唯一直接调用 Agno run API 的组件。"""

    def __init__(self, agent_for_id: Callable[[str], Agent]):
        self.agent_for_id = agent_for_id

    async def arun(
        self,
        scope: CodingScope,
        attempt: AttemptSnapshot,
        instruction: str,
        *,
        dependencies: dict[str, Any],
    ) -> AsyncIterator[Any]:
        source: Any = self.agent_for_id(scope.agent_id).arun(
            instruction,
            stream=True,
            stream_events=True,
            run_id=attempt.internal_run_id,
            session_id=scope.thread_id,
            user_id=scope.owner_user_id,
            dependencies=dependencies,
        )
        if isawaitable(source):
            source = await source
        if not hasattr(source, "__aiter__"):
            raise RuntimeError("Agno arun 未返回事件流。")
        async for event in source:
            yield event

    async def acontinue_run(
        self,
        scope: CodingScope,
        attempt: AttemptSnapshot,
        instruction: str | None,
        *,
        dependencies: dict[str, Any],
    ) -> AsyncIterator[Any]:
        source: Any = self.agent_for_id(scope.agent_id).acontinue_run(
            run_id=attempt.internal_run_id,
            input=instruction,
            stream=True,
            stream_events=True,
            session_id=scope.thread_id,
            user_id=scope.owner_user_id,
            dependencies=dependencies,
        )
        if isawaitable(source):
            source = await source
        if not hasattr(source, "__aiter__"):
            raise RuntimeError("Agno acontinue_run 未返回事件流。")
        async for event in source:
            yield event

    async def state(self, scope: CodingScope, attempt: AttemptSnapshot) -> AgnoRunState:
        output = await self.agent_for_id(scope.agent_id).aget_run_output(
            run_id=attempt.internal_run_id,
            session_id=scope.thread_id,
            user_id=scope.owner_user_id,
        )
        if output is None:
            return AgnoRunState(exists=False)
        status_value = getattr(output, "status", None)
        status = (
            status_value.value if isinstance(status_value, RunStatus) else str(status_value or "")
        )
        terminal = status_value in {
            RunStatus.completed,
            RunStatus.cancelled,
            RunStatus.error,
            RunStatus.regenerated,
        }
        recoverable = bool(
            status_value == RunStatus.paused
            or getattr(output, "last_checkpoint_at_message_index", None) is not None
        )
        content = getattr(output, "content", "")
        return AgnoRunState(
            exists=True,
            status=status or None,
            terminal=terminal,
            checkpoint_recoverable=recoverable,
            output=str(content or ""),
        )
