"""使用真实 Reporting 模型探测 apply_analysis_patch 的输出稳定性。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))

from agno.agent import Agent  # noqa: E402 - 直接执行脚本时必须先定位 worktree 根目录
from agno.tools import Function  # noqa: E402 - 同上

from smart_reporting.reporting.agent import _report_model  # noqa: E402 - 同上
from smart_reporting.reporting.model_policy import (  # noqa: E402 - 同上
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
)
from smart_reporting.runtime.settings import AgentSettings  # noqa: E402 - 同上
from smart_reporting.task_execution.tools import parse_unified_diff  # noqa: E402 - 同上


def _task(index: int) -> tuple[str, str, str, str, str]:
    domain = ("income", "cost", "床位", "门诊", "药品", "手术", "满意度", "库存")[index % 8]
    target = f"analysis/{domain}/script_{index:03d}.py"
    old = f"value_{index} = {index}"
    new = f"value_{index} = {index + 1}"
    # 与 parse_unified_diff 的内部操作名保持一致；修改统一表示为 update。
    operation = ("update", "create", "delete")[index % 3]
    if operation == "update":
        action = f"把已有文件 {target} 中的 `{old}` 修改为 `{new}`。"
        patch_template = f"--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-{old}\n+{new}"
    elif operation == "create":
        action = f"新建文件 {target}，内容只有一行 `{new}`。"
        patch_template = f"--- /dev/null\n+++ b/{target}\n@@ -0,0 +1 @@\n+{new}"
    else:
        action = f"删除已有文件 {target}，该文件当前内容只有一行 `{old}`。"
        patch_template = f"--- a/{target}\n+++ /dev/null\n@@ -1 +0,0 @@\n-{old}"
    prompt = f"""你是 Reporting Worker 的测试代理，正在处理第 {index} 个独立编码需求。
{action}
只调用 apply_analysis_patch，不要输出普通文本。
工具调用是唯一有效输出；如果上一轮未产生工具调用，下一轮会使用全新 Agent 重试。
patch 参数必须是可直接交给 git apply 的标准 unified diff，必须包含：
当前任务必须使用下列完整模板，其中每一行都不能省略：
{patch_template}
单行文件更新必须使用 @@ -1 +1 @@，不得声明不存在的行。
禁止 *** Begin Patch、*** Update File、Markdown 代码围栏和解释文字。
"""
    return target, old, new, operation, prompt


def _patch_function(received: list[dict[str, Any]], target: str, operation: str) -> Function:
    def apply_analysis_patch(
        patch: str, expected_sha256: dict[str, str] | None = None
    ) -> dict[str, Any]:
        record: dict[str, Any] = {"patch": patch, "expected_sha256": expected_sha256 or {}}
        received.append(record)
        try:
            operations = parse_unified_diff(patch)
        except Exception as error:  # noqa: BLE001 - 探针必须记录模型原始失败类型
            record.update({"valid": False, "error": str(error)})
            return {"ok": False, "code": "invalid_unified_diff", "message": str(error)}
        paths = [operation.path for operation in operations]
        valid = (
            paths == [target]
            and operations[0].operation == operation
            and "*** Begin Patch" not in patch
        )
        record.update({"valid": valid, "paths": paths})
        return {"ok": valid, "code": "accepted" if valid else "unexpected_target"}

    return Function(
        name="apply_analysis_patch",
        description=(
            "提交标准 Git unified diff。必须包含完整文件头、hunk 头和每一行内容；"
            "单行更新使用 @@ -1 +1 @@。expected_sha256 只能是 64 位小写十六进制字符串；"
            "新建文件或不需要基线时省略该字段，禁止填写 true、false 或其他布尔值。"
            "禁止 *** Begin Patch、*** Update File、Markdown 代码围栏和解释文字。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "patch": {"type": "string", "minLength": 1},
                "expected_sha256": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
        strict=True,
        entrypoint=apply_analysis_patch,
        stop_after_tool_call=True,
    )


def _build_agent(
    settings: AgentSettings,
    received: list[dict[str, Any]],
    target: str,
    prompt: str,
    operation: str,
    *,
    thinking: bool,
) -> Agent:
    model = _report_model(
        settings,
        enable_thinking=thinking,
        retries=0,
        timeout_seconds=settings.model_timeout_seconds,
    )
    profile = (
        ReportingThinkingProfile.on(
            reasoning_effort="high",
            thinking_budget=settings.report_coding_thinking_budget,
            temperature=settings.report_coding_temperature,
        )
        if thinking
        else ReportingThinkingProfile.off(temperature=0.0)
    )
    apply_reporting_thinking_profile(model, profile)
    model.max_tokens = min(settings.report_output_token_reserve, 8192)
    return Agent(
        model=model,
        tools=[_patch_function(received, target, operation)],
        instructions=[prompt],
        markdown=False,
    )


async def _run(args: argparse.Namespace) -> None:
    os.environ["AGENT_ENV_FILE"] = args.env_file
    settings = AgentSettings.from_environment()
    summary: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        target, _old, _new, operation, prompt = _task(index)
        started = time.perf_counter()
        error: str | None = None
        attempts: list[list[dict[str, Any]]] = []
        # 未调用工具或工具参数被拒绝都不能推进任务；每轮使用全新 Agent，最多三轮，
        # 避免同一上下文在 stop_after_tool_call 后继续生成无效文本。
        for attempt in range(1, 4):
            received: list[dict[str, Any]] = []
            attempts.append(received)
            try:
                await _build_agent(
                    settings, received, target, prompt, operation, thinking=args.thinking
                ).arun(prompt)
            except Exception as exc:  # noqa: BLE001 - 探针将异常写入结果，不吞掉诊断信息
                error = f"{type(exc).__name__}: {exc}"
                break
            if received and all(item.get("valid") is True for item in received):
                break
            # 工具校验失败后，当前 attempt 已被 stop_after_tool_call 终止；
            # 下一轮必须创建全新的 Agent，避免模型在同一上下文中无限修复。
        received = [item for attempt_records in attempts for item in attempt_records]
        valid = bool(attempts[-1]) and all(item.get("valid") is True for item in attempts[-1])
        if not valid and error is None and not received:
            error = "no_tool_call: Agent 未调用 apply_analysis_patch。"
        elapsed = round(time.perf_counter() - started, 2)
        summary.append(
            {
                "run": index,
                "seconds": elapsed,
                "attempts": len(attempts),
                "tool_calls": len(received),
                "valid": valid,
                "error": error,
                "calls": received,
            }
        )
        if args.progress_file:
            with open(args.progress_file, "a", encoding="utf-8") as progress:
                progress.write(json.dumps(summary[-1], ensure_ascii=False) + "\n")
    valid_count = sum(item["valid"] for item in summary)
    print(
        json.dumps(
            {
                "model": settings.model_id,
                "thinking": args.thinking,
                "runs": summary,
                "valid_count": valid_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="探测真实模型是否稳定生成标准 unified diff")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--progress-file")
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 100:
        parser.error("--runs 必须在 1 到 100 之间")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
