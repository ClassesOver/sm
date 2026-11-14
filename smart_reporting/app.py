from contextlib import nullcontext
from os import getenv
from pathlib import Path

from agno.os.config import MCPConfig
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger as loguru_logger
from starlette.concurrency import run_in_threadpool

from .context_management import validate_configured_tiktoken_cache
from .http.identity import (
    requires_workspace_capability,
    verified_report_request,
)
from .http.request_limits import (
    RequestBodyLimitError,
    agentos_run_request_limit,
    business_document_upload_request_limit,
    install_streaming_body_limit,
    is_agentos_run_create,
    native_import_request_limit,
    read_limited_body,
    report_editor_write_request_limit,
    request_body_limit_error,
    validate_agentos_run_multipart,
)
from .http.security import CapabilityError, verify_capability
from .integrations.agno_function_arguments import install_agno_function_argument_decoder
from .integrations.dingyi_process import DingyiProcessAdapter, mount_process_routes
from .management.api import create_management_router
from .management.auth import AdminAuthService
from .management.business_documents import BusinessDocumentService
from .management.business_documents_api import create_business_documents_router
from .management.business_evidence import BusinessEvidenceService
from .management.business_evidence_api import create_business_evidence_router
from .management.business_ingestion_worker import BusinessIngestionWorker
from .management.catalog_api import create_catalog_router
from .management.data_sources.api import create_source_router
from .management.data_sources.secrets import CredentialVault
from .management.import_api import create_import_router
from .management.metrics import MetricService
from .management.metrics_api import create_metrics_router
from .management.profile_api import create_profile_router
from .management.repository import AdminRepository
from .management.settings import ManagementSettings
from .management.statistical_policies import StatisticalPolicyService
from .management.statistical_policy_api import create_statistical_policy_router
from .management.table_access_api import create_table_access_router
from .management.version_options import create_version_options_router
from .quality_warnings.api import create_quality_warning_router
from .quality_warnings.repository import SqlAlchemyQualityWarningRepository
from .quality_warnings.service import QualityWarningService
from .report_editor import (
    ReportEditorGrantService,
    ReportEditorService,
    ReportSlidesEditorService,
    ReportSlidesImageService,
    ReportWorkbookEditorService,
    SqlAlchemyReportEditorRepository,
    create_report_editor_ai_service,
    create_report_editor_chart_ai_service,
    create_report_editor_router,
    create_report_editor_table_ai_service,
    create_report_slides_ai_service,
    create_report_slides_editor_router,
    create_report_workbook_ai_service,
    create_report_workbook_editor_router,
)
from .report_editor.data_revisions import ReportDataRevisionService
from .report_editor.design_repository import SqlAlchemyDesignTemplateRepository
from .report_editor.native import NativeEditorService
from .report_editor.native_ai import create_native_ai_service
from .report_editor.native_ai_api import create_native_ai_router
from .report_editor.native_pdf_ai import create_native_pdf_read_planner
from .report_editor.native_pdf_ai_tasks import NativePDFReadService
from .report_editor.native_office_read_tasks import NativeOfficeReadService
from .report_editor.native_slides_read_ai import AgnoNativeSlidesReadPlanner
from .report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner
from .report_editor.native_word_read_ai import AgnoNativeWordReadPlanner
from .report_editor.native_word_read_tasks import NativeWordReadService
from .report_editor.native_pdf_review_ai import create_native_pdf_review_planner
from .report_editor.native_pdf_review_ai_tasks import NativePDFReviewService
from .report_editor.native_pdf_review_ai_api import create_native_pdf_review_ai_router
from .report_editor.native_pdf_form_ai import AgnoNativePDFFormPlanner
from .report_editor.native_pdf_form_ai_tasks import NativePDFFormService
from .report_editor.native_pdf_form_ai_api import create_native_pdf_form_ai_router
from .report_editor.slides_native_ai import create_native_slides_ai_service
from .report_editor.slides_native_ai_api import create_native_slides_ai_router
from .report_editor.workbook_native_ai import create_native_workbook_ai_service
from .report_editor.workbook_native_ai_api import create_native_workbook_ai_router
from .report_editor.native_api import create_native_editor_router
from .report_editor.native_import import NativeImportService
from .report_editor.native_import_api import create_native_import_router
from .report_editor.native_publication import NativePublicationService
from .report_editor.native_readiness import native_readiness_checks
from .report_editor.native_repository import NativeDocumentRepository
from .report_editor.slides_chart_ai import ReportSlidesChartAIService
from .reporting.agent import create_report_agent
from .reporting.bootstrap import create_report_runtime
from .reporting.business_knowledge.originals import BusinessOriginalStore
from .reporting.code_agent.lsp_process import ReportingLspProcessManager
from .reporting.code_mode import create_reporting_code_mode_runtime
from .reporting.data_source.starrocks import StarRocksSourceConfig
from .reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
    create_report_download_router,
    install_report_download_access_log_filter,
)
from .reporting.diagnostics import (
    ReportingDependencyDiagnostics,
    create_reporting_dependency_diagnostics_router,
)
from .reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from .reporting.metadata import ReportingMetadataClient
from .reporting.workflow.controller import ReportWorkflowController
from .reporting.workflow.repository import REPORTING_DB_SCHEMA
from .reporting.workflow.runtime.standard_chart_proof import configure_render_proof_signing
from .reporting_mcp.identity import CapabilityTokenVerifier
from .runtime.application import ApplicationContext, create_agentos_app
from .runtime.database import check_database, create_agent_database
from .runtime.execution import ExecutionContext, configure_execution_tracing
from .runtime.logging import configure_application_logging, configure_file_logging
from .runtime.settings import AgentSettings
from .runtime.system_configuration import load_system_configuration
from .task_execution import DEFAULT_TERMINAL_TIMEOUT

