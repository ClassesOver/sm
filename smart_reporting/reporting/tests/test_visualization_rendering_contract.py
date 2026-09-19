from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.contract import ReportRequestEnvelope
from smart_reporting.reporting.delivery.draft_v1 import ReportChartRegistration
from smart_reporting.reporting.workflow.checkpoint import AnalysisChart
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDraft


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


def test_report_request_visualization_mode_defaults_to_auto_and_serializes_override() -> None:
    assert _request().visualization_mode == "auto"
    assert _request(visualizationMode="interactive").model_dump(by_alias=True)[
        "visualizationMode"
    ] == "interactive"


def test_legacy_chart_payload_defaults_to_matplotlib() -> None:
    draft = ChartDraft.model_validate(_chart_payload())
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
