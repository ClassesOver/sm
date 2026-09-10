from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from unittest.mock import ANY, AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput
from loguru import logger
from pydantic import ValidationError

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import analysis_item_workflow as item_workflow
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult


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


def _code_result(
    sha256: str = "c" * 64,
    *,
    path: str = "报表/智能分析/run-1/evidence/analysis_001/supplement.py",
) -> CodeGenerationResult:
    return CodeGenerationResult(FileIdentity(path=path, size=1, sha256=sha256))


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
async def test_analysis_item_stage_reports_started_and_completed_progress_once() -> None:
    state = item_workflow._AnalysisItemState(instruction=_instruction())

    async def complete_stage() -> StepOutput:
        state.statuses["read-facts"] = "completed"
        return StepOutput(content={})

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")
    try:
        await AnalysisItemWorkflow._timed_stage("read-facts", state, complete_stage())
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert log_text.count("report_analysis_item_stage_started") == 1
    assert log_text.count("report_analysis_item_stage_completed") == 1
    assert "stage_name=read-facts" in log_text
    assert "analysis_id=analysis_001" in log_text
    assert "status=completed" in log_text


@pytest.mark.anyio
async def test_cancelled_analysis_item_stage_does_not_report_completed_progress() -> None:
    state = item_workflow._AnalysisItemState(instruction=_instruction())

    async def cancel_stage() -> StepOutput:
        raise asyncio.CancelledError

    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")
    try:
        with pytest.raises(asyncio.CancelledError):
            await AnalysisItemWorkflow._timed_stage("read-facts", state, cancel_stage())
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert log_text.count("report_analysis_item_stage_started") == 1
    assert "report_analysis_item_stage_completed" not in log_text


def test_analysis_summary_projection_bounds_high_cardinality_evidence_with_reconciliation() -> None:
    rows = [
        [f"group-{index:05d}", 100 + index, 100, index if index % 2 == 0 else -index]
        for index in range(19_637)
    ]
    payload = {
        "currentAnalysis": {"managementQuestion": "主要正负贡献是什么？"},
        "deterministicFacts": {"metrics": []},
        "supplementalEvidence": {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [
                {"name": "按院区汇总", "columns": ["area", "change"], "rows": [["总部", 8]]},
                {
                    "name": "高基数交叉贡献",
                    "columns": ["group", "current", "yoy", "change"],
                    "rows": rows,
                },
            ],
            "reconciliations": [{"name": "差额守恒", "passed": True}],
            "warnings": [],
        },
        "supplementalEvidenceSource": {
            "path": "analysis/evidence.json",
            "size": 1_900_000,
            "sha256": "b" * 64,
        },
        "analysisBlock": {"blockId": "analysis_001:summary"},
    }
    original = deepcopy(payload)

    projected = item_workflow._project_analysis_summary_payload(
        payload,
        max_tokens=12_000,
        count_tokens=lambda value: len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        ),
    )

    assert payload == original
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"))) <= 12_000
    evidence = projected["supplementalEvidence"]
    assert evidence["findings"][0] == original["supplementalEvidence"]["findings"][0]
    high_cardinality = evidence["findings"][1]
    selected_rows = high_cardinality["rows"]
    view = high_cardinality["view"]
    assert view["rowCount"] == 19_637
    assert view["selectedRowCount"] == len(selected_rows) < 19_637
    assert view["rankColumn"] == "change"
    assert max(row[3] for row in rows) in {row[3] for row in selected_rows}
    assert min(row[3] for row in rows) in {row[3] for row in selected_rows}
    assert view["omittedNumericSums"]["change"] + sum(row[3] for row in selected_rows) == sum(
        row[3] for row in rows
    )
    assert evidence["sourceFile"] == payload["supplementalEvidenceSource"]
    assert (
        item_workflow._project_analysis_summary_payload(
            payload,
            max_tokens=12_000,
            count_tokens=lambda value: len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            ),
        )
        == projected
    )


