from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import jmespath
import pytest
from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.tools import Function
from daytona.common.errors import DaytonaError
from pydantic import ValidationError

from smart_reporting.reporting.agent import (
    _REPORT_TOOL_FAILURE_STATE_KEY,
    _enforce_reporting_no_progress,
    _report_tool_argument_failure,
    normalize_reporting_tool_arguments,
)
from smart_reporting.reporting.delivery.acceptance import build_report_phase_acceptance_contract
from smart_reporting.reporting.delivery.artifacts_v1 import Citation
from smart_reporting.reporting.delivery.draft_v1 import ReportChartRegistration
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    reporting_analysis_fact_budget_contract_from_acceptance_contract,
    reporting_visualization_budget_contract_from_acceptance_contract,
    reporting_visualization_budget_from_acceptance_contract,
    reporting_visualization_budget_from_run_context,
    reporting_visualization_recovery_from_acceptance_contract,
    reporting_visualization_registered_from_acceptance_contract,
)
from smart_reporting.reporting.tests.workspace_fakes import service as fake_workspace_service
from smart_reporting.reporting.tools.analysis import (
    MAX_ANALYSIS_WRITE_INTENT_BYTES,
    _derive_durable_analysis_binding,
    _fact_metric_codes,
    _missing_metric_definition_codes,
    _normalize_analysis_summary_comparability,
)
from smart_reporting.reporting.tools.factory import build_report_worker_tools
from smart_reporting.reporting.tools.profile import (
    _analysis_context_projection,
    _profile_receipt_command_id,
)
from smart_reporting.reporting.tools.toolkit import (
    ReportWorkspaceTaskToolkit,
    _reset_stop_after_tool_call,
    _stop_after_accepted_tool_call,
    _stop_after_nonretryable_tool_call,
)
from smart_reporting.reporting.tools.validation import (
    ANALYSIS_WRITE_PUBLIC_TOOL_NAMES,
    ANALYSIS_WRITE_TOOL_NAMES,
    _analysis_write_operation_arguments,
    _analysis_write_parameters,
    _bound_profile_pointer_value,
    _canonical_analysis_write_call,
    _jmespath_reporting_error,
)
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    FileIdentity,
    MetricDefinition,
    ProfileReadReceipt,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime import analysis as runtime_analysis
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_item_completion_conditions,
    _visualization_analysis_citation_ids,
    _visualization_completion_conditions,
    _visualization_dynamic_budget,
    _visualization_retry_budget,
    _visualization_retry_usage,
)
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.task_execution.acceptance import normalize_acceptance_contract
from smart_reporting.task_execution.execution import WorkspaceTaskToolkit
from smart_reporting.workspace import WorkspaceError, WorkspacePathConflict


def _chart_registration() -> ReportChartRegistration:
    return ReportChartRegistration.model_validate(
        {
            "chartId": "income",
            "sourcePath": "analysis/charts/income.png",
            "title": "收入趋势",
            "altText": "收入趋势图",
            "citationIds": ["citation-1"],
            "metricCodes": ["income"],
            "currentPeriod": "2026-01",
            "sourceDatasetId": "dataset-1",
            "aggregationGrain": "month",
        }
    )


def _chart_identity(*, width: int, height: int) -> dict[str, Any]:
    return {
        "sourcePath": "analysis/charts/income.png",
        "size": 1024,
        "sha256": "a" * 64,
        "format": "PNG",
        "mediaType": "image/png",
        "extension": ".png",
        "width": width,
        "height": height,
    }


def test_missing_metric_definition_codes_covers_facts_derived_and_charts() -> None:
    missing = _missing_metric_definition_codes(
        fact_bundles=(
            {
                "metrics": [{"metricCodes": ["income_summary_total", "defined_metric"]}],
                "derivedMetrics": [{"code": "income_margin"}],
            },
        ),
        chart_metric_codes=("chart_only", "defined_metric"),
        metric_definitions=(
            MetricDefinition(
                code="defined_metric",
                name="已定义",
                definition="测试指标",
                periodBasis="月",
            ),
        ),
    )

    assert missing == ("chart_only", "income_margin", "income_summary_total")


def test_fact_metric_codes_replace_generic_planner_placeholder() -> None:
    assert _fact_metric_codes(
        {
            "metrics": [{"metricCodes": ["income_summary_total"]}],
            "derivedMetrics": [{"code": "income_growth_rate"}],
        }
    ) == ("income_growth_rate", "income_summary_total")


def test_section_unknown_metric_is_preserved_with_warning() -> None:
    normalized, warnings = ReportWorkspaceTaskToolkit._normalize_section_claims(
        section_code="section_002",
        claims=[
            {
                "claimId": "claim_001",
                "metricCode": "income_summary_total",
                "value": 1,
                "managementQuestionRef": "analysis_002",
                "currentPeriod": "2025年1-11月",
                "citationIds": ["citation_001"],
            }
        ],
        work_item=SimpleNamespace(
            metric_definitions=(),
            charts=(),
            citations=(SimpleNamespace(citation_id="citation_001"),),
            management_question_catalog=(
                SimpleNamespace(ref="analysis_002", question="收入结构如何？"),
            ),
        ),
    )

    assert normalized[0].metric_code == "income_summary_total"
    assert normalized[0].period_basis == "2025年1-11月"
    assert [item["code"] for item in warnings] == ["report_section_claim_metric_unknown"]


def write_functions() -> dict[str, Function]:
    schemas = {
        "apply_patch": {
            "type": "object",
            "properties": {"patch": {"type": "string", "minLength": 1}},
            "required": ["patch"],
            "additionalProperties": False,
        },
        "create_files": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["files"],
            "additionalProperties": False,
        },
        "overwrite_file": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
                "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "required": ["path", "content", "expected_sha256"],
            "additionalProperties": False,
        },
        "replace_text": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "old_string": {"type": "string", "minLength": 1},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        },
    }
    return {
        name: Function(name=name, parameters=parameters, entrypoint=lambda: None)
        for name, parameters in schemas.items()
    }


def test_analysis_item_budget_retry_forces_fixed_fact_submission() -> None:
    conditions = _analysis_item_completion_conditions(
        None,
        ReportingError(
            "report_analysis_tool_budget_exhausted",
            "当前分析项已达到成功工具调用上限。",
        ),
    )

    assert any("禁止继续探索 Profile" in item for item in conditions)
    assert any("只调用一次 query_analysis_facts" in item for item in conditions)
    assert any("立即调用 complete_analysis_item" in item for item in conditions)
    assert not any("创建补充 evidence" in item for item in conditions)


def test_analysis_item_first_attempt_converges_on_fixed_facts() -> None:
    conditions = _analysis_item_completion_conditions(None, None)

    assert any("deterministicFacts 已内联" in item for item in conditions)
    assert any("不得为探索 facts 结构" in item for item in conditions)
    assert any("固定事实足够时立即调用 complete_analysis_item" in item for item in conditions)
    assert any("当前管理问题确实缺少必需事实" in item for item in conditions)
    assert any("不得猜测、补齐或替代缺失事实" in item for item in conditions)


@pytest.mark.parametrize(
    ("summary", "expected_summary", "expected_warnings"),
    [
        (
            "2025年1-11月较2024年全年同比下降3.96%。",
            "2025年1-11月较2024年全年参考对比下降3.96%。",
            ("摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。",),
        ),
        (
            "2025年1-10月较2024年1-10月同比增长12.33%。",
            "2025年1-10月较2024年1-10月同比增长12.33%。",
            (),
        ),
    ],
)
def test_analysis_summary_normalizes_only_incomparable_yoy_claims(
    summary: str,
    expected_summary: str,
    expected_warnings: tuple[str, ...],
) -> None:
    assert _normalize_analysis_summary_comparability(summary) == (
        expected_summary,
        expected_warnings,
    )


def test_visualization_retry_after_registration_only_allows_finalize() -> None:
    conditions = _visualization_completion_conditions(
        ReportingError(
            "report_visualization_tool_budget_exhausted",
            "当前可视化 Task 已达到成功工具调用上限。",
        ),
        True,
    )

    assert any("禁止改图" in item for item in conditions)
    assert any("不要调用任何读取" in item for item in conditions)
    assert any("finalize_report_analysis" in item for item in conditions)
    assert not any("register_report_charts" in item for item in conditions)


def test_visualization_completion_conditions_forbid_citation_and_workspace_exploration() -> None:
    conditions = _visualization_completion_conditions(None, False)

    assert any("analysisCitationIds" in item for item in conditions)
    assert any(
        "不得用 read_file、terminal 或目录探测寻找 citationId" in item for item in conditions
    )
    assert any("仅可执行 python3 <scriptPath>" in item for item in conditions)


def test_visualization_retry_budget_is_read_from_trusted_phase_contract() -> None:
    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "visualization_section",
            "reportRunId": "report-1",
            "visualizationToolCalls": 48,
            "visualizationScriptFailures": 2,
        },
        analysis_output_path="analysis-output.json",
    )

    assert reporting_visualization_budget_from_acceptance_contract(contract) == (48, 2)


def test_old_visualization_acceptance_contract_is_rejected() -> None:
    with pytest.raises(ValueError, match="taskKind"):
        build_report_phase_acceptance_contract(
            phase="analysis",
            validation_context_file={"path": "analysis-context.json"},
            phase_contract={"taskKind": "visualization", "visualizationToolCalls": 7},
            analysis_output_path="analysis-output.json",
        )


def test_analysis_fact_budget_contract_requires_all_v1_scalars_and_recovery_flag() -> None:
    phase_contract = {
        "taskKind": "analysis_item",
        "analysisIds": ["analysis_001"],
        "analysisOutputRoot": "evidence/analysis_001",
        "analysisFactBudgetVersion": 1,
        "analysisFactQueryLimit": 4,
        "analysisFactQueriesUsed": 1,
        "analysisRecovery": False,
    }
    valid = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract=phase_contract,
    )

    assert reporting_analysis_fact_budget_contract_from_acceptance_contract(valid) == {
        "analysisFactBudgetVersion": 1,
        "analysisFactQueryLimit": 4,
        "analysisFactQueriesUsed": 1,
        "analysisRecovery": False,
    }

    for missing in {
        "analysisFactQueryLimit",
        "analysisFactQueriesUsed",
        "analysisRecovery",
    }:
        invalid = build_report_phase_acceptance_contract(
            phase="analysis",
            validation_context_file={"path": "analysis-context.json"},
            phase_contract={key: value for key, value in phase_contract.items() if key != missing},
        )
        with pytest.raises(ReportingError, match="report_phase_contract_invalid"):
            reporting_analysis_fact_budget_contract_from_acceptance_contract(invalid)

    invalid_bool = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={**phase_contract, "analysisFactQueriesUsed": True},
    )
    with pytest.raises(ReportingError, match="report_phase_contract_invalid"):
        reporting_analysis_fact_budget_contract_from_acceptance_contract(invalid_bool)


def test_historical_analysis_fact_contract_uses_fixed_defaults() -> None:
    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            "analysisOutputRoot": "evidence/analysis_001",
        },
    )

    assert reporting_analysis_fact_budget_contract_from_acceptance_contract(contract) == {
        "analysisFactBudgetVersion": 0,
        "analysisFactQueryLimit": 4,
        "analysisFactQueriesUsed": 0,
        "analysisRecovery": False,
    }


def test_visualization_v1_contract_requires_every_signed_budget_scalar() -> None:
    phase_contract = {
        "taskKind": "visualization_section",
        "visualizationBudgetVersion": 1,
        "visualizationEvidenceReadUnits": 3,
        "visualizationReadLimit": 12,
        "visualizationFactQueryLimit": 4,
        "visualizationAttemptToolLimit": 48,
        "visualizationTotalToolLimit": 64,
        "visualizationReadUnitsUsed": 0,
        "visualizationFactQueriesUsed": 0,
        "visualizationToolCalls": 0,
        "visualizationScriptFailures": 0,
    }
    valid = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract=phase_contract,
        analysis_output_path="analysis-output.json",
    )
    assert (
        reporting_visualization_budget_contract_from_acceptance_contract(valid)[
            "visualizationEvidenceReadUnits"
        ]
        == 3
    )

    for missing in phase_contract.keys() - {"taskKind", "visualizationBudgetVersion"}:
        invalid = build_report_phase_acceptance_contract(
            phase="analysis",
            validation_context_file={"path": "analysis-context.json"},
            phase_contract={key: value for key, value in phase_contract.items() if key != missing},
            analysis_output_path="analysis-output.json",
        )
        with pytest.raises(ReportingError, match="report_phase_contract_invalid"):
            reporting_visualization_budget_contract_from_acceptance_contract(invalid)


@pytest.mark.parametrize(
    ("evidence_sizes", "fact_size", "expected"),
    [
        ([], 0, (0, 12, 4, 48, 64)),
        ([1, 65536, 65537], 16385, (4, 12, 4, 48, 64)),
        ([65536] * 25, 16 * 16384, (25, 12, 16, 48, 64)),
        ([65536] * 512, 1, (512, 12, 4, 48, 64)),
    ],
)
def test_visualization_dynamic_budget_uses_unique_file_bytes(
    evidence_sizes: list[int], fact_size: int, expected: tuple[int, int, int, int, int]
) -> None:
    evidence_files = [
        {"path": f"evidence/{index}.json", "size": size, "sha256": f"{index:064x}"}
        for index, size in enumerate(evidence_sizes, start=1)
    ]
    analysis_items = {"analysis_001": {"evidenceFiles": [*evidence_files, *evidence_files[:1]]}}
    facts = (
        {
            "analysis_001": FileIdentity(
                path="facts/analysis_001.json", size=fact_size, sha256="f" * 64
            )
        }
        if fact_size
        else {}
    )

    budget = _visualization_dynamic_budget(analysis_items, facts)

    assert (
        budget["visualizationEvidenceReadUnits"],
        budget["visualizationReadLimit"],
        budget["visualizationFactQueryLimit"],
        budget["visualizationAttemptToolLimit"],
        budget["visualizationTotalToolLimit"],
    ) == expected


def test_visualization_dynamic_budget_rejects_513_units_and_identity_conflicts() -> None:
    with pytest.raises(ReportingError) as exceeded:
        _visualization_dynamic_budget(
            {
                "analysis_001": {
                    "evidenceFiles": [
                        {"path": "evidence/large.json", "size": 513 * 65536, "sha256": "a" * 64}
                    ]
                }
            },
            {},
        )
    with pytest.raises(ReportingError) as conflicted:
        _visualization_dynamic_budget(
            {
                "analysis_001": {
                    "evidenceFiles": [
                        {"path": "evidence/same.json", "size": 1, "sha256": "a" * 64},
                        {"path": "evidence/same.json", "size": 2, "sha256": "b" * 64},
                    ]
                }
            },
            {},
        )

    assert exceeded.value.code == "report_visualization_evidence_budget_exceeded"
    assert conflicted.value.code == "report_visualization_evidence_identity_conflict"


def test_visualization_analysis_citation_ids_only_projects_bound_ids() -> None:
    plan = DetailedAnalysisPlan(
        datasetIds=("dataset-income", "dataset-budget", "dataset-unused"),
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_001",
                domain="income",
                managementQuestion="收入趋势",
                primaryMetricFamily="收入",
                datasetIds=("dataset-income",),
                fields=(),
                metrics=(),
                periods=(),
                actions=("趋势",),
                evidenceSummary="固定事实",
                suggestedSection="收入",
                completionConditions=("完成",),
            ),
            DetailedAnalysisItem(
                analysisId="analysis_002",
                domain="budget",
                managementQuestion="预算执行",
                primaryMetricFamily="预算",
                datasetIds=("dataset-budget", "dataset-income"),
                fields=(),
                metrics=(),
                periods=(),
                actions=("对比",),
                evidenceSummary="固定事实",
                suggestedSection="预算",
                completionConditions=("完成",),
            ),
        ),
    )
    citations = (
        Citation(
            citationId="citation-income",
            datasetId="dataset-income",
            requirementId="r1",
            snapshotHash="a" * 64,
        ),
        Citation(
            citationId="citation-budget",
            datasetId="dataset-budget",
            requirementId="r2",
            snapshotHash="b" * 64,
        ),
        Citation(
            citationId="citation-unused",
            datasetId="dataset-unused",
            requirementId="r3",
            snapshotHash="c" * 64,
        ),
    )

    assert _visualization_analysis_citation_ids(plan, citations) == {
        "analysis_001": ["citation-income"],
        "analysis_002": ["citation-income", "citation-budget"],
    }


def test_visualization_retry_budget_is_restored_from_budget_error() -> None:
    error = ReportingError(
        "report_visualization_tool_budget_exhausted",
        "当前可视化 Task 已达到工具调用上限。",
        details={"totalToolCalls": 48, "scriptFailureCount": 2},
    )

    assert _visualization_retry_budget(error) == (48, 2)
    assert _visualization_retry_budget(RuntimeError("other")) == (0, 0)


