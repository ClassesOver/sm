from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent import toolkit as toolkit_module
from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import (
    ReportingCodeModeToolkit,
    _visual_repair_diagnostic,
)
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Workspace:
    def __init__(self, root: Path) -> None:
        self.identity = SimpleNamespace(workspace_key="workspace-a", root=root)
        self.files = {
            "charts/charts.py": {"path": "charts/charts.py", "size": 15, "sha256": "a" * 64},
            "charts/chart.png": {"path": "charts/chart.png", "size": 8, "sha256": "b" * 64},
        }

    async def ahash_file(self, _task_id: str, path: str) -> dict[str, object]:
        return self.files[path]


def _binding(tmp_path: Path, *, task_kind: str = "visualization") -> ReportingCodingTaskBinding:
    workspace = _Workspace(tmp_path)
    return ReportingCodingTaskBinding(
        ReportingCodingTaskContext(
            task_id="task-1",
            task_kind=cast(Literal["analysis", "visualization"], task_kind),
            code_mode_session_id="code-task-1",
            workspace_key="workspace-a",
            workspace_root=workspace.identity.root,
            script_path="charts/charts.py",
            authorized_read_paths=(),
            authorized_write_paths=("charts/charts.py", "charts/chart.png"),
            declared_output_paths=("charts/chart.png",),
            max_source_bytes=128 * 1024,
        ),
        workspace,  # type: ignore[arg-type]
    )


def test_view_image_projects_model_receipt_but_keeps_full_audit_receipt(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path)
    script_file = FileIdentity.model_validate(
        binding.workspace.files["charts/charts.py"]  # type: ignore[attr-defined]
    )
    chart_file = FileIdentity.model_validate(
        binding.workspace.files["charts/chart.png"]  # type: ignore[attr-defined]
    )
    binding.execution_receipt = ExecutionReceipt(
        runId="run-1", sourceFile=script_file, outputFiles=(chart_file,)
    )
    reviewed = ChartVisualInspectionReceipt(
        sourcePath=chart_file.path,
        sha256=chart_file.sha256,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            ChartVisualInspectionIssue(
                category="text_overlap",
                severity="critical",
                description="关键标签完全重叠。",
            ),
            ChartVisualInspectionIssue(
                category="missing_units",
                severity="warning",
                description="不应返回模型的 warning。",
            ),
        ),
        summary="不应返回模型的混合摘要。",
        suggestions=("无法确定归属的建议。",),
    )
    reviewer = AsyncMock()
    reviewer.review.return_value = reviewed
    toolkit = ReportingCodeModeToolkit(
        binding,
        SimpleNamespace(),
        ReportingLspProcessManager(),
        vision_reviewer=reviewer,
    )

    result = asyncio.run(toolkit.view_image(chart_file.path))

    # freshReviewCount 是本次新鲜审查计数，与回执投影无关。
    assert result.pop("freshReviewCount") == 1
    assert result == {
        "ok": True,
        "receipt": {
            "sourcePath": chart_file.path,
            "sha256": chart_file.sha256,
            "visualReviewStatus": "passed",
            "reviewed": True,
            "requiresRevision": True,
            "criticalIssues": [
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "关键标签完全重叠。",
                }
            ],
        },
    }
    assert binding.visual_inspection_receipts == {chart_file.path: reviewed}


