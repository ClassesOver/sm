from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agno.workflow import Step, Workflow

from smart_reporting.database import create_agent_database
from smart_reporting.reporting.workflow.repository import ReportingStateRepository


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL/Agno 集成测试。")
    return value


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_owner_and_execution_lock_across_repository_instances() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-thread-{suffix}"
    external_run_id = f"integration-run-{suffix}"

    assert await first.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=external_run_id,
        owner_user_id="integration-user",
    )
    owner = await second.get_workflow_thread_owner(thread_id)
    assert owner is not None
    assert owner["external_run_id"] == external_run_id

    async with first.workflow_execution_lock(external_run_id):
        assert await second.is_workflow_run_active(external_run_id)

    assert not await second.is_workflow_run_active(external_run_id)
    assert await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=external_run_id,
        owner_user_id="integration-user",
    )


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
    assert restored.status.value == "COMPLETED"
