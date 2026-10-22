from __future__ import annotations

import pytest

from smart_reporting.reporting.contract import MeasureSemantic
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    AnalysisFileIdentity,
    DatasetAnalysisContext,
    DetailedAnalysisItem,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
    validate_metric_code_bindings,
)


def semantic(
    field: str,
    aggregation: str = "sum",
    *,
    scope: dict[str, str] | None = None,
    unit: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "fieldRef": f"dynamic_source.dynamic_db.dynamic_table.{field}",
        "aggregation": aggregation,
        "additiveAcross": ["month", "department"],
        "exclusiveScope": scope or {},
    }
    if unit is not None:
        value["unit"] = unit
    return value


def context(
    dataset_id: str,
    *,
    fields: tuple[str, ...] = ("month", "department", "amount"),
    semantics: tuple[dict[str, object], ...] | None = None,
    sha256: str = "b" * 64,
) -> DatasetAnalysisContext:
    return DatasetAnalysisContext(
        profileFile=AnalysisFileIdentity(
            path=f"profiles/{dataset_id}.json", size=1, sha256="a" * 64
        ),
        profileModelView={},
        profileEngineVersion="4.19.1",
        datasetId=dataset_id,
        path=f"datasets/{dataset_id}.csv",
        size=1,
        sha256=sha256,
        rowCount=3,
        columnCount=len(fields),
        fields=fields,
        organizationGrain=("department",),
        metricSemantics=semantics or (semantic("amount", unit="元"),),
        numericFields=tuple(
            field for field in fields if field not in {"month", "department", "scope_type"}
        ),
        periodValues=("2025-01", "2025-02", "2025-03"),
        timeSeriesSortField="month",
    )


def analysis(*, fields: tuple[str, ...] = ("amount",), correlation: bool = False) -> DetailedAnalysisItem:
    return DetailedAnalysisItem(
        analysisId="analysis_001",
        domain="income",
        managementQuestion="分析规模、同比、环比、趋势和异常贡献",
        primaryMetricFamily="收入",
        datasetIds=("current", "yoy", "mom"),
        fields=fields,
        metrics=("收入",),
        periods=("2025-01", "2025-02", "2025-03"),
        comparisonBasis=("yoy", "mom"),
        organizationGrain=("department",),
        actions=("汇总", "同比", "环比", "异常", *(("相关性",) if correlation else ())),
        evidenceSummary="服务端复算",
        suggestedSection="收入分析",
        completionConditions=("固定指标可复算",),
    )


def test_measure_semantic_accepts_confirmed_unit() -> None:
    value = MeasureSemantic.model_validate(semantic("dynamic_value", unit="元"))

    assert value.unit == "元"


@pytest.mark.parametrize("aggregation,expected", [
    ("sum", 100), ("count", 1), ("min", 100), ("max", 100),
    ("average", None), ("count_distinct", None),
])
def test_comparison_excludes_rows_without_period(aggregation, expected):
    def scoped(dataset_id):
        return context(dataset_id, semantics=(semantic("amount", aggregation),))

    bundle = build_deterministic_analysis_bundle(analysis(), (
        ("current", b"month,department,amount\n2025-01,A,100\n,A,900\n", scoped("current"), ("current",)),
        ("baseline", b"month,department,amount\n2024-01,A,50\n", scoped("baseline"), ("yoy",)),
    ))
    assert bundle.metrics[0].period_missing_count == 1
    if expected is None:
        assert bundle.comparisons == ()
        assert any("无法形成" in warning for warning in bundle.warnings)
    else:
        assert bundle.comparisons[0].current_total == expected
        if aggregation == "sum":
            assert bundle.comparisons[0].change_rate == 100
    assert any("期间" in warning and "缺失" in warning for warning in bundle.metrics[0].warnings)


@pytest.mark.parametrize("aggregation,current_rows,baseline_rows,total", [
    ("average", "2025-01,A,10\n2025-01,A,20\n2025-02,A,90\n",
     "2024-01,A,5\n2024-01,A,10\n2024-02,A,45\n", 40),
    ("count_distinct", "2025-01,A,1\n2025-02,A,1\n",
     "2024-01,A,2\n2024-02,A,2\n", 1),
])
def test_complete_periods_preserve_weighted_average_and_cross_period_distinct(
    aggregation, current_rows, baseline_rows, total
):
    bundle = build_deterministic_analysis_bundle(analysis(), tuple(
        (name, ("month,department,amount\n" + rows).encode(),
         context(name, semantics=(semantic("amount", aggregation),)), (role,))
        for name, rows, role in (("current", current_rows, "current"), ("baseline", baseline_rows, "yoy"))
    ))
    assert bundle.comparisons[0].current_total == total


