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


def analysis(*, fields: tuple[str, ...] = ("amount",)) -> DetailedAnalysisItem:
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
        actions=("汇总", "同比", "环比", "异常"),
        evidenceSummary="服务端复算",
        suggestedSection="收入分析",
        completionConditions=("固定指标可复算",),
    )


def test_measure_semantic_accepts_confirmed_unit() -> None:
    value = MeasureSemantic.model_validate(semantic("dynamic_value", unit="元"))

    assert value.unit == "元"


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


def test_deterministic_bundle_excludes_suspicious_trailing_zero_months() -> None:
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
    assert comparison.baseline_total == 15
    assert comparison.change_rate == 100
    assert comparison.period_end == "2025-02"
    assert any("连续 2 个零值期间" in warning for warning in comparison.warnings)


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


def test_deterministic_bundle_builds_profile_ratio_difference_and_reconciliation() -> None:
    semantics = (
        semantic("actual_value", unit="元"),
        semantic("budget_value", unit="元"),
        semantic("ledger_value", unit="元"),
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
                b"month,actual_value,budget_value\n"
                b"2025-01,80,100\n"
                b"2025-02,70,100\n"
                b"2025-03,,100\n",
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
