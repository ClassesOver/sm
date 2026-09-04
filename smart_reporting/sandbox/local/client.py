from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..contracts import (
    CodeRunRequest,
    CommandLogs,
    CommandResult,
    DestroyResult,
    ExecRequest,
    ExecResult,
    FileInfo,
    ProviderCapabilities,
    ProviderHealth,
    RunPythonScriptRequest,
    RunPythonScriptResult,
    SandboxRef,
    SandboxState,
    SandboxSummary,
    SessionCommandRequest,
    SessionRef,
    SessionSummary,
    WorkspaceBinding,
)
from ..errors import (
    DependencyUnavailable,
    SandboxBusy,
    SandboxCapabilityUnsupported,
    SandboxNotFound,
    SandboxPolicyDenied,
    SandboxPreflightFailed,
    SandboxProviderError,
    SandboxTimeout,
)
from .config import LocalProviderConfig

_ERROR_TYPES = {
    error.code: error
    for error in (
        SandboxProviderError,
        SandboxNotFound,
        SandboxBusy,
        SandboxTimeout,
        SandboxPreflightFailed,
    )
}


def _binding_digest(binding: WorkspaceBinding, secret: bytes) -> str:
    payload = binding.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


class _LocalApi:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def request(
        self,
        method: str,
        path: str,
        *,
        binding_digest: str,
        idempotency_key: str | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        headers = {"x-sandbox-binding": binding_digest}
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        try:
            response = await self.client.request(
                method, path, headers=headers, json=json_body, content=content
            )
        except httpx.TimeoutException as error:
            raise SandboxTimeout("local-sandboxd 请求超时。") from error
        except httpx.HTTPError as error:
            raise SandboxProviderError(
                "local-sandboxd 不可用。", retryable=True, details={"backend": "local"}
            ) from error
        if response.is_success:
            return response
        self._raise_response(response)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_response(response: httpx.Response) -> None:
        try:
            value = response.json()
        except ValueError as error:
            raise SandboxProviderError(
                "local-sandboxd 返回无效错误响应。", retryable=response.status_code >= 500
            ) from error
        code = str(value.get("code", "sandbox_provider_error"))
        message = str(value.get("message", "local-sandboxd 请求失败。"))
        details = value.get("details") if isinstance(value.get("details"), dict) else {}
        if code == SandboxPolicyDenied.code:
            raise SandboxPolicyDenied(message, reason=str(details.get("reason", "policy_denied")))
        if code == SandboxCapabilityUnsupported.code:
            raise SandboxCapabilityUnsupported(str(details.get("capability", "unknown")))
        if code == DependencyUnavailable.code:
            raise DependencyUnavailable(str(details.get("module", "unknown")))
        error_type = _ERROR_TYPES.get(code, SandboxProviderError)
        raise error_type(
            message,
            retryable=bool(value.get("retryable", response.status_code >= 500)),
            details=details,
        )


class LocalFileSystemApi:
    def __init__(self, api: _LocalApi, ref: SandboxRef) -> None:
        self._api = api
        self._ref = ref

    async def _action(self, action: str, body: dict[str, Any]) -> httpx.Response:
        return await self._api.request(
            "POST",
            f"/v1/workspaces/{self._ref.resource_id}/files/{action}",
            binding_digest=self._ref.binding_digest,
            json_body=body,
        )

    async def get_file_info(self, path: str) -> FileInfo:
        return FileInfo.model_validate((await self._action("stat", {"path": path})).json())

    async def list_files(self, path: str) -> list[FileInfo]:
        values = (await self._action("list", {"path": path})).json()
        return [FileInfo.model_validate(value) for value in values]

    async def create_folder(self, path: str, mode: str) -> None:
        await self._action("mkdir", {"path": path, "mode": mode})

    async def upload_file(self, content: bytes, path: str) -> None:
        await self._api.request(
            "PUT",
            f"/v1/workspaces/{self._ref.resource_id}/files/content",
            binding_digest=self._ref.binding_digest,
            json_body=None,
            content=content,
            idempotency_key=hashlib.sha256(path.encode() + content).hexdigest(),
        )
        await self._action("commit-upload", {"path": path})

    async def download_file(self, path: str) -> bytes:
        return (await self._action("download", {"path": path})).content

    async def download_file_stream(self, path: str, timeout: int) -> AsyncIterator[bytes]:
        response = await self._action("download", {"path": path, "timeout": timeout})

        async def stream() -> AsyncIterator[bytes]:
            yield response.content

        return stream()

    async def delete_file(self, path: str, recursive: bool = False) -> None:
        await self._action("delete", {"path": path, "recursive": recursive})

    async def move_files(self, source: str, destination: str) -> None:
        await self._action("move", {"source": source, "destination": destination})


class LocalProcessApi:
    def __init__(self, api: _LocalApi, ref: SandboxRef) -> None:
        self._api = api
        self._ref = ref

    async def _action(self, action: str, body: dict[str, Any]) -> Any:
        response = await self._api.request(
            "POST",
            f"/v1/workspaces/{self._ref.resource_id}/process/{action}",
            binding_digest=self._ref.binding_digest,
            json_body=body,
        )
        return response.json()

    async def exec(self, request: ExecRequest) -> ExecResult:
        raise SandboxCapabilityUnsupported("shell_exec")

    async def code_run(self, request: CodeRunRequest) -> ExecResult:
        result = await self.run_python_script(
            RunPythonScriptRequest(
                script=request.code, cwd=request.cwd, timeout_ms=request.timeout * 1000
            )
        )
        return ExecResult.model_validate(
            result.model_dump(exclude={"script_hash", "dependency_bundle_digest"})
        )

    async def run_python_script(self, request: RunPythonScriptRequest) -> RunPythonScriptResult:
        return RunPythonScriptResult.model_validate(
            await self._action("python", request.model_dump(mode="json"))
        )

    async def create_session(self, session_id: str) -> SessionRef:
        await self._action("sessions/create", {"session_id": session_id})
        return SessionRef(sandbox_ref=self._ref, provider_session_id=session_id)

    async def list_sessions(self) -> list[SessionSummary]:
        return [
            SessionSummary.model_validate(value)
            for value in await self._action("sessions/list", {})
        ]

    async def get_session(self, session_id: str) -> SessionSummary:
        return SessionSummary.model_validate(
            await self._action("sessions/get", {"session_id": session_id})
        )

    async def delete_session(self, session_id: str) -> None:
        await self._action("sessions/delete", {"session_id": session_id})

    async def execute_session_command(
        self, session_id: str, request: SessionCommandRequest
    ) -> CommandResult:
        return CommandResult.model_validate(
            await self._action(
                "sessions/execute",
                {"session_id": session_id, **request.model_dump(mode="json")},
            )
        )

    async def get_session_command(self, session_id: str, command_id: str) -> CommandResult:
        return CommandResult.model_validate(
            await self._action(
                "sessions/command", {"session_id": session_id, "command_id": command_id}
            )
        )

    async def get_session_command_logs(self, session_id: str, command_id: str) -> CommandLogs:
        return CommandLogs.model_validate(
            await self._action(
                "sessions/logs", {"session_id": session_id, "command_id": command_id}
            )
        )

    async def send_session_command_input(self, session_id: str, command_id: str, data: str) -> None:
        await self._action(
            "sessions/input", {"session_id": session_id, "command_id": command_id, "data": data}
        )


@dataclass(frozen=True)
class LocalSandboxHandle:
    ref: SandboxRef
    state: SandboxState
    fs: LocalFileSystemApi
    process: LocalProcessApi
    execution: LocalProcessApi


class LocalProvider:
    def __init__(
        self,
        config: LocalProviderConfig,
        *,
        registry: Any,
        binding_secret: bytes,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._binding_secret = binding_secret
        parsed = urlsplit(config.endpoint)
        if transport is None and parsed.scheme == "unix":
            transport = httpx.AsyncHTTPTransport(uds=parsed.path)
        verify: bool | str = config.ca_cert or True
        cert = (
            (config.client_cert, config.client_key)
            if config.client_cert and config.client_key
            else None
        )
        base_url = "http://local-sandboxd" if parsed.scheme == "unix" else config.endpoint
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            verify=verify,
            cert=cert,
            trust_env=False,
            timeout=httpx.Timeout(config.request_timeout, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._api = _LocalApi(self._client)

    @classmethod
    def from_settings(
        cls, settings: object, *, registry: Any, binding_secret: bytes
    ) -> LocalProvider:
        return cls(
            LocalProviderConfig.from_settings(settings),
            registry=registry,
            binding_secret=binding_secret,
        )

    def _digest(self, binding: WorkspaceBinding) -> str:
        if len(self._binding_secret) < 32:
            raise SandboxPolicyDenied(
                "sandbox binding secret 未安全配置。", reason="invalid_binding_secret"
            )
        return _binding_digest(binding, self._binding_secret)

    def _handle(self, value: dict[str, Any]) -> LocalSandboxHandle:
        ref = SandboxRef.model_validate(value["ref"])
        process = LocalProcessApi(self._api, ref)
        return LocalSandboxHandle(
            ref=ref,
            state=SandboxState(value["state"]),
            fs=LocalFileSystemApi(self._api, ref),
            process=process,
            execution=process,
        )

    async def ensure_workspace(self, binding: WorkspaceBinding) -> LocalSandboxHandle:
        digest = self._digest(binding)
        response = await self._api.request(
            "POST",
            "/v1/workspaces",
            binding_digest=digest,
            idempotency_key=binding.idempotency_key,
            json_body={
                "profile": self._config.profile,
                "rootfs_digest": self._config.rootfs_digest,
            },
        )
        handle = self._handle(response.json())
        async with self._registry.locked(digest) as registry:
            await registry.set(digest, handle.ref.resource_id)
        return handle

    async def get_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> LocalSandboxHandle:
        digest = self._digest(binding)
        if ref.binding_digest != digest:
            raise SandboxPolicyDenied("sandbox 资源不属于当前请求范围。", reason="binding_mismatch")
        response = await self._api.request(
            "GET", f"/v1/workspaces/{ref.resource_id}", binding_digest=digest
        )
        return self._handle(response.json())

    async def list_workspaces(self, binding: WorkspaceBinding) -> list[SandboxSummary]:
        response = await self._api.request(
            "GET", "/v1/workspaces", binding_digest=self._digest(binding)
        )
        return [SandboxSummary.model_validate(value) for value in response.json()]

    async def start_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> LocalSandboxHandle:
        return await self.get_workspace(ref, binding)

    async def stop_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> LocalSandboxHandle:
        raise SandboxCapabilityUnsupported("workspace_stop")

    async def destroy_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> DestroyResult:
        digest = self._digest(binding)
        if ref.binding_digest != digest:
            raise SandboxPolicyDenied("sandbox 资源不属于当前请求范围。", reason="binding_mismatch")
        response = await self._api.request(
            "DELETE", f"/v1/workspaces/{ref.resource_id}", binding_digest=digest
        )
        return DestroyResult.model_validate(response.json())

    async def health_check(self) -> ProviderHealth:
        response = await self._api.request("GET", "/v1/health", binding_digest="0" * 64)
        return ProviderHealth.model_validate(response.json())

    async def capabilities(self) -> ProviderCapabilities:
        response = await self._api.request("GET", "/v1/capabilities", binding_digest="0" * 64)
        return ProviderCapabilities.model_validate(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()
