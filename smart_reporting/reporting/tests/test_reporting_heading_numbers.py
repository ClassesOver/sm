from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    Citation,
    DocxArtifactManifest,
    ReportArtifactManifest,
)
from smart_reporting.reporting.delivery.draft_v1 import (
    HeadingNumber,
    ReportChartInput,
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
    validate_report_draft_blocks,
)
from smart_reporting.reporting.delivery.report_runtime.markdown import (
    _document_context,
    _semantic_documents,
)
from smart_reporting.reporting.delivery.report_runtime.pdf import (
    DEFAULT_PAGE_LAYOUT,
    _page_layout,
)
from smart_reporting.reporting.hospital_operation.outline import ReportOutline, freeze_outline
from smart_reporting.reporting.models import ReportingError


def _render(*blocks: str):
    return assemble_report_markdown(
        ReportDraft(
            sections=(
                ReportDraftSection(
                    sectionCode="section_001",
                    blocks=tuple(
                        ReportDraftBlock(blockId=f"block_{index}", markdown=markdown)
                        for index, markdown in enumerate(blocks, start=1)
                    ),
                ),
            )
        ),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(
            ReportSectionDefinition(
                code="section_001",
                sectionNumber="1",
                title="经营分析",
                analysisIds=("analysis_001",),
            ),
        ),
        citation_ids=(),
    )


def test_freeze_outline_generates_contiguous_section_numbers() -> None:
    outline = freeze_outline(
        {
            "reportType": "comprehensive",
            "title": "运营报告",
            "sections": [
                {"title": title, "analysisIds": [f"analysis_{index:03d}"]}
                for index, title in enumerate(("经营", "效率", "质量"), start=1)
            ],
        },
        analyses=[{"analysisId": f"analysis_{index:03d}"} for index in range(1, 4)],
    )

    assert [item.section_number for item in outline.sections] == ["1", "2", "3"]
    payload = outline.model_dump(mode="json", by_alias=True)
    payload["sections"][1]["sectionNumber"] = "3"
    with pytest.raises(ValidationError, match="sectionNumber 必须从 1 连续生成"):
        ReportOutline.model_validate(payload)


def test_assemble_numbers_headings_across_blocks_and_rewrites_manual_number() -> None:
    rendered = _render(
        "### 2.3 收入趋势\n\n正文\n\n#### 同比变化",
        "### 成本结构\n\n正文\n\n#### 重点项目",
    )

    assert "## 1. 经营分析" in rendered.markdown
    assert "### 1.1 收入趋势" in rendered.markdown
    assert "#### 1.1.1 同比变化" in rendered.markdown
    assert "### 1.2 成本结构" in rendered.markdown
    assert "#### 1.2.1 重点项目" in rendered.markdown
    assert [item.number for item in rendered.heading_numbers] == [
        "1",
        "1.1",
        "1.1.1",
        "1.2",
        "1.2.1",
    ]


def test_assemble_does_not_rewrite_fenced_heading() -> None:
    rendered = _render("```markdown\n### 9.9 示例\n```\n\n### 结论")

    assert "### 9.9 示例" in rendered.markdown
    assert "### 1.1 结论" in rendered.markdown
    assert [item.number for item in rendered.heading_numbers] == ["1", "1.1"]


def test_assemble_preserves_inline_markdown_but_records_visible_title() -> None:
    rendered = _render("### **经营结论** 与 `预算`")

    assert "### 1.1 **经营结论** 与 `预算`" in rendered.markdown
    assert rendered.heading_numbers[1].title == "经营结论 与 预算"


@pytest.mark.parametrize(
    "markdown_title",
    [
        "甲" * 300,
        f"**{'甲' * 150}**`{'乙' * 150}`",
    ],
)
def test_assemble_allows_heading_with_300_visible_characters(markdown_title: str) -> None:
    rendered = _render(f"### {markdown_title}\n\n正文")

    assert len(rendered.heading_numbers[1].title) == 300


