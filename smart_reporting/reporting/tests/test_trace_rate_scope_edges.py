import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)


def monthly(previous, current):
    raw = f"month,department,amount\n2025-01,A,{previous}\n2025-02,A,{current}\n".encode()
    ctx = context("current", semantics=(semantic("amount", unit="元"),)).model_copy(
        update={"period_granularities": {"month": "month"}}
    )
    return build_deterministic_analysis_bundle(
        analysis().model_copy(update={"series_granularity": "month"}),
        (dataset("current", raw, ctx),),
    )


@pytest.mark.parametrize(
    "previous,current,expected",
    [(-100, -50, 50), (-100, -150, -50), (-100, 0, 100), (-100, 100, 200), (-100, -100, 0)],
)
def test_monthly_selector_growth_matches_deterministic_comparison(previous, current, expected):
    bundle = monthly(previous, current)
    token = "{{value:" + bundle.metrics[0].fact_id + ":periodChangeRates.1:%}}"
    frozen = [bundle.model_dump_json(by_alias=True)]
    selected = resolve_number_reference(token, frozen)
    # The same two periods, provided as current/baseline datasets, use abs(baseline).
    entries = []
    for role, period, value in [("current", "2025-02", current), ("mom", "2025-01", previous)]:
        raw = f"month,department,amount\n{period},A,{value}\n".encode()
        entry = dataset(role, raw, context(role, semantics=(semantic("amount", unit="元"),)))
        entries.append((*entry[:3], (role,)))
    check = build_deterministic_analysis_bundle(analysis(), tuple(entries)).comparisons[0]
    assert check.change_rate == expected
    text, refs, notices = render_bound_numbers(
        "2025年2月收入环比增长" + token, frozen, key="growth"
    )
    assert len(refs) == 1 and not notices
    assert selected["formula"] == f"(({current}) - ({previous})) / abs({previous}) * 100"
    if expected < 0:
        assert "下降" in text and "增长" not in text
    else:
        assert "增长" in text and "下降" not in text
    assert selected["value"] == check.change_rate, (
        selected["value"],
        check.change_rate,
        text,
        notices,
    )


@pytest.mark.parametrize("previous,current,expected", [(100, 150, 50), (100, 50, -50)])
def test_positive_baseline_rate_control(previous, current, expected):
    bundle = monthly(previous, current)
    token = "{{value:" + bundle.metrics[0].fact_id + ":periodChangeRates.1:%}}"
    assert (
        resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)])["value"]
        == expected
    )


def scoped(scope):
    raw = b"month,department,region,service,amount\n2025-01,A,east;service=inpatient,other,100\n2025-01,A,east,inpatient,100\n"
    ctx = context(
        "current",
        fields=("month", "department", "region", "service", "amount"),
        semantics=(semantic("amount", scope=scope, unit="元"),),
    )
    return build_deterministic_analysis_bundle(analysis(), (dataset("current", raw, ctx),))


@pytest.mark.parametrize("reverse", [False, True])
def test_scope_delimiters_do_not_drop_independent_registered_numbers(reverse):
    left = scoped({"region": "east;service=inpatient"})
    right = scoped({"region": "east", "service": "inpatient"})
    assert left.metrics[0].scope != right.metrics[0].scope
    assert left.metrics[0].fact_id != right.metrics[0].fact_id
    bundles = (right, left) if reverse else (left, right)
    for bundle in bundles:
        assert bundle.metrics[0].total == 100
        token = "{{value:" + bundle.metrics[0].fact_id + ":total:元}}"
        text, refs, notices = render_bound_numbers(
            "收入为" + token, [bundle.model_dump_json(by_alias=True)], key="single"
        )
        assert len(refs) == 1 and not notices, (text, notices)
    token = "{{value:" + left.metrics[0].fact_id + ":total:元}}"
    text, refs, notices = render_bound_numbers(
        "收入为" + token, [b.model_dump_json(by_alias=True) for b in bundles], key="combined"
    )
    assert len(refs) == 1 and not notices, (
        left.metrics[0].fact_id,
        right.metrics[0].fact_id,
        text,
        notices,
    )


