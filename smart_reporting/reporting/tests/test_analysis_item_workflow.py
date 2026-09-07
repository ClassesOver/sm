from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisEvidencePlan,
    AnalysisItemWorkflow,
    AnalysisScriptDraft,
    AnalysisSummaryDraft,
)
from smart_reporting.task_execution import MAX_READ_FILE_BYTES


def _instruction() -> dict[str, Any]:
    return {
        "currentAnalysisId": "analysis_001",
        "currentAnalysis": {
            "analysisId": "analysis_001",
            "managementQuestion": "收入构成如何？",
            "datasetIds": ["dataset-1"],
        },
        "analysisOutputRoot": "报表/智能分析/run-1/evidence/analysis_001",
        "deterministicFactFile": {
            "path": "报表/智能分析/run-1/facts/analysis_001.json",
            "size": len(_facts().encode("utf-8")),
            "sha256": "a" * 64,
        },
        "deterministicFacts": json.loads(_facts()),
        "datasets": [{"datasetId": "dataset-1", "path": "datasets/income.csv"}],
        "citationRegistry": [{"citationId": "citation-1", "datasetId": "dataset-1"}],
    }


def _facts() -> str:
    return json.dumps(
        {
            "analysisId": "analysis_001",
            "metrics": [],
            "derivedMetrics": [],
            "comparisons": [],
            "reconciliations": [],
            "warnings": [],
        }
    )


def _tool_result(**values: Any) -> dict[str, Any]:
    return {"ok": True, **values}


def _facts_read_result(content: str | None = None) -> dict[str, Any]:
    selected = content if content is not None else _facts()
    size = len(selected.encode("utf-8"))
    return _tool_result(
        content=selected,
        sha256="a" * 64,
        totalBytes=size,
        nextOffset=size,
        hasMore=False,
    )