@pytest.mark.parametrize(
    "markdown_title",
    [
        "甲" * 301,
        f"**{'甲' * 150}**`{'乙' * 151}`",
    ],
)
def test_assemble_rejects_heading_with_301_visible_characters(markdown_title: str) -> None:
    with pytest.raises(ReportingError) as raised:
        _render(f"### {markdown_title}\n\n正文")

    assert raised.value.code == "report_draft_heading_title_too_long"
    assert raised.value.details == {
        "issues": [
            {
                "path": "$.markdown",
                "type": "heading_title_too_long",
                "message": "章节正文标题可见文本不得超过 300 个字符。",
                "maxLength": 300,
                "actualLength": 301,
            }
        ]
    }


def test_assemble_normalizes_open_spaced_chinese_strong_marker() -> None:
    rendered = _render("下滑主要由** 总部院区**、挂号等收入构成。")

    assert "下滑主要由**总部院区**、挂号等收入构成。" in rendered.markdown
    assert rendered.auto_fixes == (
        {
            "code": "markdown_strong_marker_normalized",
            "sectionCode": "section_001",
            "blockId": "block_1",
        },
    )


def test_assemble_removes_numbered_duplicate_section_heading() -> None:
    rendered = _render("## 9.9 经营分析\n\n### 结论")

    assert rendered.markdown.count("## 1. 经营分析") == 1
    assert "9.9" not in rendered.markdown
    assert rendered.auto_fixes[0]["code"] == "duplicate_section_heading_removed"


def test_assemble_excludes_duplicate_chart_before_revalidating_later_block_binding() -> None:
    rendered = assemble_report_markdown(
        ReportDraft(
            sections=(
                ReportDraftSection(
                    sectionCode="section_001",
                    blocks=(
                        ReportDraftBlock(
                            blockId="block_1",
                            markdown="收入趋势。",
                            citationIds=("citation_001",),
                            chartIds=("chart_001",),
                        ),
                        ReportDraftBlock(
                            blockId="block_2",
                            markdown="补充说明。",
                            chartIds=("chart_001",),
                        ),
                    ),
                ),
            )
        ),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(
            ReportSectionDefinition(
                code="section_001",
                sectionNumber="1",
                title="经营分析",
                analysisIds=("analysis_001",),
            ),
        ),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="chart_001",
                fileName="revenue.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
    )

    assert rendered.markdown.count("revenue.png") == 1
    assert rendered.warnings == (
        {
            "code": "duplicate_chart_reference_excluded",
            "chartId": "chart_001",
            "sectionCode": "section_001",
            "blockId": "block_2",
            "message": "同一 chartId 已在前文渲染，重复引用已排除。",
        },
    )


def test_document_context_and_manifest_share_heading_number_contract() -> None:
    rendered = _render("### 结论\n\n#### 收入")
    headings = [item.model_dump(mode="json", by_alias=True) for item in rendered.heading_numbers]
    context = _document_context(
        {
            "title": "运营报告",
            "periodLabel": "2026-01-01 至 2026-12-31",
            "organizationName": "测试机构",
            "generatedByLabel": "智能报告平台",
            "watermarkText": "测试水印",
            "generatedDate": "2026-08-24",
            "sectionNumbers": ["1"],
            "sections": [{"code": "section_001", "sectionNumber": "1", "title": "经营分析"}],
            "headingNumbers": headings,
        }
    )
    manifest = ReportArtifactManifest(
        reportId="report-1",
        revision=1,
        codingTaskKey="task-1",
        datasetSnapshotHash="a" * 64,
        effectiveProfileHash="b" * 64,
        markdown=ArtifactFile(
            path="reports/report.md", mediaType="text/markdown", size=1, sha256="c" * 64
        ),
        citations=(
            Citation(
                citationId="citation_001",
                datasetId="dataset-1",
                requirementId="requirement-1",
                snapshotHash="d" * 64,
            ),
        ),
        sections=("section_001",),
        sectionNumbers=rendered.section_numbers,
        headingNumbers=rendered.heading_numbers,
    )
    body = (
        "<h2>1. 经营分析</h2>"
        '<p><img src="charts/revenue.png" alt="收入趋势"></p>'
        "<p><em>图表：2025 年收入趋势</em></p>"
    )
    pdf_html, word_html = _semantic_documents(body, context=context, layout=DEFAULT_PAGE_LAYOUT)

    assert manifest.heading_numbers == rendered.heading_numbers
    assert '<span class="toc-title">1. 经营分析</span>' in pdf_html
    assert '<span class="toc-title">1. 经营分析</span>' in word_html
    assert 'class="toc-entry toc-level-4"' in pdf_html
    assert 'href="#report-heading-section_001-1-1-1"' in pdf_html
    assert "1.1.1 收入" in word_html
    assert "max-height:180mm" in pdf_html
    assert "object-fit:contain" in pdf_html
    assert pdf_html.count('<figure class="report-figure">') == 1
    assert (
        '<figcaption class="report-figure-caption">图表：2025 年收入趋势</figcaption>' in pdf_html
    )
    assert ".report-figure + p{break-before:avoid;page-break-before:avoid}" in pdf_html