@pytest.mark.parametrize("period", ["2025-01", "", "invalid-period"])
def test_derived_ratio_uses_only_rows_in_the_common_period(period):
    metrics = (
        {"code": "revenue", "aggregation": "sum", "fieldRef": semantic("amount")["fieldRef"]},
        {"code": "visits", "aggregation": "sum", "fieldRef": semantic("visits")["fieldRef"]},
        {"code": "per_visit", "aggregation": "ratio", "numeratorMetric": "revenue", "denominatorMetric": "visits"},
    )
    bundle = build_deterministic_analysis_bundle(analysis(fields=("amount", "visits")), (
        ("current", f"month,department,amount,visits\n{period},A,100,10\n,A,900,1\n".encode(),
         context("current", fields=("month", "department", "amount", "visits"),
                 semantics=(semantic("amount"), semantic("visits"))), ("current",)),
    ), profile_metrics=metrics)
    if period != "2025-01":
        assert bundle.derived_metrics == ()
        assert any("无法形成" in warning for warning in bundle.warnings)
        return
    assert bundle.derived_metrics[0].numerator == 100
    assert bundle.derived_metrics[0].denominator == 10
    assert bundle.derived_metrics[0].value == 10


def test_fact_granularity_uses_dataset_buckets_instead_of_planned_summary():
    item = analysis().model_copy(update={'series_granularity': 'year'})
    dataset = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(item, (
        ('current', b'month,department,amount\n2025-01,A,10\n2025-02,A,20\n', dataset, ('current',)),
    ), profile_hash='c' * 64)
    assert bundle.metrics[0].period_granularity == 'month'
    assert len(bundle.metrics[0].period_values) == 2


def test_untyped_income_fact_defaults_to_cny_yuan() -> None:
    dataset_context = context(
        "current",
        fields=("month", "department", "revenue_amount"),
        semantics=(semantic("revenue_amount"),),
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("revenue_amount",)),
        (("current", b"month,department,revenue_amount\n2025-01,A,100\n", dataset_context, ("current",)),),
        profile_metrics=({
            "code": "revenue_total",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue_amount",
        },),
    )

    assert bundle.metrics[0].unit == "元"
    explicit = build_deterministic_analysis_bundle(
        analysis(fields=("revenue_amount",)),
        (("current", b"month,department,revenue_amount\n2025-01,A,100\n",
          context("current", fields=("month", "department", "revenue_amount"),
                  semantics=(semantic("revenue_amount", unit="元"),)), ("current",)),),
        profile_metrics=({
            "code": "revenue_total", "kind": "amount", "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue_amount",
        },),
    )
    assert bundle.metrics[0].fact_id == explicit.metrics[0].fact_id


@pytest.mark.parametrize("kind,aggregation,unit,expected", [
    ("amount", "sum", None, "元"),
    ("currency", "average", None, "元"),
    ("amount", "sum", "CNY", "元"),
    ("amount", "sum", "万元", "万元"),
    ("amount", "sum", "USD", "USD"),
    ("amount", "count", None, None),
    ("amount", "count_distinct", None, None),
    ("count", "sum", None, None),
    ("ratio", "average", "%", "%"),
    ("count", "sum", "床日", "床日"),
    (None, "sum", None, None),
])
def test_default_cny_uses_confirmed_metric_kind(kind, aggregation, unit, expected):
    # 即使分析属于收入域、指标别名含收入字样，也不能把未确定量纲的字段当作金额。
    metric = {"code": "income_metric", "kind": kind, "aggregation": aggregation,
              "fieldRef": "dynamic_source.dynamic_db.dynamic_table.dynamic_value"}
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("dynamic_value",)),
        (("current", b"month,department,dynamic_value\n2025-01,A,123456\n",
          context("current", fields=("month", "department", "dynamic_value"),
                  semantics=(semantic("dynamic_value", aggregation, unit=unit),)), ("current",)),),
        profile_metrics=(metric,),
    )
    assert bundle.metrics[0].unit == expected
    if expected == "元":
        from smart_reporting.reporting.trace.content_review import review_content
        from smart_reporting.reporting.trace.numeric_text import (
            frozen_number_catalog,
            replace_unregistered_numbers,
        )

        contents = [bundle.model_dump_json(by_alias=True)]
        catalog = frozen_number_catalog(contents)
        fact_id = bundle.metrics[0].fact_id
        assert catalog[f"{{{{value:{fact_id}:total:元}}}}"] == "123,456元"
        assert catalog[f"{{{{value:{fact_id}:total:万元}}}}"] == "12.35万元"
        text = "收入123,456元（12.35万元）。"
        assert replace_unregistered_numbers(text, contents) == text
        assert review_content(text, contents) == []
        assert replace_unregistered_numbers("收入999,999元。", contents) == "收入待核实。"


