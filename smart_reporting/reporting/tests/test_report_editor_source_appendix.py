from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.service import _export_citation_presentations


def test_shared_fact_claims_keep_all_markers_and_one_first_appearance_number() -> None:
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown

    reference = SimpleNamespace(file_resource_id="file-1", json_pointer="/metrics/0")
    index = SimpleNamespace(
        datasets=(), tables=(), chart_traces=(), files=(), computations=(),
        subject_bindings=tuple(SimpleNamespace(
            claim_id=claim_id, subject_id=f"sub-{position:016x}",
            fact_refs=(reference,), subject_kind="text_claim",
            locator=SimpleNamespace(table_id=None),
        ) for position, claim_id in enumerate(("claim-first", "claim-second"))),
    )
    payload = _build_export_trace_sources(
        index, {"subjects": [
            {"claimId": "claim-first", "status": "valid", "factValue": 3600},
            {"claimId": "claim-second", "status": "stale", "factValue": 3600},
        ]}, public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    assert len(payload["claims"]) == 1
    assert payload["claims"][0]["claimIds"] == ["claim-first", "claim-second"]
    visible, _, trace = _pdf_markdown(
        "先出现3800[[claim:claim-second]]，再出现3600[[claim:claim-first]]。",
        [], trace_sources=payload,
    )
    assert visible.count("[数据来源 001]") == 2
    assert len(trace["entries"]) == 1
    assert trace["entries"][0]["status"] == "stale"
    assert len(trace["entries"][0]["links"]) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_only_fact_sources_and_claim_warnings_survive_export(tmp_path) -> None:
    import hashlib

    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.tests.test_trace_subject_validate import (
        _make_editor_with_subject,
    )

    editor, _, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    assert index is not None
    markdown = await editor.workspace.aread_text(context.scope["threadId"], context.markdown_path)
    markdown += "\n2025-10收入3600亿元[[claim:claim-1]]\n"
    validation = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert validation["subjects"][0]["status"] == "valid"
    assert len(validation["subjects"][0]["warnings"]) == 2
    assert validation["tables"][0]["datasetIds"] == ["dataset-url-abc0001"]
    assert validation["tables"][0]["methods"] == ["sum(revenue)"]
    payload = _build_export_trace_sources(
        index, validation, public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    assert payload["claims"][0]["status"] == "stale"
    # 只有表格引用的事实同样拥有源文件与方法摘要，不依赖正文 claim 的缓存。
    table_only = index.model_copy(update={"subject_bindings": ()})
    payload = _build_export_trace_sources(
        table_only, validation, public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    assert payload["claims"] == []
    assert payload["tables"][0]["datasetIds"] == ["dataset-url-abc0001"]
    assert payload["tables"][0]["methods"] == ["sum(revenue)"]
    validation["tables"][0]["insertedRows"] = 1
    payload = _build_export_trace_sources(
        table_only, validation, public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    assert payload["tables"][0]["status"] == "stale"


def _subject(subject_id: str, kind: str, table_id: str | None = None):
    return SimpleNamespace(
        subject_id=subject_id,
        subject_kind=kind,
        locator=SimpleNamespace(table_id=table_id),
    )


def test_export_summary_records_all_omitted_counts_without_mutating_registry() -> None:
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _trace_source_appendix_html,
    )
    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown

    dataset_ids = [f"dataset-{number:06d}" for number in range(12)]
    methods = [f"method-{number}" for number in range(7)]
    subjects = tuple(SimpleNamespace(
        subject_id=f"sub-{number:016x}", subject_kind="table_cell", claim_id=None,
        locator=SimpleNamespace(table_id="tbl-1"),
    ) for number in range(12))
    index = SimpleNamespace(
        datasets=tuple(SimpleNamespace(dataset_id=key, filename=key + ".csv", business_label=key, period_roles=()) for key in dataset_ids),
        subject_bindings=subjects, tables=(SimpleNamespace(table_id="tbl-1", cells=()),),
        chart_traces=(), files=(), computations=(),
    )
    payload = _build_export_trace_sources(
        index, {"tables": [{"tableId": "tbl-1", "cells": {"valid": 12}, "datasetIds": dataset_ids, "methods": methods}]},
        public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    entry = payload["tables"][0]
    assert entry["omittedCounts"] == {"datasetIds": 2, "methods": 2, "subjectIds": 2, "links": 2}
    assert len(entry["datasetIds"]) == len(entry["links"]) == 10
    assert len(entry["methods"]) == 5
    assert len(index.subject_bindings) == len(index.datasets) == len(dataset_ids) == 12
    assert len(methods) == 7
    _, _, trace = _pdf_markdown("[[table:tbl-1]]", [], trace_sources=payload)
    rendered = _trace_source_appendix_html(trace)
    assert "源文件省略 2 项；方法省略 2 项；在线定位省略 2 项" in rendered


def test_claim_and_chart_summary_keep_markers_and_count_omitted_fields() -> None:
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _trace_source_appendix_html,
    )
    from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown

    dataset_ids = tuple(f"dataset-{number:06d}" for number in range(11))
    reference = SimpleNamespace(file_resource_id="file-1", json_pointer="/metrics/0")
    bindings = tuple(SimpleNamespace(
        subject_id=f"sub-{number:016x}", claim_id=f"claim-{number}", fact_refs=(reference,),
        subject_kind="text_claim", locator=SimpleNamespace(table_id=None),
    ) for number in range(12))
    index = SimpleNamespace(
        datasets=tuple(SimpleNamespace(dataset_id=key, filename=key + ".csv", business_label=key, period_roles=()) for key in dataset_ids),
        subject_bindings=bindings, tables=(), computations=(),
        files=(SimpleNamespace(resource_id="image-1", path="reports/chart.png"),),
        chart_traces=(SimpleNamespace(
            chart_id="chart_001", image_file_resource_id="image-1", computation_id=None,
            dataset_ids=dataset_ids, transform_notes=tuple(f"转换{number}" for number in range(12)), axis_unit="元",
        ),),
    )
    payload = _build_export_trace_sources(
        index, {"subjects": [{"claimId": binding.claim_id, "status": "valid", "factValue": 3600, "datasetIds": list(dataset_ids)} for binding in bindings]},
        public_base_url="https://reports.example.com", report_id="report-1", revision=2,
    )
    assert payload["claims"][0]["omittedCounts"] == {"datasetIds": 1, "subjectIds": 2, "links": 2}
    assert len(payload["claims"][0]["claimIds"]) == 12
    assert payload["charts"][0]["omittedCounts"] == {"datasetIds": 1, "transformNotes": 2}
    visible, _, trace = _pdf_markdown(
        "结论[[claim:claim-11]]，再次[[claim:claim-0]]。", [], trace_sources=payload,
    )
    assert visible.count("[数据来源 001]") == 2
    rendered = _trace_source_appendix_html(trace)
    assert "转换说明省略 2 项" in rendered
    assert "在线定位省略 2 项" in rendered


def test_export_source_budget_is_still_explicit_after_summary_limits() -> None:
    from smart_reporting.report_editor.service import _build_export_trace_sources
    from smart_reporting.reporting.models import ReportingError

    index = SimpleNamespace(
        datasets=tuple(SimpleNamespace(
            dataset_id=f"dataset-{number:06d}", filename="文件" * 100 + ".csv",
            business_label="业务" * 100, period_roles=(),
        ) for number in range(30)),
        subject_bindings=(), tables=(), chart_traces=(), files=(), computations=(),
    )
    with pytest.raises(ReportingError) as error:
        _build_export_trace_sources(index, {}, public_base_url="https://reports.example.com",
            report_id="report-1", revision=2)
    assert error.value.code == "report_editor_trace_sources_too_large"
    assert len(index.datasets) == 30


def test_export_appendix_projects_current_subject_status_and_new_revision_links() -> None:
    text_subject = "sub-aaaaaaaaaaaaaaaa"
    table_subject = "sub-bbbbbbbbbbbbbbbb"
    presentations = [
        {
            "citationId": "citation_001",
            "label": "收入",
            "coverageItems": [],
            "status": "valid",
            "links": [
                {"subjectId": text_subject, "label": "正文结论", "url": "https://old"},
                {"subjectId": table_subject, "label": "表格单元格", "url": "https://old"},
            ],
        }
    ]
    validation = {
        "subjects": [{"subjectId": text_subject, "status": "stale"}],
        "tables": [
            {
                "tableId": "table_001",
                "cells": {"valid": 3, "stale": 0, "unbound": 1},
            }
        ],
    }
    index = SimpleNamespace(
        subject_bindings=(
            _subject(text_subject, "text_claim"),
            _subject(table_subject, "table_cell", "table_001"),
        )
    )

    rebound = _export_citation_presentations(
        presentations,
        validation,
        index,
        public_base_url="https://reports.example.com/",
        report_id="report/1",
        revision=2,
    )

    assert rebound[0]["status"] == "unbound"
    assert [item["url"] for item in rebound[0]["links"]] == [
        "https://reports.example.com/reports/v1/editor/report%2F1/2?subject=" + text_subject,
        "https://reports.example.com/reports/v1/editor/report%2F1/2?subject=" + table_subject,
    ]
    assert presentations[0]["status"] == "valid"


def test_export_appendix_preserves_status_when_citation_has_no_bound_subject() -> None:
    presentations = [
        {
            "citationId": "citation_001",
            "label": "收入",
            "coverageItems": [],
            "status": "missing",
            "links": [],
        }
    ]

    rebound = _export_citation_presentations(
        presentations,
        {"subjects": [], "tables": []},
        SimpleNamespace(subject_bindings=()),
        public_base_url="https://reports.example.com",
        report_id="report-1",
        revision=3,
    )

    assert rebound[0]["status"] == "missing"


@pytest.mark.parametrize("kind", ["subjects", "tables", "charts"])
def test_citation_without_links_projects_only_registered_dataset_status(kind) -> None:
    presentations = [{"citationId": citation_id, "status": "valid"}
                     for citation_id in ("citation_001", "citation_002")]
    entry = {"datasetIds": ["dataset-1"], "status": "stale"}
    if kind == "tables":
        entry.update(tableId="tbl-1", cells={"valid": 1, "stale": 1})
    result = _export_citation_presentations(
        presentations, {kind: [entry]}, SimpleNamespace(subject_bindings=()),
        public_base_url="https://reports.example.com", report_id="report-1", revision=2,
        citations=(SimpleNamespace(citation_id="citation_001", dataset_id="dataset-1"),
                   SimpleNamespace(citation_id="citation_002", dataset_id="dataset-2")),
    )
    assert [item["status"] for item in result] == ["stale", "valid"]
    assert presentations[0]["status"] == "valid"


def test_citation_appendix_projects_soft_warning_and_inserted_row_as_stale() -> None:
    presentations = [{
        "citationId": "citation_001", "status": "valid",
        "links": [{"subjectId": "sub-a", "url": "https://old"}],
    }]
    index = SimpleNamespace(subject_bindings=(_subject("sub-a", "table_cell", "tbl-1"),))
    for validation in (
        {"subjects": [{"subjectId": "sub-a", "status": "valid", "warnings": ["单位不一致"]}]},
        {"tables": [{"tableId": "tbl-1", "cells": {"valid": 2}, "insertedRows": 1}]},
    ):
        rebound = _export_citation_presentations(
            presentations, validation, index, public_base_url="https://reports.example.com",
            report_id="report-1", revision=2,
        )
        assert rebound[0]["status"] == "stale"
