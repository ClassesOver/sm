"""真实验证 Coding Agent 执行修复闭环，并对照 Responses reasoning effort。"""

# ruff: noqa: E402 - 直接运行脚本时先把仓库根目录加入模块搜索路径。

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx
from agno.metrics import RunMetrics
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.workspace import Workspace
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import create_reporting_code_mode_runtime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceIdentity,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
)

BROKEN_SOURCE = '''import json
from pathlib import Path

values = [3, 1, 4, 1, 5]
result = {"sum": sum(values), "count": len(value)}
Path("analysis/out.json").write_text(json.dumps(result), encoding="utf-8")
'''
FIXED_SOURCE = BROKEN_SOURCE.replace("len(value)", "len(values)")
RUN_TOOL = {
    "type": "custom",
    "name": "run",
    "description": (
        "FREEFORM Python source. Start with # Python and a newline; "
        "do not use JSON, quotes, or Markdown."
    ),
    "format": {
        "type": "grammar",
        "syntax": "lark",
        "definition": (
            'start: "# Python" NEWLINE SOURCE\n'
            'NEWLINE: /\\r?\\n/\nSOURCE: /[\\s\\S]+/'
        ),
    },
}
RECORD_TOOL = {
    "type": "function",
    "name": "record_design",
    "description": "Record the implementation design.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "algorithm": {"type": "string"},
            "complexity": {"type": "string"},
            "rollback_safe": {"type": "boolean"},
        },
        "required": ["algorithm", "complexity", "rollback_safe"],
        "additionalProperties": False,
    },
}
COMPARE_PROMPT = (
    "Implement a compact production-quality Python 3 rollback DSU module. It must support "
    "snapshots, rollback, union-by-size, connectivity queries, component sizes, duplicate union "
    "attempts, and must not use path compression. Keep it under 140 nonblank source lines. Before "
    "ending this response, call run once with the complete raw module starting '# Python\\n' and "
    "call record_design once. Calls may appear in either order. Emit structured calls, not prose."
)


