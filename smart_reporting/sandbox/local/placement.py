from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..errors import SandboxPreflightFailed
from ..registry import SandboxBindingRecord


@dataclass(frozen=True, slots=True)
class LocalNode:
    node_id: str
    endpoint: str
    healthy: bool


class PlacementService:
    """用 rendezvous hashing 为未绑定 workspace 选择健康节点。"""

    def __init__(self, nodes: tuple[LocalNode, ...]) -> None:
        if len({node.node_id for node in nodes}) != len(nodes):
            raise ValueError("local sandbox node_id 必须唯一")
        self._nodes = nodes

    def resolve(
        self,
        binding_digest: str,
        *,
        existing: SandboxBindingRecord | None = None,
        exclude: frozenset[str] = frozenset(),
    ) -> LocalNode:
        if existing is not None:
            node = next(
                (candidate for candidate in self._nodes if candidate.node_id == existing.node),
                None,
            )
            if node is None:
                raise SandboxPreflightFailed(
                    "既有 workspace 的绑定节点不在配置中。",
                    details={"node": existing.node},
                )
            return node
        candidates = [node for node in self._nodes if node.healthy and node.node_id not in exclude]
        if not candidates:
            raise SandboxPreflightFailed("没有可用的 local sandbox 节点。")
        return max(
            candidates,
            key=lambda node: hashlib.sha256(f"{binding_digest}:{node.node_id}".encode()).digest(),
        )
