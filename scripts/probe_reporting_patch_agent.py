"""使用真实 Reporting Coding Agent 探测 free-form Python 源码签发。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))

from agno.run import RunContext  # noqa: E402 - 直接执行脚本时必须先定位 worktree 根目录

from smart_reporting.reporting.agent import (  # noqa: E402 - 同上
    _report_model,
    create_reporting_code_agent,
)
from smart_reporting.reporting.model_policy import (  # noqa: E402 - 同上
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
)
from smart_reporting.reporting.models import ReportingError  # noqa: E402 - 同上
from smart_reporting.reporting.phase import (  # noqa: E402 - 同上
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    bind_reporting_run_context,
)
from smart_reporting.reporting.tools.analysis_item import (  # noqa: E402 - 同上
    validate_reporting_python_source,
)
from smart_reporting.reporting.workflow.checkpoint import FileIdentity  # noqa: E402 - 同上
from smart_reporting.reporting.workflow.runtime.code_generation import (  # noqa: E402 - 同上
    ReportingCodeGenerationRunner,
)
from smart_reporting.runtime.settings import AgentSettings  # noqa: E402 - 同上
from smart_reporting.task_execution import abuild_workspace_changes  # noqa: E402 - 同上
from smart_reporting.workspace import WorkspaceError, WorkspaceService  # noqa: E402 - 同上

ANALYSIS_MAX_BYTES = 128 * 1024
VISUALIZATION_MAX_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ProbeScenario:
    name: str
    task_kind: Literal["analysis_item", "visualization_section"]
    operation: Literal["create", "update"]
    path: str
    initial_source: str | None
    facts: Mapping[str, Any]
    diagnostic: Mapping[str, Any] | None = None

    @property
    def visualization(self) -> bool:
        return self.task_kind == "visualization_section"

    @property
    def max_bytes(self) -> int:
        return VISUALIZATION_MAX_BYTES if self.visualization else ANALYSIS_MAX_BYTES


@dataclass(frozen=True, slots=True)
class ProbeWorkspace:
    """仅向 patch builder 暴露当前签发脚本的可信原文。"""

    path: str
    content: str | None

    @staticmethod
    def normalize_path(path: str, *, allow_root: bool) -> tuple[str, str]:
        return WorkspaceService.normalize_path(path, allow_root=allow_root)

    async def aread_text(self, _thread: str, path: str) -> str:
        if path != self.path or self.content is None:
            raise WorkspaceError("探针工作区不包含请求的签发脚本。")
        return self.content


def _scenarios() -> tuple[ProbeScenario, ...]:
    analysis_repair_source = (
        "from pathlib import Path\n"
        "\n"
        "value = 1\n"
        'output_path = Path("analysis/output/probe_analysis.json")\n'
        'output_path.write_text(str(value), encoding="utf-8")\n'
    )
    visualization_repair_source = (
        "import matplotlib\n"
        'matplotlib.use("Agg")\n'
        "import matplotlib.pyplot as plt\n"
        "\n"
        "values = [1, 2, 3]\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot(values)\n"
        'fig.savefig("analysis/charts/probe_visualization.png")\n'
        "plt.close(fig)\n"
    )
    return (
        ProbeScenario(
            name="analysis_create",
            task_kind="analysis_item",
            operation="create",
            path="analysis/evidence/probe_analysis_create.py",
            initial_source=None,
            facts={
                "task": "创建确定性的多行 Python 分析脚本。",
                "scriptPath": "analysis/evidence/probe_analysis_create.py",
                "evidencePath": "analysis/output/probe_analysis_create.json",
                "requirements": [
                    "脚本必须是可编译的 Python，并将一个简单 JSON 对象写入 evidencePath。",
                    "不得执行网络请求或动态代码。",
                ],
            },
        ),
        ProbeScenario(
            name="analysis_repair",
            task_kind="analysis_item",
            operation="update",
            path="analysis/evidence/probe_analysis_repair.py",
            initial_source=analysis_repair_source,
            facts={
                "task": "修复签发脚本，把 value 从 1 调整为 2，并保留输出行为。",
                "scriptPath": "analysis/evidence/probe_analysis_repair.py",
            },
            diagnostic={
                "code": "probe_analysis_value_stale",
                "message": "分析值应更新为 2。",
                "details": {"path": "analysis/evidence/probe_analysis_repair.py"},
            },
        ),
        ProbeScenario(
            name="visualization_create",
            task_kind="visualization_section",
            operation="create",
            path="analysis/charts/probe_visualization_create.py",
            initial_source=None,
            facts={
                "task": "创建确定性的 Matplotlib 折线图脚本。",
                "visualizationWorkspace": {
                    "scriptPath": "analysis/charts/probe_visualization_create.py",
                    "chartPath": "analysis/charts/probe_visualization_create.png",
                },
                "values": [1, 3, 2, 4],
                "requirements": [
                    "先导入 matplotlib 并调用 matplotlib.use('Agg')，再导入 pyplot。",
                    "使用 fig.savefig 写入 chartPath。",
                ],
            },
        ),
        ProbeScenario(
            name="visualization_repair",
            task_kind="visualization_section",
            operation="update",
            path="analysis/charts/probe_visualization_repair.py",
            initial_source=visualization_repair_source,
            facts={
                "task": "修复签发图表脚本，为折线添加 marker='o' 并保留签发输出路径。",
                "visualizationWorkspace": {
                    "scriptPath": "analysis/charts/probe_visualization_repair.py",
                    "chartPath": "analysis/charts/probe_visualization.png",
                },
            },
            diagnostic={
                "code": "probe_visual_marker_missing",
                "message": "折线缺少 marker='o'。",
                "details": {"path": "analysis/charts/probe_visualization_repair.py"},
            },
        ),
    )


def _source_metrics(scenario: ProbeScenario, source: str) -> dict[str, Any]:
    metrics = validate_reporting_python_source(
        path=scenario.path,
        content=source,
        max_bytes=scenario.max_bytes,
        visualization=scenario.visualization,
    )
    lines = source.splitlines()
    return {
        "operation": scenario.operation,
        "path": scenario.path,
        "size": metrics["sizeBytes"],
        "lineCount": metrics["sourceLineCount"],
        "maxLineLength": max(
            (len(line.encode("utf-8")) for line in lines),
            default=0,
        ),
        "sha256": metrics["sha256"],
    }


def _run_context(
    scenario: ProbeScenario,
    *,
    model_id: str,
    thinking: bool,
    thinking_budget: int,
) -> RunContext:
    binding: dict[str, Any] = {
        "externalRunId": f"probe-{scenario.name}",
        "threadId": f"probe-thread-{scenario.name}",
        "sandboxId": f"probe-sandbox-{scenario.name}",
        "leaseOwner": "reporting-source-probe",
        "leaseEpoch": 1,
        "attemptNo": 1,
        REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
        REPORTING_TASK_KIND_DEPENDENCY_KEY: scenario.task_kind,
        REPORTING_MODEL_TIER_DEPENDENCY_KEY: "standard",
        REPORTING_MODEL_ID_DEPENDENCY_KEY: model_id,
        REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "high" if thinking else "off",
    }
    if thinking:
        binding[REPORTING_THINKING_BUDGET_DEPENDENCY_KEY] = thinking_budget
    return RunContext(
        run_id=f"probe-run-{scenario.name}",
        session_id=f"probe-session-{scenario.name}",
        user_id="reporting-source-probe",
        session_state={},
        dependencies={REPORTING_TASK_DEPENDENCY: binding},
    )


def _model(settings: AgentSettings, *, thinking: bool) -> Any:
    model = _report_model(
        settings,
        enable_thinking=thinking,
        retries=0,
        timeout_seconds=settings.model_timeout_seconds,
    )
    profile = (
        ReportingThinkingProfile.on(
            reasoning_effort="high",
            thinking_budget=settings.report_phase_thinking_budget,
            temperature=settings.report_phase_temperature,
        )
        if thinking
        else ReportingThinkingProfile.off(temperature=0.0)
    )
    model.max_tokens = min(settings.report_output_token_reserve, 8192)
    return apply_reporting_thinking_profile(model, profile)


def _short_error(error: BaseException) -> str:
    if isinstance(error, ReportingError):
        message = " ".join(error.message.split())[:160]
        return f"{error.code}: {message}"
    return type(error).__name__


async def _probe_once(
    settings: AgentSettings,
    scenario: ProbeScenario,
    *,
    thinking: bool,
    task_timeout: int,
) -> dict[str, Any]:
    model = _model(settings, thinking=thinking)
    model_id = str(model.id)
    context = _run_context(
        scenario,
        model_id=model_id,
        thinking=thinking,
        thinking_budget=settings.report_phase_thinking_budget,
    )
    workspace = ProbeWorkspace(scenario.path, scenario.initial_source)
    accepted: dict[str, Any] | None = None

    async def apply_patch(*, patch: str, **_kwargs: Any) -> dict[str, Any]:
        nonlocal accepted
        try:
            changes = await abuild_workspace_changes(workspace, "probe", patch)
            if len(changes) != 1:
                raise ReportingError(
                    "probe_source_change_invalid",
                    "源码提交必须只包含一个文件操作。",
                )
            change = changes[0]
            source = change.get("content")
            if (
                change.get("operation") != scenario.operation
                or change.get("path") != scenario.path
                or not isinstance(source, str)
            ):
                raise ReportingError(
                    "probe_source_change_invalid",
                    "源码提交必须是签发路径上的单一 create 或 update。",
                )
            accepted = _source_metrics(scenario, source)
            return {
                "ok": True,
                "artifacts": [
                    {
                        "path": accepted["path"],
                        "size": accepted["size"],
                        "sha256": accepted["sha256"],
                    }
                ],
            }
        except ReportingError as error:
            return {"ok": False, "code": error.code, "message": error.message}
        except WorkspaceError:
            return {
                "ok": False,
                "code": "probe_source_patch_invalid",
                "message": "源码提交无法构造为受控工作区变更。",
            }

    async def read_file(*, path: str, max_bytes: int, **_kwargs: Any) -> dict[str, Any]:
        source = scenario.initial_source
        if path != scenario.path or source is None:
            return {
                "ok": False,
                "code": "probe_source_read_invalid",
                "message": "只能读取当前签发脚本。",
            }
        raw = source.encode("utf-8")
        if len(raw) > max_bytes:
            return {
                "ok": False,
                "code": "probe_source_read_too_large",
                "message": "签发脚本超过读取上限。",
            }
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "ok": True,
            "path": scenario.path,
            "content": source,
            "sha256": digest,
            "offset": 0,
            "nextOffset": len(raw),
            "totalBytes": len(raw),
            "hasMore": False,
            "outputTruncated": False,
        }

    runner = ReportingCodeGenerationRunner(
        agent_factory=lambda: create_reporting_code_agent(
            model=model,
            name=f"probe-{scenario.name}-code",
            instructions=[
                "严格使用任务事实中的签发路径；不要推导或修改其他路径。",
                "只生成脚本源码，探针不会执行生成代码。",
            ],
        )
    )

    async def invoke() -> None:
        if scenario.operation == "create":
            await runner.generate(
                scenario.path,
                scenario.facts,
                apply_patch,
                context,
                max_source_bytes=scenario.max_bytes,
            )
            return
        initial_source = scenario.initial_source
        if initial_source is None or scenario.diagnostic is None:
            raise RuntimeError("repair scenario is incomplete")
        raw = initial_source.encode("utf-8")
        await runner.repair(
            FileIdentity(
                path=scenario.path,
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            ),
            scenario.diagnostic,
            read_file,
            apply_patch,
            context,
            task_facts=scenario.facts,
            max_source_bytes=scenario.max_bytes,
        )

    started = time.perf_counter()
    error: str | None = None
    try:
        with bind_reporting_run_context(context):
            await asyncio.wait_for(invoke(), timeout=task_timeout)
    except TimeoutError:
        error = f"task_timeout: exceeded {task_timeout} seconds"
    except Exception as exc:  # noqa: BLE001 - 探针只输出去敏后的短错误。
        error = _short_error(exc)
    elapsed = round(time.perf_counter() - started, 2)
    return {
        "model": model_id,
        "scenario": scenario.name,
        "valid": error is None and accepted is not None,
        "operation": accepted.get("operation") if accepted else scenario.operation,
        "path": accepted.get("path") if accepted else scenario.path,
        "size": accepted.get("size") if accepted else None,
        "lineCount": accepted.get("lineCount") if accepted else None,
        "maxLineLength": accepted.get("maxLineLength") if accepted else None,
        "sha256": accepted.get("sha256") if accepted else None,
        "seconds": elapsed,
        "error": error,
    }


def _emit(record: Mapping[str, Any], progress_file: str | None) -> None:
    line = json.dumps(dict(record), ensure_ascii=False, separators=(",", ":"))
    print(line, flush=True)
    if progress_file:
        with open(progress_file, "a", encoding="utf-8") as progress:
            progress.write(line + "\n")


async def _run(args: argparse.Namespace) -> None:
    os.environ["AGENT_ENV_FILE"] = args.env_file
    settings = AgentSettings.from_environment()
    for _repetition in range(args.repetitions):
        for scenario in _scenarios():
            record = await _probe_once(
                settings,
                scenario,
                thinking=args.thinking,
                task_timeout=args.task_timeout,
            )
            _emit(record, args.progress_file)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="用真实 Reporting 模型探测 free-form Python 源码签发协议"
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--task-timeout", type=int, default=180)
    parser.add_argument("--progress-file")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 100:
        parser.error("--repetitions 必须在 1 到 100 之间")
    if not 1 <= args.task_timeout <= 3600:
        parser.error("--task-timeout 必须在 1 到 3600 之间")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