def test_validate_metric_code_bindings_rejects_numeric_fact_without_authoritative_code() -> None:
    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            (
                "current",
                b"month,department,amount\n2025-01,A,100\n",
                context("current"),
                ("current",),
            ),
        ),
        profile_hash="c" * 64,
    )

    with pytest.raises(ValueError, match="metric code"):
        validate_metric_code_bindings(bundle)

    assert bundle.model_dump(by_alias=True)["analysisName"] == analysis().management_question


def test_validate_metric_code_bindings_accepts_profile_metric_code() -> None:
    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            (
                "current",
                b"month,department,amount\n2025-01,A,100\n",
                context("current"),
                ("current",),
            ),
        ),
        profile_metrics=(
            {
                "code": "income_total",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
            },
        ),
        profile_hash="c" * 64,
    )

    validate_metric_code_bindings(bundle)


def test_deterministic_bundle_calculates_semantic_facts_and_separate_comparisons() -> None:
    current = b"month,department,amount\n2025-01,A,100\n2025-02,B,0\n2025-03,A,-10\n"
    yoy = b"month,department,amount\n2024-01,A,80\n2024-02,B,10\n2024-03,A,0\n"
    mom = b"month,department,amount\n2025-02,A,60\n"

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            ("current", current, context("current"), ("current",)),
            ("yoy", yoy, context("yoy"), ("yoy",)),
            ("mom", mom, context("mom"), ("mom",)),
        ),
        profile_hash="c" * 64,
    )

    current_fact = next(item for item in bundle.metrics if item.dataset_id == "current")
    assert current_fact.total == 90
    assert current_fact.aggregation == "sum"
    assert current_fact.field_ref == "dynamic_source.dynamic_db.dynamic_table.amount"
    assert current_fact.dataset_sha256 == "b" * 64
    assert current_fact.profile_hash == "c" * 64
    assert current_fact.unit == "元"
    assert current_fact.scope == {}
    assert current_fact.zero_count == 1
    assert current_fact.negative_count == 1
    assert [item.period for item in current_fact.period_values] == [
        "2025-01",
        "2025-02",
        "2025-03",
    ]
    assert current_fact.top_groups[0].group == "A"
    assert {(item.comparison_type, item.baseline_dataset_id) for item in bundle.comparisons} == {
        ("yoy", "yoy"),
        ("mom", "mom"),
    }
    mom_comparison = next(item for item in bundle.comparisons if item.comparison_type == "mom")
    assert mom_comparison.current_total == -10
    assert mom_comparison.baseline_total == 60


def test_deterministic_bundle_reads_lineage_bound_dataset_alias() -> None:
    projected_semantic = semantic("amount", unit="元")
    projected_semantic["datasetField"] = "measure_val"

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("measure_val",)),
        (
            (
                "current",
                b"month,measure_val\n2025-01,100\n2025-02,50\n",
                context(
                    "current",
                    fields=("month", "measure_val"),
                    semantics=(projected_semantic,),
                ),
                ("current",),
            ),
        ),
    )

    assert bundle.metrics[0].field == "measure_val"
    assert bundle.metrics[0].field_ref == "dynamic_source.dynamic_db.dynamic_table.amount"
    assert bundle.metrics[0].total == 150


def test_deterministic_bundle_orders_equal_group_contributions_stably() -> None:
    rows = "month,department,amount\n2025-01,C,10\n2025-01,A,10\n2025-01,B,10\n"
    reversed_rows = "month,department,amount\n2025-01,B,10\n2025-01,A,10\n2025-01,C,10\n"

    first_bundle = build_deterministic_analysis_bundle(
        analysis(),
        (("current", rows.encode(), context("current"), ("current",)),),
    )
    second_bundle = build_deterministic_analysis_bundle(
        analysis(),
        (("current", reversed_rows.encode(), context("current"), ("current",)),),
    )
    first = first_bundle.metrics[0]

    assert [item.group for item in first.top_groups] == ["A", "B", "C"]
    assert [item.group for item in first.bottom_groups] == ["A", "B", "C"]
    assert first_bundle == second_bundle


