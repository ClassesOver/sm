import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_deterministic_analysis import context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import (
    dataset,
    reconcile,
)
from smart_reporting.reporting.tests.test_trace_lineage_regressions import _scoped_ratio
from smart_reporting.reporting.tests.test_trace_server_tables import _Harness
from smart_reporting.reporting.trace.contracts_v1 import FactRefV1, derive_resource_id
from smart_reporting.reporting.trace.fact_service import resolve_fact
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin


def scoped_check(scope):
    content = b"month,department,actual,ledger\n2025-01,A,100,100\n2025-01,B,100,100\n"
    ctx = context(
        "current",
        fields=("month", "department", "actual", "ledger"),
        semantics=(
            semantic("actual", scope={"department": scope}, unit="元"),
            semantic("ledger", scope={"department": scope}, unit="元"),
        ),
    )
    return reconcile((dataset("current", content, ctx),))


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_reconciliation_keeps_its_actual_input_scope_after_assembly(reverse):
    left = scoped_check("A").model_copy(update={"analysis_id": "analysis_101"})
    right = scoped_check("B").model_copy(update={"analysis_id": "analysis_102"})
    assert left.metrics[0].fact_id != right.metrics[0].fact_id
    bundles = (right, left) if reverse else (left, right)
    files, identities, resources = {}, {}, {}
    for bundle in bundles:
        path = f"facts/{bundle.analysis_id}.json"
        raw = bundle.model_dump_json(by_alias=True).encode()
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
    for bundle, scope in ((left, "A"), (right, "B")):
        token = "{{value:" + bundle.reconciliations[0].fact_id + ":difference:元}}"
        text, refs, notices = render_bound_numbers(
            scope + "科对账差额" + token,
            [b.model_dump_json(by_alias=True) for b in bundles],
            key=scope,
        )
        assert len(refs) == 1 and not notices, (text, notices)
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
        actual = bindings[0].fact_refs[0]
        payload = resolve_fact(files["facts/" + actual.analysis_id + ".json"], actual)
        inputs = payload["inputFactRefs"]
        actual_scopes = [
            m.scope
            for b in bundles
            if b.analysis_id == actual.analysis_id
            for m in b.metrics
            if m.fact_id in {i["factId"] for i in inputs}
        ]
        assert actual.analysis_id == bundle.analysis_id, (scope, actual.analysis_id, actual_scopes)


def test_dimensioned_ratio_fact_details_display_the_raw_ratio():
    bundle = _scoped_ratio("A")
    fact = bundle.derived_metrics[0]
    payload = resolve_fact(
        bundle.model_dump_json(by_alias=True).encode(),
        FactRefV1(
            analysisId=bundle.analysis_id,
            fileResourceId="trf-" + "a" * 20,
            factKind="derived",
            jsonPointer="/derivedMetrics/0",
            factKey=fact.fact_id,
        ),
    )
    assert payload["displayValue"] == 10 and payload["displayUnit"] != "%", (
        payload["displayValue"],
        payload["displayUnit"],
    )


def test_dimensioned_ratio_does_not_register_invalid_percent_claim():
    bundle = _scoped_ratio("A")
    token = "{{value:" + bundle.derived_metrics[0].fact_id + ":percentage:%}}"
    text, refs, notices = render_bound_numbers(
        "人均收入为" + token, [bundle.model_dump_json(by_alias=True)], key="ratio"
    )
    assert not refs and notices, (text, refs, notices)


def test_scoped_reconciliation_control():
    for scope in ("A", "B"):
        bundle = scoped_check(scope)
        assert bundle.reconciliations[0].passed
        assert all(m.scope == {"department": scope} for m in bundle.metrics)


def test_dimensioned_ratio_raw_value_control():
    bundle = _scoped_ratio("A")
    token = "{{value:" + bundle.derived_metrics[0].fact_id + ":value:}}"
    text, refs, notices = render_bound_numbers(
        "人均收入为" + token, [bundle.model_dump_json(by_alias=True)], key="ratio-value"
    )
    assert text.endswith("10") and len(refs) == 1 and not notices


@pytest.mark.parametrize("scope", ["A", "B"])
def test_reconciliation_freezes_ordered_inputs_and_keeps_them_on_roundtrip(scope):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.fact_index import assign_fact_ids, fact_input_relations

    bundle = scoped_check(scope)
    fact = bundle.reconciliations[0]
    expected = tuple(metric.fact_id for metric in bundle.metrics)
    assert fact.input_fact_ids == expected
    assert assign_fact_ids(bundle).model_dump() == bundle.model_dump()
    loaded = DeterministicAnalysisBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
    assert fact_input_relations(loaded)[fact.fact_id] == expected
    # Even when another same-code metric exists, dependency expansion uses frozen IDs.
    other = scoped_check("B" if scope == "A" else "A")
    combined = bundle.model_copy(update={"metrics": bundle.metrics + other.metrics})
    payload = resolve_fact(
        combined.model_dump_json(by_alias=True).encode(),
        FactRefV1(
            analysisId=bundle.analysis_id,
            fileResourceId="trf-" + "a" * 20,
            factKind="reconciliation",
            jsonPointer="/reconciliations/0",
            factKey=fact.fact_id,
        ),
    )
    assert tuple(item["factId"] for item in payload["inputFactRefs"]) == expected


