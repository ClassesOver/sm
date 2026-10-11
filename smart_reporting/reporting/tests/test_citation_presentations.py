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
    # 首尾写成一个区间，避免两项并列被读成两个孤立期间；写不下时保留首尾两项。
    assert _coverage_period_bounds(_DAILY) == ["2025-01-01至2025-12-31"]
    stamps = {f"2025-01-{day:02d} 00:00:00" for day in range(1, 31)}
    assert _coverage_period_bounds(stamps) == ["2025-01-01 00:00:00", "2025-01-30 00:00:00"]


@pytest.mark.anyio
async def test_daily_coverage_presentations_fit_job_state() -> None:
    service, run_context, job_id = _service_with_job()

    # 完整日粒度期间约 48 KB，超过绑定边界；保留首尾后可以正常绑定。
    await service.bind_citation_presentations(
        job_id, _presentations(_coverage_period_bounds(_DAILY)), run_context
    )


@pytest.mark.anyio
async def test_large_source_link_lists_are_bounded_in_job_state() -> None:
    service, run_context, job_id = _service_with_job()
    presentations = _presentations(["2025-01", "2025-12"])
    for index, presentation in enumerate(presentations):
        presentation["links"] = [
            {"subjectId": f"subject-{item}", "label": "正文结论", "url": f"https://reports.example/{index}/{item}"}
            for item in range(100)
        ]

    await service.bind_citation_presentations(job_id, presentations, run_context)

    saved = run_context.session_state[REPORT_JOBS_STATE_KEY][job_id]["_citationPresentations"]
    assert all(len(item["links"]) == 2 for item in saved)
    assert all(item["links"][0]["subjectId"] == "subject-0" for item in saved)
    assert all(item["links"][1]["subjectId"] == "subject-99" for item in saved)


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


def test_citation_presentation_scope_uses_reader_facing_period_roles() -> None:
    from smart_reporting.reporting.workflow.query_pipeline import DatasetLineage
    from smart_reporting.reporting.workflow.runtime.publication import _citation_presentations

    lineage = DatasetLineage(
        datasetId="dataset-1", sourceId="source-1", requirementId="requirement-1",
        sqlHash="a" * 64, rowCount=12, size=100, sha256="b" * 64, periodRoles=("current", "yoy"),
    )
    presentations = _citation_presentations(
        lineage=(lineage,), requirements=(), analyses=(), snapshots=(), observed_facts=[],
    )
    # current/yoy 是内部代码，附录“范围”写本期、同比基期。
    assert presentations[0]["scope"] == "本期、同比基期"
