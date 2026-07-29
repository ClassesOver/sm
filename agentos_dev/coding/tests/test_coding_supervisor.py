import asyncio
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
        self.instructions: list[str | None] = []
        self.finish_on_attempt = 0
        self.finish_failure: dict[str, Any] | None = None
        self.dependencies = None

    async def state(self, scope, attempt):
        return self.status_by_run.get(attempt.internal_run_id, AgnoRunState(exists=False))

    async def arun(self, scope, attempt, instruction, *, dependencies) -> AsyncIterator[Any]:
        self.calls.append(("arun", attempt.internal_run_id))
        self.instructions.append(instruction)
        async for event in self._events(scope, attempt, dependencies):
            yield event

    async def acontinue_run(
        self, scope, attempt, instruction, *, dependencies
    ) -> AsyncIterator[Any]:
        self.calls.append(("acontinue_run", attempt.internal_run_id))
        self.instructions.append(instruction)
        async for event in self._events(scope, attempt, dependencies):
            yield event

    async def _events(self, scope, attempt, dependencies) -> AsyncIterator[Any]:
        self.dependencies = dependencies
        yield type(
            "ReasoningEvent",
            (),
            {
                "event": "RunContent",
                "reasoning_content": "先检查",
                "model_provider_data": {"thinking": "不得透传"},
            },
        )()
        yield type(
            "ReasoningEvent",
            (),
            {"event": "RunContent", "reasoning_content": "，再修改"},
        )()
        yield type(
            "ReasoningEvent",
            (),
            {"event": "RunContent", "reasoning_content": ""},
        )()
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
            exists=True,
            status="COMPLETED",
            terminal=True,
            output="候选文本",
            finish_failure=(self.finish_failure if attempt.attempt_no == 0 else None),
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


async def _collect(source) -> list:
    return [event async for event in source]


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
    assert [event.data for event in events[:4]] == [
        {"event": "ReasoningStarted"},
        {"event": "ReasoningContentDelta", "reasoning_content": "先检查"},
        {"event": "ReasoningContentDelta", "reasoning_content": "，再修改"},
        {"event": "ReasoningCompleted"},
    ]
    assert "不得透传" not in str(events)
    tool_event = events[4]
    assert tool_event.data["phase"] == "started"
    assert tool_event.data["tool"] == "terminal"
    assert tool_event.data["call_id"] == "external:0:internal:call-terminal-12345678"
    assert "top-secret" not in tool_event.data["arguments"]
    assert "private-token" not in tool_event.data["arguments"]
    assert "[REDACTED]" in tool_event.data["arguments"]
    task = await repository.get_task_snapshot("external")
    assert task is not None and task.state is TaskState.COMPLETED


@pytest.mark.anyio
async def test_completed_task_revision_reuses_task_and_creates_next_attempt(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    current_scope = coding_scope()
    await supervisor.start_task(current_scope, "生成报告")
    await asyncio.wait_for(
        _collect(supervisor.run_task(current_scope)),
        timeout=2,
    )
    first = await repository.get_task_snapshot(current_scope.external_run_id)
    assert first is not None and first.state is TaskState.COMPLETED

    executor.finish_on_attempt = 1
    revised = await supervisor.revise_task(
        current_scope,
        "report-revision-2",
        "根据审核意见修订报告",
    )
    events = await asyncio.wait_for(
        _collect(supervisor.run_task(current_scope)),
        timeout=2,
    )

    completed = await repository.get_task_snapshot(current_scope.external_run_id)
    assert revised.scope.external_run_id == first.scope.external_run_id == "external"
    assert revised.current_attempt_no == first.current_attempt_no + 1
    assert completed is not None and completed.state is TaskState.COMPLETED
    assert completed.current_attempt_no == 1
    assert executor.instructions[-1] == "生成报告\n\n根据审核意见修订报告"
    assert events[-1].event_id == "external:terminal"


@pytest.mark.anyio
async def test_task_revision_requires_completed_task_and_rejects_instruction_conflict(
    supervisor_runtime,
):
    _repository, _executor, supervisor = supervisor_runtime
    current_scope = coding_scope()
    await supervisor.start_task(current_scope, "生成报告")

    with pytest.raises(CodingRepositoryError) as not_ready:
        await supervisor.revise_task(
            current_scope,
            "report-revision-2",
            "根据审核意见修订报告",
        )
    assert not_ready.value.code == "task_revision_not_ready"

    await asyncio.wait_for(_collect(supervisor.run_task(current_scope)), timeout=2)
    await supervisor.revise_task(
        current_scope,
        "report-revision-2",
        "根据审核意见修订报告",
    )
    with pytest.raises(CodingRepositoryError) as conflict:
        await supervisor.revise_task(
            current_scope,
            "report-revision-2",
            "替换为不同的修订要求",
        )
    assert conflict.value.code == "instruction_id_conflict"


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

    async def collect_events():
        return [event async for event in supervisor.run_task(coding_scope())]

    try:
        events = await asyncio.wait_for(collect_events(), timeout=2)
    except TimeoutError:
        task = await repository.get_task_snapshot("external")
        pytest.fail(f"supervisor timeout: calls={executor.calls}, task={task}")

    assert [call[0] for call in executor.calls] == ["arun", "arun"]
    assert executor.instructions[0] == "实现目标"
    assert "实现目标\n\n补充失败测试" in executor.instructions[1]
    assert '"marker":"CODING_RUNTIME_FEEDBACK"' in executor.instructions[1]
    assert '"sourceAttempt":0' in executor.instructions[1]
    task = await repository.get_task_snapshot("external")
    assert task is not None and task.current_attempt_no == 1
    assert task.state is TaskState.COMPLETED
    assert events[-1].event_id == "external:terminal"

    repeated = [event async for event in supervisor.resume_task(coding_scope())]
    assert executor.calls == [
        ("arun", CodingTaskRepository.internal_run_id("external", 0)),
        ("arun", CodingTaskRepository.internal_run_id("external", 1)),
    ]
    assert repeated[-1].event_id == "external:terminal"


@pytest.mark.anyio
async def test_new_attempt_keeps_latest_finish_failure_feedback(supervisor_runtime):
    repository, executor, supervisor = supervisor_runtime
    executor.finish_on_attempt = 1
    executor.finish_failure = {
        "code": "finish_artifact_missing",
        "details": {
            "mutationSequence": 0,
            "missingPaths": ["reports/ruijin-2025.pdf"],
        },
        "requiredActions": [
            "调用 verify 运行产物生成命令，并将 details.missingPaths 作为 artifact_paths；"
            "验证成功后重新调用 finish_task。"
        ],
    }
    await supervisor.start_task(coding_scope(), "生成报告")

    events = [event async for event in supervisor.run_task(coding_scope())]

    feedback = executor.instructions[1]
    assert feedback is not None
    assert '"code":"finish_artifact_missing"' in feedback
    assert '"missingPaths":["reports/ruijin-2025.pdf"]' in feedback
    assert "将 details.missingPaths 作为 artifact_paths" in feedback
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
