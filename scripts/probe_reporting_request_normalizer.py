"""使用真实 Reporting 请求归一化器探测 reportType 和 domains 语义决策。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))

from agno.agent import Agent  # noqa: E402 - 直接执行脚本时必须先定位 worktree 根目录
from agno.run import RunContext  # noqa: E402 - 同上

from smart_reporting.reporting.agent import _report_model  # noqa: E402 - 同上
from smart_reporting.reporting.phase import bind_reporting_run_context  # noqa: E402 - 同上
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime  # noqa: E402 - 同上
from smart_reporting.runtime.settings import AgentSettings  # noqa: E402 - 同上


@dataclass(frozen=True, slots=True)
class ProbeScenario:
    name: str
    prompt: str
    report_type: Literal["comprehensive", "topic"]
    domains: tuple[str, ...]


def probe_scenarios() -> tuple[ProbeScenario, ...]:
    return (
        ProbeScenario(
            name="overall-operation",
            prompt="分析下2025年医院整体运营情况",
            report_type="comprehensive",
            domains=("income", "workload", "budget", "full_cost", "cost_control", "funds"),
        ),
        ProbeScenario(
            name="hospital-cost",
            prompt="分析2025年医院成本",
            report_type="topic",
            domains=("full_cost",),
        ),
        ProbeScenario(
            name="income-workload",
            prompt="分析2025年收入和工作量关系",
            report_type="topic",
            domains=("income", "workload"),
        ),
        ProbeScenario(
            name="scoped-comprehensive",
            prompt="综合分析2025年收入、预算和成本",
            report_type="comprehensive",
            domains=("income", "budget", "full_cost"),
        ),
    )


def _runtime(settings: AgentSettings, model_tier: Literal["fast", "standard"]) -> ReportWorkflowRuntime:
    selected_model = (
        settings.model_fast_id if model_tier == "fast" else settings.model_standard_id
    )
    selected_mode = (
        settings.model_fast_structured_mode
        if model_tier == "fast"
        else settings.model_standard_structured_mode
    )
    probe_settings = replace(
        settings,
        model_standard_id=selected_model,
        model_standard_structured_mode=selected_mode,
    )
    model = _report_model(
        probe_settings,
        enable_thinking=False,
        retries=0,
        timeout_seconds=settings.model_timeout_seconds,
    )
    return ReportWorkflowRuntime(
        db=SimpleNamespace(),
        reporting_agent_template=Agent(model=model),
        task_runner=SimpleNamespace(),
        workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(),
        profiles=SimpleNamespace(),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
        state_repository=SimpleNamespace(),
    )


async def _probe_once(
    runtime: Any,
    scenario: ProbeScenario,
    *,
    task_timeout: int,
) -> dict[str, Any]:
    context = RunContext(
        run_id=f"probe-request-{scenario.name}",
        session_id=f"probe-request-session-{scenario.name}",
        user_id="reporting-request-probe",
        session_state={},
    )
    started = time.perf_counter()
    error: str | None = None
    content: Any = None
    try:
        with bind_reporting_run_context(context):
            output = await asyncio.wait_for(
                runtime.normalize_report_request(
                    SimpleNamespace(input=scenario.prompt, additional_data=None),
                    context,
                ),
                timeout=task_timeout,
            )
        content = output.content
    except TimeoutError:
        error = f"task_timeout: exceeded {task_timeout} seconds"
    except Exception as exc:  # noqa: BLE001 - Probe 只输出异常类型和短消息。
        error = f"{type(exc).__name__}: {str(exc)[:500]}"

    actual_report_type = content.get("reportType") if isinstance(content, dict) else None
    raw_domains = content.get("domains") if isinstance(content, dict) else None
    actual_domains = raw_domains if isinstance(raw_domains, list) else None
    valid = (
        error is None
        and actual_report_type == scenario.report_type
        and actual_domains == list(scenario.domains)
    )
    return {
        "scenario": scenario.name,
        "prompt": scenario.prompt,
        "expectedReportType": scenario.report_type,
        "expectedDomains": list(scenario.domains),
        "actualReportType": actual_report_type,
        "actualDomains": actual_domains,
        "valid": valid,
        "seconds": round(time.perf_counter() - started, 2),
        "error": error,
    }


async def _run(
    args: argparse.Namespace,
    *,
    runtime: Any | None = None,
    model_id: str | None = None,
) -> int:
    if runtime is None:
        settings = AgentSettings.from_environment()
        runtime = _runtime(settings, args.model_tier)
        model_id = (
            settings.model_fast_id
            if args.model_tier == "fast"
            else settings.model_standard_id
        )

    results: list[dict[str, Any]] = []
    for scenario in probe_scenarios():
        result = await _probe_once(runtime, scenario, task_timeout=args.task_timeout)
        results.append(result)
        if args.progress_file:
            with open(args.progress_file, "a", encoding="utf-8") as progress:
                progress.write(json.dumps(result, ensure_ascii=False) + "\n")

    valid_count = sum(result["valid"] for result in results)
    print(
        json.dumps(
            {
                "model": model_id,
                "runs": results,
                "valid_count": valid_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if valid_count == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="使用真实 Reporting 请求归一化器探测 reportType 和 domains 语义决策"
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model-tier", choices=("fast", "standard"), default="standard")
    parser.add_argument("--task-timeout", type=int, default=90)
    parser.add_argument("--progress-file")
    args = parser.parse_args()
    if not 1 <= args.task_timeout <= 300:
        parser.error("--task-timeout 必须在 1 到 300 之间")
    os.environ["AGENT_ENV_FILE"] = args.env_file
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()


__all__ = ["ProbeScenario", "probe_scenarios"]
