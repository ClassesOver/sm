from __future__ import annotations

import pytest

from agentos_dev.coding.reporting.artifacts_v1 import (
    REQUIRED_REPORT_SECTIONS,
    ArtifactFile,
    ChartArtifact,
    Citation,
    PdfArtifactManifest,
    ReportArtifactManifest,
    dataset_snapshot_hash,
    validate_rendered_artifacts,
)
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.workflow_v1 import DatasetLineage


def lineage() -> tuple[DatasetLineage, ...]:
    return (
        DatasetLineage(
            datasetId="income-monthly-dataset",
            sourceId="operations",
            requirementId="income-monthly",
            sqlHash="a" * 64,
            rowCount=12,
            size=2048,
            sha256="b" * 64,
        ),
    )


def draft() -> ReportArtifactManifest:
    return ReportArtifactManifest(
        reportId="report-1",
        revision=1,
        codingTaskKey="report-coding-stable",
        datasetSnapshotHash=dataset_snapshot_hash(lineage()),
        effectiveProfileHash="f" * 64,
        markdown=ArtifactFile(
            path="reports/revision-1/report.md",
            mediaType="text/markdown",
            size=4096,
            sha256="c" * 64,
        ),
        charts=(
            ChartArtifact(
                chartId="income-trend",
                path="reports/revision-1/income-trend.png",
                mediaType="image/png",
                size=1024,
                sha256="d" * 64,
                datasetIds=("income-monthly-dataset",),
            ),
        ),
        citations=(
            Citation(
                citationId="citation-income",
                datasetId="income-monthly-dataset",
                requirementId="income-monthly",
            ),
        ),
        sections=tuple(sorted(REQUIRED_REPORT_SECTIONS)),
    )


def test_产物清单绑定不可变数据集图表引用和revision():
    current = draft()
    rendered = PdfArtifactManifest(
        reportId="report-1",
        revision=1,
        pdf=ArtifactFile(
            path="reports/revision-1/report.pdf",
            mediaType="application/pdf",
            size=8192,
            sha256="e" * 64,
        ),
        pageCount=8,
        renderedChartIds=("income-trend",),
        citationIds=("citation-income",),
        sections=current.sections,
    )

    validate_rendered_artifacts(current, rendered, lineage=lineage())


def test_报告产物只要求领域无关的通用章节():
    assert REQUIRED_REPORT_SECTIONS == {
        "executive_summary",
        "scope_and_methodology",
        "key_findings",
        "limitations",
        "recommendations",
    }
    assert (
        not {
            "campus_comparison",
            "department_ranking",
            "budget_variance",
            "income_structure",
        }
        & REQUIRED_REPORT_SECTIONS
    )


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"revision": 2}, "report_artifact_revision_mismatch"),
        ({"renderedChartIds": ()}, "report_artifact_chart_missing"),
        ({"citationIds": ()}, "report_artifact_citation_missing"),
        ({"sections": ("executive_summary",)}, "report_artifact_section_missing"),
    ],
)
def test_pdf验收拒绝revision或图表引用章节缺失(update: dict[str, object], code: str):
    current = draft()
    payload = {
        "reportId": "report-1",
        "revision": 1,
        "pdf": {
            "path": "reports/revision-1/report.pdf",
            "mediaType": "application/pdf",
            "size": 8192,
            "sha256": "e" * 64,
        },
        "pageCount": 8,
        "renderedChartIds": ("income-trend",),
        "citationIds": ("citation-income",),
        "sections": current.sections,
        **update,
    }
    rendered = PdfArtifactManifest.model_validate(payload)

    with pytest.raises(ReportingError) as captured:
        validate_rendered_artifacts(current, rendered, lineage=lineage())

    assert captured.value.code == code


def test_产物路径禁止绝对路径和目录穿越():
    for path in ("/tmp/report.pdf", "reports/../secret.pdf", "reports\\report.pdf"):
        with pytest.raises(ValueError):
            ArtifactFile(
                path=path,
                mediaType="application/pdf",
                size=1,
                sha256="a" * 64,
            )


def test_数据集快照变化使产物失效():
    changed = lineage()[0].model_copy(update={"sha256": "f" * 64})
    current = draft()
    rendered = PdfArtifactManifest(
        reportId="report-1",
        revision=1,
        pdf=ArtifactFile(
            path="reports/revision-1/report.pdf",
            mediaType="application/pdf",
            size=8192,
            sha256="e" * 64,
        ),
        pageCount=8,
        renderedChartIds=("income-trend",),
        citationIds=("citation-income",),
        sections=current.sections,
    )

    with pytest.raises(ReportingError) as captured:
        validate_rendered_artifacts(current, rendered, lineage=(changed,))

    assert captured.value.code == "report_artifact_dataset_changed"
