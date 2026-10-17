"""下钻线程在请求超时或取消后仍遵守并发和关闭约束。"""

import asyncio
import threading

import pytest

from smart_reporting.reporting.models import ReportingError

from . import test_report_editor_trace as editor_fixtures


@pytest.fixture(autouse=True)
def reset_registered_manifests():
    editor_fixtures._REGISTERED_MANIFESTS.clear()
    yield
    editor_fixtures._REGISTERED_MANIFESTS.clear()


@pytest.mark.anyio
@pytest.mark.parametrize("threshold,capacity", [(0, 1), (10**9, 4)], ids=["large", "small"])
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
@pytest.mark.parametrize("worker_fails", [False, True], ids=["success", "failure"])
async def test_drilldown_holds_capacity_until_worker_exits(
    tmp_path, monkeypatch, threshold, capacity, stop, worker_fails,
):
    from smart_reporting.report_editor import trace_sources

    editor, grants, _ = await editor_fixtures._make_editor(tmp_path, with_fact_file=True, with_drilldown=True)
    raw, _ = await grants.issue(editor_fixtures._context())
    _, session = await grants.exchange(raw)
    monkeypatch.setattr(trace_sources, "_DRILLDOWN_LARGE_FILE_BYTES", threshold)
    monkeypatch.setattr(trace_sources, "_DRILLDOWN_TIMEOUT_SECONDS", 0.5 if stop == "timeout" else 5)
    original = editor.trace._drilldown.drilldown
    loop = asyncio.get_running_loop()
    release = threading.Event()
    started = asyncio.Event()
    lock = threading.Lock()
    active = total_started = peak = 0

    def blocked(*args, **kwargs):
        nonlocal active, total_started, peak
        with lock:
            active += 1
            total_started += 1
            peak = max(peak, active)
            if active == capacity:
                loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise TimeoutError("test worker was not released")
            if worker_fails:
                raise ValueError("calculation failed after request ended")
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(editor.trace._drilldown, "drilldown", blocked)

    async def request():
        return await editor.trace_drilldown_metric(
            editor_fixtures._context(), session, "income_total", dataset_id=editor_fixtures.DATASET_ID, dimension_code="branch",
        )

    requests = [asyncio.create_task(request()) for _ in range(capacity)]
    closing = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        if stop == "cancel":
            for task in requests:
                task.cancel()
        outcomes = await asyncio.gather(*requests, return_exceptions=True)
        for outcome in outcomes:
            if stop == "cancel":
                assert isinstance(outcome, asyncio.CancelledError)
            else:
                assert isinstance(outcome, ReportingError)
                assert outcome.code == "resource_limit_exceeded"
        assert active == capacity

        # Waiting requests must time out without ever launching extra work.
        monkeypatch.setattr(trace_sources, "_DRILLDOWN_TIMEOUT_SECONDS", 0.02)
        for _ in range(2):
            with pytest.raises(ReportingError) as error:
                await request()
            assert error.value.code == "resource_limit_exceeded"
        assert total_started == peak == capacity

        closing = asyncio.create_task(editor.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
    finally:
        release.set()
        await asyncio.gather(*requests, return_exceptions=True)
        if closing is not None:
            await asyncio.wait_for(closing, 3)
        else:
            await editor.aclose()
    assert active == 0
    assert not editor.trace._drilldown_tasks
    assert editor.trace._drilldown_limiter.borrowed_tokens == 0
    assert editor.trace._drilldown_large_limiter.borrowed_tokens == 0

    # Capacity is reusable once the actual calculations finish.
    monkeypatch.setattr(trace_sources, "_DRILLDOWN_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(editor.trace._drilldown, "drilldown", original)
    page = await request()
    assert page["reconciliation"]["passed"] is True
    await editor.aclose()