def _config(env_file: Path) -> dict[str, Any]:
    config = {**dotenv_values(env_file), **os.environ}
    missing = [key for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY") if not config.get(key)]
    if missing:
        raise SystemExit(f"缺少环境变量：{', '.join(missing)}")
    return config


def _metrics(metrics: RunMetrics | None, request_count: int) -> dict[str, Any]:
    return {
        "requestCount": request_count,
        "inputTokens": getattr(metrics, "input_tokens", 0) or 0,
        "outputTokens": getattr(metrics, "output_tokens", 0) or 0,
        "reasoningTokens": getattr(metrics, "reasoning_tokens", 0) or 0,
        "cacheReadTokens": getattr(metrics, "cache_read_tokens", 0) or 0,
        "timeToFirstTokenSeconds": getattr(metrics, "time_to_first_token", None),
    }


async def _workflow_probe(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started = perf_counter()
    model_id = args.model or config.get("AGENT_MODEL_STANDARD") or "deepseek-v4-flash-0731"
    with tempfile.TemporaryDirectory(prefix="reporting-code-workflow-") as directory:
        root = Path(directory).resolve()
        identity = ReportingWorkspaceIdentity(
            workflow_session_id="live-code-workflow",
            workspace_key="live-code-workflow",
            scope_fingerprint="live-code-workflow",
            root=root,
            workspace=Workspace(str(root)),
        )
        workspace = HostReportingWorkspace(identity)
        await workspace.aensure_directory("live-task", "analysis")
        await workspace.awrite_text("live-task", "analysis/task.py", BROKEN_SOURCE)
        task = ReportingCodingTaskContext(
            task_id="live-task",
            task_kind="analysis",
            code_mode_session_id="live-code-workflow",
            workspace_key=identity.workspace_key,
            workspace_root=root,
            script_path="analysis/task.py",
            authorized_read_paths=(),
            authorized_write_paths=("analysis/task.py", "analysis/out.json"),
            declared_output_paths=("analysis/out.json",),
            max_source_bytes=128 * 1024,
        )
        model = OpenAIChat(
            id=model_id,
            api_key=config["OPENAI_API_KEY"],
            base_url=config["OPENAI_BASE_URL"],
            timeout=args.timeout,
            max_retries=0,
        )
        model.reasoning_effort = args.reasoning_effort
        model.temperature = 0.0
        factory = create_reporting_code_agent_factory(
            model=model,
            name="live-code-workflow",
            task_kind="analysis",
            instructions=(
                "当前脚本已存在。先原样 run_script 获取真实错误；"
                "依据失败回执用 edit_script 精确局部修复，重新 run_script，最后 submit_script。"
                "输出必须是 analysis/out.json，内容严格为 sum=14、count=5。"
            ),
        )
        runtime = create_reporting_code_mode_runtime(
            root, analysis_concurrency=1, section_concurrency=0, timeout=args.timeout
        )
        lsp = ReportingLspProcessManager()
        recorded: list[dict[str, Any]] = []
        coding_metrics: list[dict[str, Any]] = []

        def record(run_output: Any, request_count: int) -> None:
            recorded.append(_metrics(getattr(run_output, "metrics", None), request_count))

        runner = ReportingCodeGenerationRunner(
            factory, runtime, lsp, model_metrics_recorder=record,
            coding_metrics_recorder=lambda sample: coding_metrics.append(dict(sample)),
        )
        try:
            result = await runner.run(
                task,
                workspace,
                {
                    "expectedOutput": {"sum": 14, "count": 5},
                    "acceptance": "修复已有脚本并通过真实执行后提交",
                },
                run_context=RunContext(
                    run_id="live-code-workflow",
                    session_id="live-code-workflow",
                    session_state={},
                ),
            )
            source = await workspace.aread_text(task.task_id, task.script_path)
            output = json.loads(
                await workspace.aread_text(task.task_id, task.declared_output_paths[0])
            )
            diff = list(
                difflib.unified_diff(
                    BROKEN_SOURCE.splitlines(), source.splitlines(), lineterm=""
                )
            )
            passed = (
                source == FIXED_SOURCE
                and output == {"sum": 14, "count": 5}
                and result.script_file.sha256 == result.execution_receipt.source_file.sha256
                and [item.path for item in result.execution_receipt.output_files]
                == ["analysis/out.json"]
            )
            return {
                "passed": passed,
                "model": model_id,
                "seconds": round(perf_counter() - started, 3),
                "output": output,
                "sourceExactLocalFix": source == FIXED_SOURCE,
                "diff": diff,
                "metrics": recorded,
                "codingMetrics": coding_metrics,
            }
        except Exception as error:
            return {
                "passed": False,
                "model": model_id,
                "seconds": round(perf_counter() - started, 3),
                "failure": {"type": type(error).__name__,
                            "code": getattr(error, "code", type(error).__name__),
                            "details": getattr(error, "details", {})},
                "codingMetrics": coding_metrics,
            }
        finally:
            await runtime.aclose()
            await lsp.aclose()


def _reasoning_summary_chars(output: list[dict[str, Any]]) -> int:
    return sum(
        len(part.get("text", ""))
        for item in output
        if item.get("type") == "reasoning"
        for part in item.get("summary", [])
    )


async def _compare_trial(
    client: httpx.AsyncClient,
    endpoint: str,
    api_key: str,
    model: str,
    effort: str,
    index: int,
) -> dict[str, Any]:
    started = perf_counter()
    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": effort, "summary": "auto"},
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [RUN_TOOL, RECORD_TOOL],
            "input": [{"role": "user", "content": COMPARE_PROMPT}],
        },
    )
    elapsed = round(perf_counter() - started, 3)
    if response.status_code != 200:
        try:
            error = response.json().get("error", {})
            provider_error = {key: error.get(key) for key in ("type", "code", "param")}
        except (ValueError, AttributeError):
            provider_error = "non_json"
        return {
            "effort": effort,
            "trial": index,
            "passed": False,
            "httpStatus": response.status_code,
            "seconds": elapsed,
            "providerError": provider_error,
        }
    body = response.json()
    output = body.get("output") or []
    calls = [
        item for item in output
        if item.get("type") in {"custom_tool_call", "function_call"}
    ]
    names = [item.get("name") for item in calls]
    usage = body.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    output_tokens = usage.get("output_tokens") or 0
    reasoning_tokens = details.get("reasoning_tokens") or 0
    run_calls = [item for item in calls if item.get("name") == "run"]
    raw_input = run_calls[0].get("input", "") if len(run_calls) == 1 else ""
    passed = (
        body.get("status") == "completed"
        and sorted(names) == ["record_design", "run"]
        and isinstance(raw_input, str)
        and raw_input.startswith("# Python\n")
        and not raw_input.lstrip().startswith('{"data"')
        and all(item.get("id") and item.get("call_id") for item in calls)
    )
    return {
        "effort": effort,
        "trial": index,
        "passed": passed,
        "httpStatus": response.status_code,
        "status": body.get("status"),
        "seconds": elapsed,
        "calls": names,
        "sourceChars": len(raw_input),
        "inputTokens": usage.get("input_tokens"),
        "outputTokens": output_tokens,
        "reasoningTokens": reasoning_tokens,
        "visibleOutputTokens": max(output_tokens - reasoning_tokens, 0),
        "summaryChars": _reasoning_summary_chars(output),
        "incompleteReason": (body.get("incomplete_details") or {}).get("reason"),
    }


