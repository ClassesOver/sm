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
        "dataBindings": [{
            "analysisId": "analysis_001",
            "factPath": "facts/analysis_001.json",
            "dataPath": "metrics[0].periodValues",
            "fields": ["period", "value"],
            "role": "月度趋势",
        }],
    }


def test_report_request_visualization_mode_defaults_to_auto_and_serializes_override() -> None:
    assert _request().visualization_mode == "auto"
    assert _request(visualizationMode="interactive").model_dump(by_alias=True)[
        "visualizationMode"
    ] == "interactive"


def test_legacy_chart_payload_defaults_to_matplotlib() -> None:
    draft = ChartDraft.model_validate(_draft_payload())
    registration = ReportChartRegistration.model_validate(_chart_payload())

    assert draft.renderer == "matplotlib"
    assert draft.interactive_path is None
    assert registration.renderer == "matplotlib"
    assert registration.interactive_path is None


def test_plotly_chart_requires_safe_plotly_json_companion() -> None:
    with pytest.raises(ValidationError, match="interactivePath"):
        ReportChartRegistration.model_validate(_chart_payload(renderer="plotly"))

    registration = ReportChartRegistration.model_validate(
        _chart_payload(
            renderer="plotly",
            interactivePath="analysis/charts/income.plotly.json",
        )
    )

    assert registration.interactive_path == "analysis/charts/income.plotly.json"


@pytest.mark.parametrize(
    ("renderer", "interactive_path"),
    [
        ("matplotlib", "analysis/charts/income.plotly.json"),
        ("plotly", "analysis/charts/income.json"),
        ("plotly", "../income.plotly.json"),
    ],
)
def test_chart_rejects_inconsistent_interactive_companion(
    renderer: str, interactive_path: str
) -> None:
    with pytest.raises(ValidationError):
        ChartDraft.model_validate(
            _chart_payload(renderer=renderer, interactivePath=interactive_path)
        )


def test_analysis_chart_preserves_plotly_companion_identity() -> None:
    chart = AnalysisChart.model_validate(
        {
            key: value
            for key, value in _chart_payload(
                renderer="plotly",
            ).items()
            if key not in {"sourcePath"}
        }
        | {
            "sourceFile": {
                "path": "analysis/charts/income.png",
                "size": 10,
                "sha256": "a" * 64,
            },
            "interactiveFile": {
                "path": "analysis/charts/income.plotly.json",
                "size": 20,
                "sha256": "b" * 64,
            },
        }
    )

    assert chart.renderer == "plotly"
    assert chart.interactive_file is not None
    assert chart.interactive_file.sha256 == "b" * 64


def test_visualization_task_signs_both_plotly_outputs() -> None:
    chart = ChartDraft.model_validate(
        _draft_payload(
            renderer="plotly",
            interactivePath="analysis/charts/income.plotly.json",
        )
    )

    assert _visualization_output_paths(VisualizationPlanDraft(charts=(chart,))) == (
        "analysis/charts/income.plotly.json",
        "analysis/charts/income.png",
    )


def test_visualization_registration_drops_coding_only_plan_fields() -> None:
    chart = ChartDraft.model_validate(_draft_payload())

    payload = runtime_analysis._visualization_registration_payload(chart)

    assert "visualForm" not in payload
    assert "dataBindings" not in payload
    assert ReportChartRegistration.model_validate(payload).chart_id == "income-trend"


def test_plotly_visual_review_only_requires_raster_receipt() -> None:
    chart = ChartDraft.model_validate(
        _draft_payload(
            renderer="plotly",
            interactivePath="analysis/charts/income.plotly.json",
        )
    )
    image = FileIdentity(path=chart.source_path, size=10, sha256="a" * 64)
    companion = FileIdentity(path=chart.interactive_path, size=20, sha256="b" * 64)
    script = FileIdentity(path="analysis/charts/chart.py", size=5, sha256="c" * 64)
    result = CodeGenerationResult(
        script_file=script,
        execution_receipt=ExecutionReceipt(
            runId="run-1", sourceFile=script, outputFiles=(image, companion)
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


def test_analysis_freeze_binds_plotly_identity_without_leaking_source_paths() -> None:
    registration = _chart_payload(
        renderer="plotly",
        interactivePath="analysis/charts/income.plotly.json",
    )
    chart = _analysis_chart_from_registration(
        registration,
        {"path": "analysis/charts/income.png", "size": 10, "sha256": "a" * 64},
        {"path": "analysis/charts/income.plotly.json", "size": 20, "sha256": "b" * 64},
    )

    assert chart.interactive_file is not None
    assert chart.interactive_file.path == "analysis/charts/income.plotly.json"
    assert "interactivePath" not in chart.model_dump(by_alias=True)


def test_analysis_freeze_rejects_missing_plotly_identity() -> None:
    registration = _chart_payload(
        renderer="plotly",
        interactivePath="analysis/charts/income.plotly.json",
    )
    with pytest.raises(ReportingError, match="交互文件"):
        _analysis_chart_from_registration(
            registration,
            {"path": "analysis/charts/income.png", "size": 10, "sha256": "a" * 64},
            None,
        )
