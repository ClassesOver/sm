from types import SimpleNamespace

import pytest
from agno.media import Image
from agno.tools.function import ToolResult

from smart_reporting.reporting.vision import ReportVisionReviewer


def test_visual_model_disables_thinking():
    reviewer = ReportVisionReviewer(
        SimpleNamespace(
            report_vision_model="vision-model", openai_base_url="https://example.com/v1",
            openai_api_key="test", model_timeout_seconds=30, debug=False,
        ),
        None,
    )
    assert reviewer._new_agent().model.extra_body == {"enable_thinking": False}


@pytest.mark.anyio
async def test_vision_reviewer_reads_image_through_async_workspace_api() -> None:
    content = b"\x89PNG\r\n\x1a\ncontent"

    class Workspace:
        def view_image(self, *_args: object) -> ToolResult:
            raise AssertionError("异步视觉审查不得调用同步工作区接口")

        async def aview_image(self, thread_id: str, path: str) -> ToolResult:
            assert (thread_id, path) == ("thread-1", "charts/revenue.png")
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    prompts: list[str] = []

    class Agent:
        async def arun(self, prompt: str, *, images: list[Image]):
            prompts.append(prompt)
            assert images[0].content == content
            return SimpleNamespace(
                content={
                    "summary": "图表清晰。",
                    "requiresRevision": False,
                    "issues": [],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["reviewed"] is True
    assert result["sha256"]
    assert prompts == ["请按审查规则检查这张图片并返回结构化审查结果。"]


@pytest.mark.anyio
async def test_vision_reviewer_demotes_minor_presentation_issues_to_warnings() -> None:
    content = b"image"

    class Workspace:
        async def aview_image(self, *_args: object) -> ToolResult:
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
            return SimpleNamespace(
                content={
                    "summary": "有轻微排版问题。",
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "text_overlap",
                            "severity": "warning",
                            "description": "标签有轻微重叠。",
                        },
                        {
                            "category": "legend_occlusion",
                            "severity": "warning",
                            "description": "图例有轻微遮挡。",
                        },
                        {
                            "category": "missing_units",
                            "severity": "critical",
                            "description": "坐标轴缺少单位。",
                        },
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["requiresRevision"] is False
    assert [issue["severity"] for issue in result["issues"]] == [
        "warning",
        "warning",
        "warning",
    ]
    assert result["warnings"] == ["标签有轻微重叠。", "图例有轻微遮挡。", "坐标轴缺少单位。"]


@pytest.mark.anyio
async def test_vision_reviewer_demotes_legend_occlusion_to_warning() -> None:
    content = b"image"

    class Workspace:
        async def aview_image(self, *_args: object) -> ToolResult:
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
            return SimpleNamespace(
                content={
                    "summary": "关键图例被完全遮挡。",
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "legend_occlusion",
                            "severity": "critical",
                            "description": "关键图例被完全遮挡。",
                        }
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["requiresRevision"] is False
    assert result["issues"][0]["severity"] == "warning"
    assert result["warnings"] == ["关键图例被完全遮挡。"]


@pytest.mark.anyio
async def test_vision_reviewer_demotes_data_semantic_findings_to_warnings() -> None:
    content = b"image"

    class Workspace:
        async def aview_image(self, *_args: object) -> ToolResult:
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
            return SimpleNamespace(
                content={
                    "summary": "数据序列缺少变化。",
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "misleading",
                            "severity": "critical",
                            "description": "所有数据点均为0，两条折线完全重合。",
                        },
                        {
                            "category": "blank",
                            "severity": "critical",
                            "description": "收入柱状系列不可见，可能是因为数据全为0。",
                        },
                        {
                            "category": "misleading",
                            "severity": "critical",
                            "description": "次均收入在所有月份均为1.00，呈水平直线。",
                        },
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["requiresRevision"] is False
    assert [issue["severity"] for issue in result["issues"]] == [
        "warning",
        "warning",
        "warning",
    ]
    assert result["warnings"] == [
        "所有数据点均为0，两条折线完全重合。",
        "收入柱状系列不可见，可能是因为数据全为0。",
        "次均收入在所有月份均为1.00，呈水平直线。",
    ]


@pytest.mark.anyio
async def test_vision_reviewer_keeps_severe_text_overlap_as_blocking() -> None:
    content = b"image"

    class Workspace:
        async def aview_image(self, *_args: object) -> ToolResult:
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
            return SimpleNamespace(
                content={
                    "summary": "关键标签无法阅读。",
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "text_overlap",
                            "severity": "critical",
                            "description": "关键数据标签完全重叠。",
                        }
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["requiresRevision"] is True
    assert result["issues"][0]["severity"] == "critical"


@pytest.mark.anyio
async def test_vision_reviewer_keeps_blank_chart_as_blocking() -> None:
    content = b"image"

    class Workspace:
        async def aview_image(self, *_args: object) -> ToolResult:
            return ToolResult(
                content="loaded",
                images=[Image(content=content, mime_type="image/png", format="png")],
            )

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
            return SimpleNamespace(
                content={
                    "summary": "图表为空白。",
                    "requiresRevision": False,
                    "issues": [
                        {
                            "category": "blank",
                            "severity": "critical",
                            "description": "图表主体为空白。",
                        }
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            )

    reviewer = ReportVisionReviewer(
        SimpleNamespace(report_vision_model="vision-model", debug=False),  # type: ignore[arg-type]
        Workspace(),  # type: ignore[arg-type]
        agent_factory=Agent,
    )

    result = await reviewer.review("thread-1", "charts/revenue.png")

    assert result["requiresRevision"] is True
    assert result["issues"][0]["severity"] == "critical"