def test_visualization_retry_usage_merges_full_snapshot_with_terminal_error_details() -> None:
    error = ReportingError(
        "report_visualization_tool_budget_exhausted",
        "当前可视化 Task 已达到工具调用上限。",
        details={"totalToolCalls": 49, "scriptFailureCount": 2},
    )
    setattr(
        error,
        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
        {
            "visualizationReadUnitsUsed": 13,
            "visualizationFactQueriesUsed": 4,
            "visualizationToolCalls": 48,
            "visualizationScriptFailures": 1,
        },
    )

    assert _visualization_retry_usage(error) == {
        "visualizationReadUnitsUsed": 13,
        "visualizationFactQueriesUsed": 4,
        "visualizationToolCalls": 49,
        "visualizationScriptFailures": 2,
    }


def test_visualization_retry_budget_survives_unrelated_worker_error() -> None:
    context = RunContext(
        run_id="worker-run-2",
        session_id="worker-session-2",
        session_state={
            REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY: {
                "visualization-task-2:worker-run-2": {
                    "baseTotal": 20,
                    "baseScriptFailures": 1,
                    "attemptedCount": 7,
                    "scriptFailureCount": 1,
                }
            }
        },
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-task-2",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization_section",
            }
        },
    )
    error = TimeoutError("model timeout")
    setattr(
        error,
        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
        reporting_visualization_budget_from_run_context(context),
    )

    assert _visualization_retry_budget(error) == (27, 2)
    conditions = _visualization_completion_conditions(error, False)
    assert any("只整合 completedAnalysisItems" in item for item in conditions)

    domain_error = ReportingError("report_worker_error", "worker failed", details={"stage": 2})
    setattr(domain_error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, (27, 2))
    assert _visualization_retry_budget(domain_error) == (27, 2)


def test_visualization_recovery_contract_is_only_enabled_for_budget_failures() -> None:
    budget_error = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "visualization_section",
            "reportRunId": "report-1",
            "visualizationRecovery": True,
        },
        analysis_output_path="analysis-output.json",
    )
    ordinary_retry = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "visualization_section",
            "reportRunId": "report-1",
            "visualizationRecovery": False,
        },
        analysis_output_path="analysis-output.json",
    )

    assert reporting_visualization_recovery_from_acceptance_contract(budget_error) is True
    assert reporting_visualization_recovery_from_acceptance_contract(ordinary_retry) is False


def test_visualization_retry_budget_keeps_dependency_base_before_first_tool() -> None:
    context = RunContext(
        run_id="worker-run-3",
        session_id="worker-session-3",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-task-3",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization_section",
                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: 48,
                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: 2,
            }
        },
    )

    assert reporting_visualization_budget_from_run_context(context) == (48, 2)


@pytest.mark.anyio
async def test_register_report_charts_accepts_cross_dataset_comparison() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=3))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-current", "citation-yoy"],
            "citationDatasetIds": {
                "citation-current": "dataset-current",
                "citation-yoy": "dataset-yoy",
            },
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    receipt = {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "a" * 64,
        "inspectionMode": "vision",
        "visualReviewStatus": "passed",
        "inspectorId": None,
        "modelId": "vision-model",
        "reviewed": True,
        "requiresRevision": False,
        "issues": [],
        "summary": "检查完成",
        "warnings": [],
        "suggestions": [],
    }
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"charts": [], "chartInspectionReceipts": [receipt]})
    )
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_identity(width=1000, height=700))
    expected_warnings = [
        {
            "code": "chart_low_resolution",
            "chartId": "income",
            "width": 1000,
            "height": 700,
            "minimumWidth": 1200,
            "minimumHeight": 675,
            "message": "图表尺寸偏低，仅作为非阻断质量告警。",
        },
        {
            "code": "chart_low_effective_dpi",
            "chartId": "income",
            "width": 1000,
            "height": 700,
            "effectiveDpi": 146.0,
            "minimumDpi": 150,
            "message": "按 A4 正文全宽估算的有效分辨率偏低，仅作为非阻断质量告警。",
        },
    ]
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-current", "citation-yoy"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "comparisonPeriod": "2025-01",
                "comparisonType": "yoy",
                "sourceDatasetId": "dataset-current",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["warnings"] == expected_warnings
    toolkit._apply_durable.assert_awaited_once()


@pytest.mark.anyio
async def test_register_report_charts_rejects_legacy_visualization_kind() -> None:
    scope = SimpleNamespace(thread_id="thread-legacy", task=SimpleNamespace(mutation_sequence=1))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))

    def reject_legacy(*_args: Any, **kwargs: Any) -> None:
        assert kwargs["task_kinds"] == frozenset({"visualization_finalize"})
        raise ReportingError("report_phase_tool_forbidden", "旧 visualization Task 无权登记图表。")

    toolkit._require_phase_tool = reject_legacy
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"

    result = await toolkit.register_report_charts(
        [], run_context=RunContext(run_id="run-legacy", session_id="session-legacy")
    )

    assert result["ok"] is False
    assert result["code"] == "report_phase_tool_forbidden"


@pytest.mark.anyio
@pytest.mark.parametrize("task_kind", ["visualization_section", "visualization_finalize"])
async def test_inspect_chart_production_gate_allows_only_section_kind(task_kind: str) -> None:
    acceptance_contract = {
        "requirements": [
            {
                "parameters": {
                    "phase": "analysis",
                    "phaseContract": {"taskKind": task_kind},
                }
            }
        ]
    }
    scope = SimpleNamespace(
        thread_id="thread-inspect-gate",
        task=SimpleNamespace(acceptance_contract=acceptance_contract),
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "visualInspectionMode": "vision",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._inspect_chart_file = AsyncMock(
        return_value={"sourcePath": "analysis/charts/income.png", "sha256": "a" * 64}
    )
    receipt = {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "a" * 64,
        "inspectionMode": "vision",
        "visualReviewStatus": "passed",
        "inspectorId": None,
        "modelId": "vision-model",
        "reviewed": True,
        "requiresRevision": False,
        "issues": [],
        "summary": "检查完成",
        "warnings": [],
        "suggestions": [],
    }
    toolkit._vision_reviewer = SimpleNamespace(review=AsyncMock(return_value=receipt))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.inspect_chart(
        path="analysis/charts/income.png",
        run_context=RunContext(run_id="run-inspect-gate", session_id="session-inspect-gate"),
    )

    if task_kind == "visualization_section":
        assert result["ok"] is True, result
        toolkit._apply_durable.assert_awaited_once()
    else:
        assert result["ok"] is False
        assert result["code"] == "report_phase_tool_forbidden"
        toolkit._inspect_chart_file.assert_not_awaited()


@pytest.mark.anyio
async def test_submit_visualization_charts_requires_section_task_kind() -> None:
    scope = SimpleNamespace(thread_id="thread-finalize", task=SimpleNamespace(mutation_sequence=4))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))

    def reject_non_section_task(*_args: Any, **kwargs: Any) -> None:
        if kwargs["task_kinds"] != frozenset({"visualization_section"}):
            raise AssertionError("unexpected task kind allowlist")
        raise ReportingError("report_phase_tool_forbidden", "visualization_finalize 调用被拒")

    toolkit._require_phase_tool = reject_non_section_task
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"

    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-finalize", session_id="session-finalize"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_phase_tool_forbidden"


@pytest.mark.anyio
async def test_submit_visualization_charts_commit_flow() -> None:
    scope = SimpleNamespace(thread_id="thread-section", task=SimpleNamespace(mutation_sequence=7))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_001",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_001/attempt-2"},
        },
    )
    identity = {
        "sourcePath": "analysis/charts/section_001/attempt-2/income.png",
        "size": 1024,
        "sha256": "b" * 64,
        "format": "PNG",
        "mediaType": "image/png",
        "extension": ".png",
        "width": 1200,
        "height": 800,
    }
    toolkit._inspect_chart_file = AsyncMock(return_value=identity)
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(revision=7))
    toolkit._apply_durable = AsyncMock()
    chart = {
        "chartId": "income",
        "sourcePath": identity["sourcePath"],
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
    }

    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[chart],
        run_context=RunContext(run_id="run-section", session_id="session-section"),
    )

    assert result == {
        "ok": True,
        "status": "committed",
        "sectionCode": "section_001",
        "chartCount": 1,
    }
    durable_call = toolkit._apply_durable.await_args.kwargs
    assert durable_call["name"] == "submit_visualization_charts"
    assert durable_call["payload"] == {
        "sectionCode": "section_001",
        "charts": [
            {
                **chart,
                "comparisonPeriod": None,
                "comparisonType": "none",
                "comparability": "strict",
            }
        ],
        "files": [
            {
                "path": identity["sourcePath"],
                "size": identity["size"],
                "sha256": identity["sha256"],
            }
        ],
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            {
                "charts": durable_call["payload"]["charts"],
                "files": durable_call["payload"]["files"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert durable_call["command_id"] == f"viz-section:7:section_001:{expected_digest}"


@pytest.mark.anyio
async def test_submit_visualization_charts_rejects_section_code_mismatch() -> None:
    scope = SimpleNamespace(thread_id="thread-section-mismatch", task=SimpleNamespace())
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_002",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_002"},
        },
    )
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-mismatch", session_id="session-mismatch"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_visualization_section_invalid"
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_submit_visualization_charts_allows_empty_charts() -> None:
    scope = SimpleNamespace(thread_id="thread-empty", task=SimpleNamespace())
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_001",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_001"},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(revision=9))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-empty", session_id="session-empty"),
    )

    assert result["ok"] is True
    assert result["chartCount"] == 0
    durable_call = toolkit._apply_durable.await_args.kwargs
    assert durable_call["payload"] == {"sectionCode": "section_001", "charts": [], "files": []}


@pytest.mark.anyio
async def test_submit_visualization_charts_missing_file_returns_recoverable_failure() -> None:
    scope = SimpleNamespace(thread_id="thread-submit-missing", task=SimpleNamespace())
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_001",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_001"},
        },
    )
    toolkit._inspect_chart_file = AsyncMock(
        side_effect=ReportingError(
            "report_chart_file_missing",
            "图表源文件不存在。",
            details={"sourcePath": "analysis/charts/section_001/missing.png"},
        )
    )
    toolkit._apply_durable = AsyncMock()
    chart = {
        "chartId": "income",
        "sourcePath": "analysis/charts/section_001/missing.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
    }

    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[chart],
        run_context=RunContext(run_id="run-submit-missing", session_id="session-submit-missing"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_chart_file_missing"
    assert result["retryable"] is True
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_missing_file_returns_recoverable_failure() -> None:
    # 注册不存在的图表文件曾经让 _avalidate_existing_path 抛 WorkspaceError 穿透炸 run；
    # 这里改用可恢复的字段级回执,要求模型移除该图或先生成真实 PNG 再提交。
    scope = SimpleNamespace(thread_id="thread-missing", task=SimpleNamespace(mutation_sequence=3))

    @asynccontextmanager
    async def client_context():
        yield object()

    service = SimpleNamespace(
        normalize_path=lambda path, **_kwargs: (path, f"/workspace/{path}"),
        _async_client=client_context,
        _asandbox_for=AsyncMock(return_value=object()),
        _avalidate_existing_path=AsyncMock(side_effect=WorkspaceError("图表源文件不存在")),
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope), service=service)
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
            "visualInspectionMode": "deterministic",
        },
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "chart_missing",
                "sourcePath": "analysis/charts/section_001/attempt-1/chart_x.png",
                "title": "标题",
                "altText": "图注",
                "citationIds": ["citation-1"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_chart_file_missing"
    assert result["retryable"] is True
    # requiredActions 必须指示模型从清单移除该图或先生成再提交,不能让 WorkspaceError
    # 穿透为 run 级失败后注入全量任务上下文滚入 tool_no_progress 终态。
    assert any("移除" in action or "生成" in action for action in result["requiredActions"])


@pytest.mark.anyio
async def test_register_report_charts_rejects_after_recent_script_failure() -> None:
    scope = SimpleNamespace(
        thread_id="thread-script-failure", task=SimpleNamespace(mutation_sequence=1)
    )
    run_context = RunContext(
        run_id="run-script-failure",
        session_id="session-script-failure",
        session_state={
            REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY: {
                "visualization-task:run-script-failure": {
                    "lastScriptFailed": True,
                    "diagnostics": ["[FAIL] chart: TypeError"],
                }
            }
        },
        dependencies={"AgentOS 编码任务": {"externalRunId": "visualization-task"}},
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: ({}, {})
    toolkit._inspect_chart = AsyncMock()

    result = await toolkit.register_report_charts([], run_context=run_context)

    assert result["ok"] is False
    assert result["code"] == "report_visualization_script_failed"
    toolkit._inspect_chart.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_rejects_pending_failure_from_previous_retry() -> None:
    scope = SimpleNamespace(
        thread_id="thread-script-retry", task=SimpleNamespace(mutation_sequence=1)
    )
    run_context = RunContext(
        run_id="run-script-failure-retry",
        session_id="session-script-failure-retry",
        session_state={
            REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY: {
                "visualization-task:run-script-failure": {
                    "lastScriptFailed": True,
                    "diagnostics": ["[FAIL] chart: TypeError"],
                }
            }
        },
        dependencies={REPORTING_TASK_DEPENDENCY: {"externalRunId": "visualization-task"}},
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: ({}, {})
    toolkit._inspect_chart = AsyncMock()

    result = await toolkit.register_report_charts([], run_context=run_context)

    assert result["ok"] is False
    assert result["code"] == "report_visualization_script_failed"
    toolkit._inspect_chart.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_rejects_running_visualization_script() -> None:
    scope = SimpleNamespace(
        thread_id="thread-script-running",
        external_run_id="visualization-task-running",
        internal_run_id="run-script-running",
        task=SimpleNamespace(mutation_sequence=1),
    )
    run_context = RunContext(
        run_id="run-script-running",
        session_id="session-script-running",
        session_state={},
        dependencies={REPORTING_TASK_DEPENDENCY: {"externalRunId": "visualization-task-running"}},
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit.repository = SimpleNamespace(
        list_executions=AsyncMock(
            return_value=[
                SimpleNamespace(
                    execution_id="execution-running",
                    internal_run_id="run-script-running",
                    kind="terminal",
                    status="running",
                )
            ]
        )
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: ({}, {})
    toolkit._inspect_chart = AsyncMock()

    result = await toolkit.register_report_charts([], run_context=run_context)

    assert result["ok"] is False
    assert result["code"] == "report_visualization_script_running"
    assert result["retryable"] is True
    toolkit._inspect_chart.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_accepts_missing_optional_run_context() -> None:
    scope = SimpleNamespace(
        thread_id="thread-no-run-context", task=SimpleNamespace(mutation_sequence=1)
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": [],
            "citationDatasetIds": {},
            "visualInspectionMode": "deterministic",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.register_report_charts([], run_context=None)

    assert result["ok"] is True
    toolkit._apply_durable.assert_awaited_once()


@pytest.mark.anyio
async def test_register_report_charts_rejects_metric_code_outside_frozen_catalog() -> None:
    scope = SimpleNamespace(
        thread_id="thread-metric-catalog", task=SimpleNamespace(mutation_sequence=1)
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "allowedMetricCodes": ["income_total"],
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))
    toolkit._inspect_chart = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["invented_metric"],
                "currentPeriod": "2026-01",
                "comparisonType": "none",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
            }
        ],
        run_context=RunContext(run_id="run-metric-catalog", session_id="session-metric-catalog"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_chart_metric_unknown"
    toolkit._inspect_chart.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_allows_defined_metric_when_catalog_is_absent() -> None:
    """null 目录允许 Worker 定义指标；finalize 的 manifest 仍负责冻结同名定义。"""

    scope = SimpleNamespace(
        thread_id="thread-no-metric-catalog", task=SimpleNamespace(mutation_sequence=1)
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "allowedMetricCodes": None,
            "visualInspectionMode": "deterministic",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))
    toolkit._inspect_chart = AsyncMock(
        return_value=(
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income_total"],
                "currentPeriod": "2026-01",
                "comparisonPeriod": None,
                "comparisonType": "none",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
                "comparability": "strict",
                "size": 1024,
                "sha256": "a" * 64,
                "format": "PNG",
                "mediaType": "image/png",
                "extension": ".png",
                "width": 1200,
                "height": 800,
            },
            [],
        )
    )
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income_total"],
                "currentPeriod": "2026-01",
                "comparisonType": "none",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
            }
        ],
        run_context=RunContext(
            run_id="run-no-metric-catalog", session_id="session-no-metric-catalog"
        ),
    )

    assert result["ok"] is True
    toolkit._apply_durable.assert_awaited_once()


