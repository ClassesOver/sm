"""Reporting 图表的独立视觉审查。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Annotated, Any

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..integrations.model_config import OPENAI_COMPATIBLE_ROLE_MAP
from ..runtime.settings import AgentSettings
from ..workspace import WorkspaceError, WorkspaceService
from .workflow.checkpoint import (
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
)

_IssueText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
_REPORT_VISION_PROMPT = """
只审查图表的呈现质量，不判断数据真实性、业务口径或 citation 是否正确。

逐项检查 blank、cropping、text_overlap、legend_occlusion、missing_units 和 misleading。
每个发现必须用 issues 返回对应 category、severity 和 description。只有整张图片或绘图区空白、
严重裁剪或关键文字完全重叠且无法辨认，才标为 critical 并设置 requiresRevision=true。
blank 仅表示整张图片、画布或绘图区没有有效图表内容；某个数据系列因数值为零而不可见不属于
blank。legend_occlusion、missing_units 和 misleading 一律只作为 warning，不得阻断。数据全零、
恒定值、折线水平、系列重合、数值或坐标范围疑似异常均属于数据语义，不得据此要求重新生成。
局部文字或数据标签距离过近、轻微交叠但内容仍可辨认时，必须标为 warning，不得标为 critical，
也不得设置 requiresRevision=true；只有关键文字因完全重叠或遮挡而无法辨认时才属于 critical。
字体或布局不理想也放入 warnings。suggestions 提供可选改进。不要要求固定图表类型、数量、配色
或风格，也不要因为图表未采用某种常见形式而判定失败。
""".strip()

_NON_BLOCKING_ISSUE_CATEGORIES = frozenset(
    {"legend_occlusion", "missing_units", "misleading"}
)
_WHOLE_CHART_BLANK_MARKERS = (
    "整张",
    "整个图表",
    "整幅",
    "全图",
    "图表主体",
    "绘图区",
    "画布",
    "entire chart",
    "whole chart",
    "plot area",
    "canvas",
)


def _is_non_blocking_issue(issue: dict[str, Any]) -> bool:
    category = issue.get("category")
    if category in _NON_BLOCKING_ISSUE_CATEGORIES:
        return True
    if category != "blank":
        return False
    description = str(issue.get("description", "")).lower()
    return not any(marker in description for marker in _WHOLE_CHART_BLANK_MARKERS)


def _normalize_visual_assessment(result: dict[str, Any]) -> dict[str, Any]:
    """将轻微呈现问题统一降为告警，避免视觉模型过度阻断章节。"""
    warnings = list(result.get("warnings", ()))
    normalized_issues: list[dict[str, Any]] = []
    for raw_issue in result.get("issues", ()):
        issue = dict(raw_issue)
        if _is_non_blocking_issue(issue):
            issue["severity"] = "warning"
        if issue.get("severity") == "warning":
            description = issue.get("description")
            if isinstance(description, str) and description and description not in warnings:
                warnings.append(description)
        normalized_issues.append(issue)
    result["issues"] = normalized_issues
    result["warnings"] = warnings[:20]
    result["requiresRevision"] = any(
        issue.get("severity") == "critical" for issue in normalized_issues
    )
    return result


class ReportVisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    requires_revision: bool = Field(alias="requiresRevision")
    issues: list[ChartVisualInspectionIssue] = Field(default_factory=list, max_length=20)
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
            telemetry=False,
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

        # WorkspaceService 是图片路径、格式、签名和大小的安全读取边界。模型只接收
        # 已通过该边界返回的内存字节，不获得工作区路径或通用文件权限。
        loaded = await self._workspace_service.aview_image(thread_id, path)
        if not loaded.images or loaded.images[0].content is None:
            raise WorkspaceError("图片读取结果无效，请重新生成后重试。")
        source = loaded.images[0]
        assert source.content is not None
        image = Image(
            content=source.content,
            mime_type=source.mime_type,
            format=source.format,
            detail="high" if detail == "original" else detail,
        )

        digest = hashlib.sha256(source.content).hexdigest()
        try:
            response = await self._new_agent().arun(
                "请按审查规则检查这张图片并返回结构化审查结果。",
                images=[image],
            )
            assessment = ReportVisionAssessment.model_validate(response.content)
        except Exception as error:
            # 视觉回执已成为正式图表发布门禁。供应商失败不能伪造 reviewed=true，
            # 也不能把原始异常或供应商响应带回模型上下文。
            raise WorkspaceError("图表视觉审查暂不可用，请稍后重试。") from error

        result = _normalize_visual_assessment(
            assessment.model_dump(mode="json", by_alias=True)
        )
        return ChartVisualInspectionReceipt.model_validate(
            {
                "sourcePath": path,
                "sha256": digest,
                "reviewed": True,
                "modelId": self.model_id,
                **result,
            }
        ).model_dump(mode="json", by_alias=True)
