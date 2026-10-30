from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.contract import ReportRequestEnvelope
from smart_reporting.reporting.delivery.draft_v1 import ReportChartRegistration
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisChart,
    ChartVisualInspectionReceipt,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime import analysis as runtime_analysis
from smart_reporting.reporting.workflow.runtime.analysis import _visualization_output_paths
from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.sections import _analysis_chart_from_registration
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    _validated_visual_receipts,
)


def _request(**overrides: object) -> ReportRequestEnvelope:
    return ReportRequestEnvelope.model_validate(
        {
            "reportGoal": "分析收入趋势",
            "period": {"start": "2026-01-01", "end": "2026-08-31"},
            **overrides,
        }
    )


def _chart_payload(**overrides: object) -> dict[str, object]:
    return {
        "chartId": "income-trend",
        "sourcePath": "analysis/charts/income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01 至 2026-08",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
        **overrides,
    }


def _draft_payload(**overrides: object) -> dict[str, object]:
    return {
        **_chart_payload(**overrides),
        "visualForm": "按月折线图",
        "dataBindings": [
            {
                "analysisId": "analysis_001",
                "factPath": "facts/analysis_001.json",
                "dataPath": "metrics[0].periodValues",
                "fields": ["period", "value"],
                "role": "月度趋势",
            }
        ],
    }


def test_report_request_only_accepts_static_visualization_mode() -> None:
    assert _request().visualization_mode == "static"
    assert _request(visualizationMode="static").model_dump(by_alias=True)["visualizationMode"] == "static"
    with pytest.raises(ValidationError):
        _request(visualizationMode="interactive")
    with pytest.raises(ValidationError):
        _request(visualizationMode="auto")


def test_chart_contracts_reject_renderer_and_companion_fields() -> None:
    draft = ChartDraft.model_validate(_draft_payload())
    registration = ReportChartRegistration.model_validate(_chart_payload())
    frozen = AnalysisChart.model_validate(
        {
            "chartId": "income-trend",
            "sourceFile": {"path": "analysis/charts/income.png", "size": 10, "sha256": "a" * 64},
            "title": "收入趋势",
            "altText": "收入趋势图",
            "citationIds": ["citation-1"],
            "metricCodes": ["income"],
            "currentPeriod": "2026-01 至 2026-08",
            "sourceDatasetId": "dataset-1",
            "aggregationGrain": "month",
        }
    )

    assert "renderer" not in draft.model_dump()
    assert "renderer" not in registration.model_dump()
    assert "renderer" not in frozen.model_dump()
    for model, payload in (
        (ChartDraft, _draft_payload(renderer="plotly", interactivePath="chart.plotly.json")),
        (ReportChartRegistration, _chart_payload(renderer="plotly", interactivePath="chart.plotly.json")),
        (AnalysisChart, {**frozen.model_dump(by_alias=True), "renderer": "plotly"}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_visualization_task_signs_only_static_image_outputs() -> None:
    chart = ChartDraft.model_validate(_draft_payload())
    assert _visualization_output_paths(VisualizationPlanDraft(charts=(chart,))) == (
        "analysis/charts/income.png",
    )


def test_visualization_registration_drops_coding_only_plan_fields() -> None:
    chart = ChartDraft.model_validate(_draft_payload(
        standardValueFields=['actual'], standardLabelField='科室',
        standardView={'kind': 'group', 'labelField': '科室', 'valueFields': ['actual']},
        standardAxes={'scale': 'symlog'},
    ))

    payload = runtime_analysis._visualization_registration_payload(chart)

    assert "visualForm" not in payload
    assert "dataBindings" not in payload
    assert not any(key.startswith('standard') for key in payload)
    assert ReportChartRegistration.model_validate(payload).chart_id == "income-trend"


def test_static_visual_review_requires_raster_receipt() -> None:
    chart = ChartDraft.model_validate(_draft_payload())
    image = FileIdentity(path=chart.source_path, size=10, sha256="a" * 64)
    script = FileIdentity(path="analysis/charts/chart.py", size=5, sha256="c" * 64)
    result = CodeGenerationResult(
        script_file=script,
        execution_receipt=ExecutionReceipt(
            runId="run-1", sourceFile=script, outputFiles=(image,)
        ),
        visual_inspection_receipts=(
            ChartVisualInspectionReceipt(
                sourcePath=image.path,
                sha256=image.sha256,
                modelId="vision-1",
                reviewed=True,
                requiresRevision=False,
            ),
        ),
    )

    assert len(_validated_visual_receipts(result, VisualizationPlanDraft(charts=(chart,)))) == 1


def test_analysis_freeze_binds_static_chart_without_leaking_source_paths() -> None:
    registration = _chart_payload()
    chart = _analysis_chart_from_registration(
        registration,
        {"path": "analysis/charts/income.png", "size": 10, "sha256": "a" * 64},
    )

    assert chart.source_file.path == "analysis/charts/income.png"
    assert "interactiveFile" not in chart.model_dump(by_alias=True)


_SOURCE_FILE = {"path": "analysis/charts/income.png", "size": 10, "sha256": "a" * 64}
_VISION_RECEIPT = {
    "sourcePath": "analysis/charts/income.png",
    "sha256": "a" * 64,
    "inspectionMode": "vision",
    "visualReviewStatus": "passed",
    "modelId": "vision-model",
    "reviewed": True,
    "requiresRevision": False,
}


@pytest.mark.parametrize(
    ("receipt", "expected_mode", "expected_status"),
    [
        (_VISION_RECEIPT, "vision", "passed"),
        ({**_VISION_RECEIPT, "sha256": "c" * 64}, "deterministic", "not_run"),
        (None, "deterministic", "not_run"),
    ],
    ids=["matching-vision-receipt", "stale-receipt", "no-receipt"],
)
def test_analysis_freeze_keeps_matching_visual_receipt(
    receipt: dict[str, object] | None, expected_mode: str, expected_status: str
) -> None:
    chart = _analysis_chart_from_registration(_chart_payload(), _SOURCE_FILE, visual_receipt=receipt)

    frozen = chart.model_dump(by_alias=True)["visualInspectionReceipt"]
    assert frozen["inspectionMode"] == expected_mode
    assert frozen["visualReviewStatus"] == expected_status
