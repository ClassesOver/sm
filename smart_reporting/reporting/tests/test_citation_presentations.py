from __future__ import annotations

import datetime
import uuid

import pytest
from agno.run import RunContext

from smart_reporting.reporting.workflow.runtime.publication import _coverage_period_bounds
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY, WorkspaceReportService

_DAILY = {
    (datetime.date(2025, 1, 1) + datetime.timedelta(days=offset)).isoformat()
    for offset in range(365)
}


def _presentations(periods: list[str]) -> list[dict[str, object]]:
    return [
        {
            "citationId": f"citation_{index:03d}",
            "label": "门诊日报表",
            "coverageItems": [{"label": "门诊量明细", "periods": periods}],
        }
        for index in range(10)
    ]


def _service_with_job() -> tuple[WorkspaceReportService, RunContext, str]:
    job_id = str(uuid.uuid4())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    service = WorkspaceReportService(object())  # type: ignore[arg-type]
    run_context.session_state[REPORT_JOBS_STATE_KEY] = {
        job_id: {"jobId": job_id, "_threadBinding": service._thread_binding("session-1")}
    }
    return service, run_context, job_id


def test_coverage_periods_keep_bounds_for_fine_grained_data() -> None:
    assert _coverage_period_bounds({"2025-02", "2025-01"}) == ["2025-01", "2025-02"]
    assert _coverage_period_bounds(_DAILY) == ["2025-01-01", "2025-12-31"]


@pytest.mark.anyio
async def test_daily_coverage_presentations_fit_job_state() -> None:
    service, run_context, job_id = _service_with_job()

    # 完整日粒度期间约 48 KB，超过绑定边界；保留首尾后可以正常绑定。
    await service.bind_citation_presentations(
        job_id, _presentations(_coverage_period_bounds(_DAILY)), run_context
    )


@pytest.mark.anyio
async def test_rebinding_ignores_period_detail_but_rejects_changed_citations() -> None:
    service, run_context, job_id = _service_with_job()
    await service.bind_citation_presentations(
        job_id, _presentations(["2025-01", "2025-02", "2025-03"]), run_context
    )

    # 历史运行保存了完整期间，新版本只保存首尾，不应被判为冲突。
    await service.bind_citation_presentations(
        job_id, _presentations(["2025-01", "2025-03"]), run_context
    )
    changed = _presentations(["2025-01", "2025-03"])
    changed[0]["label"] = "住院日报表"
    with pytest.raises(Exception, match="已经绑定且内容不同"):
        await service.bind_citation_presentations(job_id, changed, run_context)
