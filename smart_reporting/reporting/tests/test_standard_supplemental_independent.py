"""七类标准补证的独立复算与反例；不使用生产计算辅助函数产生预期值。

运行版本、输入哈希与已证实失败见同日期 standard-supplemental-depth 报告。
已知缺陷保留普通失败断言，不使用 skip/xfail 将审查结果伪装为通过。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smart_reporting.reporting.workflow.runtime import standard_supplemental as standard

HEADER = "period,department,amount\n"
MONTHS = ("2025-01", "2025-02")
AUDIT_SETTINGS = settings(max_examples=30, derandomize=True, database=None, deadline=None)


def _run(body, operation="group_summary", *, total=100, periods=("2025-01",), **options):
    """仅组装实际执行请求；不从生产输出推导任何预期。"""
    content = body.encode() if isinstance(body, str) else body
    fields = tuple(next(csv.reader(io.StringIO(content.decode()))))
    request = standard.StandardSupplementalRequest.model_validate({
        "operation": operation, "datasetId": "current", "outputName": "audit",
        "measureField": "amount", "measureUnit": "元", "dimensionField": "department",
        "periodField": "period", "periodGranularity": "month",
        "currentPeriods": periods, "parentTotal": total, **options,
    })
    payload = standard.run_standard_supplemental(
        analysis_id="audit", dataset_ids=("current", "prior"), authorized_fields=fields,
        csv_content=content, request=request,
    )
    return request, payload


def _table(payload):
    finding, = payload["findings"]
    return [dict(zip(finding["columns"], row, strict=True)) for row in finding["rows"]]


def _decimal_groups(content, periods, *, field="amount", dimensions=("department",)):
    """只用于规范日期、小额有限数样本；原生 csv + Decimal 独立聚合。"""
    result = defaultdict(Decimal)
    for row in csv.DictReader(io.StringIO(content.decode())):
        if row["period"] in periods:
            result[tuple(row[name] for name in dimensions)] += Decimal(row[field])
    return dict(result)


def _proof(content, request, payload, *, parent_updates=None):
    """构造可读身份的冻结父事实；总额和期间由手写请求给定。"""
    values = request.parent_period_totals or (request.parent_total,)
    period_values = (parent_updates or {}).get("period_values")
    if period_values is None:
        period_values = [SimpleNamespace(period=p, value=v)
                         for p, v in zip(request.current_periods, values, strict=True)]
    parent = SimpleNamespace(
        fact_id="fact-" + "a" * 16, dataset_id="current",
        dataset_sha256=hashlib.sha256(content).hexdigest(), field="amount",
        period_field="period", aggregation="sum", period_aggregation="sum",
        cumulative_policy=None, scope={}, unit="元", period_granularity="month",
        period_values=period_values,
    )
    for name, value in (parent_updates or {}).items():
        setattr(parent, name, value)
    return standard.build_standard_population_proof(
        csv_content=content, dataset_sha256=hashlib.sha256(content).hexdigest(),
        request=request, parent_fact=parent, finding=payload["findings"][0],
    )


@pytest.mark.parametrize("operation,body,options,expected", [
    ("group_summary", HEADER + "2025-01,A,60\n2025-01,B,40\n", {},
     [["A", 60, 1, .6], ["B", 40, 2, .4]]),
    ("group_period_series", HEADER + "2025-01,A,60\n2025-01,B,40\n", {"parentPeriodTotals": [100]},
     [["2025-01", "A", 60, 1, .6], ["2025-01", "B", 40, 2, .4]]),
    ("cross_group_summary", "period,department,site,amount\n2025-01,A,X,60\n2025-01,A,Y,40\n",
     {"secondaryDimensionField": "site", "includeMarginalShares": True},
     [["A", "X", 60, 1, .6, 100, .6, 60, 1], ["A", "Y", 40, 2, .4, 100, .4, 40, 1]]),
    ("period_comparison", HEADER + "2025-01,A,60\n2025-01,B,40\n2024-01,A,40\n2024-01,B,40\n",
     {"baselinePeriods": ["2024-01"], "baselineParentTotal": 80},
     [["A", 60, 40, 20, .5, 1, 1], ["B", 40, 40, 0, 0, 0, 2]]),
    ("group_ratio", "period,department,amount,budget\n2025-01,A,60,30\n2025-01,B,40,20\n",
     {"denominatorField": "budget", "denominatorParentTotal": 50,
      "denominatorScale": 1, "ratioFactId": "fact-ratio"},
     [["A", 60, 30, 30, 2], ["B", 40, 20, 20, 2]]),
    ("group_period_comparison", HEADER + "2025-01,A,60\n2025-01,B,40\n2024-12,A,40\n2024-12,B,40\n",
     {"baselinePeriods": ["2024-12"], "baselineMethod": "previous_period",
      "parentPeriodTotals": [100], "baselinePeriodTotals": [80]},
     [["2025-01", "A", 60, 40, 20, .5, 1, 1, 80, 20],
      ["2025-01", "B", 40, 40, 0, 0, 0, 2, 80, 20]]),
    ("group_concentration", HEADER + "2025-01,A,60\n2025-01,B,40\n", {},
     [["2025-01", 1, .52, 100, 100, 2, 0]]),
])
def test_seven_operations_match_hand_calculated_tables(operation, body, options, expected):
    _, payload = _run(body, operation, **options)
    actual = payload["findings"][0]["rows"]
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert len(got) == len(want)
        for actual_value, expected_value in zip(got, want, strict=True):
            if isinstance(expected_value, (int, float)):
                assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)
            else:
                assert actual_value == expected_value
    assert all(check["passed"] for check in payload["reconciliations"])
    assert payload["warnings"] == []
    json.dumps(payload, allow_nan=False)


def test_summary_cancellation_is_not_proof_of_business_row_uniqueness():
    # 两条 A=60 加 B=-20 与 A=60/B=40 总额相同；缺少业务行键不能识别替换。
    original = (HEADER + "2025-01,A,60\n2025-01,B,40\n").encode()
    changed = (HEADER + "2025-01,A,60\n2025-01,A,60\n2025-01,B,-20\n").encode()
    _, before = _run(original)
    _, after = _run(changed)
    assert _table(before)[0]["value"] == 60
    assert _table(after)[0]["value"] == 120
    assert all(check["passed"] for check in after["reconciliations"])
    assert _decimal_groups(changed, ("2025-01",)) == {("A",): Decimal(120), ("B",): Decimal(-20)}
    assert hashlib.sha256(original).digest() != hashlib.sha256(changed).digest()


def test_series_preserves_missing_period_and_true_zero_as_distinct():
    _, payload = _run(HEADER + "2025-01,A,0\n", "group_period_series",
                      total=0, periods=MONTHS, parentPeriodTotals=[0, 0])
    assert payload["findings"][0]["rows"] == [["2025-01", "A", 0, 1, None]]
    assert payload["warnings"]
    assert all(check["passed"] for check in payload["reconciliations"])


def test_cross_cells_add_before_marginal_shares_and_do_not_invent_missing_cells():
    content = (b"period,department,site,amount\n2025-01,A,X,10\n2025-01,A,X,20\n"
               b"2025-01,A,Y,30\n2025-01,B,X,40\n")
    _, payload = _run(content, "cross_group_summary", secondaryDimensionField="site", includeMarginalShares=True)
    expected = _decimal_groups(content, ("2025-01",), dimensions=("department", "site"))
    rows = _table(payload)
    assert {(r["department"], r["site"]): r["value"] for r in rows} == {k: float(v) for k, v in expected.items()}
    ax = next(r for r in rows if (r["department"], r["site"]) == ("A", "X"))
    assert (ax["value"], ax["primaryTotal"], ax["secondaryTotal"]) == (30, 60, 70)
    assert ax["primaryShare"] == .5
    assert ax["secondaryShare"] == pytest.approx(3 / 7)
    assert ("B", "Y") not in expected


@pytest.mark.parametrize("mode,expected", [("signed", -.5), ("absolute", .5)])
def test_comparison_negative_baseline_keeps_explicit_denominator(mode, expected):
    _, payload = _run(HEADER + "2025-01,A,-10\n2024-01,A,-20\n", "period_comparison", total=-10,
                      baselinePeriods=["2024-01"], baselineParentTotal=-20, changeRateDenominator=mode)
    row, = _table(payload)
    assert row["change"] == 10
    assert row["changeRate"] == expected
    assert row["contribution"] == 1


def test_comparison_missing_member_cannot_become_zero():
    _, payload = _run(HEADER + "2025-01,A,100\n2024-01,B,100\n", "period_comparison",
                      baselinePeriods=["2024-01"], baselineParentTotal=100)
    assert all(row["change"] is None and row["contribution"] is None for row in _table(payload))
    assert payload["warnings"]
    assert all(check["passed"] for check in payload["reconciliations"])


def test_comparison_zero_window_change_has_no_contribution_denominator():
    _, payload = _run(HEADER + "2025-01,A,60\n2025-01,B,40\n2024-01,A,40\n2024-01,B,60\n",
                      "period_comparison", baselinePeriods=["2024-01"], baselineParentTotal=100)
    assert [r["change"] for r in _table(payload)] == [20, -20]
    assert all(r["contribution"] is None for r in _table(payload))


def test_ratio_aggregates_operands_instead_of_averaging_row_ratios():
    content = b"period,department,amount,budget\n2025-01,A,1,1\n2025-01,A,9,99\n"
    _, payload = _run(content, "group_ratio", total=10, denominatorField="budget",
                      denominatorParentTotal=100, denominatorScale=1, ratioFactId="fact-ratio")
    numerator = _decimal_groups(content, ("2025-01",))[("A",)]
    denominator = _decimal_groups(content, ("2025-01",), field="budget")[("A",)]
    row, = _table(payload)
    assert numerator / denominator == Decimal("0.1")
    assert row["ratio"] == .1
    assert row["ratio"] != float((Decimal(1) + Decimal(9) / 99) / 2)
    assert row["difference"] == -90


def test_ratio_zero_denominator_retains_operands_and_warning():
    _, payload = _run("period,department,amount,budget\n2025-01,A,100,0\n", "group_ratio",
                      denominatorField="budget", denominatorParentTotal=0, denominatorScale=1, ratioFactId="fact-ratio")
    row, = _table(payload)
    assert (row["numerator"], row["denominator"], row["difference"], row["ratio"]) == (100, 0, 100, None)
    assert payload["warnings"]
    assert all(c["passed"] for c in payload["reconciliations"])


def test_ratio_disjoint_invalid_operands_warn_even_if_both_totals_close():
    _, payload = _run("period,department,amount,budget\n2025-01,A,100,invalid\n2025-01,A,invalid,50\n",
                      "group_ratio", denominatorField="budget", denominatorParentTotal=50,
                      denominatorScale=1, ratioFactId="fact-ratio")
    row, = _table(payload)
    assert (row["numerator"], row["denominator"]) == (100, 50)
    assert payload["warnings"]
    assert all(c["passed"] for c in payload["reconciliations"])
    # 当前比率2仅说明各自有效操作数的比值，不能证明同行总体完整。
    assert row["ratio"] == 2


@pytest.mark.parametrize("method,baseline,baseline_total,total_change,changes", [
    ("mean", 100 / 3, 200 / 3, 100 / 3, [50 - 100 / 3, 50 - 100 / 3]),
    ("median", 0, 100, 0, [50, 50]),
    ("previous_period", None, None, None, [None, None]),
])
def test_baseline_statistic_preserves_nonadditive_median(method, baseline, baseline_total, total_change, changes):
    body = HEADER + ("2025-04,A,50\n2025-04,B,50\n2025-01,A,0\n2025-01,B,0\n"
                     "2025-02,A,0\n2025-02,B,100\n2025-03,A,100\n2025-03,B,0\n")
    # previous_period 另选不连续窗口；不可借用最近存在的1月当3月。
    selected = ["2025-01"] if method == "previous_period" else ["2025-01", "2025-02", "2025-03"]
    totals = [0] if method == "previous_period" else [0, 100, 100]
    _, payload = _run(body, "group_period_comparison", periods=("2025-04",),
                      parentPeriodTotals=[100], baselinePeriods=selected, baselinePeriodTotals=totals,
                      baselineMethod=method)
    rows = _table(payload)
    for row, change in zip(rows, changes, strict=True):
        for field, value in (("baseline", baseline), ("baselineTotal", baseline_total),
                             ("totalChange", total_change), ("change", change)):
            assert row[field] is None if value is None else row[field] == pytest.approx(value)
    if method == "median":
        assert sum(r["baseline"] for r in rows) == 0
        assert rows[0]["baselineTotal"] == 100
        assert all(r["contribution"] is None for r in rows)
        assert any(not c["passed"] for c in payload["reconciliations"])
        assert payload["warnings"]
    elif method == "previous_period":
        assert payload["warnings"]
    else:
        assert all(c["passed"] for c in payload["reconciliations"])


def test_concentration_reaggregates_months_and_retains_complete_tail():
    body = HEADER + "".join(f"2025-01,{name},10\n2025-02,{name},10\n" for name in "ABCDEF")
    _, payload = _run(body, "group_concentration", total=120, periods=MONTHS)
    row, = _table(payload)
    assert row["group_count"] == 6
    assert row["cr5"] == pytest.approx(5 / 6)
    assert row["hhi"] == pytest.approx(1 / 6)
    assert row["top5_amount"] == 100
    assert payload["findings"][0]["top5Units"] == list("ABCDE")


@pytest.mark.parametrize("body,total,periods", [
    ("2025-01,A,0\n", 0, ("2025-01",)),
    ("2025-01,A,100\n", 100, MONTHS),
    ("2025-01,A,60\n2025-01,   ,40\n", 100, ("2025-01",)),
])
def test_concentration_declines_undefined_or_incomplete_population(body, total, periods):
    _, payload = _run(HEADER + body, "group_concentration", total=total, periods=periods)
    row, = _table(payload)
    assert row["cr5"] is None and row["hhi"] is None
    assert payload["warnings"]


def test_concentration_negative_net_group_declines_classical_hhi():
    _, payload = _run(HEADER + "2025-01,A,110\n2025-01,B,-10\n", "group_concentration")
    row, = _table(payload)
    assert row["hhi"] is None
    assert row["cr5"] == 1
    assert payload["warnings"]


@pytest.mark.parametrize("fault", ["members", "period", "scope", "identity"])
def test_population_proof_rejects_tampering_even_when_total_closes(fault):
    content = (HEADER + "2025-01,A,60\n2025-01,B,40\n").encode()
    request, payload = _run(content)
    assert _proof(content, request, payload)["completePopulation"] is True
    modified = deepcopy(payload)
    updates = {}
    if fault == "members":
        modified["findings"][0]["rows"][0][0] = "foreign"
    elif fault == "period":
        modified["findings"][0]["periods"] = ["2025-02"]
    elif fault == "scope":
        modified["findings"][0]["scope"] = {"company": "foreign"}
    else:
        updates["dataset_sha256"] = "b" * 64
    assert sum(row[1] for row in modified["findings"][0]["rows"]) == 100
    assert _proof(content, request, modified, parent_updates=updates) is None


def test_population_proof_must_not_certify_whitespace_only_member():
    content = (HEADER + "2025-01,A,60\n2025-01,   ,40\n").encode()
    request, payload = _run(content)
    # 分组空白意味着未知归属，与集中度及总体证明已有的完整性要求一致。
    assert _proof(content, request, payload) is None


@AUDIT_SETTINGS
@given(st.lists(st.tuples(st.sampled_from(["A", "B", "C"]), st.integers(-1000, 1000)), min_size=1, max_size=15))
def test_summary_row_order_and_exact_partition_additivity(rows):
    content = (HEADER + "".join(f"2025-01,{group},{value}\n" for group, value in rows)).encode()
    expected = _decimal_groups(content, ("2025-01",))
    total = int(sum(expected.values()))
    _, forward = _run(content, total=total)
    reverse = (HEADER + "".join(f"2025-01,{group},{value}\n" for group, value in reversed(rows))).encode()
    _, backward = _run(reverse, total=total)
    assert forward == backward
    assert {(r["department"],): r["value"] for r in _table(forward)} == {k: float(v) for k, v in expected.items()}
    # 用标准库独立按任意行分区复算；只对可加金额使用该性质。
    midpoint = len(rows) // 2
    left = sum(Decimal(v) for _, v in rows[:midpoint])
    right = sum(Decimal(v) for _, v in rows[midpoint:])
    assert sum(r["value"] for r in _table(forward)) == float(left + right)
    parts = defaultdict(float)
    for partition in (rows[:midpoint], rows[midpoint:]):
        body = HEADER + "".join(f"2025-01,{group},{value}\n" for group, value in partition)
        _, partial = _run(body, total=sum(value for _, value in partition))
        for row in _table(partial):
            parts[row["department"]] += row["value"]
    assert dict(parts) == {key[0]: float(value) for key, value in expected.items()}


@AUDIT_SETTINGS
@given(numerator=st.integers(0, 10000), denominator=st.integers(1, 10000), scale=st.sampled_from([1, 10, 10000]))
def test_ratio_unit_conversion_preserves_dimensionless_result(numerator, denominator, scale):
    raw = Decimal(denominator) / Decimal(scale)
    content = f"period,department,amount,budget\n2025-01,A,{numerator},{raw}\n"
    _, payload = _run(content, "group_ratio", total=numerator, denominatorField="budget",
                      denominatorParentTotal=float(raw), denominatorScale=scale, ratioFactId="fact-ratio")
    row, = _table(payload)
    expected = Decimal(numerator) / Decimal(denominator)
    assert row["ratio"] == pytest.approx(float(expected), rel=1e-12, abs=1e-12)
    assert row["denominator"] == pytest.approx(denominator, rel=1e-12)
    assert all(c["passed"] for c in payload["reconciliations"])


def test_population_proof_must_not_infer_missing_month_from_zero_parent():
    content = (HEADER + "2025-01,A,100\n").encode()
    request, payload = _run(content, periods=MONTHS)
    # 父事实给零不能证明二月确实观测到零；本例刻意保持期间和总额一致。
    proof = _proof(content, request, payload, parent_updates={"period_values": [
        SimpleNamespace(period="2025-01", value=100),
        SimpleNamespace(period="2025-02", value=0),
    ]})
    assert proof is None


def test_comparison_external_baseline_uses_separate_authorized_bytes():
    current = b"period,department,amount\n2025-01,A,100\n2024-01,A,999\n"
    prior = b"period,department,amount\n2024-01,A,50\n2025-01,A,999\n"
    request = standard.StandardSupplementalRequest(
        operation="period_comparison", datasetId="current", baselineDatasetId="prior",
        outputName="audit", measureField="amount", measureUnit="元", dimensionField="department",
        periodField="period", periodGranularity="month", currentPeriods=["2025-01"],
        baselinePeriods=["2024-01"], parentTotal=100, baselineParentTotal=50,
    )
    payload = standard.run_standard_supplemental(
        analysis_id="audit", dataset_ids=("current", "prior"),
        authorized_fields=("period", "department", "amount"), csv_content=current, request=request,
        baseline_csv_content=prior, baseline_authorized_fields=("period", "department", "amount"),
    )
    assert payload["findings"][0]["rows"] == [["A", 100, 50, 50, 1, 1, 1]]
    assert _decimal_groups(current, ("2025-01",)) == {("A",): Decimal(100)}
    assert _decimal_groups(prior, ("2024-01",)) == {("A",): Decimal(50)}


def test_monthly_comparison_pairs_calendar_and_uses_window_contribution():
    body = HEADER + ("2025-01,A,100\n2025-02,A,30\n"
                     "2024-01,A,50\n2024-02,A,60\n")
    _, payload = _run(body, "period_comparison", total=130, periods=("2025-02", "2025-01"),
                      baselinePeriods=["2024-01", "2024-02"], baselineParentTotal=110,
                      groupByPeriod=True, parentPeriodTotals=[30, 100], baselinePeriodTotals=[50, 60])
    rows = {row["period"]: row for row in _table(payload)}
    assert (rows["2025-01"]["baseline"], rows["2025-02"]["baseline"]) == (50, 60)
    assert rows["2025-01"]["contribution"] == 2.5
    assert rows["2025-02"]["contribution"] == -1.5
    assert rows["2025-01"]["rank"] == 1
    assert rows["2025-02"]["rank"] == 2
    assert all(check["passed"] for check in payload["reconciliations"])


def test_population_proof_cannot_detect_common_aggregation_fault(monkeypatch):
    content = (HEADER + "2025-01,A,60\n2025-01,B,40\n").encode()
    original = standard.additive_group_totals

    def wrong_members(frame, field, group_field):
        grouped, total = original(frame, field, group_field)
        # 注入保持总额和成员不变的错分组金额，独立基准仍能分辨。
        return {key: total - value for key, value in grouped.items()}, total

    monkeypatch.setattr(standard, "additive_group_totals", wrong_members)
    request, payload = _run(content)
    actual = {row["department"]: row["value"] for row in _table(payload)}
    expected = {key[0]: float(value) for key, value in _decimal_groups(content, ("2025-01",)).items()}
    assert actual != expected
    assert all(check["passed"] for check in payload["reconciliations"])
    assert _proof(content, request, payload)["completePopulation"] is True
