import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent as AgnoAgent
from agno.metrics import RunMetrics
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.tools.function import Function
from openai.types.responses import ResponseUsage

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.metrics import (
    bounded_failure_diagnostics,
    bounded_request_params_snapshot,
    build_coding_metric_sample,
    group_coding_metrics,
    measure_input_components,
    percentile,
    planner_coding_reasoning_tokens,
    summarize_coding_metrics,
)
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _function_response,
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.execution import (
    ReportingTaskCoordinator,
    _TaskModelMetricsSettlement,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
    _metric_failure_code,
)


@pytest.mark.anyio
@pytest.mark.parametrize("with_usage", [True, False])
@pytest.mark.parametrize("declared_edit", [True, False])
async def test_rejected_provider_call_keeps_usage_and_safe_identity(
    monkeypatch, with_usage, declared_edit,
):
    response = _function_response(1, "edit_script", {"patch": "PRIVATE_SOURCE"})
    if with_usage:
        response.usage = ResponseUsage(
            input_tokens=100, output_tokens=70, total_tokens=170,
            input_tokens_details={"cached_tokens": 40, "cache_write_tokens": 0},
            output_tokens_details={"reasoning_tokens": 60},
        )
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="edit_script" if declared_edit else "run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    monkeypatch.setattr(model, "get_async_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=response)),
    ))
    if declared_edit:
        # 任务集内 FREEFORM 工具以 function 形态返回：不执行、补未执行回执，
        # 不是协议异常；usage 照常结算，私密输入不进指标。
        await model.ainvoke([], assistant_message=Message(role="assistant"), tools=tools)
        metric = model.code_run_request_metrics()[0]
        assert metric["status"] == "completed"
        assert metric["providerRequestId"] == "resp-1"
        assert model._code_budget.wire_shape_rejections == 1
        assert model._code_budget.protocol_violations == 0
        assert "PRIVATE_SOURCE" not in json.dumps(model.code_run_request_metrics())
        return
    with pytest.raises(ReportingError) as caught:
        await model.ainvoke([], assistant_message=Message(role="assistant"), tools=tools)

    assert caught.value.code == "report_code_custom_tool_protocol_error"
    metric = model.code_run_request_metrics()[0]
    assert metric["status"] == "failed"
    assert metric["providerRequestId"] == "resp-1"
    assert metric["reasoningTokens"] == (60 if with_usage else "unknown")
    assert metric["inputTokens"] == (100 if with_usage else "unknown")
    assert metric["outputTokens"] == (70 if with_usage else "unknown")
    assert metric["cacheReadTokens"] == (40 if with_usage else "unknown")
    assert metric["visibleOutputTokens"] == (10 if with_usage else "unknown")
    assert caught.value.details == {
        "retryable": False,
        "toolName": "edit_script", "receivedType": "function",
        "expectedType": "undeclared",
        "declaredTools": {"run_script": "function"},
        "itemId": "item-1", "callId": "call-1",
    }
    sample = build_coding_metric_sample(duration_ms=1, request_metrics=[metric])
    assert sample["modelRequestMetrics"][0]["reasoningTokens"] == (60 if with_usage else "unknown")
    assert "PRIVATE_SOURCE" not in json.dumps([sample, caught.value.details])


def test_coding_metrics_keep_unknown_separate_from_zero_and_report_tail_latency():
    assert percentile([], 50) == "unknown"
    summary = summarize_coding_metrics([
        {
            "rawProtocolCorrect": True,
            "firstPatchApplied": True,
            "firstRepairSuccess": True,
            "criticalVisualDefect": False,
            "durationMs": 100,
            "reasoningTokens": 10,
            "firstWriteRequestDurationMs": 80,
            "firstWriteReasoningTokens": 8,
        },
        {
            "rawProtocolCorrect": False,
            "firstPatchApplied": False,
            "firstRepairSuccess": True,
            "criticalVisualDefect": True,
            "durationMs": 900,
            "reasoningTokens": 9000,
            "firstWriteRequestDurationMs": 700,
            "firstWriteReasoningTokens": 7000,
        },
    ])
    assert summary["sampleCount"] == 2
    assert summary["rawProtocolCorrectRate"] == 0.5
    assert summary["durationMs"] == {"p50": 100.0, "p95": 900.0}
    assert summary["reasoningTokens"] == {"p50": 10.0, "p95": 9000.0}
    assert summary["firstWriteRequestDurationMs"] == {"p50": 80.0, "p95": 700.0}
    assert summary["firstWriteReasoningTokens"] == {"p50": 8.0, "p95": 7000.0}
    assert summary["firstRunFailureCodes"] == {}


@pytest.mark.parametrize("failed_tokens,total", [(60, 80), (None, "unknown")])
def test_failed_task_usage_includes_rejected_response_or_is_unknown(failed_tokens, total):
    sample = build_coding_metric_sample(
        duration_ms=1, request_count=2, reasoning_tokens=20, model_cost=0.01,
        request_metrics=[
            {"requestIndex": 1, "status": "completed", "reasoningTokens": 20},
            {"requestIndex": 2, "status": "failed", "reasoningTokens": failed_tokens},
        ],
    )
    assert sample["reasoningTokens"] == total
    assert sample["modelCost"] == "unknown"


def test_coding_metrics_summarize_first_run_failure_codes_without_full_diagnostics():
    summary = summarize_coding_metrics([
        {"firstRunFailureCode": "report_code_execution_failed"},
        {"firstRunFailureCode": "report_code_execution_failed"},
        {"firstRunFailureCode": "report_code_script_edit_conflict"},
        {"firstRunFailureCode": "unknown"},
    ])

    assert summary["firstRunFailureCodes"] == {
        "report_code_execution_failed": 2,
        "report_code_script_edit_conflict": 1,
    }


@pytest.mark.parametrize("code,expected", [
    (None, "unknown"),
    ("", "unknown"),
    ("report_code_input_wrapped", "report_code_input_wrapped"),
    ("x" * 200, "x" * 128),
])
def test_first_script_failure_code_is_bounded(code, expected):
    sample = build_coding_metric_sample(duration_ms=1, first_script_failure_code=code)
    assert sample["firstScriptFailureCode"] == expected