def test_deterministic_bundle_aligns_yoy_to_common_months() -> None:
    current = b"month,department,amount\n2025-01,A,10\n2025-02,A,20\n"
    yoy = b"month,department,amount\n2024-01,A,5\n2024-02,A,20\n2024-03,A,100\n"

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            ("current", current, context("current"), ("current",)),
            ("yoy", yoy, context("yoy"), ("yoy",)),
        ),
    )

    comparison = bundle.comparisons[0]
    assert comparison.current_total == 30
    assert comparison.baseline_total == 25
    assert comparison.change_rate == 20
    assert comparison.period_start == "2025-01"
    assert comparison.period_end == "2025-02"
    assert any("共同连续窗口" in warning for warning in comparison.warnings)


def test_declared_monthly_dates_align_all_months_and_keep_business_name() -> None:
    current = b"month,department,amount\n2025-01-01,A,10\n2025-02-01,A,20\n"
    baseline = b"month,department,amount\n2024-01-01,A,5\n2024-02-01,A,20\n2024-03-01,A,100\n"
    item = analysis().model_copy(update={"series_granularity": "month", "analysis_name": "2025年收入同比"})
    bundle = build_deterministic_analysis_bundle(item, (
        ("current", current, context("current"), ("current",)),
        ("yoy", baseline, context("yoy"), ("yoy",)),
    ))
    assert bundle.analysis_name == "2025年收入同比"
    assert bundle.comparisons[0].current_total == 30
    assert bundle.comparisons[0].baseline_total == 25
    assert bundle.comparisons[0].change_rate == 20
    summary = build_deterministic_analysis_bundle(item, (("current", current, context("current"), ("current",)),))
    assert not summary.comparisons


def test_deterministic_bundle_keeps_zero_months_and_warns_without_changing_comparison() -> None:
    current = b"month,department,amount\n2025-01,A,10\n2025-02,A,20\n2025-03,A,0\n2025-04,A,0\n"
    yoy = b"month,department,amount\n2024-01,A,5\n2024-02,A,10\n2024-03,A,30\n2024-04,A,40\n"

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            ("current", current, context("current"), ("current",)),
            ("yoy", yoy, context("yoy"), ("yoy",)),
        ),
    )

    comparison = bundle.comparisons[0]
    assert comparison.current_total == 30
    assert comparison.baseline_total == 85
    assert comparison.change_rate == pytest.approx((30 - 85) / 85 * 100)
    assert comparison.period_end == "2025-04"
    assert [item.value for item in bundle.metrics[0].period_values] == [10, 20, 0, 0]
    assert any("保留原始零值" in warning for warning in comparison.warnings)


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    (
        ("sum", 6.0),
        ("average", 2.0),
        ("min", 1.0),
        ("max", 3.0),
        ("count", 3.0),
        ("count_distinct", 3.0),
    ),
)
def test_deterministic_bundle_executes_confirmed_aggregation(
    aggregation: str, expected: float
) -> None:
    dataset_context = context(
        "current", semantics=(semantic("dynamic_value", aggregation),), fields=("dynamic_value",)
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("dynamic_source.dynamic_db.dynamic_table.dynamic_value",)),
        (("current", b"dynamic_value\n1\n2\n3\n", dataset_context, ("current",)),),
    )

    assert bundle.metrics[0].total == expected
    assert bundle.metrics[0].aggregation == aggregation


def test_deterministic_bundle_applies_exclusive_scope_without_fixed_table_names() -> None:
    dataset_context = context(
        "current",
        fields=("month", "department", "scope_type", "dynamic_value"),
        semantics=(semantic("dynamic_value", scope={"scope_type": "approved"}),),
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("dynamic_value",)),
        (
            (
                "current",
                b"month,department,scope_type,dynamic_value\n"
                b"2025-01,A,approved,10\n"
                b"2025-01,A,rejected,90\n",
                dataset_context,
                ("current",),
            ),
        ),
    )

    fact = bundle.metrics[0]
    assert fact.total == 10
    assert fact.scope == {"scope_type": "approved"}
    assert "scope_type='approved'" in fact.formula


