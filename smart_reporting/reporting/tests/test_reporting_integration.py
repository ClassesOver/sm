from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.workflow import Step, Workflow

from smart_reporting.database import create_agent_database
from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting.workflow.repository import ReportingStateRepository


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL/Agno 集成测试。")
    return value


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_owner_claim_release_matrix() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-thread-{suffix}"
    first_run_id = f"integration-run-a-{suffix}"
    second_run_id = f"integration-run-b-{suffix}"

    assert await first.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.ensure_workflow_thread_owner(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.ensure_workflow_thread_owner(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    owner = await second.get_workflow_thread_owner(thread_id)
    assert owner is not None
    assert owner["external_run_id"] == first_run_id

    assert not await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_concurrent_owner_claim_has_single_winner() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-thread-race-{suffix}"
    run_ids = (f"integration-run-a-{suffix}", f"integration-run-b-{suffix}")

    results = await asyncio.gather(
        first.claim_workflow_thread(
            thread_id=thread_id,
            external_run_id=run_ids[0],
            owner_user_id="integration-user",
        ),
        second.claim_workflow_thread(
            thread_id=thread_id,
            external_run_id=run_ids[1],
            owner_user_id="integration-user",
        ),
    )

    assert sorted(results) == [False, True]
    owner = await first.get_workflow_thread_owner(thread_id)
    assert owner is not None
    winner = run_ids[results.index(True)]
    assert owner["external_run_id"] == winner
    assert await first.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=winner,
        owner_user_id="integration-user",
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_execution_lock_matrix() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    first_run_id = f"integration-lock-a-{suffix}"
    second_run_id = f"integration-lock-b-{suffix}"

    async with first.workflow_execution_lock(first_run_id):
        assert await second.is_workflow_run_active(first_run_id)
        assert not await second.is_workflow_run_active(second_run_id)
        async with second.workflow_execution_lock(second_run_id):
            assert await first.is_workflow_run_active(second_run_id)

    assert not await second.is_workflow_run_active(first_run_id)
    assert not await first.is_workflow_run_active(second_run_id)


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_controller_releases_owner_after_deferred_sandbox_cleanup() -> (
    None
):
    database = create_agent_database(_integration_database_url())
    repository = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-deferred-cleanup-{suffix}"
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 1:
                raise RuntimeError("materialize failed")
            return SimpleNamespace(status=RunStatus.completed)

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_cleanup_failed",
            "失败运行环境已隔离并转入后台清理。",
        )

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=repository,
        terminal_cleanup=cleanup,
    )
    first_context = RunContext(
        run_id=f"integration-run-a-{suffix}",
        session_id=thread_id,
        user_id="integration-user",
        session_state={},
    )
    second_context = RunContext(
        run_id=f"integration-run-b-{suffix}",
        session_id=thread_id,
        user_id="integration-user",
        session_state={},
    )

    try:
        with pytest.raises(RuntimeError, match="materialize failed"):
            await controller.start(ReportingWorkflowInput(prompt="第一次运行"), first_context)
        assert await repository.get_workflow_thread_owner(thread_id) is None

        result = await controller.start(ReportingWorkflowInput(prompt="第二次运行"), second_context)

        assert result["status"] == "completed"
        assert run_calls == 2
        assert await repository.get_workflow_thread_owner(thread_id) is None
    finally:
        await repository.release_workflow_thread(
            thread_id=thread_id,
            external_run_id=str(first_context.run_id),
            owner_user_id="integration-user",
        )
        await repository.release_workflow_thread(
            thread_id=thread_id,
            external_run_id=str(second_context.run_id),
            owner_user_id="integration-user",
        )
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_agno_workflow_persists_and_reads_reporting_run() -> None:
    database = create_agent_database(_integration_database_url())
    session_id = f"integration-session-{uuid4().hex}"
    run_id = f"integration-run-{uuid4().hex}"

    async def execute(step_input):
        return f"ok:{step_input.input}"

    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        db=database.async_db,
        steps=[Step(name="integration-step", executor=execute)],
    )
    output = await workflow.arun(
        "integration",
        run_id=run_id,
        session_id=session_id,
        user_id="integration-user",
        stream=False,
    )
    restored = await workflow.aget_run(run_id, session_id=session_id)

    assert output.status.value == "COMPLETED"
    assert restored is not None
    assert restored.run_id == run_id
    assert getattr(restored.status, "value", restored.status) == "COMPLETED"