def test_input_component_metrics_record_only_bytes_and_stable_hashes():
    metrics = measure_input_components(
        {
            "commonInstructions": ["rule-a", "rule-b"],
            "task": {"task_kind": "analysis", "task_id": "analysis-001"},
            "diagnostic": None,
        }
    )

    assert set(metrics) == {"commonInstructions", "task", "diagnostic"}
    assert metrics["commonInstructions"]["bytes"] > 0
    assert len(metrics["commonInstructions"]["sha256"]) == 64
    assert metrics["diagnostic"]["bytes"] == 4
    assert "rule-a" not in str(metrics)
    assert measure_input_components({"task": {"a": 1, "b": 2}})["task"] == (
        measure_input_components({"task": {"b": 2, "a": 1}})["task"]
    )
    assert measure_input_components({"task": {"value": 1}})["task"]["sha256"] != (
        measure_input_components({"task": {"value": 2}})["task"]["sha256"]
    )


def test_request_params_snapshot_preserves_only_bounded_request_fingerprints():
    sha = "a" * 64

    snapshot = bounded_request_params_snapshot(
        {
            "systemPrefixSha256": sha,
            "systemPrefixBytes": 123,
            "toolDeclarationsSha256": sha,
            "toolDeclarationsBytes": 456,
            "schemaSha256": sha,
            "schemaBytes": 789,
            "systemPrefix": "secret prompt",
            "tools": [{"description": "secret tool"}],
            "schema": {"secret": True},
        }
    )

    assert snapshot is not None
    assert snapshot["systemPrefixSha256"] == sha
    assert snapshot["systemPrefixBytes"] == 123
    assert snapshot["toolDeclarationsSha256"] == sha
    assert snapshot["toolDeclarationsBytes"] == 456
    assert snapshot["schemaSha256"] == sha
    assert snapshot["schemaBytes"] == 789
    assert "secret" not in str(snapshot)


def test_coding_metrics_mark_missing_and_explicit_unknown_observations_unknown():
    summary = summarize_coding_metrics([
        {"durationMs": 10, "firstPatchApplied": "unknown"}
    ])
    assert summary["firstPatchAppliedRate"] == "unknown"
    assert summary["reasoningTokens"] == {"p50": "unknown", "p95": "unknown"}
    assert "firstPatchApplied" in summary["unknownFields"]
    assert "reasoningTokens" in summary["unknownFields"]


def test_coding_metrics_summarize_execution_spans_by_phase():
    summary = summarize_coding_metrics([
        {
            "durationMs": 100,
            "executionSpans": {
                "bootstrap": [10, 20],
                "monitor": [3],
                "cell": [40],
                "script": [50],
                "shutdown": [4],
            },
        }
    ])

    assert summary["executionSpans"] == {
        "bootstrap": {"p50": 10.0, "p95": 20.0},
        "monitor": {"p50": 3.0, "p95": 3.0},
        "cell": {"p50": 40.0, "p95": 40.0},
        "script": {"p50": 50.0, "p95": 50.0},
        "shutdown": {"p50": 4.0, "p95": 4.0},
    }
    assert "executionSpans" not in summary["unknownFields"]

    partial = summarize_coding_metrics([{
        "durationMs": 1,
        "executionSpans": {"bootstrap": [1]},
    }])
    assert "executionSpans" in partial["unknownFields"]


def test_coding_metric_sample_keeps_delivery_evidence_and_unknowns_separate():
    sample = build_coding_metric_sample(
        duration_ms=321,
        task_kind="visualization",
        model="coding-model",
        provider="provider",
        reasoning_effort="high",
        request_count=3,
        input_tokens=120,
        output_tokens=50,
        reasoning_tokens=44,
        cache_read_tokens=20,
        model_cost=0.125,
        tool_counts={"write_script": 1, "edit_script": 2, "run_script": 3},
        completed_tool_calls=6,
        visual_review_duration_ms=77,
        first_patch_applied=False,
        critical_visual_defect=True,
        failure_code="report_code_generation_no_submission",
    )

    assert sample == {
        "durationMs": 321,
        "taskId": "unknown",
        "taskKind": "visualization",
        "model": "coding-model",
        "provider": "provider",
        "reasoningEffort": "high",
        "modelRequests": 3,
        "inputTokens": 120,
        "outputTokens": 50,
        "reasoningTokens": 44,
        "cacheReadTokens": 20,
        "modelCost": 0.125,
        "toolCalls": 6,
        "toolCounts": {"write_script": 1, "edit_script": 2, "run_script": 3},
        "visualReviewDurationMs": 77,
            "modelRequestMetrics": [],
            "executionSpans": "unknown",
            "inputComponents": {},
        "firstWriteRequestIndex": "unknown",
        "firstWriteRequestDurationMs": "unknown",
        "firstWriteReasoningTokens": "unknown",
        "firstPatchApplied": False,
        "criticalVisualDefect": True,
        "failureCode": "report_code_generation_no_submission",
        "rawProtocolCorrect": "unknown",
        "envelopeNormalizedInputs": "unknown",
        "wireShapeRejections": "unknown",
            "firstScriptSuccess": "unknown",
            "firstScriptFailureCode": "unknown",
            "firstRunSuccess": "unknown",
        "firstRunFailureCode": "unknown",
        "firstRunFailure": "unknown",
        "firstRepairSuccess": "unknown",
    }


def test_coding_metric_sample_normalizes_execution_spans_without_inventing_values():
    sample = build_coding_metric_sample(
        duration_ms=1,
        execution_spans={
            "bootstrap": [12, -1, 4],
            "monitor": [8],
            "cell": [21.5],
            "script": None,
            "shutdown": [0],
        },
    )

    assert sample["executionSpans"] == {
        "bootstrap": [12, 4],
        "monitor": [8],
        "cell": [21.5],
        "script": "unknown",
        "shutdown": [0],
    }


