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
from agno.run import RunContext
from agno.tools import Function
from daytona.common.errors import DaytonaError

from smart_reporting.reporting.agent import (
    _REPORT_TOOL_FAILURE_STATE_KEY,
    _enforce_reporting_no_progress,
    normalize_reporting_tool_arguments,
)
from smart_reporting.reporting.delivery.acceptance import build_report_phase_acceptance_contract
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
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
    _canonical_analysis_write_call,
    _jmespath_reporting_error,
)
from smart_reporting.reporting.workflow.checkpoint import FileIdentity, ProfileReadReceipt
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_item_completion_conditions,
    _visualization_completion_conditions,
    _visualization_dynamic_budget,
    _visualization_retry_budget,
    _visualization_retry_usage,
)
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.task_execution.acceptance import normalize_acceptance_contract
from smart_reporting.task_execution.execution import WorkspaceTaskToolkit
from smart_reporting.workspace import WorkspaceError, WorkspacePathConflict


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


def test_visualization_retry_budget_is_read_from_trusted_phase_contract() -> None:
    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "visualization",
            "reportRunId": "report-1",
            "visualizationToolCalls": 48,
            "visualizationScriptFailures": 2,
        },
        analysis_output_path="analysis-output.json",
    )

    assert reporting_visualization_budget_from_acceptance_contract(contract) == (48, 2)


def test_historical_visualization_contract_keeps_fixed_budget() -> None:
    contract = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={"taskKind": "visualization", "visualizationToolCalls": 7},
        analysis_output_path="analysis-output.json",
    )

    assert reporting_visualization_budget_contract_from_acceptance_contract(contract) == {
        "visualizationBudgetVersion": 0,
        "visualizationEvidenceReadUnits": 0,
        "visualizationReadLimit": 12,
        "visualizationFactQueryLimit": 4,
        "visualizationAttemptToolLimit": 48,
        "visualizationTotalToolLimit": 64,
        "visualizationReadUnitsUsed": 0,
        "visualizationFactQueriesUsed": 0,
        "visualizationToolCalls": 7,
        "visualizationScriptFailures": 0,
    }


def test_visualization_v1_contract_requires_every_signed_budget_scalar() -> None:
    phase_contract = {
        "taskKind": "visualization",
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
        ([65536] * 25, 16 * 16384, (25, 33, 16, 65, 81)),
        ([65536] * 512, 1, (512, 520, 4, 540, 556)),
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
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
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
            "taskKind": "visualization",
            "reportRunId": "report-1",
            "visualizationRecovery": True,
        },
        analysis_output_path="analysis-output.json",
    )
    ordinary_retry = build_report_phase_acceptance_contract(
        phase="analysis",
        validation_context_file={"path": "analysis-context.json"},
        phase_contract={
            "taskKind": "visualization",
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
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: 48,
                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: 2,
            }
        },
    )

    assert reporting_visualization_budget_from_run_context(context) == (48, 2)


@pytest.mark.anyio
async def test_register_report_charts_commits_one_atomic_durable_batch() -> None:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=3))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=scope))
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization"
    toolkit._phase_parameters = lambda *_args: ({}, {"citationIds": ["citation-1"]})
    toolkit._durable_state = AsyncMock(return_value=SimpleNamespace(payload={"charts": []}))
    identity = {
        "chartId": "income",
        "sourcePath": "analysis/charts/income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
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
            }
        ],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )

    assert result["ok"] is True
    toolkit._apply_durable.assert_awaited_once()
    assert toolkit._apply_durable.await_args.kwargs["name"] == "register_charts"
    assert toolkit._apply_durable.await_args.kwargs["payload"] == {"charts": [identity]}


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
async def test_analysis_python_syntax_error_escapes_for_agent_retry(monkeypatch) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)

    async def invalid_source(*, thread_id: str, path: str) -> bytes:
        assert thread_id == "thread"
        assert path == "analysis/report.py"
        return b'print("OK")\\ No newline at end of file'

    monkeypatch.setattr(toolkit, "_analysis_python_source", invalid_source)

    with pytest.raises(SyntaxError):
        await toolkit._analysis_python_dependency_rejection(
            scope=SimpleNamespace(thread_id="thread"),
            command="python3 analysis/report.py",
            workdir=None,
        )


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
            "taskKind": "visualization",
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
    for expected_count in range(2, 5):
        guided = _enforce_reporting_no_progress(context, "terminal", failure)
        assert guided["details"]["sameFailureCount"] == expected_count
        assert guided["requiredActions"]
    assert context.session_state[_REPORT_TOOL_FAILURE_STATE_KEY]["phaseFailureCount"] == 4

    success = {"ok": True, "status": "accepted"}
    assert _enforce_reporting_no_progress(context, "write_analysis_files", success) == success
    assert _REPORT_TOOL_FAILURE_STATE_KEY not in context.session_state

    assert _enforce_reporting_no_progress(context, "terminal", failure) == failure
    assert context.session_state[_REPORT_TOOL_FAILURE_STATE_KEY]["phaseFailureCount"] == 1


