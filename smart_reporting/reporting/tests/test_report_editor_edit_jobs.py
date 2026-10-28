"""改图与改表任务清理的时间边界契约。"""

from types import SimpleNamespace

import pytest

from smart_reporting.report_editor import chart_ai, table_ai


@pytest.mark.parametrize("module", [chart_ai, table_ai])
def test_finished_jobs_keep_running_and_start_retention_when_completion_is_observed(
    module, monkeypatch
):
    service_class = (
        chart_ai.ChartAIEditService if module is chart_ai else table_ai.TableAIEditService
    )
    service = object.__new__(service_class)
    clock = [7200.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    running = SimpleNamespace(task=SimpleNamespace(done=lambda: False), finished_at=None)
    observed = SimpleNamespace(task=SimpleNamespace(done=lambda: True), finished_at=None)
    boundary = SimpleNamespace(task=SimpleNamespace(done=lambda: True), finished_at=3600.0)
    expired = SimpleNamespace(task=SimpleNamespace(done=lambda: True), finished_at=3599.0)
    service._jobs = {
        "running": running, "observed": observed, "boundary": boundary, "expired": expired
    }

    service._prune_jobs()

    assert set(service._jobs) == {"running", "observed", "boundary"}
    assert running.finished_at is None
    assert observed.finished_at == 7200.0
    clock[0] = 10800.0
    service._prune_jobs()
    assert set(service._jobs) == {"running", "observed"}
    assert observed.finished_at == 7200.0
    clock[0] += 0.1
    service._prune_jobs()
    assert set(service._jobs) == {"running"}


@pytest.mark.parametrize("module", [chart_ai, table_ai])
def test_hourly_window_excludes_exact_boundary_and_removes_empty_user(module, monkeypatch):
    service_class = (
        chart_ai.ChartAIEditService if module is chart_ai else table_ai.TableAIEditService
    )
    service = object.__new__(service_class)
    monkeypatch.setattr(module.time, "monotonic", lambda: 7200.0)
    service._hourly = {"user": [3599.0, 3600.0, 3600.1, 7199.0], "other": [1.0]}

    service._prune_hourly("user")

    assert service._hourly == {"user": [3600.1, 7199.0], "other": [1.0]}
    service._prune_hourly("other")
    service._prune_hourly("missing")
    assert service._hourly == {"user": [3600.1, 7199.0]}
