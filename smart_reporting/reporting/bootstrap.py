"""Reporting Worker、Workflow Runtime 和执行依赖的协议无关装配。"""

from agno.agent import Agent

from ..execution_context import ExecutionContext
from ..settings import AgentSettings
from ..task_execution import TaskExecutionRepository
from ..task_execution.execution import TaskExecutionKernel
from .agent import create_report_worker
from .data_source import load_configured_report_source_registry
from .delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
)
from .metadata import ReportingMetadataClient
from .profile import load_configured_reporting_profiles
from .workflow.execution import ReportTaskRunner, WorkerEventSink
from .workflow.repository import ReportingStateRepository
from .workflow.runtime import ReportWorkflowRuntime


def create_report_runtime(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
    artifact_persistence: ReportArtifactPersistenceService | None = None,
    worker_event_sink: WorkerEventSink | None = None,
) -> tuple[Agent, ReportWorkflowRuntime]:
    task_repository = TaskExecutionRepository(context.database)
    state_repository = ReportingStateRepository(context.database)
    report_worker = create_report_worker(
        settings,
        context.database,
        context.workspace_service,
        task_repository,
        state_repository=state_repository,
    )
    task_runner = ReportTaskRunner(
        task_repository,
        report_worker,
        TaskExecutionKernel(context.workspace_service, task_repository),
        event_sink=worker_event_sink,
        idle_timeout_seconds=settings.model_timeout_seconds,
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        report_worker=report_worker,
        task_runner=task_runner,
        workspace_service=context.workspace_service,
        registry=load_configured_report_source_registry(settings.report_data_sources_dir),
        profiles=load_configured_reporting_profiles(settings.report_data_sources_dir),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
        metadata_client=(
            ReportingMetadataClient(
                settings.report_metadata_url,
                token=settings.report_metadata_token,
            )
            if settings.report_metadata_url
            else None
        ),
        download_grants=download_grants,
        artifact_persistence=artifact_persistence,
        state_repository=state_repository,
        analysis_concurrency=settings.report_analysis_concurrency,
        section_concurrency=settings.report_section_concurrency,
    )
    return report_worker, runtime