@pytest.mark.parametrize("unit", [None, "元"])
def test_deterministic_bundle_builds_profile_ratio_difference_and_reconciliation(unit) -> None:
    semantics = (
        semantic("actual_value", unit=unit),
        semantic("budget_value", unit=unit),
        semantic("ledger_value", unit=unit),
    )
    dataset_context = context(
        "current",
        fields=("month", "department", "actual_value", "budget_value", "ledger_value"),
        semantics=semantics,
    )
    profile_metrics = (
        {
            "code": "actual_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.actual_value",
        },
        {
            "code": "budget_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.budget_value",
        },
        {
            "code": "ledger_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.ledger_value",
        },
        {
            "code": "execution_ratio",
            "kind": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "actual_metric",
            "denominatorMetric": "budget_metric",
            "zeroDenominatorPolicy": "disclose",
        },
    )
    reconciliations = (
        {
            "code": "actual_ledger_check",
            "leftMetric": "actual_metric",
            "rightMetric": "ledger_metric",
            "grain": ["department"],
            "absoluteTolerance": 1,
            "relativeTolerance": 0.01,
        },
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("actual_value", "budget_value", "ledger_value")),
        (
            (
                "current",
                b"month,department,actual_value,budget_value,ledger_value\n"
                b"2025-01,A,80,100,80\n"
                b"2025-01,B,10,20,8\n",
                dataset_context,
                ("current",),
            ),
        ),
        profile_metrics=profile_metrics,
        profile_reconciliations=reconciliations,
        profile_dimensions=(
            {
                "code": "department",
                "kind": "organization",
                "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.department"],
            },
        ),
    )

    ratio = bundle.derived_metrics[0]
    assert ratio.code == "execution_ratio"
    assert ratio.value == 0.75
    assert ratio.percentage == 75.0
    assert ratio.difference == -30
    assert ratio.unit == "元"
    assert ratio.dataset_sha256s == ("b" * 64,)
    reconciliation = bundle.reconciliations[0]
    assert reconciliation.code == "actual_ledger_check"
    assert reconciliation.passed is False
    assert reconciliation.checked_group_count == 2
    assert reconciliation.failed_group_count == 1
    assert reconciliation.grain == ("department",)


def test_deterministic_bundle_aligns_cross_dataset_ratio_periods() -> None:
    actual_context = context(
        "actual",
        fields=("month", "actual_value"),
        semantics=(semantic("actual_value", unit="元"),),
    )
    budget_context = context(
        "budget",
        fields=("month", "budget_value"),
        semantics=(semantic("budget_value", unit="元"),),
    )
    profile_metrics = (
        {
            "code": "actual_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.actual_value",
        },
        {
            "code": "budget_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.budget_value",
        },
        {
            "code": "execution_ratio",
            "kind": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "actual_metric",
            "denominatorMetric": "budget_metric",
        },
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("actual_value", "budget_value")),
        (
            (
                "actual",
                b"month,actual_value\n2025-01,80\n2025-02,70\n",
                actual_context,
                ("current",),
            ),
            (
                "budget",
                b"month,budget_value\n2025-01,100\n2025-02,100\n2025-03,100\n",
                budget_context,
                ("current",),
            ),
        ),
        profile_metrics=profile_metrics,
    )

    ratio = bundle.derived_metrics[0]
    assert ratio.numerator == 150
    assert ratio.denominator == 200
    assert ratio.percentage == 75
    assert ratio.period_start == "2025-01"
    assert ratio.period_end == "2025-02"
    assert any("共同连续窗口" in warning for warning in ratio.warnings)


def test_deterministic_bundle_aligns_same_dataset_ratio_periods() -> None:
    dataset_context = context(
        "current",
        fields=("month", "actual_value", "budget_value"),
        semantics=(
            semantic("actual_value", unit="元"),
            semantic("budget_value", unit="元"),
        ),
    )
    profile_metrics = (
        {
            "code": "actual_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.actual_value",
        },
        {
            "code": "budget_metric",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.budget_value",
        },
        {
            "code": "execution_ratio",
            "kind": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "actual_metric",
            "denominatorMetric": "budget_metric",
        },
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("actual_value", "budget_value")),
        (
            (
                "current",
                b"month,actual_value,budget_value\n2025-01,80,100\n2025-02,70,100\n2025-03,,100\n",
                dataset_context,
                ("current",),
            ),
        ),
        profile_metrics=profile_metrics,
    )

    ratio = bundle.derived_metrics[0]
    assert ratio.numerator == 150
    assert ratio.denominator == 200
    assert ratio.percentage == 75
    assert ratio.period_start == "2025-01"
    assert ratio.period_end == "2025-02"
    assert any("共同连续窗口" in warning for warning in ratio.warnings)


