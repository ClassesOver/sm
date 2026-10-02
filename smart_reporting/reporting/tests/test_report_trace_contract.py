from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.trace_v1 import (
    TRACE_ERROR_HTTP_STATUS,
    FactRefV1,
    RevisionTraceIndexV1,
    canonical_json_bytes,
    resolve_fact,
    trace_index_sha256,
)
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    AnalysisFileIdentity,
    DatasetAnalysisContext,
    DetailedAnalysisItem,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)

FIXTURES = Path(__file__).parent / "fixtures" / "report_trace"
ANSWERS = json.loads((FIXTURES / "expected_answers.json").read_text(encoding="utf-8"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file(index: int, media_type: str, path: str, sha: str | None = None) -> dict[str, Any]:
    return {
        "resourceId": f"res_{index:032x}",
        "mediaType": media_type,
        "path": path,
        "size": 10,
        "sha256": sha or f"{index:064x}",
    }


def _context(dataset_id: str, content: bytes, scope: dict[str, str]) -> DatasetAnalysisContext:
    period = "2026-09" if dataset_id == "current" else "2026-08"
    return DatasetAnalysisContext(
        profileFile=AnalysisFileIdentity(
            path=f"profiles/{dataset_id}.json", size=1, sha256="a" * 64
        ),
        profileModelView={},
        profileEngineVersion="4.19.1",
        datasetId=dataset_id,
        path=f"datasets/{dataset_id}.csv",
        size=len(content),
        sha256=_sha(content),
        rowCount=2,
        columnCount=4,
        fields=("month", "campus", "income", "visits"),
        organizationGrain=("campus",),
        metricSemantics=tuple(
            {
                "fieldRef": f"dynamic_source.dynamic_db.dynamic_table.{field}",
                "aggregation": "sum",
                "additiveAcross": ["month", "campus"],
                "exclusiveScope": scope,
                "unit": unit,
            }
            for field, unit in (("income", "元"), ("visits", "人次"))
        ),
        numericFields=("income", "visits"),
        periodValues=(period,),
        timeSeriesSortField="month",
    )


def _bundle(scope: dict[str, str]) -> dict[str, Any]:
    current = (FIXTURES / "current_2026_09.csv").read_bytes()
    mom = (FIXTURES / "mom_2026_08.csv").read_bytes()
    analysis = DetailedAnalysisItem(
        analysisId="analysis_001",
        domain="income",
        managementQuestion="9 月收入、人次与次均的环比变化",
        primaryMetricFamily="收入",
        datasetIds=("current", "mom"),
        fields=("income", "visits"),
        metrics=("收入", "人次"),
        periods=("2026-09",),
        comparisonBasis=("mom",),
        organizationGrain=("campus",),
        actions=("汇总", "环比"),
        evidenceSummary="服务端复算",
        suggestedSection="收入分析",
        completionConditions=("固定指标可复算",),
    )
    bundle = build_deterministic_analysis_bundle(
        analysis,
        (
            ("current", current, _context("current", current, scope), ("current",)),
            ("mom", mom, _context("mom", mom, scope), ("mom",)),
        ),
        profile_metrics=(
            {"code": "income", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.income"},
            {"code": "visits", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits"},
            {
                "code": "income_per_visit",
                "aggregation": "ratio",
                "numeratorMetric": "income",
                "denominatorMetric": "visits",
            },
        ),
        profile_hash="c" * 64,
    )
    return bundle.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("scenario", ["R1", "R2"])
def test_fixture_bundle_matches_independent_answers(scenario: str) -> None:
    expected = ANSWERS["scenarios"][scenario]
    bundle = _bundle(expected["scope"])

    totals = {(item["datasetId"], item["field"]): item["total"] for item in bundle["metrics"]}
    for role in ("current", "mom"):
        assert totals[(role, "income")] == expected[role]["income"]
        assert totals[(role, "visits")] == expected[role]["visits"]
    ratios = {item["periodRole"]: item["value"] for item in bundle["derivedMetrics"]}
    assert ratios == {
        "current": expected["current"]["incomePerVisit"],
        "mom": expected["mom"]["incomePerVisit"],
    }
    comparisons = {item["field"]: item for item in bundle["comparisons"]}
    for field, answer in expected["momComparison"].items():
        assert comparisons[field]["comparisonType"] == "mom"
        assert comparisons[field]["change"] == answer["change"]
        assert comparisons[field]["changeRate"] == pytest.approx(answer["changeRatePercent"])
    assert bundle["warnings"] == []


def _index_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    fact_file = _file(9, "application/json", "facts/revision-1/analysis_001.json")
    current_csv = (FIXTURES / "current_2026_09.csv").read_bytes()
    mom_csv = (FIXTURES / "mom_2026_08.csv").read_bytes()
    pointer = {
        (item["datasetId"], item["field"]): f"/metrics/{index}"
        for index, item in enumerate(bundle["metrics"])
    }
    comparison_index = next(
        index for index, item in enumerate(bundle["comparisons"]) if item["field"] == "income"
    )
    return {
        "reportId": "report_r1",
        "revision": 1,
        "workflowRunId": "run_1",
        "markdownSha256": "d" * 64,
        "effectiveProfileHash": "c" * 64,
        "datasets": [
            {
                "datasetRefId": f"ds_{role}",
                "datasetId": role,
                "file": _file(i, "text/csv", f"datasets/{role}.csv", _sha(content)),
                "sourceType": "starrocks_materialized",
                "requirementId": "req_income",
                "periodRoles": [role],
                "queryWindowId": role,
                "rowCount": 2,
                "displayName": f"{role} 收入人次",
            }
            for i, (role, content) in enumerate((("current", current_csv), ("mom", mom_csv)), 1)
        ],
        "facts": [
            {
                "factRefId": f"fact_{role}_income",
                "analysisId": "analysis_001",
                "kind": "metric",
                "file": fact_file,
                "pointer": pointer[(role, "income")],
                "evidenceNature": "computed",
                "datasetRefIds": [f"ds_{role}"],
            }
            for role in ("current", "mom")
        ]
        + [
            {
                "factRefId": "fact_income_mom",
                "analysisId": "analysis_001",
                "kind": "comparison",
                "file": fact_file,
                "pointer": f"/comparisons/{comparison_index}",
                "evidenceNature": "computed",
                "datasetRefIds": [],
                "inputFactRefIds": ["fact_current_income", "fact_mom_income"],
            }
        ],
        "subjects": [
            {
                "subjectId": "subject_claim_income",
                "subjectType": "claim",
                "sectionCode": "income",
                "claimId": "claim_001",
                "subjectSha256": "e" * 64,
                "evidenceNature": "computed",
                "factRefIds": ["fact_current_income", "fact_income_mom"],
            }
        ],
    }


def test_fact_refs_resolve_exact_records_in_frozen_bundle() -> None:
    bundle = _bundle({})
    index = RevisionTraceIndexV1.model_validate(_index_payload(bundle))
    facts = {item.fact_ref_id: item for item in index.facts}

    current = resolve_fact(bundle, facts["fact_current_income"])
    comparison = resolve_fact(bundle, facts["fact_income_mom"])

    assert (current["datasetId"], current["field"], current["total"]) == ("current", "income", 3600)
    assert (comparison["currentTotal"], comparison["baselineTotal"]) == (3600, 3000)
    assert trace_index_sha256(index) == trace_index_sha256(
        RevisionTraceIndexV1.model_validate(_index_payload(bundle))
    )


def test_resolve_fact_rejects_unknown_pointer() -> None:
    ref = FactRefV1.model_validate(
        {
            "factRefId": "fact_x",
            "analysisId": "analysis_001",
            "kind": "metric",
            "file": _file(9, "application/json", "facts/a.json"),
            "pointer": "/metrics/99",
            "evidenceNature": "computed",
            "datasetRefIds": ["ds_current"],
        }
    )

    with pytest.raises(LookupError, match="fact_binding_unavailable"):
        resolve_fact(_bundle({}), ref)


@pytest.mark.parametrize(
    ("kind", "pointer"),
    [
        ("metric", "/warnings/0"),
        ("metric", "/metrics"),
        ("metric", "/metrics/-"),
        ("comparison", "/metrics/0"),
        ("metric", "metrics/0"),
        ("metric", "/metrics/~2"),
    ],
)
def test_fact_ref_pointer_is_limited_to_registered_collection(kind: str, pointer: str) -> None:
    with pytest.raises(ValidationError):
        FactRefV1.model_validate(
            {
                "factRefId": "fact_x",
                "analysisId": "analysis_001",
                "kind": kind,
                "file": _file(9, "application/json", "facts/a.json"),
                "pointer": pointer,
                "evidenceNature": "computed",
                "datasetRefIds": ["ds_current"],
            }
        )


def _mutated(mutate: Any) -> dict[str, Any]:
    payload = _index_payload(_bundle({}))
    mutate(payload)
    return payload


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda p: p["facts"][0].update(datasetRefIds=["ds_unknown"]), id="unknown-dataset"
        ),
        pytest.param(
            lambda p: p["subjects"][0].update(factRefIds=["fact_unknown"]), id="unknown-fact"
        ),
        pytest.param(
            lambda p: p["facts"][0].update(inputFactRefIds=["fact_income_mom"]), id="fact-cycle"
        ),
        pytest.param(
            lambda p: p["facts"][1].update(pointer=p["facts"][0]["pointer"]),
            id="duplicate-location",
        ),
        pytest.param(
            lambda p: p["datasets"][1]["file"].update(
                resourceId=p["datasets"][0]["file"]["resourceId"]
            ),
            id="resource-id-reused-for-other-file",
        ),
        pytest.param(
            lambda p: p["datasets"][0].update(sourceType="url_csv"), id="url-csv-without-filename"
        ),
        pytest.param(
            lambda p: p["datasets"][0]["file"].update(path="../other/report.csv"),
            id="path-escape",
        ),
        pytest.param(
            lambda p: p["subjects"][0].update(
                tableCell={"tableId": "t", "rowKey": "r", "columnKey": "c"}
            ),
            id="subject-two-locators",
        ),
        pytest.param(
            lambda p: p["subjects"][0].update(evidenceNature="interpretation", factRefIds=[]),
            id="interpretation-without-facts",
        ),
    ],
)
def test_trace_index_rejects_invalid_references(mutate: Any) -> None:
    with pytest.raises(ValidationError):
        RevisionTraceIndexV1.model_validate(_mutated(mutate))


def _computation(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "computationId": "comp_contribution",
        "analysisId": "analysis_001",
        "method": "net_increment_contribution",
        "methodVersion": "1",
        "parameters": {"group": "campus"},
        "inputFactRefIds": ["fact_current_income", "fact_mom_income"],
        "outputFactRefIds": ["fact_income_mom"],
        "verification": "not_checked",
        "reproducibility": "limited",
    }
    value.update(overrides)
    return value


def test_computation_records_reject_shared_producers_and_cycles() -> None:
    accepted = _mutated(lambda p: p.update(computations=[_computation()]))
    RevisionTraceIndexV1.model_validate(accepted)

    two_producers = _mutated(
        lambda p: p.update(computations=[_computation(), _computation(computationId="comp_other")])
    )
    cyclic = _mutated(
        lambda p: p.update(
            computations=[
                _computation(),
                _computation(
                    computationId="comp_back",
                    inputFactRefIds=["fact_income_mom"],
                    outputFactRefIds=["fact_current_income"],
                ),
            ]
        )
    )
    for payload in (two_producers, cyclic):
        with pytest.raises(ValidationError):
            RevisionTraceIndexV1.model_validate(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"inputFactRefIds": [], "inputDatasetRefIds": []},
        {"inputFactRefIds": ["fact_income_mom"]},
        {"reproducibility": "reproducible"},
        {"parameters": {"alpha": float("nan")}},
    ],
)
def test_computation_record_rejects_invalid_shapes(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RevisionTraceIndexV1.model_validate(
            _mutated(lambda p: p.update(computations=[_computation(**overrides)]))
        )


def test_chart_trace_requires_static_image_and_csv_plot_data() -> None:
    chart = {
        "chartId": "chart_001",
        "image": _file(20, "image/png", "charts/income.png"),
        "plotData": [_file(21, "text/csv", "charts/income.plot.csv")],
        "categoryColumn": "campus",
        "series": [{"name": "收入", "column": "income", "unit": "元"}],
        "datasetRefIds": ["ds_current"],
        "visualReviewStatus": "not_run",
    }
    RevisionTraceIndexV1.model_validate(_mutated(lambda p: p.update(charts=[chart])))

    for broken in (
        {**chart, "image": _file(20, "application/json", "charts/income.plotly.json")},
        {**chart, "plotData": [_file(21, "application/json", "charts/income.json")]},
        {**chart, "datasetRefIds": []},
    ):
        with pytest.raises(ValidationError):
            RevisionTraceIndexV1.model_validate(_mutated(lambda p, c=broken: p.update(charts=[c])))


def test_canonical_json_rejects_non_finite_and_is_order_independent() -> None:
    assert canonical_json_bytes({"b": 1, "a": "收入"}) == canonical_json_bytes(
        {"a": "收入", "b": 1}
    )
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("inf")})


def test_error_codes_have_fixed_http_mapping() -> None:
    assert TRACE_ERROR_HTTP_STATUS["source_missing"] == 404
    assert TRACE_ERROR_HTTP_STATUS["snapshot_integrity_failed"] == 409
    assert set(TRACE_ERROR_HTTP_STATUS.values()) <= {400, 403, 404, 409, 410, 422, 429}
