"""独立智能报表 CLI。"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from uuid import uuid4

from agno.run import RunContext

from ...async_utils import complete_cleanup
from ...settings import AgentSettings
from ...skills import SkillValidatorRegistry
from .. import AgnoCodingExecutor, CodingTaskSupervisor
from ..cli import _close_cli_resources, create_cli_agent, create_cli_context
from ..execution import CodingExecutionKernel
from .adapters import CliReviewAdapter
from .agent import create_report_worker
from .controller import REPORT_WORKFLOW_SCOPE_DEPENDENCY, ReportWorkflowController
from .data_source import load_configured_report_source_registry
from .entrypoints import parse_cli_envelope
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
    context = create_cli_context(settings)
    session_id = f"cli-report-{uuid4().hex}"
    coding_agent = create_cli_agent(context)
    report_worker = create_report_worker(
        coding_agent,
        context.workspace_service,
        context.coding_repository,
        instructions=build_report_agent_instructions,
        context_token_budget=context.settings.context_token_budget,
        output_token_reserve=context.settings.output_token_reserve,
    )
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: report_worker),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
        validator_registry=SkillValidatorRegistry.from_skills(report_worker.skills),
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        supervisor=supervisor,
        workspace_service=context.workspace_service,
        registry=load_configured_report_source_registry(context.settings.report_data_sources_dir),
        profiles=load_configured_reporting_profiles(context.settings.report_data_sources_dir),
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
        runtime.workflow,
        cancel_cleanup=runtime.cleanup_cancelled,
        publication_issuer=runtime.issue_cli_publication,
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
        await complete_cleanup(_close_cli_resources(context, report_worker, coding_agent))


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
