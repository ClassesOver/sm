from collections.abc import AsyncIterator
from typing import Any

import pytest

from agentos_dev.coding import (
    AgnoRunState,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
    Lease,
    TaskState,
)
from agentos_dev.database import create_agent_database


class FakeExecutor:
    def __init__(self, repository: CodingTaskRepository):
        self.repository = repository
        self.status_by_run: dict[str, AgnoRunState] = {}
        self.calls: list[tuple[str, str]] = []
        self.finish_on_attempt = 0

    async def state(self, scope, attempt):
        return self.status_by_run.get(attempt.internal_run_id, AgnoRunState(exists=False))

    async def arun(self, scope, attempt, instruction, *, dependencies) -> AsyncIterator[Any]:
        self.calls.append(("arun", attempt.internal_run_id))
        async for event in self._events(scope, attempt, dependencies):
            yield event

    async def acontinue_run(
        self, scope, attempt, instruction, *, dependencies
    ) -> AsyncIterator[Any]:
        self.calls.append(("acontinue_run", attempt.internal_run_id))
        async for event in self._events(scope, attempt, dependencies):
            yield event

    async def _events(self, scope, attempt, dependencies) -> AsyncIterator[Any]:
        yield type("ToolEvent", (), {"event": "ToolCallStarted"})()
        if attempt.attempt_no == self.finish_on_attempt:
            task = await self.repository.get_task_snapshot(scope.external_run_id)
            assert task is not None
            binding = dependencies["AgentOS 编码任务"]
            lease = Lease(binding["leaseOwner"], binding["leaseEpoch"], task.deadline_at)
            await self.repository.request_finish(
                scope.external_run_id,
                lease,
                task.state_version,
                {"summary": "完成", "attempt": attempt.attempt_no},
                result_text="完成",
                retained_execution_ids=[],
            )
        self.status_by_run[attempt.internal_run_id] = AgnoRunState(
            exists=True, status="COMPLETED", terminal=True, output="候选文本"
        )
        yield type("TextEvent", (), {"event": "RunContent", "content": "候选文本"})()


@pytest.fixture
async def supervisor_runtime(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    repository = CodingTaskRepository(database.async_db)
    executor = FakeExecutor(repository)
    supervisor = CodingTaskSupervisor(repository, executor)  # type: ignore[arg-type]
    yield repository, executor, supervisor
    await database.async_engine.dispose()
    database.sync_engine.dispose()


def coding_scope() -> CodingScope:
    return CodingScope("external", "user", "thread", "sandbox", "coding-agent")


@pytest.mark.anyio
async def test_supervisor_first_run_only_publishes_receipted_final(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    await supervisor.start_task(coding_scope(), "实现目标")

    events = [event async for event in supervisor.run_task(coding_scope())]

    assert executor.calls[0][0] == "arun"
    assert [event.event_id for event in events[-2:]] == [
        "external:final",
        "external:terminal",
    ]
    assert events[-2].data == {"content": "完成"}
    assert all("候选文本" not in str(event.data) for event in events)
    task = await repository.get_task_snapshot("external")
    assert task is not None and task.state is TaskState.COMPLETED


@pytest.mark.anyio
async def test_pending_instruction_is_applied_to_one_new_attempt(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    executor.finish_on_attempt = 1
    await supervisor.start_task(coding_scope(), "实现目标")
    await supervisor.submit_instruction(coding_scope(), "follow-up", "补充失败测试")

    events = [event async for event in supervisor.run_task(coding_scope())]

    assert [call[0] for call in executor.calls] == ["arun", "arun"]
    task = await repository.get_task_snapshot("external")
    assert task is not None and task.current_attempt_no == 1
    assert task.state is TaskState.COMPLETED
    assert events[-1].event_id == "external:terminal"


@pytest.mark.anyio
async def test_closing_event_stream_pauses_before_releasing_lease(supervisor_runtime):
    repository, _executor, supervisor = supervisor_runtime
    await supervisor.start_task(coding_scope(), "实现目标")
    events = supervisor.run_task(coding_scope())

    assert (await anext(events)).type == "agno_event"
    await events.aclose()

    task = await repository.get_task_snapshot("external")
    assert task is not None and task.state is TaskState.SUSPENDED
    attempt = await repository.get_attempt(task.current_internal_run_id)
    assert attempt is not None and attempt.state.value == "paused"
