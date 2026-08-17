from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agentos_dev.reporting.delivery.report_runtime import (
    _WORD_PAGE_FIELDS,
    DEFAULT_PAGE_LAYOUT,
    _page_number_context,
    _postprocess_docx,
)


@pytest.mark.parametrize(
    ("physical_page", "body_start_page", "physical_page_count", "expected"),
    [
        (2, 3, 25, ("i", "i")),
        (2, 4, 25, ("i", "ii")),
        (3, 4, 25, ("ii", "ii")),
        (3, 3, 25, (1, 23)),
        (25, 3, 25, (23, 23)),
    ],
)
def test_page_number_context_uses_section_page_count(
    physical_page: int,
    body_start_page: int,
    physical_page_count: int,
    expected: tuple[str | int, str | int],
) -> None:
    assert (
        _page_number_context(
            physical_page,
            body_start_page=body_start_page,
            physical_page_count=physical_page_count,
        )
        == expected
    )


def test_postprocess_docx_uses_section_page_count_field(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")

    path = tmp_path / "report.docx"
    document = docx.Document()
    for text in (
        "测试报告",
        "__REPORT_COVER_END__",
        "目录",
        "__REPORT_TOC_FIELD_START__",
        "经营概览",
        "__REPORT_TOC_FIELD_END__",
        "__REPORT_TOC_END__",
        "__REPORT_BODY_START__",
        "经营概览",
        "测试机构",
        "2026-08-17",
    ):
        document.add_paragraph(text)
    document.save(path)

    _postprocess_docx(
        path,
        context={
            "title": "测试报告",
            "periodLabel": "2025 年",
            "organizationName": "测试机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-08-17",
            "sections": [{"code": "overview", "title": "经营概览"}],
        },
        layout=DEFAULT_PAGE_LAYOUT,
    )

    with zipfile.ZipFile(path) as package:
        footer_xml = "\n".join(
            package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        )

    assert "SECTIONPAGES" in footer_xml
    assert "NUMPAGES" not in footer_xml


def test_word_page_fields_use_section_page_count() -> None:
    assert _WORD_PAGE_FIELDS == {"page": "PAGE", "pages": "SECTIONPAGES"}
