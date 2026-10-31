from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.chart_templates import (
    TEMPLATE_IDS,
    build_chart_input,
    matched_fact_name,
    matched_pointer_count,
    materialize_chart_template,
    template_availability,
)
from smart_reporting.report_editor.table_ai import (
    _review_payload,
    _template_availability,
    _template_spec,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)


def _fact_ref(fact_id: str) -> SimpleNamespace:
    return SimpleNamespace(analysis_id="analysis_001", fact_key=fact_id)


def test_review_payload_carries_per_cell_fact_sources() -> None:
    """逐格来源（§14.1 第 4 步）：数据格携带 FactRef，行标签格不携带。"""
    trace = SimpleNamespace(
        row_keys=("period:2025-09", "total"),
        column_keys=("收入（万元）",),
        cells=(
            SimpleNamespace(
                row_key="period:2025-09",
                column_key="收入（万元）",
                value_selector="periodValues.0",
                fact_refs=(_fact_ref("fact-aaaaaaaaaaaaaaaa"),),
            ),
            SimpleNamespace(
                row_key="total",
                column_key="收入（万元）",
                value_selector="total",
                fact_refs=(_fact_ref("fact-aaaaaaaaaaaaaaaa"),),
            ),
        ),
    )
    markdown = (
        "[[table:t1]]\n"
        "| | 收入（万元） |\n"
        "| --- | ---: |\n"
        "| 2025年9月 | 3,600 |\n"
        "| 合计 | 3,600 |\n\n"
        "[[/table:t1]]"
    )
    payload = _review_payload("", markdown, trace)
    period_cell = payload["rows"][0]["cells"][1]
    assert period_cell["source"] == {
        "analysisId": "analysis_001",
        "factIds": ["fact-aaaaaaaaaaaaaaaa"],
        "selector": "periodValues.0",
    }
    total_cell = payload["rows"][1]["cells"][1]
    assert total_cell["source"]["selector"] == "total"
    # 行标签列（第 0 列）不携带来源。
    assert "source" not in payload["rows"][0]["cells"][0]
    # 未提供 trace 时来源缺省，审阅仍可用。
    assert "source" not in _review_payload("", markdown)["rows"][0]["cells"][1]


def test_all_chart_templates_are_deterministic_and_disable_without_facts() -> None:
    bundle = DeterministicAnalysisBundle(analysisId="analysis_001")
    assert TEMPLATE_IDS == (
        "composition-bars",
        "monthly-trend",
        "yoy-comparison",
        "budget-progress",
    )
    for template_id in TEMPLATE_IDS:
        available, reason = template_availability(template_id, bundle)
        assert available is False
        assert reason


def test_chart_template_materializes_the_referenced_fact_once_with_source_identity() -> None:
    def metric(letter: str, dataset_id: str, values: list[int]) -> dict[str, object]:
        return {
            "factId": "fact-" + letter * 16,
            "datasetId": dataset_id,
            "datasetSha256": letter * 64,
            "periodRoles": ["current"],
            "metricCodes": [f"metric-{letter}"],
            "field": f"metric_{letter}",
            "fieldRef": f"source.table.metric_{letter}",
            "aggregation": "sum",
            "unit": "元",
            "formula": "sum",
            "total": sum(values),
            "missingCount": 0,
            "zeroCount": 0,
            "negativeCount": 0,
            "periodGranularity": "month",
            "periodValues": [
                {"period": f"2025-{index + 1:02d}", "value": value}
                for index, value in enumerate(values)
            ],
        }

    bundle = DeterministicAnalysisBundle.model_validate(
        {
            "analysisId": "analysis_001",
            "metrics": [
                metric("a", "dataset-a", [1, 2, 3]),
                metric("b", "dataset-b", [10, 20, 30]),
            ],
        }
    )
    refs = (
        SimpleNamespace(
            fact_kind="metric",
            fact_key="fact-bbbbbbbbbbbbbbbb",
            json_pointer="/metrics/1",
        ),
    )
    materialized = materialize_chart_template("monthly-trend", bundle, refs)
    assert materialized.source_pointers == ("/metrics/1",)
    payload = json.loads(
        build_chart_input(
            "monthly-trend",
            bundle,
            chart_id="chart_001",
            source_path="facts.json",
            source_resource_id="res-facts",
            fact_file_path="facts.json",
            fact_file_sha256="c" * 64,
            materialization=materialized,
        )
    )
    assert payload["source"] == {
        "analysisId": "analysis_001",
        "path": "facts.json",
        "dataPath": "/metrics/1",
        "dataPaths": ["/metrics/1"],
        "factFileResourceId": "res-facts",
        "factFilePath": "facts.json",
        "factFileSha256": "c" * 64,
    }
    assert [row[payload["columns"].index("value")] for row in payload["rows"]] == [
        10.0,
        20.0,
        30.0,
    ]


