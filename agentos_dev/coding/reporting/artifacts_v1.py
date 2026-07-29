from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contract import SHA256_PATTERN, StrictModel
from .models import ReportingError
from .workflow_v1 import DatasetLineage

REQUIRED_REPORT_SECTIONS = frozenset(
    {
        "executive_summary",
        "scope_and_methodology",
        "key_findings",
        "limitations",
        "recommendations",
    }
)


class ArtifactFile(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    media_type: Literal["text/markdown", "image/png", "image/jpeg", "application/pdf"] = Field(
        alias="mediaType"
    )
    size: int = Field(ge=1, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("产物路径必须使用 POSIX 相对路径")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("产物路径必须位于工作区内")
        return value


class ChartArtifact(ArtifactFile):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_image(self) -> ChartArtifact:
        if not self.media_type.startswith("image/"):
            raise ValueError("图表产物必须是图片")
        if len(set(self.dataset_ids)) != len(self.dataset_ids):
            raise ValueError("图表数据集引用不能重复")
        return self


class Citation(StrictModel):
    citation_id: str = Field(alias="citationId", min_length=1, max_length=128)
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=128)
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)


class ReportArtifactManifest(StrictModel):
    report_id: str = Field(alias="reportId", min_length=1, max_length=128)
    revision: int = Field(ge=1)
    coding_task_key: str = Field(alias="codingTaskKey", min_length=1, max_length=128)
    dataset_snapshot_hash: str = Field(alias="datasetSnapshotHash", pattern=SHA256_PATTERN)
    effective_profile_hash: str = Field(alias="effectiveProfileHash", pattern=SHA256_PATTERN)
    markdown: ArtifactFile
    charts: tuple[ChartArtifact, ...] = Field(default=(), max_length=100)
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=2_000)
    sections: tuple[str, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_manifest(self) -> ReportArtifactManifest:
        if self.markdown.media_type != "text/markdown":
            raise ValueError("正文产物必须是 Markdown")
        chart_ids = [item.chart_id for item in self.charts]
        citation_ids = [item.citation_id for item in self.citations]
        paths = [self.markdown.path, *(item.path for item in self.charts)]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("chartId 不能重复")
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("citationId 不能重复")
        if len(paths) != len(set(paths)):
            raise ValueError("产物路径不能重复")
        if len(self.sections) != len(set(self.sections)):
            raise ValueError("报告章节不能重复")
        if not REQUIRED_REPORT_SECTIONS.issubset(self.sections):
            raise ValueError("报告缺少关键章节")
        return self


class PdfArtifactManifest(StrictModel):
    report_id: str = Field(alias="reportId", min_length=1, max_length=128)
    revision: int = Field(ge=1)
    pdf: ArtifactFile
    page_count: int = Field(alias="pageCount", ge=1, le=1_000)
    rendered_chart_ids: tuple[str, ...] = Field(
        default=(), alias="renderedChartIds", max_length=100
    )
    citation_ids: tuple[str, ...] = Field(default=(), alias="citationIds", max_length=2_000)
    sections: tuple[str, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_pdf(self) -> PdfArtifactManifest:
        if self.pdf.media_type != "application/pdf":
            raise ValueError("PDF 产物类型无效")
        if len(self.rendered_chart_ids) != len(set(self.rendered_chart_ids)):
            raise ValueError("PDF 图表引用不能重复")
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("PDF 引用不能重复")
        return self


def dataset_snapshot_hash(lineage: tuple[DatasetLineage, ...]) -> str:
    values = sorted(
        (item.model_dump(mode="json", by_alias=True) for item in lineage),
        key=lambda item: (item["sourceId"], item["requirementId"], item["datasetId"]),
    )
    encoded = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_rendered_artifacts(
    draft: ReportArtifactManifest,
    rendered: PdfArtifactManifest,
    *,
    lineage: tuple[DatasetLineage, ...],
) -> None:
    if draft.report_id != rendered.report_id or draft.revision != rendered.revision:
        raise ReportingError(
            "report_artifact_revision_mismatch", "PDF 与当前报告 revision 不一致。"
        )
    if dataset_snapshot_hash(lineage) != draft.dataset_snapshot_hash:
        raise ReportingError("report_artifact_dataset_changed", "成稿使用的数据集已变化。")

    lineage_keys = {(item.dataset_id, item.requirement_id) for item in lineage}
    if any(
        (citation.dataset_id, citation.requirement_id) not in lineage_keys
        for citation in draft.citations
    ) or any(
        dataset_id not in {item.dataset_id for item in lineage}
        for chart in draft.charts
        for dataset_id in chart.dataset_ids
    ):
        raise ReportingError("report_artifact_lineage_invalid", "报告产物引用了未知数据集。")

    if {item.chart_id for item in draft.charts} != set(rendered.rendered_chart_ids):
        raise ReportingError("report_artifact_chart_missing", "PDF 未完整渲染报告图表。")
    if {item.citation_id for item in draft.citations} != set(rendered.citation_ids):
        raise ReportingError("report_artifact_citation_missing", "PDF 未完整保留数据引用。")
    if not set(draft.sections).issubset(rendered.sections):
        raise ReportingError("report_artifact_section_missing", "PDF 缺少报告关键章节。")
