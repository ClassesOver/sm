"""Coding task 性能指标的有界汇总。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from math import ceil
from typing import Any

_REQUEST_TOOL_CALL_LIMIT = 140


def _bounded_tool_calls(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)):
        return []
    calls: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        call_id = item.get("id")
        name = item.get("name")
        if isinstance(call_id, str) and call_id and isinstance(name, str) and name:
            calls.append({"id": call_id[:256], "name": name[:128]})
            if len(calls) >= _REQUEST_TOOL_CALL_LIMIT:
                break
    return calls


def bounded_request_params_snapshot(value: Any) -> dict[str, Any] | None:
    """规范化脱敏 provider 参数；拒绝携带 prompt、源码或任意 extra body 值。"""

    if not isinstance(value, Mapping):
        return None

    def fingerprint(name: str) -> str:
        candidate = value.get(name)
        return (
            candidate
            if isinstance(candidate, str)
            and re.fullmatch(r"[0-9a-f]{64}", candidate)
            else "unknown"
        )

    def byte_count(name: str) -> int | str:
        candidate = value.get(name)
        return (
            candidate
            if isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and candidate >= 0
            else "unknown"
        )

    snapshot = {
        "model": (
            value.get("model")
            if isinstance(value.get("model"), str) and value.get("model")
            else "unknown"
        ),
        "reasoningEffort": (
            value.get("reasoningEffort")
            if isinstance(value.get("reasoningEffort"), str)
            and value.get("reasoningEffort")
            else "unknown"
        ),
        "reasoningSummary": (
            value.get("reasoningSummary")
            if isinstance(value.get("reasoningSummary"), str)
            and value.get("reasoningSummary")
            else "unknown"
        ),
        "enableThinking": (
            value.get("enableThinking")
            if isinstance(value.get("enableThinking"), bool)
            else "unknown"
        ),
        "enableThinkingLocation": (
            value.get("enableThinkingLocation")
            if value.get("enableThinkingLocation")
            in {"top_level", "chat_template_kwargs", "omitted"}
            else "unknown"
        ),
        "maxOutputTokens": (
            value.get("maxOutputTokens")
            if isinstance(value.get("maxOutputTokens"), int)
            and not isinstance(value.get("maxOutputTokens"), bool)
            and value.get("maxOutputTokens") >= 0
            else "unknown"
        ),
        "parallelToolCalls": (
            value.get("parallelToolCalls")
            if isinstance(value.get("parallelToolCalls"), bool)
            else "unknown"
        ),
        "toolChoice": (
            value.get("toolChoice")
            if isinstance(value.get("toolChoice"), str) and value.get("toolChoice")
            else "unknown"
        ),
        "extraBodyKeys": [
            key[:64]
            for key in value.get("extraBodyKeys", [])
            if isinstance(key, str) and key
        ][:20],
    }
    for name in (
        "systemPrefixSha256",
        "toolDeclarationsSha256",
        "schemaSha256",
    ):
        if name in value:
            snapshot[name] = fingerprint(name)
    for name in (
        "systemPrefixBytes",
        "toolDeclarationsBytes",
        "schemaBytes",
    ):
        if name in value:
            snapshot[name] = byte_count(name)
    return snapshot


def planner_coding_reasoning_tokens(
    metrics_by_stage: Mapping[str, Mapping[str, Any]],
) -> int | str:
    """严格累计 planner + Coding reasoning；任何阶段缺失都返回 unknown。"""

    values: list[int] = []
    for stage in ("planner", "coding"):
        metrics = metrics_by_stage.get(stage)
        value = metrics.get("reasoningTokens") if isinstance(metrics, Mapping) else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return "unknown"
        values.append(value)
    return sum(values)


def measure_input_components(
    components: Mapping[str, Any],
) -> dict[str, dict[str, int | str]]:
    """对稳定输入分量记录 UTF-8 大小和身份，不记录原文。"""

    result: dict[str, dict[str, int | str]] = {}
    for name, value in components.items():
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        result[name] = {
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    return result


def build_coding_metric_sample(
    *,
    duration_ms: int,
    task_id: str | None = None,
    task_kind: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    reasoning_effort: str | None = None,
    request_count: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    model_cost: float | None = None,
    tool_counts: Mapping[str, int] | None = None,
    completed_tool_calls: int | None = None,
    visual_review_duration_ms: int | None = None,
    request_metrics: Iterable[Mapping[str, Any]] | None = None,
    input_components: Mapping[str, Mapping[str, Any]] | None = None,
    raw_protocol_correct: bool | str = "unknown",
    first_script_success: bool | str = "unknown",
    first_script_failure_code: str | None = None,
    first_run_success: bool | str = "unknown",
    first_run_failure_code: str | None = None,
    first_run_failure: Mapping[str, Any] | None = None,
    first_patch_applied: bool | str = "unknown",
    first_repair_success: bool | str = "unknown",
    critical_visual_defect: bool | str = "unknown",
    failure_code: str | None = None,
    execution_spans: Mapping[str, Iterable[int | float]] | str | None = None,
) -> dict[str, Any]:
    """构造单个 Coding task 样本；没有证据的核心字段保留 ``unknown``。"""

    def bounded_nonnegative(value: Any) -> int | str:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else "unknown"

    def bounded_nonnegative_number(value: Any) -> int | float | str:
        return (
            value
            if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0
            else "unknown"
        )

    failure_snapshot: dict[str, Any] | str = "unknown"
    if isinstance(first_run_failure, Mapping):
        source_sha = first_run_failure.get("sourceSha256")
        failure_snapshot = {
            "code": (
                first_run_failure.get("code")[:128]
                if isinstance(first_run_failure.get("code"), str)
                and first_run_failure.get("code")
                else "unknown"
            ),
            "errorType": (
                first_run_failure.get("errorType")[:128]
                if isinstance(first_run_failure.get("errorType"), str)
                and first_run_failure.get("errorType")
                else "unknown"
            ),
            "path": (
                first_run_failure.get("path")[:256]
                if isinstance(first_run_failure.get("path"), str)
                and first_run_failure.get("path")
                else "unknown"
            ),
            "errorLine": bounded_nonnegative(first_run_failure.get("errorLine")),
            "exitCode": bounded_nonnegative(first_run_failure.get("exitCode")),
            "sourceSha256": (
                source_sha
                if isinstance(source_sha, str)
                and re.fullmatch(r"[0-9a-f]{64}", source_sha)
                else "unknown"
            ),
            "detailsBytes": bounded_nonnegative(first_run_failure.get("detailsBytes")),
        }

    normalized_requests: list[dict[str, Any]] = []
    for item in request_metrics or ():
        tool_names = item.get("toolNames")
        tool_calls = _bounded_tool_calls(item.get("toolCalls"))
        normalized: dict[str, Any] = {
                "requestIndex": bounded_nonnegative(item.get("requestIndex")),
                "providerRequestId": (
                    item.get("providerRequestId")
                    if isinstance(item.get("providerRequestId"), str)
                    and item.get("providerRequestId")
                    else "unknown"
                ),
                "durationMs": bounded_nonnegative(item.get("durationMs")),
                "inputTokens": bounded_nonnegative(item.get("inputTokens")),
                "outputTokens": bounded_nonnegative(item.get("outputTokens")),
                "reasoningTokens": bounded_nonnegative(item.get("reasoningTokens")),
                "visibleOutputTokens": bounded_nonnegative(
                    item.get("visibleOutputTokens")
                ),
                "cacheReadTokens": bounded_nonnegative(item.get("cacheReadTokens")),
                "timeToFirstTokenSeconds": bounded_nonnegative_number(
                    item.get("timeToFirstTokenSeconds")
                ),
                "toolNames": [
                    name[:128]
                    for name in tool_names
                    if isinstance(name, str) and name
                ][:20]
                if isinstance(tool_names, (list, tuple))
                else [],
                "toolCalls": tool_calls,
                "toolCallCount": bounded_nonnegative(item.get("toolCallCount")),
                "status": (
                    item.get("status")
                    if item.get("status") in {"started", "completed", "failed"}
                    else "unknown"
                ),
            }
        request_params = bounded_request_params_snapshot(item.get("requestParams"))
        if request_params is not None:
            normalized["requestParams"] = request_params
        normalized_requests.append(normalized)
    normalized_spans: dict[str, list[int | float] | str] | str = "unknown"
    if isinstance(execution_spans, Mapping):
        normalized_spans = {}
        for name in ("bootstrap", "monitor", "cell", "script", "shutdown"):
            values = execution_spans.get(name)
            normalized_spans[name] = (
                [
                    value for value in values[:64]
                    if isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value >= 0
                ]
                if isinstance(values, (list, tuple)) else "unknown"
            )
    first_write = next(
        (
            item
            for item in normalized_requests
            if "write_script" in item["toolNames"]
        ),
        None,
    )

    sample: dict[str, Any] = {
        "durationMs": bounded_nonnegative(duration_ms),
        "taskId": task_id if isinstance(task_id, str) and task_id else "unknown",
        "taskKind": task_kind if isinstance(task_kind, str) and task_kind else "unknown",
        "model": model if isinstance(model, str) and model else "unknown",
        "provider": provider if isinstance(provider, str) and provider else "unknown",
        "reasoningEffort": reasoning_effort if isinstance(reasoning_effort, str) and reasoning_effort else "unknown",
        "modelRequests": bounded_nonnegative(request_count),
        "inputTokens": bounded_nonnegative(input_tokens),
        "outputTokens": bounded_nonnegative(output_tokens),
        "reasoningTokens": bounded_nonnegative(reasoning_tokens),
        "cacheReadTokens": bounded_nonnegative(cache_read_tokens),
        "modelCost": bounded_nonnegative_number(model_cost),
        "toolCalls": bounded_nonnegative(completed_tool_calls),
        "toolCounts": {
            name: count
            for name, count in sorted((tool_counts or {}).items())
            if isinstance(name, str)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
        },
        "visualReviewDurationMs": bounded_nonnegative(visual_review_duration_ms),
        "modelRequestMetrics": normalized_requests,
        "executionSpans": normalized_spans,
        "inputComponents": {
            name: {
                "bytes": bounded_nonnegative(identity.get("bytes")),
                "sha256": (
                    identity.get("sha256")
                    if isinstance(identity.get("sha256"), str)
                    and len(identity["sha256"]) == 64
                    else "unknown"
                ),
            }
            for name, identity in sorted((input_components or {}).items())
            if isinstance(name, str) and isinstance(identity, Mapping)
        },
        "firstWriteRequestIndex": (
            first_write["requestIndex"] if first_write is not None else "unknown"
        ),
        "firstWriteRequestDurationMs": (
            first_write["durationMs"] if first_write is not None else "unknown"
        ),
        "firstWriteReasoningTokens": (
            first_write["reasoningTokens"] if first_write is not None else "unknown"
        ),
        "rawProtocolCorrect": raw_protocol_correct,
        "firstScriptSuccess": first_script_success,
        "firstScriptFailureCode": (
            first_script_failure_code[:128]
            if isinstance(first_script_failure_code, str) and first_script_failure_code
            else "unknown"
        ),
        "firstRunSuccess": first_run_success,
        "firstRunFailureCode": (
            first_run_failure_code[:128]
            if isinstance(first_run_failure_code, str)
            and first_run_failure_code
            and first_run_failure_code != "unknown"
            else "unknown"
        ),
        "firstRunFailure": failure_snapshot,
        "firstPatchApplied": first_patch_applied,
        "firstRepairSuccess": first_repair_success,
        "criticalVisualDefect": critical_visual_defect,
        "failureCode": failure_code if isinstance(failure_code, str) and failure_code else "unknown",
    }
    if any(item["status"] != "completed" for item in normalized_requests):
        # Agno 的累计用量可能只包含解析成功的响应，不能当作失败任务总量。
        complete = request_count == len(normalized_requests)
        for key in ("inputTokens", "outputTokens", "reasoningTokens", "cacheReadTokens"):
            values = [item[key] for item in normalized_requests]
            sample[key] = (
                sum(values) if complete and all(type(value) is int for value in values)
                else "unknown"
            )
        sample["modelCost"] = "unknown"
    return sample


def percentile(values: Iterable[float | int], rank: float) -> float | str:
    """计算最近秩 P50/P95；没有观测时返回 unknown。"""

    numbers = sorted(
        float(value)
        for value in values
        if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0
    )
    if not numbers:
        return "unknown"
    if rank <= 0 or rank > 100:
        raise ValueError("rank 必须在 (0, 100] 范围内")
    index = max(0, min(len(numbers) - 1, ceil((rank / 100) * len(numbers)) - 1))
    return numbers[index]


def summarize_coding_metrics(samples: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """按冻结回放样本汇总核心成功率、耗时和 token 长尾指标。"""

    rows = list(samples)
    count = len(rows)

    def rate(field: str) -> float | str:
        if not rows:
            return "unknown"
        observed = [row[field] for row in rows if isinstance(row.get(field), bool)]
        return sum(observed) / len(observed) if observed else "unknown"

    durations = [row.get("durationMs") for row in rows]
    reasoning = [row.get("reasoningTokens") for row in rows]
    first_write_durations = [row.get("firstWriteRequestDurationMs") for row in rows]
    first_write_reasoning = [row.get("firstWriteReasoningTokens") for row in rows]
    model_costs = [row.get("modelCost") for row in rows]
    visual_review_durations = [row.get("visualReviewDurationMs") for row in rows]
    execution_span_values: dict[str, list[int | float]] = {
        name: [] for name in ("bootstrap", "monitor", "cell", "script", "shutdown")
    }
    execution_spans_complete = True
    for row in rows:
        spans = row.get("executionSpans")
        if not isinstance(spans, Mapping):
            execution_spans_complete = False
            continue
        for name in execution_span_values:
            values = spans.get(name)
            if isinstance(values, (list, tuple)):
                execution_span_values[name].extend(
                    value for value in values
                    if isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and value >= 0
                )
            else:
                execution_spans_complete = False
    first_run_failure_codes: dict[str, int] = {}
    for row in rows:
        code = row.get("firstRunFailureCode")
        if isinstance(code, str) and code and code != "unknown":
            bounded_code = code[:128]
            first_run_failure_codes[bounded_code] = (
                first_run_failure_codes.get(bounded_code, 0) + 1
            )
    unknown_fields = {
        field
        for row in rows
        for field in (
            "rawProtocolCorrect",
            "firstScriptSuccess",
            "firstRunSuccess",
            "firstPatchApplied",
            "firstRepairSuccess",
            "criticalVisualDefect",
            "durationMs",
            "reasoningTokens",
            "firstWriteRequestDurationMs",
            "firstWriteReasoningTokens",
            "modelCost",
            "visualReviewDurationMs",
        )
        if field not in row or row.get(field) is None or row.get(field) == "unknown"
    }
    if not execution_spans_complete:
        unknown_fields.add("executionSpans")
    return {
        "sampleCount": count,
        "rawProtocolCorrectRate": rate("rawProtocolCorrect"),
        "firstScriptSuccessRate": rate("firstScriptSuccess"),
        "firstRunSuccessRate": rate("firstRunSuccess"),
        "firstPatchAppliedRate": rate("firstPatchApplied"),
        "firstRepairSuccessRate": rate("firstRepairSuccess"),
        "firstRunFailureCodes": dict(sorted(first_run_failure_codes.items())),
        "criticalVisualDefectRate": rate("criticalVisualDefect"),
        "durationMs": {"p50": percentile(durations, 50), "p95": percentile(durations, 95)},
        "reasoningTokens": {
            "p50": percentile(reasoning, 50),
            "p95": percentile(reasoning, 95),
        },
        "firstWriteRequestDurationMs": {
            "p50": percentile(first_write_durations, 50),
            "p95": percentile(first_write_durations, 95),
        },
        "firstWriteReasoningTokens": {
            "p50": percentile(first_write_reasoning, 50),
            "p95": percentile(first_write_reasoning, 95),
        },
        "modelCost": {
            "p50": percentile(model_costs, 50),
            "p95": percentile(model_costs, 95),
        },
        "visualReviewDurationMs": {
            "p50": percentile(visual_review_durations, 50),
            "p95": percentile(visual_review_durations, 95),
        },
        "executionSpans": {
            name: {"p50": percentile(values, 50), "p95": percentile(values, 95)}
            for name, values in execution_span_values.items()
        },
        "unknownFields": sorted(unknown_fields),
    }


def group_coding_metrics(samples: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """按任务类型、模型、推理档位和 provider 汇总 Coding 样本。"""

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        key = "|".join(
            str(sample.get(field) or "unknown")
            for field in ("taskKind", "model", "reasoningEffort", "provider")
        )
        groups.setdefault(key, []).append(sample)
    return {key: summarize_coding_metrics(rows) for key, rows in sorted(groups.items())}
