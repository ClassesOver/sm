from pathlib import PurePosixPath

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.workflow.checkpoint import FileIdentity, SectionClaimSubmission
from smart_reporting.reporting.workflow.runtime.phase_models import (
    AnalysisReworkDecision,
    ChartDraft,
    RenderSectionDecision,
    SectionDecisionAdapter,
    SectionDecisionOutput,
    VisualizationScriptDraft,
)


def _chart(path: str = "report/charts/chart-001.png") -> ChartDraft:
    return ChartDraft(
        chartId="chart_001",
        sourcePath=path,
        title="收入趋势",
        altText="收入按月趋势",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2026-08",
        sourceDatasetId="dataset_001",
        aggregationGrain="month",
    )


def test_visualization_script_draft_accepts_bound_chart_paths() -> None:
    draft = VisualizationScriptDraft(
        scriptPath="report/charts/charts.py",
        pythonSource="print('ok')",
        charts=(_chart(),),
    )
    assert draft.charts[0].chart_id == "chart_001"


@pytest.mark.parametrize(
    "path", ["/tmp/chart.png", "../chart.png", "charts\\chart.png", "chart.svg"]
)
def test_chart_draft_rejects_unsafe_source_path(path: str) -> None:
    with pytest.raises(ValidationError):
        _chart(path)


def test_section_decision_is_a_render_or_rework_union() -> None:
    rendered = RenderSectionDecision(
        sectionCode="section_001",
        blocks=(
            ReportDraftBlock(
                blockId="block_001",
                markdown="收入保持增长。",
                citationIds=("citation_001",),
                claimIds=("claim_001",),
            ),
        ),
        claims=(
            SectionClaimSubmission(
                claimId="claim_001",
                metricCode="revenue",
                value=100,
                managementQuestionRef="analysis_001",
                citationIds=("citation_001",),
            ),
        ),
    )
    parsed = SectionDecisionAdapter.validate_python(rendered.model_dump(mode="json", by_alias=True))
    assert isinstance(parsed, RenderSectionDecision)
    output = SectionDecisionOutput.model_validate_json(rendered.model_dump_json(by_alias=True))
    assert isinstance(output.root, RenderSectionDecision)

    with pytest.raises(ValidationError):
        AnalysisReworkDecision(
            sectionCode="section_001",
            analysisIds=(),
            reason="缺少证据",
            missingEvidence=("dataset_001",),
        )


def test_section_decision_normalizes_single_render_wrapper() -> None:
    output = SectionDecisionOutput.model_validate(
        {
            "render": {
                "sectionCode": "section_001",
                "blocks": [
                    {
                        "blockId": "block_001",
                        "markdown": "收入保持增长。",
                        "citationIds": ["citation_001"],
                        "claimIds": ["claim_001"],
                    }
                ],
                "claims": [
                    {
                        "claimId": "claim_001",
                        "metricCode": "revenue",
                        "value": 100,
                        "managementQuestionRef": "analysis_001",
                        "citationIds": ["citation_001"],
                    }
                ],
            }
        }
    )

    assert isinstance(output.root, RenderSectionDecision)
    assert output.root.kind == "render"


def test_section_decision_normalizes_numeric_comparison_display_value() -> None:
    output = SectionDecisionOutput.model_validate(
        {
            "kind": "render",
            "sectionCode": "section_001",
            "blocks": [
                {
                    "blockId": "block_001",
                    "markdown": "收入下降。",
                    "citationIds": ["citation_001"],
                    "claimIds": ["claim_001"],
                }
            ],
            "claims": [
                {
                    "claimId": "claim_001",
                    "metricCode": "revenue",
                    "value": 100,
                    "comparison": -40000000,
                    "managementQuestionRef": "analysis_001",
                    "citationIds": ["citation_001"],
                }
            ],
        }
    )

    assert output.root.claims[0].comparison == "-40000000"


def test_file_identity_keeps_existing_safe_path_contract() -> None:
    identity = FileIdentity(path="report/evidence.json", size=1, sha256="a" * 64)
    assert PurePosixPath(identity.path).is_absolute() is False