install_agno_function_argument_decoder()
system_configuration = load_system_configuration(AgentSettings.from_environment())
settings = system_configuration.settings
configure_application_logging(debug=settings.debug)
configure_file_logging(
    settings.log_file_path,
    debug=settings.debug,
    max_bytes=settings.log_file_max_bytes,
    backup_count=settings.log_file_backup_count,
)
validate_configured_tiktoken_cache()
agent_database = create_agent_database(settings.database_url)
configure_execution_tracing(agent_database, settings)
reporting_workspace_registry = ReportingWorkspaceRegistry(
    settings.reporting_host_workspace_root,
    secret=settings.workspace_hmac_secret,
)
native_workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(
    Path(settings.reporting_host_workspace_root) / "native",
    secret=settings.workspace_hmac_secret,
))
# 标准渲染证明签名复用工作区密钥（按用途派生子密钥），使模板演进后旧证明仍可核验。
configure_render_proof_signing(settings.workspace_hmac_secret)
reporting_code_mode_runtime = create_reporting_code_mode_runtime(
    reporting_workspace_registry.root,
    analysis_concurrency=settings.report_analysis_concurrency,
    section_concurrency=settings.report_section_concurrency,
    timeout=DEFAULT_TERMINAL_TIMEOUT,
)
reporting_lsp_process_manager = ReportingLspProcessManager()
report_download_repository = SqlAlchemyDownloadGrantRepository(agent_database.async_engine)
report_editor_repository = SqlAlchemyReportEditorRepository(agent_database.async_engine)
native_document_repository = NativeDocumentRepository(agent_database.async_engine)
report_editor_grants = ReportEditorGrantService(
    report_editor_repository,
    secret=settings.workspace_hmac_secret,
)
quality_warning_repository = SqlAlchemyQualityWarningRepository(agent_database.async_engine)
quality_warning_service = QualityWarningService(quality_warning_repository)
report_artifact_repository = SqlAlchemyReportArtifactRepository(agent_database.async_engine)
report_download_grants = ReportDownloadGrantService(report_download_repository)
# 报告产物读取依赖 Reporting 宿主机工作区的有界读取接口。
report_artifact_persistence = ReportArtifactPersistenceService(
    report_artifact_repository,
    ReportingWorkspaceRouter(reporting_workspace_registry),
)
report_downloads = ReportDownloadHttpService(
    report_download_grants,
    report_artifact_repository,
    workspace_service=ReportingWorkspaceRouter(reporting_workspace_registry),
)
native_artifact_persistence = ReportArtifactPersistenceService(
    report_artifact_repository, native_workspace,
)
native_downloads = ReportDownloadHttpService(
    report_download_grants, report_artifact_repository, workspace_service=native_workspace,
)
router = APIRouter()


