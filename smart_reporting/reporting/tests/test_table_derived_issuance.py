"""Original-cell provenance survives numeric checking and reference issuance."""

import hashlib
import json

import pytest

from smart_reporting.reporting.trace.numeric_text import derived_number_values
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
)
from smart_reporting.reporting.trace.table_sources import resolve_table_derivation

RID = "trf-0123456789abcdefabcd"


def table_bytes(rows, *, columns=None, metadata=None, title=None):
    table = {
        "columns": columns or ["项目", "金额"],
        "rows": rows,
        "columnMeta": metadata if metadata is not None else {"金额": {"unit": "万元"}},
    }
    if title:
        table["title"] = title
    return json.dumps({"findings": [table]}, ensure_ascii=False).encode()


def issue(text, raw, *, sources=None, contents=None):
    return render_bound_numbers(
        text, contents or [raw.decode()], key="table-issuance",
        table_sources={RID: raw} if sources is None else sources,
    )


@pytest.mark.parametrize("text,expected,coefficients", [
    ("甲项目比乙项目多60.00万元。", "60.00万元", ["1", "-1"]),
    ("乙项目比甲项目少60.00万元。", "60.00万元", ["1", "-1"]),
    ("乙项目比甲项目多-60.00万元。", "60.00万元", ["1", "-1"]),
    ("甲项目比乙项目多59.99万元。", "60.00万元", ["1", "-1"]),
    ("甲项目比乙项目多0.0060亿元。", "0.01亿元", ["0.0001", "-0.0001"]),
])
def test_difference_issuance_retains_coordinates_sign_scale_and_corrected_display(
    text, expected, coefficients,
):
    raw = table_bytes([["甲", 100], ["乙", 40]])
    markdown, references, notices = issue(text, raw)
    assert expected in markdown and not notices
    assert len(references) == 1
    reference = references[0]
    assert reference.display_text == expected
    assert reference.table_derivation is not None
    assert reference.statement_sha256
    assert reference.model_dump(by_alias=True)["tableDerivation"]
    operands = reference.table_derivation.operands
    assert [(op.table_pointer, op.row_index, op.column_index) for op in operands] == [
        ("/findings/0", 0, 1), ("/findings/0", 1, 1),
    ]
    assert [op.coefficient for op in operands] == coefficients
    selected = resolve_table_derivation(reference.token, reference.table_derivation, {RID: raw})
    assert selected is not None
    assert selected["value"] == (-60 if expected.startswith("-") else 0.006 if "亿元" in expected else 60)
    assert reference.token.startswith("{{tableDerived:")
    assert anchor_bound_numbers(markdown, references, notices).count("[[claim:") == 1


def test_top_n_issuance_keeps_ranked_original_coordinates_and_source_periods():
    raw = table_bytes(
        [["丙", 10], ["合计", 100], ["乙", 35], ["甲", 55]],
        columns=["项目", "占比"], metadata={"占比": {"unit": "%", "isPercent": True}},
        title="2025年1-3月收入类型结构分布",
    )
    markdown, references, notices = issue("2025年1-3月甲与乙前两项合计占比90.00%。", raw)
    assert "90.00%" in markdown and not notices
    assert len(references) == 1
    reference = references[0]
    assert [op.row_index for op in reference.table_derivation.operands] == [3, 2]
    selected = resolve_table_derivation(reference.token, reference.table_derivation, {RID: raw})
    assert selected["value"] == 90
    assert selected["periods"] == ("2025-01", "2025-02", "2025-03")


@pytest.mark.parametrize("fault", ["untrusted", "different_bytes", "duplicate_identity", "malformed_row"])
def test_supported_table_values_stay_visible_without_unsafe_reference(fault):
    rows = [["甲", 100], ["乙", 40]]
    if fault == "malformed_row":
        rows.insert(1, ["坏行", 1, "extra"])
    raw = table_bytes(rows)
    sources = {
        "untrusted": {},
        "different_bytes": {RID: raw + b" "},
        "duplicate_identity": {RID: raw, "trf-aaaaaaaaaaaaaaaaaaaa": raw},
        "malformed_row": {RID: raw},
    }[fault]
    markdown, references, notices = issue("甲项目比乙项目多60.00万元。", raw, sources=sources)
    assert markdown == "甲项目比乙项目多60.00万元。"
    assert not references and not notices


def test_display_alias_collision_does_not_overwrite_original_column_coordinates():
    from smart_reporting.reporting.tests.test_numeric_text import _metric_pair_document

    document = json.loads(_metric_pair_document())
    document["metrics"][0]["field"] = "budget"
    document["metrics"][0]["displayName"] = "实际支出"
    raw = table_bytes(
        [["甲", 100, 40], ["乙", 90, 20]], columns=["项目", "budget", "实际支出"],
        metadata={"budget": {"unit": "元"}, "实际支出": {"unit": "元"}},
    )
    values = derived_number_values([raw.decode(), json.dumps(document)], table_sources={RID: raw})
    entries = [entry for _, entry in values.derived_entries() if entry.table_derivation]
    assert entries
    assert {op.column_index for entry in entries for op in entry.table_derivation.operands} == {1, 2}


