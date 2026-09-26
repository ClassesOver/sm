from __future__ import annotations

from types import SimpleNamespace

import pytest

from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.models import ReportingError


def _context() -> ReportEditorContext:
    return ReportEditorContext(
        reportId="report-1",
        revision=2,
        jobId="job-1",
        workflowRunId="run-1",
        markdownPath="reports/revision-2/report.md",
        job={"jobId": "job-1"},
        scope={
            "runId": "run-1",
            "externalRunId": "external-1",
            "sessionId": "workflow-session",
            "callerThreadId": "caller-thread",
            "threadId": "workspace-1",
            "userId": "user-1",
            "database": "database-1",
            "companyId": "company-1",
            "threadLeaseKey": "lease-1",
        },
    )


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def arun(self, prompt: str, **kwargs: object):
        self.calls.append((prompt, kwargs))
        yield SimpleNamespace(event="RunContent", content="改写后的")
        yield SimpleNamespace(event="ToolCallStarted", content="ignored")
        yield SimpleNamespace(event="RunContent", content="正文")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("selection", "action", "code"),
    [
        ("  ", "polish", "report_editor_ai_selection_required"),
        ("正文", "unknown", "report_editor_ai_action_invalid"),
        ("x" * 12001, "polish", "report_editor_ai_selection_too_large"),
        (
            "[[section:summary]]\n正文",
            "polish",
            "report_editor_ai_protocol_marker",
        ),
        ("正文[[citation:x]]", "polish", "report_editor_ai_protocol_marker"),
        # 编辑器以 Markdown 序列化选区，协议标记以转义形态到达。
        ("正文\\[\\[citation:x\\_1]]", "polish", "report_editor_ai_protocol_marker"),
    ],
)
async def test_report_editor_ai_validation_rejects_invalid_selection_before_model_call(
    selection: str,
    action: str,
    code: str,
) -> None:
    from smart_reporting.report_editor.ai import ReportEditorAIService

    agent = _FakeAgent()
    service = ReportEditorAIService(agent)

    with pytest.raises(ReportingError) as raised:
        _ = [
            chunk
            async for chunk in service.stream_rewrite(
                _context(), selection=selection, action=action
            )
        ]

    assert raised.value.code == code
    assert agent.calls == []


@pytest.mark.anyio
async def test_report_editor_ai_streaming_forwards_only_content_events() -> None:
    from smart_reporting.report_editor.ai import ReportEditorAIService

    agent = _FakeAgent()
    service = ReportEditorAIService(agent)

    chunks = [
        chunk
        async for chunk in service.stream_rewrite(
            _context(), selection="原始正文", action="professional"
        )
    ]

    assert chunks == ["改写后的", "正文"]
    prompt, kwargs = agent.calls[0]
    assert "原始正文" in prompt
    assert "专业报告语气" in prompt
    assert "只返回改写后的 Markdown" in prompt
    assert kwargs == {
        "add_history_to_context": False,
        "session_id": "report-editor:report-1:2:user-1",
        "stream": True,
        "stream_events": True,
        "user_id": "user-1",
    }
