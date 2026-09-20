from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery import artifacts_v1
from smart_reporting.reporting.delivery.artifacts_v1 import ChartArtifact
from smart_reporting.reporting.workflow.runtime.publication import (
    _accepted_artifacts_match_manifest,
    _editor_interactive_charts,
)
from smart_reporting.reporting.workflow.runtime.sections import _archived_interactive_path


def _chart(**overrides: object) -> dict[str, object]:
    return {
        "path": "reports/revision-1/chart-001.png",
        "mediaType": "image/png",
        "size": 100,
        "sha256": "a" * 64,
        "chartId": "chart_001",
        "datasetIds": ["dataset-1"],
        **overrides,
    }


def test_static_chart_preserves_legacy_manifest_shape() -> None:
    chart = ChartArtifact.model_validate(_chart())

    assert chart.renderer == "matplotlib"
    assert chart.interactive_spec is None


def test_plotly_chart_manifest_binds_json_identity() -> None:
    chart = ChartArtifact.model_validate(
        _chart(
            renderer="plotly",
            interactiveSpec={
                "path": "reports/revision-1/chart-001.plotly.json",
                "mediaType": "application/vnd.plotly.v1+json",
                "size": 400,
                "sha256": "b" * 64,
            },
        )
    )

    assert chart.interactive_spec is not None
    assert chart.interactive_spec.sha256 == "b" * 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"renderer": "plotly"},
        {"renderer": "matplotlib", "interactiveSpec": {"path": "x.plotly.json", "mediaType": "application/vnd.plotly.v1+json", "size": 1, "sha256": "b" * 64}},
        {"renderer": "plotly", "interactiveSpec": {"path": "reports/revision-2/chart-001.plotly.json", "mediaType": "application/vnd.plotly.v1+json", "size": 1, "sha256": "b" * 64}},
    ],
)
def test_chart_rejects_missing_or_unbound_plotly_spec(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChartArtifact.model_validate(_chart(**overrides))


def test_authoritative_manifest_binds_plotly_json_as_accepted_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifacts_v1,
        "authoritative_citations",
        lambda _lineage: (
            artifacts_v1.Citation(
                citationId="citation_001",
                datasetId="dataset-1",
                requirementId="requirement-1",
                snapshotHash="c" * 64,
            ),
        ),
    )
    markdown_path = "reports/revision-1/report.md"
    image_path = "reports/revision-1/chart-001.png"
    spec_path = "reports/revision-1/chart-001.plotly.json"
    accepted = [
        {"path": markdown_path, "size": 100, "sha256": "d" * 64},
        {"path": image_path, "size": 200, "sha256": "a" * 64},
        {"path": spec_path, "size": 400, "sha256": "b" * 64},
    ]

    manifest = artifacts_v1.build_authoritative_manifest(
        report_id="report-1",
        revision=1,
        task_key="task-1",
        effective_profile_hash="e" * 64,
        markdown_path=markdown_path,
        markdown="![收入趋势](chart-001.png) [[citation:citation_001]]\n",
        accepted_artifacts=accepted,
        interactive_charts={image_path: spec_path},
        lineage=(),
        sections=("section_001",),
        section_numbers=("1",),
        heading_numbers=(
            artifacts_v1.HeadingNumber(
                level=2, number="1", title="收入", sectionCode="section_001",
                anchor="report-section-section_001",
            ),
        ),
    )

    assert manifest.charts[0].interactive_spec is not None
    assert manifest.charts[0].interactive_spec.path == spec_path
    assert _editor_interactive_charts(manifest) == {
        image_path: {"path": spec_path, "size": 400, "sha256": "b" * 64}
    }
    assert _accepted_artifacts_match_manifest(manifest, "reports/revision-1/manifest.json", accepted)

    without_spec = accepted[:-1]
    assert not _accepted_artifacts_match_manifest(
        manifest, "reports/revision-1/manifest.json", without_spec
    )


def test_plotly_companion_uses_static_chart_revision_stem() -> None:
    assert _archived_interactive_path("reports/revision-2/chart-003.png") == (
        "reports/revision-2/chart-003.plotly.json"
    )
