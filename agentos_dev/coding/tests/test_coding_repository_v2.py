from datetime import timedelta

import pytest

from agentos_dev.coding import (
    AttemptOutcome,
    AttemptState,
    CodingRepositoryError,
    CodingScope,
    CodingTaskRepository,
    InstructionState,
    Lease,
    TaskState,
)
from agentos_dev.database import create_agent_database
from agentos_dev.task_execution.repository import MAX_INSTRUCTION_BYTES, utcnow


@pytest.fixture
async def repository_v2(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    repository = CodingTaskRepository(database.async_db)
    yield repository
    await database.async_engine.dispose()
    database.sync_engine.dispose()


def scope(run_id: str = "run") -> CodingScope:
    return CodingScope(run_id, "user", "thread", "sandbox", "coding-agent")


@pytest.mark.anyio
async def test_reporting可显式提高单条指令上限且默认边界不变(repository_v2):
    content = "x" * (MAX_INSTRUCTION_BYTES + 1)
    with pytest.raises(CodingRepositoryError) as rejected:
        await repository_v2.create_task_with_initial_attempt(scope("default-limit"), content)
    assert rejected.value.code == "instruction_too_large"

    task = await repository_v2.create_task_with_initial_attempt(
        scope("report-limit"),
        content,
        max_instruction_bytes=512 * 1024,
    )

    assert task.scope.external_run_id == "report-limit"


@pytest.mark.anyio
async def test_create_aggregate_is_idempotent_and_attempt_zero_is_free(repository_v2):
    task = await repository_v2.create_task_with_initial_attempt(scope(), "实现目标")
    duplicate = await repository_v2.create_task_with_initial_attempt(scope(), "实现目标")

    assert duplicate == task
    assert task.state is TaskState.NEW
    assert task.current_attempt_no == task.continuation_count == 0
    attempt = await repository_v2.get_attempt(task.current_internal_run_id)
    assert attempt is not None and attempt.state is AttemptState.CREATED

    with pytest.raises(CodingRepositoryError, match="初始目标不一致") as conflict:
        await repository_v2.create_task_with_initial_attempt(scope(), "另一个目标")
    assert conflict.value.code == "task_initial_instruction_conflict"


@pytest.mark.anyio
async def test_new_attempt_instruction_keeps_initial_goal_and_latest_supplement(repository_v2):
    task = await repository_v2.create_task_with_initial_attempt(scope(), "不可变目标")
    await repository_v2.submit_instruction(scope(), "first", "较早补充")
    await repository_v2.submit_instruction(scope(), "latest", "最新补充")
    lease = await repository_v2.claim_lease("run", "worker")
    assert isinstance(lease, Lease)
    continued = await repository_v2.close_and_decide(
        "run",
        lease,
        task.state_version + 2,
        outcome=AttemptOutcome.NO_FINISH,
        agno_status="COMPLETED",
        create_next=True,
    )

    assert (
        await repository_v2.attempt_instruction("run", continued.current_attempt_no)
        == "不可变目标\n\n最新补充"
    )


@pytest.mark.anyio
async def test_acceptance_contract_is_persisted_and_immutable(repository_v2):
    acceptance_contract = {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {"currency": "CNY"},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }

    task = await repository_v2.create_task_with_initial_attempt(
        scope(),
        "实现目标",
        acceptance_contract=acceptance_contract,
    )
    duplicate = await repository_v2.create_task_with_initial_attempt(
        scope(),
        "实现目标",
        acceptance_contract=acceptance_contract,
    )

    assert task.acceptance_contract == acceptance_contract
    assert duplicate.acceptance_contract == acceptance_contract
    acceptance_contract["requirements"][0]["parameters"]["currency"] = "USD"
    assert (await repository_v2.get_task_snapshot("run")).acceptance_contract != acceptance_contract
    with pytest.raises(CodingRepositoryError) as conflict:
        await repository_v2.create_task_with_initial_attempt(
            scope(),
            "实现目标",
            acceptance_contract=acceptance_contract,
        )
    assert conflict.value.code == "task_acceptance_contract_conflict"


@pytest.mark.anyio
async def test_legacy_terminal_task_is_not_exposed_as_v2_snapshot(repository_v2):
    legacy = await repository_v2.create_task(
        external_run_id="legacy",
        owner_user_id="user",
        thread_id="thread",
        agent_id="coding-agent",
        sandbox_id="sandbox",
        deadline_at=utcnow() + timedelta(hours=24),
    )
    await repository_v2.set_task_status(legacy.external_run_id, "cancelled")

    assert await repository_v2.get_task_snapshot(legacy.external_run_id) is None


@pytest.mark.anyio
async def test_lease_epoch_fences_old_owner_and_heartbeat_does_not_change_version(repository_v2):
    task = await repository_v2.create_task_with_initial_attempt(scope(), "实现目标")
    first = await repository_v2.claim_lease("run", "worker-a")
    assert isinstance(first, Lease)
    heartbeat = await repository_v2.heartbeat_lease("run", first)

    assert heartbeat.epoch == first.epoch == 1
    assert (await repository_v2.get_task_snapshot("run")).state_version == task.state_version
    assert await repository_v2.claim_lease("run", "worker-b") is None

    expired = Lease(first.owner, first.epoch - 1, first.expires_at)
    with pytest.raises(CodingRepositoryError) as stale:
        await repository_v2.resume_current("run", expired, task.state_version)
    assert stale.value.code == "task_cas_conflict"


@pytest.mark.anyio
async def test_instruction_inbox_idempotency_conflict_and_atomic_apply(repository_v2):
    await repository_v2.create_task_with_initial_attempt(scope(), "实现目标")
    first = await repository_v2.submit_instruction(scope(), "instruction-1", "增加失败测试")
    duplicate = await repository_v2.submit_instruction(scope(), "instruction-1", "增加失败测试")

    assert duplicate == first
    assert first.state is InstructionState.PENDING
    with pytest.raises(CodingRepositoryError) as conflict:
        await repository_v2.submit_instruction(scope(), "instruction-1", "修改成别的内容")
    assert conflict.value.code == "instruction_id_conflict"

    current = await repository_v2.get_task_snapshot("run")
    lease = await repository_v2.claim_lease("run", "worker")
    assert current is not None and isinstance(lease, Lease)
    continued = await repository_v2.close_and_decide(
        "run",
        lease,
        current.state_version,
        outcome=AttemptOutcome.NO_FINISH,
        agno_status="COMPLETED",
        create_next=True,
    )

    assert continued.current_attempt_no == continued.continuation_count == 1
    assert await repository_v2.pending_instructions("run") == []


@pytest.mark.anyio
async def test_finish_is_two_phase_and_instruction_requires_successor(repository_v2):
    task = await repository_v2.create_task_with_initial_attempt(scope(), "实现目标")
    lease = await repository_v2.claim_lease("run", "worker")
    assert isinstance(lease, Lease)
    receipt = {"summary": "完成", "digest": "abc"}
    finishing = await repository_v2.request_finish(
        "run",
        lease,
        task.state_version,
        receipt,
        result_text="完成",
        retained_execution_ids=[],
    )

    assert finishing.state is TaskState.FINISHING
    attempt = await repository_v2.get_attempt(finishing.current_internal_run_id)
    assert attempt is not None and attempt.state is AttemptState.FINISH_REQUESTED
    with pytest.raises(CodingRepositoryError) as successor:
        await repository_v2.submit_instruction(scope(), "late", "继续修改")
    assert successor.value.code == "task_successor_required"

    completed = await repository_v2.finalize_finish(
        "run", lease, finishing.state_version, agno_status="COMPLETED"
    )
    assert completed.state is TaskState.COMPLETED
    closed = await repository_v2.get_attempt(completed.current_internal_run_id)
    assert closed is not None and closed.outcome is AttemptOutcome.FINISH_ACCEPTED