def test_view_image_cache_uses_same_model_receipt_projection(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    script_file = FileIdentity.model_validate(
        binding.workspace.files["charts/charts.py"]  # type: ignore[attr-defined]
    )
    chart_file = FileIdentity.model_validate(
        binding.workspace.files["charts/chart.png"]  # type: ignore[attr-defined]
    )
    binding.execution_receipt = ExecutionReceipt(
        runId="run-1", sourceFile=script_file, outputFiles=(chart_file,)
    )
    reviewed = ChartVisualInspectionReceipt(
        sourcePath=chart_file.path,
        sha256=chart_file.sha256,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
        issues=(
            ChartVisualInspectionIssue(
                category="missing_units",
                severity="warning",
                description="缓存 warning 不得返回模型。",
            ),
        ),
        summary="缓存摘要不得返回模型。",
        warnings=("缓存 warnings 字段不得返回模型。",),
        suggestions=("缓存建议不得返回模型。",),
    )
    binding.visual_inspection_receipts[chart_file.path] = reviewed
    reviewer = AsyncMock()
    toolkit = ReportingCodeModeToolkit(
        binding,
        SimpleNamespace(),
        ReportingLspProcessManager(),
        vision_reviewer=reviewer,
    )

    result = asyncio.run(toolkit.view_image(chart_file.path))

    assert result["receipt"] == {
        "sourcePath": chart_file.path,
        "sha256": chart_file.sha256,
        "visualReviewStatus": "passed",
        "reviewed": True,
        "requiresRevision": False,
        "warningCount": 1,
        "message": "非阻断问题已记录，无需修改。",
    }
    reviewer.review.assert_not_awaited()


def test_compact_visual_receipt_still_marks_first_repair_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding(tmp_path)
    toolkit = ReportingCodeModeToolkit(
        binding,
        SimpleNamespace(),
        ReportingLspProcessManager(),
    )
    toolkit._awaiting_first_repair_run = True
    monkeypatch.setattr(toolkit_module, "log_tool_event", lambda **_kwargs: None)
    call = SimpleNamespace(
        function=SimpleNamespace(name="view_image"),
        result={"ok": True, "receipt": {"requiresRevision": True}},
        error=None,
        call_id="call-1",
    )

    asyncio.run(toolkit._update_tool_result(call))

    assert toolkit.first_repair_success is False
    assert toolkit._awaiting_first_repair_run is False


def test_delivery_state_exposes_only_critical_visual_failures(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    script_file = FileIdentity.model_validate(
        binding.workspace.files["charts/charts.py"]  # type: ignore[attr-defined]
    )
    chart_file = FileIdentity.model_validate(
        binding.workspace.files["charts/chart.png"]  # type: ignore[attr-defined]
    )
    binding.execution_receipt = ExecutionReceipt(
        runId="run-1", sourceFile=script_file, outputFiles=(chart_file,)
    )
    binding.visual_inspection_receipts[chart_file.path] = (
        ChartVisualInspectionReceipt(
            sourcePath=chart_file.path,
            sha256=chart_file.sha256,
            inspectionMode="vision",
            visualReviewStatus="passed",
            modelId="vision-test",
            reviewed=True,
            requiresRevision=True,
            issues=(
                ChartVisualInspectionIssue(
                    category="text_overlap",
                    severity="critical",
                    description="关键标签完全重叠。",
                ),
                ChartVisualInspectionIssue(
                    category="missing_units",
                    severity="warning",
                    description="不得进入交付状态的 warning。",
                ),
            ),
            summary="不得进入交付状态的摘要。",
            suggestions=("无法确定归属的建议。",),
        )
    )
    toolkit = ReportingCodeModeToolkit(
        binding,
        SimpleNamespace(),
        ReportingLspProcessManager(),
    )

    asyncio.run(toolkit.refresh_delivery_state())

    assert toolkit.delivery_state()["visualFailures"] == [
        {
            "path": chart_file.path,
            "paths": [chart_file.path],
                "summary": "",
            "issues": [
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "关键标签完全重叠。",
                }
            ],
            "suggestions": [],
        }
    ]


def test_visual_repair_diagnostic_summarizes_only_critical_issues() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/chart.png",
        sha256="b" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            ChartVisualInspectionIssue(
                category="text_overlap",
                severity="critical",
                description="关键标签完全重叠。",
            ),
            ChartVisualInspectionIssue(
                category="missing_units",
                severity="warning",
                description="非阻断单位问题。",
            ),
        ),
    )

    assert _visual_repair_diagnostic(receipt) == {
        "code": "report_visualization_review_failed",
        "message": "图表独立视觉审查要求修订。",
        "details": {
            "sourcePath": "charts/chart.png",
            "visualReviewStatus": "passed",
            "requiresRevision": True,
            "issueCategories": ["text_overlap"],
            "issueSeverities": ["critical"],
        },
    }