@pytest.mark.anyio
async def test_register_report_charts_creates_honest_deterministic_receipt() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=3))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "visualInspectionMode": "deterministic",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"charts": [], "chartInspectionReceipts": []})
    )
    identity = {
        "chartId": "income",
        "sourcePath": "analysis/charts/income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01",
        "comparisonPeriod": None,
        "comparisonType": "none",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
        "comparability": "strict",
        "size": 1024,
        "sha256": "a" * 64,
        "format": "PNG",
        "mediaType": "image/png",
        "extension": ".png",
        "width": 1200,
        "height": 800,
    }
    toolkit._inspect_chart = AsyncMock(return_value=(identity, []))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "comparisonType": "none",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is True
    receipt = toolkit._apply_durable.await_args.kwargs["payload"]["charts"][0][
        "visualInspectionReceipt"
    ]
    assert receipt == {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "a" * 64,
        "inspectionMode": "deterministic",
        "visualReviewStatus": "not_run",
        "inspectorId": "deterministic-raster-inspector-v1",
        "modelId": None,
        "reviewed": True,
        "requiresRevision": False,
        "issues": [],
        "summary": "已通过确定性图片文件检查；未运行模型视觉审查。",
        "warnings": ["未运行模型视觉审查。"],
        "suggestions": [],
    }
    assert result["warnings"] == [
        {
            "code": "chart_visual_review_not_run",
            "chartId": "income",
            "message": "未运行模型视觉审查；图表仅通过确定性图片文件检查。",
        }
    ]


@pytest.mark.anyio
async def test_register_report_charts_rejects_primary_dataset_absent_from_citations() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=3))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-yoy"],
            "citationDatasetIds": {"citation-yoy": "dataset-yoy"},
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._inspect_chart = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-yoy"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "comparisonPeriod": "2025-01",
                "comparisonType": "yoy",
                "sourceDatasetId": "dataset-current",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_chart_citation_dataset_mismatch"
    assert result["details"] == {
        "chartId": "income",
        "sourceDatasetId": "dataset-current",
        "citationDatasetIds": ["dataset-yoy"],
    }
    toolkit._inspect_chart.assert_not_awaited()


@pytest.mark.anyio
async def test_register_report_charts_rejects_retained_chart_before_inspection() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=0))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "retainedChartIds": ["income"],
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"charts": [], "chartInspectionReceipts": []})
    )
    toolkit._inspect_chart = AsyncMock()
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "comparisonPeriod": "2025-01",
                "comparisonType": "yoy",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_chart_registration_duplicate"
    assert "只能登记缺失图表" in result["message"]
    toolkit._inspect_chart.assert_not_awaited()
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_inspect_chart_rejects_path_outside_signed_output_root() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=0))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {"visualizationWorkspace": {"chartOutputRoot": "analysis/charts"}},
    )
    toolkit._vision_reviewer = SimpleNamespace(review=AsyncMock())

    result = await toolkit.inspect_chart(
        path="analysis/private.png",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_chart_source_path_forbidden"
    toolkit._vision_reviewer.review.assert_not_awaited()


@pytest.mark.anyio
async def test_inspect_chart_rejects_deterministic_mode_before_reading_file() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=0))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "visualInspectionMode": "deterministic",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._inspect_chart_file = AsyncMock()
    toolkit._vision_reviewer = SimpleNamespace(review=AsyncMock())

    result = await toolkit.inspect_chart(
        path="analysis/charts/income.png",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_phase_tool_forbidden"
    toolkit._inspect_chart_file.assert_not_awaited()
    toolkit._vision_reviewer.review.assert_not_awaited()


@pytest.mark.anyio
async def test_inspect_chart_persists_hash_bound_receipt() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=0))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {"visualizationWorkspace": {"chartOutputRoot": "analysis/charts"}},
    )
    toolkit._inspect_chart_file = AsyncMock(
        return_value={"sourcePath": "analysis/charts/income.png", "sha256": "a" * 64}
    )
    receipt = {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "a" * 64,
        "inspectionMode": "vision",
        "visualReviewStatus": "passed",
        "inspectorId": None,
        "modelId": "vision-model",
        "reviewed": True,
        "requiresRevision": False,
        "issues": [],
        "summary": "检查完成",
        "warnings": [],
        "suggestions": [],
    }
    toolkit._vision_reviewer = SimpleNamespace(review=AsyncMock(return_value=receipt))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.inspect_chart(
        path="analysis/charts/income.png",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result == {"ok": True, "status": "reviewed", "receipt": receipt}
    toolkit._apply_durable.assert_awaited_once()
    assert toolkit._apply_durable.await_args.kwargs["name"] == "record_chart_inspection"
    assert toolkit._apply_durable.await_args.kwargs["payload"] == {"receipt": receipt}


@pytest.mark.anyio
@pytest.mark.parametrize(("width", "height"), [(1199, 675), (1200, 674)])
async def test_inspect_chart_warns_below_minimum_dimensions(width: int, height: int) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(
        return_value=_chart_identity(width=width, height=height)
    )

    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1",
        registration=_chart_registration(),
    )

    assert identity["chartId"] == "income"
    warning = next(item for item in warnings if item["code"] == "chart_low_resolution")
    assert warning == {
        "code": "chart_low_resolution",
        "chartId": "income",
        "width": width,
        "height": height,
        "minimumWidth": 1200,
        "minimumHeight": 675,
        "message": "图表尺寸偏低，仅作为非阻断质量告警。",
    }


@pytest.mark.anyio
async def test_inspect_chart_warns_below_effective_a4_body_dpi() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_identity(width=1000, height=700))

    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1",
        registration=_chart_registration(),
    )

    assert identity["chartId"] == "income"
    warning = next(item for item in warnings if item["code"] == "chart_low_effective_dpi")
    assert warning == {
        "code": "chart_low_effective_dpi",
        "chartId": "income",
        "width": 1000,
        "height": 700,
        "effectiveDpi": 146.0,
        "minimumDpi": 150,
        "message": "按 A4 正文全宽估算的有效分辨率偏低，仅作为非阻断质量告警。",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(("width", "expected_effective_dpi"), [(1027, 149.9), (1028, None)])
async def test_inspect_chart_effective_dpi_uses_raw_threshold(
    width: int, expected_effective_dpi: float | None
) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_identity(width=width, height=700))

    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1",
        registration=_chart_registration(),
    )

    assert identity["chartId"] == "income"
    dpi_warnings = [item for item in warnings if item["code"] == "chart_low_effective_dpi"]
    if expected_effective_dpi is None:
        assert dpi_warnings == []
    else:
        assert dpi_warnings[0]["effectiveDpi"] == expected_effective_dpi


@pytest.mark.anyio
async def test_inspect_chart_at_minimum_dimensions_has_no_low_resolution_warning() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_identity(width=1200, height=675))

    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1",
        registration=_chart_registration(),
    )

    assert identity["chartId"] == "income"
    assert not any(item["code"] == "chart_low_resolution" for item in warnings)


@pytest.mark.anyio
async def test_inspect_chart_file_rejects_non_image_content() -> None:
    @asynccontextmanager
    async def client_context():
        yield object()

    service = SimpleNamespace(
        normalize_path=lambda path, **_kwargs: (path, f"/workspace/{path}"),
        _async_client=client_context,
        _asandbox_for=AsyncMock(return_value=object()),
        _avalidate_existing_path=AsyncMock(),
        _ainfo=AsyncMock(return_value=SimpleNamespace(size=12)),
        _is_regular_file=lambda _info: True,
        _adownload_file=AsyncMock(return_value=b"not-an-image"),
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(service=service)

    with pytest.raises(ReportingError) as raised:
        await toolkit._inspect_chart_file(
            thread_id="thread-1",
            path="analysis/charts/not-image.png",
        )

    assert raised.value.code == "report_chart_source_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("receipts", "code"),
    [
        ([], "report_chart_inspection_missing"),
        (
            [
                {
                    "sourcePath": "analysis/charts/income.png",
                    "sha256": "b" * 64,
                    "modelId": "vision-model",
                    "reviewed": True,
                    "requiresRevision": False,
                    "issues": [],
                }
            ],
            "report_chart_inspection_changed",
        ),
        (
            [
                {
                    "sourcePath": "analysis/charts/income.png",
                    "sha256": "a" * 64,
                    "modelId": "vision-model",
                    "reviewed": True,
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "cropping",
                            "severity": "critical",
                            "description": "标题裁切",
                        },
                        {
                            "category": "text_overlap",
                            "severity": "critical",
                            "description": "文字重叠",
                        },
                    ],
                }
            ],
            "report_chart_inspection_failed",
        ),
        (
            [
                {
                    "sourcePath": "analysis/charts/income.png",
                    "sha256": "a" * 64,
                    "inspectionMode": "deterministic",
                    "visualReviewStatus": "not_run",
                    "inspectorId": "deterministic-raster-inspector-v1",
                    "modelId": None,
                    "reviewed": True,
                    "requiresRevision": False,
                    "issues": [],
                }
            ],
            "report_chart_inspection_failed",
        ),
    ],
)
async def test_register_report_charts_requires_current_acceptable_inspection(
    receipts: list[dict[str, Any]], code: str
) -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=3))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_finalize"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "citationIds": ["citation-1"],
            "citationDatasetIds": {"citation-1": "dataset-1"},
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(payload={"charts": [], "chartInspectionReceipts": receipts})
    )
    toolkit._inspect_chart = AsyncMock(
        return_value=(
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "sha256": "a" * 64,
                "size": 1024,
                "format": "PNG",
                "mediaType": "image/png",
                "extension": ".png",
                "width": 1200,
                "height": 800,
            },
            [],
        )
    )

    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/income.png",
                "title": "收入趋势",
                "altText": "收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income"],
                "currentPeriod": "2026-01",
                "comparisonPeriod": "2025-01",
                "comparisonType": "yoy",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is False
    assert result["code"] == code


def test_write_analysis_files_schema_exposes_every_underlying_primitive() -> None:
    parameters = _analysis_write_parameters(write_functions())

    assert parameters["properties"]["operation"]["enum"] == sorted(ANALYSIS_WRITE_PUBLIC_TOOL_NAMES)
    assert parameters["required"] == ["operation"]
    assert set(parameters["properties"]) == {
        "operation",
        "path",
        "content",
        "expected_sha256",
        "old_string",
        "new_string",
        "replace_all",
        "patch",
    }
    assert "arguments" not in parameters["properties"]
    assert "oneOf" not in parameters
    assert (
        '{"operation":"create_file","path":' in parameters["properties"]["operation"]["description"]
    )
    assert "content 单字符串" in parameters["properties"]["content"]["description"]


def test_write_analysis_files_create_file_is_canonicalized_to_existing_primitive() -> None:
    tool_name, arguments = _canonical_analysis_write_call(
        "create_file",
        {
            "path": "analysis/report.py",
            "content": "def main():\n    return 1\n",
        },
    )

    assert tool_name == "create_files"
    assert arguments == {
        "files": [
            {
                "path": "analysis/report.py",
                "content": "def main():\n    return 1\n",
            }
        ]
    }


def test_write_analysis_files_drops_inactive_neutral_fields() -> None:
    arguments = _analysis_write_operation_arguments(
        "replace_text",
        {
            "path": "analysis/report.py",
            "content": "",
            "expected_sha256": "",
            "old_string": "before",
            "new_string": "after",
            "replace_all": False,
            "patch": "",
        },
    )

    assert arguments == {
        "path": "analysis/report.py",
        "old_string": "before",
        "new_string": "after",
        "replace_all": False,
    }


def test_write_analysis_files_drops_empty_create_file_alternative() -> None:
    arguments = _analysis_write_operation_arguments(
        "create_file",
        {
            "path": "analysis/report.py",
            "content": "print('ok')\n",
            "expected_sha256": "",
            "old_string": "",
            "new_string": "",
            "replace_all": False,
            "patch": "",
        },
    )

    assert arguments == {
        "path": "analysis/report.py",
        "content": "print('ok')\n",
    }


def test_write_analysis_files_drops_nonempty_inactive_create_file_fields() -> None:
    arguments = _analysis_write_operation_arguments(
        "create_file",
        {
            "path": "analysis/report.py",
            "content": "print('ok')\n",
            "expected_sha256": "0" * 64,
            "old_string": "stale",
            "new_string": "stale",
            "replace_all": True,
            "patch": "--- a/old.py\n+++ b/old.py\n",
        },
    )

    assert arguments == {"path": "analysis/report.py", "content": "print('ok')\n"}


@pytest.mark.parametrize(
    ("operation", "arguments", "expected"),
    [
        (
            "overwrite_file",
            {
                "path": "analysis/report.py",
                "content": "after",
                "expected_sha256": "a" * 64,
                "old_string": "before",
                "new_string": "after",
                "replace_all": True,
                "patch": "--- a/report.py\n+++ b/report.py\n",
            },
            {
                "path": "analysis/report.py",
                "content": "after",
                "expected_sha256": "a" * 64,
            },
        ),
        (
            "replace_text",
            {
                "path": "analysis/report.py",
                "old_string": "before",
                "new_string": "after",
                "replace_all": True,
                "content": "ignored",
                "expected_sha256": "a" * 64,
                "patch": "--- a/report.py\n+++ b/report.py\n",
            },
            {
                "path": "analysis/report.py",
                "old_string": "before",
                "new_string": "after",
                "replace_all": True,
            },
        ),
        (
            "apply_patch",
            {
                "patch": "--- a/report.py\n+++ b/report.py\n@@ -1 +1 @@\n-before\n+after\n",
                "path": "analysis/report.py",
                "content": "ignored",
                "expected_sha256": "a" * 64,
                "old_string": "before",
                "new_string": "after",
                "replace_all": True,
            },
            {
                "patch": "--- a/report.py\n+++ b/report.py\n@@ -1 +1 @@\n-before\n+after\n",
            },
        ),
    ],
)
def test_write_analysis_files_drops_nonempty_inactive_fields_for_each_operation(
    operation: str,
    arguments: dict[str, object],
    expected: dict[str, object],
) -> None:
    assert _analysis_write_operation_arguments(operation, arguments) == expected


def test_write_analysis_files_create_file_accepts_complete_content() -> None:
    tool_name, arguments = _canonical_analysis_write_call(
        "create_file",
        {
            "path": "analysis/report.py",
            "content": "def main():\n    return 1\n",
        },
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    canonical, paths, _expected_states, _payload_bytes = toolkit._validate_analysis_write_arguments(
        tool_name, arguments
    )

    assert paths == ("analysis/report.py",)
    assert canonical["files"][0]["content"] == "def main():\n    return 1\n"


def test_write_analysis_files_rejects_content_lines() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    with pytest.raises(ReportingError) as raised:
        toolkit._validate_analysis_write_arguments(
            "create_files",
            {
                "files": [
                    {
                        "path": "analysis/report.py",
                        "contentLines": ["x = 1"],
                    }
                ]
            },
        )

    assert raised.value.code == "report_analysis_write_intent_invalid"


def test_write_analysis_files_rejects_multiple_create_files_targets() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    with pytest.raises(ReportingError) as raised:
        toolkit._validate_analysis_write_arguments(
            "create_files",
            {
                "files": [
                    {"path": "analysis/a.py", "content": "a = 1\n"},
                    {"path": "analysis/b.py", "content": "b = 2\n"},
                ]
            },
        )

    assert raised.value.code == "report_analysis_write_intent_invalid"
    assert "一个文件" in raised.value.message


def test_write_analysis_files_accepts_long_content_in_one_create() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    canonical, paths, _expected_states, _payload_bytes = toolkit._validate_analysis_write_arguments(
        "create_files",
        {
            "files": [
                {
                    "path": "analysis/report.py",
                    "content": "".join(f"line_{index} = {index}\n" for index in range(500)),
                }
            ]
        },
    )

    assert paths == ("analysis/report.py",)
    content = canonical["files"][0]["content"]
    assert content.startswith("line_0 = 0\n")
    assert content.endswith("line_499 = 499\n")
    assert len(content.splitlines()) == 500


def test_write_analysis_files_accepts_long_single_content_line() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    long_line = "payload = " + repr("x" * 4000)

    canonical, paths, _expected_states, _payload_bytes = toolkit._validate_analysis_write_arguments(
        "create_files",
        {
            "files": [
                {
                    "path": "analysis/report.py",
                    "content": long_line,
                }
            ]
        },
    )

    assert paths == ("analysis/report.py",)
    assert canonical["files"][0]["content"] == long_line


def test_write_analysis_files_rejects_intent_over_four_mib() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    with pytest.raises(ReportingError) as raised:
        toolkit._validate_analysis_write_arguments(
            "create_files",
            {
                "files": [
                    {
                        "path": "analysis/report.py",
                        "content": "x" * MAX_ANALYSIS_WRITE_INTENT_BYTES,
                    }
                ]
            },
        )

    assert raised.value.code == "report_analysis_write_intent_too_large"


def test_write_analysis_files_validation_returns_actionable_field_details() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    with pytest.raises(ReportingError) as raised:
        toolkit._validate_analysis_write_arguments(
            "replace_text",
            {"path": "analysis/report.py", "old": "before", "new": "after"},
        )

    assert raised.value.code == "report_analysis_write_intent_invalid"
    assert raised.value.details == {
        "toolName": "replace_text",
        "path": "arguments",
        "validator": "required",
        "message": "'old_string' is a required property",
        "expectedFields": ["new_string", "old_string", "path", "replace_all"],
    }
    failure = toolkit._failure(raised.value)
    assert failure["details"] == raised.value.details
    assert "details.expectedFields" in failure["requiredActions"][0]


def test_reporting_tool_workspace_error_escapes_for_agent_retry() -> None:
    error = WorkspaceError("daytona read failed")

    with pytest.raises(WorkspaceError) as raised:
        ReportWorkspaceTaskToolkit._failure(error)

    assert raised.value is error


@pytest.mark.anyio
async def test_analysis_python_syntax_error_returns_retryable_receipt(monkeypatch) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)

    async def invalid_source(*, thread_id: str, path: str) -> bytes:
        assert thread_id == "thread"
        assert path == "analysis/report.py"
        return b'print("OK")\\ No newline at end of file'

    monkeypatch.setattr(toolkit, "_analysis_python_source", invalid_source)

    result = await toolkit._analysis_python_dependency_rejection(
        scope=SimpleNamespace(thread_id="thread"),
        command="python3 analysis/report.py",
        workdir=None,
    )

    assert result is not None
    assert result["ok"] is False
    assert result["code"] == "report_analysis_python_syntax_invalid"
    assert result["details"]["path"] == "analysis/report.py"
    assert result["details"]["line"] == 1
    assert result["retryable"] is True


