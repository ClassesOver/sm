from __future__ import annotations

from collections.abc import AsyncIterator

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from .coding.adapters import CodingMemberAdapter
from .coding.models import CodingEvent, CodingScope


class AguiCodingAdapter(CodingMemberAdapter):
    async def start_events(
        self,
        scope: CodingScope,
        instruction: str,
        *,
        predecessor_task_id: str | None = None,
    ) -> AsyncIterator[BaseEvent]:
        async for event in self.start(scope, instruction, predecessor_task_id=predecessor_task_id):
            for converted in self.convert(event, scope):
                yield converted

    async def resume_events(self, scope: CodingScope) -> AsyncIterator[BaseEvent]:
        async for event in self.resume(scope):
            for converted in self.convert(event, scope):
                yield converted

    @staticmethod
    def convert(event: CodingEvent, scope: CodingScope) -> list[BaseEvent]:
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
        return []


__all__ = ["AguiCodingAdapter"]
