"""原生 Agno任务的有界、可重放进度事件。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from starlette.responses import StreamingResponse

from ..reporting.agent_events import observe_agent_events


@dataclass
class AgentEventLog:
    capacity: int = 128
    history: list[dict[str, Any]] = field(default_factory=list)
    sequence: int = 0
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    pending: set[asyncio.Task] = field(default_factory=set)

    async def emit(self, kind: str, **data: Any) -> None:
        if kind not in {'phase', 'content', 'toolStarted', 'toolCompleted', 'terminal'}:
            return
        self.sequence += 1
        event = {'sequence': self.sequence, 'kind': kind, **data}
        async with self.condition:
            self.history.append(event)
            del self.history[:-self.capacity]
            self.condition.notify_all()

    def schedule(self, event: Any) -> None:
        task = asyncio.get_running_loop().create_task(emit_agno_event(event))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def finish(self, status: str) -> None:
        while self.pending:
            await asyncio.gather(*tuple(self.pending), return_exceptions=True)
        await self.emit('terminal', status=status)

    async def after(self, cursor: int, timeout: float = 15) -> tuple[list[dict[str, Any]], int, bool]:
        async with self.condition:
            oldest = self.history[0]['sequence'] if self.history else self.sequence + 1
            reset = cursor < oldest - 1
            if not reset and cursor >= self.sequence:
                try:
                    await asyncio.wait_for(self.condition.wait_for(lambda: self.sequence > cursor), timeout=timeout)
                except TimeoutError:
                    pass
                oldest = self.history[0]['sequence'] if self.history else self.sequence + 1
                reset = cursor < oldest - 1
            return [event for event in self.history if event['sequence'] > cursor], self.sequence, reset


_current_log: ContextVar[AgentEventLog | None] = ContextVar('native_agent_event_log', default=None)


@asynccontextmanager
async def bind_agent_event_log(log: AgentEventLog):
    token = _current_log.set(log)
    try:
        with observe_agent_events(agent_event_callback):
            yield
    finally:
        _current_log.reset(token)


def current_agent_event_log() -> AgentEventLog | None:
    return _current_log.get()


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ''


async def emit_agno_event(event: Any) -> None:
    log = current_agent_event_log()
    if log is None:
        return
    name = type(event).__name__
    if name == 'RunContentEvent':
        content = _string(getattr(event, 'content', None))
        if content:
            await log.emit('content', delta=content)
    elif name in {'ToolCallStartedEvent', 'ToolCallCompletedEvent', 'ToolCallErrorEvent'}:
        tool = getattr(event, 'tool', None)
        function = getattr(tool, 'function', None)
        tool_name = getattr(function, 'name', None) or getattr(tool, 'tool_name', None)
        if isinstance(tool_name, str):
            kind = {'ToolCallStartedEvent': 'toolStarted', 'ToolCallCompletedEvent': 'toolCompleted',
                    'ToolCallErrorEvent': 'toolCompleted'}[name]
            call_id = getattr(tool, 'tool_call_id', None)
            await log.emit(
                kind,
                toolName=tool_name,
                **({'toolCallId': call_id} if isinstance(call_id, str) and call_id else {}),
                **({'outcome': 'error' if name == 'ToolCallErrorEvent' or getattr(tool, 'tool_call_error', False) else 'success'}
                   if kind == 'toolCompleted' else {}),
            )


def agent_event_callback(event: Any) -> None:
    log = current_agent_event_log()
    if log is None:
        return
    try:
        log.schedule(event)
    except RuntimeError:
        return


async def stream_agent_events(log: AgentEventLog, after: int = 0):
    cursor = max(0, after)
    while True:
        events, latest, reset = await log.after(cursor)
        if reset:
            cursor = log.history[0]['sequence'] - 1 if log.history else latest
            yield f'id: {cursor}\nevent: progress\ndata: {{"sequence":{cursor},"kind":"reset"}}\n\n'
            continue
        for event in events:
            cursor = event['sequence']
            import json
            yield f'id: {cursor}\nevent: progress\ndata: {json.dumps(event, ensure_ascii=False, separators=(",", ":"))}\n\n'
        if any(event['kind'] == 'terminal' for event in events):
            return
        if not events:
            yield ': heartbeat\n\n'


def event_stream_response(log: AgentEventLog, after: int = 0) -> StreamingResponse:
    return StreamingResponse(stream_agent_events(log, after), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})