def test_unknown_jmespath_function_returns_short_supported_function_receipt() -> None:
    expression = jmespath.compile("variables | to_entries(@)")
    with pytest.raises(jmespath.exceptions.JMESPathError) as raised:
        expression.search({"variables": {"amount": {"min": 1}}})

    error = _jmespath_reporting_error(
        raised.value,
        code="report_profile_query_invalid",
        subject="Profile query",
    )
    failure = ReportWorkspaceTaskToolkit._failure(error)

    assert failure["code"] == "report_profile_query_invalid"
    assert failure["details"]["unsupportedFunction"] == "to_entries"
    assert "keys" in failure["details"]["supportedFunctions"]
    assert "Traceback" not in failure["message"]
    assert failure["requiredActions"] == [
        "只使用 details.supportedFunctions 中的标准 JMESPath 函数改写 query。"
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("query_profile", "report_profile_query_invalid"),
        ("query_analysis_context", "report_analysis_context_query_invalid"),
    ],
)
async def test_invalid_jmespath_syntax_returns_short_receipt(
    method_name: str,
    expected_code: str,
) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    method = getattr(toolkit, method_name)
    arguments = {"query": "variables[", "purpose": "检查非法语法"}
    if method_name == "query_profile":
        arguments["datasetId"] = "dataset-1"

    result = await method(**arguments)

    assert result["ok"] is False
    assert result["code"] == expected_code
    assert "supportedFunctions" in result["details"]
    assert "Traceback" not in result["message"]


@pytest.mark.anyio
async def test_query_profile_runtime_type_error_returns_short_receipt(monkeypatch) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)

    class Expression:
        def search(self, _value):
            raise TypeError("NoneType object is not iterable")

    monkeypatch.setattr(jmespath, "compile", lambda _query: Expression())
    toolkit.kernel = SimpleNamespace(scope=AsyncMock())
    toolkit.kernel.scope.return_value = SimpleNamespace(thread_id="thread-1")
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"validationContextFile": {"path": "validation.json", "size": 1, "sha256": "a" * 64}},
        {
            "taskKind": "analysis_item",
            "currentAnalysisId": "analysis_001",
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
        },
    )
    toolkit._require_phase_tool = lambda *args, **kwargs: None
    toolkit._read_trusted_json = AsyncMock(
        side_effect=[
            {"analysisContextFile": {"path": "context.json", "size": 1, "sha256": "b" * 64}},
            {
                "datasetContexts": [
                    {
                        "datasetId": "dataset-1",
                        "profileFile": {"path": "profile.json", "size": 1, "sha256": "c" * 64},
                    }
                ]
            },
            {"variables": {}},
        ]
    )

    result = await toolkit.query_profile(
        datasetId="dataset-1",
        query="merge(variables.a, variables.b)",
        purpose="复现 merge 空值",
    )

    assert result["ok"] is False
    assert result["code"] == "report_profile_query_invalid"
    assert "Traceback" not in result["message"]


@pytest.mark.anyio
async def test_query_analysis_facts_reads_only_current_immutable_file_and_bounds_output() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1"))
    )
    current_identity = {
        "path": "facts/analysis_001.json",
        "size": 10,
        "sha256": "a" * 64,
    }
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "currentAnalysisId": "analysis_001",
            "deterministicFactFiles": {
                "analysis_001": current_identity,
                "analysis_002": {
                    "path": "facts/analysis_002.json",
                    "size": 10,
                    "sha256": "b" * 64,
                },
            },
        },
    )
    toolkit._require_phase_tool = lambda *args, **kwargs: None
    toolkit._read_trusted_json = AsyncMock(
        return_value={"metrics": [{"value": value} for value in range(5)]}
    )

    async def return_result(**kwargs):
        return kwargs["result"]

    toolkit._record_and_bound_profile_result = AsyncMock(side_effect=return_result)

    result = await toolkit.query_analysis_facts(
        query="metrics[].value",
        purpose="读取当前分析指标",
        maxItems=2,
    )

    assert result["analysisIds"] == ["analysis_001"]
    assert result["value"] == [0, 1]
    assert result["truncated"] is True
    toolkit._read_trusted_json.assert_awaited_once_with(
        thread_id="thread-1",
        identity=current_identity,
        identity_code="report_analysis_facts_changed",
        structure_code="report_analysis_facts_invalid",
    )


def test_bound_profile_pointer_value_does_not_truncate_metric_scalars_for_array_limit() -> None:
    value, truncated = _bound_profile_pointer_value(
        {
            "field": "income",
            "total": 12,
            "aggregation": "sum",
            "periodStart": "2025-01-01",
            "periodEnd": "2025-12-31",
        },
        max_items=1,
    )

    assert value == {
        "field": "income",
        "total": 12,
        "aggregation": "sum",
        "periodStart": "2025-01-01",
        "periodEnd": "2025-12-31",
    }
    assert truncated is False


@pytest.mark.anyio
async def test_visualization_facts_v1_aggregates_out_of_order_durable_items_in_plan_order() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1"))
    )
    identities = {
        analysis_id: {
            "path": f"facts/{analysis_id}.json",
            "size": 10,
            "sha256": sha * 64,
        }
        for analysis_id, sha in (("analysis_001", "a"), ("analysis_002", "b"))
    }
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationBudgetVersion": 1,
            "analysisIds": ["analysis_001", "analysis_002"],
            "analysisPlans": {
                "analysis_001": {
                    "analysisId": "analysis_001",
                    "domain": "income",
                    "step": "收入趋势",
                    "primaryMetricFamily": "收入",
                    "datasetIds": ["dataset-1"],
                    "ignored": "not projected",
                }
            },
            "deterministicFactFiles": identities,
        },
    )
    toolkit._require_phase_tool = lambda *args, **kwargs: None
    toolkit._read_trusted_json = AsyncMock(side_effect=[{"metrics": [1]}, {"metrics": [2]}])
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "completedAnalysisIds": ["analysis_002", "analysis_001"],
                "analysisPlans": {
                    "analysis_001": {
                        "analysisId": "analysis_001",
                        "domain": "income",
                        "step": "收入趋势",
                        "primaryMetricFamily": "收入",
                        "datasetIds": ["dataset-1"],
                    },
                    "analysis_002": {
                        "analysisId": "analysis_002",
                        "domain": "cost",
                        "step": "成本趋势",
                        "primaryMetricFamily": "成本",
                        "datasetIds": ["dataset-2"],
                    },
                },
                "analysisItems": {
                    "analysis_001": {
                        "summary": "收入增长",
                        "evidenceFiles": [
                            {"path": "evidence/one.json", "size": 8, "sha256": "c" * 64}
                        ],
                        "citationIds": ["citation-1"],
                    },
                    "analysis_002": {
                        "summary": "成本承压",
                        "evidenceFiles": [],
                        "citationIds": ["citation-2"],
                    },
                },
            }
        )
    )

    async def return_result(**kwargs):
        return kwargs["result"]

    toolkit._record_and_bound_profile_result = AsyncMock(side_effect=return_result)

    result = await toolkit.query_analysis_facts(
        query="analyses", purpose="一次聚合读取全部分析", maxItems=50
    )

    assert [item["analysisId"] for item in result["value"]] == [
        "analysis_001",
        "analysis_002",
    ]
    assert result["value"][0] == {
        "analysisId": "analysis_001",
        "facts": {"metrics": [1]},
        "summary": "收入增长",
        "plan": {
            "analysisId": "analysis_001",
            "domain": "income",
            "step": "收入趋势",
            "primaryMetricFamily": "收入",
            "datasetIds": ["dataset-1"],
        },
        "evidenceFiles": [{"path": "evidence/one.json", "size": 8, "sha256": "c" * 64}],
        "citationIds": ["citation-1"],
    }


@pytest.mark.anyio
async def test_visualization_facts_keeps_complete_aggregate_in_128_kib_window() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1"))
    )
    identity = {"path": "facts/analysis_001.json", "size": 10, "sha256": "a" * 64}
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "analysisIds": ["analysis_001"],
            "deterministicFactFiles": {"analysis_001": identity},
        },
    )
    toolkit._require_phase_tool = lambda *args, **kwargs: None
    toolkit._read_trusted_json = AsyncMock(
        return_value={"metrics": [{"label": "x" * 800, "value": index} for index in range(50)]}
    )

    async def return_result(**kwargs):
        return kwargs["result"]

    toolkit._record_and_bound_profile_result = AsyncMock(side_effect=return_result)

    result = await toolkit.query_analysis_facts(
        query="analyses[0].facts.metrics", purpose="一次读取完整指标", maxItems=50
    )

    assert result["itemLimit"] == 50
    assert result["truncated"] is False
    assert len(result["value"]) == 50
    assert toolkit._record_and_bound_profile_result.await_args.kwargs["preview_bytes"] == 128 * 1024


@pytest.mark.anyio
async def test_analysis_item_facts_keeps_16_kib_output_boundary() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1"))
    )
    identity = {"path": "facts/analysis_001.json", "size": 10, "sha256": "a" * 64}
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "currentAnalysisId": "analysis_001",
            "deterministicFactFiles": {"analysis_001": identity},
        },
    )
    toolkit._require_phase_tool = lambda *args, **kwargs: None
    toolkit._read_trusted_json = AsyncMock(
        return_value={"metrics": [{"label": "x" * 800, "value": index} for index in range(50)]}
    )

    async def return_result(**kwargs):
        return kwargs["result"]

    toolkit._record_and_bound_profile_result = AsyncMock(side_effect=return_result)

    result = await toolkit.query_analysis_facts(
        query="metrics", purpose="读取当前分析指标", maxItems=50
    )

    assert result["itemLimit"] < 50
    assert result["truncated"] is True
    assert "preview_bytes" not in toolkit._record_and_bound_profile_result.await_args.kwargs


def test_analysis_context_projection_is_typed_compact_and_current_dataset_only() -> None:
    projection = _analysis_context_projection(
        {
            "datasetContexts": [
                {
                    "datasetId": "dataset-1",
                    "path": "datasets/one.csv",
                    "rowCount": 2,
                    "fields": ["amount"],
                    "profileFile": {"path": "profiles/one.json", "size": 99},
                    "profileModelView": {"large": "not projected"},
                },
                {
                    "datasetId": "dataset-2",
                    "path": "datasets/two.csv",
                    "rowCount": 3,
                    "fields": ["budget"],
                },
            ],
            "warnings": ["数据提醒"],
        },
        {
            "taskKind": "analysis_item",
            "currentAnalysisId": "analysis_001",
            "analysisPlans": {
                "analysis_001": {
                    "analysisId": "analysis_001",
                    "primaryMetricFamily": "收入",
                    "datasetIds": ["dataset-1"],
                }
            },
        },
    )

    assert projection["currentAnalysis"]["primaryMetricFamily"] == "收入"
    assert projection["datasets"] == [
        {
            "datasetId": "dataset-1",
            "path": "datasets/one.csv",
            "rowCount": 2,
            "fields": ["amount"],
        }
    ]
    assert "profileFile" not in projection["datasets"][0]
    assert "profileModelView" not in projection["datasets"][0]


def test_profile_query_receipt_identity_reuses_same_query_across_purposes() -> None:
    first = ProfileReadReceipt.create_query(
        dataset_id="dataset-1",
        query="variables.area.value_counts_without_nan",
        snapshot_hash="a" * 64,
        purpose="读取院区分布",
    )
    second = ProfileReadReceipt.create_query(
        dataset_id="dataset-1",
        query="variables.area.value_counts_without_nan",
        snapshot_hash="a" * 64,
        purpose="复核院区结构",
    )

    assert first.receipt_id == second.receipt_id
    assert first.purpose != second.purpose


@pytest.mark.anyio
async def test_repeated_empty_profile_query_is_rejected_across_purpose_changes() -> None:
    execution_count = 0
    context = RunContext(
        run_id="run-analysis-1",
        session_id="session-analysis",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-task-1",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
            }
        },
    )

    def empty_result(purpose: str) -> dict[str, object]:
        return {
            "ok": True,
            "datasetId": "dataset-1",
            "query": "variables.department.distinct_values",
            "value": None,
            "readReceipt": {
                "receiptId": "profile-read-1",
                "datasetId": "dataset-1",
                "query": "variables.department.distinct_values",
                "snapshotHash": "a" * 64,
                "purpose": purpose,
            },
        }

    def execute(purpose: str):
        def call(**_arguments):
            nonlocal execution_count
            execution_count += 1
            return empty_result(purpose)

        return call

    first = await normalize_reporting_tool_arguments(
        context,
        "query_profile",
        execute("读取科室分类"),
        {
            "datasetId": "dataset-1",
            "query": "variables.department.distinct_values",
            "purpose": "读取科室分类",
            "maxItems": 50,
        },
    )
    repeated = await normalize_reporting_tool_arguments(
        context,
        "query_profile",
        execute("复核科室分类"),
        {
            "datasetId": "dataset-1",
            "query": "variables.department.distinct_values",
            "purpose": "复核科室分类",
            "maxItems": 100,
        },
    )

    assert first["ok"] is True
    assert execution_count == 1
    assert repeated == {
        "ok": False,
        "status": "rejected",
        "code": "report_profile_query_repeated_empty",
        "message": "相同 Profile 快照的相同查询已确认无结果，禁止重复执行。",
        "requiredActions": [
            "不要再次提交相同查询；改用当前分析已有事实、其他合法查询，或明确记录该分布不可用。"
        ],
        "retryable": False,
        "details": {
            "datasetId": "dataset-1",
            "query": "variables.department.distinct_values",
            "snapshotHash": "a" * 64,
            "receiptId": "profile-read-1",
        },
    }


@pytest.mark.anyio
async def test_empty_profile_query_dedup_isolated_by_analysis_task() -> None:
    shared_state: dict[str, object] = {}

    def context(run_id: str, task_id: str) -> RunContext:
        return RunContext(
            run_id=run_id,
            session_id="session-analysis",
            session_state=shared_state,
            dependencies={
                REPORTING_TASK_DEPENDENCY: {
                    "externalRunId": task_id,
                    REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                    REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                }
            },
        )

    def empty_result(snapshot_hash: str) -> dict[str, object]:
        return {
            "ok": True,
            "datasetId": "dataset-1",
            "query": "variables.department.distinct_values",
            "value": None,
            "readReceipt": {
                "receiptId": f"profile-read-{snapshot_hash[0]}",
                "datasetId": "dataset-1",
                "query": "variables.department.distinct_values",
                "snapshotHash": snapshot_hash,
                "purpose": "读取科室分类",
            },
        }

    arguments = {
        "datasetId": "dataset-1",
        "query": "variables.department.distinct_values",
        "purpose": "读取科室分类",
        "maxItems": 50,
    }
    first_task = context("run-analysis-1", "analysis-task-1")

    first = await normalize_reporting_tool_arguments(
        first_task, "query_profile", lambda **_arguments: empty_result("a" * 64), arguments
    )
    other_task = await normalize_reporting_tool_arguments(
        context("run-analysis-2", "analysis-task-2"),
        "query_profile",
        lambda **_arguments: empty_result("a" * 64),
        arguments,
    )
    changed_snapshot_task = await normalize_reporting_tool_arguments(
        context("run-analysis-3", "analysis-task-3"),
        "query_profile",
        lambda **_arguments: empty_result("b" * 64),
        arguments,
    )

    assert first["ok"] is True
    assert other_task["ok"] is True
    assert changed_snapshot_task["ok"] is True


