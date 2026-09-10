from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY


class Repository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.owners: dict[str, dict[str, Any]] = {}

    async def register_run(self, **values: Any) -> dict[str, Any]:
        row = dict(values)
        self.runs[str(values["external_run_id"])] = row
        return row

    async def claim_workflow_thread(self, **values: str) -> bool:
        key = values["thread_id"]
        if key in self.owners:
            return False
        self.owners[key] = dict(values)
        return True

    async def attach_workflow_owner_run(self, **values: str) -> None:
        self.owners[values["thread_id"]]["report_run_id"] = values["report_run_id"]

    async def update_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None = None,
    ) -> None:
        row = self.runs[report_run_id]
        row["status"] = status
        if finalization_pending is not None:
            row["finalization_pending"] = finalization_pending

    async def get_run_by_external(self, external_run_id: str) -> dict[str, Any] | None:
        return self.runs.get(external_run_id)

    async def get_workflow_thread_owner(self, thread_id: str) -> dict[str, Any] | None:
        return self.owners.get(thread_id)

    async def release_workflow_thread(self, **values: str) -> bool:
        key = values["thread_id"]
        owner = self.owners.get(key)
        if owner is None or owner["external_run_id"] != values["external_run_id"]:
            return False
        del self.owners[key]
        return True

    @asynccontextmanager
    async def workflow_thread_lifecycle_lock(self, _thread_id: str):
        yield


def runtime(repository: Repository, cleaned: list[str]) -> ReportWorkflowRuntime:
    current = object.__new__(ReportWorkflowRuntime)
    current.state_repository = repository

    async def cleanup(scope: dict[str, str], *_args: Any) -> None:
        cleaned.append(scope["thread_id"])

    current.cleanup_terminal = cleanup
    return current


def prepared(
    current: ReportWorkflowRuntime,
    *,
    run_id: str,
    thread_id: str = "thread-1",
    database: str = "db-1",
    company_id: str = "company-1",
    user_id: str = "user-1",
) -> dict[str, Any]:
    return current.prepare_run(
        run_id=run_id,
        session_id=thread_id,
        user_id=user_id,
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "database": database,
                "companyId": company_id,
            }
        },
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_same_raw_thread_in_different_tenants_can_run() -> None:
    repository = Repository()
    current = runtime(repository, [])

    await current.start_run("run-a", prepared(current, run_id="run-a", database="db-a"))
    await current.start_run("run-b", prepared(current, run_id="run-b", database="db-b"))

    assert len(repository.owners) == 2


@pytest.mark.anyio
async def test_same_full_thread_scope_rejects_second_active_run() -> None:
    repository = Repository()
    current = runtime(repository, [])

    await current.start_run("run-a", prepared(current, run_id="run-a"))

    with pytest.raises(ReportingError) as raised:
        await current.start_run("run-b", prepared(current, run_id="run-b"))

    assert raised.value.code == "report_workflow_thread_busy"
    assert repository.runs["run-b"]["status"] == "failed"


@pytest.mark.anyio
async def test_terminal_cleanup_is_run_scoped_and_allows_next_run() -> None:
    repository = Repository()
    cleaned: list[str] = []
    current = runtime(repository, cleaned)
    first_state = prepared(current, run_id="run-a")
    other_state = prepared(current, run_id="run-b", thread_id="thread-2")
    await current.start_run("run-a", first_state)
    await current.start_run("run-b", other_state)

    await current.settle_run("run-a", "completed")

    assert cleaned == [first_state["report_workflow_scope"]["threadId"]]
    assert len(repository.owners) == 1
    assert next(iter(repository.owners.values()))["external_run_id"] == "run-b"

    await current.start_run("run-c", prepared(current, run_id="run-c"))
    assert len(repository.owners) == 2


@pytest.mark.anyio
async def test_paused_run_retains_thread_owner() -> None:
    repository = Repository()
    current = runtime(repository, [])
    await current.start_run("run-a", prepared(current, run_id="run-a"))

    await current.settle_run("run-a", "paused")

    assert repository.runs["run-a"]["status"] == "paused"
    assert len(repository.owners) == 1