@pytest.mark.anyio
async def test_analysis_item_workflow_keeps_five_stages_when_supplement_is_skipped() -> None:
    events: list[str] = []

    async def plan(payload: Mapping[str, Any], *, repair: bool) -> AnalysisEvidencePlan:
        assert repair is False
        events.append("plan")
        return AnalysisEvidencePlan(
            requiresSupplementalEvidence=False,
            reason="固定事实足够",
            missingFacts=(),
            script=None,
        )

    async def summarize(payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
        assert payload["supplementalEvidence"] is None
        events.append("summarize")
        return AnalysisSummaryDraft(summary="固定事实显示收入规模稳定。", warnings=())

    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        plan_evidence=plan,
        summarize=summarize,
        read_file=AsyncMock(return_value=_facts_read_result()),
        apply_patch=AsyncMock(),
        run_script=AsyncMock(),
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert result.stage_statuses == (
        ("read-facts", "completed"),
        ("plan-evidence", "completed"),
        ("execute-script", "skipped"),
        ("validate-evidence", "skipped"),
        ("complete-analysis", "completed"),
    )
    assert events == ["plan", "summarize"]
    workflow.apply_patch.assert_not_awaited()
    workflow.run_script.assert_not_awaited()
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["evidencePaths"] == []


@pytest.mark.anyio
async def test_analysis_item_workflow_executes_all_five_stages_in_order() -> None:
    events: list[str] = []
    evidence = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "门诊收入", "value": 80, "unit": "元"}],
            "reconciliations": [{"name": "收入构成对账", "passed": True}],
            "warnings": [],
        }
    )

    async def plan(payload: Mapping[str, Any], *, repair: bool) -> AnalysisEvidencePlan:
        events.append("repair" if repair else "plan")
        return AnalysisEvidencePlan(
            requiresSupplementalEvidence=True,
            reason="缺少收入类型构成",
            missingFacts=("收入类型构成",),
            script="print('write evidence')",
        )

    async def summarize(payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
        events.append("summarize")
        assert payload["supplementalEvidence"]["findings"][0]["name"] == "门诊收入"
        return AnalysisSummaryDraft(summary="门诊收入是主要收入来源。", warnings=())

    reads = AsyncMock(
        side_effect=[
            _facts_read_result(),
            _tool_result(content=evidence, sha256="b" * 64),
        ]
    )
    apply_patch = AsyncMock(
        side_effect=lambda **kwargs: (
            events.append("create")
            or _tool_result(
                artifacts=[
                    {
                        "path": "报表/智能分析/run-1/evidence/analysis_001/supplement.py",
                        "sha256": "c" * 64,
                    }
                ]
            )
        )
    )
    terminal = AsyncMock(
        side_effect=lambda **_kwargs: (
            events.append("execute") or _tool_result(exitCode=0, output="")
        )
    )
    complete = AsyncMock(
        side_effect=lambda **_kwargs: (
            events.append("complete") or _tool_result(status="accepted", taskFinished=True)
        )
    )
    workflow = AnalysisItemWorkflow(
        plan_evidence=plan,
        summarize=summarize,
        read_file=reads,
        apply_patch=apply_patch,
        run_script=terminal,
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert events == ["plan", "create", "execute", "summarize", "complete"]
    submitted_patch = apply_patch.await_args.kwargs["patch"]
    assert submitted_patch.endswith("+print('write evidence')\n")
    assert complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]


@pytest.mark.anyio
async def test_analysis_item_workflow_reads_large_supplemental_evidence_in_chunks() -> None:
    rows = [
        {"period": f"2025-{index:04d}", "value": index, "note": "x" * 96} for index in range(1_200)
    ]
    evidence = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "完整明细", "rows": rows}],
            "reconciliations": [{"name": "完整性对账", "passed": True}],
            "warnings": [],
        },
        separators=(",", ":"),
    )
    page_size = 64 * 1024
    evidence_reads = [
        _tool_result(
            content=evidence[offset : offset + page_size],
            sha256="b" * 64,
            totalBytes=len(evidence),
            nextOffset=min(len(evidence), offset + page_size),
            hasMore=offset + page_size < len(evidence),
        )
        for offset in range(0, len(evidence), page_size)
    ]
    summarize = AsyncMock(return_value=AnalysisSummaryDraft(summary="补充证据完整。", warnings=()))
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    read_file = AsyncMock(side_effect=[_facts_read_result(), *evidence_reads])
    workflow = AnalysisItemWorkflow(
        plan_evidence=AsyncMock(
            return_value=AnalysisEvidencePlan(
                requiresSupplementalEvidence=True,
                reason="需要完整明细",
                missingFacts=("完整明细",),
                script="print('evidence')",
            )
        ),
        summarize=summarize,
        read_file=read_file,
        apply_patch=AsyncMock(
            return_value=_tool_result(artifacts=[{"path": "x", "sha256": "c" * 64}])
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=complete,
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    compact_finding = summarize.await_args.args[0]["supplementalEvidence"]["findings"][0]
    assert compact_finding["columns"] == ["period", "value", "note"]
    assert len(compact_finding["rows"]) == len(rows)
    assert compact_finding["rows"][0] == ["2025-0000", 0, "x" * 96]
    assert compact_finding["rows"][-1] == ["2025-1199", 1199, "x" * 96]
    assert [call.kwargs["offset"] for call in read_file.await_args_list[1:]] == [
        *range(0, len(evidence), page_size),
    ]
    assert complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]


@pytest.mark.anyio
async def test_analysis_item_workflow_repairs_script_at_most_twice() -> None:
    repairs: list[bool] = []

    async def plan(_payload: Mapping[str, Any], *, repair: bool) -> AnalysisEvidencePlan:
        repairs.append(repair)
        return AnalysisEvidencePlan(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
            script=f"print({len(repairs)})",
        )

    script_reads = [
        _tool_result(
            content=f"print({index})\n",
            sha256=sha256 * 64,
            totalBytes=9,
            nextOffset=9,
            hasMore=False,
        )
        for index, sha256 in ((1, "b"), (2, "c"))
    ]
    read_file = AsyncMock(side_effect=[_facts_read_result(), *script_reads])
    summarize = AsyncMock(
        return_value=AnalysisSummaryDraft(summary="仅使用确定性事实完成摘要。", warnings=())
    )
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        plan_evidence=plan,
        summarize=summarize,
        read_file=read_file,
        apply_patch=AsyncMock(
            side_effect=[
                _tool_result(artifacts=[{"path": "supplement.py", "sha256": "b" * 64}]),
                _tool_result(artifacts=[{"path": "supplement.py", "sha256": "c" * 64}]),
                _tool_result(artifacts=[{"path": "supplement.py", "sha256": "d" * 64}]),
            ]
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=1, output="bad csv")),
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert repairs == [False, True, True]
    assert workflow.run_script.await_count == 3
    assert workflow.apply_patch.await_count == 3
    assert [call.kwargs["max_bytes"] for call in read_file.await_args_list[1:]] == [
        MAX_READ_FILE_BYTES,
        MAX_READ_FILE_BYTES,
    ]
    assert summarize.await_args.args[0]["supplementalEvidence"] is None
    assert any(
        "report_analysis_supplement_abandoned" in warning
        for warning in summarize.await_args.args[0]["evidenceWarnings"]
    )
    assert complete.await_args.kwargs["evidencePaths"] == []
    assert any(
        "report_analysis_supplement_abandoned" in warning
        for warning in complete.await_args.kwargs["warnings"]
    )