def test_all_table_templates_disable_without_registered_facts() -> None:
    bundle = DeterministicAnalysisBundle(analysisId="analysis_001")
    for template_id in ("composition", "yoy-comparison", "budget-execution", "monthly-detail"):
        available, reason = _template_availability(template_id, bundle)
        assert available is False
        assert reason
        spec, skipped = _template_spec(template_id, bundle)
        assert spec is None
        if template_id != "budget-execution":
            assert skipped


def test_yoy_template_labels_use_frozen_parent_names_and_periods():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicComparison,
        DeterministicMetricFact,
    )

    metrics = []
    comparisons = []
    for letter, label in (("a", "医疗收入"), ("b", "医疗成本")):
        fact = DeterministicMetricFact(datasetId="dataset-current", datasetSha256="a" * 64,
            periodRoles=("current",),
            field="indicator_value", fieldRef="source.indicator_value", displayName=label,
            aggregation="sum", formula="sum(indicator_value)", unit="元", total=1200,
            missingCount=0, zeroCount=0, negativeCount=0, factId="fact-" + letter * 16)
        metrics.append(fact)
        comparisons.append(DeterministicComparison(comparisonType="yoy", field="indicator_value",
            fieldRef="source.indicator_value", currentDatasetId="dataset-current",
            baselineDatasetId="dataset-baseline", currentDatasetSha256="a" * 64,
            baselineDatasetSha256="b" * 64, currentTotal=1200, baselineTotal=1000,
            change=200, changeRate=20, formula="current - baseline", unit="元", periodEnd="2025-01",
            inputFactIds=(fact.fact_id,)))
    bundle = DeterministicAnalysisBundle(analysisId="analysis_001", metrics=tuple(metrics),
        comparisons=tuple(comparisons))
    materialized = materialize_chart_template("yoy-comparison", bundle)
    assert materialized.available
    labels = [row["label"] for row in materialized.rows]
    assert len(set(labels)) == 2
    assert "医疗收入" in labels[0] and "2025-01" in labels[0]
    assert "医疗成本" in labels[1] and "2025-01" in labels[1]


def test_recommendation_signals_follow_the_bound_facts() -> None:
    """推荐信号只认图表绑定的事实：命中计数与点名都随 fact_refs 变，无绑定则无信号。"""

    def metric(letter: str, values: list[int]) -> dict[str, object]:
        return {
            "factId": "fact-" + letter * 16,
            "datasetId": f"dataset-{letter}",
            "datasetSha256": letter * 64,
            "periodRoles": ["current"],
            "metricCodes": [f"metric-{letter}"],
            "field": f"metric_{letter}",
            "fieldRef": f"source.table.metric_{letter}",
            "displayName": f"指标{letter.upper()}",
            "aggregation": "sum",
            "unit": "元",
            "formula": "sum",
            "total": sum(values),
            "missingCount": 0,
            "zeroCount": 0,
            "negativeCount": 0,
            "periodGranularity": "month",
            "periodValues": [
                {"period": f"2025-{index + 1:02d}", "value": value}
                for index, value in enumerate(values)
            ],
        }

    bundle = DeterministicAnalysisBundle.model_validate(
        {
            "analysisId": "analysis_001",
            "metrics": [metric("a", [1, 2, 3]), metric("b", [10, 20, 30])],
        }
    )
    refs = (
        SimpleNamespace(
            fact_kind="metric",
            fact_key="fact-bbbbbbbbbbbbbbbb",
            json_pointer="/metrics/1",
        ),
    )
    materialized = materialize_chart_template("monthly-trend", bundle, refs)
    assert matched_pointer_count(materialized.source_pointers, refs) == 1
    assert matched_fact_name(materialized.source_pointers, refs, bundle) == "指标B"
    assert matched_pointer_count(materialized.source_pointers, ()) == 0
    assert matched_fact_name(materialized.source_pointers, (), bundle) is None


