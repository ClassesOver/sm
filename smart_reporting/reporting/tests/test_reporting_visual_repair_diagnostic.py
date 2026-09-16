from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.workflow.checkpoint import (
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


@pytest.mark.anyio
async def test_view_image_keeps_bounded_revision_diagnostic_when_execution_state_clears(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path)
    script_file = FileIdentity.model_validate(
        await binding.workspace.ahash_file("task-1", "charts/charts.py")
    )
    chart_file = FileIdentity.model_validate(
        await binding.workspace.ahash_file("task-1", "charts/chart.png")
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

    result = await toolkit.view_image(chart_file.path)
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


@pytest.mark.anyio
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
async def test_runner_returns_visual_repair_diagnostic_only_from_visualization_binding(
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

    class Registry:
        @asynccontextmanager
        async def bind(self, _context: object, _workspace: object):
            yield binding

    class Toolkit:
        def __init__(self, received_binding: object, *_args: object, **_kwargs: object) -> None:
            assert received_binding is binding
            self.tool_functions = ()
            self.submitted_receipt = receipt

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

    result = await runner.run(
        binding.context,
        binding.workspace,
        {},
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result.visual_repair_diagnostic == expected