@pytest.mark.anyio
async def test_analysis_item_workflow_warns_and_completes_unreconciled_evidence() -> None:
    invalid = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "收入构成", "value": 80, "unit": "元"}],
            "reconciliations": [{"name": "收入构成对账", "passed": False}],
            "warnings": [],
        }
    )
    workflow = AnalysisItemWorkflow(
        plan_evidence=AsyncMock(
            return_value=AnalysisEvidencePlan(
                requiresSupplementalEvidence=True,
                reason="缺少收入构成",
                missingFacts=("收入构成",),
                script="print('evidence')",
            )
        ),
        summarize=AsyncMock(),
        read_file=AsyncMock(
            side_effect=[
                _facts_read_result(),
                *[_tool_result(content=invalid, sha256="b" * 64) for _ in range(3)],
            ]
        ),
        apply_patch=AsyncMock(
            return_value=_tool_result(artifacts=[{"path": "x", "sha256": "c" * 64}])
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert result.stage_statuses[-2:] == (
        ("validate-evidence", "completed"),
        ("complete-analysis", "completed"),
    )
    workflow.plan_evidence.assert_awaited_once()
    workflow.summarize.assert_awaited_once()
    workflow.complete.assert_awaited_once()
    assert workflow.complete.await_args.kwargs["evidencePaths"] == []
    assert any(
        "report_analysis_evidence_reconciliation_failed" in warning
        for warning in workflow.complete.await_args.kwargs["warnings"]
    )


@pytest.mark.anyio
async def test_analysis_item_workflow_reuses_durable_completion_payload_exactly() -> None:
    instruction = _instruction()
    instruction["durableAnalysisItem"] = {
        "analysisId": "analysis_001",
        "summary": "已冻结摘要",
        "datasetIds": ["dataset-1"],
        "evidencePaths": ["报表/智能分析/run-1/evidence/analysis_001/supplement.json"],
        "citationIds": ["citation-1"],
        "profileReadReceiptIds": [],
        "warnings": ["已冻结告警"],
        "chartIds": [],
    }
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        plan_evidence=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(return_value=_facts_read_result()),
        apply_patch=AsyncMock(),
        run_script=AsyncMock(),
        complete=complete,
    )

    result = await workflow.run(
        instruction, RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert result.stage_statuses[1:4] == (
        ("plan-evidence", "completed"),
        ("execute-script", "skipped"),
        ("validate-evidence", "skipped"),
    )
    workflow.plan_evidence.assert_not_awaited()
    workflow.summarize.assert_not_awaited()
    assert {
        key: value for key, value in complete.await_args.kwargs.items() if key != "run_context"
    } == instruction["durableAnalysisItem"]


@pytest.mark.anyio
async def test_analysis_item_workflow_preserves_planner_provider_error() -> None:
    provider_error = RuntimeError("provider unavailable")
    complete = AsyncMock()
    workflow = AnalysisItemWorkflow(
        plan_evidence=AsyncMock(side_effect=provider_error),
        summarize=AsyncMock(),
        read_file=AsyncMock(return_value=_facts_read_result()),
        apply_patch=AsyncMock(),
        run_script=AsyncMock(),
        complete=complete,
    )

    with pytest.raises(RuntimeError) as raised:
        await workflow.run(
            _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
        )

    assert raised.value is provider_error
    complete.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_item_workflow_reads_deterministic_facts_in_chunks() -> None:
    content = _facts()
    split = len(content) // 2
    reads = AsyncMock(
        side_effect=[
            _tool_result(
                content=content[:split],
                sha256="a" * 64,
                totalBytes=len(content),
                nextOffset=split,
                hasMore=True,
            ),
            _tool_result(
                content=content[split:],
                sha256="a" * 64,
                totalBytes=len(content),
                nextOffset=len(content),
                hasMore=False,
            ),
        ]
    )
    workflow = AnalysisItemWorkflow(
        plan_evidence=AsyncMock(
            return_value=AnalysisEvidencePlan(
                requiresSupplementalEvidence=False,
                reason="固定事实足够",
                missingFacts=(),
                script=None,
            )
        ),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="固定事实摘要", warnings=())),
        read_file=reads,
        apply_patch=AsyncMock(),
        run_script=AsyncMock(),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    assert [call.kwargs["offset"] for call in reads.await_args_list] == [0, split]


def test_evidence_plan_normalizes_omitted_empty_missing_facts() -> None:
    plan = AnalysisEvidencePlan.model_validate(
        {
            "requiresSupplementalEvidence": False,
            "reason": "固定事实已足够。",
            "script": None,
        }
    )

    assert plan.missing_facts == ()


def test_analysis_script_models_do_not_impose_an_artificial_length_limit() -> None:
    plan_script_schema = AnalysisEvidencePlan.model_json_schema()["properties"]["script"]
    draft_script_schema = AnalysisScriptDraft.model_json_schema()["properties"]["script"]

    assert "maxLength" not in json.dumps(plan_script_schema)
    assert "maxLength" not in json.dumps(draft_script_schema)


def test_evidence_decision_normalizes_omitted_empty_missing_facts() -> None:
    decision = AnalysisEvidenceDecision.model_validate(
        {
            "requiresSupplementalEvidence": False,
            "reason": "固定事实已足够。",
        }
    )

    assert decision.missing_facts == ()


def test_analysis_item_workflow_preserves_structured_tool_error_for_repair() -> None:
    with pytest.raises(ReportingError) as raised:
        AnalysisItemWorkflow._require_ok(
            {
                "ok": False,
                "code": "report_analysis_write_intent_invalid",
                "message": "参数不符合公开 schema。",
                "details": {"path": "arguments.patch", "validator": "minLength"},
            },
            default_code="report_analysis_script_write_failed",
        )

    assert raised.value.details == {
        "path": "arguments.patch",
        "validator": "minLength",
    }
    assert AnalysisItemWorkflow._repair_error(raised.value) == {
        "code": "report_analysis_write_intent_invalid",
        "message": "参数不符合公开 schema。",
        "details": {"path": "arguments.patch", "validator": "minLength"},
    }