def _composition_bundle(*, dimensions=("area",), roles=("current", "yoy")):
    metrics, breakdowns = [], []
    for position, role in enumerate(roles):
        parent = {
            "factId": f"fact-{position + 1:016x}",
            "datasetId": f"dataset-{role}-{position}",
            "datasetSha256": "a" * 64,
            "periodRoles": [role], "field": "indicator_value",
            "fieldRef": "source.indicator_value", "displayName": "医疗收入，也称收入金额",
            "aggregation": "sum", "formula": "sum", "unit": "元",
            "total": 100, "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
        }
        metrics.append(parent)
        for dimension in dimensions:
            for label, value in (("甲", 60), ("乙", 40)):
                breakdowns.append({**parent, "factId": f"fact-{len(breakdowns) + 100:016x}",
                    "parentFactId": parent["factId"], "breakdownField": dimension,
                    "breakdownValue": label, "scope": {dimension: label}, "total": value})
    return DeterministicAnalysisBundle.model_validate({"analysisId": "analysis_001",
        "metrics": metrics, "breakdowns": breakdowns})


def _bound(pointer, kind="metric"):
    return SimpleNamespace(fact_kind=kind, fact_key=None, json_pointer=pointer)


def test_composition_prefers_current_only_for_the_same_bound_measure_and_dimension():
    bundle = _composition_bundle()
    result = materialize_chart_template("composition-bars", bundle,
        (_bound("/metrics/0"), _bound("/metrics/1")))
    assert result.available
    assert result.source_pointers == ("/metrics/0", "/breakdowns/0", "/breakdowns/1")


def test_composition_explicit_dimension_beats_parent_binding_and_keeps_explicit_baseline():
    bundle = _composition_bundle(dimensions=("area", "department"))
    result = materialize_chart_template("composition-bars", bundle,
        (_bound("/metrics/0"), _bound("/metrics/1"), _bound("/breakdowns/6")))
    assert result.available
    assert result.source_pointers == ("/metrics/1", "/breakdowns/6", "/breakdowns/7")


@pytest.mark.parametrize("dimensions,roles", [
    (("area", "department"), ("current", "yoy")),
    (("area",), ("current", "current")),
])
def test_composition_remains_disabled_when_dimension_or_measure_is_ambiguous(dimensions, roles):
    bundle = _composition_bundle(dimensions=dimensions, roles=roles)
    result = materialize_chart_template("composition-bars", bundle,
        (_bound("/metrics/0"), _bound("/metrics/1")))
    assert not result.available


def test_composition_does_not_use_unbound_inventory_or_infer_supplement_dimension():
    bundle = _composition_bundle(roles=("current",))
    for refs in (
        (_bound("/metrics/99"),),
        (_bound("/metrics/0"), _bound("/findings/0", "supplemental_finding")),
    ):
        result = materialize_chart_template("composition-bars", bundle, refs)
        assert not result.available
        assert result.reason


def test_composition_does_not_prefer_current_across_different_business_names():
    bundle = _composition_bundle()
    other = bundle.metrics[1].model_copy(update={"display_name": "医疗成本"})
    bundle = bundle.model_copy(update={"metrics": (bundle.metrics[0], other)})
    result = materialize_chart_template("composition-bars", bundle,
        (_bound("/metrics/0"), _bound("/metrics/1")))
    assert not result.available


def test_comparison_recommendation_uses_frozen_parent_business_name():
    bundle = _composition_bundle()
    comparison = {
        "comparisonType": "yoy", "field": "indicator_value",
        "fieldRef": "source.indicator_value", "currentDatasetId": "current",
        "baselineDatasetId": "baseline", "currentDatasetSha256": "a" * 64,
        "baselineDatasetSha256": "b" * 64, "currentTotal": 100,
        "baselineTotal": 80, "change": 20, "formula": "current-baseline",
        "inputFactIds": [fact.fact_id for fact in bundle.metrics],
    }
    bundle = DeterministicAnalysisBundle.model_validate({**bundle.model_dump(by_alias=True),
        "comparisons": [comparison]})
    refs = (_bound("/comparisons/0", "comparison"),)
    assert matched_fact_name(("/comparisons/0",), refs, bundle) == "医疗收入"

    # 冻结名称冲突时退回通用推荐，不泄露字段或任取一个名称。
    conflicting = bundle.metrics[1].model_copy(update={"display_name": "医疗成本"})
    bundle = bundle.model_copy(update={"metrics": (bundle.metrics[0], conflicting)})
    assert matched_fact_name(("/comparisons/0",), refs, bundle) is None