def test_analysis_summary_projection_rejects_oversized_non_tabular_payload() -> None:
    payload = {
        "currentAnalysis": {"managementQuestion": "x" * 1_000},
        "deterministicFacts": {"metrics": []},
        "supplementalEvidence": None,
    }

    with pytest.raises(ReportingError) as captured:
        item_workflow._project_analysis_summary_payload(
            payload,
            max_tokens=100,
            count_tokens=lambda value: len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            ),
        )

    assert captured.value.code == "report_analysis_summary_context_too_large"
    assert captured.value.details == {
        "inputTokens": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        "inputTokenBudget": 100,
    }


def test_analysis_summary_projection_preserves_large_integer_reconciliation() -> None:
    large = 2**53 + 1
    finding = {
        "name": "大整数差额",
        "columns": ["group", "change"],
        "rows": [["selected", large + 2], ["omitted-a", large], ["omitted-b", 1]],
    }

    projected = item_workflow._project_tabular_finding(finding, row_limit=1)

    assert projected["view"]["omittedNumericSums"]["change"] == large + 1
    assert projected["view"]["omittedNumericSums"]["change"] + sum(
        row[1] for row in projected["rows"]
    ) == sum(row[1] for row in finding["rows"])


def test_analysis_summary_projection_uses_normalized_change_rate_rank_column() -> None:
    finding = {
        "name": "变化率极值",
        "columns": ["group", "current", "changeRate"],
        "rows": [
            ["largest-current", 1_000_000, 0.01],
            ["largest-decline", 10, -0.9],
            ["largest-growth", 20, 0.8],
        ],
    }

    projected = item_workflow._project_tabular_finding(finding, row_limit=2)

    assert projected["view"]["rankColumn"] == "changeRate"
    assert {row[0] for row in projected["rows"]} == {"largest-decline", "largest-growth"}


@pytest.mark.parametrize(
    "columns, rows",
    (
        (["change", "change"], [[1, 2]]),
        (["group", "change"], [["invalid", float("nan")]]),
        (["group", "change"], [["invalid", float("inf")]]),
    ),
)
def test_supplemental_evidence_rejects_ambiguous_or_non_finite_tabular_values(
    columns: list[str], rows: list[list[Any]]
) -> None:
    with pytest.raises(ValueError):
        item_workflow.SupplementalEvidence.model_validate(
            {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset-1"],
                "findings": [{"name": "invalid", "columns": columns, "rows": rows}],
                "reconciliations": [{"name": "check", "passed": True}],
                "warnings": [],
            }
        )


@pytest.mark.parametrize(
    "warnings, expected",
    [
        ([], ()),
        ([" 原有告警 "], (" 原有告警 ",)),
        (
            [
                "原有告警",
                {"code": "invalid_rows", "message": " 存在非数值行 "},
                {"code": "dimension_source"},
            ],
            ("原有告警", "存在非数值行", "dimension_source"),
        ),
        ([{"message": "  ", "code": " fallback "}], ("fallback",)),
        ([{"message": None, "code": "fallback"}], ("fallback",)),
        (["告警"] * 100, ("告警",) * 100),
    ],
)
def test_supplemental_evidence_normalizes_structured_warnings(
    warnings: list[Any], expected: tuple[str, ...]
) -> None:
    original = deepcopy(warnings)
    evidence = item_workflow.SupplementalEvidence.model_validate(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "收入构成", "value": 80}],
            "reconciliations": [{"name": "check", "passed": True}],
            "warnings": warnings,
        }
    )

    assert evidence.warnings == expected
    assert evidence.model_dump(mode="json")["warnings"] == list(expected)
    assert warnings == original