def test_coding_metric_sample_identifies_first_write_request_without_hiding_unknowns():
    sample = build_coding_metric_sample(
        duration_ms=900,
        task_id="section-001",
        task_kind="visualization",
        request_metrics=[
            {
                "requestIndex": 1,
                "providerRequestId": "resp-1",
                "durationMs": 573000,
                "inputTokens": 14284,
                "outputTokens": 49222,
                "reasoningTokens": 41267,
                "visibleOutputTokens": 7955,
                "cacheReadTokens": 1024,
                "timeToFirstTokenSeconds": "unknown",
                "toolNames": ["write_script"],
                "requestParams": {
                    "model": "coding-model",
                    "reasoningEffort": "medium",
                    "reasoningSummary": "auto",
                    "enableThinking": True,
                    "enableThinkingLocation": "top_level",
                    "maxOutputTokens": 8192,
                    "parallelToolCalls": True,
                    "toolChoice": "auto",
                    "extraBodyKeys": ["enable_thinking"],
                },
                "status": "completed",
            },
            {
                "requestIndex": 2,
                "durationMs": 8000,
                "inputTokens": "unknown",
                "outputTokens": "unknown",
                "reasoningTokens": "unknown",
                "visibleOutputTokens": "unknown",
                "cacheReadTokens": "unknown",
                "timeToFirstTokenSeconds": "unknown",
                "toolNames": ["run_script"],
                "status": "completed",
            },
        ],
    )

    assert sample["taskId"] == "section-001"
    assert sample["firstWriteRequestIndex"] == 1
    assert sample["firstWriteRequestDurationMs"] == 573000
    assert sample["modelRequestMetrics"][0]["providerRequestId"] == "resp-1"
    assert sample["modelRequestMetrics"][0]["requestParams"]["parallelToolCalls"] is True
    assert sample["modelRequestMetrics"][0]["requestParams"]["enableThinkingLocation"] == "top_level"
    assert sample["firstWriteReasoningTokens"] == 41267
    assert sample["modelRequestMetrics"][1]["reasoningTokens"] == "unknown"


def test_coding_metric_sample_preserves_started_request_after_cancellation():
    sample = build_coding_metric_sample(
        duration_ms=900_000,
        task_kind="visualization",
        request_metrics=[
            {
                "requestIndex": 1,
                "toolNames": [],
                "toolCalls": [],
                "toolCallCount": 0,
                "status": "started",
            }
        ],
    )

    assert sample["modelRequestMetrics"][0]["status"] == "started"


def test_response_tool_calls_keep_provider_order_and_duplicate_names():
    response = SimpleNamespace(
        tool_calls=[
            {
                "id": "item-1",
                "call_id": "call-1",
                "type": "function",
                "function": {"name": "run", "arguments": "secret-1"},
            },
            {
                "id": "item-2",
                "call_id": "call-2",
                "type": "function",
                "function": {"name": "run", "arguments": "secret-2"},
            },
            {
                "id": "item-3",
                "call_id": "call-3",
                "type": "custom",
                "name": "write_script",
                "provider_data": {"raw_input": "secret-source"},
            },
        ]
    )

    assert ReportingCodeOpenAIResponses._response_tool_calls(response) == [
        {"id": "call-1", "name": "run"},
        {"id": "call-2", "name": "run"},
        {"id": "call-3", "name": "write_script"},
    ]
    assert ReportingCodeOpenAIResponses._response_tool_names(response) == [
        "run",
        "write_script",
    ]


def test_coding_metric_sample_replays_bounded_ordered_tool_call_identities_only():
    sample = build_coding_metric_sample(
        duration_ms=1,
        request_metrics=[
            {
                "requestIndex": 1,
                "providerRequestId": "resp-1",
                "durationMs": 2,
                "toolNames": ["run", "write_script"],
                "toolCalls": [
                    {
                        "id": "call-1",
                        "name": "run",
                        "arguments": "secret-arguments",
                        "result": "secret-result",
                    },
                    {"id": "call-2", "name": "run"},
                    {
                        "id": "call-3",
                        "name": "write_script",
                        "source": "secret-source",
                    },
                ],
                "toolCallCount": 3,
                "status": "completed",
                "firstToolFailure": {
                    "toolName": "write_script",
                    "code": "report_python_source_path_invalid",
                    "details": {"source": "secret-source"},
                },
            }
        ],
    )

    request = sample["modelRequestMetrics"][0]
    assert request["toolCalls"] == [
        {"id": "call-1", "name": "run"},
        {"id": "call-2", "name": "run"},
        {"id": "call-3", "name": "write_script"},
    ]
    assert request["toolCallCount"] == 3
    assert request["toolNames"] == ["run", "write_script"]
    assert "secret" not in str(request)
    assert request["firstToolFailure"] == {
        "toolName": "write_script", "code": "report_python_source_path_invalid",
    }


def test_coding_metric_sample_keeps_bounded_first_tool_failure_diagnostics():
    sample = build_coding_metric_sample(
        duration_ms=1,
        request_metrics=[
            {
                "requestIndex": 1,
                "providerRequestId": "resp-1",
                "durationMs": 2,
                "toolNames": ["run_script"],
                "toolCalls": [{"id": "call-1", "name": "run_script"}],
                "toolCallCount": 1,
                "status": "completed",
                "firstToolFailure": {
                    "toolName": "run_script",
                    "code": "report_code_declared_output_missing",
                    "diagnostics": {
                        "path": "analysis/out.json",
                        "missingPaths": [f"analysis/out-{index}.json" for index in range(30)],
                        "presentPaths": [],
                        "unsignedPaths": [f"data/unsigned-{index}.csv" for index in range(25)],
                        "forbiddenPathOperations": ["os.getcwd"],
                        "stdoutTail": "s" * 5000,
                        "errorType": "E" * 300,
                        "exitCode": 0,
                        "declaredOutputCount": 17,
                        "detectedOutputWrites": [f"charts/chart-{index:02d}.png" for index in range(30)],
                        "source": "secret-source",
                    },
                    "details": {"source": "secret-source"},
                },
            }
        ],
    )

    failure = sample["modelRequestMetrics"][0]["firstToolFailure"]
    assert failure["toolName"] == "run_script"
    assert failure["code"] == "report_code_declared_output_missing"
    diagnostics = failure["diagnostics"]
    assert diagnostics["path"] == "analysis/out.json"
    assert len(diagnostics["missingPaths"]) == 20
    assert diagnostics["presentPaths"] == []
    assert len(diagnostics["unsignedPaths"]) == 20
    assert diagnostics["forbiddenPathOperations"] == ["os.getcwd"]
    assert diagnostics["stdoutTail"] == "s" * 1000
    assert diagnostics["errorType"] == "E" * 256
    assert diagnostics["exitCode"] == 0
    assert diagnostics["declaredOutputCount"] == 17
    assert len(diagnostics["detectedOutputWrites"]) == 20
    assert "secret" not in str(failure)


