import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset
from smart_reporting.reporting.tests.test_trace_drilldown_builder import (
    DIMENSIONS,
    METRICS,
    SEMANTICS,
    metric,
)
from smart_reporting.reporting.tests.test_trace_server_tables import _Harness
from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.fact_index import (
    assign_fact_ids,
    comparison_fact_identity,
    fact_input_relations,
)
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin


def comparison(
    current_scope="A",
    baseline_scope=None,
    *,
    role="yoy",
    current_aggregation="sum",
    baseline_aggregation="sum",
):
    entries = []
    baseline_scope = baseline_scope or current_scope
    for dataset_role, period, scope, amount, aggregation in [
        ("current", "2025-01", current_scope, 100, current_aggregation),
        (role, "2024-01" if role == "yoy" else "2024-12", baseline_scope, 50, baseline_aggregation),
    ]:
        raw = f"month,department,amount\n{period},A,{amount}\n{period},B,{amount}\n".encode()
        ctx = context(
            dataset_role,
            semantics=(semantic("amount", aggregation, scope={"department": scope}, unit="元"),),
        )
        entry = dataset(dataset_role, raw, ctx)
        entries.append((*entry[:3], (dataset_role,)))
    return build_deterministic_analysis_bundle(analysis(), tuple(entries))


@pytest.mark.parametrize("role", ["yoy", "mom"])
def test_mismatched_comparison_scope_is_not_reported_as_like_for_like(role):
    bundle = comparison("A", "B", role=role)
    assert not bundle.comparisons
    assert len(bundle.metrics) == 2
    assert any("固定范围或聚合口径不一致" in warning for warning in bundle.warnings)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_comparison_keeps_source_scope_after_server_assembly(reverse):
    left = comparison("A").model_copy(update={"analysis_id": "analysis_101"})
    right = comparison("B").model_copy(update={"analysis_id": "analysis_102"})
    assert left.metrics[0].fact_id != right.metrics[0].fact_id
    assert left.comparisons[0].fact_id != right.comparisons[0].fact_id
    bundles = (right, left) if reverse else (left, right)
    files, identities, resources = {}, {}, {}
    for bundle in bundles:
        raw = bundle.model_dump_json(by_alias=True).encode()
        path = f"facts/{bundle.analysis_id}.json"
        files[path] = raw
        identities[bundle.analysis_id] = FileIdentity(
            path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )
        resources[bundle.analysis_id] = derive_resource_id(path)
    _, _, directory, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files),
        SimpleNamespace(),
        checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=()),
    )
    # Assert each source, so whichever is retained cannot satisfy both.
    for bundle, scope in ((left, "A"), (right, "B")):
        token = "{{value:" + bundle.comparisons[0].fact_id + ":changeRate:%}}"
        text, refs, notices = render_bound_numbers(
            scope + "科收入同比增长" + token,
            [b.model_dump_json(by_alias=True) for b in bundles],
            key=scope,
        )
        assert len(refs) == 1 and not notices, (text, notices)
        selected = resolve_number_reference(
            token, [b.model_dump_json(by_alias=True) for b in bundles]
        )
        assert selected["scope"] == {"department": scope}
        artifact = SimpleNamespace(
            section_code="section_101",
            claims=(),
            blocks=(
                SimpleNamespace(
                    number_references=refs,
                    review_notices=(),
                    claim_ids=tuple(ref.claim_id for ref in refs),
                ),
            ),
        )
        bindings = build_claim_subject_bindings((artifact,), directory, resources)
        assert len(bindings) == 1
        assert bindings[0].fact_refs[0].analysis_id == bundle.analysis_id, (
            scope,
            bindings[0].fact_refs,
        )


def declarations(bundles):
    return build_drilldown_metrics(
        bundles=bundles,
        dataset_columns={"dataset-drill01": ("department", "month", "revenue", "visits", "scope")},
        profile_dimensions=DIMENSIONS,
        profile_metrics=METRICS,
        measure_semantics=SEMANTICS,
    )


def test_metadata_only_repeat_does_not_disable_ratio_drilldown():
    bundle = {
        "metrics": [metric("revenue", "revenue", 750), metric("visits", "visits", 53)],
        "derivedMetrics": [
            {
                "code": "revenue_per_visit",
                "numeratorMetric": "revenue",
                "denominatorMetric": "visits",
                "value": 750 / 53,
                "datasetIds": ["dataset-drill01"],
            }
        ],
    }
    single = {x.metric_code for x in declarations([bundle])}
    assert single == {"revenue", "visits", "revenue_per_visit"}
    other = copy.deepcopy(bundle)
    for fact in other["metrics"]:
        fact["displayName"] = "另一个分析展示名"
        fact["warnings"] = ["仅展示告警"]
    combined = {x.metric_code for x in declarations([bundle, other])}
    assert combined == single, combined


def test_same_scope_comparison_control():
    bundle = comparison("A")
    assert len(bundle.comparisons) == 1
    assert bundle.comparisons[0].change_rate == 100
    assert not bundle.comparisons[0].warnings


def test_exact_duplicate_ratio_control():
    bundle = {
        "metrics": [metric("revenue", "revenue", 750), metric("visits", "visits", 53)],
        "derivedMetrics": [
            {
                "code": "revenue_per_visit",
                "numeratorMetric": "revenue",
                "denominatorMetric": "visits",
                "value": 750 / 53,
                "datasetIds": ["dataset-drill01"],
            }
        ],
    }
    assert {x.metric_code for x in declarations([bundle, copy.deepcopy(bundle)])} == {
        "revenue",
        "visits",
        "revenue_per_visit",
    }


