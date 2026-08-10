import json
from types import SimpleNamespace

import pytest

from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import ReportWorkspaceTaskToolkit
from agentos_dev.coding.reporting.vision import ReportVisionAssessment, ReportVisionReviewer
from agentos_dev.settings import AgentSettings
from agentos_dev.workspace import WorkspaceError


class _EmptyExecutionRepository:
    async def list_executions(self, _external_run_id: str) -> list[object]:
        return []


class _VisionAgent:
    def __init__(self, content=None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls = []

    async def arun(self, prompt, *, images):
        self.calls.append({"prompt": prompt, "images": images})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.content)


def _settings(**overrides) -> AgentSettings:
    values = {
        "OPENAI_API_KEY": "test-key",
        "AGENT_REPORT_VISION_MODEL": "vision-model",
        **overrides,
    }
    return AgentSettings.from_environment(values, load_env_file=False)


@pytest.mark.anyio
async def test_visual_reviewer通过workspace安全读取并返回纯结构化反馈(tmp_path) -> None:
    workspace_service = service(tmp_path)
    content = b"\x89PNG\r\n\x1a\n" + b"chart-content"
    workspace_service.upload("thread", "analysis/charts/trend.png", content)
    assessment = ReportVisionAssessment(
        summary="图表主体可见，但右侧标签被截断。",
        requiresRevision=False,
        criticalIssues=["右侧数据标签被画布边界截断"],
        warnings=["图例与绘图区间距较小"],
        suggestions=["扩大右侧留白后重新导出"],
    )
    agents = []

    def agent_factory():
        agent = _VisionAgent(assessment)
        agents.append(agent)
        return agent

    reviewer = ReportVisionReviewer(
        _settings(),
        workspace_service,
        agent_factory=agent_factory,
    )

    result = await reviewer.review("thread", "analysis/charts/trend.png", detail="original")

    assert result == {
        "ok": True,
        "status": "reviewed",
        "reviewed": True,
        "modelId": "vision-model",
        "summary": "图表主体可见，但右侧标签被截断。",
        "requiresRevision": True,
        "criticalIssues": ["右侧数据标签被画布边界截断"],
        "warnings": ["图例与绘图区间距较小"],
        "suggestions": ["扩大右侧留白后重新导出"],
    }
    assert len(agents) == 1
    assert "只审查图表的呈现质量" in agents[0].calls[0]["prompt"]
    reviewed_image = agents[0].calls[0]["images"][0]
    assert reviewed_image.content == content
    assert reviewed_image.mime_type == "image/png"
    assert reviewed_image.detail == "high"
    assert "images" not in result


@pytest.mark.anyio
async def test_visual_reviewer模型异常返回非阻断告警且不泄露异常(tmp_path) -> None:
    workspace_service = service(tmp_path)
    workspace_service.upload(
        "thread",
        "analysis/charts/trend.png",
        b"\x89PNG\r\n\x1a\n" + b"chart-content",
    )
    reviewer = ReportVisionReviewer(
        _settings(),
        workspace_service,
        agent_factory=lambda: _VisionAgent(error=RuntimeError("internal secret endpoint")),
    )

    result = await reviewer.review("thread", "analysis/charts/trend.png")

    assert result["ok"] is True
    assert result["status"] == "warning"
    assert result["reviewed"] is False
    assert result["code"] == "report_vision_unavailable"
    assert result["modelId"] == "vision-model"
    assert result["retryable"] is False
    assert "internal secret endpoint" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.anyio
async def test_visual_reviewer在模型调用前保留图片签名校验(tmp_path) -> None:
    workspace_service = service(tmp_path)
    workspace_service.upload("thread", "analysis/charts/fake.png", b"not-a-png")
    factory_calls = 0

    def agent_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _VisionAgent()

    reviewer = ReportVisionReviewer(
        _settings(),
        workspace_service,
        agent_factory=agent_factory,
    )

    with pytest.raises(WorkspaceError, match="签名"):
        await reviewer.review("thread", "analysis/charts/fake.png")

    assert factory_calls == 0


def test_visual_reviewer每次创建无工具无历史无数据库的短生命周期agent(tmp_path) -> None:
    reviewer = ReportVisionReviewer(_settings(), service(tmp_path))

    first = reviewer._new_agent()
    second = reviewer._new_agent()

    assert first is not second
    assert first.id == "report-vision-reviewer"
    assert first.model.id == "vision-model"
    assert first.model.timeout == 900
    assert first.model.max_retries == 0
    assert first.model.retries == 2
    assert first.tools == []
    assert first.db is None
    assert first.add_history_to_context is False
    assert first.num_history_runs is None
    assert first.enable_session_summaries is False
    assert first.store_media is False
    assert first.store_history_messages is False
    assert first.output_schema is ReportVisionAssessment


@pytest.mark.anyio
async def test_report_view_image工具只返回视觉审查文字(monkeypatch, tmp_path) -> None:
    calls = []

    class Reviewer:
        async def review(self, thread_id, path, *, detail):
            calls.append((thread_id, path, detail))
            return {
                "ok": True,
                "status": "reviewed",
                "reviewed": True,
                "modelId": "vision-model",
                "summary": "可读",
                "requiresRevision": False,
                "criticalIssues": [],
                "warnings": [],
                "suggestions": [],
            }

    toolkit = ReportWorkspaceTaskToolkit(
        service(tmp_path),
        _EmptyExecutionRepository(),
        vision_reviewer=Reviewer(),
    )

    async def direct_invoke(_tool_name, _arguments, call, _run_context):
        return await call(SimpleNamespace(thread_id="thread"))

    monkeypatch.setattr(toolkit, "_invoke", direct_invoke)

    result = await toolkit.view_image("analysis/charts/trend.png", "original")

    assert calls == [("thread", "analysis/charts/trend.png", "original")]
    assert result["status"] == "reviewed"
    assert "images" not in result