def test_manifest_rejects_non_contiguous_nested_heading_numbers() -> None:
    with pytest.raises(ValidationError, match="子标题编号必须按当前章节顺序连续生成"):
        ReportArtifactManifest(
            reportId="report-1",
            revision=1,
            codingTaskKey="task-1",
            datasetSnapshotHash="a" * 64,
            effectiveProfileHash="b" * 64,
            markdown=ArtifactFile(
                path="reports/report.md",
                mediaType="text/markdown",
                size=1,
                sha256="c" * 64,
            ),
            citations=(
                Citation(
                    citationId="citation_001",
                    datasetId="dataset-1",
                    requirementId="requirement-1",
                    snapshotHash="d" * 64,
                ),
            ),
            sections=("section_001",),
            sectionNumbers=("1",),
            headingNumbers=(
                HeadingNumber(
                    level=2,
                    number="1",
                    title="经营分析",
                    sectionCode="section_001",
                    anchor="report-section-section_001",
                ),
                HeadingNumber(
                    level=3,
                    number="1.2",
                    title="跳号标题",
                    sectionCode="section_001",
                    anchor="report-heading-section_001-1-2",
                ),
            ),
        )


def _docx_manifest_with_heading_count(
    heading_count: int, *, toc_entry_count: int
) -> DocxArtifactManifest:
    headings = (
        HeadingNumber(
            level=2,
            number="1",
            title="经营分析",
            sectionCode="section_001",
            anchor="report-section-section_001",
        ),
        *(
            HeadingNumber(
                level=3,
                number=f"1.{index}",
                title=f"分析主题 {index}",
                sectionCode="section_001",
                anchor=f"report-heading-section_001-1-{index}",
            )
            for index in range(1, heading_count)
        ),
    )
    return DocxArtifactManifest(
        reportId="report-1",
        revision=1,
        effectiveProfileHash="a" * 64,
        sourceMarkdownSha256="b" * 64,
        docx=ArtifactFile(
            path="reports/report.docx",
            mediaType=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            size=1,
            sha256="c" * 64,
        ),
        convertedPageCount=1,
        sectionCount=1,
        tocEntryCount=toc_entry_count,
        sections=("section_001",),
        sectionNumbers=("1",),
        headingNumbers=headings,
    )


def test_docx_manifest_accepts_more_than_one_hundred_complete_toc_entries() -> None:
    manifest = _docx_manifest_with_heading_count(110, toc_entry_count=110)

    assert manifest.toc_entry_count == 110
    assert len(manifest.heading_numbers) == 110


def test_docx_manifest_rejects_toc_count_different_from_heading_count() -> None:
    with pytest.raises(ValidationError, match="Word 目录项必须完整覆盖标题编号映射"):
        _docx_manifest_with_heading_count(110, toc_entry_count=109)


@pytest.mark.parametrize(
    ("markdown", "code"),
    [
        ("#### 缺少父标题", "report_draft_heading_parent_missing"),
        ("##### 非法层级", "report_draft_heading_level_invalid"),
        ("# 非法正文标题", "report_draft_heading_level_invalid"),
        ("## 非法正文标题", "report_draft_heading_level_invalid"),
    ],
)
def test_assemble_rejects_invalid_heading_hierarchy(markdown: str, code: str) -> None:
    with pytest.raises(ReportingError) as raised:
        _render(markdown)

    assert raised.value.code == code


