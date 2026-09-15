# ruff: noqa: E402
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skip(reason="旧 submit_python_source smoke 已移除")
from agno.agent import Agent
from agno.tools.function import Function

from smart_reporting.reporting.agent import ReportingCodeOpenAIResponses
from smart_reporting.runtime.settings import AgentSettings


@pytest.mark.integration
@pytest.mark.anyio
async def test_dashscope_responses_custom_source_tool_reaches_callback() -> None:
    settings = AgentSettings.from_environment(dict(os.environ))
    if not settings.openai_api_key:
        pytest.skip(".env 未配置 OPENAI_API_KEY，跳过 DashScope Responses smoke test。")

    received_sources: list[str] = []

    async def submit_python_source(source: str) -> dict[str, bool]:
        received_sources.append(source)
        return {"ok": True}

    model = ReportingCodeOpenAIResponses(
        id=settings.model_standard_id,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=min(settings.model_timeout_seconds, 60),
        max_retries=0,
        max_output_tokens=256,
        extra_body={"enable_thinking": False},
    )
    agent = Agent(
        model=model,
        instructions=[
            "只调用一次 submit_python_source。",
            "custom input 只包含至少两行的完整 Python 源码，不得输出解释或 Markdown。",
        ],
        tools=[
            Function(
                name="submit_python_source",
                description="提交完整原始 Python 源码。",
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string", "minLength": 1}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=submit_python_source,
                stop_after_tool_call=True,
            )
        ],
        tool_choice={
            "type": "function",
            "function": {"name": "submit_python_source"},
        },
        tool_call_limit=1,
        add_history_to_context=False,
        enable_session_summaries=False,
        retries=0,
        telemetry=False,
    )

    await agent.arun("提交一个最小 Python 程序：第一行定义 value = 1，第二行打印 value。")

    assert len(received_sources) == 1
    source = received_sources[0]
    assert source.strip()
    assert "```" not in source
    compile(source, "dashscope-smoke.py", "exec")
