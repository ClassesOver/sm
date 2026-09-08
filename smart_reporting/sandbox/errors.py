from __future__ import annotations

from typing import Any


class SandboxProviderError(RuntimeError):
    """所有 sandbox provider 失败的稳定应用边界。"""

    code = "sandbox_provider_error"
    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = self.default_retryable if retryable is None else retryable
        self.details = dict(details or {})


class SandboxNotFound(SandboxProviderError):
    code = "sandbox_not_found"


class SandboxBusy(SandboxProviderError):
    code = "sandbox_busy"
    default_retryable = True


class SandboxTimeout(SandboxProviderError):
    code = "sandbox_timeout"
    default_retryable = True


class SandboxCapabilityUnsupported(SandboxProviderError):
    code = "sandbox_capability_unsupported"

    def __init__(self, capability: str) -> None:
        super().__init__(
            "当前 sandbox provider 不支持所需能力。",
            details={"capability": capability},
        )


class SandboxPolicyDenied(SandboxProviderError):
    code = "sandbox_policy_denied"

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message, details={"reason": reason})


class DependencyUnavailable(SandboxProviderError):
    code = "sandbox_dependency_unavailable"

    def __init__(self, module: str) -> None:
        super().__init__(
            "离线依赖目录中不存在脚本需要的模块。",
            details={"module": module},
        )


class SandboxPreflightFailed(SandboxProviderError):
    code = "sandbox_preflight_failed"
