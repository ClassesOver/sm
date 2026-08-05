from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from agentos_dev.coding.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    ChartArtifact,
    Citation,
    PdfArtifactManifest,
    ReportArtifactManifest,
    dataset_snapshot_hash,
    validate_markdown_markers,
    validate_rendered_artifacts,
)
from agentos_dev.coding.reporting.hospital_operation import COMPREHENSIVE_SECTIONS, make_outline
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.workflow.query_pipeline import DatasetLineage

REPORT_SECTIONS = tuple(section.code for section in COMPREHENSIVE_SECTIONS)


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
                factIds=("metric-income-total",),
            ),
        ),
        citations=(
            Citation(
                citationId="citation-income",
                datasetId="income-monthly-dataset",
                requirementId="income-monthly",
            ),
        ),
        factIds=("metric-income-total",),
        sections=REPORT_SECTIONS,
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
        factIds=("metric-income-total",),
        sections=current.sections,
    )

    validate_rendered_artifacts(current, rendered, lineage=lineage())


def test_报告产物schema不再另设固定业务章节():
    sections_schema = ReportArtifactManifest.model_json_schema(by_alias=True)["properties"][
        "sections"
    ]

    assert "allOf" not in sections_schema


def test_报告产物schema使用模型收到的别名且禁止额外字段():
    schema = ReportArtifactManifest.model_json_schema(by_alias=True)

    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert "codingTaskKey" in properties
    assert "datasetSnapshotHash" in properties
    assert "effectiveProfileHash" in properties
    assert "markdown" in properties
    assert "charts" in properties
    assert "citations" in properties
    assert "factIds" in properties
    assert "sections" in properties
    assert "markdownPath" not in properties
    assert "artifacts" not in properties
    assert "datasets" not in properties


@pytest.mark.parametrize(
    "sections",
    [
        tuple(section.code for section in COMPREHENSIVE_SECTIONS),
        tuple(
            section.code
            for section in make_outline(
                "topic",
                title="收入专题报告",
                selected_codes=("income",),
            ).sections
        ),
    ],
)
def test_报告产物模型和schema接受workflow批准的章节集合(sections: tuple[str, ...]):
    payload = draft().model_dump(mode="json", by_alias=True)
    payload["sections"] = list(sections)

    schema_errors = list(
        Draft202012Validator(ReportArtifactManifest.model_json_schema(by_alias=True)).iter_errors(
            payload
        )
    )

    assert schema_errors == []
    assert ReportArtifactManifest.model_validate(payload).sections == sections


@pytest.mark.parametrize(
    ("markdown", "code", "missing_id"),
    [
        (
            "[[fact:metric-income-total]]\n"
            + "\n".join(f"[[section:{item}]]" for item in REPORT_SECTIONS),
            "report_artifact_citation_missing",
            "citation-income",
        ),
        (
            "[[citation:citation-income]][[fact:metric-income-total]]",
            "report_artifact_section_missing",
            "operation_overview",
        ),
        (
            "[[citation:citation-income]]\n"
            + "\n".join(f"[[section:{item}]]" for item in REPORT_SECTIONS),
            "report_artifact_fact_missing",
            "metric-income-total",
        ),
    ],
)
def test_markdown验收在pdf渲染前反馈缺失标识(markdown: str, code: str, missing_id: str):
    with pytest.raises(ReportingError) as captured:
        validate_markdown_markers(draft(), markdown)

    assert captured.value.code == code
    assert missing_id in captured.value.message


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"revision": 2}, "report_artifact_revision_mismatch"),
        ({"renderedChartIds": ()}, "report_artifact_chart_missing"),
        ({"citationIds": ()}, "report_artifact_citation_missing"),
        ({"factIds": ()}, "report_artifact_fact_missing"),
        ({"sections": ("operation_overview",)}, "report_artifact_section_missing"),
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
        "factIds": ("metric-income-total",),
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
        factIds=("metric-income-total",),
        sections=current.sections,
    )

    with pytest.raises(ReportingError) as captured:
        validate_rendered_artifacts(current, rendered, lineage=(changed,))

    assert captured.value.code == "report_artifact_dataset_changed"