def test_generated_ratio_with_same_fact_ids_and_only_different_display_names():
    from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import metrics

    raw = b"month,department,amount,visits\n2025-01,A,100,10\n2025-01,B,100,10\n"
    definitions = metrics("amount", "visits") + (
        {
            "code": "cost_per_visit",
            "aggregation": "ratio",
            "numeratorMetric": "amount",
            "denominatorMetric": "visits",
        },
    )
    ctx = context(
        "dataset-current01",
        fields=("month", "department", "amount", "visits"),
        semantics=(
            semantic("amount", scope={"department": "A"}, unit="元"),
            semantic("visits", scope={"department": "A"}, unit="人次"),
        ),
    )
    left = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")),
        (dataset("dataset-current01", raw, ctx),),
        profile_metrics=definitions,
    ).model_dump(mode="json", by_alias=True)
    right = copy.deepcopy(left)
    right["analysisId"] = "analysis_102"
    for fact in right["metrics"]:
        fact["displayName"] += "展示"
    kwargs = dict(
        dataset_columns={"dataset-current01": ("month", "department", "amount", "visits")},
        profile_dimensions=(
            {"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},
        ),
        profile_metrics=metrics("amount", "visits")
        + (
            {
                "code": "cost_per_visit",
                "aggregation": "ratio",
                "numeratorMetric": "amount",
                "denominatorMetric": "visits",
            },
        ),
        measure_semantics=(semantic("amount", unit="元"), semantic("visits", unit="人次")),
    )
    before = {x.metric_code for x in build_drilldown_metrics(bundles=[left], **kwargs)}
    assert "cost_per_visit" in before
    assert [x["factId"] for x in left["metrics"]] == [x["factId"] for x in right["metrics"]]
    after = {x.metric_code for x in build_drilldown_metrics(bundles=[left, right], **kwargs)}
    assert after == before, (before, after)


@pytest.mark.parametrize("role", ["yoy", "mom"])
def test_comparison_rejects_different_aggregation_with_soft_warning(role):
    bundle = comparison(role=role, baseline_aggregation="average")
    assert not bundle.comparisons and len(bundle.metrics) == 2
    assert any("聚合口径不一致" in warning for warning in bundle.warnings)


@pytest.mark.parametrize("role", ["yoy", "mom"])
def test_comparison_freezes_ordered_inputs_and_survives_roundtrip(role):
    bundle = comparison(role=role)
    fact = bundle.comparisons[0]
    assert fact.input_fact_ids == tuple(metric.fact_id for metric in bundle.metrics)
    assert assign_fact_ids(bundle).model_dump() == bundle.model_dump()
    loaded = DeterministicAnalysisBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
    assert fact_input_relations(loaded)[fact.fact_id] == fact.input_fact_ids


def legacy_comparison(bundle):
    fact = bundle.comparisons[0].model_copy(update={"input_fact_ids": (), "scope": {}})
    legacy_id = "fact-" + hashlib.sha256(comparison_fact_identity(fact).encode()).hexdigest()[:16]
    payload = bundle.model_dump(mode="json", by_alias=True)
    payload["comparisons"][0].update(factId=legacy_id)
    payload["comparisons"][0].pop("inputFactIds")
    payload["comparisons"][0].pop("scope")
    return json.dumps(payload), legacy_id


def test_single_legacy_comparison_still_resolves():
    raw, fact_id = legacy_comparison(comparison())
    token = "{{value:" + fact_id + ":changeRate:%}}"
    text, refs, notices = render_bound_numbers("收入同比增长" + token, [raw], key="legacy")
    assert text.endswith("100.00%") and len(refs) == 1 and not notices


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_legacy_comparison_collision_is_unverified_instead_of_cross_bound(reverse):
    bundles = (
        comparison("A").model_copy(update={"analysis_id": "analysis_101"}),
        comparison("B").model_copy(update={"analysis_id": "analysis_102"}),
    )
    contents, files, identities = [], {}, {}
    for bundle in reversed(bundles) if reverse else bundles:
        raw, fact_id = legacy_comparison(bundle)
        contents.append(raw)
        path = f"facts/{bundle.analysis_id}.json"
        files[path] = raw.encode()
        identities[bundle.analysis_id] = FileIdentity(
            path=path, size=len(files[path]), sha256=hashlib.sha256(files[path]).hexdigest()
        )
    token = "{{value:" + fact_id + ":changeRate:%}}"
    text, refs, notices = render_bound_numbers(
        "A科收入同比增长" + token, contents, key="legacy-conflict"
    )
    assert "待核实" in text and not refs and notices
    assert resolve_number_reference(token, contents) is None
    _, _, directory, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files),
        SimpleNamespace(),
        checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=()),
    )
    assert fact_id not in directory


@pytest.mark.parametrize(
    "change",
    [
        {"total": 751},
        {"scope": {"scope": "previous"}},
        {"unit": "万元"},
        {"periodEnd": "2025-03"},
    ],
)
def test_different_frozen_values_still_disable_ambiguous_ratio_drilldown(change):
    bundle = {
        "metrics": [metric("revenue", "revenue", 750), metric("visits", "visits", 53)],
        "derivedMetrics": [
            {
                "code": "revenue_per_visit",
                "numeratorMetric": "revenue",
                "denominatorMetric": "visits",
                "value": 750 / 53,
                "datasetIds": ["dataset-drill01"],
            }
        ],
    }
    for fact, key in zip(bundle["metrics"], ("a", "b"), strict=True):
        fact["factId"] = "fact-" + key * 16
    other = copy.deepcopy(bundle)
    other["metrics"][0].update(change)
    codes = {x.metric_code for x in declarations([bundle, other])}
    assert "revenue_per_visit" not in codes
    assert "visits" in codes