def test_coding_metric_sample_keeps_edit_failure_reason_and_block_identity():
    """candidate-15 观测缺口：edit_script invalid 的 reason/blockIndex/字节数身份必须透出。"""
    sample = build_coding_metric_sample(
        duration_ms=1,
        request_metrics=[
            {
                "requestIndex": 1,
                "status": "completed",
                "firstToolFailure": {
                    "toolName": "edit_script",
                    "code": "report_code_script_edit_invalid",
                    "diagnostics": {
                        "reason": "no_valid_blocks",
                        "blockIndex": 2,
                        "actualBytes": 131234,
                        "limitBytes": 65536,
                        "source": "secret-patch-text",
                    },
                },
            }
        ],
    )
    diagnostics = sample["modelRequestMetrics"][0]["firstToolFailure"]["diagnostics"]
    assert diagnostics["reason"] == "no_valid_blocks"
    assert diagnostics["blockIndex"] == 2
    assert diagnostics["actualBytes"] == 131234
    assert diagnostics["limitBytes"] == 65536
    assert "secret" not in str(diagnostics)


def test_coding_metric_sample_persists_bounded_edit_context_diagnostics():
    """candidate-16 观测缺口：edit_script 失败回执的有界源码上下文必须能持久化。"""
    sample = build_coding_metric_sample(
        duration_ms=1,
        request_metrics=[
            {
                "requestIndex": 1,
                "status": "completed",
                "firstToolFailure": {
                    "toolName": "edit_script",
                    "code": "report_code_script_edit_not_found",
                    "diagnostics": {
                        "reason": "search_text_not_found",
                        "sourceExcerpt": "x" * 2000 + "TAIL",
                        "sourceStartLine": 3,
                        "sourceEndLine": 30,
                        "errorLine": 12,
                        "readRange": {
                            "path": "analysis/a.py",
                            "startLine": 3,
                            "endLine": 30,
                            "source": "secret-full-source",
                        },
                        "allowedEditRegion": {
                            "path": "analysis/a.py",
                            "startLine": 1,
                            "endLine": 40,
                            "source": "secret-full-source",
                        },
                        "forbiddenEditRegions": [{"path": "analysis/a.py"}],
                        "source": "secret-full-source",
                    },
                },
            }
        ],
    )

    diagnostics = sample["modelRequestMetrics"][0]["firstToolFailure"]["diagnostics"]
    assert diagnostics["sourceExcerpt"] == "x" * 1796 + "TAIL"
    assert len(diagnostics["sourceExcerpt"].encode("utf-8")) == 1800
    assert diagnostics["readRange"] == {"path": "analysis/a.py", "startLine": 3, "endLine": 30}
    assert diagnostics["allowedEditRegion"] == {
        "path": "analysis/a.py", "startLine": 1, "endLine": 40,
    }
    assert "sourceStartLine" not in diagnostics
    assert "forbiddenEditRegions" not in diagnostics
    assert "secret" not in str(diagnostics)


def test_bounded_failure_diagnostics_trims_source_excerpt_tail_to_byte_limit():
    # 1801 字节输入的尾部 1800 字节从首个多字节字符中间开始，
    # 残缺字节按 UTF-8 解码丢弃，结果不超过 1800 字节。
    diagnostics = bounded_failure_diagnostics({"sourceExcerpt": "中" * 600 + "a"})

    assert diagnostics == {"sourceExcerpt": "中" * 599 + "a"}
    assert len(diagnostics["sourceExcerpt"].encode("utf-8")) == 1798


def test_bounded_failure_diagnostics_keeps_excerpt_within_limit_unchanged():
    excerpt = "中" * 600

    assert bounded_failure_diagnostics({"sourceExcerpt": excerpt}) == {
        "sourceExcerpt": excerpt
    }


@pytest.mark.parametrize("excerpt", [None, 123, "", ["line"], {"code": 1}])
def test_bounded_failure_diagnostics_drops_malformed_excerpt(excerpt):
    assert bounded_failure_diagnostics({"sourceExcerpt": excerpt}) == {}


@pytest.mark.parametrize("region", [
    "analysis/a.py",
    None,
    42,
    ["analysis/a.py", 1, 5],
    {},
    {"path": "analysis/a.py"},
    {"path": "analysis/a.py", "startLine": 5},
    {"path": "analysis/a.py", "startLine": 10, "endLine": 5},
    {"path": "analysis/a.py", "startLine": 0, "endLine": 5},
    {"path": "analysis/a.py", "startLine": True, "endLine": 5},
    {"path": "analysis/a.py", "startLine": 1.0, "endLine": 5},
    {"path": "analysis/a.py", "startLine": "1", "endLine": 5},
    {"path": "", "startLine": 1, "endLine": 5},
    {"path": 42, "startLine": 1, "endLine": 5},
    {"startLine": 1, "endLine": 5},
])
def test_bounded_failure_diagnostics_drops_malformed_regions(region):
    for key in ("readRange", "allowedEditRegion"):
        assert bounded_failure_diagnostics({key: region}) == {}


def test_bounded_failure_diagnostics_projects_only_safe_region_fields():
    diagnostics = bounded_failure_diagnostics({
        "readRange": {
            "path": "a" * 300,
            "startLine": 2,
            "endLine": 9,
            "source": "secret-full-source",
            "sha256": "b" * 64,
            "extra": {"nested": "secret"},
        },
        "allowedEditRegion": {"path": "charts/a.png", "startLine": 1, "endLine": 12},
    })

    assert diagnostics == {
        "readRange": {"path": "a" * 256, "startLine": 2, "endLine": 9},
        "allowedEditRegion": {"path": "charts/a.png", "startLine": 1, "endLine": 12},
    }


