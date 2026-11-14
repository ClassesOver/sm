from contextlib import nullcontext
from os import getenv
from pathlib import Path

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
from .office.editor_grant_repository import SqlAlchemyReportEditorRepository
from .office.editor_grants import ReportEditorGrantService
from .office.model import create_office_model
from .quality_warnings.api import create_quality_warning_router
from .quality_warnings.repository import SqlAlchemyQualityWarningRepository
from .quality_warnings.service import QualityWarningService
from .report_editor.native import NativeEditorService
from .report_editor.native_ai import create_native_ai_service
from .report_editor.native_ai_api import create_native_ai_router
from .report_editor.native_api import create_native_editor_router
from .report_editor.native_import import NativeImportService
from .report_editor.native_import_api import create_native_import_router
from .report_editor.native_office_read_tasks import NativeOfficeReadService
from .report_editor.native_pdf_ai import create_native_pdf_read_planner
from .report_editor.native_pdf_ai_tasks import NativePDFReadService
from .report_editor.native_pdf_form_ai import AgnoNativePDFFormPlanner
from .report_editor.native_pdf_form_ai_api import create_native_pdf_form_ai_router
from .report_editor.native_pdf_form_ai_tasks import NativePDFFormService
from .report_editor.native_pdf_review_ai import create_native_pdf_review_planner
from .report_editor.native_pdf_review_ai_api import create_native_pdf_review_ai_router
from .report_editor.native_pdf_review_ai_tasks import NativePDFReviewService
from .report_editor.native_publication import NativePublicationService
from .report_editor.native_readiness import native_readiness_checks
from .report_editor.native_repository import NativeDocumentRepository
from .report_editor.native_slides_read_ai import AgnoNativeSlidesReadPlanner
from .report_editor.native_word_read_ai import AgnoNativeWordReadPlanner
from .report_editor.native_word_read_tasks import NativeWordReadService
from .report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner
from .report_editor.slides_native_ai import create_native_slides_ai_service
from .report_editor.slides_native_ai_api import create_native_slides_ai_router
from .report_editor.workbook_native_ai import create_native_workbook_ai_service
from .report_editor.workbook_native_ai_api import create_native_workbook_ai_router
from .reporting.business_knowledge.originals import BusinessOriginalStore
from .reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
    create_report_download_router,
    install_report_download_access_log_filter,
)
from .reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from .reporting.metadata import ReportingMetadataClient
from .runtime.application import ApplicationContext, create_agentos_app
from .runtime.database import check_database, create_agent_database
from .runtime.execution import configure_execution_tracing
from .runtime.logging import configure_application_logging, configure_file_logging
from .runtime.settings import AgentSettings
from .runtime.system_configuration import load_system_configuration

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
# 历史报告产物与业务原件仍位于原宿主机工作区；Office 文件使用独立的 native 子目录。
reporting_workspace_registry = ReportingWorkspaceRegistry(
    settings.reporting_host_workspace_root,
    secret=settings.workspace_hmac_secret,
)
native_workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(
    Path(settings.reporting_host_workspace_root) / "native",
    secret=settings.workspace_hmac_secret,
))
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
# 已签发的历史报告下载链接继续有效，按原工作区有界读取。
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
# 报告工作流与旧 Markdown/幻灯片/工作簿编辑器已退役，旧编辑链接统一返回 410。
_RETIRED_EDITOR_PREFIXES = ("/reports/v1/editor", "/reports/v1/slides", "/reports/v1/workbooks")


def _retired_editor_response() -> JSONResponse:
    return JSONResponse(
        {"error": "report_editor_retired", "message": "旧报告编辑入口已停用，请在 Office 中打开文件。"},
        status_code=410,
        headers={"Cache-Control": "no-store"},
    )


for _prefix in _RETIRED_EDITOR_PREFIXES:
    router.add_api_route(
        f"{_prefix}/{{retired_path:path}}",
        _retired_editor_response,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )


async def _log_runtime_identity() -> None:
    """记录实际启动的版本和数据库边界，便于确认镜像是否已更新。"""

    loguru_logger.info(
        "office_runtime_started build_id={} database_backend={} workers={}",
        getenv("REPORTING_BUILD_ID", "unknown"),
        agent_database.backend,
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
native_publication = NativePublicationService(
    native_document_repository, native_workspace, report_download_grants, report_editor_grants,
    artifact_persistence=native_artifact_persistence,
    public_base_url=settings.report_public_base_url or "",
)
native_editor = NativeEditorService(
    native_workspace, native_document_repository, report_editor_grants,
    publication=native_publication,
    docx_enabled=settings.native_docx_enabled, pdf_enabled=settings.native_pdf_enabled,
    office_enabled=settings.native_upload_enabled,
    pdf_text_enabled=settings.native_pdf_text_enabled,
)
# Office 文件内 AI 按部署配置独立创建模型。
office_model = create_office_model(settings)
native_ai = create_native_ai_service(
    office_model, native_editor, enabled=settings.native_ai_enabled,
)
native_slides_ai = create_native_slides_ai_service(
    office_model, native_editor, enabled=settings.native_ai_enabled,
)
native_workbook_ai = create_native_workbook_ai_service(
    office_model, native_editor, enabled=settings.native_ai_enabled,
)
native_pdf_read_ai = NativePDFReadService(
    native_editor, planner=create_native_pdf_read_planner(office_model),
    enabled=settings.native_ai_enabled,
)
native_word_read_ai = NativeWordReadService(
    native_editor, planner=AgnoNativeWordReadPlanner(office_model),
    enabled=settings.native_ai_enabled,
)
native_office_read_ai = NativeOfficeReadService(
    native_editor, planners={
        "xlsx": AgnoNativeWorkbookReadPlanner(office_model),
        "pptx": AgnoNativeSlidesReadPlanner(office_model),
    }, enabled=settings.native_ai_enabled,
)
native_pdf_review_ai = NativePDFReviewService(
    native_editor, planner=create_native_pdf_review_planner(office_model),
    enabled=settings.native_ai_enabled,
)
native_pdf_form_ai = NativePDFFormService(
    native_editor, planner=AgnoNativePDFFormPlanner(office_model),
    enabled=settings.native_ai_enabled,
)
native_import = NativeImportService(native_workspace, native_document_repository, report_editor_grants)


def create_base_app(context: ApplicationContext) -> FastAPI:
    application = FastAPI(title="开发智能体服务")
    application.state.agentos_context = context
    management_auth = AdminAuthService(AdminRepository(agent_database.async_engine))
    application.state.management_auth = management_auth
    management_settings = ManagementSettings.from_environment()
    application.state.management_settings = management_settings
    application.include_router(create_management_router(
        management_auth, management_settings,
        startup_settings=settings, system_configuration_state=system_configuration.state,
    ))
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
    application.include_router(create_quality_warning_router())
    application.router.add_event_handler("startup", _refresh_file_logging)
    application.router.add_event_handler("startup", business_ingestion_worker.start)
    application.router.add_event_handler("startup", _log_runtime_identity)
    application.router.add_event_handler("startup", install_report_download_access_log_filter)
    application.router.add_event_handler("startup", report_download_repository.create_schema)
    application.router.add_event_handler("startup", report_editor_repository.create_schema)
    application.router.add_event_handler("startup", native_document_repository.create_schema)
    application.router.add_event_handler("startup", quality_warning_service.create_schema)
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
    return application


application_context = ApplicationContext(
    settings,
    database=agent_database,
    quality_warning_service=quality_warning_service,
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