def test_profile_receipt_command_id_binds_full_receipt_payload() -> None:
    first = ProfileReadReceipt.create_query(
        dataset_id="dataset-1",
        query="variables.area.value_counts_without_nan",
        snapshot_hash="a" * 64,
        purpose="读取院区分布",
    ).model_dump(mode="json", by_alias=True)
    second = {**first, "purpose": "复核院区结构"}

    assert _profile_receipt_command_id(first) == _profile_receipt_command_id(dict(first))
    assert _profile_receipt_command_id(first) != _profile_receipt_command_id(second)


@pytest.mark.anyio
async def test_pending_create_files_recovers_matching_written_files() -> None:
    content = "x = 1\n"
    identity = {
        "path": "analysis/report.py",
        "size": len(content.encode()),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(abatch_hash_files=AsyncMock(return_value=[identity]))
    )
    toolkit._apply_durable = AsyncMock(return_value=object())
    scope = SimpleNamespace(thread_id="thread-1")

    result = await toolkit._recover_pending_analysis_write(
        scope=scope,
        tool_name="create_files",
        canonical={"files": [{"path": "analysis/report.py", "content": content}]},
        paths=("analysis/report.py",),
        intent_sha256="a" * 64,
        payload_bytes=123,
    )

    assert result == {
        "ok": True,
        "status": "committed",
        "intentSha256": "a" * 64,
        "bytes": 123,
        "artifacts": [identity],
        "recovered": True,
    }
    toolkit._apply_durable.assert_awaited_once_with(
        scope,
        name="commit_write_intent",
        payload={"intentId": "a" * 64, "artifacts": [identity]},
        command_id=f"write-commit:{'a' * 64}",
    )


@pytest.mark.anyio
async def test_pending_create_files_rejects_changed_written_file() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[{"path": "analysis/report.py", "size": 7, "sha256": "b" * 64}]
            )
        )
    )
    toolkit._apply_durable = AsyncMock()

    with pytest.raises(ReportingError) as raised:
        await toolkit._recover_pending_analysis_write(
            scope=SimpleNamespace(thread_id="thread-1"),
            tool_name="create_files",
            canonical={"files": [{"path": "analysis/report.py", "content": "x = 1\n"}]},
            paths=("analysis/report.py",),
            intent_sha256="a" * 64,
            payload_bytes=123,
        )

    assert raised.value.code == "report_analysis_write_identity_mismatch"
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_pending_create_files_with_missing_target_continues_write() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[{"path": "analysis/report.py", "missing": True}]
            )
        )
    )
    toolkit._apply_durable = AsyncMock()

    result = await toolkit._recover_pending_analysis_write(
        scope=SimpleNamespace(thread_id="thread-1"),
        tool_name="create_files",
        canonical={"files": [{"path": "analysis/report.py", "content": "x = 1\n"}]},
        paths=("analysis/report.py",),
        intent_sha256="a" * 64,
        payload_bytes=123,
    )

    assert result is None
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_write_path_conflict_returns_retryable_receipt() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    scheduler = SimpleNamespace(write=lambda: context(None))
    scope = SimpleNamespace(thread_id="thread-1")
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(scheduler),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(side_effect=WorkspacePathConflict("目标文件已经存在。")),
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[
                    {
                        "path": "analysis/report.py",
                        "size": 12,
                        "sha256": "a" * 64,
                    }
                ]
            )
        ),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"},
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"writeIntents": {}}))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.write_analysis_files(
        operation="create_file",
        path="analysis/report.py",
        content="print('ok')\n",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_analysis_write_path_conflict"
    assert result["details"] == {
        "paths": ["analysis/report.py"],
        "currentFiles": [{"path": "analysis/report.py", "size": 12, "sha256": "a" * 64}],
        "recoveryOperation": "overwrite_file",
    }
    assert "当前 64 位 sha256" in result["requiredActions"][0]
    assert "不得用 create_file 覆盖" in result["requiredActions"][0]
    toolkit._apply_durable.assert_awaited_once()


@pytest.mark.anyio
async def test_analysis_write_rejects_invalid_python_before_workspace_mutation() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    source = "print('ok')\n"
    scope = SimpleNamespace(thread_id="thread-1")
    identity = {
        "path": "analysis/report.py",
        "size": len(source.encode()),
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(
            SimpleNamespace(write=lambda: context(None))
        ),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(return_value={"ok": True}),
        service=SimpleNamespace(
            file_bytes=lambda _thread_id, _path: (source.encode(), "text/x-python"),
            abatch_hash_files=AsyncMock(return_value=[identity]),
        ),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"},
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"writeIntents": {}}))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.write_analysis_files(
        operation="replace_text",
        path="analysis/report.py",
        old_string="print('ok')",
        new_string="print('",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_analysis_python_syntax_invalid"
    assert result["details"]["path"] == "analysis/report.py"
    assert source == "print('ok')\n"
    toolkit.kernel.patch.assert_not_awaited()
    toolkit._apply_durable.assert_not_awaited()


@pytest.mark.anyio
async def test_analysis_write_allows_valid_python_replace() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    source = "print('ok')\n"
    updated = "print('done')\n"
    scope = SimpleNamespace(thread_id="thread-1")
    identity = {
        "path": "analysis/report.py",
        "size": len(updated.encode()),
        "sha256": hashlib.sha256(updated.encode()).hexdigest(),
    }
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(
            SimpleNamespace(write=lambda: context(None))
        ),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(return_value={"ok": True}),
        service=SimpleNamespace(
            file_bytes=lambda _thread_id, _path: (source.encode(), "text/x-python"),
            abatch_hash_files=AsyncMock(return_value=[identity]),
        ),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"},
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"writeIntents": {}}))
    toolkit._apply_durable = AsyncMock()

    result = await toolkit.write_analysis_files(
        operation="replace_text",
        path="analysis/report.py",
        old_string="print('ok')",
        new_string="print('done')",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is True
    assert result["status"] == "committed"
    assert result["artifacts"] == [identity]
    toolkit.kernel.patch.assert_awaited_once()
    assert toolkit._apply_durable.await_args_list[-1].kwargs == {
        "name": "commit_write_intent",
        "payload": {"intentId": result["intentSha256"], "artifacts": [identity]},
        "command_id": f"write-commit:{result['intentSha256']}",
    }


@pytest.mark.anyio
async def test_replace_text_not_found_returns_retryable_stable_error() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    source = "print('ok')\n"
    scope = SimpleNamespace(thread_id="thread-1")
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(
            SimpleNamespace(write=lambda: context(None))
        ),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(return_value={"ok": True}),
        service=SimpleNamespace(
            file_bytes=lambda _thread_id, _path: (source.encode(), "text/plain")
        ),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"},
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None

    result = await toolkit.write_analysis_files(
        operation="replace_text",
        path="analysis/report.py",
        old_string="missing",
        new_string="done",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_replace_target_not_found"
    assert result["retryable"] is True
    assert result["details"]["path"] == "analysis/report.py"
    assert result["details"]["matchCount"] == 0
    assert len(result["details"]["preview"]) <= 200
    assert "/" not in result["details"]["path"] or result["details"]["path"].startswith("analysis/")


@pytest.mark.anyio
async def test_replace_text_ambiguous_returns_retryable_stable_error() -> None:
    @asynccontextmanager
    async def context(value):
        yield value

    source = "x\nx\n"
    scope = SimpleNamespace(thread_id="thread-1")
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()
    toolkit.kernel = SimpleNamespace(
        bound_external_run_id=lambda _run_context: "external-run-1",
        task_scheduler=lambda _external_run_id: context(
            SimpleNamespace(write=lambda: context(None))
        ),
        scope=AsyncMock(return_value=scope),
        patch=AsyncMock(return_value={"ok": True}),
        service=SimpleNamespace(
            file_bytes=lambda _thread_id, _path: (source.encode(), "text/plain")
        ),
    )
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisOutputRoot": "analysis"},
    )
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None

    result = await toolkit.write_analysis_files(
        operation="replace_text",
        path="analysis/report.py",
        old_string="x",
        new_string="y",
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["code"] == "report_replace_target_ambiguous"
    assert result["retryable"] is True
    assert result["details"]["matchCount"] == 2


@pytest.mark.anyio
async def test_analysis_write_hash_failure_preserves_original_error() -> None:
    error = DaytonaError("temporary download failure")
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(abatch_hash_files=AsyncMock(side_effect=error))
    )

    with pytest.raises(DaytonaError) as raised:
        await toolkit._analysis_write_hash_files(
            thread_id="thread-1",
            paths=("analysis/report.py",),
        )

    assert raised.value is error


def test_successful_tool_call_resets_no_progress_failure_count() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    failure = {"ok": False, "code": "report_tool_arguments_invalid"}

    assert _enforce_reporting_no_progress(context, "terminal", failure) == failure
    guided = _enforce_reporting_no_progress(context, "terminal", failure)
    assert guided["details"]["sameFailureCount"] == 2
    assert guided["requiredActions"]
    assert context.session_state[_REPORT_TOOL_FAILURE_STATE_KEY]["phaseFailureCount"] == 2

    success = {"ok": True, "status": "accepted"}
    assert _enforce_reporting_no_progress(context, "write_analysis_files", success) == success
    assert _REPORT_TOOL_FAILURE_STATE_KEY not in context.session_state

    assert _enforce_reporting_no_progress(context, "terminal", failure) == failure
    assert context.session_state[_REPORT_TOOL_FAILURE_STATE_KEY]["phaseFailureCount"] == 1


def test_repeated_failure_without_progress_stops_after_same_failure_limit() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    failure = {"ok": False, "code": "report_tool_arguments_invalid"}

    first = _enforce_reporting_no_progress(context, "terminal", failure)
    second = _enforce_reporting_no_progress(context, "terminal", failure)
    with pytest.raises(StopAgentRun) as stopped:
        _enforce_reporting_no_progress(context, "terminal", failure)

    receipt = json.loads(str(stopped.value))
    assert first == failure
    assert second["details"]["sameFailureCount"] == 2
    assert "只修改服务端 code/details" in second["requiredActions"][-1]
    assert receipt["code"] == "report_tool_arguments_invalid"
    assert receipt["retryable"] is False
    assert receipt["details"]["terminalReason"] == "tool_no_progress"
    assert receipt["details"]["failureFingerprint"]
    assert receipt["details"]["sameFailureCount"] == 3
    assert receipt["details"]["phaseFailureCount"] == 3


def test_nonretryable_reporting_tool_result_stops_function_run() -> None:
    function_call = SimpleNamespace(
        function=SimpleNamespace(stop_after_tool_call=False),
        result={"ok": False, "code": "tool_no_progress", "retryable": False},
    )

    _stop_after_nonretryable_tool_call(function_call)

    assert function_call.function.stop_after_tool_call is True


def test_phase_failure_limit_stops_distinct_failures_without_progress() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    for index in range(7):
        result = _enforce_reporting_no_progress(
            context,
            "write_analysis_files",
            {"ok": False, "code": "report_analysis_write_intent_invalid"},
            {"path": f"analysis/{index}.py"},
        )
        assert result["code"] == "report_analysis_write_intent_invalid"
    with pytest.raises(StopAgentRun) as stopped:
        _enforce_reporting_no_progress(
            context,
            "write_analysis_files",
            {"ok": False, "code": "report_analysis_write_intent_invalid"},
            {"path": "analysis/7.py"},
        )

    receipt = json.loads(str(stopped.value))
    assert receipt["code"] == "report_analysis_write_intent_invalid"
    assert receipt["retryable"] is False
    assert receipt["details"]["terminalReason"] == "tool_no_progress"
    assert receipt["details"]["failureFingerprint"]
    assert receipt["details"]["sameFailureCount"] == 1
    assert receipt["details"]["phaseFailureCount"] == 8


def test_phase_failure_limit_ignores_generic_progress_entries_from_rejections() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    for index in range(7):
        context.session_state["agentos_coding_tool_progress"] = {
            "mutation": 0,
            "entries": [
                {
                    "tool": "process:submit",
                    "mutation": 0,
                    "resultHash": f"rejected-{item}",
                }
                for item in range(index + 1)
            ],
        }
        result = _enforce_reporting_no_progress(
            context,
            "process",
            {"ok": False, "code": "report_visualization_process_forbidden"},
            {"action": "submit", "session_id": f"chart-inspect-{index}"},
        )
        assert result["code"] == "report_visualization_process_forbidden"

    context.session_state["agentos_coding_tool_progress"] = {
        "mutation": 0,
        "entries": [
            {
                "tool": "process:submit",
                "mutation": 0,
                "resultHash": f"rejected-{item}",
            }
            for item in range(8)
        ],
    }
    with pytest.raises(StopAgentRun) as stopped:
        _enforce_reporting_no_progress(
            context,
            "process",
            {"ok": False, "code": "report_visualization_process_forbidden"},
            {"action": "submit", "session_id": "chart-inspect-7"},
        )

    receipt = json.loads(str(stopped.value))
    assert receipt["code"] == "report_visualization_process_forbidden"
    assert receipt["details"]["terminalReason"] == "tool_no_progress"
    assert receipt["details"]["phaseFailureCount"] == 8


def reporting_state_with_artifacts(*artifacts: dict[str, object]) -> ReportingRunState:
    state = ReportingRunState.initial(
        report_run_id="report-run-1",
        external_run_id="external-run-1",
        thread_id="thread-1",
        owner_user_id="user-1",
    )
    return state.model_copy(
        update={
            "payload": {
                **state.payload,
                "writeIntents": {
                    "intent-1": {
                        "status": "committed",
                        "artifacts": list(artifacts),
                    }
                },
            }
        }
    )


def test_complete_analysis_item_schema_allows_server_derived_fact_evidence() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    parameters = toolkit.async_functions["complete_analysis_item"].parameters
    evidence_paths = parameters["properties"]["evidencePaths"]

    assert evidence_paths["minItems"] == 0
    assert "固定事实" in evidence_paths["description"]


def test_analysis_context_tool_reserves_current_analysis_for_task_json() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    description = toolkit.async_functions["query_analysis_context"].description

    assert "currentAnalysis 已在任务 JSON" in description
    assert "仅用于按需读取 Dataset 元数据" in description


def test_analysis_tool_schemas_expose_flat_writes_and_standard_jmespath_patterns() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    write_tool = toolkit.async_functions["write_analysis_files"]
    operation = write_tool.parameters["properties"]["operation"]

    assert "不得嵌套 arguments" in write_tool.description
    assert "不得嵌套 arguments" in operation["description"]
    assert '"operation":"create_file"' in operation["description"]

    expected_examples = {
        "query_profile": '"query":"values(variables)[0]"',
        "query_analysis_context": '"query":"datasets[0]"',
        "query_analysis_facts": '"query":"metrics[0]"',
    }
    for name, expected_example in expected_examples.items():
        description = toolkit.async_functions[name].description
        assert "数组首项" in description
        assert "字段投影" in description
        assert "空值不补值" in description
        assert expected_example in description


def test_analysis_facts_tool_distinguishes_projection_from_file_schema() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    description = toolkit.async_functions["query_analysis_facts"].description

    assert "analyses[].facts 只存在于本工具聚合回执" in description
    assert "单个文件根节点就是对应 analysis 的 facts" in description


def _section_rework_work_item(*, dataset_ids: tuple[str, ...] = ("dataset-1",)) -> SectionWorkItem:
    return SectionWorkItem(
        sectionCode="section_001",
        sectionNumber="1",
        title="收入分析",
        objective="说明收入表现。",
        reportBrief={
            "objective": "经营分析",
            "executiveSummary": "收入表现摘要。",
            "managementQuestions": ["收入表现如何？"],
        },
        completionConditions=("说明限制",),
        analysisIds=("analysis_001",),
        evidence=(
            AnalysisEvidence(
                analysisId="analysis_001",
                summary="当前冻结事实。",
                datasetIds=dataset_ids,
                evidenceFiles=(FileIdentity(path="evidence/income.json", size=1, sha256="a" * 64),),
                citationIds=("citation-1",),
            ),
        ),
        citations=(
            {
                "citationId": "citation-1",
                "datasetId": "dataset-1",
                "requirementId": "requirement-1",
                "snapshotHash": "b" * 64,
            },
        ),
        factFiles=(FileIdentity(path="evidence/income.json", size=1, sha256="a" * 64),),
        factSummaries=("当前冻结事实。",),
        markdownRequirements=("明确限制",),
    )


def _section_rework_contract(
    *, row_counts: tuple[int, ...], bind_datasets: bool = True
) -> dict[str, Any]:
    dataset_ids = tuple(f"dataset-{index}" for index in range(1, len(row_counts) + 1))
    profile_datasets = (
        [
            {
                "datasetId": dataset_id,
                "rowCount": row_count,
                "profileSnapshotHash": "c" * 64,
            }
            for dataset_id, row_count in zip(dataset_ids, row_counts, strict=True)
        ]
        if bind_datasets
        else []
    )
    return {
        "taskKind": "section",
        "analysisReworkConstraints": {
            "analysis_001": {
                "datasetIds": list(dataset_ids),
                "periods": ["2026-01"],
                "metrics": ["revenue"],
                "profileDatasets": profile_datasets,
                "planHash": "e" * 64,
            }
        },
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("row_counts", "bind_datasets", "expected_code"),
    [
        ((0,), True, "report_analysis_rework_unresolvable"),
        ((0,), False, "report_analysis_rework_invalid"),
    ],
)
async def test_analysis_rework_rejects_zero_row_or_unbound_profile_datasets(
    row_counts: tuple[int, ...],
    bind_datasets: bool,
    expected_code: str,
) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=SimpleNamespace()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"reworkRequestPath": "sections/income.rework.json"},
        _section_rework_contract(row_counts=row_counts, bind_datasets=bind_datasets),
    )
    toolkit._section_work_item = AsyncMock(return_value=_section_rework_work_item())
    toolkit._write_phase_json = AsyncMock(
        return_value={"path": "sections/income.rework.json", "size": 1, "sha256": "d" * 64}
    )
    toolkit._finish_phase_task = AsyncMock(return_value={"ok": True, "status": "accepted"})

    result = await toolkit.request_analysis_rework(
        analysisIds=["analysis_001"],
        reason="需要补算。",
        missingEvidence=["重算当前冻结范围。"],
    )

    assert result["code"] == expected_code
    assert result["retryable"] is True
    if expected_code == "report_analysis_rework_unresolvable":
        assert result["requiredActions"] == [
            "停止重复补算；基于冻结零行事实提交明确披露数据限制的 v2 claim 和正文。"
        ]
    toolkit._write_phase_json.assert_not_awaited()
    toolkit._finish_phase_task.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("row_counts", [(1,), (0, 1)])