def test_deterministic_bundle_warns_instead_of_guessing_unconfirmed_numeric_fields() -> None:
    dataset_context = context(
        "current",
        fields=("mystery_number",),
        semantics=(),
    ).model_copy(update={"metric_semantics": ()})

    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("mystery_number",)),
        (("current", b"mystery_number\n12\n", dataset_context, ("current",)),),
    )

    assert bundle.metrics == ()
    assert any("没有已确认指标语义" in warning for warning in bundle.warnings)


def test_deterministic_daily_yoy_spans_a_leap_day_present_on_one_side() -> None:
    current = (
        b"month,department,amount\n2024-02-27,A,1\n2024-02-28,A,1\n2024-02-29,A,1\n"
        b"2024-03-01,A,1\n2024-03-02,A,1\n"
    )
    yoy = (
        b"month,department,amount\n2023-02-27,A,1\n2023-02-28,A,1\n2023-03-01,A,1\n2023-03-02,A,1\n"
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            ("current", current, context("current"), ("current",)),
            ("yoy", yoy, context("yoy"), ("yoy",)),
        ),
    )

    comparison = bundle.comparisons[0]
    # 闰日只存在于当期一侧：窗口不应在 2 月 29 日处断开，且整期口径计入闰日。
    assert comparison.period_start == "2024-02-27"
    assert comparison.period_end == "2024-03-02"
    assert comparison.current_total == 5
    assert comparison.baseline_total == 4


def test_deterministic_daily_yoy_counts_leap_day_on_the_baseline_side() -> None:
    current = b"month,department,amount\n2025-02-27,A,1\n2025-02-28,A,1\n2025-03-01,A,1\n"
    yoy = (
        b"month,department,amount\n2024-02-27,A,1\n2024-02-28,A,1\n2024-02-29,A,1\n2024-03-01,A,1\n"
    )

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (
            ("current", current, context("current"), ("current",)),
            ("yoy", yoy, context("yoy"), ("yoy",)),
        ),
    )

    comparison = bundle.comparisons[0]
    assert comparison.period_start == "2025-02-27"
    assert comparison.period_end == "2025-03-01"
    assert comparison.current_total == 3
    assert comparison.baseline_total == 4
    assert not any("共同连续窗口" in warning for warning in comparison.warnings)


def test_deterministic_period_order_uses_calendar_order_for_unpadded_months() -> None:
    rows = "".join(f"2025-{month},A,{0 if month > 10 else 10}\n" for month in range(1, 13))
    current = ("month,department,amount\n" + rows).encode()

    bundle = build_deterministic_analysis_bundle(
        analysis(),
        (("current", current, context("current"), ("current",)),),
    )

    fact = bundle.metrics[0]
    # 末尾零值保留原值并告警；未补零月份仍按日历顺序（9 月在 10 月之前）。
    assert [item.period for item in fact.period_values][-4:] == ["2025-9", "2025-10", "2025-11", "2025-12"]
    assert any("2025-11 至 2025-12" in warning for warning in fact.warnings)


def test_freezes_metric_label_from_matching_schema():
    ctx = context('current').model_copy(update={'schema_snapshot': {
        'sourceId': 'dynamic_source', 'tables': [{
            'database': 'dynamic_db', 'name': 'dynamic_table',
            'columns': [{'name': 'amount', 'description': '设备租赁回款'}],
        }],
    }})
    bundle = build_deterministic_analysis_bundle(
        analysis(), (('current', b'month,department,amount\n2025-01,A,10\n', ctx, ('current',)),),
    )
    assert bundle.metrics[0].display_name == '设备租赁回款'


