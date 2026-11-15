from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentAdapterRegistry, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_gateway import (
    DocumentCandidateDenied, DocumentCandidateGateway,
)


def scope():
    return DocumentScope("channel-a", "grant-a", "document-a", "1", "a" * 64, DocumentFormat.DOCX)


@pytest.mark.anyio
async def test_gateway_derives_scope_from_host_and_rechecks_after_prepare():
    current = scope()
    seen = []

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            seen.append(request)
            return "task-a"

        async def status(self, authorized_scope, task_id):
            return {"status": "ready"}

    async def resolve(channel, identity):
        return current if channel == "channel-a" and identity == "member" else None

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    task_id = await gateway.prepare(
        "channel-a", "member", request_id="one", instruction="Edit",
        selection=({"objectId": "one"},),
    )
    assert task_id == "task-a"
    assert seen[0].scope == current
    assert (await gateway.status("channel-a", "member", task_id))["status"] == "ready"
    with pytest.raises(DocumentCandidateDenied):
        await gateway.status("channel-b", "member", task_id)


@pytest.mark.anyio
async def test_gateway_does_not_return_result_after_grant_changes():
    current = scope()

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            nonlocal current
            current = replace(current, grant="grant-b")
            return "old-task"

        async def status(self, authorized_scope, task_id):
            return {"status": "ready"}

    async def resolve(channel, identity):
        return current

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(DocumentCandidateDenied, match="document_scope_changed"):
        await gateway.prepare(
            "channel-a", "member", request_id="one", instruction="Edit",
            selection=({"objectId": "one"},),
        )


@pytest.mark.anyio
async def test_unregistered_format_cannot_execute():
    current = replace(scope(), format=DocumentFormat.XLSX)

    async def resolve(channel, identity):
        return current

    gateway = DocumentCandidateGateway(DocumentAdapterRegistry(), resolve)
    with pytest.raises(ValueError, match="document_adapter_unavailable"):
        await gateway.prepare(
            "channel-a", "member", request_id="one", instruction="Edit",
            selection=({"cell": "A1"},),
        )


@pytest.mark.anyio
async def test_gateway_rechecks_scope_before_dispatch():
    initial = scope()
    calls = 0
    executed = []

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            executed.append("prepare")
            return "task"

        async def status(self, authorized_scope, task_id):
            executed.append("status")
            return {"status": "ready"}

    async def resolve(channel, identity):
        nonlocal calls
        calls += 1
        return initial if calls == 1 else replace(initial, revision="2")

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(DocumentCandidateDenied, match="document_scope_changed"):
        await gateway.prepare("channel-a", "member", request_id="one",
                              instruction="Edit", selection=({"objectId": "one"},))
    assert executed == []

    calls = 0
    with pytest.raises(DocumentCandidateDenied, match="document_scope_changed"):
        await gateway.status("channel-a", "member", "task")
    assert executed == []


@pytest.mark.anyio
@pytest.mark.parametrize("task_id", ["", "../other", "task\\nother", "含中文", "x" * 257])
async def test_gateway_rejects_unsafe_task_id_before_adapter_status(task_id):
    invoked = []

    class Adapter:
        format = DocumentFormat.DOCX

        async def status(self, authorized_scope, task_id):
            invoked.append(task_id)
            return {"status": "ready"}

    async def resolve(channel, identity):
        return scope()

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(ValueError, match="document_task_id_invalid"):
        await gateway.status("channel-a", "member", task_id)
    assert invoked == []


@pytest.mark.anyio
async def test_opt_in_document_routes_authorize_and_dispatch():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import AsyncMock
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")
    received = []

    class Adapter:
        format = DocumentFormat.XLSX

        async def prepare(self, request):
            received.append(request)
            return "task-one"

        async def status(self, authorized_scope, task_id):
            return {"status": "pending", "taskId": task_id}

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    authorized_scope = replace(scope(), format=DocumentFormat.XLSX)

    async def resolve(channel, caller):
        return authorized_scope if channel == "channel-a" and caller == identity else None

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        path = "/reports/v1/channels/channel-a/document-tasks"
        response = await http.post(path, json={
            "request_id": "one", "instruction": "Update", "selection": [{"cell": "A1"}],
        })
        assert response.status_code == 202
        assert response.json() == {"taskId": "task-one"}
        assert (await http.get(path + "/task-one")).json()["status"] == "pending"
        assert (await http.post(path, json={
            "request_id": "two", "instruction": "Update", "selection": [{"cell": "A1"}],
            "source_sha256": "b" * 64,
        })).status_code == 422
        assert (await http.post(path.replace("channel-a", "channel-b"), json={
            "request_id": "two", "instruction": "Update", "selection": [{"cell": "A1"}],
        })).status_code == 403
    assert received[0].scope == authorized_scope