@pytest.mark.anyio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_path_rejection_and_raw_protocol_are_independent(workspace, wrapped):  # noqa: F811
    from smart_reporting.reporting.agent import create_reporting_code_agent_factory
    from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import (
        _ResponsesClient,
    )
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
        SOURCE,
        ToolkitRuntime,
        _batch_response,
        _custom_response,
    )

    source = '# Python\nimport os\nprint(os.getcwd())\n'
    if wrapped:
        source = json.dumps({"data": source})
    client = _ResponsesClient([
        _batch_response(
            _custom_response("write_script", source, 1),
            _function_response(2, "run_script", {}),
        ),
        _batch_response(
            _custom_response("write_script", "# Python\n" + SOURCE, 3),
            _function_response(4, "run_script", {}),
            _function_response(5, "submit_script", {}),
        ),
    ])
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name="metric-failure-test",
    )

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent

    samples = []
    await ReportingCodeGenerationRunner(
        make_agent, ToolkitRuntime(), ReportingLspProcessManager(),
        coding_metrics_recorder=samples.append,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context("task-1"))
    sample = samples[0]
    # 2026-09-23 口径变更：单层 data 信封按兼容路径解封执行，不记协议违规，
    # 单列 envelopeNormalizedInputs；rawProtocolCorrect 只统计真违规。
    assert sample["rawProtocolCorrect"] is True
    assert sample["envelopeNormalizedInputs"] == (1 if wrapped else 0)
    assert sample["firstScriptFailureCode"] == "report_python_source_path_invalid"
    # 合并 origin/code：预检失败新增 violations 逐项诊断（远端"增强诊断"），
    # 断言收敛为关键字段 + violations 存在性。
    first_failure = sample["modelRequestMetrics"][0]["firstToolFailure"]
    assert first_failure["toolName"] == "write_script"
    assert first_failure["code"] == "report_python_source_path_invalid"
    diagnostics = first_failure["diagnostics"]
    assert diagnostics["path"] == "analysis/a.py"
    assert diagnostics["unsignedPaths"] == []
    assert diagnostics["forbiddenPathOperations"] == ["os.getcwd"]
    assert diagnostics["violations"]
    assert diagnostics["violations"][0]["code"] == "report_python_source_path_invalid"
    assert "firstToolFailure" not in sample["modelRequestMetrics"][1]


@pytest.mark.anyio
async def test_declared_output_missing_records_bounded_diagnostics(workspace):  # noqa: F811
    from smart_reporting.reporting.agent import create_reporting_code_agent_factory
    from smart_reporting.reporting.code_mode import ScriptProcessResult
    from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import (
        _ResponsesClient,
    )
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
        SOURCE,
        _batch_response,
        _custom_response,
    )

    class MissingThenOkRuntime:
        def __init__(self) -> None:
            self.runs = 0

        async def execute(self, _session_id, _workspace, _code, **_kwargs):
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            self.runs += 1
            if self.runs > 1:
                await received.awrite_text("task-1", "analysis/out.json", "{}")
            return ScriptProcessResult(
                SimpleNamespace(status="ok", stdout="done\n", stderr="", traceback=None), 0
            )

        async def shutdown(self, _session_id):
            return None

    client = _ResponsesClient([
        _batch_response(
            _custom_response("write_script", "# Python\n" + SOURCE, 1),
            _function_response(2, "run_script", {}),
        ),
        _batch_response(
            _function_response(3, "run_script", {}),
            _function_response(4, "submit_script", {}),
        ),
        # run_script 成功前 submit_script 不在声明表内，同批调用会被阶段门禁拒绝，
        # 需要第三轮按交付状态单独提交。
        _batch_response(
            _function_response(5, "submit_script", {}),
        ),
    ])
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name="missing-output-test",
    )

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent

    samples = []
    await ReportingCodeGenerationRunner(
        make_agent, MissingThenOkRuntime(), ReportingLspProcessManager(),
        coding_metrics_recorder=samples.append,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context("task-1"))
    sample = samples[0]
    failure = sample["modelRequestMetrics"][0]["firstToolFailure"]
    assert failure["toolName"] == "run_script"
    assert failure["code"] == "report_code_declared_output_missing"
    assert failure["diagnostics"] == {
        "path": "analysis/out.json",
        "errorLine": 4,
        "exitCode": 0,
        "missingPaths": ["analysis/out.json"],
        "presentPaths": [],
        "stdoutTail": "done\n",
        "allDeclaredOutputsMissing": True,
        "sourceExcerpt": '# Python\nfrom pathlib import Path\n\nPath("analysis/out.json").write_text("{}")\n',
        "allowedEditRegion": {"path": "analysis/a.py", "startLine": 1, "endLine": 4},
        # 写出调用静态可见但运行后产物缺失：宿主区分"未执行到"与"未引用签发路径"。
        "writeNotExecutedPaths": ["analysis/out.json"],
    }
    # 零产物场景首跑即打开重写闸门，第二轮 run_script 写出产物后同批 submit_script
    # 即可成功，整个 runner 只需要 2 个 model request。
    assert len(sample["modelRequestMetrics"]) == 2
    assert "firstToolFailure" not in sample["modelRequestMetrics"][1]


@pytest.mark.anyio
async def test_tool_call_limit_rejection_is_coded(workspace, monkeypatch):  # noqa: F811
    from smart_reporting.reporting.agent import create_reporting_code_agent_factory
    from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import (
        _ResponsesClient,
    )
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
        SOURCE,
        ToolkitRuntime,
        _batch_response,
        _custom_response,
        _message_response,
    )
    from smart_reporting.reporting.workflow.runtime import code_generation

    monkeypatch.setattr(code_generation, "ANALYSIS_TOOL_CALL_LIMIT", 2)
    client = _ResponsesClient([
        _batch_response(
            _custom_response("write_script", "# Python\n" + SOURCE, 1),
            _function_response(2, "run_script", {}),
        ),
        _batch_response(
            _function_response(3, "run_script", {}),
        ),
        _message_response("结束"),
    ])
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name="tool-limit-test",
    )

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent

    samples = []
    with pytest.raises(ReportingError):
        await ReportingCodeGenerationRunner(
            make_agent, ToolkitRuntime(), ReportingLspProcessManager(),
            coding_metrics_recorder=samples.append,
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context("task-1"))
    sample = samples[0]
    # 超限调用在执行前被宿主拦截，回执与指标都携带明确 code，
    # 不再是 Agno 硬限额的裸 tool_error。
    assert sample["modelRequestMetrics"][1]["firstToolFailure"] == {
        "toolName": "run_script",
        "code": "report_code_tool_call_limit",
        "diagnostics": {"used": 2, "limit": 2},
    }
    assert sample["toolCounts"] == {"run_script": 1, "write_script": 1}


