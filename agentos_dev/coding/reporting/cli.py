"""独立智能报表 CLI。"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from uuid import uuid4

from agno.run import RunContext

from ...async_utils import complete_cleanup
from ...execution_context import close_execution_resources, create_execution_context
from ...settings import AgentSettings
from ...task_execution import TaskExecutionRepository
from ...task_execution.execution import TaskExecutionKernel
from .adapters import CliReviewAdapter
from .agent import create_report_worker
from .controller import REPORT_WORKFLOW_SCOPE_DEPENDENCY, ReportWorkflowController
from .data_source import load_configured_report_source_registry
from .entrypoints import parse_cli_envelope
from .execution import ReportTaskRunner
from .instructions import build_report_agent_instructions
from .metadata import ReportingMetadataClient
from .profile import load_configured_reporting_profiles
from .runtime import ReportWorkflowRuntime


def read_report_request(*, read: Callable[[str], str] = input) -> str:
    lines: list[str] = []
    while True:
        line = read("" if lines else "ReportRequestEnvelope JSON（单独输入 /run 提交）:\n")
        if line.strip() == "/run":
            break
        lines.append(line)
    value = "\n".join(lines).strip()
    if not value:
        raise ValueError("报表请求不能为空。")
    return value


async def run_cli(
    *,
    settings: AgentSettings | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> None:
    envelope = parse_cli_envelope(read_report_request(read=read))
    context = create_execution_context(settings)
    task_repository = TaskExecutionRepository(context.database)
    session_id = f"cli-report-{uuid4().hex}"
    report_worker = create_report_worker(
        context.settings,
        context.database,
        context.workspace_service,
        task_repository,
        instructions=build_report_agent_instructions,
        report_coding_enable_thinking=context.settings.report_coding_enable_thinking,
        report_enable_vision=context.settings.report_enable_vision,
        context_token_budget=context.settings.report_context_token_budget,
        output_token_reserve=context.settings.report_output_token_reserve,
    )
    task_runner = ReportTaskRunner(
        task_repository,
        report_worker,
        TaskExecutionKernel(context.workspace_service, task_repository),
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        task_runner=task_runner,
        workspace_service=context.workspace_service,
        registry=load_configured_report_source_registry(context.settings.report_data_sources_dir),
        profiles=load_configured_reporting_profiles(context.settings.report_data_sources_dir),
        planner_enable_thinking=context.settings.report_enable_thinking,
        metadata_client=(
            ReportingMetadataClient(
                context.settings.report_metadata_url,
                token=context.settings.report_metadata_token,
            )
            if context.settings.report_metadata_url
            else None
        ),
    )
    controller = ReportWorkflowController(
        lambda: runtime.workflow(publication_issuer=runtime.issue_cli_publication),
        cancel_cleanup=runtime.cleanup_cancelled,
    )
    external_run_id = uuid4().hex
    run_context = RunContext(
        run_id=external_run_id,
        session_id=session_id,
        user_id="cli",
        session_state={},
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"externalRunId": external_run_id},
        },
    )
    adapter = CliReviewAdapter(read=read, write=write)
    try:
        result = await controller.start(envelope, run_context)
        while result.get("status") == "paused":
            action, feedback = adapter.review_action(result.get("review") or {})
            if action == "approve":
                result = await controller.approve(run_context)
            elif action == "select_agent":
                assert feedback is not None
                result = await controller.select_agent(feedback, run_context)
            elif action == "reject":
                assert feedback is not None
                result = await controller.reject(feedback, run_context)
            else:
                result = await controller.cancel(run_context)
        write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await complete_cleanup(close_execution_resources(context, report_worker))


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments:
            raise SystemExit("用法: python -m agentos_dev.coding.reporting.cli")
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