async def test_analysis_rework_allows_nonzero_frozen_dataset_without_expanding_schema(
    row_counts: tuple[int, ...],
) -> None:
    dataset_ids = tuple(f"dataset-{index}" for index in range(1, len(row_counts) + 1))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=SimpleNamespace()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"reworkRequestPath": "sections/income.rework.json"},
        _section_rework_contract(row_counts=row_counts),
    )
    toolkit._section_work_item = AsyncMock(
        return_value=_section_rework_work_item(dataset_ids=dataset_ids)
    )
    toolkit._write_phase_json = AsyncMock(
        return_value={"path": "sections/income.rework.json", "size": 1, "sha256": "d" * 64}
    )
    toolkit._finish_phase_task = AsyncMock(return_value={"ok": True, "status": "accepted"})

    result = await toolkit.request_analysis_rework(
        analysisIds=["analysis_001"],
        reason="需要按原口径复核。",
        missingEvidence=["复算当前冻结期间。"],
    )

    assert result["status"] == "accepted"
    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert set(payload) == {"version", "sectionCode", "analysisIds", "reason", "missingEvidence"}
    assert payload["analysisIds"] == ["analysis_001"]


@pytest.mark.anyio
async def test_analysis_rework_rejects_analysis_outside_current_work_item() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=SimpleNamespace()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"reworkRequestPath": "sections/income.rework.json"},
        _section_rework_contract(row_counts=(1,)),
    )
    toolkit._section_work_item = AsyncMock(return_value=_section_rework_work_item())
    toolkit._write_phase_json = AsyncMock()

    result = await toolkit.request_analysis_rework(
        analysisIds=["analysis_002"],
        reason="需要其他数据。",
        missingEvidence=["新增数据源。"],
    )

    assert result["code"] == "report_analysis_rework_invalid"
    toolkit._write_phase_json.assert_not_awaited()


_WORKER_TOOL_SCHEMA_NAMES = (
    "finish_task",
    "read_profile_pointer",
    "query_profile",
    "query_analysis_context",
    "query_analysis_facts",
    "write_analysis_files",
    "complete_analysis_item",
    "finalize_report_analysis",
    "inspect_chart",
    "register_report_charts",
    "submit_visualization_charts",
    "render_report_section",
)
_WORKER_TOOL_SCHEMA_FINGERPRINTS = {
    "finish_task": "ab5eb78da519bcfeb7b4d312e2febb3407b8aa43f6d5362e7cd555472f9a6ff4",
    "read_profile_pointer": "b2519d0e7b882bf1ef9cb0943daecf776a012225b5376e08b939684aadfd733d",
    "query_profile": "985e869a7ec204ff3b7ff3b9d411338ce26bfacca34e004f878ccddab01731ec",
    "query_analysis_context": "1c4c56570eb9217299fc221e62d8ba48e08f5fac0c65f3b27df480360f7982d0",
    "query_analysis_facts": "ae90792e199a1560dbd951861bcc197d508d860f6cdbf0d6ffc0f89632a53c9d",
    "write_analysis_files": "9a646ca7f0d6b907829aba11ee9094481221ffa1b4db9a6e611ddde742f423f5",
    "complete_analysis_item": "9c2e0d1eff9bb28aec286154573bbc38c025bd1f3a5d30bb129593beed755fb9",
    "finalize_report_analysis": "0a5a381b7eda6a4b5cdf93302bdc5bd1bcb3aa411bc52745a972dee6f0e99d67",
    "inspect_chart": "c038586b8d6fa4ecefe1c9d75d4d35e217d9e3cf91719c4fd2a7ad78f775c9c6",
    "register_report_charts": "4522acf4b9385c526b7403964b4496ce179ccac2935246da7265de5daebb228c",
    "submit_visualization_charts": "874571111efc572f8e47b837faf3b1a00ea4560f8f0257a8a69cd213e4505451",
    "render_report_section": "b74f37e7093dad682128cfe205c17116dd1bd3578b13575adb6d1ee3da20e724",
}


def _worker_tool_schema_snapshot(toolkit: ReportWorkspaceTaskToolkit) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "name": toolkit.async_functions[name].name,
            "description": toolkit.async_functions[name].description,
            "parameters": toolkit.async_functions[name].parameters,
        }
        for name in _WORKER_TOOL_SCHEMA_NAMES
    }


def test_report_worker_tool_schema_is_stable_from_toolkit_module() -> None:
    module = importlib.import_module("smart_reporting.reporting.tools.toolkit")
    package = importlib.import_module("smart_reporting.reporting.tools")
    toolkit_class = module.ReportWorkspaceTaskToolkit
    toolkit = toolkit_class(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )
    snapshot = _worker_tool_schema_snapshot(toolkit)
    fingerprints = {
        name: hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for name, value in snapshot.items()
    }

    assert package.ReportWorkspaceTaskToolkit is toolkit_class
    assert fingerprints == _WORKER_TOOL_SCHEMA_FINGERPRINTS


@pytest.mark.parametrize(
    ("phase", "task_kind", "required", "forbidden"),
    [
        (
            "analysis",
            "analysis_item",
            {"query_analysis_facts", "complete_analysis_item"},
            {"update_plan", "register_report_charts"},
        ),
        (
            "analysis",
            "visualization_section",
            {"read_file", "terminal"},
            {"update_plan", "complete_analysis_item"},
        ),
        (
            "section",
            "section",
            {"read_file", "render_report_section", "request_analysis_rework"},
            {"update_plan", "replace_text", "query_analysis_facts"},
        ),
    ],
)
def test_report_worker_toolkit_registers_only_current_task_tools(
    phase: str,
    task_kind: str,
    required: set[str],
    forbidden: set[str],
) -> None:
    context = RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        user_id="user-1",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: phase,
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )

    [toolkit] = build_report_worker_tools(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
        run_context=context,
    )
    names = set(toolkit.async_functions)

    assert required <= names
    assert not forbidden & names
    # 阶段工具通过 Toolkit 内部函数对象调用 finish_task 收尾；它仍由模型投影层隐藏。
    assert "finish_task" in names
    if phase == "analysis":
        assert ANALYSIS_WRITE_TOOL_NAMES <= names
    else:
        assert not ANALYSIS_WRITE_TOOL_NAMES & names
    assert "update_plan" not in (toolkit.instructions or "")
    assert "replace_text" not in (toolkit.instructions or "")
    if task_kind == "visualization_section":
        assert "submit_visualization_charts" in names
        assert "register_report_charts" not in names
        assert "finalize_report_analysis" not in names


def test_vision_enabled_visualization_toolkit_exposes_inspection() -> None:
    context = RunContext(
        run_id="run-visualization-vision",
        session_id="session-visualization-vision",
        user_id="user-1",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization_section",
            }
        },
    )

    [toolkit] = build_report_worker_tools(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
        run_context=context,
        vision_reviewer=SimpleNamespace(),
    )

    assert "inspect_chart" in toolkit.async_functions
    assert (
        "每张图必须先调用 inspect_chart"
        in toolkit.async_functions["submit_visualization_charts"].description
    )


def test_render_report_section_schema_does_not_require_server_derived_claim_fields() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    claim_schema = toolkit.async_functions["render_report_section"].parameters["properties"][
        "claims"
    ]["items"]

    assert "managementQuestionRef" in claim_schema["properties"]
    assert "periodBasis" not in claim_schema["properties"]
    assert "managementQuestion" not in claim_schema["properties"]
    assert "currentPeriod" not in claim_schema["required"]
    assert "comparisonPeriod" not in claim_schema["required"]
    assert "comparisonType" not in claim_schema["required"]


def test_render_report_section_description_does_not_invent_metric_code() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    description = toolkit.async_functions["render_report_section"].description or ""

    assert '"metricCode":"income"' not in description
    assert "SectionWorkItem.metricDefinitions.code" in description

    chart_description = toolkit.async_functions["register_report_charts"].description or ""
    assert '"metricCodes":["income"]' not in chart_description
    assert "已冻结分析事实" in chart_description


def test_dynamic_metric_tools_do_not_return_static_correction_examples() -> None:
    error = ValidationError.from_exception_data(
        "SectionClaimSubmission",
        [
            {
                "type": "missing",
                "loc": ("claims", 0, "comparisonPeriod"),
                "input": None,
            }
        ],
    )

    section_failure = _report_tool_argument_failure("render_report_section", error, {})
    chart_failure = _report_tool_argument_failure("register_report_charts", error, {})

    assert "correctCallExample" not in section_failure
    assert "correctCallExample" not in chart_failure


@pytest.mark.anyio
async def test_render_report_section_rejects_inline_image_before_writing_artifact() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/section_003.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(section_code="section_003")
    )
    toolkit._write_phase_json = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(ReportingError) as raised:
        await toolkit._render_isolated_section(
            scope=SimpleNamespace(),
            section_code="section_003",
            blocks=[
                {
                    "blockId": "workload_trend",
                    "markdown": "趋势如下。\n\n![工作量趋势](workload_monthly_trend)",
                    "citationIds": ["citation_011"],
                    "chartIds": ["workload_monthly_trend"],
                }
            ],
            claims=[],
            state={},
            run_context=None,
        )

    assert raised.value.code == "report_draft_protocol_injection"
    assert "chartIds" in raised.value.message
    toolkit._write_phase_json.assert_not_awaited()


@pytest.mark.anyio
async def test_render_report_section_binds_chart_citations_into_block() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/budget.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            section_code="section_002",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_002", question="预算执行如何？"),
            ),
            metric_definitions=(SimpleNamespace(code="revenue", period_basis="2026-01"),),
            charts=(
                SimpleNamespace(
                    chart_id="revenue_budget",
                    citation_ids=("citation_004", "citation_010"),
                    metric_codes=("revenue",),
                    source_dataset_id="dataset-1",
                    current_period="2026-01",
                    comparison_period=None,
                    comparison_type="none",
                    comparability="strict",
                ),
            ),
            citations=(
                SimpleNamespace(citation_id="citation_004", dataset_id="dataset-1"),
                SimpleNamespace(citation_id="citation_010", dataset_id="dataset-1"),
            ),
        )
    )
    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/budget.json"})  # type: ignore[method-assign]
    toolkit._finish_phase_task = AsyncMock(return_value={})  # type: ignore[method-assign]

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_002",
        blocks=[
            {
                "blockId": "budget_overall",
                "markdown": "预算执行情况。",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
                "claimIds": ["claim_revenue"],
            }
        ],
        claims=[
            {
                "claimId": "claim_revenue",
                "metricCode": "revenue",
                "value": 100,
                "managementQuestionRef": "analysis_002",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["blocks"][0]["citationIds"] == ["citation_004", "citation_010"]


@pytest.mark.anyio
async def test_render_report_section_derives_frozen_claim_semantics_on_first_submission() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/income.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            section_code="section_001",
            management_question_catalog=(
                SimpleNamespace(
                    ref="analysis_001",
                    question="2025年医疗收入总体规模及收入类型与构成结构如何？",
                ),
            ),
            metric_definitions=(
                SimpleNamespace(
                    code="medical_income",
                    period_basis="2025年1-11月累计口径",
                ),
            ),
            charts=(
                SimpleNamespace(
                    chart_id="income_monthly_trend",
                    citation_ids=("citation_007", "citation_008"),
                    metric_codes=("medical_income",),
                    source_dataset_id="dataset-1",
                    current_period="2025年1-11月",
                    comparison_period="2024年全年",
                    comparison_type="period",
                    comparability="reference_only",
                ),
            ),
            citations=(
                SimpleNamespace(citation_id="citation_007", dataset_id="dataset-1"),
                SimpleNamespace(citation_id="citation_008", dataset_id="dataset-1"),
            ),
        )
    )
    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/income.json"})  # type: ignore[method-assign]
    toolkit._finish_phase_task = AsyncMock(return_value={})  # type: ignore[method-assign]

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_001",
        blocks=[
            {
                "blockId": "income_overall",
                "markdown": "医疗收入总体保持稳定。",
                "citationIds": ["citation_007"],
                "chartIds": ["income_monthly_trend"],
                "claimIds": ["claim_income_total"],
            }
        ],
        claims=[
            {
                "claimId": "claim_income_total",
                "metricCode": "medical_income",
                "value": "111.24亿元",
                "managementQuestionRef": "analysis_001",
                "citationIds": ["citation_007"],
                "chartIds": ["income_monthly_trend"],
                "conclusionType": "value",
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["claims"] == [
        {
            "claimId": "claim_income_total",
            "metricCode": "medical_income",
            "value": "111.24亿元",
            "periodBasis": "2025年1-11月累计口径",
            "comparison": None,
            "managementQuestion": "2025年医疗收入总体规模及收入类型与构成结构如何？",
            "currentPeriod": "2025年1-11月",
            "comparisonPeriod": "2024年全年",
            "comparisonType": "period",
            "citationIds": ["citation_007", "citation_008"],
            "chartIds": ["income_monthly_trend"],
            "comparability": "reference_only",
            "conclusionType": "value",
            "aggregationGrain": None,
            "entityGrain": None,
        }
    ]
    assert payload["blocks"][0]["citationIds"] == ["citation_007", "citation_008"]
    assert "参考" in payload["blocks"][0]["markdown"]


@pytest.mark.anyio
async def test_render_report_section_warns_for_unknown_management_question_ref() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/income.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            section_code="section_001",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_001", question="收入表现如何？"),
            ),
            metric_definitions=(
                SimpleNamespace(code="medical_income", period_basis="2025年累计口径"),
            ),
            charts=(),
            citations=(SimpleNamespace(citation_id="citation_007", dataset_id="dataset-1"),),
        )
    )

    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/income.json"})
    toolkit._finish_phase_task = AsyncMock(return_value={})

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_001",
        blocks=[
            {
                "blockId": "income_overall",
                "markdown": "医疗收入总体保持稳定。",
                "citationIds": ["citation_007"],
                "claimIds": ["claim_income_total"],
            }
        ],
        claims=[
            {
                "claimId": "claim_income_total",
                "metricCode": "medical_income",
                "value": "111.24亿元",
                "managementQuestionRef": "analysis_999",
                "currentPeriod": "2025年1-11月",
                "citationIds": ["citation_007"],
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["claims"][0]["managementQuestion"] == "未绑定管理问题（analysis_999）"
    assert payload["warnings"][0]["code"] == "report_section_claim_question_unknown"


@pytest.mark.anyio
async def test_render_report_section_omits_structurally_invalid_claim_with_warning() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"sectionOutputPath": "sections/income.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(
        return_value=SimpleNamespace(
            section_code="section_001",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_001", question="收入表现如何？"),
            ),
            metric_definitions=(
                SimpleNamespace(code="medical_income", period_basis="2025年累计口径"),
            ),
            charts=(),
            citations=(SimpleNamespace(citation_id="citation_007", dataset_id="dataset-1"),),
        )
    )
    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/income.json"})
    toolkit._finish_phase_task = AsyncMock(return_value={})

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_001",
        blocks=[
            {
                "blockId": "income_overall",
                "markdown": "医疗收入总体保持稳定。",
                "citationIds": ["citation_007"],
                "claimIds": ["claim_income_total"],
            }
        ],
        claims=[
            {
                "claimId": "claim_income_total",
                "metricCode": "medical_income",
                "value": "111.24亿元",
                "managementQuestionRef": "analysis_001",
                "citationIds": ["citation_007"],
                "conclusionType": "entity_ratio",
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["version"] == "1"
    assert payload["claims"] == []
    assert payload["blocks"][0]["claimIds"] == []
    assert {item["code"] for item in payload["warnings"]} == {
        "report_section_claim_invalid",
        "report_section_block_claim_unknown",
        "report_section_claim_period_missing",
    }


@pytest.mark.anyio
async def test_render_report_section_warns_for_conflicting_chart_semantics() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/income.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            section_code="section_001",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_001", question="收入表现如何？"),
            ),
            metric_definitions=(
                SimpleNamespace(code="medical_income", period_basis="2025年累计口径"),
            ),
            charts=(
                SimpleNamespace(
                    chart_id="income_monthly",
                    citation_ids=("citation_007",),
                    metric_codes=("medical_income",),
                    source_dataset_id="dataset-1",
                    current_period="2025年1-11月",
                    comparison_period=None,
                    comparison_type="none",
                    comparability="strict",
                ),
                SimpleNamespace(
                    chart_id="income_annual",
                    citation_ids=("citation_008",),
                    metric_codes=("medical_income",),
                    source_dataset_id="dataset-1",
                    current_period="2025年全年",
                    comparison_period=None,
                    comparison_type="none",
                    comparability="strict",
                ),
            ),
            citations=(
                SimpleNamespace(citation_id="citation_007", dataset_id="dataset-1"),
                SimpleNamespace(citation_id="citation_008", dataset_id="dataset-1"),
            ),
        )
    )

    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/income.json"})
    toolkit._finish_phase_task = AsyncMock(return_value={})

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_001",
        blocks=[
            {
                "blockId": "income_overall",
                "markdown": "医疗收入总体保持稳定。",
                "citationIds": ["citation_007", "citation_008"],
                "chartIds": ["income_monthly", "income_annual"],
                "claimIds": ["claim_income_total"],
            }
        ],
        claims=[
            {
                "claimId": "claim_income_total",
                "metricCode": "medical_income",
                "value": "111.24亿元",
                "managementQuestionRef": "analysis_001",
                "citationIds": ["citation_007", "citation_008"],
                "chartIds": ["income_monthly", "income_annual"],
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["claims"][0]["chartIds"] == ["income_monthly"]
    assert payload["warnings"][0]["code"] == "report_section_claim_chart_semantics_conflict"


@pytest.mark.anyio
async def test_render_report_section_warns_for_structured_chart_metric_conflict() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (  # type: ignore[method-assign]
        {"sectionOutputPath": "sections/budget.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            section_code="section_002",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_002", question="预算执行如何？"),
            ),
            metric_definitions=(
                SimpleNamespace(code="revenue", period_basis="2026-01"),
                SimpleNamespace(code="margin", period_basis="2026-01"),
            ),
            charts=(
                SimpleNamespace(
                    chart_id="revenue_budget",
                    citation_ids=("citation_004", "citation_010"),
                    metric_codes=("revenue",),
                    source_dataset_id="dataset-1",
                    current_period="2026-01",
                    comparison_period=None,
                    comparison_type="none",
                    comparability="strict",
                ),
            ),
            citations=(
                SimpleNamespace(citation_id="citation_004", dataset_id="dataset-1"),
                SimpleNamespace(citation_id="citation_010", dataset_id="dataset-1"),
            ),
        )
    )

    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/budget.json"})
    toolkit._finish_phase_task = AsyncMock(return_value={})

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_002",
        blocks=[
            {
                "blockId": "budget_overall",
                "markdown": "预算执行情况。",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
                "claimIds": ["claim_revenue"],
            }
        ],
        claims=[
            {
                "claimId": "claim_revenue",
                "metricCode": "margin",
                "value": 100,
                "managementQuestionRef": "analysis_002",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
            }
        ],
        state={},
        run_context=None,
    )

    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    warning = next(
        item
        for item in payload["warnings"]
        if item["code"] == "report_section_claim_chart_conflict"
    )
    assert warning["details"] == {
        "sectionCode": "section_002",
        "claimId": "claim_revenue",
        "chartId": "revenue_budget",
        "conflictType": "metric_code",
        "expectedMetricCodes": ["revenue"],
        "actualMetricCode": "margin",
    }


