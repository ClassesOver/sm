from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    Citation,
    ReportArtifactManifest,
)
from smart_reporting.reporting.delivery.draft_v1 import (
    HeadingNumber,
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)
from smart_reporting.reporting.delivery.report_runtime import (
    DEFAULT_PAGE_LAYOUT,
    _document_context,
    _semantic_documents,
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

    assert "## 1 经营分析" in rendered.markdown
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

    assert rendered.markdown.count("## 1 经营分析") == 1
    assert "9.9" not in rendered.markdown
    assert rendered.auto_fixes[0]["code"] == "duplicate_section_heading_removed"


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
    pdf_html, word_html = _semantic_documents(
        "<h2>1 经营分析</h2>", context=context, layout=DEFAULT_PAGE_LAYOUT
    )

    assert manifest.heading_numbers == rendered.heading_numbers
    assert 'class="toc-entry toc-level-4"' in pdf_html
    assert 'href="#report-heading-section_001-1-1-1"' in pdf_html
    assert "1.1.1 收入" in word_html


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
