from __future__ import annotations

from datetime import date
from types import MethodType, SimpleNamespace

import pytest
from agno.db.in_memory import InMemoryDb
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting.contract import ReportRequestEnvelope, ReportingWorkflowInput
from agentos_dev.coding.reporting.hospital_operation.domains import DOMAIN_CODES
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.workflow.runtime import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    NormalizedReportPrompt,
    ReportWorkflowRuntime,
)


def _runtime_with_normalized(value: NormalizedReportPrompt) -> ReportWorkflowRuntime:
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._request_normalizer = object()

    async def run_planner(self, _agent, _payload, _context):
        return value

    runtime._run_planner = MethodType(run_planner, runtime)
    return runtime


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="thread-1", user_id="user-1")


def test_workflow_input严格区分prompt与envelope():
    assert (
        ReportingWorkflowInput.model_validate(
            {"version": "1", "prompt": "分析2025年经营情况"}
        ).prompt
        == "分析2025年经营情况"
    )
    assert (
        ReportingWorkflowInput.model_validate(
            {
                "version": "1",
                "reportGoal": "分析经营情况",
                "reportType": "comprehensive",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ).report_goal
        == "分析经营情况"
    )
    with pytest.raises(ValueError):
        ReportingWorkflowInput.model_validate(
            {
                "version": "1",
                "prompt": "分析经营情况",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        )


@pytest.mark.anyio
async def test_envelope首步直接校验且不调用模型():
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="不应调用"))

    result = await runtime.normalize_report_request(
        StepInput(
            input={
                "version": "1",
                "reportGoal": "分析经营情况",
                "reportType": "comprehensive",
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ),
        _context(),
    )

    assert result.content["reportGoal"] == "分析经营情况"
    assert result.content["reportType"] == "comprehensive"
    assert result.content["domains"] == list(DOMAIN_CODES)
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
async def test_envelope未提供report_type时由领域范围确定性推导():
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="不应调用"))

    result = await runtime.normalize_report_request(
        StepInput(
            input={
                "version": "1",
                "reportGoal": "分析收入情况",
                "domains": ["income"],
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
            }
        ),
        _context(),
    )

    assert result.content["reportType"] == "topic"
    assert result.content["domains"] == ["income"]


@pytest.mark.anyio
async def test_prompt单个明确年份转换全年并保持原文():
    prompt = "瑞金医院2025年综合运营报告，涵盖收入、预算、全成本和工作量"
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="请提供期间"))

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": prompt}), _context()
    )

    assert result.content["reportGoal"] == prompt
    assert result.content["reportType"] == "comprehensive"
    assert result.content["domains"] == list(DOMAIN_CODES)
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
async def test_整体综合报告默认六域且成本短词不触发专题澄清():
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="不应调用"))

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": "生成瑞金医院2025年整体运营成本分析报告"}),
        _context(),
    )

    assert result.content["reportType"] == "comprehensive"
    assert result.content["domains"] == list(DOMAIN_CODES)


@pytest.mark.anyio
async def test_成本专题仍要求明确全成本或费控():
    runtime = _runtime_with_normalized(NormalizedReportPrompt(clarificationQuestion="不应调用"))

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": "分析瑞金医院2025年成本"}), _context()
    )

    assert result.content == {"clarificationQuestion": "请明确主分析领域：全成本或费控。"}


@pytest.mark.anyio
@pytest.mark.parametrize("prompt", ["分析整体经营情况", "对比2024年和2025年经营情况"])
async def test_prompt缺失或冲突期间返回补充问题(prompt):
    runtime = _runtime_with_normalized(
        NormalizedReportPrompt(clarificationQuestion="请明确唯一的分析期间。")
    )

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": prompt}), _context()
    )

    assert result.content == {"clarificationQuestion": "请明确唯一的分析期间。"}


@pytest.mark.anyio
async def test_prompt缺失显式报告类型时按领域自动视为专题():
    runtime = _runtime_with_normalized(
        NormalizedReportPrompt(period={"start": "2025-01-01", "end": "2025-12-31"})
    )

    result = await runtime.normalize_report_request(
        StepInput(input={"version": "1", "prompt": "分析2025年收入"}), _context()
    )

    assert result.content["reportType"] == "topic"
    assert result.content["domains"] == ["income"]


