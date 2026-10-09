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
    recovered = {
        key: stored[key]
        for key in (
            "analysisId",
            "summary",
            "datasetIds",
            "evidencePaths",
            "citationIds",
            "profileReadReceiptIds",
            "warnings",
            "chartIds",
        )
    }

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


@pytest.mark.anyio
async def test_fresh_completion_binds_computation_record_and_script_identity() -> None:
    """有补充 evidence 与执行回执时，计算记录和脚本身份来自同一回执写入 payload。"""

    from smart_reporting.reporting.code_agent.context import ExecutionReceipt

    toolkit, _stored = _recovery_toolkit()
    durable = await toolkit._durable_state(None)
    durable.payload["analysisItems"] = {}
    toolkit._apply_durable = AsyncMock(return_value=durable)
    evidence = "报表/智能分析/run-1/evidence/analysis_001/attempt-2/evidence.json"
    script = {"path": "报表/智能分析/run-1/scripts/analysis_001.py", "size": 10, "sha256": "c" * 64}
    receipt = ExecutionReceipt(
        runId="exec-1",
        sourceFile=script,
        outputFiles=(_identity(evidence),),
        environment={"python": "3.12.0"},
    )
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        dependencies={"AgentOS 任务执行": SimpleNamespace(execution_receipt=receipt)},
    )

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入同比增长。",
        datasetIds=["dataset-1"],
        evidencePaths=[evidence],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
        run_context=run_context,
    )

    assert result["ok"] is True
    payload = toolkit._apply_durable.await_args.kwargs["payload"]
    assert payload["computationRecord"]["executionId"] == "exec-1"
    assert payload["computationScriptFile"] == script


def _receipt_and_paths():
    from smart_reporting.reporting.code_agent.context import ExecutionReceipt

    evidence = "报表/智能分析/run-1/evidence/analysis_001/attempt-2/evidence.json"
    script = {"path": "报表/智能分析/run-1/scripts/analysis_001.py", "size": 10, "sha256": "c" * 64}
    receipt = ExecutionReceipt(
        runId="exec-2",
        sourceFile=script,
        outputFiles=(_identity(evidence),),
        environment={"python": "3.12.0"},
    )
    return receipt, evidence, script


@pytest.mark.anyio
async def test_workflow_receipt_builds_computation_record_with_production_binding() -> None:
    """生产中任务依赖是 Mapping，不带回执；固定 Workflow 显式传入的已核验回执生效。"""

    toolkit, _stored = _recovery_toolkit()
    durable = await toolkit._durable_state(None)
    durable.payload["analysisItems"] = {}
    toolkit._apply_durable = AsyncMock(return_value=durable)
    receipt, evidence, script = _receipt_and_paths()
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        dependencies={"AgentOS 任务执行": {"reportingPhase": "analysis"}},
    )

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入同比增长。",
        datasetIds=["dataset-1"],
        evidencePaths=[evidence],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
        run_context=run_context,
        _execution_receipt=receipt,
    )

    assert result["ok"] is True
    payload = toolkit._apply_durable.await_args.kwargs["payload"]
    assert payload["computationRecord"]["executionId"] == "exec-2"
    assert payload["computationScriptFile"] == script


@pytest.mark.anyio
async def test_recovery_replay_keeps_server_built_computation_record() -> None:
    """恢复重放没有执行回执；durable 中服务端构造的计算记录不能让全等比对失败。"""

    toolkit, stored = _recovery_toolkit()
    receipt, _evidence, script = _receipt_and_paths()
    stored["computationRecord"] = {"computationId": "comp-" + "d" * 16, "executionId": "exec-2"}
    stored["computationScriptFile"] = script
    recovered = {
        key: stored[key]
        for key in (
            "analysisId", "summary", "datasetIds", "evidencePaths", "citationIds",
            "profileReadReceiptIds", "warnings", "chartIds",
        )
    }

    result = await toolkit.complete_analysis_item(
        **recovered, run_context=RunContext(run_id="run-1", session_id="session-1")
    )

    assert result["ok"] is True
    assert result["status"] == "accepted"
    toolkit._apply_durable.assert_not_awaited()
