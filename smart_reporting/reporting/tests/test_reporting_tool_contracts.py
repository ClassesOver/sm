from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jmespath
import pytest
from agno.run import RunContext
from agno.tools import Function
from daytona.common.errors import DaytonaError

from smart_reporting.reporting.agent import (
    _REPORT_TOOL_FAILURE_STATE_KEY,
    _enforce_reporting_no_progress,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
)
from smart_reporting.reporting.tests.workspace_fakes import service as fake_workspace_service
from smart_reporting.reporting.tools import (
    ANALYSIS_WRITE_PUBLIC_TOOL_NAMES,
    ANALYSIS_WRITE_TOOL_NAMES,
    MAX_ANALYSIS_WRITE_INTENT_BYTES,
    ReportWorkspaceTaskToolkit,
    _analysis_context_projection,
    _analysis_write_operation_arguments,
    _analysis_write_parameters,
    _canonical_analysis_write_call,
    _derive_durable_analysis_binding,
    _jmespath_reporting_error,
    _reset_stop_after_tool_call,
    _stop_after_accepted_tool_call,
    build_report_worker_tools,
)
from smart_reporting.reporting.workflow.checkpoint import ProfileReadReceipt
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.workspace import WorkspaceError


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


def test_write_analysis_files_drops_only_inactive_neutral_fields() -> None:
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


def test_write_analysis_files_keeps_inactive_nonempty_fields_for_strict_rejection() -> None:
    arguments = _analysis_write_operation_arguments(
        "replace_text",
        {
            "path": "analysis/report.py",
            "old_string": "before",
            "new_string": "after",
            "patch": "--- a/report.py\n+++ b/report.py\n",
        },
    )
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.async_functions = write_functions()

    with pytest.raises(ReportingError) as raised:
        toolkit._validate_analysis_write_arguments("replace_text", arguments)

    assert raised.value.code == "report_analysis_write_intent_invalid"
    assert raised.value.details["validator"] == "additionalProperties"


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


def test_repeated_failure_without_progress_only_adds_progressive_guidance() -> None:
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    failure = {"ok": False, "code": "report_tool_arguments_invalid"}

    results = [_enforce_reporting_no_progress(context, "terminal", failure) for _ in range(6)]

    assert results[0] == failure
    assert results[1]["details"]["sameFailureCount"] == 2
    assert "只修改服务端 code/details" in results[1]["requiredActions"][-1]
    assert results[-1]["details"]["sameFailureCount"] == 6
    assert "缩小查询" in results[-1]["requiredActions"][-1]


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
async def test_complete_analysis_item_rejects_out_of_order_submission() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(scope=AsyncMock(return_value=object()))
    toolkit._phase_parameters = lambda _scope, _phase: (
        {},
        {"taskKind": "analysis_item", "analysisIds": ["analysis_001", "analysis_002"]},
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

    assert result["code"] == "report_analysis_item_out_of_order"
    assert result["details"] == {"currentAnalysisId": "analysis_002"}
    assert "details.currentAnalysisId" in result["requiredActions"][0]


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
                "currentAnalysisId": "analysis_001",
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
            "analysisIds": ["analysis_001", "analysis_002"],
            "analysisDatasetIds": {"analysis_001": ["dataset-1"]},
        },
    )
    toolkit._durable_state = AsyncMock(return_value=durable)
    toolkit._ensure_registered_analysis_evidence = AsyncMock(return_value=durable)
    toolkit._apply_durable = AsyncMock(return_value=advanced)

    result = await toolkit.complete_analysis_item(
        analysisId="analysis_001",
        summary="收入事实已复核",
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