@pytest.mark.anyio
async def test_coding成稿前才绑定已批准提纲和服务端品牌(monkeypatch):
    events = []
    document_contexts = []

    class ReportTools:
        async def bind_document_context(self, job_id, context, *, run_context):
            events.append("bind")
            assert job_id == "job-1"
            assert run_context.session_id == "thread-1"
            document_contexts.append(context)

    class FixedDateTime:
        calls = 0

        @classmethod
        def now(cls, timezone):
            assert timezone.key == "Asia/Shanghai"
            cls.calls += 1
            return SimpleNamespace(date=lambda: date(2026, 8, 4 + cls.calls))

    state = {}
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_tools = ReportTools()
    runtime._state = lambda _context: state
    runtime._workflow_result = lambda _state: {"jobId": "job-1"}
    runtime._profile = lambda _context: SimpleNamespace(
        document_branding=SimpleNamespace(
            organization_name="测试机构",
            generated_by_label="测试平台生成",
            watermark_text="测试水印",
        )
    )
    runtime._envelope = lambda _context: SimpleNamespace(
        period=SimpleNamespace(start=date(2025, 1, 1), end=date(2025, 12, 31))
    )
    runtime._tool_context = lambda context: context

    async def run_coding(_context, *, feedback):
        events.append("coding")
        assert feedback is None
        return {"status": "accepted"}

    runtime._run_coding = run_coding
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime._frozen_outline",
        lambda _state: SimpleNamespace(
            title="已批准报告",
            sections=(
                SimpleNamespace(code="section_001", title="第一章"),
                SimpleNamespace(code="section_002", title="第二章"),
            ),
        ),
    )
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime.datetime",
        FixedDateTime,
    )

    result = await runtime.run_coding_analysis(
        StepInput(input={}),
        RunContext(run_id="run-1", session_id="thread-1", session_state={}),
    )
    repeated = await runtime.run_coding_analysis(
        StepInput(input={}),
        RunContext(run_id="run-1", session_id="thread-1", session_state={}),
    )

    assert events == ["bind", "coding", "bind", "coding"]
    assert result.content == {"status": "accepted"}
    assert repeated.content == result.content
    assert FixedDateTime.calls == 1
    assert document_contexts == [document_contexts[0], document_contexts[0]]
    assert document_contexts[0] == {
        "title": "已批准报告",
        "periodLabel": "2025-01-01 至 2025-12-31",
        "organizationName": "测试机构",
        "generatedByLabel": "测试平台生成",
        "watermarkText": "测试水印",
        "generatedDate": "2026-08-05",
        "sections": [
            {"code": "section_001", "title": "第一章"},
            {"code": "section_002", "title": "第二章"},
        ],
    }


@pytest.mark.anyio
async def test_rejection_feedback在同一首步重试并保持原始目标():
    prompt = "分析整体经营情况"
    runtime = _runtime_with_normalized(
        NormalizedReportPrompt(period={"start": "2025-01-01", "end": "2025-12-31"})
    )

    result = await runtime.normalize_report_request(
        StepInput(
            input={"version": "1", "prompt": prompt},
            additional_data={"rejection_feedback": "生成综合报告，分析2025年"},
        ),
        _context(),
    )

    assert result.content["reportGoal"] == prompt
    assert result.content["reportType"] == "comprehensive"
    assert result.content["period"] == {"start": "2025-01-01", "end": "2025-12-31"}


@pytest.mark.anyio
async def test_发布签发是workflow审核后的正式末步骤():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = InMemoryDb()
    calls = []

    async def issue(scope, session_id, run_id, output):
        calls.append((scope, session_id, run_id, output))
        return {
            "path": "reports/result.pdf",
            "size": 12,
            "sha256": "a" * 64,
            "word": {
                "path": "reports/result.docx",
                "size": 13,
                "sha256": "b" * 64,
            },
        }

    workflow = runtime.workflow(publication_issuer=issue)
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={},
    )
    content = {
        "reportId": "report-1",
        "revision": 1,
        "pdfPath": "reports/internal.pdf",
        "pdfSize": 12,
        "pdfSha256": "a" * 64,
        "wordPath": "reports/internal.docx",
        "wordSize": 13,
        "wordSha256": "b" * 64,
    }

    async def pass_publication_gate(_step_input, _run_context):
        calls.append("gate")
        return StepOutput(content={**content, "formalReleaseAllowed": True})

    runtime.publish_report = pass_publication_gate

    result = await workflow.steps[-1].executor(StepInput(previous_step_content=content), context)

    assert workflow.steps[-1].step_id == "finalize-publication"
    assert result.content == {
        "path": "reports/result.pdf",
        "size": 12,
        "sha256": "a" * 64,
        "word": {
            "path": "reports/result.docx",
            "size": 13,
            "sha256": "b" * 64,
        },
    }
    assert calls == [
        "gate",
        (
            {
                "external_run_id": "workflow-run",
                "thread_id": "workflow-session",
                "user_id": "user-1",
            },
            "workflow-session",
            "workflow-run",
            {**content, "formalReleaseAllowed": True},
        ),
    ]


@pytest.mark.anyio
async def test_发布门禁阻断时最终步骤不调用签发器():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = InMemoryDb()
    calls: list[str] = []

    async def issue(*_args):
        calls.append("issuer")
        raise AssertionError("门禁阻断后不应调用签发器")

    workflow = runtime.workflow(publication_issuer=issue)
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={},
    )

    async def block_publication_gate(_step_input, _run_context):
        calls.append("gate")
        return StepOutput(
            content={
                "formalReleaseAllowed": False,
                "reportId": "report-1",
                "revision": 1,
                "publicationGate": {"issues": [{"code": "snapshot_changed"}]},
            }
        )

    runtime.publish_report = block_publication_gate
    result = await workflow.steps[-1].executor(
        StepInput(previous_step_content={}), context
    )

    assert result.content["status"] == "formal_release_blocked"
    assert calls == ["gate"]