def test_zero_baseline_has_no_rate_reference():
    bundle = monthly(0, 100)
    token = "{{value:" + bundle.metrics[0].fact_id + ":periodChangeRates.1:%}}"
    assert resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)]) is None
    text, refs, notices = render_bound_numbers(
        "2月收入环比增长" + token, [bundle.model_dump_json(by_alias=True)], key="zero-baseline"
    )
    assert "待核实" in text and not refs and notices


def test_reserved_scope_values_keep_metric_and_correlation_identities_distinct():
    import csv
    import io

    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    scopes = ({"region": "east;service=inpatient"}, {"region": "east", "service": "inpatient"})
    stream = io.StringIO()
    writer = csv.writer(stream)
    fields = ("month", "department", "region", "service", "amount", "visits")
    writer.writerow(fields)
    for region, service in [("east;service=inpatient", "other"), ("east", "inpatient")]:
        for amount in (100, 200, 300):
            writer.writerow(("2025-01", "A", region, service, amount, amount / 10))
    raw = stream.getvalue().encode()
    bundles = []
    for scope in scopes:
        ctx = context(
            "current",
            fields=fields,
            semantics=(
                semantic("amount", scope=scope, unit="元"),
                semantic("visits", scope=scope, unit="人次"),
            ),
        )
        bundle = build_deterministic_analysis_bundle(
            analysis(fields=("amount", "visits")), (dataset("current", raw, ctx),)
        )
        assert assign_fact_ids(bundle).model_dump() == bundle.model_dump()
        assert bundle.correlation_details[0].sample_count == 3
        bundles.append(bundle)
    left, right = bundles
    assert [m.total for m in left.metrics] == [m.total for m in right.metrics]
    assert {m.fact_id for m in left.metrics}.isdisjoint(m.fact_id for m in right.metrics)
    assert left.correlation_details[0].fact_id != right.correlation_details[0].fact_id
    for bundle in bundles:
        token = "{{value:" + bundle.correlation_details[0].fact_id + ":value:}}"
        selected = resolve_number_reference(
            token, [b.model_dump_json(by_alias=True) for b in bundles]
        )
        assert selected is not None and selected["scope"] == bundle.correlation_details[0].scope


@pytest.mark.parametrize(
    "scope",
    [
        {"region": "east;service=inpatient"},
        {"a=b": "c"},
        {"a": "b=c"},
        {"region": "x|y"},
        {"region": '"quoted"'},
        {"region": "line\nvalue"},
        {"region": "反斜杠\\分号;"},
        {"region": '["json",{}]'},
    ],
)
def test_scope_encoding_is_stable_for_order_and_preserves_frozen_legacy_ids(scope):
    import hashlib
    import json

    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.fact_index import (
        _scope_identity,
        assign_fact_ids,
        metric_fact_identity,
    )

    bundle = scoped({"region": "east", "service": "inpatient"})
    fact = bundle.metrics[0].model_copy(update={"scope": scope})
    bundle = assign_fact_ids(bundle.model_copy(update={"metrics": (fact,)}))
    reordered = fact.model_copy(update={"scope": dict(reversed(tuple(scope.items())))})
    assert metric_fact_identity(fact) == metric_fact_identity(reordered)
    # 模拟旧文件保存的 ID：读取和引用解析不重新签发，保留既有引用。
    old_scope = ";".join(f"{key}={scope[key]}" for key in sorted(scope))
    old_identity = metric_fact_identity(fact).replace(_scope_identity(scope), old_scope, 1)
    old_id = "fact-" + hashlib.sha256(old_identity.encode()).hexdigest()[:16]
    document = bundle.model_dump(mode="json", by_alias=True)
    document["metrics"][0]["factId"] = old_id
    raw = json.dumps(document)
    loaded = DeterministicAnalysisBundle.model_validate_json(raw)
    assert loaded.metrics[0].fact_id == old_id
    selected = resolve_number_reference("{{value:" + old_id + ":total:元}}", [raw])
    assert selected["value"] == 100 and selected["scope"] == scope