async def _log_reporting_runtime_identity() -> None:
    """记录实际启动的 Reporting 版本和数据库边界，便于确认镜像是否已更新。"""

    loguru_logger.info(
        "reporting_runtime_started workflow_id={} build_id={} database_backend={} "
        "reporting_schema={} workers={}",
        "enterprise-reporting-workflow-v1",
        getenv("REPORTING_BUILD_ID", "unknown"),
        agent_database.backend,
        REPORTING_DB_SCHEMA,
        settings.workers,
    )


def _refresh_file_logging() -> None:
    """Uvicorn 初始化 named logger 后恢复文件日志绑定。"""

    configure_file_logging(
        settings.log_file_path,
        debug=settings.debug,
        max_bytes=settings.log_file_max_bytes,
        backup_count=settings.log_file_backup_count,
    )


def _application_context(request: Request) -> ApplicationContext:
    return request.app.state.agentos_context


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-Workspace-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if business_document_upload_request_limit(path, method):
        # 仅此上传入口在认证/CSRF后自行安装流式限制，不经过64KiB JSON缓冲。
        return None
    if path.startswith("/management/api/v1/") and method.upper() in {"POST", "PUT", "PATCH"}:
        return 64 * 1024
    return agentos_run_request_limit(path, method) or report_editor_write_request_limit(
        path, method
    )


async def require_workspace_capability(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    thread = _request_thread(request)
    capability = str(request.headers.get("X-Workspace-Capability", "")).strip()
    capability_required = requires_workspace_capability(
        path,
        has_thread=bool(thread),
        has_capability=bool(capability),
    )
    if capability_required:
        if not thread:
            return JSONResponse({"error": "thread_header_required"}, status_code=400)
        context = _application_context(request)
        try:
            request.state.capability = verify_capability(
                capability,
                context.settings.workspace_hmac_secret,
                thread,
            )
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=401)
    limit = _request_limit(path, request.method)
    import_limit = native_import_request_limit(path, request.method)
    if import_limit:
        try:
            install_streaming_body_limit(request, import_limit)
        except RequestBodyLimitError as error:
            return JSONResponse({"error": error.code}, status_code=error.status_code)
    body = await read_limited_body(request, limit) if limit else b""
    if body is None:
        return JSONResponse({"error": "request_too_large"}, status_code=413)
    if body and is_agentos_run_create(path, request.method):
        try:
            validate_agentos_run_multipart(request.headers.get("content-type", ""), body)
        except RequestBodyLimitError as error:
            return JSONResponse({"error": error.code}, status_code=error.status_code)
    # AgentOS 原生 run 表单允许调用方提交 user_id/session_id。这里用已验签的
    # Odoo 身份覆盖它们，避免合法 capability 被用于访问其他用户或 thread。
    identity_context = nullcontext()
    if capability_required:
        identity_context = verified_report_request(
            request,
            user_id=str(request.state.capability.user),
            thread_id=thread,
            database=request.state.capability.database,
            company_id=str(request.state.capability.company),
        )
    try:
        with identity_context:
            response = await call_next(request)
    except (RequestBodyLimitError, BaseExceptionGroup) as error:
        limit_error = request_body_limit_error(error)
        if limit_error is None:
            raise
        return JSONResponse({"error": limit_error.code}, status_code=limit_error.status_code)
    return response


def _readiness_checks(context: ApplicationContext):
    checks = {
        "postgresql": False,
        "hmac": len(context.settings.workspace_hmac_secret.encode("utf-8")) >= 32,
    }
    checks.update(native_readiness_checks(context.settings))
    try:
        check_database(context.database or context.settings.database_url)
        checks["postgresql"] = True
    except Exception:
        return checks
    return checks


@router.get("/ready", include_in_schema=False)
async def readiness(request: Request):
    checks = await run_in_threadpool(_readiness_checks, _application_context(request))
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )


