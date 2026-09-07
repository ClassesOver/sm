from smart_reporting.sandbox.local.placement import LocalNode, PlacementService
from smart_reporting.sandbox.registry import SandboxBindingRecord


def test_existing_binding_never_silently_moves_nodes() -> None:
    nodes = (
        LocalNode("node-a", "https://node-a:9443", healthy=False),
        LocalNode("node-b", "https://node-b:9443", healthy=True),
    )
    existing = SandboxBindingRecord(
        binding_digest="a" * 64,
        provider="local",
        isolation="linux_process",
        node="node-a",
        resource_id="local-1",
        generation=1,
        dependency_bundle_digest="sha256:" + "b" * 64,
    )

    assert PlacementService(nodes).resolve("a" * 64, existing=existing).node_id == "node-a"


def test_new_binding_uses_deterministic_healthy_node() -> None:
    nodes = (
        LocalNode("node-a", "https://node-a:9443", healthy=True),
        LocalNode("node-b", "https://node-b:9443", healthy=True),
    )
    placement = PlacementService(nodes)

    assert placement.resolve("c" * 64).node_id == placement.resolve("c" * 64).node_id