@pytest.mark.parametrize(
    "warnings",
    [[{}], [{"message": " "}], [{"code": 12}], [None], [12], "告警", ["告警"] * 101],
)
def test_supplemental_evidence_rejects_invalid_warnings(warnings: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        item_workflow.SupplementalEvidence.model_validate(
            {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset-1"],
                "findings": [{"name": "收入构成", "value": 80}],
                "reconciliations": [{"name": "check", "passed": True}],
                "warnings": warnings,
            }
        )
    assert all(issue["loc"][0] == "warnings" for issue in caught.value.errors())


@pytest.mark.anyio
async def test_analysis_item_workflow_keeps_five_stages_when_supplement_is_skipped() -> None:
    events: list[str] = []

    async def decide(payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        events.append("decision")
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=False,
            reason="固定事实足够",
            missingFacts=(),
        )

    async def summarize(payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
        assert payload["supplementalEvidence"] is None
        events.append("summarize")
        return AnalysisSummaryDraft(summary="固定事实显示收入规模稳定。", warnings=())

    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(),
        repair_script=AsyncMock(),
        summarize=summarize,
        read_file=AsyncMock(return_value=_facts_read_result()),
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
    assert events == ["decision", "summarize"]
    workflow.generate_script.assert_not_awaited()
    workflow.repair_script.assert_not_awaited()
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

    async def decide(payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        events.append("decision")
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入类型构成",
            missingFacts=("收入类型构成",),
        )

    async def summarize(payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
        events.append("summarize")
        assert payload["supplementalEvidence"]["findings"][0]["name"] == "门诊收入"
        return AnalysisSummaryDraft(summary="门诊收入是主要收入来源。", warnings=())

    async def read_file(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"].endswith("facts/analysis_001.json"):
            return _facts_read_result()
        events.append("validate")
        return _tool_result(content=evidence, sha256="b" * 64)

    generate_script = AsyncMock(
        side_effect=lambda **_kwargs: events.append("generate") or _code_result()
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
        decide_evidence=decide,
        generate_script=generate_script,
        repair_script=AsyncMock(),
        summarize=summarize,
        read_file=read_file,
        run_script=terminal,
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert events == ["decision", "generate", "execute", "validate", "summarize", "complete"]
    task_facts = generate_script.await_args.kwargs["task_facts"]
    assert task_facts["evidenceDecision"]["missingFacts"] == ["收入类型构成"]
    assert "run_python_script" not in task_facts
    assert "complete_analysis_item" not in task_facts
    assert complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]


@pytest.mark.anyio
async def test_analysis_item_workflow_hydrates_committed_script_without_regeneration() -> None:
    script_file = FileIdentity(
        path="报表/智能分析/run-1/evidence/analysis_001/supplement.py",
        size=20,
        sha256="a" * 64,
    )
    evidence = json.dumps(
        {
            "findings": [{"name": "收入构成", "value": 80}],
            "reconciliations": [{"name": "收入构成对账", "passed": True}],
            "warnings": [],
        }
    )
    load_script = AsyncMock(return_value=script_file)
    generate_script = AsyncMock()
    run_script = AsyncMock(return_value=_tool_result(exitCode=0, output=""))
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少收入构成",
                missingFacts=("收入构成",),
            )
        ),
        generate_script=generate_script,
        repair_script=AsyncMock(),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="补证完成。", warnings=())),
        read_file=AsyncMock(
            side_effect=[_facts_read_result(), _tool_result(content=evidence, sha256="b" * 64)]
        ),
        run_script=run_script,
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
        load_script=load_script,
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="session-1"))

    load_script.assert_awaited_once_with(script_file.path, ANY)
    generate_script.assert_not_awaited()
    run_script.assert_awaited_once_with(script_path=script_file.path, run_context=ANY)


@pytest.mark.anyio
async def test_analysis_item_fresh_generation_retry_receives_previous_diagnostic() -> None:
    first_error = ReportingError(
        "report_python_source_shape_invalid",
        "invalid shape",
        details={"size": 131073, "lineCount": 1, "maxLineLength": 131072},
    )
    generate_script = AsyncMock(side_effect=[first_error, _code_result()])
    evidence = json.dumps(
        {
            "findings": [],
            "reconciliations": [{"name": "检查", "passed": True}],
            "warnings": [],
        }
    )
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少事实",
                missingFacts=("事实",),
            )
        ),
        generate_script=generate_script,
        repair_script=AsyncMock(),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="完成。", warnings=())),
        read_file=AsyncMock(
            side_effect=[_facts_read_result(), _tool_result(content=evidence, sha256="b" * 64)]
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="session-1"))

    assert generate_script.await_args_list[0].kwargs["diagnostic"] is None
    assert generate_script.await_args_list[1].kwargs["diagnostic"]["code"] == (
        "report_python_source_shape_invalid"
    )


