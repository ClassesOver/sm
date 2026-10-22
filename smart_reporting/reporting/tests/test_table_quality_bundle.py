"""Table checks use actual registered files and current Markdown, without old passes."""

import hashlib
import json

import pytest

from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

from .test_trace_subject_validate import _make_editor_with_subject

_PLAIN_TABLE = "| 指标 | 金额 |\n| --- | --- |\n| 收入 | 100 |"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("grain", [None, "day", "month"])
@pytest.mark.parametrize("wrong_month", [False, True])
async def test_table_period_labels_follow_declared_grain(tmp_path, grain, wrong_month):
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    documents = {}
    for file in index.files:
        if file.resource_id in {fact.file_resource_id for fact in index.fact_files}:
            documents[file.resource_id] = json.loads(await editor.trace._read_registered_file(
                context, file, max_bytes=16 * 1024 * 1024
            ))
    table = index.tables[0]
    entry = documents[table.cells[0].fact_refs[0].file_resource_id]["metrics"][0]
    entry["periodGranularity"] = grain
    for point in entry["periodValues"]:
        point["period"] += "-01"
    table = table.model_copy(update={
        "row_keys": tuple(key + "-01" for key in table.row_keys),
        "cells": tuple(cell.model_copy(update={"row_key": cell.row_key + "-01"}) for cell in table.cells),
    })
    index = index.model_copy(update={"tables": (table,)})
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)).decode()
    if wrong_month:
        markdown = markdown.replace("2025-09", "2025-08")
    # Freeze the displayed labels as well: unchanged labels still require semantic checks.
    table = table.model_copy(update={"origin_markdown": markdown})
    index = index.model_copy(update={"tables": (table,)})
    check = evaluate_table_quality(index, markdown, documents)["tbl-1"]
    assert check.status == ("verified" if grain == "month" and not wrong_month else "unknown")
    assert ("cell_period_label_mismatch" in check.reasons) == (grain != "month" or wrong_month)