reporting_metadata_client = (
    ReportingMetadataClient(settings.report_metadata_url, token=settings.report_metadata_token)
    if settings.report_metadata_url
    else None
)
reporting_agent_template, report_runtime = create_report_runtime(
    ExecutionContext(
        settings=settings,
        database=agent_database.async_db,
        trace_database=agent_database.sync_db,
        reporting_workspace_registry=reporting_workspace_registry,
        reporting_code_mode_runtime=reporting_code_mode_runtime,
        reporting_lsp_process_manager=reporting_lsp_process_manager,
    ),
    settings,
    download_grants=report_download_grants,
    editor_grants=report_editor_grants,
    artifact_persistence=report_artifact_persistence,
    quality_warning_service=quality_warning_service,
)
report_design_templates = SqlAlchemyDesignTemplateRepository(agent_database.async_engine)
report_editor = ReportEditorService(
    state_repository=report_runtime.state_repository,
    design_templates=report_design_templates,
    workspace_registry=reporting_workspace_registry,
    workspace=report_runtime.workspace_service,
    report_tools=report_runtime.report_tools,
    artifact_persistence=report_artifact_persistence,
    download_grants=report_download_grants,
    editor_grants=report_editor_grants,
    public_base_url=settings.report_public_base_url,
    export_timeout_seconds=settings.report_editor_export_timeout_seconds,
    report_basis_service=report_runtime.report_basis_service,
    business_evidence_service=report_runtime.business_evidence_service,
    recalculation_runtime=report_runtime,
    recalculation_database=agent_database.async_db,
    recalculation_durable=True,
    lineage_panel_enabled=settings.report_lineage_panel_enabled,
    lineage_download_enabled=settings.report_lineage_download_enabled,
    lineage_drilldown_enabled=settings.report_lineage_drilldown_enabled,
    lineage_export_sources_enabled=settings.report_lineage_export_sources_enabled,
)
native_publication = NativePublicationService(
    native_document_repository, native_workspace, report_download_grants, report_editor_grants,
    artifact_persistence=native_artifact_persistence,
    public_base_url=settings.report_public_base_url or "",
)
native_editor = NativeEditorService(
    native_workspace, native_document_repository, report_editor_grants,
    report_editor=report_editor, publication=native_publication,
    docx_enabled=settings.native_docx_enabled, pdf_enabled=settings.native_pdf_enabled,
    office_enabled=settings.native_upload_enabled,
    pdf_text_enabled=settings.native_pdf_text_enabled,
)
native_ai = create_native_ai_service(
    reporting_agent_template.model, native_editor, enabled=settings.native_ai_enabled,
)
native_slides_ai = create_native_slides_ai_service(
    reporting_agent_template.model, native_editor, enabled=settings.native_ai_enabled,
)
native_workbook_ai = create_native_workbook_ai_service(
    reporting_agent_template.model, native_editor, enabled=settings.native_ai_enabled,
)
native_pdf_read_ai = NativePDFReadService(
    native_editor, planner=create_native_pdf_read_planner(reporting_agent_template.model),
    enabled=settings.native_ai_enabled,
)
native_word_read_ai = NativeWordReadService(
    native_editor, planner=AgnoNativeWordReadPlanner(reporting_agent_template.model),
    enabled=settings.native_ai_enabled,
)
native_office_read_ai = NativeOfficeReadService(
    native_editor, planners={
        "xlsx": AgnoNativeWorkbookReadPlanner(reporting_agent_template.model),
        "pptx": AgnoNativeSlidesReadPlanner(reporting_agent_template.model),
    }, enabled=settings.native_ai_enabled,
)
native_pdf_review_ai = NativePDFReviewService(
    native_editor, planner=create_native_pdf_review_planner(reporting_agent_template.model),
    enabled=settings.native_ai_enabled,
)
native_pdf_form_ai = NativePDFFormService(
    native_editor, planner=AgnoNativePDFFormPlanner(reporting_agent_template.model),
    enabled=settings.native_ai_enabled,
)
native_import = NativeImportService(native_workspace, native_document_repository, report_editor_grants)
report_slides_editor = ReportSlidesEditorService(
    state_repository=report_runtime.state_repository,
    workspace_registry=reporting_workspace_registry,
    workspace=report_runtime.workspace_service,
    editor_grants=report_editor_grants,
    artifact_persistence=report_artifact_persistence,
    download_grants=report_download_grants,
    public_base_url=settings.report_public_base_url,
)
report_workbook_editor = ReportWorkbookEditorService(
    state_repository=report_runtime.state_repository,
    workspace_registry=reporting_workspace_registry,
    workspace=report_runtime.workspace_service,
    editor_grants=report_editor_grants,
    artifact_persistence=report_artifact_persistence,
    download_grants=report_download_grants,
    public_base_url=settings.report_public_base_url,
)
report_workbook_ai = create_report_workbook_ai_service(
    reporting_agent_template.model, report_workbook_editor
)
report_slides_ai = create_report_slides_ai_service(
    reporting_agent_template.model, report_slides_editor
)
report_slides_image_ai = ReportSlidesImageService(
    report_slides_editor,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    model=settings.report_slides_image_model,
)
report_editor_ai = create_report_editor_ai_service(reporting_agent_template.model)
# 编辑器 AI 改图（AGENT_REPORT_EDITOR_CHART_AI_ENABLED，默认开启）：与可视化章节复用
# 同一 code agent 工厂、CodeMode runtime、LSP、视觉审查与任务注册表；未配置
# 视觉审查模型时服务构造仍成功，可用性接口按 vision_missing 提示不可用。
report_editor_chart_ai = None
if settings.report_editor_chart_ai_enabled:
    from .reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner

    report_editor_chart_ai = create_report_editor_chart_ai_service(
        editor=report_editor,
        workspace_registry=reporting_workspace_registry,
        model=reporting_agent_template.model,
        runner=ReportingCodeGenerationRunner(
            report_runtime.visualization_code_agent_factory,
            reporting_code_mode_runtime,
            lsp_manager=reporting_lsp_process_manager,
            registry=report_runtime.coding_task_registry,
            vision_reviewer=report_runtime.vision_reviewer,
        ),
        hourly_limit=settings.report_editor_chart_ai_hourly_limit,
        timeout_seconds=float(settings.report_editor_chart_ai_timeout_seconds),
    )