@pytest.mark.anyio
async def test_analysis_item_workflow_reads_large_supplemental_evidence_in_chunks() -> None:
    rows = [
        {"period": f"2025-{index:04d}", "value": index, "note": "x" * 96} for index in range(1_200)
    ]
    evidence = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [
                {
                    "name": "完整明细",
                    "columns": ["period", "value", "note"],
                    "rows": [[row["period"], row["value"], row["note"]] for row in rows],
                }
            ],
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
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="需要完整明细",
                missingFacts=("完整明细",),
            )
        ),
        generate_script=AsyncMock(return_value=_code_result()),
        repair_script=AsyncMock(),
        summarize=summarize,
        read_file=read_file,
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=complete,
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    compact_finding = summarize.await_args.args[0]["supplementalEvidence"]["findings"][0]
    assert compact_finding["columns"] == ["period", "value", "note"]
    assert len(compact_finding["rows"]) == len(rows)
    assert compact_finding["rows"][0] == ["2025-0000", 0, "x" * 96]
    assert compact_finding["rows"][-1] == ["2025-1199", 1199, "x" * 96]
    assert summarize.await_args.args[0]["supplementalEvidenceSource"] == {
        "path": "报表/智能分析/run-1/evidence/analysis_001/supplement.json",
        "size": len(evidence),
        "sha256": "b" * 64,
    }
    assert [call.kwargs["offset"] for call in read_file.await_args_list[1:]] == [
        *range(0, len(evidence), page_size),
    ]
    assert complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]


@pytest.mark.anyio
async def test_analysis_item_workflow_repairs_script_at_most_twice() -> None:
    decisions = 0

    async def decide(_payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        nonlocal decisions
        decisions += 1
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
        )

    read_file = AsyncMock(return_value=_facts_read_result())
    repair_script = AsyncMock(side_effect=[_code_result("c" * 64), _code_result("d" * 64)])
    summarize = AsyncMock(
        return_value=AnalysisSummaryDraft(summary="仅使用确定性事实完成摘要。", warnings=())
    )
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(return_value=_code_result("b" * 64)),
        repair_script=repair_script,
        summarize=summarize,
        read_file=read_file,
        run_script=AsyncMock(return_value=_tool_result(exitCode=1, output="private-script-output")),
        complete=complete,
    )

    log_records: list[dict[str, Any]] = []
    sink_id = logger.add(lambda message: log_records.append(message.record))
    try:
        result = await workflow.run(
            _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
        )
    finally:
        logger.remove(sink_id)

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert decisions == 1
    assert workflow.run_script.await_count == 3
    assert workflow.generate_script.await_count == 1
    assert repair_script.await_count == 2
    assert [
        list(call.kwargs["decision"].missing_facts) for call in repair_script.await_args_list
    ] == [
        ["收入构成"],
        ["收入构成"],
    ]
    assert [call.kwargs["script_file"].path for call in repair_script.await_args_list] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.py",
        "报表/智能分析/run-1/evidence/analysis_001/supplement.py",
    ]
    assert [call.kwargs["script_file"].sha256 for call in repair_script.await_args_list] == [
        "b" * 64,
        "c" * 64,
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
    failures = [
        record
        for record in log_records
        if "report_analysis_script_execution_failed" in record["message"]
    ]
    assert len(failures) == 3
    assert {record["level"].name for record in failures} == {"WARNING"}
    assert all("private-script-output" not in record["message"] for record in failures)
    assert all("output_bytes=21" in record["message"] for record in failures)


@pytest.mark.anyio
async def test_analysis_item_workflow_preserves_repairs_after_fresh_generation_retries() -> None:
    generation_error = ReportingError(
        "report_code_generation_no_patch", "Coding Agent 未提交脚本 patch。"
    )
    generate_script = AsyncMock(
        side_effect=[generation_error, generation_error, _code_result("b" * 64)]
    )
    repair_script = AsyncMock(side_effect=[_code_result("c" * 64), _code_result("d" * 64)])
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少收入构成",
                missingFacts=("收入构成",),
            )
        ),
        generate_script=generate_script,
        repair_script=repair_script,
        summarize=AsyncMock(
            return_value=AnalysisSummaryDraft(summary="仅使用确定性事实完成摘要。", warnings=())
        ),
        read_file=AsyncMock(return_value=_facts_read_result()),
        run_script=AsyncMock(return_value=_tool_result(exitCode=1, output="failed")),
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert generate_script.await_count == 3
    assert repair_script.await_count == 2
    assert workflow.run_script.await_count == 3
    assert complete.await_args.kwargs["evidencePaths"] == []
    assert any(
        "report_analysis_supplement_abandoned" in warning
        for warning in complete.await_args.kwargs["warnings"]
    )