@pytest.mark.anyio
async def test_render_report_section_overrides_submitted_chart_semantics_with_frozen_values() -> (
    None
):
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"sectionOutputPath": "sections/budget.json"},
        {},
    )
    toolkit._section_work_item = AsyncMock(
        return_value=SimpleNamespace(
            section_code="section_002",
            management_question_catalog=(
                SimpleNamespace(ref="analysis_002", question="预算执行如何？"),
            ),
            metric_definitions=(SimpleNamespace(code="revenue", period_basis="2026-01"),),
            charts=(
                SimpleNamespace(
                    chart_id="revenue_budget",
                    citation_ids=("citation_004", "citation_010"),
                    metric_codes=("revenue",),
                    source_dataset_id="dataset-1",
                    current_period="2026-01",
                    comparison_period=None,
                    comparison_type="none",
                    comparability="strict",
                ),
            ),
            citations=(
                SimpleNamespace(citation_id="citation_004", dataset_id="dataset-1"),
                SimpleNamespace(citation_id="citation_010", dataset_id="dataset-1"),
            ),
        )
    )
    toolkit._write_phase_json = AsyncMock(return_value={"path": "sections/budget.json"})
    toolkit._finish_phase_task = AsyncMock(return_value={})

    await toolkit._render_isolated_section(
        scope=SimpleNamespace(),
        section_code="section_002",
        blocks=[
            {
                "blockId": "budget_overall",
                "markdown": "预算执行情况。",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
                "claimIds": ["claim_revenue"],
            }
        ],
        claims=[
            {
                "claimId": "claim_revenue",
                "metricCode": "revenue",
                "value": 100,
                "managementQuestionRef": "analysis_002",
                "currentPeriod": "错误期间",
                "comparisonPeriod": "错误比较期间",
                "comparisonType": "yoy",
                "citationIds": ["citation_004"],
                "chartIds": ["revenue_budget"],
                "comparability": "reference_only",
            },
        ],
        state={},
        run_context=None,
    )

    [claim] = toolkit._write_phase_json.await_args.kwargs["payload"]["claims"]
    assert claim["periodBasis"] == "2026-01"
    assert claim["currentPeriod"] == "2026-01"
    assert claim["comparisonPeriod"] is None
    assert claim["comparisonType"] == "none"
    assert claim["comparability"] == "strict"
    assert claim["citationIds"] == ["citation_004", "citation_010"]


def test_analysis_evidence_accepts_current_committed_identity() -> None:
    identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}

    ReportWorkspaceTaskToolkit._validate_registered_analysis_evidence(
        durable=reporting_state_with_artifacts(identity),
        identities=[identity],
    )


@pytest.mark.anyio
async def test_analysis_evidence_registers_existing_untracked_file() -> None:
    identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}
    initial = reporting_state_with_artifacts()
    registered = reporting_state_with_artifacts(identity)
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._durable_state = AsyncMock(return_value=initial)
    toolkit._apply_durable = AsyncMock(return_value=registered)
    scope = object()

    durable = await toolkit._ensure_registered_analysis_evidence(scope=scope, identities=[identity])

    assert durable is registered
    toolkit._apply_durable.assert_awaited_once_with(
        scope,
        name="record_artifact",
        payload={"artifact": identity},
        command_id=f"analysis-evidence:analysis/evidence.json:{'a' * 64}",
    )


@pytest.mark.anyio
async def test_complete_analysis_item_rejects_contract_with_multiple_analysis_ids() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=object()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001", "analysis_002"],
            "analysisOutputRoot": "analysis",
        },
    )
    durable = reporting_state_with_artifacts().model_copy(
        update={
            "payload": {
                **reporting_state_with_artifacts().payload,
                "currentAnalysisId": "analysis_002",
            }
        }
    )
    toolkit._durable_state = AsyncMock(return_value=durable)

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="已完成",
        datasetIds=["dataset-1"],
        evidencePaths=["analysis/evidence.json"],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
    )

    assert result["code"] == "report_analysis_item_unknown"


@pytest.mark.anyio
@pytest.mark.parametrize("finish_status", ["accepted", "rejected"])
async def test_complete_analysis_item_finishes_task_and_only_accepted_stops_run(
    finish_status: str,
) -> None:
    identities = [
        {"path": "analysis/evidence-1.json", "size": 12, "sha256": "a" * 64},
        {"path": "analysis/evidence-2.json", "size": 13, "sha256": "b" * 64},
    ]
    durable = reporting_state_with_artifacts(*identities).model_copy(
        update={
            "payload": {
                **reporting_state_with_artifacts(*identities).payload,
                "analysisIds": ["analysis_001", "analysis_002"],
                "currentAnalysisId": "analysis_002",
                "profileReadReceipts": [{"receiptId": "receipt-1", "datasetId": "dataset-1"}],
            }
        }
    )
    advanced = durable.model_copy(
        update={"payload": {**durable.payload, "currentAnalysisId": "analysis_002"}}
    )
    finish_function = SimpleNamespace(name="finish_task")
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1")),
        service=SimpleNamespace(abatch_hash_files=AsyncMock(return_value=identities)),
        finish_task=AsyncMock(
            return_value={"ok": finish_status == "accepted", "status": finish_status}
        ),
    )
    toolkit.async_functions = {"finish_task": finish_function}
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            "analysisOutputRoot": "analysis",
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._ensure_registered_analysis_evidence = AsyncMock(return_value=durable)
    toolkit._apply_durable = AsyncMock(return_value=advanced)

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="2025年1-11月较2024年全年同比下降3.96%。",
        datasetIds=["dataset-1"],
        evidencePaths=[item["path"] for item in identities],
        citationIds=["citation-1"],
        profileReadReceiptIds=["receipt-1"],
        warnings=[],
    )

    assert toolkit.kernel.finish_task.await_args.args[1] == [
        "analysis/evidence-1.json",
        "analysis/evidence-2.json",
    ]
    assert toolkit.kernel.finish_task.await_args.args[5] is finish_function
    submitted = toolkit._apply_durable.await_args.kwargs["payload"]
    assert submitted["summary"] == "2025年1-11月较2024年全年参考对比下降3.96%。"
    assert submitted["warnings"] == ["摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。"]
    function_call = SimpleNamespace(
        function=SimpleNamespace(stop_after_tool_call=True),
        result=result,
    )
    _reset_stop_after_tool_call(function_call)
    assert function_call.function.stop_after_tool_call is False
    _stop_after_accepted_tool_call(function_call)
    assert function_call.function.stop_after_tool_call is (finish_status == "accepted")
    if finish_status == "accepted":
        assert result["taskFinished"] is True
        assert result["readyToFinalize"] is False
    else:
        assert result == {"ok": False, "status": "rejected"}


@pytest.mark.anyio
async def test_complete_analysis_item_recovers_same_durable_payload_and_rejects_conflict() -> None:
    identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}
    frozen_payload = {
        "analysisId": "analysis_001",
        "summary": "收入事实已复核",
        "datasetIds": ["dataset-1"],
        "evidencePaths": [identity["path"]],
        "citationIds": ["citation-1"],
        "profileReadReceiptIds": [],
        "warnings": [],
        "evidenceFiles": [identity],
    }
    durable = reporting_state_with_artifacts(identity).model_copy(
        update={
            "payload": {
                **reporting_state_with_artifacts(identity).payload,
                "analysisIds": ["analysis_001"],
                "completedAnalysisIds": ["analysis_001"],
                "currentAnalysisId": None,
                "analysisItems": {"analysis_001": frozen_payload},
            }
        }
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1")),
        service=SimpleNamespace(abatch_hash_files=AsyncMock(return_value=[identity])),
        finish_task=AsyncMock(return_value={"ok": True, "status": "accepted"}),
    )
    toolkit.async_functions = {"finish_task": SimpleNamespace(name="finish_task")}
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            "analysisOutputRoot": "analysis",
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._ensure_registered_analysis_evidence = AsyncMock(return_value=durable)
    toolkit._apply_durable = AsyncMock()

    recovered = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入事实已复核",
        datasetIds=["dataset-1"],
        evidencePaths=[identity["path"]],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
    )
    conflicted = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="试图替换摘要",
        datasetIds=["dataset-1"],
        evidencePaths=[identity["path"]],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
    )

    assert recovered["status"] == "accepted"
    assert recovered["readyToFinalize"] is True
    assert conflicted["code"] == "report_analysis_item_completion_conflict"
    toolkit._apply_durable.assert_not_awaited()
    assert toolkit.kernel.finish_task.await_count == 1


@pytest.mark.anyio
async def test_complete_analysis_item_uses_immutable_facts_without_model_evidence() -> None:
    fact_identity = {
        "path": "facts/analysis_001.json",
        "size": 128,
        "sha256": "a" * 64,
    }
    durable = reporting_state_with_artifacts(fact_identity).model_copy(
        update={
            "payload": {
                **reporting_state_with_artifacts(fact_identity).payload,
                "analysisIds": ["analysis_001"],
                "currentAnalysisId": "analysis_001",
            }
        }
    )
    advanced = durable.model_copy(
        update={"payload": {**durable.payload, "currentAnalysisId": None}}
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1")),
        service=SimpleNamespace(abatch_hash_files=AsyncMock(return_value=[fact_identity])),
        finish_task=AsyncMock(return_value={"ok": True, "status": "accepted"}),
    )
    toolkit.async_functions = {"finish_task": SimpleNamespace(name="finish_task")}
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            "analysisOutputRoot": "analysis",
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
            "deterministicFactFiles": {"analysis_001": fact_identity},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._ensure_registered_analysis_evidence = AsyncMock(return_value=durable)
    toolkit._apply_durable = AsyncMock(return_value=advanced)

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入同比增长 99.9%。",
        datasetIds=["dataset-1"],
        evidencePaths=[],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
    )

    assert result["status"] == "accepted"
    toolkit.kernel.service.abatch_hash_files.assert_awaited_once_with(
        "thread-1", [fact_identity["path"]]
    )
    submitted = toolkit._apply_durable.await_args.kwargs["payload"]
    assert submitted["evidencePaths"] == [fact_identity["path"]]
    assert submitted["evidenceFiles"] == [fact_identity]
    toolkit.kernel.finish_task.assert_awaited_once()


@pytest.mark.anyio
async def test_complete_analysis_item_rejects_empty_evidence_without_immutable_facts() -> None:
    durable = reporting_state_with_artifacts().model_copy(
        update={
            "payload": {
                **reporting_state_with_artifacts().payload,
                "analysisIds": ["analysis_001"],
                "currentAnalysisId": "analysis_001",
            }
        }
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=object()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "analysis_item",
            "analysisIds": ["analysis_001"],
            "analysisOutputRoot": "analysis",
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入事实已复核",
        datasetIds=["dataset-1"],
        evidencePaths=[],
        citationIds=["citation-1"],
        profileReadReceiptIds=[],
        warnings=[],
    )

    assert result["code"] == "report_analysis_evidence_missing"


def test_analysis_output_paths_are_confined_to_current_item_root() -> None:
    contract = {"analysisOutputRoot": "analysis/analysis_001"}

    ReportWorkspaceTaskToolkit._require_analysis_output_paths(
        contract,
        ["analysis/analysis_001/script.py", "analysis/analysis_001/evidence.json"],
    )
    with pytest.raises(ReportingError, match="专属目录") as raised:
        ReportWorkspaceTaskToolkit._require_analysis_output_paths(
            contract,
            ["analysis/analysis_002/evidence.json"],
        )

    assert raised.value.code == "report_analysis_output_path_invalid"


def test_visualization_contract_only_allows_signed_script_path() -> None:
    contract = {
        "taskKind": "visualization_section",
        "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
    }

    ReportWorkspaceTaskToolkit._require_analysis_task_output_paths(
        contract,
        ["analysis/charts/trend.py"],
    )
    with pytest.raises(ReportingError) as raised:
        ReportWorkspaceTaskToolkit._require_analysis_task_output_paths(
            contract,
            ["analysis/charts/other.py"],
        )

    assert raised.value.code == "report_visualization_write_forbidden"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "command",
    [
        "python3 -c 'print(1)'",
        "python3 analysis/charts/trend.py --extra",
        "ls analysis/charts",
        "find analysis",
        "cat analysis/charts/trend.py",
        "python3 analysis/charts/trend.py <<'PY'\nPY",
    ],
)
async def test_visualization_terminal_rejects_every_command_except_signed_script(
    command: str,
) -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )

    result = await toolkit._visualization_terminal_rejection(
        scope=SimpleNamespace(), arguments={"command": command, "workdir": None}
    )

    assert result["code"] == "report_visualization_terminal_forbidden"
    assert result["retryable"] is False