def test_view_image_keeps_bounded_revision_diagnostic_when_execution_state_clears(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path)
    script_file = FileIdentity.model_validate(
        binding.workspace.files["charts/charts.py"]  # type: ignore[attr-defined]
    )
    chart_file = FileIdentity.model_validate(
        binding.workspace.files["charts/chart.png"]  # type: ignore[attr-defined]
    )
    binding.execution_receipt = ExecutionReceipt(
        runId="run-1", sourceFile=script_file, outputFiles=(chart_file,)
    )
    reviewer = AsyncMock()
    reviewer.review.return_value = ChartVisualInspectionReceipt(
        sourcePath=chart_file.path,
        sha256=chart_file.sha256,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            {
                "category": "text_overlap",
                "severity": "critical",
                "description": "不得进入诊断的任意模型文本 /host/secret.png",
            },
        ),
        summary="不得进入诊断的任意模型摘要",
        suggestions=("不得进入诊断的任意模型建议",),
    )
    toolkit = ReportingCodeModeToolkit(
        binding,
        SimpleNamespace(),
        ReportingLspProcessManager(),
        vision_reviewer=reviewer,
    )

    result = asyncio.run(toolkit.view_image(chart_file.path))
    binding.clear_execution_state()

    assert result["ok"] is True
    assert binding.visual_repair_diagnostic == {
        "code": "report_visualization_review_failed",
        "message": "图表独立视觉审查要求修订。",
        "details": {
            "sourcePath": "charts/chart.png",
            "visualReviewStatus": "passed",
            "requiresRevision": True,
            "issueCategories": ["text_overlap"],
            "issueSeverities": ["critical"],
        },
    }
    assert "/host/secret.png" not in str(binding.visual_repair_diagnostic)
    assert binding.execution_receipt is None
    assert binding.visual_inspection_receipts == {}


@pytest.mark.parametrize(
    ("task_kind", "binding_diagnostic", "expected"),
    [
        (
            "visualization",
            {"code": "report_visualization_review_failed"},
            {"code": "report_visualization_review_failed"},
        ),
        ("analysis", {"code": "must-not-leak"}, None),
    ],
)
def test_runner_returns_visual_repair_diagnostic_only_from_visualization_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
    binding_diagnostic: dict[str, str],
    expected: dict[str, str] | None,
) -> None:
    binding = _binding(tmp_path, task_kind=task_kind)
    binding.visual_repair_diagnostic = binding_diagnostic
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    receipt = ExecutionReceipt(runId="run-1", sourceFile=script_file, outputFiles=())
    visual_receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/chart.png",
        sha256="b" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
        summary="完整审查结果。",
        warnings=("完整 warning 仍需保留。",),
    )
    if task_kind == "visualization":
        binding.visual_inspection_receipts[visual_receipt.source_path] = visual_receipt

    class Registry:
        @asynccontextmanager
        async def bind(self, _context: object, _workspace: object):
            yield binding

    class Toolkit:
        def __init__(self, received_binding: object, *_args: object, **_kwargs: object) -> None:
            assert received_binding is binding
            self.tool_functions = ()
            self.submitted_receipt = receipt
            self.terminal_failure = None

        async def refresh_delivery_state(self) -> None:
            return None

        async def require_current_receipt(self, received: ExecutionReceipt) -> None:
            assert received is receipt

    class Agent:
        tool_call_limit = 0

        async def arun(self, _prompt: str, **_kwargs: object) -> None:
            return None

    runtime = SimpleNamespace(shutdown=AsyncMock())
    monkeypatch.setattr(code_generation, "ReportingCodeModeToolkit", Toolkit)
    runner = ReportingCodeGenerationRunner(
        lambda _tools: Agent(),
        runtime,
        ReportingLspProcessManager(),
        registry=Registry(),  # type: ignore[arg-type]
        vision_reviewer=object(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        runner.run(
            binding.context,
            binding.workspace,
            {},
            run_context=RunContext(run_id="run-1", session_id="session-1"),
        )
    )

    assert result.visual_repair_diagnostic == expected
    assert result.visual_inspection_receipts == (
        (visual_receipt,) if task_kind == "visualization" else ()
    )
