from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..contracts import RunPythonScriptRequest
from ..errors import (
    SandboxCapabilityUnsupported,
    SandboxNotFound,
    SandboxPolicyDenied,
    SandboxProviderError,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(pattern=r"^(ubuntu|openeuler)$")
    rootfs_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    timeout: int | None = Field(default=None, ge=1, le=3600)


class MkdirRequest(PathRequest):
    mode: str = Field(pattern=r"^[0-7]{3,4}$")


class DeleteRequest(PathRequest):
    recursive: bool = False


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)


def _error(status: int, code: str, message: str, *, reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "retryable": False,
            "details": {"reason": reason},
        },
    )


def _binding(value: str | None) -> str:
    if value is None or _DIGEST.fullmatch(value) is None:
        raise ValueError("invalid_binding")
    return value


def create_local_sandbox_app(runtime: Any) -> FastAPI:
    app = FastAPI(title="local-sandboxd", docs_url=None, redoc_url=None)

    @app.exception_handler(PermissionError)
    async def permission_error(_request: Request, _error_value: PermissionError) -> JSONResponse:
        return _error(
            403,
            "sandbox_policy_denied",
            "workspace 不属于当前绑定。",
            reason="binding_mismatch",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, _error_value: RequestValidationError
    ) -> JSONResponse:
        return _error(
            422,
            "sandbox_policy_denied",
            "请求违反 sandbox schema。",
            reason="invalid_request",
        )

    @app.exception_handler(SandboxProviderError)
    async def provider_error(_request: Request, error: SandboxProviderError) -> JSONResponse:
        status = (
            404
            if isinstance(error, SandboxNotFound)
            else 403
            if isinstance(error, SandboxPolicyDenied)
            else 422
            if isinstance(error, SandboxCapabilityUnsupported)
            else 503
        )
        return JSONResponse(
            status_code=status,
            content={
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": error.details,
            },
        )

    @app.exception_handler(ValueError)
    async def validation_error(_request: Request, error: ValueError) -> JSONResponse:
        return _error(422, "sandbox_policy_denied", "请求违反 sandbox 策略。", reason=str(error))

    @app.post("/v1/workspaces")
    async def ensure_workspace(
        body: CreateWorkspaceRequest,
        x_sandbox_binding: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ) -> Any:
        digest = _binding(x_sandbox_binding)
        if idempotency_key is None or not 16 <= len(idempotency_key) <= 256:
            raise ValueError("invalid_idempotency_key")
        return await runtime.ensure_workspace(
            digest,
            profile=body.profile,
            rootfs_digest=body.rootfs_digest,
            idempotency_key=idempotency_key,
        )

    @app.get("/v1/workspaces/{resource_id}")
    async def get_workspace(
        resource_id: str, x_sandbox_binding: str | None = Header(default=None)
    ) -> Any:
        return await runtime.get_workspace(resource_id, _binding(x_sandbox_binding))

    @app.get("/v1/workspaces")
    async def list_workspaces(x_sandbox_binding: str | None = Header(default=None)) -> Any:
        return await runtime.list_workspaces(_binding(x_sandbox_binding))

    @app.delete("/v1/workspaces/{resource_id}")
    async def destroy_workspace(
        resource_id: str, x_sandbox_binding: str | None = Header(default=None)
    ) -> Any:
        return await runtime.destroy_workspace(resource_id, _binding(x_sandbox_binding))

    @app.post("/v1/workspaces/{resource_id}/files/stat")
    async def stat_file(
        resource_id: str,
        body: PathRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "stat", body.model_dump()
        )

    @app.post("/v1/workspaces/{resource_id}/files/list")
    async def list_files(
        resource_id: str,
        body: PathRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "list", body.model_dump()
        )

    @app.post("/v1/workspaces/{resource_id}/files/mkdir")
    async def mkdir(
        resource_id: str,
        body: MkdirRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "mkdir", body.model_dump()
        )

    @app.put("/v1/workspaces/{resource_id}/files/content")
    async def upload_file(
        resource_id: str,
        request: Request,
        path: str = Query(min_length=1, max_length=1024),
        x_sandbox_binding: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ) -> Any:
        digest = _binding(x_sandbox_binding)
        if idempotency_key is None or not 16 <= len(idempotency_key) <= 256:
            raise ValueError("invalid_idempotency_key")
        raw_length = request.headers.get("content-length")
        if raw_length is None or not raw_length.isdigit() or int(raw_length) > 200 * 1024 * 1024:
            raise ValueError("invalid_content_length")
        content = await request.body()
        if len(content) != int(raw_length):
            raise ValueError("content_length_mismatch")
        await runtime.upload_file(resource_id, digest, path, content, idempotency_key)
        return {"ok": True}

    @app.post("/v1/workspaces/{resource_id}/files/download")
    async def download_file(
        resource_id: str,
        body: PathRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Response:
        content = await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "download", body.model_dump()
        )
        return Response(content=content, media_type="application/octet-stream")

    @app.post("/v1/workspaces/{resource_id}/files/delete")
    async def delete_file(
        resource_id: str,
        body: DeleteRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "delete", body.model_dump()
        )

    @app.post("/v1/workspaces/{resource_id}/files/move")
    async def move_file(
        resource_id: str,
        body: MoveRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.file_action(
            resource_id, _binding(x_sandbox_binding), "move", body.model_dump()
        )

    @app.post("/v1/workspaces/{resource_id}/process/python")
    async def run_python(
        resource_id: str,
        body: RunPythonScriptRequest,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        return await runtime.run_python_script(resource_id, _binding(x_sandbox_binding), body)

    @app.post("/v1/workspaces/{resource_id}/process/{action:path}")
    async def process_action(
        resource_id: str,
        action: str,
        request: Request,
        x_sandbox_binding: str | None = Header(default=None),
    ) -> Any:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("invalid_process_request")
        return await runtime.process_action(resource_id, _binding(x_sandbox_binding), action, body)

    @app.get("/v1/health")
    async def health() -> Any:
        return await runtime.health()

    @app.get("/v1/capabilities")
    async def capabilities() -> Any:
        return await runtime.capabilities()

    return app
