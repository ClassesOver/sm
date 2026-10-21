"""R015/R032: arithmetic closure cannot establish a different population."""

from copy import deepcopy

import pytest

from smart_reporting.reporting.hospital_operation.finding_projection import (
    project_analysis_findings,
)
from smart_reporting.reporting.tests.test_group_share_assertions import group_bundle


@pytest.fixture
def decomposition_inputs():
    document = group_bundle().model_dump(mode="json", by_alias=True)
    metric = document["metrics"][0]
    item = {
        "name": "科室收入分解", "kind": "attribution", "directDecomposition": True,
        "reconciliationCode": "income_by_department", "sourceFactIds": [metric["factId"]],
        "metricCodes": metric["metricCodes"], "periodRoles": metric["periodRoles"],
        "periodStart": metric["periodStart"], "periodEnd": metric["periodEnd"],
        "unit": metric["unit"], "grain": ["department"], "scope": metric["scope"],
        "total": metric["total"], "components": [
            {"name": group["group"], "value": group["value"], "groupValues": group["groupValues"]}
            for group in metric["groupPopulation"]
        ],
    }
    evidence = {
        "analysisId": "analysis_001", "findings": [item],
        "reconciliations": [{
            "code": item["reconciliationCode"], "passed": True,
            "grain": item["grain"], "scope": item["scope"],
            "leftTotal": item["total"], "rightTotal": item["total"], "difference": 0,
        }],
    }
    return deepcopy((document, evidence))


def project(document, evidence):
    cards = project_analysis_findings(
        "analysis_001", document, evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_001",), fact_file_path="facts.json", fact_file_sha256="a" * 64,
        supplemental_file_path="supplement.json", supplemental_file_sha256="c" * 64,
    )
    return next(card for card in cards if any(
        ref.path == "supplement.json" and ref.pointer == "/findings/0" for ref in card.source_refs
    ))


@pytest.mark.parametrize("fault", [
    "period", "scope", "metric", "unit", "grain", "unknown_period", "unknown_unit",
    "top_only", "unknown_completeness", "missing_values", "duplicate_component",
    "split_source", "duplicate_fact", "unbound_reconciliation", "ambiguous_reconciliation",
    "hidden_zero_sum_groups", "row_count_as_amount",
    "infinite_component", "bool_component", "overflow_total", "missing_group_identity",
    "reconciliation_period", "rounding_only_closure",
    "bool_source_value",
])
def test_balanced_supplement_cannot_upgrade_incompatible_or_incomplete_source(decomposition_inputs, fault):
    document, evidence = decomposition_inputs
    metric = document["metrics"][0]
    item = evidence["findings"][0]
    if fault == "period":
        item["periodEnd"] = "2025-09"
    elif fault == "scope":
        item["scope"] = {"campus": "全院"}
        evidence["reconciliations"][0]["scope"] = item["scope"]
    elif fault == "metric":
        item["metricCodes"] = ["cost"]
    elif fault == "unit":
        item["unit"] = "万元"
    elif fault == "grain":
        item["grain"] = ["ward"]
        evidence["reconciliations"][0]["grain"] = item["grain"]
    elif fault == "unknown_period":
        for value in (metric, item):
            value.pop("periodStart", None)
            value.pop("periodEnd", None)
    elif fault == "unknown_unit":
        metric["unit"] = item["unit"] = None
    elif fault == "top_only":
        metric["groupPopulation"] = None
    elif fault == "unknown_completeness":
        metric["seriesMissingCount"] = None
    elif fault == "missing_values":
        metric["missingCount"] = 1
    elif fault == "duplicate_component":
        item["components"] = [deepcopy(item["components"][0])] * 2
        item["components"][0]["value"] = item["total"] / 2
    elif fault == "split_source":
        other = deepcopy(metric)
        other["factId"] = "fact-1111111111111111"
        other["total"] = 999
        metric["topGroups"] = []
        document["metrics"].append(other)
        item["sourceFactIds"].append(other["factId"])
    elif fault == "duplicate_fact":
        document["metrics"].append(deepcopy(metric))
    elif fault == "unbound_reconciliation":
        item["reconciliationCode"] = None
        evidence["reconciliations"][0]["code"] = None
    elif fault == "ambiguous_reconciliation":
        evidence["reconciliations"].append(deepcopy(evidence["reconciliations"][0]))
    elif fault == "hidden_zero_sum_groups":
        metric["groupPopulation"].extend([
            {"group": "遗漏正数", "value": 10, "groupValues": {"department": "遗漏正数"}},
            {"group": "遗漏负数", "value": -10, "groupValues": {"department": "遗漏负数"}},
        ])
    elif fault == "row_count_as_amount":
        metric["aggregation"] = "count"
    elif fault == "infinite_component":
        item["components"][0]["value"] = float("inf")
    elif fault == "bool_component":
        item["components"][0]["value"] = True
    elif fault == "overflow_total":
        item["total"] = 10 ** 400
    elif fault == "missing_group_identity":
        item["components"][0].pop("groupValues")
    elif fault == "reconciliation_period":
        evidence["reconciliations"][0]["periodEnd"] = "2025-09"
    elif fault == "rounding_only_closure":
        item["total"] += 1e-11
    elif fault == "bool_source_value":
        for collection in ("groupPopulation", "topGroups", "bottomGroups"):
            for group in metric[collection]:
                group["value"] = True if group["group"] == "内科" else 199
            metric[collection].sort(key=lambda group: group["value"], reverse=collection != "bottomGroups")
        for component in item["components"]:
            component["value"] = 1 if component["name"] == "内科" else 199
    card = project(document, evidence)
    assert card.evidence_level == "evidence_missing"
    assert card.actionability == "unknown"
    assert any("分解" in limitation for limitation in card.limitations)

    from smart_reporting.reporting.hospital_operation.findings import FindingGraph
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_narrative_planning_context,
    )

    context = build_narrative_planning_context(
        FindingGraph(snapshotHash="b" * 64, findings=(card,)), "分析变动来源",
    )
    assert context["findings"][0]["presentationPolicy"]["statementMode"] == "gap"


@pytest.mark.parametrize("reverse", [False, True])
def test_complete_same_basis_partition_is_direct_and_binds_both_frozen_sources(decomposition_inputs, reverse):
    document, evidence = decomposition_inputs
    if reverse:
        evidence["findings"][0]["components"].reverse()
    card = project(document, evidence)
    assert card.evidence_level == "direct_decomposition"
    assert card.actionability == "unknown"
    assert {(ref.path, ref.pointer) for ref in card.source_refs} == {
        ("supplement.json", "/findings/0"), ("facts.json", "/metrics/0"),
    }
    assert card.period_start == document["metrics"][0]["periodStart"]


def test_numeric_closure_does_not_certify_supplemental_causal_title(decomposition_inputs):
    document, evidence = decomposition_inputs
    evidence["findings"][0]["name"] = "已证实人员浪费导致亏损，必须压降人员"
    card = project(document, evidence)
    assert card.evidence_level == "direct_decomposition"
    assert card.title == "收入分组数值分解"
    assert "人员浪费" not in card.summary and "必须压降" not in card.summary
    assert "不证明分类归属或业务因果" in card.summary
