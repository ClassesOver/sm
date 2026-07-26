from collections.abc import AsyncIterator
from typing import Any

import pytest
from agno.models.response import ToolExecution

from agentos_dev.coding import (
    AgnoRunState,
    CodingRepositoryError,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
    Lease,
    TaskState,
)
from agentos_dev.coding.executor import provider_error_suspend_code
from agentos_dev.database import create_agent_database


class FakeExecutor:
    def __init__(self, repository: CodingTaskRepository):
        self.repository = repository
        self.status_by_run: dict[str, AgnoRunState] = {}
        self.calls: list[tuple[str, str]] = []
        self.finish_on_attempt = 0
        self.dependencies = None

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
        self.dependencies = dependencies
        yield type(
            "ToolEvent",
            (),
            {
                "event": "ToolCallStarted",
                "tool": ToolExecution(
                    tool_call_id="call-terminal-12345678",
                    tool_name="terminal",
                    tool_args={
                        "command": "mysql --password=top-secret db",
                        "credentials": {"token": "private-token", "user": "analyst"},
                    },
                ),
            },
        )()
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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("You exceeded your current quota", "model_insufficient_quota"),
        (
            "Free quota exhausted. Disable the use free tier only mode.",
            "model_insufficient_quota",
        ),
        ("invalid_parameter_error: unsupported tool_choice", "model_invalid_request"),
        ("429 Too many requests", "model_rate_limited"),
    ],
)
def test_provider_errors_that_must_not_auto_resume_have_stable_codes(message, expected):
    assert provider_error_suspend_code(message) == expected


@pytest.mark.anyio
async def test_supervisor_first_run_only_publishes_receipted_final(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    await supervisor.start_task(coding_scope(), "实现目标")

    events = [event async for event in supervisor.run_task(coding_scope())]

    assert executor.calls[0][0] == "arun"
    assert executor.dependencies["AgentOS 编码任务"]["threadId"] == "thread"
    assert [event.event_id for event in events[-2:]] == [
        "external:final",
        "external:terminal",
    ]
    assert events[-2].data == {"content": "完成"}
    assert all("候选文本" not in str(event.data) for event in events)
    tool_event = events[0]
    assert tool_event.data["phase"] == "started"
    assert tool_event.data["tool"] == "terminal"
    assert tool_event.data["call_id"] == "external:0:internal:call-terminal-12345678"
    assert "top-secret" not in tool_event.data["arguments"]
    assert "private-token" not in tool_event.data["arguments"]
    assert "[REDACTED]" in tool_event.data["arguments"]
    task = await repository.get_task_snapshot("external")
    assert task is not None and task.state is TaskState.COMPLETED


@pytest.mark.anyio
async def test_supervisor_validates_and_persists_server_acceptance_contract(
    supervisor_runtime,
):
    repository, executor, _supervisor = supervisor_runtime
    acceptance_contract = {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }
    observed = []

    class Registry:
        def validate_contract(self, contract):
            observed.append(contract)
            return acceptance_contract

    supervisor = CodingTaskSupervisor(
        repository,
        executor,  # type: ignore[arg-type]
        validator_registry=Registry(),
    )

    task = await supervisor.start_task(
        coding_scope(),
        "实现目标",
        acceptance_contract=acceptance_contract,
    )

    assert observed == [acceptance_contract]
    assert task.acceptance_contract == acceptance_contract


@pytest.mark.anyio
async def test_supervisor_rejects_contract_without_validator_registry(supervisor_runtime):
    _repository, _executor, supervisor = supervisor_runtime

    with pytest.raises(CodingRepositoryError) as rejected:
        await supervisor.start_task(
            coding_scope(),
            "实现目标",
            acceptance_contract={"version": 1, "requirements": []},
        )

    assert rejected.value.code == "acceptance_validator_unavailable"


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


@pytest.mark.anyio
async def test_permanent_provider_error_suspends_without_automatic_resume(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    executor.finish_on_attempt = -1
    await supervisor.start_task(coding_scope(), "实现目标")

    async def quota_error_events(scope, attempt, dependencies):
        executor.status_by_run[attempt.internal_run_id] = AgnoRunState(
            exists=True,
            status="ERROR",
            terminal=True,
            checkpoint_recoverable=True,
            output="You exceeded your current quota",
            suspend_code="model_insufficient_quota",
        )
        if False:
            yield None

    executor._events = quota_error_events

    events = [event async for event in supervisor.run_task(coding_scope())]

    task = await repository.get_task_snapshot("external")
    assert task is not None and task.state is TaskState.SUSPENDED
    attempt = await repository.get_attempt(task.current_internal_run_id)
    assert attempt is not None and attempt.resume_count == 0
    assert executor.calls == [("arun", attempt.internal_run_id)]
    assert events[-1].type == "suspended"
    assert events[-1].data["code"] == "model_insufficient_quota"
