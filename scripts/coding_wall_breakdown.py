"""把冻结回放结果 JSON 拆成墙钟构成与首写拒绝轨迹，只读、不调用 provider。

用法：
    .venv/bin/python scripts/coding_wall_breakdown.py \
        .local/reporting-validation/frozen-visual-v3/full-chain-candidate-*.json \
        [--csv out.csv]

每个样本输出：
- plannerModelS：plannerRequestMetrics[].durationMs 之和
- codingModelS：requestMetrics[].durationMs 之和（provider 边界计时）
- scriptExecS：codingMetrics[*].executionSpans.script 之和（正式脚本子进程）
- visionS：codingMetrics[*].visualReviewDurationMs 之和
- residualS：seconds 减去以上四项；为负说明存在重叠计时，只作提示
- rejectedWrites / rejectedWriteS / rejectCodes：首个被接受的 write_script 之前被拒的整稿写入
- runs / runFailures：run_script 调用与失败次数（按请求级 firstToolFailure 统计，偏保守）
- firstSuccessfulRunRequest：首个含 run_script 且整批无工具失败的请求序号（用于标定失败快停阈值）
- gateTripped / gateCriticalCategories：通过样本的最终视觉回执仍要求修订，只能经收敛闸门降级提交

Coding-only 回放（benchmarkMode=coding-only）不执行 planner，plannerModelS 记 0。
汇总另给出单次通过率 Wilson 95% 区间、expectedSecondsPerDelivery 与 gateTrippedRate；
timed_out 删失样本不进分位数、通过率和期望成本。

缺失字段保持 unknown，不填 0；不从 completion tokens 或总耗时反推任何分项。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

UNKNOWN = "unknown"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def _sum_ms(values: Iterable[Any]) -> float | None:
    total = 0.0
    observed = False
    for value in values:
        number = _num(value)
        if number is None:
            return None
        total += number
        observed = True
    return total if observed else None


def _tool_names(request: Mapping[str, Any]) -> list[str]:
    calls = request.get("toolCalls")
    if isinstance(calls, list) and calls:
        return [str(call.get("name")) for call in calls if isinstance(call, Mapping)]
    names = request.get("toolNames")
    return [str(name) for name in names] if isinstance(names, list) else []


def _first_failure(request: Mapping[str, Any]) -> tuple[str | None, str | None]:
    failure = request.get("firstToolFailure")
    if not isinstance(failure, Mapping):
        return None, None
    return failure.get("toolName"), failure.get("code")


def _review_value(review: Mapping[str, Any], snake: str, camel: str) -> Any:
    return review.get(snake, review.get(camel))


def _gate_trip(payload: Mapping[str, Any]) -> tuple[bool | str, list[str]]:
    """最终回执仍 requiresRevision 却通过，说明经连续 critical 闸门降级提交。"""

    if payload.get("status") != "passed":
        return False, []
    samples = payload.get("codingMetrics")
    last = samples[-1] if isinstance(samples, list) and samples else None
    recorded = last.get("visualReviewGateTripped") if isinstance(last, Mapping) else None
    if isinstance(recorded, bool):
        categories = last.get("gateCriticalCategories")
        return recorded, (
            [str(item) for item in categories] if recorded and isinstance(categories, list) else []
        )
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        return UNKNOWN, []
    categories: list[str] = []
    tripped = False
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        if _review_value(review, "requires_revision", "requiresRevision") is not True:
            continue
        tripped = True
        for issue in review.get("issues") or ():
            if isinstance(issue, Mapping) and issue.get("severity") == "critical":
                categories.append(str(issue.get("category") or UNKNOWN))
    return tripped, categories


def breakdown(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    requests = [item for item in payload.get("requestMetrics") or () if isinstance(item, Mapping)]
    planner_requests = [
        item for item in payload.get("plannerRequestMetrics") or () if isinstance(item, Mapping)
    ]
    coding_samples = [
        item for item in payload.get("codingMetrics") or () if isinstance(item, Mapping)
    ]

    seconds = _num(payload.get("seconds"))
    planner_ms = (
        0.0
        if payload.get("benchmarkMode") == "coding-only"
        else _sum_ms(item.get("durationMs") for item in planner_requests)
    )
    coding_ms = _sum_ms(item.get("durationMs") for item in requests)

    script_values: list[Any] = []
    spans_known = bool(coding_samples)
    for sample in coding_samples:
        spans = sample.get("executionSpans")
        script = spans.get("script") if isinstance(spans, Mapping) else None
        if not isinstance(script, list):
            spans_known = False
            break
        script_values.extend(script)
    script_ms = _sum_ms(script_values) if spans_known else None
    if spans_known and not script_values:
        script_ms = 0.0
    vision_ms = (
        _sum_ms(sample.get("visualReviewDurationMs") for sample in coding_samples)
        if coding_samples
        else None
    )

    rejected_writes = 0
    rejected_write_ms: float | None = 0.0
    reject_codes: list[str] = []
    accepted_write_index: int | str = UNKNOWN
    runs = 0
    run_failures = 0
    first_successful_run: int | str = UNKNOWN
    for position, request in enumerate(requests, start=1):
        names = _tool_names(request)
        tool, code = _first_failure(request)
        runs += names.count("run_script")
        if tool == "run_script":
            run_failures += 1
        if first_successful_run == UNKNOWN and "run_script" in names and tool is None:
            first_successful_run = request.get("requestIndex", position)
        if accepted_write_index != UNKNOWN or "write_script" not in names:
            continue
        if tool == "write_script":
            rejected_writes += 1
            reject_codes.append(str(code or UNKNOWN))
            duration = _num(request.get("durationMs"))
            rejected_write_ms = (
                None
                if rejected_write_ms is None or duration is None
                else rejected_write_ms + duration
            )
        else:
            accepted_write_index = request.get("requestIndex", position)

    parts = [planner_ms, coding_ms, script_ms, vision_ms]
    residual = (
        seconds - sum(part / 1000 for part in parts)
        if seconds is not None and all(part is not None for part in parts)
        else None
    )
    last_coding = coding_samples[-1] if coding_samples else {}
    gate_tripped, gate_categories = _gate_trip(payload)
    failure = payload.get("failure") if isinstance(payload.get("failure"), Mapping) else {}

    def seconds_or_unknown(value: float | None) -> float | str:
        return round(value / 1000, 1) if value is not None else UNKNOWN

    return {
        "sample": path.stem,
        "status": payload.get("status", UNKNOWN),
        "failureCode": failure.get("code") or "",
        "seconds": round(seconds, 1) if seconds is not None else UNKNOWN,
        "plannerModelS": seconds_or_unknown(planner_ms),
        "codingModelS": seconds_or_unknown(coding_ms),
        "scriptExecS": seconds_or_unknown(script_ms),
        "scriptRuns": len(script_values) if spans_known else UNKNOWN,
        "visionS": seconds_or_unknown(vision_ms),
        "residualS": round(residual, 1) if residual is not None else UNKNOWN,
        "codingRequests": len(requests),
        "codingReasoning": last_coding.get("reasoningTokens", UNKNOWN),
        "rejectedWrites": rejected_writes,
        "rejectedWriteS": seconds_or_unknown(rejected_write_ms),
        "rejectCodes": "|".join(reject_codes),
        "acceptedWriteRequest": accepted_write_index,
        "runs": runs,
        "runFailures": run_failures,
        "firstSuccessfulRunRequest": first_successful_run,
        "criticalVisualDefect": last_coding.get("criticalVisualDefect", UNKNOWN),
        "gateTripped": gate_tripped,
        "gateCriticalCategories": "|".join(gate_categories),
    }


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """单次通过率的 Wilson 区间；小样本下比正态近似更稳。"""

    if total <= 0:
        raise ValueError("total 必须为正数")
    rate = successes / total
    denominator = 1 + z**2 / total
    center = (rate + z**2 / (2 * total)) / denominator
    half = z * ((rate * (1 - rate) / total + z**2 / (4 * total**2)) ** 0.5) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def expected_seconds_per_delivery(
    passed_mean: float, failed_mean: float, pass_rate: float
) -> float:
    """失败后按 fresh attempt 重来时，每交付一个章节的期望墙钟。"""

    if not 0 < pass_rate <= 1:
        raise ValueError("pass_rate 必须在 (0, 1] 内")
    return passed_mean + (1 - pass_rate) / pass_rate * failed_mean


def summarize(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    passed = [row for row in rows if row["status"] == "passed"]
    censored = [row for row in rows if row["status"] == "timed_out"]
    failed = [row for row in rows if row["status"] not in {"passed", "timed_out"}]
    lines.append(
        f"samples={len(rows)} passed={len(passed)} failed={len(failed)} censored={len(censored)}"
    )
    completed = len(passed) + len(failed)
    if completed:
        low, high = wilson_interval(len(passed), completed)
        lines.append(
            f"passRate={len(passed) / completed:.0%} wilson95=[{low:.0%}, {high:.0%}] n={completed}"
        )
    passed_seconds = [row["seconds"] for row in passed if isinstance(row["seconds"], int | float)]
    failed_seconds = [row["seconds"] for row in failed if isinstance(row["seconds"], int | float)]
    if passed_seconds and completed:
        expected = expected_seconds_per_delivery(
            statistics.mean(passed_seconds),
            statistics.mean(failed_seconds) if failed_seconds else 0.0,
            len(passed) / completed,
        )
        lines.append(f"expectedSecondsPerDelivery={expected:.1f}")
    gate_known = [row for row in passed if isinstance(row["gateTripped"], bool)]
    if gate_known:
        tripped = [row for row in gate_known if row["gateTripped"]]
        categories = Counter(
            category
            for row in tripped
            for category in str(row["gateCriticalCategories"]).split("|")
            if category
        )
        lines.append(
            f"gateTrippedRate={len(tripped) / len(gate_known):.0%} "
            f"({len(tripped)}/{len(gate_known)}) categories={dict(categories.most_common())}"
        )
    for field in (
        "seconds",
        "plannerModelS",
        "codingModelS",
        "scriptExecS",
        "visionS",
        "rejectedWriteS",
    ):
        values = [row[field] for row in passed if isinstance(row[field], int | float)]
        if values:
            lines.append(
                f"passed.{field}: n={len(values)} p50={_percentile(values, 50):.1f} "
                f"p95={_percentile(values, 95):.1f} mean={statistics.mean(values):.1f}"
            )
    shares = []
    for row in passed:
        if (
            isinstance(row["seconds"], int | float)
            and isinstance(row["scriptExecS"], int | float)
            and row["seconds"]
        ):
            shares.append(row["scriptExecS"] / row["seconds"])
    if shares:
        lines.append(
            f"passed.scriptExecShare: p50={_percentile(shares, 50):.0%} max={max(shares):.0%}"
        )
    codes = Counter(code for row in rows for code in str(row["rejectCodes"]).split("|") if code)
    lines.append(f"rejectCodes: {dict(codes.most_common())}")
    failures = Counter(row["failureCode"] for row in rows if row["status"] != "passed")
    lines.append(f"failureCodes: {dict(failures.most_common())}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    rows = []
    for path in sorted(args.results):
        try:
            rows.append(breakdown(path))
        except (OSError, json.JSONDecodeError) as error:
            print(f"skip {path}: {type(error).__name__}", file=sys.stderr)
    if not rows:
        return 1
    columns = list(rows[0])
    writer = csv.DictWriter(sys.stdout, fieldnames=columns, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    print()
    for line in summarize(rows):
        print(line)
    if args.csv:
        with args.csv.open("w", encoding="utf-8", newline="") as handle:
            csv_writer = csv.DictWriter(handle, fieldnames=columns)
            csv_writer.writeheader()
            csv_writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
