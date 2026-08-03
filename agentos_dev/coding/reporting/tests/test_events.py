from __future__ import annotations

import pytest

from agentos_dev.coding.reporting.events import ReportingEventBroker


@pytest.mark.anyio
async def test_reporting事件按序号重放且按用户隔离():
    broker = ReportingEventBroker()
    await broker.publish("user-1", "run-1", "workflow_step_started", {"stepId": "one"})
    await broker.publish("user-1", "run-1", "workflow_step_completed", {"stepId": "one"})
    await broker.publish("user-2", "run-1", "workflow_step_started", {"stepId": "private"})

    stream = broker.subscribe("user-1", "run-1", after=0)
    first = await anext(stream)
    second = await anext(stream)
    await stream.aclose()

    assert (first.sequence, first.type, first.data) == (
        1,
        "workflow_step_started",
        {"stepId": "one"},
    )
    assert (second.sequence, second.type, second.data) == (
        2,
        "workflow_step_completed",
        {"stepId": "one"},
    )
