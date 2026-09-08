from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.sandbox.contracts import (
    CodeRunRequest,
    ProviderCapabilities,
    ProviderKind,
    RunPythonScriptRequest,
    SandboxRef,
    WorkspaceBinding,
)
from smart_reporting.sandbox.errors import (
    SandboxCapabilityUnsupported,
    SandboxPolicyDenied,
)


def _binding(**updates: object) -> WorkspaceBinding:
    values: dict[str, object] = {
        "tenant_id": "database-a",
        "user_id": "user-1",
        "company_id": "company-1",
        "thread_id": "thread-1",
        "idempotency_key": "request-00000001",
        "profile": "ubuntu",
    }
    values.update(updates)
    return WorkspaceBinding.model_validate(values)


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "company_id", "thread_id"])
def test_workspace_binding_rejects_missing_scope_field(field: str) -> None:
    values = _binding().model_dump()
    values.pop(field)

    with pytest.raises(ValidationError):
        WorkspaceBinding.model_validate(values)


def test_workspace_binding_rejects_short_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        _binding(idempotency_key="short")


def test_sandbox_ref_rejects_unqualified_dependency_digest() -> None:
    with pytest.raises(ValidationError):
        SandboxRef(
            provider=ProviderKind.LOCAL,
            isolation="linux_process",
            node="node-a",
            resource_id="workspace-1",
            generation=1,
            binding_digest="a" * 64,
            dependency_bundle_digest="a" * 64,
        )


@pytest.mark.parametrize("cwd", ["/tmp", "../escape", "a/../../b", "C:/Windows"])
def test_python_request_rejects_paths_outside_workspace(cwd: str) -> None:
    with pytest.raises(ValidationError):
        RunPythonScriptRequest(script="print('ok')", cwd=cwd)


def test_python_request_forbids_provider_policy_fields() -> None:
    with pytest.raises(ValidationError):
        RunPythonScriptRequest.model_validate(
            {
                "script": "print('ok')",
                "cwd": "analysis",
                "network": True,
                "interpreter": "/usr/bin/python3",
                "dependency_bundle_id": "latest",
            }
        )


def test_code_run_request_rejects_code_above_public_size_limit() -> None:
    with pytest.raises(ValidationError):
        CodeRunRequest(code="#" * (1024 * 1024 + 1))


def test_provider_capabilities_are_explicit_and_immutable() -> None:
    capabilities = ProviderCapabilities(
        persistent_sessions=True,
        pty=False,
        network_policy=True,
        branch_copy=True,
        resource_limits=True,
        snapshots=False,
    )

    assert capabilities.snapshots is False
    with pytest.raises(ValidationError):
        capabilities.snapshots = True


def test_unsupported_capability_has_stable_code_and_details() -> None:
    error = SandboxCapabilityUnsupported("snapshot")

    assert error.code == "sandbox_capability_unsupported"
    assert error.retryable is False
    assert error.details == {"capability": "snapshot"}


def test_policy_denial_does_not_echo_sensitive_input() -> None:
    error = SandboxPolicyDenied("请求不符合策略。", reason="binding_mismatch")

    assert error.code == "sandbox_policy_denied"
    assert error.details == {"reason": "binding_mismatch"}
    assert "token" not in str(error).lower()
