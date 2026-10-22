"""R002/R004/R035: unknown metadata cannot become a calendar or unit proof."""

import hashlib
import json

import pytest

from smart_reporting.reporting.trace.assertions import AssertionRequest
from smart_reporting.reporting.trace.subject_builder import fact_periods

from .test_assertion_compiler import compiler, facts, token


@pytest.mark.parametrize("unit", [" ", "\t", "\u3000"])
def test_blank_units_do_not_issue_supported_value_assertions(unit):
    result = compiler([facts(scope={"院区": "北院"}, unit=unit)]).compile(
        AssertionRequest(operation="value", operands=(token(unit=unit),)))
    assert result.status == "unknown" and "unit_unknown" in result.reasons
    assert result.value is None


@pytest.mark.parametrize("period", [" ", "unknown", "2025-00", "2025-13", "2025-02-30", "2025-02-15"])
def test_invalid_selected_buckets_do_not_issue_supported_value_assertions(period):
    document = json.loads(facts(scope={"院区": "北院"}))
    document["metrics"][0]["periodValues"][0]["period"] = period
    result = compiler([json.dumps(document)]).compile(
        AssertionRequest(operation="value", operands=(token(selector="periodValues.0"),)))
    assert result.status == "unknown" and "period_unknown" in result.reasons
    assert result.value is None


@pytest.mark.parametrize("bad", [{}, {"period": ""}, {"period": None}, {"period": " "}, {"period": "2025-02-30"}])
def test_invalid_explicit_buckets_cannot_borrow_the_declared_range(bad):
    entry = {"periodGranularity": "month", "periodStart": "2025-01", "periodEnd": "2025-03",
             "periodValues": [{"period": "2025-01"}, bad]}
    assert fact_periods(entry) == ()


@pytest.mark.parametrize("period", ["2025-02", "2025-2", "2025-02-01", "20250201", "2025/2/1"])
def test_valid_month_bucket_formats_use_the_same_calendar_identity(period):
    assert fact_periods({"periodGranularity": "month", "periodValues": [{"period": period}]}) == ("2025-02",)


@pytest.mark.parametrize("grain,period", [("year", "2025-02-01"), ("day", "2025-02"), ("month", "2025")])
def test_bucket_labels_do_not_claim_a_different_declared_granularity(grain, period):
    assert fact_periods({"periodGranularity": grain, "periodValues": [{"period": period}]}) == ()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_invalid_period_withdraws_approved_answer_and_overview_value(tmp_path):
    from smart_reporting.reporting.trace.warning_ledger import build_warning_ledger

    from .test_quality_answer_review import case, evaluate

    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    baseline = evaluate(index, markdown, sources, questions, plan)
    assert baseline.question_coverage["answered"] == 1
    resource = index.fact_files[0].file_resource_id
    document = json.loads(sources[resource])
    document["metrics"][0]["periodValues"][1]["period"] = "2025-10-32"
    sources[resource] = json.dumps(document, ensure_ascii=False).encode()
    index = index.model_copy(update={"files": tuple(
        file.model_copy(update={"size": len(sources[resource]), "sha256": hashlib.sha256(sources[resource]).hexdigest()})
        if file.resource_id == resource else file for file in index.files)})
    current = evaluate(index, markdown, sources, questions, plan)
    assert current.assertions[0].status == "unknown"
    assert "period_unknown" in current.assertions[0].reasons
    assert current.question_coverage["answered"] == 0
    assert current.management_overview.rows[0].status == "unknown"
    assert not current.management_overview.rows[0].evidence
    assert current.input_sha256 != baseline.input_sha256
    assert current.semantic_rule_versions["periodIdentity"] == "1"
    ledger = build_warning_ledger(current, index)
    fact_group = next(group for group in ledger.groups if group.target_kind == "fact")
    assert fact_group.assessments == ("definition_review",)
    assert "R002" in fact_group.review_ids
    assert fact_group.adjudication == "not_adjudicated"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_rejects_invalid_bucket_identity_even_when_display_is_unchanged(tmp_path):
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

    from .test_trace_subject_validate import _make_editor_with_subject

    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    sources = {f.resource_id: await editor.trace._read_registered_file(context, f, max_bytes=16 * 1024 * 1024)
               for f in index.files}
    table = index.tables[0]
    documents = {entry.file_resource_id: json.loads(sources[entry.file_resource_id]) for entry in index.fact_files}
    metric = documents[table.cells[0].fact_refs[0].file_resource_id]["metrics"][0]
    metric["periodGranularity"] = "month"
    metric["periodValues"][0]["period"] = "2025-02-30"
    markdown = sources[index.markdown_file_resource_id].decode().replace("2025-09", "2025-02")
    table = table.model_copy(update={
        "row_keys": ("period:2025-02-30", *table.row_keys[1:]),
        "cells": tuple(cell.model_copy(update={"row_key": "period:2025-02-30"})
                       if cell.row_key == table.row_keys[0] else cell for cell in table.cells),
        "origin_markdown": markdown,
    })
    check = evaluate_table_quality(index.model_copy(update={"tables": (table,)}), markdown, documents)[table.table_id]
    assert check.status == "unknown"
    assert "cell_period_identity_unavailable" in check.reasons
    assert check.checked_cells == 1  # The independent valid month still checks.
