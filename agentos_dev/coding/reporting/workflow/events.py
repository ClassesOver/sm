"""Reporting Workflow 的实时事件桥接。"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ReportingEvent:
    sequence: int
    type: str
    workflow_run_id: str
    data: dict[str, Any]
    created_at: str

    def sse(self) -> str:
        payload = {
            "sequence": self.sequence,
            "type": self.type,
            "timestamp": self.created_at,
            "workflowRunId": self.workflow_run_id,
            **self.data,
        }
        return (
            f"id: {self.sequence}\n"
            "event: reporting\n"
            f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        )


@dataclass
class _Channel:
    events: deque[ReportingEvent]
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    next_sequence: int = 1


class ReportingEventBroker:
    """进程内有界事件日志；持久化 Workflow 快照仍是断线兜底。"""

    def __init__(self, *, replay_limit: int = 2048, keepalive_seconds: float = 15.0):
        self.replay_limit = replay_limit
        self.keepalive_seconds = keepalive_seconds
        self._channels: dict[tuple[str, str], _Channel] = {}

    async def publish(
        self,
        user_id: str,
        workflow_run_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> ReportingEvent:
        channel = self._channel(user_id, workflow_run_id)
        async with channel.condition:
            event = ReportingEvent(
                sequence=channel.next_sequence,
                type=event_type,
                workflow_run_id=workflow_run_id,
                data=dict(data),
                created_at=datetime.now(UTC).isoformat(),
            )
            channel.next_sequence += 1
            channel.events.append(event)
            channel.condition.notify_all()
            return event

    async def emit_workflow(self, run_context: Any, event_type: str, data: dict[str, Any]) -> None:
        user_id = str(getattr(run_context, "user_id", "") or "")
        workflow_run_id = str(getattr(run_context, "run_id", "") or "")
        if user_id and workflow_run_id:
            await self.publish(user_id, workflow_run_id, event_type, data)

    async def emit_worker(self, scope: Any, workflow_run_id: str, raw_event: Any) -> None:
        event_value = getattr(raw_event, "event", None) or getattr(raw_event, "type", None)
        event_type = str(getattr(event_value, "value", event_value) or type(raw_event).__name__)
        normalized = event_type.replace("_", "").lower()
        phase = {
            "toolcallstarted": "started",
            "toolcallcompleted": "completed",
            "toolcallerror": "error",
        }.get(normalized)
        tool = getattr(raw_event, "tool", None)
        tool_name = str(getattr(tool, "tool_name", "") or "")
        if phase is None or not tool_name:
            return
        if phase == "completed" and bool(getattr(tool, "tool_call_error", False)):
            phase = "error"
        tool_call_id = str(getattr(tool, "tool_call_id", "") or tool_name)
        data: dict[str, Any] = {
            "stepId": "run-coding-analysis",
            "stepName": "Coding 分析与成稿",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
        }
        if phase == "started":
            data["args"] = getattr(tool, "tool_args", None) or {}
        else:
            data["result"] = getattr(tool, "result", None)
            metrics = getattr(tool, "metrics", None)
            duration = getattr(metrics, "duration", None)
            if isinstance(duration, int | float):
                data["metrics"] = {"duration": float(duration)}
            if phase == "error":
                data["error"] = str(getattr(raw_event, "error", None) or "Coding 工具执行失败。")
        await self.publish(
            str(getattr(scope, "owner_user_id", "") or ""),
            workflow_run_id,
            f"tool_call_{phase}",
            data,
        )

    async def subscribe(
        self,
        user_id: str,
        workflow_run_id: str,
        *,
        after: int = 0,
    ) -> AsyncIterator[ReportingEvent | None]:
        channel = self._channel(user_id, workflow_run_id)
        cursor = max(0, after)
        while True:
            keepalive = False
            async with channel.condition:
                pending = [event for event in channel.events if event.sequence > cursor]
                if not pending:
                    try:
                        await asyncio.wait_for(
                            channel.condition.wait(), timeout=self.keepalive_seconds
                        )
                    except TimeoutError:
                        keepalive = True
            if keepalive:
                yield None
                continue
            if not pending:
                continue
            for event in pending:
                cursor = event.sequence
                yield event

    def _channel(self, user_id: str, workflow_run_id: str) -> _Channel:
        key = (user_id, workflow_run_id)
        channel = self._channels.get(key)
        if channel is None:
            channel = _Channel(events=deque(maxlen=self.replay_limit))
            self._channels[key] = channel
        return channel