def test_coding_metric_sample_keeps_bounded_first_run_failure_context():
    sample = build_coding_metric_sample(
        duration_ms=1,
        first_run_failure={
            "code": "report_code_execution_failed",
            "errorType": "E" * 300,
            "path": "analysis/a.py",
            "errorLine": 12,
            "exitCode": 1,
            "sourceSha256": "a" * 64,
            "detailsBytes": 999999,
        },
    )

    assert sample["firstRunFailure"] == {
        "code": "report_code_execution_failed",
        "errorType": "E" * 128,
        "path": "analysis/a.py",
        "errorLine": 12,
        "exitCode": 1,
        "sourceSha256": "a" * 64,
        "detailsBytes": 999999,
    }
def test_coding_metrics_group_by_task_model_effort_and_provider():
    grouped = group_coding_metrics([
        {"taskKind": "visualization", "model": "m", "reasoningEffort": "high", "provider": "p", "durationMs": 10},
        {"taskKind": "visualization", "model": "m", "reasoningEffort": "high", "provider": "p", "durationMs": 20},
    ])
    assert grouped["visualization|m|high|p"]["sampleCount"] == 2
    assert grouped["visualization|m|high|p"]["durationMs"] == {"p50": 10.0, "p95": 20.0}


def test_nonstream_run_output_metrics_are_recorded_with_real_request_count():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=RunMetrics(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            reasoning_tokens=10,
            cache_read_tokens=20,
            time_to_first_token=0.25,
        )
    )

    settlement.record_run_output(output, request_count=3)

    assert settlement.snapshot() == {
        "requestCount": 3,
        "inputTokens": 120,
        "outputTokens": 30,
        "totalTokens": 150,
        "reasoningTokens": 10,
        "cacheReadTokens": 20,
        "cacheWriteTokens": 0,
        "timeToFirstTokenSeconds": 0.25,
    }


def test_nonstream_request_count_is_kept_when_provider_omits_usage():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )

    settlement.record_run_output(SimpleNamespace(metrics=None), request_count=2)

    assert settlement.snapshot()["requestCount"] == 2


def test_task_metrics_partition_planner_and_coding_without_losing_total():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    planner_output = SimpleNamespace(
        metrics=RunMetrics(
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
            reasoning_tokens=20,
            cache_read_tokens=10,
            duration=1.25,
        )
    )
    coding_output = SimpleNamespace(
        metrics=RunMetrics(
            input_tokens=200,
            output_tokens=80,
            total_tokens=280,
            reasoning_tokens=60,
            cache_read_tokens=40,
            duration=2.5,
        )
    )

    settlement.stage_recorder("planner")(planner_output, 1)
    settlement.stage_recorder("coding")(coding_output, 2)

    assert settlement.snapshot()["reasoningTokens"] == 80
    assert settlement.snapshot()["requestCount"] == 3
    assert settlement.stage_snapshot() == {
        "coding": {
            "requestCount": 2,
            "inputTokens": 200,
            "outputTokens": 80,
            "totalTokens": 280,
            "reasoningTokens": 60,
            "cacheReadTokens": 40,
            "cacheWriteTokens": 0,
            "modelDurationMs": 2500,
        },
        "planner": {
            "requestCount": 1,
            "inputTokens": 100,
            "outputTokens": 30,
            "totalTokens": 130,
            "reasoningTokens": 20,
            "cacheReadTokens": 10,
            "cacheWriteTokens": 0,
            "modelDurationMs": 1250,
        },
    }


def test_task_stage_metrics_keep_missing_usage_unknown():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )

    settlement.stage_recorder("planner")(
        SimpleNamespace(metrics=None), request_count=1
    )

    assert settlement.stage_snapshot()["planner"] == {
        "requestCount": 1,
        "inputTokens": "unknown",
        "outputTokens": "unknown",
        "totalTokens": "unknown",
        "reasoningTokens": "unknown",
        "cacheReadTokens": "unknown",
        "cacheWriteTokens": "unknown",
        "modelDurationMs": "unknown",
    }


def test_task_stage_metrics_treat_agno_default_zero_usage_as_unknown():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )

    settlement.stage_recorder("planner")(
        SimpleNamespace(metrics=RunMetrics()), request_count=1
    )

    stage = settlement.stage_snapshot()["planner"]
    assert stage["requestCount"] == 1
    assert stage["inputTokens"] == "unknown"
    assert stage["outputTokens"] == "unknown"
    assert stage["reasoningTokens"] == "unknown"
    assert stage["modelDurationMs"] == "unknown"


def test_task_stage_metrics_record_and_enforce_agent_role() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=RunMetrics(input_tokens=1, output_tokens=1, reasoning_tokens=1)
    )

    settlement.stage_recorder("coding", agent_role="analysis-coding")(output, 1)

    assert settlement.stage_snapshot()["coding"]["agentRole"] == "analysis-coding"
    with pytest.raises(ValueError, match="不同 agent_role"):
        settlement.stage_recorder("coding", agent_role="visualization-coding")(output, 1)


