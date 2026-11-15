"""Run one Agno Word task against its authenticated, in-process MCP tools."""

import json
from collections.abc import Mapping
from copy import deepcopy

import httpx2
from agno.agent import Agent
from agno.tools.mcp import MCPTools
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.asgi_transport import StreamingASGITransport, run_asgi_lifespan

from ..reporting.agent_events import run_owned_agent_with_events
from ..reporting.structured_output.policy import REPORTING_STRUCTURED_REQUEST_MODEL_ATTR
from .native_word_ai import WORD_AI_INSTRUCTIONS, NativeWordAIProposal


class AgnoWordTaskTransport:
    def __init__(self, model):
        self.model = model

    async def run(self, *, server, ticket, task_id, instruction):
        app = server.http_app(transport="streamable-http", path="/mcp", stateless_http=True)

        def client_factory(**kwargs):
            return httpx2.AsyncClient(transport=StreamingASGITransport(app), **kwargs)

        transport = StreamableHttpTransport(
            "http://127.0.0.1/mcp", auth=ticket, httpx_client_factory=client_factory,
        )
        async with run_asgi_lifespan(app), Client(transport) as client:
            tools = MCPTools(session=client)
            await tools.initialize()
            model = deepcopy(self.model)
            setattr(model, REPORTING_STRUCTURED_REQUEST_MODEL_ATTR, True)
            agent = Agent(
                name="native-word-task", model=model, tools=[tools],
                output_schema=NativeWordAIProposal, structured_outputs=False, use_json_mode=True,
                tool_call_limit=256, retries=0, add_history_to_context=False,
                enable_session_summaries=False, markdown=False, telemetry=False,
                instructions=[
                    WORD_AI_INSTRUCTIONS,
                    "文档MCP工具调用都传入给定的task_id；Agno技能读取工具按其schema调用，无需task_id。先读取授权段落，再一次性登记全部候选操作。"
                    "最终只输出 propose_operations 返回的 proposal JSON 对象，原样保留字段和值。",
                ],
            )
            from ..office.ai_skills import attach_office_skills
            attach_office_skills(agent)
            output = await run_owned_agent_with_events(
                agent, f"task_id: {task_id}\n用户要求：{instruction}", session_id=task_id,
            )
        content = output.content
        if isinstance(content, NativeWordAIProposal):
            return content.model_dump(mode="json")
        return dict(content) if isinstance(content, Mapping) else json.loads(content)
