from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import BaseEvent, EventType, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from agno.agent import Agent
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui.input import extract_tool_messages
from agno.os.interfaces.agui.router import run_entity
from agno.os.middleware.user_scope import resolve_run_user_id
from agno.session.agent import AgentSession
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .entrypoints import bind_server_envelope, prepare_agui_envelope
from .models import ReportingError


async def _run_bound(agent: Agent, run_input: RunAgentInput, envelope, user_id: str | None):
    source = run_entity(agent, run_input, user_id=user_id).__aiter__()
    while True:
        with bind_server_envelope(envelope):
            try:
                event = await source.__anext__()
            except StopAsyncIteration:
                return
        yield event


class ReportAGUI(AGUI):
    """对 ReportRequestEnvelope 做服务端清洗后再进入 Agno。"""

    def __init__(self, *, agent: Agent, prefix: str = "", tags: list[str] | None = None):
        super().__init__(agent=agent, prefix=prefix, tags=tags)

    def get_router(self, use_async: bool = True, **_kwargs: Any) -> APIRouter:
        _ = use_async
        router = APIRouter(prefix=self.prefix)
        encoder = EventEncoder()
        agent = self.agent
        assert isinstance(agent, Agent)

        @router.post("/agui", name="run_report_agent")
        async def run_report_agent(request: Request, run_input: RunAgentInput):
            client_user_id = (
                run_input.forwarded_props.get("user_id") if run_input.forwarded_props else None
            )
            user_id = resolve_run_user_id(request, client_user_id)

            async def events() -> AsyncIterator[str]:
                try:
                    active = await _has_active_workflow(agent, run_input.thread_id, user_id)
                    if active or extract_tool_messages(run_input.messages or []):
                        source = run_entity(agent, run_input, user_id=user_id)
                    else:
                        prepared = prepare_agui_envelope(run_input)
                        source = _run_bound(
                            agent,
                            prepared.run_input,
                            prepared.envelope,
                            user_id,
                        )
                except ReportingError as error:
                    source = _run_error(error)
                async for event in source:
                    yield encoder.encode(event)

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        self.router = router
        return router


async def _run_error(error: ReportingError) -> AsyncIterator[BaseEvent]:
    yield RunErrorEvent(type=EventType.RUN_ERROR, message=error.message, code=error.code)


async def _has_active_workflow(agent: Agent, thread_id: str, user_id: str | None) -> bool:
    session = await agent.aget_session(session_id=thread_id, user_id=user_id)
    if not isinstance(session, AgentSession) or not isinstance(session.session_data, dict):
        return False
    state = session.session_data.get("session_state")
    if not isinstance(state, dict):
        return False
    control = state.get("report_workflow_control")
    return isinstance(control, dict) and control.get("status") in {"running", "paused"}
