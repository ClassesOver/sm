import pytest

from smart_reporting.sandbox.local.placement import LocalNode, PlacementService
from smart_reporting.sandbox.local.reconciler import LocalSandboxReconciler
from smart_reporting.sandbox.registry import SandboxBindingRecord


@pytest.mark.anyio
async def test_reconciler_creates_new_generation_after_node_loss() -> None:
    old = SandboxBindingRecord(
        binding_digest="a" * 64,
        provider="local",
        isolation="linux_process",
        node="node-a",
        resource_id="local-1",
        generation=2,
        dependency_bundle_digest="sha256:" + "b" * 64,
    )
    saved = []

    async def save(record):
        saved.append(record)

    reconciler = LocalSandboxReconciler(
        PlacementService((LocalNode("node-b", "https://node-b:9443", healthy=True),)),
        save_binding=save,
        restore_workspace=lambda _old, _node, generation: _restore(generation),
    )

    result = await reconciler.reconcile(old, unavailable_node="node-a")

    assert result.record.generation == 3
    assert result.record.node == "node-b"
    assert result.sessions_restored is False
    assert saved == [result.record]


async def _restore(generation: int) -> str:
    return f"local-generation-{generation}"
