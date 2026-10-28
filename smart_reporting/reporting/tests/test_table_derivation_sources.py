"""Focused tests for verified table derivation tokens and semantics."""

import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.trace.contracts_v1 import TableDerivationV1, TableOperandV1
from smart_reporting.reporting.trace.table_sources import (
    resolve_table_derivation,
    table_derivation_token,
    table_semantics,
)

RID = "trf-0123456789abcdefabcd"


def source(columns, rows, **table_meta):
    document = {
        "schema": "chart-input/v1",
        "title": "2025年1-3月收入类型结构分布",
        "periodRoles": ["current"],
        "scope": {"department": "全院"},
        "findings": [{"columns": columns, "rows": rows, **table_meta}],
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()


def derivation(operands, unit="元", pointer="/findings/0"):
    return TableDerivationV1(
        operands=[
            TableOperandV1(
                fileResourceId=RID,
                tablePointer=pointer,
                rowIndex=row,
                columnIndex=column,
                coefficient=coefficient,
            )
            for row, column, coefficient in operands
        ],
        unit=unit,
    )


def test_token_binds_derivation_and_exact_source_bytes():
    raw = source(["项目", "收入（元）"], [["甲", 12], ["乙", 5]])
    operands = derivation([(0, 1, "1"), (1, 1, "-1")])
    token = table_derivation_token(operands, {RID: raw})
    assert token and token.startswith("{{tableDerived:") and token.endswith("}}")
    assert table_derivation_token(operands, {RID: raw + b" "}) != token
    assert resolve_table_derivation(token, operands, {RID: raw})["value"] == 7
    assert resolve_table_derivation(token, operands, {RID: raw + b" "}) is None


def test_derived_selected_view_uses_verified_table_semantics():
    raw = source(["项目", "收入（元）"], [["甲", 12], ["乙", 5]])
    operands = derivation([(0, 1, "1"), (1, 1, "-1")])
    selected = resolve_table_derivation(
        table_derivation_token(operands, {RID: raw}), operands, {RID: raw}
    )
    assert selected["unit"] == "元"
    assert selected["periods"] == ("2025-01", "2025-02", "2025-03")
    assert selected["period_roles"] == {"current": selected["periods"]}
    assert selected["scope"] == {"department": "全院"}
    assert selected["entry"]["scope"] == selected["scope"]
    assert selected["selector"] == "tableDerived"


def test_structured_semantics_override_title_and_table_takes_precedence():
    document = {"periodStart": "2024-01", "periodEnd": "2024-02",
                "periodGranularity": "month", "scope": {"site": "北院"}}
    assert table_semantics(document, {"title": "2025年1-3月"}) == {
        "periods": ("2024-01", "2024-02"), "period_roles": {}, "scope": {"site": "北院"}
    }
    assert table_semantics(document, {"periods": ["2023-12"]})["periods"] == ("2023-12",)


def test_rfc6901_pointer_handles_escaped_keys_and_rejects_invalid_pointer():
    raw = json.dumps({"a/b": {"~item": {"columns": ["名称", "金额（元）"],
                                      "rows": [["甲", 9], ["乙", 4]]}}}).encode()
    good = derivation([(0, 1, "1"), (1, 1, "-1")], pointer="/a~1b/~0item")
    assert table_derivation_token(good, {RID: raw})
    with pytest.raises(ValidationError):
        derivation([(0, 1, "1"), (1, 1, "-1")], pointer="/a~2b")


def test_rejects_malformed_json_and_duplicate_object_members():
    operands = derivation([(0, 1, "1"), (1, 1, "-1")])
    for raw in (b"{", b'{"findings":[],"findings":[]}'):
        assert table_derivation_token(operands, {RID: raw}) is None


def test_rejects_changed_shape_duplicate_cells_and_cross_file_operands():
    raw = source(["项目", "金额（元）"], [["甲", 9], ["乙", 4]])
    assert table_derivation_token(derivation([(0, 1, "1"), (0, 1, "-1")]), {RID: raw}) is None
    assert table_derivation_token(derivation([(0, 1, "1"), (1, 1, "-1")]), {RID: raw})
    invalid = TableDerivationV1(operands=[
        TableOperandV1(fileResourceId=RID, tablePointer="/findings/0", rowIndex=0,
                       columnIndex=1, coefficient="1"),
        TableOperandV1(fileResourceId="trf-aaaaaaaaaaaaaaaaaaaa", tablePointer="/findings/0",
                       rowIndex=1, columnIndex=1, coefficient="-1"),
    ], unit="元")
    assert table_derivation_token(invalid, {RID: raw}) is None


def test_top_n_sum_and_two_column_total_difference_are_supported():
    raw = source(["项目", "收入（元）", "支出（元）"],
                 [["甲", 10, 2], ["乙", 8, 3], ["丙", 1, 4]])
    top_two = derivation([(0, 1, "1"), (1, 1, "1")])
    token = table_derivation_token(top_two, {RID: raw})
    assert resolve_table_derivation(token, top_two, {RID: raw})["value"] == 18
    total_gap = derivation([(0, 1, "1"), (1, 1, "1"), (2, 1, "1"),
                            (0, 2, "-1"), (1, 2, "-1"), (2, 2, "-1")])
    token = table_derivation_token(total_gap, {RID: raw})
    assert resolve_table_derivation(token, total_gap, {RID: raw})["value"] == 10
    partial_gap = derivation([(0, 1, "1"), (1, 1, "1"),
                              (0, 2, "-1"), (1, 2, "-1")])
    assert table_derivation_token(partial_gap, {RID: raw}) is None


@pytest.mark.parametrize("unit", ["%", "‰"])
def test_top_n_percent_sum_excludes_total_row_and_keeps_raw_row_indices(unit):
    raw = source(["项目", f"占比（{unit}）"],
                 [["合计", 100], ["甲", 55], ["乙", 35], ["丙", 10]])
    top_two = derivation([(1, 1, "1"), (2, 1, "1")], unit=unit)
    token = table_derivation_token(top_two, {RID: raw})
    assert token
    assert resolve_table_derivation(token, top_two, {RID: raw})["value"] == 90
    # Selecting the total row instead of the raw-index TopN rows is not accepted.
    wrong_rows = derivation([(0, 1, "1"), (1, 1, "1")], unit=unit)
    assert table_derivation_token(wrong_rows, {RID: raw}) is None


def test_top_n_rejects_malformed_unselected_raw_row():
    raw = source(["项目", "金额（元）"],
                 [["甲", 55], ["坏行", 100, "extra"], ["乙", 35], ["丙", 10]])
    top_two = derivation([(0, 1, "1"), (2, 1, "1")])
    # Filtering the malformed row would change the ranked population.
    assert table_derivation_token(top_two, {RID: raw}) is None


def test_mixed_source_units_are_rejected():
    raw = source(["项目", "收入（元）", "支出（万元）"], [["甲", 20_000, 1]])
    # Even mathematically matching per-cell scales cannot authorize mixed units.
    mixed = derivation([(0, 1, "0.0001"), (0, 2, "-1")], unit="万元")
    assert table_derivation_token(mixed, {RID: raw}) is None
    same_coefficient = derivation([(0, 1, "1"), (0, 2, "-1")])
    assert table_derivation_token(same_coefficient, {RID: raw}) is None


@pytest.mark.parametrize(
    "row,column",
    [(-1, 1), (0, -1), (True, 1), (0, True), (10, 1), (0, 10)],
)
def test_model_construct_coordinates_are_revalidated(row, column):
    raw = source(["项目", "收入（元）"], [["甲", 12], ["乙", 5]])
    first = TableOperandV1.model_construct(
        file_resource_id=RID, table_pointer="/findings/0", row_index=row,
        column_index=column, coefficient="1",
    )
    second = TableOperandV1.model_construct(
        file_resource_id=RID, table_pointer="/findings/0", row_index=1,
        column_index=1, coefficient="-1",
    )
    operands = TableDerivationV1.model_construct(operands=(first, second), unit="元")
    assert table_derivation_token(operands, {RID: raw}) is None


@pytest.mark.parametrize("coefficient", ["NaN", "Infinity", "1e3", "1e-1001", "0", "1" * 33])
def test_coefficient_must_be_bounded_plain_decimal(coefficient):
    raw = source(["项目", "金额（元）"], [["甲", 9], ["乙", 4]])
    # Construct directly because the public schema rejects several malformed values first.
    try:
        operands = derivation([(0, 1, coefficient), (1, 1, "-1")])
    except ValueError:
        return
    assert table_derivation_token(operands, {RID: raw}) is None


def test_rejects_boolean_nonfinite_values_and_unsupported_table_shapes():
    malformed = source(["项目", "金额（元）"], [["甲", True], ["乙", 4]])
    operands = derivation([(0, 1, "1"), (1, 1, "-1")])
    assert table_derivation_token(operands, {RID: malformed}) is None
    malformed_rows = source(["项目", "金额（元）"], [["甲", 4], ["乙", 2, "extra"]])
    assert table_derivation_token(operands, {RID: malformed_rows}) is None


def test_percent_difference_requires_percentage_point_output():
    raw = source(["项目", "占比（%）"], [["甲", 12.5], ["乙", 8.5]])
    points = derivation([(0, 1, "1"), (1, 1, "-1")], unit="个百分点")
    token = table_derivation_token(points, {RID: raw})
    assert resolve_table_derivation(token, points, {RID: raw})["value"] == 4
    percent = derivation([(0, 1, "1"), (1, 1, "-1")], unit="%")
    assert table_derivation_token(percent, {RID: raw}) is None


def test_unit_conversion_requires_matching_coefficient_and_same_unit_family():
    raw = source(["项目", "收入（元）"], [["甲", 20_000], ["乙", 10_000]])
    correct = derivation([(0, 1, "0.0001"), (1, 1, "-0.0001")], unit="万元")
    assert resolve_table_derivation(
        table_derivation_token(correct, {RID: raw}), correct, {RID: raw}
    )["value"] == 1
    wrong = derivation([(0, 1, "1"), (1, 1, "-1")], unit="万元")
    assert table_derivation_token(wrong, {RID: raw}) is None


def mixed_sources(*, scope=None, period='2025-01', total=200, fact_key='fact-aaaaaaaaaaaaaaaa'):
    raw = json.dumps({'periods': [period], 'scope': scope or {'company': '甲院'},
        'findings': [{'columns': ['科室', '金额'], 'columnMeta': {'金额': {'unit': '元'}},
                      'rows': [['甲科', 60], ['乙科', 40]]}]}).encode()
    fact = json.dumps({'analysisId': 'analysis_001', 'metrics': [{
        'factId': fact_key, 'total': total, 'unit': '元', 'scope': {'company': '甲院'},
        'aggregation': 'sum', 'periodAggregation': 'sum',
        'periodValues': [{'period': '2025-01', 'value': total}], 'periodGranularity': 'month',
        'periodStart': '2025-01', 'periodEnd': '2025-01'}]}).encode()
    return {RID: raw, 'trf-' + 'b' * 20: fact}


def mixed_derivation():
    return TableDerivationV1.model_validate({'operands': [{
        'fileResourceId': RID, 'tablePointer': '/findings/0', 'rowIndex': 0,
        'columnIndex': 1, 'coefficient': '1'}], 'unit': '%', 'denominatorFact': {
            'analysisId': 'analysis_001', 'fileResourceId': 'trf-' + 'b' * 20,
            'jsonPointer': '/metrics/0', 'factKind': 'metric', 'factKey': 'fact-aaaaaaaaaaaaaaaa'}})


def test_mixed_table_fact_share_recomputes_ratio_and_binds_denominator_bytes():
    sources = mixed_sources()
    proof = mixed_derivation()
    token = table_derivation_token(proof, sources)
    assert token is not None
    selected = resolve_table_derivation(token, proof, sources)
    assert selected['value'] == 30
    assert selected['unit'] == '%'
    assert selected['scope'] == {'company': '甲院'}
    assert resolve_table_derivation(token, proof, {**sources, 'trf-' + 'b' * 20:
        sources['trf-' + 'b' * 20] + b' '}) is None
    assert resolve_table_derivation(token, proof, {RID: sources[RID]}) is None


@pytest.mark.parametrize('difference', ['scope', 'period', 'zero', 'identity'])
def test_mixed_share_rejects_unknown_or_conflicting_denominator_semantics(difference):
    sources = mixed_sources(**{'scope': {'company': '乙院'}} if difference == 'scope' else
        {'period': '2025-02'} if difference == 'period' else
        {'total': 0} if difference == 'zero' else {'fact_key': 'fact-bbbbbbbbbbbbbbbb'})
    assert table_derivation_token(mixed_derivation(), sources) is None
