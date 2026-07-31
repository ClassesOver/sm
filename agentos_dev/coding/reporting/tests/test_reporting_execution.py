import asyncio
from types import SimpleNamespace

import pytest

from agentos_dev.coding.reporting import execution as execution_module
from agentos_dev.coding.reporting.execution import ReportTaskRunner
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.task_execution import TaskScope, TaskState


class _Session:
    def __init__(self, _repository, _scope):
        self.lease = SimpleNamespace(owner="lease", epoch=2)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def assert_alive(self):
        return None


class _Repository:
    def __init__(self, *, finish_requested: bool, initial_state: TaskState = TaskState.NEW):
        self.finish_requested = finish_requested
        self.initial_state = initial_state
        self.reads = 0
        self.cancelled = False
        self.resumed = False

    async def get_task_snapshot(self, _task_id):
        self.reads += 1
        state = (
            self.initial_state
            if self.reads == 1
            else (TaskState.FINISHING if self.finish_requested else TaskState.ACTIVE)
        )
        return SimpleNamespace(state=state, state_version=self.reads, finish_receipt=None)

    async def open_initial(self, _task_id, _lease, _version):
        return (
            SimpleNamespace(state=TaskState.ACTIVE),
            SimpleNamespace(attempt_no=0, internal_run_id="internal-run"),
        )

    async def resume_current(self, _task_id, _lease, _version):
        self.resumed = True
        return (
            SimpleNamespace(state=TaskState.ACTIVE),
            SimpleNamespace(attempt_no=0, internal_run_id="internal-run"),
        )

    async def attempt_instruction(self, _task_id, _attempt_no):
        return "生成报表"

    async def finalize_finish(self, _task_id, _lease, _version, *, agno_status):
        assert agno_status
        return SimpleNamespace(finish_receipt={"artifacts": [], "acceptance": {"requirements": []}})

    async def cancel_and_reject(self, _scope):
        self.cancelled = True


class _Cleanup:
    def __init__(self) -> None:
        self.disconnected_epochs: list[int] = []

    async def cleanup_old_epoch(self, *_args):
        return None

    async def cleanup_disconnect(self, _scope, epoch):
        self.disconnected_epochs.append(epoch)


@pytest.mark.anyio
async def test_report_task_runner直接运行agno_worker并完成正式回执(monkeypatch):
    repository = _Repository(finish_requested=True)
    worker = SimpleNamespace(arun=lambda *_args, **_kwargs: SimpleNamespace(status="completed"))
    cleanup = _Cleanup()
    monkeypatch.setattr(execution_module, "TaskSession", _Session)
    runner = ReportTaskRunner(repository, worker, cleanup)

    receipt = await runner.run(_scope())

    assert receipt == {"artifacts": [], "acceptance": {"requirements": []}}
    assert repository.cancelled is False
    assert cleanup.disconnected_epochs == []


@pytest.mark.anyio
async def test_report_task_runner未调用finish_task时拒绝并取消任务(monkeypatch):
    repository = _Repository(finish_requested=False)
    worker = SimpleNamespace(arun=lambda *_args, **_kwargs: SimpleNamespace(status="completed"))
    cleanup = _Cleanup()
    monkeypatch.setattr(execution_module, "TaskSession", _Session)
    runner = ReportTaskRunner(repository, worker, cleanup)

    with pytest.raises(ReportingError) as captured:
        await runner.run(_scope())

    assert captured.value.code == "report_worker_failed"
    assert repository.cancelled is True
    assert cleanup.disconnected_epochs == [2]


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError("provider failed"), asyncio.CancelledError()])
async def test_report_task_runner异常或取消时拒绝任务并清理execution(monkeypatch, error):
    repository = _Repository(finish_requested=False)
    cleanup = _Cleanup()

    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(execution_module, "TaskSession", _Session)
    runner = ReportTaskRunner(repository, SimpleNamespace(arun=fail), cleanup)

    with pytest.raises(type(error)):
        await runner.run(_scope())

    assert repository.cancelled is True
    assert cleanup.disconnected_epochs == [2]


@pytest.mark.anyio
async def test_report_task_runner外部取消等待清理完成后再传播(monkeypatch):
    repository = _Repository(finish_requested=False)
    cleanup = _Cleanup()
    started = asyncio.Event()

    async def wait_forever(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(execution_module, "TaskSession", _Session)
    runner = ReportTaskRunner(repository, SimpleNamespace(arun=wait_forever), cleanup)
    task = asyncio.create_task(runner.run(_scope()))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.cancelled is True
    assert cleanup.disconnected_epochs == [2]


@pytest.mark.anyio
async def test_report_task_runner从agno_checkpoint恢复同一worker_run(monkeypatch):
    repository = _Repository(finish_requested=True, initial_state=TaskState.ACTIVE)
    continued: list[dict] = []

    def unexpected_arun(*_args, **_kwargs):
        raise AssertionError("恢复已有 Attempt 时不应创建新的 Agno run。")

    def continue_run(**kwargs):
        continued.append(kwargs)
        return SimpleNamespace(status="completed")

    worker = SimpleNamespace(arun=unexpected_arun, acontinue_run=continue_run)
    cleanup = _Cleanup()
    monkeypatch.setattr(execution_module, "TaskSession", _Session)
    runner = ReportTaskRunner(repository, worker, cleanup)

    receipt = await runner.run(_scope())

    assert receipt == {"artifacts": [], "acceptance": {"requirements": []}}
    assert repository.resumed is True
    assert len(continued) == 1
    call = continued[0]
    assert call["run_id"] == "internal-run"
    assert call["stream"] is False
    assert call["session_id"] == "report-worker-b2c800fd50c58fe2bf0528a53a85c34e"
    assert call["user_id"] == "user"
    assert call["dependencies"][execution_module.TASK_EXECUTION_DEPENDENCY] == {
        "externalRunId": "task",
        "threadId": "thread",
        "sandboxId": "sandbox",
        "leaseOwner": "lease",
        "leaseEpoch": 2,
        "attemptNo": 0,
    }


def _scope() -> TaskScope:
    return TaskScope("task", "user", "thread", "sandbox", "report-worker")
