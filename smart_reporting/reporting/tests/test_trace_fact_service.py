"""B2 事实稳定 ID、FactRef 解析与一层依赖展开测试（计划 B2 第 1/4 项）。"""

from __future__ import annotations

import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import FactRefV1
from smart_reporting.reporting.trace.fact_index import (
    assign_fact_ids,
    fact_input_relations,
    fact_pointer,
)
from smart_reporting.reporting.trace.fact_service import (
    expand_fact_tree,
    resolve_fact,
)

from .test_deterministic_analysis import analysis, context, semantic

CURRENT = b"month,department,amount\n2025-01,A,100\n2025-02,B,0\n2025-03,A,-10\n"
MOM = b"month,department,amount\n2025-02,A,60\n"


def _bundle():
    """含 metric/比较/派生比率/对账的完整样本（语义与既有确定性测试一致）。"""

    fields = ("month", "department", "actual_value", "budget_value", "ledger_value")
    semantics = (
        semantic("actual_value", unit="元"),
        semantic("budget_value", unit="元"),
        semantic("ledger_value", unit="元"),
    )
    dataset_context = context("current", fields=fields, semantics=semantics)
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
    return build_deterministic_analysis_bundle(
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
        profile_hash="c" * 64,
    )


# ---------------------------------------------------------------------------
# factId 赋值（未决#3）
# ---------------------------------------------------------------------------


def test_bundle_facts_receive_stable_content_addressed_ids() -> None:
    bundle = _bundle()
    assert bundle.metrics and bundle.derived_metrics and bundle.reconciliations
    all_ids = [f.fact_id for f in bundle.metrics]
    all_ids += [f.fact_id for f in bundle.comparisons]
    all_ids += [f.fact_id for f in bundle.derived_metrics]
    all_ids += [f.fact_id for f in bundle.reconciliations]
    assert all(i and i.startswith("fact-") and len(i) == 21 for i in all_ids)
    assert len(all_ids) == len(set(all_ids))  # bundle 内唯一


def test_fact_ids_are_deterministic_across_rebuild() -> None:
    first = _bundle()
    second = _bundle()
    assert [f.fact_id for f in first.metrics] == [f.fact_id for f in second.metrics]
    # 快照身份变化（真实内容变化必然伴随 dataset sha256 变化）→ ID 变化。
    fields = ("month", "department", "actual_value", "budget_value", "ledger_value")
    semantics = (
        semantic("actual_value", unit="元"),
        semantic("budget_value", unit="元"),
        semantic("ledger_value", unit="元"),
    )
    rebuilt = build_deterministic_analysis_bundle(
        analysis(fields=("actual_value", "budget_value", "ledger_value")),
        (
            (
                "current",
                b"month,department,actual_value,budget_value,ledger_value\n"
                b"2025-01,A,81,100,80\n"
                b"2025-01,B,10,20,8\n",
                context("current", fields=fields, semantics=semantics, sha256="d" * 64),
                ("current",),
            ),
        ),
        profile_metrics=(
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
        ),
        profile_hash="c" * 64,
    )
    assert [f.fact_id for f in first.metrics] != [f.fact_id for f in rebuilt.metrics]


def test_assign_fact_ids_is_idempotent_for_duplicate_free_bundles() -> None:
    bundle = _bundle()
    reassigned = assign_fact_ids(bundle)
    assert [f.fact_id for f in reassigned.metrics] == [f.fact_id for f in bundle.metrics]


def test_fact_pointer_maps_ids_to_array_positions() -> None:
    bundle = _bundle()
    first_metric = bundle.metrics[0]
    assert fact_pointer(bundle, first_metric.fact_id) == "/metrics/0"
    first_derived = bundle.derived_metrics[0]
    assert fact_pointer(bundle, first_derived.fact_id) == "/derivedMetrics/0"
    assert fact_pointer(bundle, "fact-" + "0" * 16) is None


# ---------------------------------------------------------------------------
# 输入关系
# ---------------------------------------------------------------------------


