import pytest
from pydantic import ValidationError

from smart_reporting.sandbox.registry import SandboxBindingRecord


def test_binding_record_requires_provider_identity() -> None:
    with pytest.raises(ValidationError):
        SandboxBindingRecord.model_validate(
            {
                "binding_digest": "a" * 64,
                "resource_id": "sandbox-1",
            }
        )


def test_binding_record_round_trips_local_generation() -> None:
    record = SandboxBindingRecord(
        binding_digest="a" * 64,
        provider="local",
        isolation="linux_process",
        node="node-a",
        resource_id="workspace-1",
        generation=2,
        dependency_bundle_digest="sha256:" + "b" * 64,
    )

    assert record.provider == "local"
    assert record.generation == 2
    assert record.dependency_bundle_digest == "sha256:" + "b" * 64
