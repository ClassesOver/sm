from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..registry import SandboxBindingRecord
from .placement import LocalNode, PlacementService


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    record: SandboxBindingRecord
    sessions_restored: bool = False


class LocalSandboxReconciler:
    """节点丢失时只恢复 workspace，新 generation 不继承进程或 PTY。"""

    def __init__(
        self,
        placement: PlacementService,
        *,
        save_binding: Callable[[SandboxBindingRecord], Awaitable[None]],
        restore_workspace: Callable[[SandboxBindingRecord, LocalNode, int], Awaitable[str]],
        quarantine_binding: Callable[[SandboxBindingRecord], Awaitable[None]] | None = None,
    ) -> None:
        self._placement = placement
        self._save_binding = save_binding
        self._restore_workspace = restore_workspace
        self._quarantine_binding = quarantine_binding
        self._locks: dict[str, asyncio.Lock] = {}

    async def reconcile(
        self, record: SandboxBindingRecord, *, unavailable_node: str
    ) -> ReconcileResult:
        lock = self._locks.setdefault(record.binding_digest, asyncio.Lock())
        async with lock:
            if record.node != unavailable_node:
                return ReconcileResult(record=record)
            if self._quarantine_binding is not None:
                await self._quarantine_binding(record)
            node = self._placement.resolve(
                record.binding_digest,
                exclude=frozenset({unavailable_node}),
            )
            generation = record.generation + 1
            resource_id = await self._restore_workspace(record, node, generation)
            replacement = record.model_copy(
                update={
                    "node": node.node_id,
                    "resource_id": resource_id,
                    "generation": generation,
                }
            )
            await self._save_binding(replacement)
            return ReconcileResult(record=replacement, sessions_restored=False)
