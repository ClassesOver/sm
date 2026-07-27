from datetime import timedelta
from typing import Any, cast

import pytest

from agentos_dev.coding.models import CodingScope, Lease, utcnow
from agentos_dev.coding.session import TaskSession


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_task_session_cleans_expired_tasks_once_before_claiming_lease():
    calls = []
    lease = Lease("session-owner", 3, utcnow() + timedelta(minutes=1))

    class Repository:
        async def cleanup_expired(self, *, lease_owner):
            calls.append(("cleanup", lease_owner))
            return 0

        async def claim_lease(self, external_run_id, lease_owner, *, ttl):
            calls.append(("claim", external_run_id, lease_owner, ttl))
            return Lease(lease_owner, lease.epoch, lease.expires_at)

        async def release_lease(self, external_run_id, lease_owner):
            calls.append(("release", external_run_id, lease_owner))

    scope = CodingScope("run", "user", "thread", "sandbox", "coding-agent")
    session = TaskSession(
        cast(Any, Repository()),
        scope,
        heartbeat_interval=3600,
    )

    async with session:
        assert session.lease.epoch == lease.epoch

    assert [call[0] for call in calls] == ["cleanup", "claim", "release"]
    assert calls[0][1] == calls[1][2]