@pytest.mark.parametrize(
    "generation_result",
    (
        _code_result(path="other.py"),
        (_code_result(), _code_result("d" * 64)),
    ),
)
@pytest.mark.anyio
async def test_analysis_item_workflow_rejects_non_signed_script_identity(
    generation_result: object,
) -> None:
    decisions = 0

    async def decide(_payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        nonlocal decisions
        decisions += 1
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
        )

    run_script = AsyncMock()
    summarize = AsyncMock(
        return_value=AnalysisSummaryDraft(summary="仅使用确定性事实完成摘要。", warnings=())
    )
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(return_value=generation_result),
        repair_script=AsyncMock(),
        summarize=summarize,
        read_file=AsyncMock(return_value=_facts_read_result()),
        run_script=run_script,
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert result.stage_statuses[-3:] == (
        ("execute-script", "completed"),
        ("validate-evidence", "completed"),
        ("complete-analysis", "completed"),
    )
    run_script.assert_not_awaited()
    assert decisions == 1
    assert workflow.generate_script.await_count == 3
    workflow.repair_script.assert_not_awaited()
    assert complete.await_args.kwargs["evidencePaths"] == []
    assert any(
        "report_analysis_supplement_abandoned" in warning
        for warning in complete.await_args.kwargs["warnings"]
    )


@pytest.mark.anyio
async def test_analysis_item_workflow_warns_and_completes_unreconciled_evidence() -> None:
    unreconciled = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "收入构成", "value": 80, "unit": "元"}],
            "reconciliations": [{"name": "收入构成对账", "passed": False}],
            "warnings": [],
        }
    )
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少收入构成",
                missingFacts=("收入构成",),
            )
        ),
        generate_script=AsyncMock(return_value=_code_result()),
        repair_script=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(
            side_effect=[
                _facts_read_result(),
                _tool_result(content=unreconciled, sha256="b" * 64),
            ]
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
    workflow.decide_evidence.assert_awaited_once()
    workflow.summarize.assert_awaited_once()
    summary_payload = workflow.summarize.await_args.args[0]
    assert summary_payload["supplementalEvidence"]["reconciliations"] == [
        {"name": "收入构成对账", "passed": False}
    ]
    assert summary_payload["supplementalEvidenceSource"] == {
        "path": "报表/智能分析/run-1/evidence/analysis_001/supplement.json",
        "size": len(unreconciled.encode("utf-8")),
        "sha256": "b" * 64,
    }
    assert any(
        "report_analysis_evidence_reconciliation_warning" in warning and "收入构成对账" in warning
        for warning in summary_payload["evidenceWarnings"]
    )
    workflow.complete.assert_awaited_once()
    assert workflow.complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]
    assert any(
        "report_analysis_evidence_reconciliation_warning" in warning and "收入构成对账" in warning
        for warning in workflow.complete.await_args.kwargs["warnings"]
    )
    assert all(
        "report_analysis_evidence_reconciliation_failed" not in warning
        for warning in workflow.complete.await_args.kwargs["warnings"]
    )