def test_validate_report_draft_blocks_rejects_h2_before_section_is_persisted() -> None:
    blocks = (ReportDraftBlock(blockId="block_1", markdown="## 非法正文标题\n\n正文"),)

    with pytest.raises(ReportingError) as raised:
        validate_report_draft_blocks(blocks, expected_section_title="经营分析")

    assert raised.value.code == "report_draft_heading_level_invalid"


def test_validate_report_draft_blocks_reports_heading_parent_path() -> None:
    blocks = (
        ReportDraftBlock(blockId="block_1", markdown="普通正文"),
        ReportDraftBlock(blockId="block_2", markdown="#### 缺少父标题\n\n正文"),
    )

    with pytest.raises(ReportingError) as raised:
        validate_report_draft_blocks(blocks, expected_section_title="经营分析")

    assert raised.value.code == "report_draft_heading_parent_missing"
    assert raised.value.details == {
        "issues": [
            {
                "path": "$.blocks[1].markdown",
                "type": "heading_parent_missing",
                "message": "H4 标题必须位于当前章节的 H3 标题之后。",
            }
        ]
    }


def test_validate_report_draft_blocks_reports_long_heading_block_path() -> None:
    blocks = (
        ReportDraftBlock(blockId="block_1", markdown="### 正常标题\n\n正文"),
        ReportDraftBlock(blockId="block_2", markdown=f"### {'甲' * 301}\n\n正文"),
    )

    with pytest.raises(ReportingError) as raised:
        validate_report_draft_blocks(blocks, expected_section_title="经营分析")

    assert raised.value.code == "report_draft_heading_title_too_long"
    assert raised.value.details == {
        "issues": [
            {
                "path": "$.blocks[1].markdown",
                "type": "heading_title_too_long",
                "message": "章节正文标题可见文本不得超过 300 个字符。",
                "maxLength": 300,
                "actualLength": 301,
            }
        ]
    }


def test_validate_report_draft_blocks_allows_leading_duplicate_section_heading() -> None:
    blocks = (
        ReportDraftBlock(
            blockId="block_1",
            markdown="## 9.9 经营分析\n\n### 收入趋势\n\n正文",
        ),
    )

    validate_report_draft_blocks(blocks, expected_section_title="经营分析")


def test_validate_report_draft_blocks_tracks_h3_parent_across_blocks() -> None:
    blocks = (
        ReportDraftBlock(blockId="block_1", markdown="### 收入趋势\n\n正文"),
        ReportDraftBlock(blockId="block_2", markdown="#### 同比变化\n\n正文"),
    )

    validate_report_draft_blocks(blocks, expected_section_title="经营分析")


def test_page_layout_export_flags_remove_optional_decorations() -> None:
    layout = _page_layout(
        DEFAULT_PAGE_LAYOUT,
        include_header_footer=False,
        include_page_numbers=False,
    )
    assert layout == {
        "headerLeft": "",
        "headerRight": "",
        "footerLeft": "",
        "footerRight": "",
    }
    assert _page_layout(None, include_page_numbers=False)["footerRight"] == ""


def test_semantic_documents_can_skip_cover_and_toc() -> None:
    context = _document_context(
        {
            "title": "运营报告",
            "periodLabel": "2026",
            "organizationName": "测试机构",
            "generatedByLabel": "平台",
            "watermarkText": "水印",
            "generatedDate": "2026-01-01",
            "sectionNumbers": ["1"],
            "sections": [{"code": "section_001", "sectionNumber": "1", "title": "经营分析"}],
            "headingNumbers": [
                {
                    "level": 2,
                    "number": "1",
                    "title": "经营分析",
                    "sectionCode": "section_001",
                    "anchor": "report-section-section_001",
                }
            ],
        }
    )
    pdf_html, word_html = _semantic_documents(
        "<h2>1. 经营分析</h2><p>正文</p>",
        context=context,
        layout=DEFAULT_PAGE_LAYOUT,
        include_cover=False,
        include_toc=False,
    )
    assert '<section class="report-cover">' not in pdf_html
    assert '<section class="report-toc">' not in pdf_html
    assert "目录" not in word_html
