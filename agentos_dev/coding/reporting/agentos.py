"""独立 Report AgentOS 装配。"""

from contextlib import asynccontextmanager

from agno.agent import Agent
from agno.os import AgentOS
from fastapi import FastAPI

from ...settings import AgentSettings
from ...skills import SkillValidatorRegistry
from .. import AgnoCodingExecutor, CodingTaskSupervisor
from ..cli import CliContext, _close_cli_resources, create_cli_agent, create_cli_context
from ..execution import CodingExecutionKernel
from .agent import create_report_agent, create_report_worker
from .controller import ReportWorkflowController
from .data_source import load_configured_report_source_registry
from .instructions import build_report_agent_instructions
from .interface import ReportAGUI
from .metadata import ReportingMetadataClient
from .runtime import ReportWorkflowRuntime


def create_report_agentos_components(
    context: CliContext,
    coding_worker: Agent,
    settings: AgentSettings,
) -> tuple[Agent, Agent]:
    report_worker = create_report_worker(
        coding_worker,
        context.workspace_service,
        context.coding_repository,
        instructions=build_report_agent_instructions,
        context_token_budget=settings.context_token_budget,
        output_token_reserve=settings.output_token_reserve,
    )
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: report_worker),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
        validator_registry=SkillValidatorRegistry.from_skills(report_worker.skills),
    )
    registry = load_configured_report_source_registry(settings.report_data_sources_dir)
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        supervisor=supervisor,
        workspace_service=context.workspace_service,
        registry=registry,
        metadata_client=(
            ReportingMetadataClient(
                settings.report_metadata_url,
                token=settings.report_metadata_token,
            )
            if settings.report_metadata_url
            else None
        ),
    )
    controller = ReportWorkflowController(
        runtime.workflow,
        cancel_cleanup=runtime.cleanup_cancelled,
    )
    return create_report_agent(report_worker, controller), report_worker


def create_agentos(settings: AgentSettings | None = None) -> AgentOS:
    current_settings = settings or AgentSettings.from_environment()
    context = create_cli_context(current_settings)
    coding_worker = create_cli_agent(context)
    facade, report_worker = create_report_agentos_components(
        context, coding_worker, current_settings
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            await _close_cli_resources(context, facade, report_worker, coding_worker)

    return AgentOS(
        name="Report AgentOS",
        agents=[facade],
        interfaces=[ReportAGUI(agent=facade)],
        db=context.database,
        cors_allowed_origins=list(current_settings.cors_allowed_origins),
        lifespan=lifespan,
    )


def main() -> None:
    settings = AgentSettings.from_environment()
    agent_os = create_agentos(settings)
    agent_os.serve(
        app=agent_os.get_app(),
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
