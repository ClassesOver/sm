"""The renderer's presentation has an identity distinct from frozen evidence."""

from __future__ import annotations

import copy
import hashlib

import pytest

from smart_reporting.reporting.delivery.report_runtime.markdown import (
    _normalize_cjk_strong_markers,
    align_numeric_table_columns,
    collapse_repeated_values,
    compact_single_column_tables,
    insert_executive_summary,
    readable_large_amounts,
    relocate_server_tables,
)
from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown
from smart_reporting.reporting.delivery.report_runtime.projection import (
    PROJECTION_VERSION,
    build_render_projection,
    verify_render_projection,
)

SECTIONS = [
    {"code": "overview", "title": "收入分析"},
    {"code": "cost", "title": "成本分析"},
]
MARKDOWN = (
    "# 运营报告\n\n[[section:overview]]\n\n## 1. 收入分析\n\n"
    "收入增长至123456789元[[claim:income]]，需要复核期间。\n\n"
    "[[section:cost]]\n\n## 2. 成本分析\n\n"
    "支出分别为0元[[claim:a]]、0元[[claim:b]]，仍需关注。\n"
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_projection_runs_the_exact_existing_render_text_pipeline():
    previous = align_numeric_table_columns(
        readable_large_amounts(
            collapse_repeated_values(
                insert_executive_summary(
                    compact_single_column_tables(relocate_server_tables(MARKDOWN)),
                    SECTIONS,
                )
            )
        )
    )
    previous, citations, trace = _pdf_markdown(previous, None, include_sources=False)
    previous = _normalize_cjk_strong_markers(previous)
    projection = build_render_projection(MARKDOWN.encode(), SECTIONS)
    assert projection.markdown == previous
    assert projection.citation_presentations == citations
    assert projection.trace_source_render == trace
    receipt = projection.receipt
    assert receipt["version"] == PROJECTION_VERSION
    assert receipt["sourceSha256"] == _sha(MARKDOWN.encode())
    assert receipt["markdownSha256"] == _sha(previous.encode())
    assert receipt["sourceSha256"] != receipt["markdownSha256"]
    assert receipt["semanticSupportReused"] is False
    stages = receipt["stages"]
    assert [stage["name"] for stage in stages] == [
        "relocate_server_tables/1",
        "compact_single_column_tables/1",
        "insert_executive_summary/2",
        "collapse_repeated_values/1",
        "readable_large_amounts/1",
        "align_numeric_table_columns/1",
        "source_presentations/1",
        "normalize_cjk_strong_markers/1",
    ]
    assert stages[0]["sourceSha256"] == receipt["normalizedSourceSha256"]
    assert all(
        left["markdownSha256"] == right["sourceSha256"] for left, right in zip(stages, stages[1:])
    )
    assert stages[-1]["markdownSha256"] == receipt["markdownSha256"]
    assert verify_render_projection(receipt, MARKDOWN.encode(), SECTIONS)["status"] == "verified"


def test_raw_crlf_identity_is_not_replaced_by_normalized_text_identity():
    windows_source = MARKDOWN.replace("\n", "\r\n").encode()
    windows = build_render_projection(windows_source, SECTIONS)
    unix = build_render_projection(MARKDOWN.encode(), SECTIONS)
    assert windows.markdown == unix.markdown
    assert windows.receipt["sourceSha256"] != unix.receipt["sourceSha256"]
    assert windows.receipt["normalizedSourceSha256"] == unix.receipt["normalizedSourceSha256"]
    assert (
        verify_render_projection(windows.receipt, MARKDOWN.encode(), SECTIONS)["reason"]
        == "projection_source_changed"
    )
    assert (
        verify_render_projection(windows.receipt, windows_source, SECTIONS)["status"] == "verified"
    )


@pytest.mark.parametrize(
    "field",
    [
        "sourceSha256",
        "sourceSize",
        "normalizedSourceSha256",
        "markdownSha256",
        "contextSha256",
        "projectionSha256",
        "presentationSha256",
        "stages",
        "semanticSupportReused",
    ],
)
def test_receipt_fields_cannot_be_self_rehashed_into_a_pass(field):
    projection = build_render_projection(MARKDOWN, SECTIONS)
    receipt = projection.receipt
    receipt[field] = "forged"
    assert verify_render_projection(receipt, MARKDOWN, SECTIONS)["status"] == "unknown"


def test_rule_or_context_changes_do_not_reuse_prior_support():
    projection = build_render_projection(MARKDOWN, SECTIONS)
    receipt = projection.receipt
    receipt["version"] = "report-markdown/999"
    assert (
        verify_render_projection(receipt, MARKDOWN, SECTIONS)["reason"]
        == "projection_rule_unavailable"
    )
    assert verify_render_projection(None, MARKDOWN, SECTIONS)["reason"] == "projection_unavailable"
    changed_sections = copy.deepcopy(SECTIONS)
    changed_sections[0]["title"] = "支出分析"
    assert (
        verify_render_projection(projection.receipt, MARKDOWN, changed_sections)["reason"]
        == "projection_context_changed"
    )
    assert (
        verify_render_projection(projection.receipt, MARKDOWN, SECTIONS, include_sources=True)[
            "reason"
        ]
        == "projection_context_changed"
    )


def test_identity_is_detached_from_caller_and_returned_mutable_values():
    sections = copy.deepcopy(SECTIONS)
    projection = build_render_projection(MARKDOWN, sections)
    original = projection.receipt
    sections[0]["title"] = "changed"
    receipt = projection.receipt
    receipt["stages"][0]["name"] = "mutated"
    projection.trace_source_render["entries"].append({"forged": True})
    projection.citation_presentations.append({"forged": True})
    assert projection.receipt == original
    assert verify_render_projection(original, MARKDOWN, SECTIONS)["status"] == "verified"


def test_consumer_failures_and_invalid_encoding_are_unknown_not_exceptions():
    receipt = build_render_projection(MARKDOWN, SECTIONS).receipt
    assert (
        verify_render_projection(receipt, b"\xff", SECTIONS)["reason"] == "projection_check_failed"
    )
    assert (
        verify_render_projection(receipt, MARKDOWN, [{"title": "no code"}])["reason"]
        == "projection_check_failed"
    )


def test_compacted_table_retains_separate_source_and_presentation_identity():
    table = "\n".join(
        [
            "[[table:monthly]]",
            "| | 收入（元） |",
            "| --- | ---: |",
            *(f"| 2025年{month}月 | {month * 100} |" for month in range(1, 13)),
            "[[/table:monthly]]",
            "",
        ]
    )
    source = MARKDOWN + "\n" + table
    projection = build_render_projection(source, SECTIONS)
    stages = {stage.name: stage for stage in projection.stages}
    assert (
        stages["compact_single_column_tables/1"].source_sha256
        != stages["compact_single_column_tables/1"].markdown_sha256
    )
    assert "| 2025年 | 1月 | 2月 |" in projection.markdown
    assert source.endswith(table)
    assert verify_render_projection(projection.receipt, source, SECTIONS)["status"] == "verified"
    altered_source = source.replace("| 2025年6月 | 600 |", "| 2025年6月 | 999 |")
    assert (
        verify_render_projection(projection.receipt, altered_source, SECTIONS)["reason"]
        == "projection_source_changed"
    )


def test_sources_appendix_inputs_and_aliases_are_part_of_projection_identity():
    source = MARKDOWN + "\n收入来源[[citation:registered]]。\n"
    presentations = [
        {
            "citationId": "registered",
            "label": "冻结收入数据",
            "coverageItems": [{"label": "收入", "periods": ["2025-01"]}],
        }
    ]
    projection = build_render_projection(
        source, SECTIONS, citation_presentations=presentations, include_sources=True
    )
    assert "[来源 001]" in projection.markdown
    assert (
        verify_render_projection(
            projection.receipt,
            source,
            SECTIONS,
            citation_presentations=presentations,
            include_sources=True,
        )["status"]
        == "verified"
    )
    presentations[0]["coverageItems"][0]["periods"] = ["2024-01"]
    assert (
        verify_render_projection(
            projection.receipt,
            source,
            SECTIONS,
            citation_presentations=presentations,
            include_sources=True,
        )["reason"]
        == "projection_context_changed"
    )
    assert projection.citation_presentations[0]["coverageItems"][0]["periods"] == ["2025-01"]


def test_real_renderer_and_visual_consumer_keep_projection_failure_nonblocking(tmp_path):
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    from .test_report_runtime_full_render import (
        _DEPENDENCIES_OK,
        _SKIP_REASON,
        _build_workspace,
    )

    if not _DEPENDENCIES_OK:
        pytest.skip(_SKIP_REASON)
    workspace = tmp_path / "workspace"
    state = _build_workspace(workspace)
    runtime = ReportRuntime(workspace)
    result = runtime.render_markdown(
        state,
        "report.md",
        "out/report.pdf",
        ".reporting-tmp/workspace-report-projection-render/render.pdf",
    )
    render = result["render"]
    source = (workspace / "report.md").read_bytes()
    receipt = render["projection"]
    assert receipt["sourceSha256"] == render["markdown"]["sha256"] == _sha(source)
    state["render"] = render
    validated = runtime.validate_pdf(
        state,
        "out/report.pdf",
        ".reporting-tmp/workspace-report-projection-valid-validate",
    )
    assert validated["projectionCheck"]["status"] == "verified"
    pdf_before = (workspace / "out/report.pdf").read_bytes()
    word_before = (workspace / "out/report.docx").read_bytes()
    render["projection"] = {**receipt, "markdownSha256": "0" * 64}
    invalidated = runtime.validate_pdf(
        state,
        "out/report.pdf",
        ".reporting-tmp/workspace-report-projection-invalid-validate",
    )
    assert invalidated["projectionCheck"]["status"] == "unknown"
    assert invalidated["ok"] is False
    assert any(issue["code"] == "render_projection_unknown" for issue in invalidated["issues"])
    assert (workspace / "out/report.pdf").read_bytes() == pdf_before
    assert (workspace / "out/report.docx").read_bytes() == word_before