@pytest.mark.parametrize(
    "invalid_payload, expected_code",
    (
        (
            {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset-1"],
                "findings": [{"name": "收入构成", "value": 80}],
                "reconciliations": [{"name": "收入构成对账"}],
                "warnings": [],
            },
            "report_analysis_evidence_schema_invalid",
        ),
    ),
)
@pytest.mark.anyio
async def test_analysis_item_workflow_repairs_invalid_evidence_once(
    invalid_payload: dict[str, Any], expected_code: str
) -> None:
    invalid = json.dumps(invalid_payload)
    valid = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "收入构成", "value": 80}],
            "reconciliations": [{"name": "收入构成对账", "passed": True}],
            "warnings": [],
        }
    )
    decisions: list[Mapping[str, Any]] = []

    async def decide(payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        decisions.append(payload)
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
        )

    repair_script = AsyncMock(return_value=_code_result("c" * 64))
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(return_value=_code_result("b" * 64)),
        repair_script=repair_script,
        summarize=AsyncMock(
            return_value=AnalysisSummaryDraft(summary="补充证据验证完成。", warnings=())
        ),
        read_file=AsyncMock(
            side_effect=[
                _facts_read_result(),
                _tool_result(content=invalid, sha256="d" * 64),
                _tool_result(content=valid, sha256="e" * 64),
            ]
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    assert len(decisions) == 1
    diagnostic = repair_script.await_args.kwargs["diagnostic"]
    assert diagnostic["code"] == expected_code
    assert repair_script.await_args.kwargs["decision"].missing_facts == ("收入构成",)
    assert repair_script.await_args.kwargs["script_file"].path == (
        "报表/智能分析/run-1/evidence/analysis_001/supplement.py"
    )
    assert workflow.run_script.await_count == 2
    assert workflow.summarize.await_args.args[0]["supplementalEvidence"]["analysisId"] == (
        "analysis_001"
    )
    assert workflow.complete.await_args.kwargs["evidencePaths"] == [
        "报表/智能分析/run-1/evidence/analysis_001/supplement.json"
    ]


@pytest.mark.anyio
async def test_analysis_item_workflow_binds_evidence_identity_to_current_analysis() -> None:
    model_evidence = json.dumps(
        {
            "findings": [{"name": "收入构成", "value": 80}],
            "reconciliations": [{"name": "收入构成对账", "passed": True}],
            "warnings": [],
        }
    )
    decisions = 0

    async def decide(_payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        nonlocal decisions
        decisions += 1
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
        )

    summarize = AsyncMock(
        return_value=AnalysisSummaryDraft(summary="补充证据验证完成。", warnings=())
    )
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(return_value=_code_result("b" * 64)),
        repair_script=AsyncMock(),
        summarize=summarize,
        read_file=AsyncMock(
            side_effect=[
                _facts_read_result(),
                _tool_result(content=model_evidence, sha256="d" * 64),
            ]
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    assert decisions == 1
    assert workflow.run_script.await_count == 1
    workflow.generate_script.assert_awaited_once()
    evidence = summarize.await_args.args[0]["supplementalEvidence"]
    assert evidence["analysisId"] == "analysis_001"
    assert evidence["datasetIds"] == ["dataset-1"]
    assert evidence["findings"] == [{"name": "收入构成", "value": 80}]
    assert evidence["reconciliations"] == [{"name": "收入构成对账", "passed": True}]


@pytest.mark.anyio
async def test_analysis_item_workflow_abandons_structurally_invalid_evidence_after_repairs() -> (
    None
):
    invalid = json.dumps(
        {
            "analysisId": "analysis_001",
            "datasetIds": ["dataset-1"],
            "findings": [{"name": "收入构成", "value": 80}],
            "reconciliations": [{"name": "收入构成对账"}],
            "warnings": [],
        }
    )
    decisions = 0

    async def decide(_payload: Mapping[str, Any]) -> AnalysisEvidenceDecision:
        nonlocal decisions
        decisions += 1
        return AnalysisEvidenceDecision(
            requiresSupplementalEvidence=True,
            reason="缺少收入构成",
            missingFacts=("收入构成",),
        )

    summarize = AsyncMock(
        return_value=AnalysisSummaryDraft(summary="仅使用确定性事实完成摘要。", warnings=())
    )
    complete = AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True))
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        generate_script=AsyncMock(return_value=_code_result("b" * 64)),
        repair_script=AsyncMock(side_effect=[_code_result("c" * 64), _code_result("d" * 64)]),
        summarize=summarize,
        read_file=AsyncMock(
            side_effect=[
                _facts_read_result(),
                _tool_result(content=invalid, sha256="d" * 64),
                _tool_result(content=invalid, sha256="e" * 64),
                _tool_result(content=invalid, sha256="f" * 64),
            ]
        ),
        run_script=AsyncMock(return_value=_tool_result(exitCode=0, output="")),
        complete=complete,
    )

    result = await workflow.run(
        _instruction(), RunContext(run_id="task-run-1", session_id="task-session-1")
    )

    assert [status for _, status in result.stage_statuses] == ["completed"] * 5
    assert decisions == 1
    assert workflow.repair_script.await_count == 2
    assert summarize.await_args.args[0]["supplementalEvidence"] is None
    assert complete.await_args.kwargs["evidencePaths"] == []
    assert any(
        "report_analysis_supplement_abandoned" in warning
        and "report_analysis_evidence_schema_invalid" in warning
        for warning in complete.await_args.kwargs["warnings"]
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
        decide_evidence=AsyncMock(),
        generate_script=AsyncMock(),
        repair_script=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(return_value=_facts_read_result()),
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
    workflow.decide_evidence.assert_not_awaited()
    workflow.generate_script.assert_not_awaited()
    workflow.repair_script.assert_not_awaited()
    workflow.summarize.assert_not_awaited()
    assert {
        key: value for key, value in complete.await_args.kwargs.items() if key != "run_context"
    } == instruction["durableAnalysisItem"]


@pytest.mark.anyio
async def test_analysis_item_workflow_preserves_planner_provider_error() -> None:
    provider_error = RuntimeError("provider unavailable")
    complete = AsyncMock()
    workflow = AnalysisItemWorkflow(
        decide_evidence=AsyncMock(side_effect=provider_error),
        generate_script=AsyncMock(),
        repair_script=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(return_value=_facts_read_result()),
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
        decide_evidence=AsyncMock(
            return_value=AnalysisEvidenceDecision(
                requiresSupplementalEvidence=False,
                reason="固定事实足够",
                missingFacts=(),
            )
        ),
        generate_script=AsyncMock(),
        repair_script=AsyncMock(),
        summarize=AsyncMock(return_value=AnalysisSummaryDraft(summary="固定事实摘要", warnings=())),
        read_file=reads,
        run_script=AsyncMock(),
        complete=AsyncMock(return_value=_tool_result(status="accepted", taskFinished=True)),
    )

    await workflow.run(_instruction(), RunContext(run_id="task-run-1", session_id="task-session-1"))

    assert [call.kwargs["offset"] for call in reads.await_args_list] == [0, split]


def test_evidence_decision_normalizes_omitted_empty_missing_facts() -> None:
    decision = AnalysisEvidenceDecision.model_validate(
        {
            "requiresSupplementalEvidence": False,
            "reason": "固定事实已足够。",
        }
    )

    assert decision.missing_facts == ()


def test_evidence_decision_rejects_script_source() -> None:
    with pytest.raises(ValueError):
        AnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": True,
                "reason": "缺少收入构成。",
                "missingFacts": ["收入构成"],
                "script": "print('not allowed')",
            }
        )


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
