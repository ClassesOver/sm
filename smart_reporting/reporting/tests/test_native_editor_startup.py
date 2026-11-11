"""应用工厂登记原生表初始化，但本测试不启动业务数据库或模型。"""

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet


@pytest.mark.anyio
async def test_application_registers_native_schema_startup(monkeypatch):
    # 导入工厂前关闭注册外的数据库/追踪副作用，不运行其他 startup。
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.configure_execution_tracing", lambda *args: None
    )
    monkeypatch.setattr(
        "smart_reporting.integrations.dingyi_process.mount_process_routes", lambda *args: None
    )
    monkeypatch.setenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS", f"test:{Fernet.generate_key().decode()}")
    import smart_reporting.app as app_module

    create_schema = AsyncMock()
    monkeypatch.setattr(app_module.native_document_repository, "create_schema", create_schema)
    application = app_module.create_base_app(app_module.application_context)
    registered = [handler for handler in application.router.on_startup if handler is create_schema]
    assert len(registered) == 1
    await registered[0]()
    create_schema.assert_awaited_once()
    paths = application.openapi()["paths"]
    assert "/reports/v1/native/{document_id}/{revision}/api/context" in paths
    assert "/reports/v1/native/{document_id}/{revision}/api/save" in paths
    assert "/reports/v1/native/{document_id}/{revision}/api/ai/start" in paths
    assert "/reports/v1/native/{document_id}/{revision}/api/slides-ai/start" in paths
    assert app_module.native_slides_ai.aclose in application.router.on_shutdown
    assert "/reports/v1/native/{document_id}/{revision}/api/workbook-ai/start" in paths
    assert "/reports/v1/native/{document_id}/{revision}/api/workbook-ai/cancel-request" in paths
    assert app_module.native_workbook_ai.aclose in application.router.on_shutdown
    assert "/reports/v1/native/{document_id}/{revision}/api/ai/review/start" in paths
    assert "/reports/v1/native/{document_id}/{revision}/api/ai/review/{edit_id}/accept" in paths
    assert app_module.native_pdf_review_ai.aclose in application.router.on_shutdown
    assert app_module.native_editor.publication is app_module.native_publication
    assert app_module.native_artifact_persistence.workspace_service is app_module.native_workspace
    assert app_module.native_downloads.workspace_service is app_module.native_workspace
    assert app_module.native_workspace.registry is not app_module.reporting_workspace_registry