@pytest.mark.parametrize("selected", ["actual", "budget"])
def test_correlation_uses_the_metrics_registered_scope(selected):
    content = (
        b"month,department,scope_type,amount,visits\n"
        b"2025-01,A,actual,1,1\n2025-01,B,actual,2,2\n2025-01,C,actual,3,3\n"
        b"2025-01,A,budget,1,30\n2025-01,B,budget,2,20\n2025-01,C,budget,3,10\n"
    )
    scope = {"scope_type": selected}
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits"), correlation=True),
        (("current", content, context(
            "current", fields=("month", "department", "scope_type", "amount", "visits"),
            semantics=(semantic("amount", scope=scope), semantic("visits", scope=scope)),
        ), ("current",)),),
        profile_metrics=(
            {"code": "amount", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount"},
            {"code": "visits", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits"},
        ),
    )
    detail = bundle.correlation_details[0]
    assert detail.sample_count == 3
    assert detail.value == pytest.approx(1 if selected == "actual" else -1)
    assert detail.scope == scope
    assert next(iter(bundle.correlations.values())) == detail.value

    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    changed_scope = detail.model_copy(update={"scope": {"scope_type": "other"}})
    changed_bundle = assign_fact_ids(bundle.model_copy(update={"correlation_details": (changed_scope,)}))
    assert changed_bundle.correlation_details[0].fact_id != detail.fact_id


def test_correlation_skips_incompatible_metric_scopes_with_warning():
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits"), correlation=True),
        (("current", b"month,department,scope_type,amount,visits\n"
          b"2025-01,A,actual,1,1\n2025-01,B,actual,2,2\n2025-01,C,budget,3,3\n",
          context("current", fields=("month", "department", "scope_type", "amount", "visits"),
                  semantics=(semantic("amount", scope={"scope_type": "actual"}),
                             semantic("visits", scope={"scope_type": "budget"}))),
          ("current",)),),
        profile_metrics=(
            {"code": "amount", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount"},
            {"code": "visits", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits"},
        ),
    )
    assert bundle.metrics
    assert bundle.correlations == {}
    assert bundle.correlation_details == ()
    assert any("固定范围不一致" in warning for warning in bundle.warnings)



def test_profile_month_dimension_makes_month_start_dates_compare_the_whole_window():
    from smart_reporting.reporting.workflow.runtime.datasets import _profile_monthly_period_columns

    profile = {"dimensions": [
        {"code": "month", "kind": "time", "fieldRefs": ["rj.dwd_income_budget_view.data_date"]},
        {"code": "year", "kind": "time", "fieldRefs": ["rj.dwd_project_budget_view.year"]},
    ]}
    assert _profile_monthly_period_columns(profile) == {("dwd_income_budget_view", "data_date")}
    assert _profile_monthly_period_columns(None) == frozenset()

    current = b"month,department,amount\n2025-01-01,A,10\n2025-02-01,A,20\n2025-03-01,A,30\n"
    baseline = b"month,department,amount\n2024-01-01,A,5\n2024-02-01,A,10\n2024-03-01,A,15\n"

    def contexts(grain: str):
        return tuple(
            (role, data, context(role).model_copy(update={"period_granularities": {"month": grain}}), (role,))
            for role, data in (("current", current), ("yoy", baseline))
        )

    # 未经 Profile 确认的 date 粒度保持按日判断，只能对齐最后一期。
    day = build_deterministic_analysis_bundle(analysis(), contexts("date")).comparisons[0]
    assert (day.period_start, day.period_end) == ("2025-03-01", "2025-03-01")
    month = build_deterministic_analysis_bundle(analysis(), contexts("month")).comparisons[0]
    assert (month.period_start, month.period_end) == ("2025-01-01", "2025-03-01")
    assert (month.current_total, month.baseline_total) == (60, 30)


def test_fact_keeps_only_its_own_profile_defects_while_bundle_keeps_all_alerts():
    alerts = (
        "[amount] is highly overall correlated with [visits]",
        "[amount] has 3 (50.0%) zeros",
        "[department] is highly imbalanced (0.55)",
        "[visits] has a constant value",
        "[amount] has 2 (10.0%) missing values",
        "同一月份有多条科室或项目明细记录，未在明细层面做趋势与季节性检验；趋势判断须以按月及科室汇总后的数据为准。",
        "数据源提示：部分科室未映射。",
    )
    current = b"month,department,amount\n2025-01,A,10\n2025-02,A,20\n"
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ("current", current, context("current").model_copy(update={"quality_warnings": alerts}), ("current",)),
    ))
    fact = bundle.metrics[0]
    assert set(fact.warnings) >= {"[amount] has 2 (10.0%) missing values", "数据源提示：部分科室未映射。"}
    assert not {alerts[0], alerts[1], alerts[2], alerts[3], alerts[5]} & set(fact.warnings)
    # 描述性告警不丢失：仍作为分析级 warnings 供章节披露。
    assert set(alerts) <= set(bundle.warnings)


def test_correlations_are_only_computed_when_the_analysis_asks_for_them():
    raw = b"month,department,amount,visits\n2025-01,A,10,1\n2025-02,A,20,3\n2025-03,A,40,4\n"
    ctx = context("current", fields=("month", "department", "amount", "visits"),
                  semantics=(semantic("amount", unit="元"), semantic("visits", unit="人次")))
    plain = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")), (("current", raw, ctx, ("current",)),)
    )
    assert not plain.correlations and not plain.correlation_details
    requested = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits"), correlation=True), (("current", raw, ctx, ("current",)),)
    )
    assert requested.correlation_details


