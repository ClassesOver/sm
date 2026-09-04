from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(pattern=r"^(ubuntu|openeuler)$")
    rootfs_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


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

    return app
