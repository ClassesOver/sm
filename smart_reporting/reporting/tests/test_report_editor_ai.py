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
        ("正文[[analysis:analysis_001]]", "polish", "report_editor_ai_protocol_marker"),
        ("正文\\[\\[analysis:analysis\\_001]]", "polish", "report_editor_ai_protocol_marker"),
        ("收入3600[[claim:claim-1]]", "polish", "report_editor_ai_protocol_marker"),
        ("收入3600\\[\\[claim:claim\\_1]]", "polish", "report_editor_ai_protocol_marker"),
        ("[[table:tbl-1]]", "polish", "report_editor_ai_protocol_marker"),
        ("[[/table:tbl-1]]", "polish", "report_editor_ai_protocol_marker"),
        ("\\[\\[/table:tbl\\_1]]", "polish", "report_editor_ai_protocol_marker"),
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


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_ai_rewrite_save_and_undo_revalidate_frozen_claim(tmp_path) -> None:
    """AI 改值只产生软状态，保存或撤销都不重写冻结事实。"""
    import hashlib

    from smart_reporting.report_editor.ai import ReportEditorAIService
    from smart_reporting.reporting.tests.test_trace_subject_validate import (
        _make_editor_with_subject,
    )

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    original = "收入3600万元。[[claim:claim-1]]"
    before = await editor.read_document(context)
    saved = await editor.save_draft(context, markdown=original, expected_sha256=before.sha256)

    class RewriteAgent:
        async def arun(self, _prompt, **_kwargs):
            yield SimpleNamespace(event="RunContent", content="收入3800万元。")

    ai = ReportEditorAIService(RewriteAgent())
    rewritten = "".join([
        chunk async for chunk in ai.stream_rewrite(
            context, selection="收入3600万元。", action="polish",
        )
    ]) + "[[claim:claim-1]]"
    changed = await editor.trace_validate(
        context, session, rewritten, hashlib.sha256(rewritten.encode()).hexdigest(),
    )
    assert changed["subjects"][0]["status"] == "stale"
    assert changed["subjects"][0]["factValue"] == 3600.0
    saved = await editor.save_draft(context, markdown=rewritten, expected_sha256=saved.sha256)
    assert (await editor.read_document(context)).markdown == rewritten
    undone = await editor.save_draft(context, markdown=original, expected_sha256=saved.sha256)
    restored = await editor.trace_validate(context, session, undone.markdown, undone.sha256)
    assert restored["subjects"][0]["status"] == "valid"
    assert restored["subjects"][0]["factValue"] == 3600.0