@pytest.mark.anyio
async def test_document_adapter_runtime_value_error_is_not_misreported_as_bad_request():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import AsyncMock
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            raise ValueError("internal adapter failure")

        async def status(self, authorized_scope, task_id):
            raise ValueError("internal adapter failure")

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, caller):
        return scope()

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    path = "/reports/v1/channels/channel-a/document-tasks"
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True),
                           base_url="https://reports.test") as http:
        with pytest.raises(ValueError, match="internal adapter failure"):
            await http.post(path, json={
                "request_id": "one", "instruction": "Edit",
                "selection": [{"objectId": "one"}],
            })
        with pytest.raises(ValueError, match="internal adapter failure"):
            await http.get(path + "/task-one")


@pytest.mark.anyio
async def test_document_adapter_permission_denied_returns_403():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import AsyncMock
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            raise PermissionError("private grant or source detail")

        async def status(self, authorized_scope, task_id):
            raise PermissionError("private grant or source detail")

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, caller):
        return scope()

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    path = "/reports/v1/channels/channel-a/document-tasks"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        response = await http.post(path, json={
            "request_id": "one", "instruction": "Edit", "selection": [{"objectId": "one"}],
        })
        assert response.status_code == 403
        assert "private" not in response.text
        response = await http.get(path + "/task-one")
        assert response.status_code == 403
        assert "private" not in response.text


@pytest.mark.anyio
async def test_document_selection_mismatch_returns_422():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import AsyncMock
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            raise ValueError("document_selection_mismatch")

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, caller):
        return scope()

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        response = await http.post("/reports/v1/channels/channel-a/document-tasks", json={
            "request_id": "one", "instruction": "Edit", "selection": [{"paragraph": "1"}],
        })
    assert response.status_code == 422
    assert response.json()["detail"] == "document_task_invalid"


@pytest.mark.anyio
async def test_document_request_id_conflict_returns_http_409():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import AsyncMock
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")

    class Adapter:
        format = DocumentFormat.PPTX

        async def prepare(self, request):
            raise ValueError("document_request_id_conflict")

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, caller):
        return replace(scope(), format=DocumentFormat.PPTX)

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        response = await http.post("/reports/v1/channels/channel-a/document-tasks", json={
            "request_id": "same", "instruction": "Edit",
            "selection": [{"slide_id": 256, "shape_id": 2}],
        })
    assert response.status_code == 409
    assert response.json()["detail"] == "document_request_id_conflict"


@pytest.mark.anyio
@pytest.mark.parametrize("returned_task_id", [None, "", "../other", "bad id", 42, "x" * 257])
async def test_gateway_rejects_invalid_adapter_generated_task_ids(returned_task_id):
    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            return returned_task_id

    async def resolve(channel, identity):
        return scope()

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(ValueError, match="document_task_id_invalid"):
        await gateway.prepare(
            "channel-a", "member", request_id="one", instruction="Edit",
            selection=({"objectId": "one"},),
        )



@pytest.mark.anyio
@pytest.mark.parametrize("error_code", [
    "xlsx_target_out_of_bounds",
    "xlsx_preview_protected_sheet",
    "pptx_operation_target_unapproved",
    "pptx_preview_target_unsupported",
    "pdf_rect_invalid",
    "pdf_annotation_target_unapproved",
    "pdf_page_out_of_bounds",
])
async def test_format_candidate_validation_errors_return_422(error_code):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            raise ValueError(error_code)

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, caller):
        return scope()

    async def authenticate(request):
        return identity

    repository = type("Repository", (), {"has_member": AsyncMock(return_value=True)})()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, document_gateway=DocumentCandidateGateway(registry, resolve),
    ))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://reports.test",
    ) as http:
        result = await http.post("/reports/v1/channels/channel-a/document-tasks", json={
            "request_id": "one", "instruction": "Edit",
            "selection": [{"objectId": "one"}],
        })
    assert result.status_code == 422
    assert result.json()["detail"] == "document_task_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [
    {"taskId": "another-task", "status": "preview_ready", "accepted": False},
    {"taskId": None, "status": "preview_ready"},
])
async def test_gateway_never_returns_status_of_different_task(status):
    class Adapter:
        format = DocumentFormat.DOCX

        async def status(self, authorized_scope, task_id):
            return status

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, identity):
        return scope() if channel == "channel-a" and identity == "member" else None

    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(DocumentCandidateDenied, match="document_task_identity_mismatch"):
        await gateway.status("channel-a", "member", "expected-task")


@pytest.mark.anyio
async def test_gateway_rejects_non_mapping_adapter_status():
    class Adapter:
        format = DocumentFormat.DOCX

        async def status(self, authorized_scope, task_id):
            return None

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())

    async def resolve(channel, identity):
        return scope()

    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(ValueError, match="document_task_status_invalid"):
        await gateway.status("channel-a", "member", "expected-task")