def legacy_check(bundle):
    import json

    from smart_reporting.reporting.trace.fact_index import reconciliation_fact_identity

    fact = bundle.reconciliations[0].model_copy(update={"input_fact_ids": ()})
    legacy_id = (
        "fact-" + hashlib.sha256(reconciliation_fact_identity(fact).encode()).hexdigest()[:16]
    )
    document = bundle.model_dump(mode="json", by_alias=True)
    document["reconciliations"][0].update(factId=legacy_id)
    document["reconciliations"][0].pop("inputFactIds")
    return json.dumps(document), legacy_id


def test_single_legacy_reconciliation_remains_readable():
    raw, fact_id = legacy_check(scoped_check("A"))
    token = "{{value:" + fact_id + ":difference:元}}"
    text, refs, notices = render_bound_numbers("对账差额为" + token, [raw], key="legacy")
    assert text.endswith("0元") and len(refs) == 1 and not notices
    payload = resolve_fact(
        raw.encode(),
        FactRefV1(
            analysisId="analysis_001",
            fileResourceId="trf-" + "a" * 20,
            factKind="reconciliation",
            jsonPointer="/reconciliations/0",
            factKey=fact_id,
        ),
    )
    assert len(payload["inputFactRefs"]) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_legacy_reconciliation_conflicting_scopes_never_cross_bind(reverse):
    bundles = (
        scoped_check("A").model_copy(update={"analysis_id": "analysis_101"}),
        scoped_check("B").model_copy(update={"analysis_id": "analysis_102"}),
    )
    contents, files, identities = [], {}, {}
    for bundle in reversed(bundles) if reverse else bundles:
        raw, fact_id = legacy_check(bundle)
        contents.append(raw)
        path = f"facts/{bundle.analysis_id}.json"
        files[path] = raw.encode()
        identities[bundle.analysis_id] = FileIdentity(
            path=path, size=len(files[path]), sha256=hashlib.sha256(files[path]).hexdigest()
        )
    token = "{{value:" + fact_id + ":difference:元}}"
    text, refs, notices = render_bound_numbers(
        "A科对账差额为" + token, contents, key="legacy-conflict"
    )
    assert "待核实" in text and not refs and notices
    _, _, directory, _ = await RuntimeSectionsMixin._build_server_tables(
        _Harness(files),
        SimpleNamespace(),
        checkpoint=SimpleNamespace(deterministic_fact_files=identities),
        outline=SimpleNamespace(sections=()),
    )
    assert fact_id not in directory


@pytest.mark.parametrize(
    "numerator_unit,denominator_unit,expected,percentage",
    [
        ("元", "人次", 10, None),
        ("万元", "人次", 10, None),
        ("床日", "人次", 10, None),
        ("元", None, 10, None),
        ("元", "元", 10, 1000),
        ("元", "万元", 0.001, 0.1),
        ("万元", "元", 100000, 10000000),
        ("人次", "万人次", 0.001, 0.1),
        ("%", "%", 10, 1000),
        (None, None, 10, 1000),
    ],
)
@pytest.mark.parametrize("denominator", [0, 10])
def test_ratio_percentage_requires_compatible_dimensions(
    numerator_unit, denominator_unit, expected, percentage, denominator
):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )
    from smart_reporting.reporting.tests.test_deterministic_analysis import analysis
    from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import metrics
    from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog

    fields = ("numerator_value", "denominator_value")
    raw = f"month,department,numerator_value,denominator_value\n2025-01,A,100,{denominator}\n".encode()
    ctx = context(
        "current",
        fields=("month", "department", *fields),
        semantics=(
            semantic(fields[0], unit=numerator_unit),
            semantic(fields[1], unit=denominator_unit),
        ),
    )
    definitions = metrics(*fields) + (
        {
            "code": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": fields[0],
            "denominatorMetric": fields[1],
        },
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=fields), (dataset("current", raw, ctx),), profile_metrics=definitions
    )
    fact = bundle.derived_metrics[0]
    if denominator == 0:
        assert fact.value is fact.percentage is None
    else:
        assert fact.value == pytest.approx(expected)
        assert (
            fact.percentage is None
            if percentage is None
            else fact.percentage == pytest.approx(percentage)
        )
    payload = resolve_fact(
        bundle.model_dump_json(by_alias=True).encode(),
        FactRefV1(
            analysisId=bundle.analysis_id,
            fileResourceId="trf-" + "a" * 20,
            factKind="derived",
            jsonPointer="/derivedMetrics/0",
            factKey=fact.fact_id,
        ),
    )
    assert payload["displayValue"] == (
        fact.percentage if fact.percentage is not None else fact.value
    )
    token = "{{value:" + fact.fact_id + ":percentage:%}}"
    assert (token in frozen_number_catalog([bundle.model_dump_json(by_alias=True)])) == (
        fact.percentage is not None
    )
