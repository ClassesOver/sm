from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from .models import CodingScope, Lease, utcnow
from .repository import CodingRepositoryError, CodingTaskRepository

HEARTBEAT_INTERVAL_SECONDS = 15
LEASE_TTL_SECONDS = 45
LEASE_EXPIRY_GUARD_SECONDS = 2


class TaskSession:
    """持有不可由请求方指定 owner 的任务租约，并独立续租。"""

    def __init__(
        self,
        repository: CodingTaskRepository,
        scope: CodingScope,
        *,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
        lease_ttl: timedelta = timedelta(seconds=LEASE_TTL_SECONDS),
    ):
        self.repository = repository
        self.scope = scope
        self.heartbeat_interval = heartbeat_interval
        self.lease_ttl = lease_ttl
        self._owner = uuid.uuid4().hex
        self._lease: Lease | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._lost = asyncio.Event()

    @property
    def lease(self) -> Lease:
        if self._lease is None:
            raise CodingRepositoryError("task_lease_missing", "任务租约尚未获取。")
        return self._lease

    async def __aenter__(self) -> TaskSession:
        claimed = await self.repository.claim_lease(
            self.scope.external_run_id, self._owner, ttl=self.lease_ttl
        )
        if not isinstance(claimed, Lease):
            raise CodingRepositoryError("task_lease_conflict", "任务正由其他实例处理。")
        self._lease = claimed
        self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="coding-task-heartbeat")
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
        if self._lease is not None:
            await self.repository.release_lease(self.scope.external_run_id, self._lease.owner)

    def assert_alive(self) -> None:
        lease = self.lease
        if self._lost.is_set() or lease.expires_at <= utcnow() + timedelta(
            seconds=LEASE_EXPIRY_GUARD_SECONDS
        ):
            raise CodingRepositoryError("task_lease_lost", "任务租约已失效。")

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                self._lease = await self.repository.heartbeat_lease(
                    self.scope.external_run_id, self.lease, ttl=self.lease_ttl
                )
            except asyncio.CancelledError:
                raise
            except CodingRepositoryError:
                self._lost.set()
                raise
