"""Reporting 图表的独立视觉审查。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...agents import OPENAI_COMPATIBLE_ROLE_MAP
from ...settings import AgentSettings
from ...workspace import WorkspaceError, WorkspaceService

_IssueText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
_REPORT_VISION_PROMPT = """
只审查图表的呈现质量，不判断数据真实性、业务口径或 citation 是否正确。

检查空白画布、内容截断、严重重叠、文字或图例不可读，以及会妨碍读者理解的其他明显问题。
仅当图片必须重新生成或修正后才能用于报告时设置 requiresRevision=true，并把原因写入
criticalIssues。warnings 记录不阻断使用的问题，suggestions 提供可选改进。不要要求固定图表
类型、数量、配色或风格，也不要因为图表未采用某种常见形式而判定失败。
""".strip()


class ReportVisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    requires_revision: bool = Field(alias="requiresRevision")
    critical_issues: list[_IssueText] = Field(
        default_factory=list,
        alias="criticalIssues",
        max_length=20,
    )
    warnings: list[_IssueText] = Field(default_factory=list, max_length=20)
    suggestions: list[_IssueText] = Field(default_factory=list, max_length=20)


class ReportVisionReviewer:
    """每次调用创建隔离的视觉 Agent，并只返回结构化文字反馈。"""

    def __init__(
        self,
        settings: AgentSettings,
        workspace_service: WorkspaceService,
        *,
        agent_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._workspace_service = workspace_service
        self._agent_factory = agent_factory

    @property
    def model_id(self) -> str:
        return self._settings.report_vision_model

    def _new_agent(self) -> Agent:
        if self._agent_factory is not None:
            return self._agent_factory()
        model = OpenAIChat(
            id=self.model_id,
            base_url=self._settings.openai_base_url,
            api_key=self._settings.openai_api_key,
            timeout=self._settings.model_timeout_seconds,
            max_retries=0,
            role_map=OPENAI_COMPATIBLE_ROLE_MAP,
            extra_body={"enable_thinking": False},
            temperature=0.1,
            top_p=0.95,
            retries=2,
            exponential_backoff=True,
        )
        agent = Agent(
            id="report-vision-reviewer",
            name="Reporting 图表视觉审查",
            role="只审查单张报告图片的呈现质量。",
            model=model,
            instructions=[_REPORT_VISION_PROMPT],
            tools=[],
            db=None,
            add_history_to_context=False,
            enable_session_summaries=False,
            add_session_summary_to_context=False,
            store_media=False,
            store_history_messages=False,
            output_schema=ReportVisionAssessment,
            parse_response=True,
            retries=0,
            send_media_to_model=True,
            markdown=False,
            debug_mode=self._settings.debug,
        )
        agent.num_history_runs = None
        return agent

    async def review(
        self,
        thread_id: str,
        path: str,
        *,
        detail: str = "high",
    ) -> dict[str, Any]:
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")

        # WorkspaceService 是图片路径、格式、签名和大小的唯一安全读取边界。
        # 视觉模型失败可以降级，但不得绕过该边界直接读取 Daytona 文件。
        loaded = await asyncio.to_thread(self._workspace_service.view_image, thread_id, path)
        if not loaded.images or loaded.images[0].content is None:
            raise WorkspaceError("图片读取结果无效，请重新生成后重试。")
        source = loaded.images[0]
        image = Image(
            content=source.content,
            mime_type=source.mime_type,
            format=source.format,
            detail="high" if detail == "original" else detail,
        )

        try:
            response = await self._new_agent().arun(
                _REPORT_VISION_PROMPT,
                images=[image],
            )
            assessment = ReportVisionAssessment.model_validate(response.content)
        except Exception:
            # 视觉审查不是报告真实性或发布门禁。这里不暴露供应商异常，也不把图片
            # 回退给主 Worker；ok=true 使 Worker 能继续登记图表和完成报告。
            return {
                "ok": True,
                "status": "warning",
                "reviewed": False,
                "code": "report_vision_unavailable",
                "modelId": self.model_id,
                "message": "独立视觉审查暂不可用；图表登记与报告交付可以继续。",
                "retryable": False,
                "warnings": ["本次图片未获得视觉模型反馈。"],
            }

        result = assessment.model_dump(mode="json", by_alias=True)
        result["requiresRevision"] = bool(result["requiresRevision"] or result["criticalIssues"])
        return {
            "ok": True,
            "status": "reviewed",
            "reviewed": True,
            "modelId": self.model_id,
            **result,
        }
