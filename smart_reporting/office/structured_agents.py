"""无工具结构化候选 Agent 的中立工厂，供 Office 文件内 AI 与报告链路共用。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agno.agent import Agent

from ..reporting.structured_output.agno_compat import install_agno_structured_output_parser

STRUCTURED_CANDIDATE_INSTRUCTIONS: tuple[str, ...] = (
    "只返回一个严格满足 output_schema 的 JSON 对象，不得返回推理、解释、Markdown 或代码围栏。",
    "所有必填顶层字段必须各出现一次；不得把 schema 顶层字段只写入其他字段。",
    "长文本字段必须是合法 JSON 字符串，换行和引号必须按 JSON 转义。",
)

DEFAULT_CANDIDATE_ROLE = "只返回固定阶段要求的结构化候选内容。"


def create_structured_candidate_agent(
    *,
    model: Any,
    output_schema: type[Any],
    name: str,
    role: str | None = None,
    stage_instructions: Sequence[str] = (),
    base_instructions: Sequence[str] = STRUCTURED_CANDIDATE_INSTRUCTIONS,
) -> Agent:
    """创建关闭工具、历史与 Agent 重试的结构化候选生成器。

    生成器只返回 Pydantic 契约对应的结果；脚本执行、证据读取与提交由调用方负责。
    """

    install_agno_structured_output_parser()
    return Agent(
        id=name,
        name=name,
        role=role or DEFAULT_CANDIDATE_ROLE,
        model=model,
        output_schema=output_schema,
        instructions=[*base_instructions, *stage_instructions],
        # 实际传输方式由结构化输出执行器根据路由后的模型能力选择；基础 Agent
        # 保持原生模式，禁止 Agno 把完整 Schema 注入 system prompt。
        structured_outputs=True,
        use_json_mode=False,
        tools=[],
        add_history_to_context=False,
        enable_session_summaries=False,
        retries=0,
        exponential_backoff=False,
        markdown=False,
        telemetry=False,
    )


__all__ = [
    "DEFAULT_CANDIDATE_ROLE",
    "STRUCTURED_CANDIDATE_INSTRUCTIONS",
    "create_structured_candidate_agent",
]