report_slides_chart_ai = (
    ReportSlidesChartAIService(report_slides_editor, chart_ai=report_editor_chart_ai)
    if report_editor_chart_ai is not None else None
)
report_data_revisions = ReportDataRevisionService(editor=report_editor, chart_service=report_editor_chart_ai)
report_editor_table_ai = None
if settings.report_editor_table_ai_enabled:
    report_editor_table_ai = create_report_editor_table_ai_service(
        editor=report_editor,
        model=reporting_agent_template.model,
        hourly_limit=settings.report_editor_table_ai_hourly_limit,
        timeout_seconds=float(settings.report_editor_table_ai_timeout_seconds),
    )
report_workflow = report_runtime.workflow()
dingyi_process = DingyiProcessAdapter(agent_database.sync_engine)
report_workflow_controller = ReportWorkflowController(
    report_runtime.workflow,
    thread_ownership=report_runtime.state_repository,
    terminal_cleanup=report_runtime.cleanup_terminal,
    process_lifecycle=dingyi_process,
)
report_agent = create_report_agent(
    reporting_agent_template, report_workflow_controller, settings=settings
)
reporting_dependency_diagnostics = ReportingDependencyDiagnostics(
    sources=tuple(
        source
        for source in (report_runtime.registry.sources.values() if report_runtime.registry is not None else ())
        if isinstance(source, StarRocksSourceConfig)
    ),
    metadata_client=reporting_metadata_client,
)
router.include_router(
    create_reporting_dependency_diagnostics_router(reporting_dependency_diagnostics)
)