def test_task_stage_metrics_persist_provider_request_ids() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=RunMetrics(input_tokens=1, output_tokens=1, reasoning_tokens=1),
        _reporting_request_metrics=[
            {
                "requestIndex": 1,
                "providerRequestId": "resp-coding-1",
                "durationMs": 123,
                "status": "completed",
                "toolCalls": [
                    {"id": "call-1", "name": "run", "arguments": "secret"},
                    {"id": "call-2", "name": "run"},
                ],
                "toolCallCount": 2,
                "requestParams": {
                    "model": "deepseek-v4-flash-0731",
                    "reasoningEffort": "high",
                    "reasoningSummary": "auto",
                    "enableThinking": True,
                    "enableThinkingLocation": "top_level",
                    "maxOutputTokens": 65536,
                    "parallelToolCalls": True,
                    "toolChoice": "auto",
                    "extraBodyKeys": ["enable_thinking"],
                },
            }
        ],
    )

    settlement.stage_recorder("coding", agent_role="analysis-coding")(output, 1)

    assert settlement.stage_snapshot()["coding"]["requestMetrics"] == [
        {
            "requestIndex": 1,
            "providerRequestId": "resp-coding-1",
            "durationMs": 123,
            "status": "completed",
            "toolCalls": [
                {"id": "call-1", "name": "run"},
                {"id": "call-2", "name": "run"},
            ],
            "toolCallCount": 2,
            "requestParams": {
                "model": "deepseek-v4-flash-0731",
                "reasoningEffort": "high",
                "reasoningSummary": "auto",
                "enableThinking": True,
                "enableThinkingLocation": "top_level",
                "maxOutputTokens": 65536,
                "parallelToolCalls": True,
                "toolChoice": "auto",
                "extraBodyKeys": ["enable_thinking"],
            },
        }
    ]


def test_task_stage_metrics_preserve_started_request_without_usage() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=None,
        _reporting_request_metrics=[
            {
                "requestIndex": 1,
                "providerRequestId": "unknown",
                "status": "started",
                "durationMs": "unknown",
            }
        ],
    )

    settlement.stage_recorder("coding", agent_role="analysis-coding")(output, 1)

    stage = settlement.stage_snapshot()["coding"]
    assert stage["requestMetrics"][0]["status"] == "started"
    assert stage["reasoningTokens"] == "unknown"


def test_task_stage_request_metrics_bound_values() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=RunMetrics(input_tokens=1),
        _reporting_request_metrics=[
            {
                "requestIndex": -1,
                "providerRequestId": "x" * 500,
                "durationMs": -1,
                "status": "unexpected",
            }
        ],
    )

    settlement.stage_recorder("coding")(output, 1)

    assert settlement.stage_snapshot()["coding"]["requestMetrics"] == [
        {
            "requestIndex": "unknown",
            "providerRequestId": "x" * 256,
            "durationMs": "unknown",
            "status": "unknown",
        }
    ]


def test_task_receipt_exposes_stage_metrics_without_changing_total_metrics():
    receipt = ReportingTaskCoordinator._finish_receipt(
        SimpleNamespace(finish_receipt={"ok": True}),
        model_metrics={"requestCount": 3, "reasoningTokens": 80},
        model_metrics_by_stage={
            "planner": {"requestCount": 1, "reasoningTokens": 20},
            "coding": {"requestCount": 2, "reasoningTokens": 60},
        },
    )

    assert receipt == {
        "ok": True,
        "modelMetrics": {"requestCount": 3, "reasoningTokens": 80},
        "modelMetricsByStage": {
            "planner": {"requestCount": 1, "reasoningTokens": 20},
            "coding": {"requestCount": 2, "reasoningTokens": 60},
        },
        "plannerCodingReasoningTokens": 80,
    }


@pytest.mark.parametrize(
    "metrics",
    [
        {},
        {"planner": {"reasoningTokens": 20}},
        {
            "planner": {"reasoningTokens": "unknown"},
            "coding": {"reasoningTokens": 60},
        },
        {
            "planner": {"reasoningTokens": 20},
            "coding": {"reasoningTokens": "unknown"},
        },
    ],
)
def test_planner_coding_reasoning_requires_both_observed_stages(metrics) -> None:
    assert planner_coding_reasoning_tokens(metrics) == "unknown"


def test_task_receipt_keeps_summary_separate_from_planner_coding_reasoning() -> None:
    receipt = ReportingTaskCoordinator._finish_receipt(
        SimpleNamespace(finish_receipt={"ok": True}),
        model_metrics_by_stage={
            "planner": {"reasoningTokens": 20},
            "coding": {"reasoningTokens": 60},
            "summary": {"reasoningTokens": 40},
        },
    )

    assert receipt["plannerCodingReasoningTokens"] == 80
    assert receipt["modelMetricsByStage"]["summary"]["reasoningTokens"] == 40


def test_metric_failure_code_ignores_resolved_tool_failure():
    assert _metric_failure_code(
        None,
        {
            "code": "report_python_source_path_invalid",
            "resolved": True,
        },
    ) is None


