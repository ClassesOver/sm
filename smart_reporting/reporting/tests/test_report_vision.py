from types import SimpleNamespace

import pytest
from agno.media import Image
from agno.tools.function import ToolResult

from smart_reporting.reporting.vision import ReportVisionReviewer


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

    class Agent:
        async def arun(self, _prompt: str, *, images: list[Image]):
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