def test_derived_and_comparison_link_to_metric_inputs() -> None:
    bundle = _bundle()
    relations = fact_input_relations(bundle)
    # 派生 fact 的分子/分母都能落到带 income_total code 的 metric facts。
    for derived in bundle.derived_metrics:
        inputs = relations[derived.fact_id]
        assert inputs, "派生事实应至少关联一个输入 metric fact"
        input_facts = {f.fact_id for f in bundle.metrics}
        assert set(inputs) <= input_facts
    # 比较 fact 关联本期 dataset 上的对应 metric fact。
    for comparison in bundle.comparisons:
        inputs = relations[comparison.fact_id]
        assert inputs, "比较事实应关联本期输入 metric fact"
        by_id = {f.fact_id: f for f in bundle.metrics}
        for fact_id in inputs:
            assert by_id[fact_id].dataset_id == comparison.current_dataset_id


# ---------------------------------------------------------------------------
# FactRef 解析与展开
# ---------------------------------------------------------------------------


def _bundle_bytes() -> bytes:
    return json.dumps(
        _bundle().model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _metric_ref(bundle, index: int = 0) -> FactRefV1:
    fact = bundle.metrics[index]
    return FactRefV1(
        analysisId=bundle.analysis_id,
        fileResourceId="trf-" + "0" * 20,
        jsonPointer=fact_pointer(bundle, fact.fact_id),
        factKind="metric",
        factKey=fact.fact_id,
    )


def test_resolve_fact_returns_entry_display_value_and_inputs() -> None:
    bundle = _bundle()
    payload = resolve_fact(_bundle_bytes(), _metric_ref(bundle))
    assert payload["factKind"] == "metric"
    assert payload["displayValue"] is not None
    assert payload["entry"]["factId"] == bundle.metrics[0].fact_id
    assert payload["inputFactRefs"] == ()  # metric 是叶子


def test_resolve_fact_rejects_mismatched_analysis_and_drifted_pointer() -> None:
    bundle = _bundle()
    ref = _metric_ref(bundle)
    with pytest.raises(ReportingError) as exc:
        resolve_fact(_bundle_bytes(), ref.model_copy(update={"analysis_id": "analysis_999"}))
    assert exc.value.code == "fact_binding_unavailable"
    # 位置漂移防御：factKey 与指针命中记录不符。
    drifted = ref.model_copy(update={"fact_key": "fact-" + "f" * 16})
    with pytest.raises(ReportingError) as exc:
        resolve_fact(_bundle_bytes(), drifted)
    assert exc.value.code == "fact_binding_unavailable"
    # 越界指针。
    bad = ref.model_copy(update={"json_pointer": "/metrics/999"})
    with pytest.raises(ReportingError) as exc:
        resolve_fact(_bundle_bytes(), bad)
    assert exc.value.code == "fact_binding_unavailable"


def test_resolve_derived_fact_exposes_metric_inputs() -> None:
    bundle = _bundle()
    derived = bundle.derived_metrics[0]
    ref = FactRefV1(
        analysisId=bundle.analysis_id,
        fileResourceId="trf-" + "0" * 20,
        jsonPointer=fact_pointer(bundle, derived.fact_id),
        factKind="derived",
        factKey=derived.fact_id,
    )
    payload = resolve_fact(_bundle_bytes(), ref)
    assert payload["inputFactRefs"], "派生事实必须暴露输入 metric 引用"
    assert all(item["factId"] for item in payload["inputFactRefs"])


def test_expand_fact_tree_depth_and_node_budget() -> None:
    bundle = _bundle()
    derived = bundle.derived_metrics[0]
    ref = FactRefV1(
        analysisId=bundle.analysis_id,
        fileResourceId="trf-" + "0" * 20,
        jsonPointer=fact_pointer(bundle, derived.fact_id),
        factKind="derived",
    )
    tree = expand_fact_tree(_bundle_bytes(), ref, depth=2)
    assert tree["factKind"] == "derived"
    assert tree["inputs"], "深度 2 应展开到 metric 叶子"
    assert all("inputs" not in child or not child["inputs"] for child in tree["inputs"])
    with pytest.raises(ReportingError) as exc:
        expand_fact_tree(_bundle_bytes(), ref, depth=99)
    assert exc.value.code == "request_invalid"