def test_metric_failure_code_keeps_terminal_and_unresolved_failures():
    unresolved = {
        "code": "report_python_source_path_invalid",
        "resolved": False,
    }

    assert _metric_failure_code(None, unresolved) == "report_python_source_path_invalid"
    assert _metric_failure_code("report_code_generation_no_submission", unresolved) == (
        "report_code_generation_no_submission"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("protocol_error", [False, True])
async def test_runner_records_metrics_before_no_submission(workspace, protocol_error):  # noqa: F811
    recorded: list[tuple[object, int]] = []
    coding_samples: list[dict[str, object]] = []
    output = SimpleNamespace(
        metrics=RunMetrics(
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            cache_read_tokens=3,
            cost=0.004,
        )
    )
    if protocol_error:
        output.metrics = RunMetrics()

    class Model:
        def configure_code_run(self, _tools, *, max_model_requests, delivery_reserve=None, redundant_call_check=None, delivery_state_reader=None, tool_call_limit=None, visual_budget_gate_safety_margin=2):
            # 30 次工具调用后仍需允许一次模型终止响应。
            assert max_model_requests == 31
            assert delivery_state_reader()["nextTools"] == ["write_script"]

        def code_run_request_count(self):
            return 2

        def code_run_raw_protocol_correct(self):
            return False

        def code_run_request_metrics(self):
            return [
                {
                    "requestIndex": 1,
                    "durationMs": 111,
                    "inputTokens": 10,
                    "outputTokens": 20,
                    "reasoningTokens": 12,
                    "visibleOutputTokens": 8,
                    "cacheReadTokens": 3,
                    "timeToFirstTokenSeconds": "unknown",
                    "toolNames": ["write_script"],
                    "status": "completed",
                }
            ]

        def report_run_error(self):
            if protocol_error:
                return ReportingError("report_code_custom_tool_protocol_error", "invalid call")
            return None

    class Agent:
        model = Model()
        tool_call_limit = 20

        async def arun(self, _prompt, **_kwargs):
            return output

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    def build_agent(tools):
        toolkit = next(tool.entrypoint.__self__ for tool in tools if tool.name == "write_script")
        toolkit.first_repair_success = True
        toolkit.first_script_success = False
        toolkit.first_script_failure_code = "report_code_input_wrapped"
        toolkit.first_run_success = False
        toolkit.first_run_failure_code = "report_code_execution_failed"
        toolkit.visual_review_duration_ms = 123
        return Agent()

    runner = ReportingCodeGenerationRunner(
        build_agent,
        Runtime(),
        ReportingLspProcessManager(),
        model_metrics_recorder=lambda value, count: recorded.append((value, count)),
        coding_metrics_recorder=coding_samples.append,
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    expected_code = (
        "report_code_custom_tool_protocol_error" if protocol_error
        else "report_code_generation_no_submission"
    )
    assert caught.value.code == expected_code
    assert coding_samples[0]["failureCode"] == expected_code
    assert recorded == [(output, 2)]
    assert output._reporting_request_metrics == [
        {
            "requestIndex": 1,
            "durationMs": 111,
            "inputTokens": 10,
            "outputTokens": 20,
            "reasoningTokens": 12,
            "visibleOutputTokens": 8,
            "cacheReadTokens": 3,
            "timeToFirstTokenSeconds": "unknown",
            "toolNames": ["write_script"],
            "status": "completed",
        }
    ]
    assert coding_samples[0]["durationMs"] >= 0
    assert coding_samples[0]["taskId"] == "task-1"
    assert coding_samples[0]["modelRequests"] == 2
    assert coding_samples[0]["firstWriteRequestDurationMs"] == 111
    assert coding_samples[0]["firstWriteReasoningTokens"] == 12
    assert coding_samples[0]["firstScriptFailureCode"] == "report_code_input_wrapped"
    assert coding_samples[0]["inputTokens"] == ("unknown" if protocol_error else 10)
    assert coding_samples[0]["outputTokens"] == ("unknown" if protocol_error else 20)
    assert coding_samples[0]["cacheReadTokens"] == ("unknown" if protocol_error else 3)
    assert coding_samples[0]["modelCost"] == ("unknown" if protocol_error else 0.004)
    assert coding_samples[0]["toolCalls"] == 0
    assert coding_samples[0]["rawProtocolCorrect"] is False
    assert coding_samples[0]["firstScriptSuccess"] is False
    assert coding_samples[0]["firstRunSuccess"] is False
    assert coding_samples[0]["firstRunFailureCode"] == "report_code_execution_failed"
    assert coding_samples[0]["firstRepairSuccess"] is True
    assert coding_samples[0]["visualReviewDurationMs"] == 123


@pytest.mark.anyio
async def test_runner_rejects_agno_model_without_code_protocol(workspace):  # noqa: F811
    agent = AgnoAgent(
        model=OpenAIChat(id="test", api_key="test", base_url="http://localhost")
    )
    agent.arun = AsyncMock()

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    runner = ReportingCodeGenerationRunner(
        lambda _tools: agent, Runtime(), ReportingLspProcessManager()
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_model_protocol_missing"
    agent.arun.assert_not_awaited()


@pytest.mark.anyio
async def test_runner_records_request_count_when_agent_raises(workspace):  # noqa: F811
    recorded: list[tuple[object, int]] = []

    class Model:
        def configure_code_run(self, _tools, *, max_model_requests, delivery_reserve=None, redundant_call_check=None, delivery_state_reader=None, tool_call_limit=None, visual_budget_gate_safety_margin=2):
            assert max_model_requests == 31
            assert delivery_state_reader()["nextTools"] == ["write_script"]

        def code_run_request_count(self):
            return 2

    class Agent:
        model = Model()
        tool_call_limit = 20

        async def arun(self, _prompt, **_kwargs):
            raise RuntimeError("provider failed")

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    runner = ReportingCodeGenerationRunner(
        lambda _tools: Agent(),
        Runtime(),
        ReportingLspProcessManager(),
        model_metrics_recorder=lambda value, count: recorded.append((value, count)),
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_generation_agent_failed"
    assert recorded == [(None, 2)]


def test_budget_envelope_normalized_is_not_a_protocol_violation():
    from smart_reporting.reporting.code_agent.budget import CodeBudget

    budget = CodeBudget(request_limit=4, reserve=0)
    budget.record_custom_input(protocol_correct=True)
    budget.record_envelope_normalized()
    assert budget.raw_protocol_correct() is True
    assert budget.envelope_normalized_inputs == 1
    budget.record_custom_input(protocol_correct=False)
    assert budget.raw_protocol_correct() is False
    assert budget.envelope_normalized_inputs == 1


@pytest.mark.anyio
async def test_multi_layer_envelope_still_counts_as_protocol_violation(workspace):  # noqa: F811
    from smart_reporting.reporting.agent import create_reporting_code_agent_factory
    from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import (
        _ResponsesClient,
    )
    from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
        ToolkitRuntime,
        _custom_response,
    )

    source = '# Python\nprint(1)\n'
    wrapped = json.dumps({"data": json.dumps({"data": source})})
    client = _ResponsesClient([_custom_response("write_script", wrapped, 1)])
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name="envelope-multilayer-test",
    )

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent

    samples = []
    with pytest.raises(ReportingError, match="report_code_generation_agent_failed"):
        await ReportingCodeGenerationRunner(
            make_agent, ToolkitRuntime(), ReportingLspProcessManager(),
            coding_metrics_recorder=samples.append,
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context("task-1"))
    assert samples[0]["rawProtocolCorrect"] is False
    assert samples[0]["envelopeNormalizedInputs"] == 0
