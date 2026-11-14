"""Expiry must be checked after the registry await, not before it."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    ReportEditorSession,
)
from smart_reporting.reporting.models import ReportingError


@pytest.mark.anyio
async def test_lookup_rejects_session_expiring_during_registry_read():
    entered, release = asyncio.Event(), asyncio.Event()

    class Repository(InMemoryReportEditorRepository):
        async def get_session(self, session_hash):
            entered.set()
            await release.wait()
            return await super().get_session(session_hash)

    repository = Repository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    expires = datetime.now(UTC) + timedelta(seconds=1)
    session = ReportEditorSession("report", 1, "run", "a" * 64, expires)
    await repository.put_session("hash", session)
    task = asyncio.create_task(grants.lookup_registered_session("hash"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        while datetime.now(UTC) <= expires:
            await asyncio.sleep(0.005)
        release.set()
        with pytest.raises(ReportingError) as error:
            await task
        assert error.value.code == "report_editor_session_expired"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
