"""分析项 durable 完成后 Task 收尾中断：新 attempt 以原 payload 幂等恢复。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.tools.toolkit import ReportingToolkit

FACT_PATH = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
OLD_EVIDENCE = "报表/智能分析/run-1/evidence/analysis_001/attempt-1/evidence.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _identity(path: str) -> dict[str, object]:
    return {"path": path, "size": 2, "sha256": "a" * 64}


def _recovery_toolkit() -> tuple[ReportingToolkit, dict[str, object]]:
    stored = {
        "analysisId": "analysis_001",
        "summary": "收入同比增长。",
        "datasetIds": ["dataset-1"],
        "evidencePaths": [OLD_EVIDENCE, FACT_PATH],
        "citationIds": ["citation-1"],
        "profileReadReceiptIds": [],
        "warnings": [],
        "chartIds": [],
        "evidenceFiles": [_identity(OLD_EVIDENCE), _identity(FACT_PATH)],
    }
    durable = SimpleNamespace(
        revision=1, payload={"analysisItems": {"analysis_001": stored}, "profileReadReceipts": []}
    )
    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1")),
        workspace=SimpleNamespace(
            batch_hash_files=AsyncMock(
                side_effect=lambda _thread, paths: [_identity(path) for path in paths]
            )
        ),
        finish_task=AsyncMock(return_value={"ok": True, "status": "accepted"}),
    )
    toolkit._finish_function = SimpleNamespace(name="finish_task")
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            # fresh attempt 签发新的输出目录；上一 attempt 的补证路径不在其中。
            "analysisOutputRoot": "报表/智能分析/run-1/evidence/analysis_001/attempt-2",
            "deterministicFactFiles": {"analysis_001": _identity(FACT_PATH)},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._ensure_registered_analysis_evidence = AsyncMock(return_value=(durable, []))
    toolkit._apply_durable = AsyncMock()
    toolkit._complete_phase_plan = lambda *_args: None
    toolkit._session_state = lambda *_args: {}
    return toolkit, stored


@pytest.mark.anyio
async def test_durable_completion_recovery_replays_prior_attempt_paths() -> None:
    toolkit, stored = _recovery_toolkit()
    recovered = {key: stored[key] for key in (
        "analysisId", "summary", "datasetIds", "evidencePaths", "citationIds",
        "profileReadReceiptIds", "warnings", "chartIds",
    )}

    result = await toolkit.complete_analysis_item(
        **recovered, run_context=RunContext(run_id="run-1", session_id="session-1")
    )

    assert result["ok"] is True
    assert result["status"] == "accepted"
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_new_evidence_outside_current_attempt_root_is_still_rejected() -> None:
    toolkit, stored = _recovery_toolkit()

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="新的总结。",
        datasetIds=["dataset-1"],
        evidencePaths=["报表/智能分析/run-1/evidence/analysis_001/attempt-9/x.json"],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_analysis_output_path_invalid"