@pytest.mark.anyio
async def test_正式发布拒绝验收后被替换的pdf():
    runtime = object.__new__(ReportWorkflowRuntime)

    class Workspace:
        async def ahash_file(self, thread_id, path):
            assert thread_id == "thread-1"
            if path == "reports/result.pdf":
                return {"path": path, "size": 7, "sha256": "b" * 64}
            assert path == "reports/result.docx"
            return {"path": path, "size": 13, "sha256": "c" * 64}

    runtime.workspace_service = Workspace()

    with pytest.raises(ReportingError) as raised:
        await runtime.issue_cli_publication(
            {"thread_id": "thread-1"},
            "session-1",
            "run-1",
            {
                "reportId": "report-1",
                "revision": 1,
                "pdfPath": "reports/result.pdf",
                "pdfSize": 12,
                "pdfSha256": "a" * 64,
                "wordPath": "reports/result.docx",
                "wordSize": 13,
                "wordSha256": "c" * 64,
            },
        )

    assert raised.value.code == "report_artifact_changed"


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["validation", "word_path", "hash"])
async def test_双格式发布后的任一处理异常都会清理整个revision(monkeypatch, failure_stage):
    pdf_path = "reports/revision-1/report.pdf"
    word_path = "reports/revision-1/report.docx"
    state = {
        REPORT_ARTIFACTS_STATE_KEY: {
            "draft": {
                "reportId": "report-1",
                "revision": 1,
                "codingTaskKey": "task-1",
                "datasetSnapshotHash": "a" * 64,
                "effectiveProfileHash": "b" * 64,
                "markdown": {
                    "path": "report.md",
                    "mediaType": "text/markdown",
                    "size": 1,
                    "sha256": "c" * 64,
                },
                "citations": [
                        {
                            "citationId": "citation_001",
                            "datasetId": "dataset-1",
                            "requirementId": "requirement-1",
                            "snapshotHash": "e" * 64,
                        }
                ],
                "sections": ["section_001"],
            }
        },
        REPORT_DATASET_LINEAGE_STATE_KEY: [
            {
                "datasetId": "dataset-1",
                "sourceId": "source-1",
                "requirementId": "requirement-1",
                "sqlHash": "d" * 64,
                "rowCount": 1,
                "size": 1,
                "sha256": "e" * 64,
            }
        ],
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [
            {
                "requirementId": "requirement-1",
                "sourceId": "source-1",
                "tables": [
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "periodGranularity": "date",
                        "measureColumns": ["amount"],
                    }
                ],
                "dimensionColumns": ["month"],
                "grainColumns": ["month"],
            }
        ],
        REPORT_ANALYSIS_PLAN_STATE_KEY: [
            {
                "code": "income",
                "description": "分析收入",
                "requirementIds": ["requirement-1"],
            }
        ],
    }
    discarded = []

    class ReportTools:
        async def bind_citation_presentations(self, *_args, **_kwargs):
            return None

        async def _render_report_pair(self, *_args, **_kwargs):
            if failure_stage == "validation":
                return {"wordPath": word_path, "validation": {"ok": False}}
            if failure_stage == "word_path":
                return {"validation": {"ok": True}}
            return {"wordPath": word_path, "validation": {"ok": True}}

        async def discard_report_revision(self, *args, **_kwargs):
            discarded.append(args)

    class Workspace:
        async def ahash_file(self, _thread_id, _path):
            raise RuntimeError("hash failed")

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_tools = ReportTools()
    runtime.workspace_service = Workspace()
    runtime._state = lambda _context: state
    runtime._workflow_result = lambda _state: {
        "jobId": "job-1",
        "revision": 0,
        "markdownPath": "report.md",
    }
    runtime._envelope = lambda _context: SimpleNamespace(period=None)
    runtime._tool_context = lambda context: context
    runtime._scope = lambda _context: {"threadId": "thread-1"}
    runtime._data_shapes = lambda _context: ()
    runtime._snapshots = lambda _context: ()
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime._frozen_outline",
        lambda _state: SimpleNamespace(title="报告"),
    )
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime._report_pdf_path",
        lambda *_args: pdf_path,
    )
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime._coding_observed_data_facts",
        lambda *_args: (),
    )
    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime._citation_presentations",
        lambda **_kwargs: {},
    )

    expected_error = RuntimeError if failure_stage == "hash" else ReportingError
    with pytest.raises(expected_error):
        await runtime._render_and_validate(
            RunContext(run_id="run-1", session_id="thread-1", session_state=state)
        )

    assert discarded == [("job-1", pdf_path, word_path)]