async def _compare_probe(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    model = args.model or config.get("AGENT_MODEL_STANDARD") or "deepseek-v4-flash-0731"
    endpoint = config["OPENAI_BASE_URL"].rstrip("/") + "/responses"
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async def run(effort: str, index: int) -> dict[str, Any]:
            async with semaphore:
                try:
                    result = await _compare_trial(
                        client,
                        endpoint,
                        config["OPENAI_API_KEY"],
                        model,
                        effort,
                        index,
                    )
                except httpx.HTTPError as error:
                    result = {
                        "effort": effort,
                        "trial": index,
                        "passed": False,
                        "failure": type(error).__name__,
                    }
                print(
                    json.dumps(
                        {
                            "progress": "completed",
                            "effort": effort,
                            "trial": index,
                            "passed": result["passed"],
                            "seconds": result.get("seconds"),
                            "failure": result.get("failure"),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                return result

        trials = await asyncio.gather(*[
            run(effort, index)
            for index in range(1, args.repetitions + 1)
            for effort in ("high", "medium")
        ])
    return {
        "passed": all(trial["passed"] for trial in trials),
        "model": model,
        "host": urlsplit(endpoint).hostname,
        "repetitions": args.repetitions,
        "concurrency": args.concurrency,
        "trials": trials,
    }


async def _run(args: argparse.Namespace) -> int:
    config = _config(args.env_file)
    result = (
        await _workflow_probe(config, args)
        if args.command == "workflow"
        else await _compare_probe(config, args)
    )
    evidence = {
        "createdAt": datetime.now(UTC).isoformat(),
        "command": args.command,
        "result": result,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if result["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    workflow = subparsers.add_parser("workflow")
    workflow.add_argument(
        "--reasoning-effort", choices=("low", "medium", "high"), default="high"
    )
    compare = subparsers.add_parser("compare")
    compare.add_argument("--repetitions", type=int, default=3)
    compare.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 900:
        parser.error("--timeout 必须在 1 到 900 之间")
    if args.command == "compare" and not 1 <= args.repetitions <= 20:
        parser.error("--repetitions 必须在 1 到 20 之间")
    if args.command == "compare" and not 1 <= args.concurrency <= 20:
        parser.error("--concurrency 必须在 1 到 20 之间")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
