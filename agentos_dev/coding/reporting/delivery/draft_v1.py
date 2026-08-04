from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from ..contract import StrictModel
from ..models import ReportingError


class ReportSectionDefinition(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    protocol_marker: bool = Field(default=True, alias="protocolMarker")


class ReportChartInput(StrictModel):
    """服务端归档后的图表输入；fileName 永远由服务端生成。"""

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    file_name: str = Field(alias="fileName", min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_citations(self) -> ReportChartInput:
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("图表 citationId 不能重复")
        return self


class ReportChartRegistration(StrictModel):
    """模型只登记工作区源文件与展示元数据，不控制发布路径。"""

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("图表源路径必须使用 POSIX 格式")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("图表源路径必须是安全工作区相对路径")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_unique_citations(self) -> ReportChartRegistration:
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("图表 citationId 不能重复")
        return self


class ReportDraftBlock(StrictModel):
    block_id: str = Field(alias="blockId", min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=24_000)
    citation_ids: tuple[str, ...] = Field(default=(), alias="citationIds", max_length=100)
    chart_ids: tuple[str, ...] = Field(default=(), alias="chartIds", max_length=100)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_unique_references(self) -> ReportDraftBlock:
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("正文 citationId 不能重复")
        if len(self.chart_ids) != len(set(self.chart_ids)):
            raise ValueError("正文 chartId 不能重复")
        return self


class ReportDraftSection(StrictModel):
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_blocks(self) -> ReportDraftSection:
        block_ids = [item.block_id for item in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("同一章节的 blockId 不能重复")
        return self


class ReportDraft(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[ReportDraftSection, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_sections(self) -> ReportDraft:
        codes = [item.section_code for item in self.sections]
        if len(codes) != len(set(codes)):
            raise ValueError("草稿章节不能重复")
        return self


class RenderedReportDraft(StrictModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=False,
    )

    markdown: str
    chart_paths: tuple[str, ...] = Field(alias="chartPaths")
    warnings: tuple[dict[str, Any], ...] = ()
    auto_fixes: tuple[dict[str, Any], ...] = Field(default=(), alias="autoFixes")


def _safe_chart_name(
    file_name: str,
    *,
    report_parent: PurePosixPath,
) -> tuple[str, dict[str, Any] | None]:
    if "\\" in file_name:
        raise ReportingError("report_draft_chart_path_invalid", "图表路径必须使用 POSIX 格式。")
    raw = PurePosixPath(file_name)
    normalized_from: str | None = None
    if raw.is_absolute():
        expected_parent = PurePosixPath("/").joinpath(report_parent)
        if raw.parent != expected_parent:
            raise ReportingError(
                "report_draft_chart_path_invalid", "绝对图表路径必须精确位于当前报告目录。"
            )
        normalized_from = file_name
        raw = PurePosixPath(raw.name)
    if len(raw.parts) != 1 or raw.name in {"", ".", ".."}:
        raise ReportingError(
            "report_draft_chart_path_invalid", "图表只能使用当前报告目录内的文件名。"
        )
    if raw.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ReportingError("report_draft_chart_path_invalid", "图表只允许 PNG 或 JPEG。")
    auto_fix = (
        {
            "code": "chart_path_normalized",
            "from": normalized_from,
            "to": raw.as_posix(),
        }
        if normalized_from is not None
        else None
    )
    return raw.as_posix(), auto_fix


def _marker_lines(text: str, citation_ids: tuple[str, ...]) -> str:
    markers = "".join(f"[[citation:{citation_id}]]" for citation_id in citation_ids)
    return f"{text}{markers}"


def render_report_draft(
    draft: ReportDraft,
    *,
    expected_title: str,
    markdown_path: str,
    sections: tuple[ReportSectionDefinition, ...],
    citation_ids: tuple[str, ...],
    charts: tuple[ReportChartInput, ...] = (),
) -> RenderedReportDraft:
    if draft.title != expected_title:
        raise ReportingError("report_draft_title_mismatch", "报告标题与 Workflow 固定标题不一致。")

    section_registry = {item.code: item for item in sections}
    if len(section_registry) != len(sections):
        raise ReportingError("report_draft_registry_invalid", "Workflow 章节注册表包含重复 code。")
    draft_codes = tuple(item.section_code for item in draft.sections)
    if draft_codes != tuple(section_registry):
        raise ReportingError(
            "report_draft_section_mismatch", "草稿章节必须按 effectiveProfile 的顺序完整生成。"
        )

    citation_registry = set(citation_ids)
    if len(citation_registry) != len(citation_ids):
        raise ReportingError(
            "report_draft_registry_invalid", "Workflow citation 注册表包含重复 ID。"
        )
    chart_registry = {item.chart_id: item for item in charts}
    if len(chart_registry) != len(charts):
        raise ReportingError(
            "report_draft_registry_invalid", "Workflow 图表注册表包含重复 chartId。"
        )

    report_path = PurePosixPath(markdown_path)
    if report_path.is_absolute() or ".." in report_path.parts or "\\" in markdown_path:
        raise ReportingError("report_draft_path_invalid", "Markdown 路径必须是安全工作区相对路径。")

    normalized_charts: dict[str, tuple[ReportChartInput, str]] = {}
    auto_fixes: list[dict[str, Any]] = []
    for chart in charts:
        unknown = set(chart.citation_ids) - citation_registry
        if unknown:
            raise ReportingError("report_draft_citation_unknown", "图表引用了未注册 citation。")
        file_name, auto_fix = _safe_chart_name(
            chart.file_name,
            report_parent=report_path.parent,
        )
        if auto_fix is not None:
            auto_fixes.append(auto_fix)
        normalized_charts[chart.chart_id] = (chart, file_name)

    referenced_chart_ids: list[str] = []
    markdown_parts = [f"# {expected_title}"]
    for section in draft.sections:
        definition = section_registry[section.section_code]
        heading = f"## {definition.title}"
        markdown_parts.append(
            f"[[section:{definition.code}]]\n{heading}" if definition.protocol_marker else heading
        )
        for block in section.blocks:
            if (
                "[[citation:" in block.text
                or "[[section:" in block.text
                or "<!-- repair-warning:" in block.text
                or "![" in block.text
            ):
                raise ReportingError(
                    "report_draft_protocol_injection",
                    "正文不得自行包含协议标记或图片语法。",
                )
            unknown_citations = set(block.citation_ids) - citation_registry
            if unknown_citations:
                raise ReportingError("report_draft_citation_unknown", "草稿引用了未注册 citation。")
            unknown_charts = set(block.chart_ids) - set(chart_registry)
            if unknown_charts:
                raise ReportingError("report_draft_chart_unknown", "草稿引用了未注册图表。")
            markdown_parts.append(_marker_lines(block.text, block.citation_ids))
            for chart_id in block.chart_ids:
                chart, file_name = normalized_charts[chart_id]
                if not set(chart.citation_ids).issubset(block.citation_ids):
                    raise ReportingError(
                        "report_draft_chart_citation_invalid",
                        "图表 citation 必须属于所在正文块的 citation 绑定。",
                    )
                referenced_chart_ids.append(chart_id)
                markdown_parts.append(
                    f'![{chart.alt_text}]({file_name} "{chart.title}")'
                    + "".join(f"[[citation:{citation_id}]]" for citation_id in chart.citation_ids)
                    + f"\n\n*图表：{chart.title}*"
                )

    unused = sorted(set(chart_registry) - set(referenced_chart_ids))
    warnings: list[dict[str, Any]] = []
    if unused:
        warnings.append(
            {
                "code": "unused_chart_excluded",
                "chartIds": unused,
                "message": "未被正文引用的图表已从发布包排除。",
            }
        )
    used_citations = {
        citation_id
        for section in draft.sections
        for block in section.blocks
        for citation_id in block.citation_ids
    }
    missing_citations = sorted(citation_registry - used_citations)
    if missing_citations:
        raise ReportingError(
            "report_draft_citation_missing",
            "结构化草稿必须使用 Workflow 注册的全部 citation。",
        )
    chart_paths = tuple(
        report_path.parent.joinpath(normalized_charts[chart_id][1]).as_posix()
        for chart_id in dict.fromkeys(referenced_chart_ids)
    )
    return RenderedReportDraft(
        markdown="\n\n".join(markdown_parts) + "\n",
        chartPaths=chart_paths,
        warnings=tuple(warnings),
        autoFixes=tuple(auto_fixes),
    )