def create_base_app(context: ApplicationContext) -> FastAPI:
    application = FastAPI(title="开发智能体服务")
    application.state.agentos_context = context
    management_auth = AdminAuthService(AdminRepository(agent_database.async_engine))
    application.state.management_auth = management_auth
    management_settings = ManagementSettings.from_environment()
    application.state.management_settings = management_settings
    application.include_router(create_management_router(management_auth, management_settings, report_runtime=report_runtime,
        startup_settings=settings, system_configuration_state=system_configuration.state))
    from .management.format_preferences import FormatPreferenceService
    from .management.preference_approval import PreferenceApprovalService
    from .management.preference_report_preflight import BoundPreferencePreflightService
    from .management.preference_verification import PreferenceVerificationHandoffService
    from .management.preference_verification_api import create_preference_verification_router
    from .preferences.models import FormatPreferences

    preferences = FormatPreferenceService(management_auth, FormatPreferences.from_delivery(settings.report_delivery_settings))
    bound_preferences = BoundPreferencePreflightService(preferences=preferences,
        editor=report_editor, grants=report_editor_grants)
    preference_verification = PreferenceVerificationHandoffService(preferences=preferences, bound=bound_preferences)
    application.state.preference_approval = PreferenceApprovalService(evidence=preference_verification.evidence)
    application.include_router(create_preference_verification_router(preference_verification, management_settings))
    try:
        source_vault = CredentialVault()
    except Exception:
        source_vault = None
    from .management.scopes import ScopeService
    management_scopes = ScopeService(management_auth)
    business_documents = BusinessDocumentService(management_scopes, BusinessOriginalStore(
        reporting_workspace_registry.root / "business-knowledge",
    ))
    business_ingestion_worker = BusinessIngestionWorker(business_documents)
    application.state.business_ingestion_worker = business_ingestion_worker
    application.include_router(create_business_documents_router(
        business_documents, management_settings, notify=business_ingestion_worker.notify,
    ))
    business_evidence = BusinessEvidenceService(business_documents, None)
    application.state.business_evidence = business_evidence
    report_runtime.business_evidence_service = business_evidence
    report_editor.trace.business_evidence_service = business_evidence
    application.include_router(create_business_evidence_router(business_evidence, management_settings))
    application.include_router(create_metrics_router(MetricService(management_scopes), management_settings))
    application.include_router(create_statistical_policy_router(
        StatisticalPolicyService(management_scopes, business_evidence), management_settings,
    ))
    application.include_router(create_version_options_router(management_scopes))
    application.include_router(create_profile_router(management_scopes))
    application.include_router(create_catalog_router(
        management_scopes, source_vault, reporting_metadata_client,
    ))
    if source_vault is not None:
        application.include_router(create_source_router(management_scopes, source_vault))
        application.include_router(create_table_access_router(management_scopes, source_vault, reporting_metadata_client))
        application.include_router(create_import_router(
            management_scopes, source_vault, reporting_metadata_client,
        ))
    application.middleware("http")(require_workspace_capability)
    application.include_router(router)
    application.include_router(create_report_download_router(report_downloads))
    application.include_router(
        create_report_editor_router(
            report_editor_grants,
            editor=report_editor,
            ai=report_editor_ai,
            chart_ai=report_editor_chart_ai,
            data_revisions=report_data_revisions,
            table_ai=report_editor_table_ai,
            native_editor=native_editor,
            cookie_secure=bool(
                settings.report_public_base_url
                and settings.report_public_base_url.startswith("https://")
            ),
            allowed_origin=settings.report_public_base_url,
            static_dir=settings.report_editor_static_dir,
        )
    )
    static_root = Path(
        settings.report_editor_static_dir
        or Path(__file__).with_name("report_editor") / "static"
    )
    application.include_router(create_native_editor_router(
        report_editor_grants, editor=native_editor, download_service=native_downloads,
        ai_enabled=settings.native_ai_enabled,
        static_dir=static_root, allowed_origin=settings.report_public_base_url,
        cookie_secure=bool(settings.report_public_base_url and settings.report_public_base_url.startswith("https://")),
    ))
    application.include_router(create_native_ai_router(
        report_editor_grants, editor=native_editor, ai=native_ai, pdf_read=native_pdf_read_ai,
        word_read=native_word_read_ai,
        office_read=native_office_read_ai,
        allowed_origin=settings.report_public_base_url,
    ))
    application.include_router(create_native_pdf_review_ai_router(
        report_editor_grants, editor=native_editor, review=native_pdf_review_ai,
        allowed_origin=settings.report_public_base_url,
    ))
    application.include_router(create_native_pdf_form_ai_router(
        report_editor_grants, editor=native_editor, forms=native_pdf_form_ai,
        allowed_origin=settings.report_public_base_url,
    ))
    application.include_router(create_native_slides_ai_router(
        report_editor_grants, editor=native_editor, ai=native_slides_ai,
        allowed_origin=settings.report_public_base_url,
    ))
    application.include_router(create_native_workbook_ai_router(
        report_editor_grants, editor=native_editor, ai=native_workbook_ai,
        allowed_origin=settings.report_public_base_url,
    ))
    application.include_router(create_native_import_router(native_import, enabled=settings.native_upload_enabled))
    application.include_router(
        create_report_slides_editor_router(
            report_editor_grants,
            slides=report_slides_editor,
            slides_ai=report_slides_ai,
            slides_images=report_slides_image_ai,
            slides_charts=report_slides_chart_ai,
            static_dir=static_root / "slides",
            cookie_secure=bool(
                settings.report_public_base_url
                and settings.report_public_base_url.startswith("https://")
            ),
        )
    )
    application.include_router(
        create_report_workbook_editor_router(
            report_editor_grants,
            workbooks=report_workbook_editor,
            workbook_ai=report_workbook_ai,
            static_dir=static_root,
            cookie_secure=bool(
                settings.report_public_base_url
                and settings.report_public_base_url.startswith("https://")
            ),
        )
    )
    application.include_router(create_quality_warning_router())
    mount_process_routes(application, dingyi_process)
    application.router.add_event_handler("startup", _refresh_file_logging)
    application.router.add_event_handler("startup", business_ingestion_worker.start)
    application.router.add_event_handler("startup", _log_reporting_runtime_identity)
    application.router.add_event_handler("startup", install_report_download_access_log_filter)
    application.router.add_event_handler("startup", report_download_repository.create_schema)
    application.router.add_event_handler("startup", report_editor_repository.create_schema)
    application.router.add_event_handler("startup", native_document_repository.create_schema)
    application.router.add_event_handler("startup", report_design_templates.create_schema)
    application.router.add_event_handler("startup", quality_warning_service.create_schema)
    application.router.add_event_handler("shutdown", report_editor.aclose)
    application.router.add_event_handler("shutdown", business_ingestion_worker.aclose)
    application.router.add_event_handler("shutdown", native_workspace.registry.aclose)
    application.router.add_event_handler("shutdown", native_ai.aclose)
    application.router.add_event_handler("shutdown", native_pdf_read_ai.aclose)
    application.router.add_event_handler("shutdown", native_word_read_ai.aclose)
    application.router.add_event_handler("shutdown", native_office_read_ai.aclose)
    application.router.add_event_handler("shutdown", native_pdf_review_ai.aclose)
    application.router.add_event_handler("shutdown", native_pdf_form_ai.aclose)
    application.router.add_event_handler("shutdown", native_slides_ai.aclose)
    application.router.add_event_handler("shutdown", native_workbook_ai.aclose)
    if report_editor_chart_ai is not None:
        application.router.add_event_handler("shutdown", report_editor_chart_ai.aclose)
    if report_editor_table_ai is not None:
        application.router.add_event_handler("shutdown", report_editor_table_ai.aclose)
    return application


application_context = ApplicationContext(
    settings,
    report_agent,
    report_workflow,
    database=agent_database,
    recalculation_editor=report_editor,
    quality_warning_service=quality_warning_service,
    mcp_config=MCPConfig(
        tools=[
            report_workflow.as_tool(
                name="run_reporting_workflow",
                description="运行企业智能运营报表工作流，返回官方 Run 状态和审核要求。",
            )
        ],
        default_tools=False,
        lifecycle_tools=True,
        allowed_hosts=list(settings.reporting_mcp_allowed_hosts),
    ),
    mcp_auth=CapabilityTokenVerifier(settings.workspace_hmac_secret),
    reporting_code_mode_runtime=reporting_code_mode_runtime,
    reporting_lsp_process_manager=reporting_lsp_process_manager,
)
base_app = create_base_app(application_context)
agent_os, app = create_agentos_app(application_context, base_app)


if __name__ == "__main__":
    agent_os.serve(
        app="smart_reporting.app:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
