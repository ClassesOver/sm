from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from smart_reporting.coding import AgnoCodingExecutor, CodingScope
from smart_reporting.task_execution.models import AttemptSnapshot, AttemptState


class RecordingAgent:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _events(self) -> AsyncIterator[object]:
        if False:
            yield object()

    def arun(self, *args, **kwargs):
        self.calls.append(("arun", kwargs))
        return self._events()

    def acontinue_run(self, **kwargs):
        self.calls.append(("continue", kwargs))
        return self._events()

    async def aget_run_output(self, **kwargs):
        self.calls.append(("state", kwargs))
        return None


@pytest.mark.anyio
async def test_executor_uses_stable_internal_session_separate_from_facade_thread():
    agent = RecordingAgent()
    executor = AgnoCodingExecutor(lambda _agent_id: agent)  # type: ignore[arg-type]
    scope = CodingScope("external-run", "user", "facade-thread", "sandbox", "coding-agent")
    attempt = AttemptSnapshot(
        internal_run_id="internal-run",
        external_run_id="external-run",
        attempt_no=0,
        state=AttemptState.RUNNING,
        resume_count=0,
        lease_epoch=1,
    )

    _ = [event async for event in executor.arun(scope, attempt, "work", dependencies={})]
    _ = [
        event async for event in executor.acontinue_run(scope, attempt, "continue", dependencies={})
    ]
    await executor.state(scope, attempt)

    session_ids = [str(kwargs["session_id"]) for _name, kwargs in agent.calls]
    assert len(set(session_ids)) == 1
    assert session_ids[0].startswith("coding-")
    assert session_ids[0] != scope.thread_id
