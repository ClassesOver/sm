from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
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
    sections: tuple[str, ...] = Field(
        min_length=1,
        max_length=100,
        json_schema_extra={
            "allOf": [
                {"contains": {"const": section}} for section in sorted(REQUIRED_REPORT_SECTIONS)
            ]
        },
    )

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


def authoritative_citations(lineage: tuple[DatasetLineage, ...]) -> tuple[Citation, ...]:
    ordered = sorted(lineage, key=lambda item: (item.requirement_id, item.dataset_id))
    return tuple(
        Citation(
            citationId=f"citation_{index:03d}",
            datasetId=item.dataset_id,
            requirementId=item.requirement_id,
        )
        for index, item in enumerate(ordered, start=1)
    )


def build_authoritative_manifest(
    *,
    report_id: str,
    revision: int,
    coding_task_key: str,
    effective_profile_hash: str,
    markdown_path: str,
    markdown: str,
    accepted_artifacts: list[dict[str, Any]],
    lineage: tuple[DatasetLineage, ...],
    sections: tuple[str, ...],
) -> ReportArtifactManifest:
    artifacts: dict[str, dict[str, Any]] = {
        path: item
        for item in accepted_artifacts
        if isinstance(item, dict) and isinstance(path := item.get("path"), str)
    }
    if len(artifacts) != len(accepted_artifacts):
        raise ReportingError(
            "report_artifact_acceptance_incomplete", "正式产物回执包含重复或无效路径。"
        )
    markdown_artifact = artifacts.get(markdown_path)
    if markdown_artifact is None:
        raise ReportingError(
            "report_artifact_acceptance_missing", "正式产物回执缺少报告 Markdown。"
        )

    citations = authoritative_citations(lineage)
    citation_datasets = {item.citation_id: item.dataset_id for item in citations}
    image_bindings = _markdown_image_bindings(markdown, markdown_path, citation_datasets)
    extra_paths = set(artifacts) - {markdown_path}
    submitted_images = {
        path
        for path in extra_paths
        if PurePosixPath(path).suffix.lower() in {".png", ".jpg", ".jpeg"}
    }
    if submitted_images != extra_paths or not set(image_bindings).issubset(submitted_images):
        raise ReportingError(
            "report_artifact_acceptance_incomplete",
            "正式产物回执必须包含 Markdown 引用的全部图表，且不能包含非图片附加产物。",
        )

    charts = tuple(
        ChartArtifact(
            path=path,
            mediaType=_image_media_type(path),
            size=_artifact_size(artifacts[path]),
            sha256=_artifact_sha256(artifacts[path]),
            chartId=f"chart_{index:03d}",
            datasetIds=image_bindings[path],
        )
        for index, path in enumerate(sorted(image_bindings), start=1)
    )
    return ReportArtifactManifest(
        reportId=report_id,
        revision=revision,
        codingTaskKey=coding_task_key,
        datasetSnapshotHash=dataset_snapshot_hash(lineage),
        effectiveProfileHash=effective_profile_hash,
        markdown=ArtifactFile(
            path=markdown_path,
            mediaType="text/markdown",
            size=_artifact_size(markdown_artifact),
            sha256=_artifact_sha256(markdown_artifact),
        ),
        charts=charts,
        citations=citations,
        sections=sections,
    )


def _artifact_size(artifact: dict[str, Any]) -> int:
    value = artifact.get("size")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReportingError("report_artifact_acceptance_incomplete", "正式产物回执缺少有效 size。")
    return value


def _artifact_sha256(artifact: dict[str, Any]) -> str:
    value = artifact.get("sha256")
    if not isinstance(value, str) or not re.fullmatch(SHA256_PATTERN, value):
        raise ReportingError(
            "report_artifact_acceptance_incomplete", "正式产物回执缺少有效 SHA-256。"
        )
    return value


def _image_media_type(path: str) -> Literal["image/png", "image/jpeg"]:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    raise ReportingError("report_artifact_chart_invalid", "图表产物只允许 PNG 或 JPEG。")


def _markdown_image_bindings(
    markdown: str,
    markdown_path: str,
    citation_datasets: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    lines = markdown.splitlines()
    parent = PurePosixPath(markdown_path).parent
    bindings: dict[str, set[str]] = {}
    for token in MarkdownIt("commonmark").parse(markdown):
        images = [item for item in token.children or () if item.type == "image"]
        if not images:
            continue
        start, end = token.map or (0, len(lines))
        citation_ids = set(
            re.findall(r"\[\[citation:([^\]\r\n]+)\]\]", "\n".join(lines[start:end]))
        )
        unknown = citation_ids - set(citation_datasets)
        if unknown or not citation_ids:
            raise ReportingError(
                "report_artifact_chart_citation_invalid",
                "每个图表必须在同一 Markdown 段落绑定至少一个 Workflow citation marker。",
            )
        for image in images:
            source = str(image.attrGet("src") or "")
            parsed = urlsplit(source)
            decoded = unquote(parsed.path)
            relative = PurePosixPath(decoded)
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or not decoded
                or "\\" in decoded
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                raise ReportingError(
                    "report_artifact_chart_invalid", "Markdown 图表必须使用安全相对路径。"
                )
            path = parent.joinpath(relative).as_posix()
            bindings.setdefault(path, set()).update(
                citation_datasets[item] for item in citation_ids
            )
    return {path: tuple(sorted(dataset_ids)) for path, dataset_ids in bindings.items()}


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


def validate_markdown_markers(draft: ReportArtifactManifest, markdown: str) -> None:
    missing_citations = [
        item.citation_id
        for item in draft.citations
        if f"[[citation:{item.citation_id}]]" not in markdown
    ]
    if missing_citations:
        raise ReportingError(
            "report_artifact_citation_missing",
            f"Markdown 缺少数据引用标识：{', '.join(missing_citations)}。",
        )
    missing_sections = [
        section for section in draft.sections if f"[[section:{section}]]" not in markdown
    ]
    if missing_sections:
        raise ReportingError(
            "report_artifact_section_missing",
            f"Markdown 缺少关键章节标识：{', '.join(missing_sections)}。",
        )


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