def test_period_sums_do_not_depend_on_row_order():
    """同一数据集在不同分析中行序不同；浮点求和末位不同会被核对视为冲突事实（写成“待核实”）。"""
    import random

    import polars as pl

    from smart_reporting.reporting.hospital_operation.deterministic_analysis import _period_values

    rng = random.Random(7)
    rows = [("2025-01-01" if index % 2 else "2025-02-01", 145289383.78472222 * rng.random())
            for index in range(5000)]
    results = set()
    for seed in range(6):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        frame = pl.DataFrame({"month": [r[0] for r in shuffled], "amount": [str(r[1]) for r in shuffled]})
        results.add(tuple(item.value for item in _period_values(
            frame, "amount", "month", "sum", period_granularity="month")))
    assert len(results) == 1


def test_period_level_warnings_flag_spikes_and_low_tail_without_asserting_causes():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        PeriodValue,
        _period_level_warnings,
    )

    def series(*values):
        return tuple(PeriodValue(period=f"2025-{index:02d}-01", value=value)
                     for index, value in enumerate(values, start=1))

    # 与真实支出同形：1 月含年度量级数据，9 月入账不足。
    warnings = _period_level_warnings(
        "actual_expenditure", series(147.9, 14.8, 15.4, 16.0, 14.6, 12.1, 14.9, 14.2, 4.0), enabled=True
    )
    assert any("2025-01-01" in item and "量级异常" in item for item in warnings)
    assert any("2025-09-01" in item and "完整性待确认" in item for item in warnings)
    assert all("未入账" not in item for item in warnings)
    # 正常波动、期末零值（另有规则）与存量不告警。
    assert _period_level_warnings("x", series(8.9, 9.0, 10.9, 10.9, 10.6, 11.6, 10.9, 11.7, 9.3), enabled=True) == ()
    assert _period_level_warnings("x", series(10, 11, 12, 10, 0, 0), enabled=True) == ()
    assert _period_level_warnings("x", series(147.9, 14.8, 15.4, 16.0), enabled=False) == ()


def test_dimension_concentration_is_reported_at_analysis_level():
    raw = (b"month,department,amount\n2025-01,A,1000\n2025-01,B,1\n2025-02,A,1000\n2025-02,C,2\n")
    bundle = build_deterministic_analysis_bundle(analysis(), (("current", raw, context("current"), ("current",)),))
    assert any("集中于“A”" in item for item in bundle.warnings)
    assert not any("集中于" in item for item in bundle.metrics[0].warnings)
    balanced = b"month,department,amount\n2025-01,A,10\n2025-01,B,9\n2025-02,A,10\n2025-02,B,8\n"
    assert not any("集中于" in item for item in build_deterministic_analysis_bundle(
        analysis(), (("current", balanced, context("current"), ("current",)),)).warnings)


@pytest.mark.parametrize("aggregation,rows,expected", [
    ("count", "A,1\nA,2\nB,1000\n", None),
    ("count", "A,foo\n" * 100 + "B,bar\n", "99.01%"),
    ("sum", "A,100\nA,100\n", "100.00%"),
    ("average", "A,1\nB,1000\n", None),
    ("count_distinct", "A,1\nB,1000\n", None),
    ("sum", "A,100\nB,-1\n", None),
    ("sum", "A,100\n,10\n", None),
])
def test_concentration_uses_registered_additive_aggregation(aggregation, rows, expected):
    raw = ("month,department,amount\n" + "".join(
        "2025-01," + line + "\n" for line in rows.splitlines()
    )).encode()
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ("current", raw, context("current", semantics=(semantic("amount", aggregation),)), ("current",)),
    ))
    warnings = [item for item in bundle.warnings if "集中于" in item]
    if expected is None:
        assert warnings == []
    else:
        assert len(warnings) == 1
        assert expected in warnings[0] and "“A”" in warnings[0]


def test_concentration_does_not_warn_for_explicit_single_organization_scope():
    bundle = build_deterministic_analysis_bundle(analysis(), ((
        "current", b"month,department,amount\n2025-01,A,100\n2025-01,B,1\n",
        context("current", semantics=(semantic("amount", scope={"department": "A"}),)), ("current",),
    ),))
    assert not any("集中于" in item for item in bundle.warnings)