def test_repeated_failure_without_progress_stops_after_same_failure_limit() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    failure = {"ok": False, "code": "report_tool_arguments_invalid"}

    results = [_enforce_reporting_no_progress(context, "terminal", failure) for _ in range(3)]

    assert results[0] == failure
    assert results[1]["details"]["sameFailureCount"] == 2
    assert "只修改服务端 code/details" in results[1]["requiredActions"][-1]
    assert results[-1]["code"] == "tool_no_progress"
    assert results[-1]["retryable"] is False
    assert results[-1]["details"]["sameFailureCount"] == 3


def test_nonretryable_reporting_tool_result_stops_function_run() -> None:
    function_call = SimpleNamespace(
        function=SimpleNamespace(stop_after_tool_call=False),
        result={"ok": False, "code": "tool_no_progress", "retryable": False},
    )

    _stop_after_nonretryable_tool_call(function_call)

    assert function_call.function.stop_after_tool_call is True


def test_phase_failure_limit_stops_distinct_failures_without_progress() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    results = [
        _enforce_reporting_no_progress(
            context,
            "write_analysis_files",
            {"ok": False, "code": "report_analysis_write_intent_invalid"},
            {"path": f"analysis/{index}.py"},
        )
        for index in range(8)
    ]

    assert results[-1]["code"] == "tool_no_progress"
    assert results[-1]["retryable"] is False
    assert results[-1]["details"]["phaseFailureCount"] == 8


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


def test_analysis_facts_tool_distinguishes_projection_from_file_schema() -> None:
    toolkit = ReportWorkspaceTaskToolkit(
        fake_workspace_service(None),
        AsyncMock(),
        state_repository=AsyncMock(),
    )

    description = toolkit.async_functions["query_analysis_facts"].description

    assert "analyses[].facts 只存在于本工具聚合回执" in description
    assert "单个文件根节点就是对应 analysis 的 facts" in description


_WORKER_TOOL_SCHEMA_NAMES = (
    "finish_task",
    "read_profile_pointer",
    "query_profile",
    "query_analysis_context",
    "query_analysis_facts",
    "write_analysis_files",
    "complete_analysis_item",
    "finalize_report_analysis",
    "register_report_charts",
    "render_report_section",
)
_WORKER_TOOL_SCHEMA_FINGERPRINTS = {
    "finish_task": "8f2c3da628346e18a879213d6b2201da58e68eae5dda3e9477c6d2875aeb878e",
    "read_profile_pointer": "a6287140ea3b87551c1126cbe2d4e0df034223e59937ac33276e30e627785018",
    "query_profile": "442fe01a0e251791e117648a28d4c25e2041307ea7b26aae490ef7f3dadf87f6",
    "query_analysis_context": "fb2d26cd963d66da970742c6a543fad0d492669f895fca01e536f123cc70cd0e",
    "query_analysis_facts": "b1b463cc581dc8e66a40dc86570bfca698dba8562cefe66ca6987d8552cbdc68",
    "write_analysis_files": "30f1cf3bd9ab5077d66c0373858dc6b1b8e889927d7d0cd41528ada4ef487125",
    "complete_analysis_item": "cb93f40d4226ced6a1a2ac96d2b26ffe51e0e1fb3eba1e25d05e73d2496f2073",
    "finalize_report_analysis": "198d0662d1589b8961b784c5a11b138da322e0577320251d47adaaa37b9be7ec",
    "register_report_charts": "c512a28f7b2bc55752a42652f53688450a5252f6a51d06f21e106573cf74e841",
    "render_report_section": "59f1b6252af25b741cd13d455d86d0d72c9c67cd958816d1451dd681224ec452",
}


def _worker_tool_schema_snapshot(toolkit: ReportWorkspaceTaskToolkit) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "name": toolkit.async_functions[name].name,
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
            "visualization",
            {"query_analysis_facts", "register_report_charts", "finalize_report_analysis"},
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
            state={},
            run_context=None,
        )

    assert raised.value.code == "report_draft_protocol_injection"
    assert "chartIds" in raised.value.message
    toolkit._write_phase_json.assert_not_awaited()


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
        "taskKind": "visualization",
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
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization",
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
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization",
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
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization",
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
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
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
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
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
async def test_visualization_read_rejects_untrusted_and_changed_evidence() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
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
    toolkit.kernel = SimpleNamespace(
        service=SimpleNamespace(
            abatch_hash_files=AsyncMock(
                return_value=[{"path": "evidence/one.json", "size": 9, "sha256": "b" * 64}]
            )
        )
    )
    scope = SimpleNamespace(thread_id="thread-1")

    forbidden = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="evidence/other.json"
    )
    changed = await toolkit._visualization_evidence_read_rejection(
        scope=scope, path="evidence/one.json"
    )

    assert forbidden["code"] == "report_visualization_evidence_path_forbidden"
    assert changed["code"] == "report_visualization_evidence_changed"


@pytest.mark.anyio
async def test_visualization_read_allows_only_latest_committed_signed_script() -> None:
    toolkit: Any = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._active_reporting_phase = lambda _scope: "analysis"
    toolkit._active_reporting_task_kind = lambda _scope: "visualization"
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {
            "taskKind": "visualization",
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
        "taskKind": "visualization",
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