@pytest.mark.parametrize(
    ("markdown", "registered", "expected"),
    [
        (_PLAIN_TABLE, set(), (1,)),
        (f"[[table:t]]\n\n{_PLAIN_TABLE}\n\n[[/table:t]]", {"t"}, ()),
        (f"[[table:foreign]]\n\n{_PLAIN_TABLE}\n\n[[/table:foreign]]", {"t"}, (3,)),
        (f"```markdown\n{_PLAIN_TABLE}\n```", set(), ()),
        (f"<!--\n{_PLAIN_TABLE}\n-->", set(), ()),
        (f"`[[table:t]]`\n\n{_PLAIN_TABLE}\n\n`[[/table:t]]`", {"t"}, (3,)),
        (f"[[table:t]]\n\n{_PLAIN_TABLE}\n\n{_PLAIN_TABLE}\n\n[[/table:t]]", {"t"}, (3, 7)),
        (
            f"[[table:t]]\n\n{_PLAIN_TABLE}\n\n[[/table:t]]\n\n"
            f"[[table:t]]\n\n{_PLAIN_TABLE}\n\n[[/table:t]]",
            {"t"},
            (3, 11),
        ),
        ("> " + _PLAIN_TABLE.replace("\n", "\n> "), set(), (1,)),
    ],
)
def test_rendered_table_coverage(markdown, registered, expected):
    from smart_reporting.reporting.trace.table_quality import uncovered_table_lines

    assert uncovered_table_lines(markdown, registered) == expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_unregistered_table_warns_without_downgrading_verified_table(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
        if file.media_type in {"application/json", "text/markdown"}
    }
    markdown = sources[index.markdown_file_resource_id].decode() + "\n\n" + _PLAIN_TABLE
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    assert quality.table_checks["tbl-1"].status == "verified"
    warnings = [issue for issue in quality.issues if issue.code == "table_coverage_unknown"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].reasons[0] == "table_registration_unavailable"
    # Cached bundles from the checker without coverage must not remain current.
    from smart_reporting.reporting.trace.quality_bundle import quality_bundle_is_current

    old = quality.model_copy(update={"semantic_rule_versions": {}})
    assert not quality_bundle_is_current(old, index, markdown, input_sha256=quality.input_sha256)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "sort",
        "value",
        "period",
        "duplicate",
        "missing",
        "pointer",
        "selector",
        "unit",
        "frozen_period",
    ],
)
async def test_table_quality_rechecks_frozen_cells(tmp_path, fault):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
        if file.media_type in {"application/json", "text/markdown"}
    }
    markdown = sources[index.markdown_file_resource_id].decode()
    if fault == "sort":
        lines = markdown.splitlines()
        positions = [i for i, line in enumerate(lines) if line.startswith("| 2025-")]
        assert len(positions) == 2
        a, b = positions
        lines[a], lines[b] = lines[b], lines[a]
        markdown = "\n".join(lines)
    elif fault == "value":
        markdown = markdown.replace("1,200", "9,999")
    elif fault == "period":
        markdown = markdown.replace("2025-09", "2024-09")
    elif fault == "duplicate":
        line = next(line for line in markdown.splitlines() if line.startswith("| 2025-09"))
        markdown = markdown.replace(line, line + "\n" + line)
    elif fault == "missing":
        sources.pop(index.fact_files[0].file_resource_id)
    elif fault in {"pointer", "selector", "unit", "frozen_period"}:
        table = index.tables[0]
        if fault in {"unit", "frozen_period"}:
            # A bad frozen display must not become verified just because it stayed unchanged.
            origin = (
                markdown.replace("1,200", "1,200亿元")
                if fault == "unit"
                else markdown.replace("2025-09", "2024-09")
            )
            markdown = origin
            table = table.model_copy(update={"origin_markdown": origin})
        else:
            cell = table.cells[0]
            if fault == "selector":
                cell = cell.model_copy(update={"value_selector": "periodValues.1"})
            else:
                ref = cell.fact_refs[0].model_copy(update={"json_pointer": "/metrics/99"})
                cell = cell.model_copy(update={"fact_refs": (ref,)})
            table = table.model_copy(update={"cells": (cell, *table.cells[1:])})
        index = index.model_copy(update={"tables": (table,)})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    check = quality.table_checks["tbl-1"]
    assert check.scope == "frozen_cells"
    assert check.status == ("verified" if fault in {"none", "sort"} else "unknown")
    if fault in {"none", "sort"}:
        assert check.checked_cells == 2
    else:
        assert any(issue.code == "table_support_unknown" for issue in quality.issues)
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["quality"]["status"] == "evaluated"
    assert "dataCheck" in result["tables"][0]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_duplicate_row_cannot_count_as_a_valid_cell(tmp_path):
    from .test_trace_subject_validate import _table_markdown, _validate_tables

    markdown = _table_markdown([["本期", "3,600"], ["本期", "3,600"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path, markdown)
    assert result["tableSummary"]["valid"] == 1
    assert result["tableSummary"]["unbound"] == 1
    assert [location["rowKey"] for location in result["tables"][0]["locations"]] == ["row:prev"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_frozen_table_rechecks_after_revision_copy_and_isolates_bad_table(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
        if file.media_type in {"application/json", "text/markdown"}
    }
    original = sources.pop(index.markdown_file_resource_id).decode()
    table = index.tables[0].model_copy(update={"origin_markdown": original})
    bad = table.model_copy(
        update={"table_id": "tbl-bad", "origin_markdown": original.replace("tbl-1", "tbl-bad")}
    )
    markdown = original + "\n\n" + original.replace("tbl-1", "tbl-bad").replace("1,200", "9,999")
    copied = index.model_copy(update={"revision": 2, "tables": (table, bad)})
    first = evaluate_quality_bundle(copied, markdown, sources, authorization_scope_hash="c" * 64)
    assert first.table_checks["tbl-1"].status == "verified"
    assert first.table_checks["tbl-bad"].status == "unknown"
    # A prior pass is never an input to the next evaluation.
    sources[index.fact_files[0].file_resource_id] += b" "
    second = evaluate_quality_bundle(copied, markdown, sources, authorization_scope_hash="c" * 64)
    assert second.table_checks["tbl-1"].status == "unknown"
    assert first.input_sha256 != second.input_sha256


@pytest.mark.parametrize(
    "text,value,unit,expected",
    [
        ("9999（原值1200）", 1200, "元", False),
        ("9999元（原值1200元）", 1200, "元", False),
        ("1200（原值9999）", 1200, "元", True),
        ("0（备注1200）", 1200, "元", False),
        ("1200美元", 1200, "元", False),
        ("1200元", 1200, None, False),
        ("1200", 1200, None, True),
        ("[1200]9999", 1200, "元", False),
        ("约1.20万元（原值9999元）", 12000, "元", True),
        ("减少20%（上期5%）", -20, "%", True),
        ("2025年估算1200元（原值9999）", 1200, "元", True),
    ],
)
def test_unscaled_table_checks_primary_value_instead_of_note(text, value, unit, expected):
    from smart_reporting.reporting.trace.table_quality import table_value_matches

    assert table_value_matches(text, value, unit, "金额") is expected


@pytest.mark.parametrize(
    "row,selector,expected",
    [
        ("total", "total", True),
        ("total", "periodValues.0", False),
        ("period:2025-09", "periodValues.0", True),
        ("period:2025-09", "periodValues.1", False),
        ("period:2025-09", "total", False),
        ("comparison:0:currentTotal", "baselineTotal", False),
        ("comparison:0:changeRate", "change", False),
        ("comparison:0:currentTotal", "currentTotal", True),
        ("comparison:0:currentTotal", "comparison:0:currentTotal", True),
    ],
)
def test_equal_values_do_not_override_reserved_row_role(row, selector, expected):
    from smart_reporting.reporting.trace.table_quality import table_selector_matches

    entry = {
        "total": 1200,
        "currentTotal": 1200,
        "baselineTotal": 1200,
        "change": 1200,
        "changeRate": 1200,
        "periodValues": [
            {"period": "2025-09", "value": 1200},
            {"period": "2025-10", "value": 1200},
        ],
    }
    assert table_selector_matches(entry, row, selector) is expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_equal_month_values_cannot_hide_wrong_selector_in_editor(tmp_path):
    from unittest.mock import AsyncMock

    editor, _, context = await _make_editor_with_subject(
        tmp_path,
        period_table=True,
        metric_values=(1200, 1200),
    )
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
        if file.media_type in {"application/json", "text/markdown"}
    }
    markdown = sources[index.markdown_file_resource_id].decode()
    table = index.tables[0]
    wrong = table.cells[0].model_copy(update={"value_selector": "periodValues.1"})
    table = table.model_copy(update={"cells": (wrong, *table.cells[1:])})
    index = index.model_copy(update={"tables": (table,)})
    editor.trace.require_index = AsyncMock(return_value=index)
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["tableSummary"]["valid"] == 1
    assert result["tableSummary"]["stale"] == 1
    assert result["tables"][0]["dataCheck"]["status"] == "unknown"
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    assert "cell_selector_binding_mismatch" in quality.table_checks["tbl-1"].reasons


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_does_not_accept_a_note_as_the_main_table_value(tmp_path):
    from .test_trace_subject_validate import _table_markdown, _validate_tables

    markdown = _table_markdown([["本期", "9,999（原值3,600）"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path, markdown)
    assert result["tableSummary"]["valid"] == 1
    assert result["tableSummary"]["stale"] == 1


@pytest.mark.parametrize(
    "value,source_unit,text,header,expected",
    [
        (20, "%", "20", "占比（%）", True),
        (20, "元", "20", "占比（%）", False),
        (20, "%", "20", "占比（‰）", False),
        (20, "%", "20", "变化（个百分点）", False),
        (20, "个百分点", "20", "变化（个百分点）", True),
        (20, "个百分点", "20个百分点", "占比（%）", False),
        (20, "%", "20%", "变化（个百分点）", False),
        (20, "元/人次", "20", "次均费用（元/人次）", True),
        (20, "元", "20", "次均费用（元/人次）", False),
        (20, "元/人次", "20元/人次", "金额（元）", False),
        (20, "元", "20元/秒", "数值", False),
        (20, "元", "20", "费用（元/秒）", False),
        (20, "元", "20%", "数值", False),
        (20, "%", "20个百分点", "数值", False),
        (20, "元/人", "20元/人次/日", "数值", False),
        (20, "%", "20%%", "数值", False),
        (20, "元", "20元／秒", "金额（元）", False),
        (20, "元", "20元/人次/日", "数值", False),
        (20, "元/人次", "20元/人次/日", "次均费用（元/人次）", False),
        (20000, "元", "20000元", "收入（万元）", True),
        (20, "人次", "20人次", "收入（元）", False),
        (20, "床日", "20", "住院量（床日）", True),
    ],
)
def test_table_header_and_explicit_units_have_compatible_dimensions(
    value,
    source_unit,
    text,
    header,
    expected,
):
    from smart_reporting.reporting.trace.table_quality import table_value_matches

    assert table_value_matches(text, value, source_unit, header) is expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "source_unit,header,text,expected",
    [
        ("%", "占比（%）", "20", "verified"),
        ("%", "变化（个百分点）", "20", "unknown"),
        ("个百分点", "占比（%）", "20个百分点", "unknown"),
        ("元/人次", "金额（元）", "20元/人次", "unknown"),
        ("元", "费用（元/秒）", "20", "unknown"),
    ],
)
async def test_editor_and_quality_agree_on_table_dimensions(
    tmp_path, source_unit, header, text, expected
):
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    editor, _, context = await _make_editor_with_subject(
        tmp_path,
        period_table=True,
        metric_values=(20, 20),
        metric_unit=source_unit,
    )
    index = await editor.trace.require_index(context)
    markdown = render_table_markdown("tbl-1", (header,), [["2025-09", text], ["2025-10", text]])
    table = index.tables[0]
    table = table.model_copy(
        update={
            "column_keys": (header,),
            "origin_markdown": markdown,
            "cells": tuple(cell.model_copy(update={"column_key": header}) for cell in table.cells),
        }
    )
    index = index.model_copy(update={"tables": (table,)})
    editor.trace.require_index = AsyncMock(return_value=index)
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["tables"][0]["dataCheck"]["status"] == expected
    assert result["tableSummary"]["valid"] == (2 if expected == "verified" else 0)
    assert result["tableSummary"]["stale"] == (0 if expected == "verified" else 2)


def test_legacy_wrapper_without_blank_line_covers_its_registered_table():
    # 审阅：旧格式结束标记紧跟末行时被 markdown-it 并入表格，已登记的旧表被误报 table_coverage_unknown。
    from smart_reporting.reporting.trace.table_quality import uncovered_table_lines

    legacy = "[[table:t1]]\n|a|b|\n|---|---|\n|1|2|\n[[/table:t1]]"
    assert uncovered_table_lines(legacy, {"t1"}) == ()
    assert uncovered_table_lines(legacy + "\n\n|x|y|\n|---|---|\n|3|4|\n", {"t1"}) == (7,)
    assert uncovered_table_lines(legacy, set()) == (2,)
