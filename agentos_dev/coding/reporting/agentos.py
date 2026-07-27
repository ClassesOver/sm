"""独立 Report AgentOS 装配。"""

from contextlib import asynccontextmanager

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from fastapi import FastAPI

from ...settings import AgentSettings
from ...skills import SkillValidatorRegistry
from .. import AgnoCodingExecutor, CodingTaskSupervisor
from ..cli import _close_cli_resources, create_cli_agent, create_cli_context
from ..execution import CodingExecutionKernel
from .agent import create_report_agent, create_report_worker
from .binding import TemporarySourceBindingService
from .controller import ReportWorkflowController
from .credentials import TemporaryCredentialStore
from .data_sources import ReportDataSourceToolkit
from .instructions import build_report_agent_instructions
from .runtime import ReportWorkflowRuntime
from .starrocks import create_starrocks_client


def create_agentos(settings: AgentSettings | None = None) -> AgentOS:
    current_settings = settings or AgentSettings.from_environment()
    context = create_cli_context(current_settings)
    coding_worker = create_cli_agent(context)
    report_worker = create_report_worker(
        coding_worker,
        context.workspace_service,
        context.coding_repository,
        instructions=build_report_agent_instructions,
        context_token_budget=current_settings.context_token_budget,
        output_token_reserve=current_settings.output_token_reserve,
    )
    credentials = TemporaryCredentialStore()
    bindings = TemporarySourceBindingService(
        credentials,
        create_starrocks_client,
        network_allowlist=current_settings.report_source_network_allow_list,
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
        config_path=current_settings.report_data_sources_file,
        excluded_database_url=current_settings.database_url,
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
    facade = create_report_agent(report_worker, controller)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            credentials.close_all()
            await _close_cli_resources(context, facade, report_worker, coding_worker)

    return AgentOS(
        name="Report AgentOS",
        agents=[facade],
        interfaces=[AGUI(agent=facade)],
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
