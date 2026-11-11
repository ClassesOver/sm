"""观察 Agno 原生运行事件，不替换工具执行器或最终输出合同。"""
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from inspect import isawaitable
from typing import Any

from agno.run.agent import (
    RunContentEvent,
    RunOutput,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)

_observer: ContextVar[Callable[[Any], None] | None] = ContextVar('reporting_agent_event_observer', default=None)


@contextmanager
def observe_agent_events(observer: Callable[[Any], None]):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def current_agent_event_observer() -> Callable[[Any], None] | None:
    return _observer.get()


async def run_agent_with_events(agent: Any, input: Any, **kwargs: Any) -> RunOutput:
    observer = _observer.get()
    result = agent.arun(input, stream=observer is not None,
                        **({'stream_events': True, 'yield_run_output': True} if observer is not None else {}),
                        **kwargs)
    if observer is None:
        return await result if isawaitable(result) else result
    stream = await result if isawaitable(result) else result
    output = None
    async for event in stream:
        if isinstance(event, RunOutput):
            output = event
        else:
            if isinstance(event, RunContentEvent):
                observer(event)
            elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent, ToolCallErrorEvent)):
                observer(event)
    if output is None:
        raise ValueError('agent_stream_output_missing')
    return output


def agent_event_callback(event: Any) -> None:
    """Agno callback strictly records safe content/tool lifecycle through the bound observer."""
    observer = _observer.get()
    if observer is None:
        return
    if isinstance(event, (RunContentEvent, ToolCallStartedEvent, ToolCallCompletedEvent, ToolCallErrorEvent)):
        observer(event)