def test_source_byte_or_operand_tampering_invalidates_issued_reference():
    raw = table_bytes([["甲", 100], ["乙", 40]])
    _, references, _ = issue("甲项目比乙项目多60.00万元。", raw)
    reference = references[0]
    assert resolve_table_derivation(reference.token, reference.table_derivation, {RID: raw + b" "}) is None
    operands = reference.table_derivation.operands
    tampered = reference.table_derivation.model_copy(update={
        "operands": (operands[0].model_copy(update={"coefficient": "-1"}), operands[1]),
    })
    assert resolve_table_derivation(reference.token, tampered, {RID: raw}) is None


SUPPLEMENT_RID = "trf-0123456789abcdefabc1"
CHART_RID = "trf-0123456789abcdefabc2"
OTHER_RID = "trf-0123456789abcdefabc3"


def _chart_bytes(rows, declared_sha, *, columns=None, metadata=None):
    return json.dumps({
        "chartId": "chart-001",
        "columns": columns or ["项目", "金额"],
        "rows": rows,
        "columnMeta": metadata if metadata is not None else {"金额": {"unit": "万元"}},
        "source": {"path": "run/evidence/analysis_001/attempt-1/supplement.json",
                   "sha256": declared_sha},
        "rowCount": len(rows),
    }, ensure_ascii=False).encode()


def test_declared_chart_projection_collapses_to_verified_supplement_source():
    supplement = table_bytes([["甲", 100], ["乙", 40]])
    chart = _chart_bytes(
        [["甲", 100], ["乙", 40]], hashlib.sha256(supplement).hexdigest(),
    )
    markdown, references, notices = render_bound_numbers(
        "甲项目比乙项目多60.00万元。", [supplement.decode(), chart.decode()],
        key="chart-collapse", table_sources={SUPPLEMENT_RID: supplement, CHART_RID: chart},
    )
    assert "60.00万元" in markdown and not notices
    assert len(references) == 1
    operands = references[0].table_derivation.operands
    assert {op.file_resource_id for op in operands} == {SUPPLEMENT_RID}
    assert resolve_table_derivation(
        references[0].token, references[0].table_derivation, {SUPPLEMENT_RID: supplement},
    ) is not None


def test_unverifiable_declaration_keeps_ambiguity_without_reference():
    missing = hashlib.sha256(b"absent-supplement").hexdigest()
    first = _chart_bytes([["甲", 100], ["乙", 40]], missing)
    second = _chart_bytes([["甲", 100], ["乙", 40]], missing)
    markdown, references, notices = render_bound_numbers(
        "甲项目比乙项目多60.00万元。", [first.decode(), second.decode()],
        key="chart-unverified", table_sources={CHART_RID: first, OTHER_RID: second},
    )
    assert markdown == "甲项目比乙项目多60.00万元。"
    assert not references and not notices


def test_projection_only_collapses_when_declared_original_is_a_candidate():
    unrelated = table_bytes([["丙", 1], ["丁", 2]])
    supplement = table_bytes([["甲", 100], ["乙", 40]])
    chart = _chart_bytes(
        [["甲", 100], ["乙", 40]], hashlib.sha256(unrelated).hexdigest(),
    )
    markdown, references, notices = render_bound_numbers(
        "甲项目比乙项目多60.00万元。",
        [unrelated.decode(), supplement.decode(), chart.decode()],
        key="chart-noncandidate", table_sources={
            OTHER_RID: unrelated, SUPPLEMENT_RID: supplement, CHART_RID: chart,
        },
    )
    assert markdown == "甲项目比乙项目多60.00万元。"
    assert not references and not notices


def test_decline_worded_difference_still_anchors():
    raw = table_bytes([["甲", 100], ["乙", 40]])
    markdown, references, notices = issue("乙项目比甲项目减少60.00万元。", raw)
    assert "60.00万元" in markdown and not notices
    assert len(references) == 1
    assert resolve_table_derivation(
        references[0].token, references[0].table_derivation, {RID: raw},
    ) is not None


def test_unique_but_display_inexact_candidate_keeps_number_without_anchor():
    """折叠到全精度补证值时不得签锚；已注册数值更不能被降级为待核实。"""

    full_precision = table_bytes(
        [["甲", "29.663578969945096"], ["乙", "45.321578969945096"],
         ["丙", "14.013521030054904"]],
        columns=["项目", "占比"], metadata={"占比": {"unit": "%", "isPercent": True}},
    )
    rounded = _chart_bytes(
        [["甲", "29.66"], ["乙", "45.32"], ["丙", "14.02"]],
        hashlib.sha256(full_precision).hexdigest(),
        columns=["项目", "占比"], metadata={"占比": {"unit": "%", "isPercent": True}},
    )
    markdown, references, notices = render_bound_numbers(
        "甲、乙、丙三类合计约占89.0%，是主要构成。",
        [full_precision.decode(), rounded.decode()],
        key="display-inexact", table_sources={
            SUPPLEMENT_RID: full_precision, CHART_RID: rounded,
        },
    )
    assert "89.0%" in markdown
    assert "待核实" not in markdown
    assert not references
    assert notices == ()
