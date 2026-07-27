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
from .agui import REPORT_SOURCE_INTAKE_DEPENDENCY
from .binding import TemporarySourceBindingService
from .controller import REPORT_WORKFLOW_SCOPE_DEPENDENCY, ReportWorkflowController
from .credentials import TemporaryCredentialStore
from .data_sources import ReportDataSourceToolkit
from .instructions import build_report_agent_instructions
from .intake import ReportIntakeService
from .models import ReportingError
from .runtime import ReportWorkflowRuntime
from .starrocks import create_starrocks_client


def read_report_request(*, read: Callable[[str], str] = input) -> str:
    lines: list[str] = []
    while True:
        line = read("" if lines else "报表目标、连接块和 DDL（单独输入 /run 提交）:\n")
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
    raw = read_report_request(read=read)
    parsed = ReportIntakeService().parse(raw)
    if parsed.source_request is None or not parsed.ddl_tables:
        raise ReportingError(
            "source_connection_incomplete",
            "Report CLI 当前必须同时提供临时 StarRocks 连接块和目标表 DDL。",
        )

    context = create_cli_context(settings)
    credentials = TemporaryCredentialStore()
    bindings = TemporarySourceBindingService(
        credentials,
        create_starrocks_client,
        network_allowlist=context.settings.report_source_network_allow_list,
    )
    session_id = f"cli-report-{uuid4().hex}"
    confirmation = bindings.prepare(
        parsed,
        user_id="cli",
        thread_id=session_id,
        session_id=session_id,
    )
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
    data_sources = ReportDataSourceToolkit(
        context.workspace_service,
        config_path=context.settings.report_data_sources_file,
        excluded_database_url=context.settings.database_url,
        temporary_source_bindings=bindings,
        temporary_report_credentials=credentials,
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        supervisor=supervisor,
        workspace_service=context.workspace_service,
        binding_service=bindings,
        credentials=credentials,
        client_factory=create_starrocks_client,
        data_sources=data_sources,
    )
    controller = ReportWorkflowController(
        runtime.workflow,
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
            REPORT_SOURCE_INTAKE_DEPENDENCY: {
                "confirmationId": confirmation.confirmation_id,
                "sourceMode": "temporary_database",
                "sourceType": "starrocks",
                "endpoint": confirmation.endpoint,
                "database": confirmation.database,
                "ddlTables": list(parsed.ddl_tables),
                "metadataFingerprint": parsed.metadata_fingerprint,
                "expiresAt": confirmation.expires_at.isoformat(),
                "requiresConfirmation": True,
            },
        },
    )
    adapter = CliReviewAdapter(read=read, write=write)
    try:
        result = await controller.start(parsed.sanitized_text, None, run_context)
        while result.get("status") == "paused":
            action, feedback = adapter.review_action(result.get("review") or {})
            if action == "approve":
                result = await controller.approve(run_context)
            elif action == "reject":
                assert feedback is not None
                result = await controller.reject(feedback, run_context)
            else:
                result = await controller.cancel(run_context)
        write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        credentials.close_session(user_id="cli", thread_id=session_id, session_id=session_id)
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
