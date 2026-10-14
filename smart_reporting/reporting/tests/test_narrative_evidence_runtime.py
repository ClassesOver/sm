"""分析执行分区与最终目录的运行时边界。"""

from datetime import date
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput

from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
from smart_reporting.reporting.hospital_operation.outline import ReportOutline
from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
from smart_reporting.reporting.workflow.runtime.base import (
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    _frozen_outline,
)


def analysis_plan():
    return DetailedAnalysisPlan.model_validate({
        "datasetIds": ["dataset_001"],
        "analyses": [{
            "analysisId": f"analysis_{index:03d}", "domain": "income",
            "managementQuestion": "解释经营变化", "primaryMetricFamily": "income",
            "datasetIds": ["dataset_001"], "fields": ["amount"],
            "metrics": ["income_total"], "periods": [], "actions": ["sum"],
            "evidenceSummary": "总额与趋势", "suggestedSection": "收入分析",
            "completionConditions": ["冻结事实"],
        } for index in range(1, 4)],
    })


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_evidence_stage_creates_internal_partition_without_outline_model(anyio_backend):
    state = {REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: analysis_plan().model_dump(mode="json", by_alias=True)}
    observed = {}

    class Runtime(RuntimeAnalysisMixin):
        def _state(self, context):
            return state

        def _envelope(self, context):
            return SimpleNamespace(report_type="comprehensive")

        async def run_reporting_analysis(self, step_input, context):
            observed["outline"] = _frozen_outline(state)
            assert state["_narrative_evidence_only"] is True
            return StepOutput(content={"status": "evidence_frozen"})

    await Runtime().run_analysis_evidence(None, RunContext(run_id="run-1", session_id="session-1"))
    assert observed["outline"].sections[0].analysis_ids == ("analysis_001", "analysis_002", "analysis_003")
    assert "_narrative_evidence_only" not in state


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_document_context_is_bound_only_after_narrative_freeze(anyio_backend):
    state = {"_narrative_evidence_only": True}
    bound = {}

    async def bind(job_id, document_context, **kwargs):
        if bound and bound != document_context:
            raise AssertionError("不可改写已绑定的文档目录")
        bound.update(document_context)

    runtime = SimpleNamespace(
        _state=lambda context: state,
        _envelope=lambda context: SimpleNamespace(period=SimpleNamespace(start=date(2025, 1, 1), end=date(2025, 12, 31))),
        _profile=lambda context: SimpleNamespace(document_branding=SimpleNamespace(
            organization_name="医院", generated_by_label="运营管理部", watermark_text="内部资料",
        )),
        _tool_context=lambda context: context, report_tools=SimpleNamespace(bind_document_context=bind),
    )
    internal = ReportOutline(reportType="comprehensive", title="运营分析报告", sections=[{
        "code": "section_001", "sectionNumber": "1", "title": "分析任务执行分区",
        "analysisIds": ["analysis_001"],
    }])
    await RuntimeAnalysisMixin._bind_report_document_context(runtime, None, outline=internal, job_id="job-1")
    assert not bound
    assert REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY not in state
    state.pop("_narrative_evidence_only")
    narrative = internal.model_copy(update={"sections": (
        internal.sections[0].model_copy(update={"title": "收入增长与结构风险"}),
    )})
    state[REPORT_OUTLINE_STATE_KEY] = narrative.model_dump(mode="json", by_alias=True)
    await RuntimeAnalysisMixin._bind_report_document_context(runtime, None, outline=narrative, job_id="job-1")
    assert [section["title"] for section in bound["sections"]] == ["收入增长与结构风险"]
