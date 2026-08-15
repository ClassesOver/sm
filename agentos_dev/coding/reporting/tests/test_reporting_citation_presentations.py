from __future__ import annotations

import pytest

from agentos_dev.coding.reporting.delivery.report_runtime import ReportFailure, _pdf_markdown


def presentation(citation_id: str) -> dict[str, object]:
    return {
        "citationId": citation_id,
        "label": f"来源 {citation_id}",
        "coverageItems": [],
    }


def test_pdf_markdown_accepts_authoritative_citation_superset() -> None:
    markdown = "# 报告\n\n收入结论[[citation:citation_003]]\n"
    presentations = [
        presentation("citation_001"),
        presentation("citation_002"),
        presentation("citation_003"),
    ]

    visible, normalized = _pdf_markdown(markdown, presentations)

    assert "[[citation:" not in visible
    assert [item["citationId"] for item in normalized] == [
        "citation_001",
        "citation_002",
        "citation_003",
    ]


def test_pdf_markdown_rejects_unknown_markdown_citation() -> None:
    with pytest.raises(ReportFailure, match="Markdown 引用不一致"):
        _pdf_markdown(
            "结论[[citation:citation_999]]",
            [presentation("citation_001")],
        )
