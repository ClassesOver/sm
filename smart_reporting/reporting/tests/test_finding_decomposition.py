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


@pytest.mark.parametrize("fault", ["unit", "scope", "ordinary"])
def test_full_warning_budget_keeps_mandatory_proof_boundary(decomposition_inputs, fault):
    document, evidence = decomposition_inputs
    item = evidence["findings"][0]
    if fault == "unit":
        item["unit"] = "万元"
    elif fault == "scope":
        item["scope"] = ["北院"]
    else:
        item.update(kind="impact", directDecomposition=False)
    evidence["warnings"] = [f"一般业务提醒{i}" for i in range(100)]
    card = project(document, evidence)
    assert card.evidence_level == "evidence_missing"
    expected = "尚未得到确定性验证" if fault == "ordinary" else "不能据此归因"
    assert any(expected in warning for warning in card.limitations)
    if fault == "scope":
        assert any("scope 格式无效" in warning for warning in card.limitations)
    assert len(card.limitations) <= 100


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("invalid_count", [0, 1, 100, 499])
@pytest.mark.parametrize("business_warning", [False, True])
@pytest.mark.parametrize("proof_fault", [None, "unit", "incomplete_population"])
async def test_freezing_mixed_supplements_preserves_independent_numeric_proof(
    decomposition_inputs, invalid_count, business_warning, proof_fault,
):
    import hashlib
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.hospital_operation.findings import FindingGraph
    from smart_reporting.reporting.profile.models import EffectiveMetric
    from smart_reporting.reporting.tests.test_deterministic_analysis import analysis
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity, ReportingCheckpoint
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
    from smart_reporting.reporting.workflow.runtime.base import (
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    )

    document, evidence = decomposition_inputs
    if proof_fault == "unit":
        evidence["findings"][0]["unit"] = "万元"
    elif proof_fault == "incomplete_population":
        document["metrics"][0]["groupPopulation"] = None
    evidence["findings"] = [{"name": "其他用途", "metricCodes": ["budget"], "value": 999}] * invalid_count + evidence["findings"]
    evidence["reconciliations"][0]["name"] = "完整分组对账"
    evidence["warnings"] = ["基础数据口径待核对"] if business_warning else []
    original = json.dumps(evidence).encode()
    fact_file = FileIdentity(path="facts.json", size=1, sha256="a" * 64)
    supplement = FileIdentity(path="supplement.json", size=len(original), sha256=hashlib.sha256(original).hexdigest())
    dataset_id = "dataset-url-abc0001"
    plan = DetailedAnalysisPlan(analyses=(analysis().model_copy(update={
        "dataset_ids": (dataset_id,), "metric_purposes": ("收入多维分析",),
    }),), datasetIds=(dataset_id,))
    metric = EffectiveMetric(code="income", kind="currency", description="收入", aggregation="sum",
                             fieldRef=document["metrics"][0]["fieldRef"], purpose="收入多维分析")
    saved = {}

    async def read_model(_thread, _identity, _model):
        return DeterministicAnalysisBundle.model_validate(document)

    async def read_bytes(_thread, _identity):
        return original

    async def write(_thread, path, content):
        assert path not in {fact_file.path, supplement.path}
        saved["graph"] = FindingGraph.model_validate_json(content)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    async def persist(_context, checkpoint):
        return checkpoint

    runtime = SimpleNamespace(
        _profile=lambda _: SimpleNamespace(metrics=(metric,)),
        _state=lambda _: {REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: plan.model_dump(by_alias=True)},
        _read_identity_model=read_model, _read_identity_bytes=read_bytes,
        _write_immutable_artifact=write, _persist_reporting_checkpoint=persist,
        _update_reporting_checkpoint=RuntimeAnalysisMixin._update_reporting_checkpoint,
        _merge_checkpoint_files=RuntimeAnalysisMixin._merge_checkpoint_files,
    )
    await RuntimeAnalysisMixin._restore_or_create_finding_graph(
        runtime, run_context=None,
        checkpoint=ReportingCheckpoint(revision=1, phase="analysis", outlineHash="d" * 64, profileCoverage=_coverage()),
        thread_id="thread", report_run_id="run", revision=1,
        fact_files={"analysis_001": fact_file},
        analysis_items={"analysis_001": {"analysisId": "analysis_001", "datasetIds": [dataset_id],
                                        "evidenceFiles": [supplement.model_dump(by_alias=True)]}},
        citation_bindings=(Citation(citationId="citation_001", datasetId=dataset_id,
                                   requirementId="requirement_001", snapshotHash="b" * 64),),
    )
    card = next(card for card in saved["graph"].findings if any(
        ref.path == supplement.path for ref in card.source_refs
    ))
    assert card.evidence_level == ("evidence_missing" if business_warning or proof_fault else "direct_decomposition")
    assert card.source_refs[0].pointer == f"/findings/{invalid_count}"
    assert card.source_refs[0].file_sha256 == supplement.sha256
    assert all("budget" not in card.metric_codes for card in saved["graph"].findings)
    if invalid_count:
        assert any("未用于正文" in issue for card in saved["graph"].findings for issue in card.limitations)