@pytest.mark.anyio
async def test_visualization_terminal_rejects_script_changed_after_committed_write() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "writeIntents": {
                    "intent": {
                        "status": "committed",
                        "artifacts": [
                            {
                                "path": "analysis/charts/trend.py",
                                "size": 10,
                                "sha256": "a" * 64,
                            }
                        ],
                    }
                }
            }
        )
    )
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[
                    {
                        "path": "analysis/charts/trend.py",
                        "size": 11,
                        "sha256": "b" * 64,
                    }
                ]
            )
        )
    )

    result = await toolkit._visualization_terminal_rejection(
        scope=SimpleNamespace(thread_id="thread-1"),
        arguments={"command": "python3 analysis/charts/trend.py", "workdir": None},
    )

    assert result["code"] == "report_visualization_script_identity_changed"


@pytest.mark.anyio
async def test_visualization_terminal_only_accepts_latest_committed_script_identity() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "writeIntents": {
                    "old": {
                        "status": "committed",
                        "artifacts": [
                            {"path": "analysis/charts/trend.py", "size": 10, "sha256": "a" * 64}
                        ],
                    },
                    "latest": {
                        "status": "committed",
                        "artifacts": [
                            {"path": "analysis/charts/trend.py", "size": 11, "sha256": "b" * 64}
                        ],
                    },
                }
            }
        )
    )
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[{"path": "analysis/charts/trend.py", "size": 10, "sha256": "a" * 64}]
            )
        )
    )

    result = await toolkit._visualization_terminal_rejection(
        scope=SimpleNamespace(thread_id="thread-1"),
        arguments={"command": "python3 analysis/charts/trend.py", "workdir": None},
    )

    assert result["code"] == "report_visualization_script_identity_changed"


@pytest.mark.anyio
async def test_visualization_terminal_records_running_session_without_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._visualization_terminal_rejection = AsyncMock(return_value=None)
    toolkit._analysis_python_dependency_rejection = AsyncMock(return_value=None)
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    async def base_invoke(_self, _tool_name, _arguments, call, _run_context):
        return await call(SimpleNamespace())

    async def running_result(_scope: Any) -> dict[str, str]:
        return {"status": "running", "session_id": "session-42"}

    monkeypatch.setattr(WorkspaceTaskToolkit, "_invoke", base_invoke)
    result = await toolkit._invoke(
        "terminal",
        {"command": "python3 analysis/charts/trend.py"},
        running_result,
        context,
    )

    assert result == {"status": "running", "session_id": "session-42"}
    assert context.session_state["reportingVisualizationSessions"] == ["session-42"]


def test_visualization_process_rejects_foreign_session_and_mutating_action() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"reportingVisualizationSessions": ["owned-session"]},
    )

    foreign = toolkit._visualization_process_rejection(
        scope=SimpleNamespace(),
        arguments={"action": "poll", "session_id": "foreign-session"},
        run_context=context,
    )
    write = toolkit._visualization_process_rejection(
        scope=SimpleNamespace(),
        arguments={"action": "write", "session_id": "owned-session"},
        run_context=context,
    )

    assert foreign["code"] == "report_visualization_process_session_forbidden"
    assert write["code"] == "report_visualization_process_forbidden"


@pytest.mark.anyio
async def test_visualization_read_rejects_all_direct_evidence_access() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "analysisItems": {
                    "analysis_001": {
                        "evidenceFiles": [
                            {
                                "path": "evidence/one.json",
                                "size": 8,
                                "sha256": "a" * 64,
                            }
                        ]
                    }
                }
            }
        )
    )
    toolkit.kernel = SimpleNamespace(service=SimpleNamespace(abatch_hash_files=AsyncMock()))
    scope = SimpleNamespace(thread_id="thread-1")

    forbidden = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="evidence/other.json"
    )
    frozen = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="evidence/one.json"
    )

    assert forbidden["code"] == "report_visualization_evidence_path_forbidden"
    assert frozen["code"] == "report_visualization_evidence_path_forbidden"
    toolkit.kernel.service.abatch_hash_files.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_read_allows_only_latest_committed_signed_script() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(
            payload={
                "analysisItems": {},
                "writeIntents": {
                    "delayed_latest": {
                        "status": "committed",
                        "commitSequence": 2,
                        "artifacts": [
                            {
                                "path": "analysis/charts/trend.py",
                                "size": 11,
                                "sha256": "b" * 64,
                            }
                        ],
                    },
                    "committed_earlier": {
                        "status": "committed",
                        "commitSequence": 1,
                        "artifacts": [
                            {
                                "path": "analysis/charts/trend.py",
                                "size": 10,
                                "sha256": "a" * 64,
                            }
                        ],
                    },
                    "other": {
                        "status": "committed",
                        "artifacts": [
                            {
                                "path": "analysis/charts/other.py",
                                "size": 12,
                                "sha256": "c" * 64,
                            }
                        ],
                    },
                },
            }
        )
    )
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                side_effect=[
                    [
                        {
                            "path": "analysis/charts/trend.py",
                            "size": 11,
                            "sha256": "b" * 64,
                        }
                    ],
                    [
                        {
                            "path": "analysis/charts/trend.py",
                            "size": 10,
                            "sha256": "a" * 64,
                        }
                    ],
                ]
            )
        )
    )
    scope = SimpleNamespace(thread_id="thread-1")

    allowed = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="analysis/charts/trend.py"
    )
    stale = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="analysis/charts/trend.py"
    )
    unsigned = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="analysis/charts/other.py"
    )

    assert allowed is None
    assert stale["code"] == "report_visualization_script_identity_changed"
    assert unsigned["code"] == "report_visualization_evidence_path_forbidden"


def test_visualization_signed_script_read_uses_64_kib_preview_window() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization_section"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )
    scope = SimpleNamespace()

    selected = toolkit._tool_preview_bytes(
        scope,
        "read_file",
        {"path": "analysis/charts/trend.py"},
        {"content": "x" * (40 * 1024)},
    )
    ordinary = toolkit._tool_preview_bytes(
        scope,
        "read_file",
        {"path": "analysis/charts/other.py"},
        {"content": "x" * (40 * 1024)},
    )

    assert selected == 64 * 1024
    assert ordinary is None


@pytest.mark.anyio
async def test_visualization_script_over_64_kib_fails_before_write_intent() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization_section",
            "visualizationWorkspace": {"scriptPath": "analysis/charts/trend.py"},
        },
    )

    with pytest.raises(ReportingError) as raised:
        await toolkit._preflight_analysis_python_write(
            scope=SimpleNamespace(thread_id="thread-1"),
            tool_name="create_files",
            canonical={
                "files": [
                    {
                        "path": "analysis/charts/trend.py",
                        "content": "#" * (64 * 1024 + 1),
                    }
                ]
            },
        )

    assert raised.value.code == "report_visualization_script_too_large"
    assert raised.value.details == {
        "path": "analysis/charts/trend.py",
        "size": 64 * 1024 + 1,
        "limit": 64 * 1024,
    }


def test_analysis_item_acceptance_contract_requires_single_id_and_output_root() -> None:
    base = {
        "taskKind": "analysis_item",
        "analysisIds": ["analysis_001"],
        "analysisOutputRoot": "analysis/analysis_001",
    }

    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "validation.json"},
        phase_contract=base,
    )
    parameters = contract["requirements"][0]["parameters"]
    assert parameters["phaseContract"]["analysisOutputRoot"] == "analysis/analysis_001"
    assert "citationRegistry" not in parameters["phaseContract"]

    with pytest.raises(ValueError, match="唯一 analysisId"):
        build_report_phase_acceptance_contract(
            phase="analysis",
            validation_context_file={"path": "validation.json"},
            phase_contract={**base, "analysisIds": ["analysis_001", "analysis_002"]},
        )


def test_visualization_acceptance_contract_drops_unused_large_projections() -> None:
    analysis_ids = [f"analysis_{index:03d}" for index in range(1, 19)]
    phase_contract = {
        "taskKind": "visualization_finalize",
        "chartsRegistered": True,
        "analysisIds": analysis_ids,
        "analysisPlans": {
            analysis_id: {"analysisId": analysis_id, "step": "复杂分析说明" * 100}
            for analysis_id in analysis_ids
        },
        "analysisDatasetIds": {analysis_id: ["dataset-1"] for analysis_id in analysis_ids},
        "deterministicFactFiles": {
            analysis_id: {
                "path": f"facts/{analysis_id}.json",
                "size": 1,
                "sha256": "a" * 64,
            }
            for analysis_id in analysis_ids
        },
        "datasetIds": ["dataset-1"],
        "citationIds": [f"citation-{index:03d}" for index in range(1, 19)],
        "citationRegistry": [
            {"citationId": f"citation-{index:03d}", "quote": "大型引用正文" * 200}
            for index in range(1, 19)
        ],
        "citationDatasetIds": {f"citation-{index:03d}": "dataset-1" for index in range(1, 19)},
    }

    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "validation.json", "size": 1, "sha256": "b" * 64},
        phase_contract=phase_contract,
        analysis_output_path="analysis/final.json",
    )
    normalized = normalize_acceptance_contract(contract)
    trusted = normalized["requirements"][0]["parameters"]["phaseContract"]

    assert trusted["analysisIds"] == analysis_ids
    assert trusted["chartsRegistered"] is True
    assert reporting_visualization_registered_from_acceptance_contract(normalized) is True
    assert trusted["deterministicFactFiles"] == phase_contract["deterministicFactFiles"]
    assert "analysisPlans" not in trusted
    assert "analysisDatasetIds" not in trusted
    assert "citationRegistry" not in trusted
    assert trusted["citationDatasetIds"] == phase_contract["citationDatasetIds"]


@pytest.mark.parametrize(
    ("registered", "current", "expected_code"),
    [
        (
            ({"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64},),
            {"path": "analysis/evidence.json", "size": 13, "sha256": "b" * 64},
            "report_analysis_evidence_identity_mismatch",
        ),
        (
            (),
            {"path": "analysis/evidence.json", "missing": True},
            "report_analysis_evidence_missing",
        ),
    ],
)
def test_analysis_evidence_rejects_invalid_durable_identity(
    registered: tuple[dict[str, object], ...],
    current: dict[str, object],
    expected_code: str,
) -> None:
    with pytest.raises(ReportingError) as raised:
        ReportWorkspaceTaskToolkit._validate_registered_analysis_evidence(
            durable=reporting_state_with_artifacts(*registered),
            identities=[current],
        )

    assert raised.value.code == expected_code
    assert raised.value.details["paths"] == ["analysis/evidence.json"]


def test_finalize_binding_is_derived_from_durable_analysis_item() -> None:
    durable_item = {
        "analysisId": "analysis_003",
        "datasetIds": ["dataset-income", "dataset-budget"],
        "profileReadReceiptIds": ["receipt-income"],
        "citationIds": ["citation-budget"],
        "chartIds": ["chart-budget"],
        "evidenceFiles": [{"path": "analysis/evidence.json", "size": 2, "sha256": "a" * 64}],
    }
    derived = _derive_durable_analysis_binding(durable_item)

    assert derived["datasetIds"] == ["dataset-income", "dataset-budget"]
    assert derived["profileReadReceiptIds"] == ["receipt-income"]
    assert derived["citationIds"] == ["citation-budget"]
    assert derived["chartIds"] == ["chart-budget"]
    assert derived["evidenceFiles"] == durable_item["evidenceFiles"]


@pytest.mark.anyio
async def test_finalize_submit_semantics_from_projected_catalog() -> None:
    evidence_identity = {"path": "analysis/evidence.json", "size": 12, "sha256": "a" * 64}
    chart_identity = {"path": "analysis/charts/income.png", "size": 1024, "sha256": "b" * 64}
    chart_receipt = {
        "sourcePath": "analysis/charts/income.png",
        "sha256": "b" * 64,
        "inspectionMode": "deterministic",
        "visualReviewStatus": "not_run",
        "inspectorId": "deterministic-raster-inspector-v1",
        "reviewed": True,
        "requiresRevision": False,
        "summary": "已通过确定性图片文件检查；未运行模型视觉审查。",
        "warnings": ("未运行模型视觉审查。",),
    }
    registered_chart = {
        "chartId": "income_trend",
        "sourcePath": "analysis/charts/income.png",
        "size": 1024,
        "sha256": "b" * 64,
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income_total"],
        "currentPeriod": "2026-01",
        "comparisonPeriod": None,
        "comparisonType": "none",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
        "comparability": "strict",
        "visualInspectionReceipt": chart_receipt,
    }
    contract_semantics, contract_metrics = runtime_analysis._finalize_semantic_catalog(
        analysis_plans={
            "analysis_001": {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset-1"],
                "organizationGrain": ["record"],
            }
        },
        fact_bundles={
            "analysis_001": {
                "metrics": [
                    {
                        "datasetId": "dataset-1",
                        "metricCodes": ["income_total"],
                        "formula": "sum(income)",
                        "unit": "元",
                        "periodStart": "2026-01",
                        "periodEnd": "2026-01",
                    }
                ],
                "derivedMetrics": [],
            }
        },
        dataset_ids=("dataset-1",),
    )
    assert contract_semantics == [
        {"datasetId": "dataset-1", "rowGrain": "record", "duplicateResolution": "not_applicable"}
    ]
    assert contract_metrics == [
        {
            "code": "income_total",
            "name": "income_total",
            "definition": "income_total；sum(income)",
            "unit": "元",
            "periodBasis": "2026-01",
        }
    ]
    state: dict[str, Any] = {}
    durable = SimpleNamespace(
        payload={
            "charts": [registered_chart],
            "analysisItems": {
                "analysis_001": {
                    "analysisId": "analysis_001",
                    "summary": "收入事实已冻结。",
                    "datasetIds": ["dataset-1"],
                    "evidenceFiles": [evidence_identity],
                    "citationIds": ["citation-1"],
                    "profileReadReceiptIds": [],
                    "chartIds": ["income_trend"],
                    "warnings": [],
                }
            },
            "profileReadReceipts": [],
        }
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1")),
        service=SimpleNamespace(
            ahash_file=AsyncMock(
                side_effect=lambda _thread_id, path: {
                    "analysis/evidence.json": evidence_identity,
                    "analysis/charts/income.png": chart_identity,
                }[path]
            )
        ),
    )
    toolkit._session_state = lambda _run_context: state
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._ensure_visualization_terminal_settled = AsyncMock()
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._phase_parameters = lambda _scope, _phase: (
        {"analysisOutputPath": "analysis/final.json"},
        {
            "taskKind": "visualization_finalize",
            "analysisIds": ["analysis_001"],
            "datasetIds": ["dataset-1"],
            "citationIds": ["citation-1"],
            "datasetSemantics": contract_semantics,
            "metricDefinitions": contract_metrics,
        },
    )
    toolkit._write_phase_json = AsyncMock(
        return_value={"path": "analysis/final.json", "size": 10, "sha256": "c" * 64}
    )
    toolkit._finish_phase_task = AsyncMock(return_value={"ok": True, "status": "accepted"})

    result = await toolkit.finalize_report_analysis(
        reportBrief={
            "objective": "经营分析",
            "executiveSummary": "收入摘要。",
            "managementQuestions": ["收入表现如何？"],
        },
        datasetSemantics=[
            {"datasetId": "dataset-1", "rowGrain": "month", "duplicateResolution": "resolved"}
        ],
        metricDefinitions=[
            {
                "code": "income_total",
                "name": "被改写的指标",
                "definition": "模型自定义口径。",
                "unit": "元",
                "periodBasis": "2025-01",
            }
        ],
        run_context=RunContext(run_id="run-finalize", session_id="session-finalize"),
    )

    assert result["status"] == "accepted"
    payload = toolkit._write_phase_json.await_args.kwargs["payload"]
    assert payload["evidenceManifest"]["datasetSemantics"] == contract_semantics
    assert payload["evidenceManifest"]["metricDefinitions"] == contract_metrics


@pytest.mark.anyio
async def test_global_zero_charts_fails_at_finalize() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=SimpleNamespace(thread_id="thread-1"))
    )
    toolkit._session_state = lambda _run_context: {}
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._ensure_visualization_terminal_settled = AsyncMock()
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))
    toolkit._phase_parameters = lambda *_args: pytest.fail(
        "零图必须在读取 finalize phase contract 前失败"
    )

    result = await toolkit.finalize_report_analysis(
        reportBrief={
            "objective": "经营分析",
            "executiveSummary": "摘要。",
            "managementQuestions": ["经营表现如何？"],
        },
        datasetSemantics=[],
        metricDefinitions=[],
        run_context=RunContext(run_id="run-finalize", session_id="session-finalize"),
    )

    assert result["ok"] is False
    assert result["code"] == "report_visualization_charts_not_registered"
