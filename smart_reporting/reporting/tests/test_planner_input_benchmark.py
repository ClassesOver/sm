from copy import deepcopy

from scripts.benchmark_planner_input import build_variants, select_winner, validate_plan
from scripts.validate_planner_benchmark import assess_results


def sample_payload():
    return {
        "reportGoal": "收入预算与收入分析",
        "domains": ["income", "budget"],
        "periodWindows": {"windows": [{"role": "current"}, {"role": "yoy"}]},
        "analysisContext": {
            "profile": {
                "dimensions": [{"code": "area", "kind": "organization", "description": "院区",
                                "fieldRefs": ["rj.rj.income.area"]}],
                "metrics": [{"code": "income", "fieldRef": "rj.rj.income.amount",
                             "purpose": "收入多维分析", "description": "收入",
                             "numeratorMetric": None, "denominatorMetric": None}],
            },
            "capabilities": [{"code": "income", "kind": "metric", "available": True, "reasons": []}],
            "metricUsageGroups": [{"purpose": "收入多维分析", "metricCodes": ["income"]}],
            "terms": [{"name": "预算执行率", "description": "实际执行金额/全年预算金额"}],
            "observedDataFacts": [{"sourceId": "rj", "table": "rj.income", "periodRowCount": 0}],
        },
        "schemas": [{
            "tables": [{"sourceId": "rj", "table": "rj.income", "periodColumn": "date",
                        "periodGranularity": "date", "columns": [
                            {"name": "amount", "dataType": "DECIMAL(10,0)", "description": "收入"},
                            {"name": "area", "dataType": "VARCHAR(255)", "description": "院区"},
                            {"name": "date", "dataType": "DATE", "description": "日期"},
                        ]}],
            "measureSemantics": [{"fieldRef": "rj.rj.income.amount", "unit": "元",
                                  "aggregation": "sum", "additiveAcross": [],
                                  "exclusiveScope": {"income_nature": "开单收入"}}],
        }],
    }


def test_variants_preserve_scope_unknown_additivity_zero_rows_and_original_input():
    original = sample_payload()
    frozen = deepcopy(original)
    variants = build_variants(original)
    assert original == frozen
    assert variants["baseline"] == frozen
    table = variants["table_grouped"]["tables"][0]
    assert table["observedDataFacts"]["periodRowCount"] == 0
    amount = next(item for item in table["columns"] if item["name"] == "amount")
    assert amount["measureSemantic"]["exclusiveScope"] == {"income_nature": "开单收入"}
    assert amount["measureSemantic"]["additiveAcross"] == []
    assert amount["metrics"][0]["code"] == "income"
    assert amount["metrics"][0]["capability"]["available"] is True
    assert table["columns"][1]["dimensions"][0]["code"] == "area"
    assert variants["table_grouped"]["terms"][0]["description"] == "实际执行金额/全年预算金额"


def test_grouped_input_retains_unbound_profile_fields_and_unmatched_usage_groups():
    original = sample_payload()
    original["analysisContext"]["profile"]["metrics"].append(
        {"code": "project_budget", "fieldRef": "rj.rj.project.amount", "purpose": "项目预算分析"}
    )
    original["analysisContext"]["metricUsageGroups"].append(
        {"purpose": "特殊用途", "metricCodes": ["income"]}
    )
    variants = build_variants(original)
    assert variants["table_grouped"]["unboundMetrics"][0]["code"] == "project_budget"
    assert variants["conservative"]["analysisContext"]["metricUsageGroups"][-1]["purpose"] == "特殊用途"


def test_invalid_fields_and_undeclared_metric_purposes_are_not_scored_as_valid():
    plan = {
        "analyses": [{"code": "a1", "analysisName": "收入同比", "domain": "income",
                      "description": "比较收入", "managementQuestion": "收入如何变化？",
                      "primaryMetricFamily": "收入", "requirementIds": ["r1"],
                      "periodRoles": ["current", "yoy"], "seriesGranularity": "month",
                      "metricPurposes": ["收入多维分析"]}],
        "requirements": [{"requirementId": "r1", "sourceId": "rj",
                          "tables": [{"table": "rj.income", "periodColumn": "date",
                                      "periodGranularity": "date", "measureColumns": ["forged_amount"]}],
                          "dimensionColumns": ["area"], "grainColumns": ["area"], "relations": []}],
    }
    issues = validate_plan(plan, sample_payload())["issues"]
    assert any("forged_amount" in issue for issue in issues)
    plan["requirements"][0]["tables"][0]["measureColumns"] = ["amount"]
    plan["analyses"][0]["metricPurposes"] = []
    assert any("metricPurposes" in issue for issue in validate_plan(plan, sample_payload())["issues"])


def test_selection_never_trades_quality_for_smaller_input_or_ignores_failed_runs():
    summaries = [
        {"variant": "baseline", "passRate": 1.0, "qualityScore": 95, "inputTokens": 1000, "seconds": 10},
        {"variant": "conservative", "passRate": 1.0, "qualityScore": 95, "inputTokens": 800, "seconds": 9},
        {"variant": "table_grouped", "passRate": 0.5, "qualityScore": 100, "inputTokens": 400, "seconds": 4},
    ]
    assert select_winner(summaries) == "conservative"
    summaries[1]["qualityScore"] = 90
    assert select_winner(summaries) == "baseline"


def test_semantic_focus_frontloads_only_existing_constraints_and_shares_dimension_meanings():
    variants = build_variants(sample_payload())
    focused = variants["semantic_focus"]
    assert focused["businessRules"]["terms"][0]["description"] == "实际执行金额/全年预算金额"
    assert focused["businessRules"]["fixedScopes"] == [
        {"fieldRef": "rj.rj.income.amount", "exclusiveScope": {"income_nature": "开单收入"}}
    ]
    assert focused["dimensionDefinitions"][0]["description"] == "院区"
    assert focused["tables"][0]["columns"][1]["dimensions"] == ["area"]
    assert focused["tables"][0]["columns"][0]["measureSemantic"]["additiveAcross"] == []


def test_conservative_focus_keeps_physical_schema_and_frontloads_required_scope():
    original = sample_payload()
    value = build_variants(original)["conservative_focus"]
    assert value["schemas"][0]["tables"] == original["schemas"][0]["tables"]
    assert value["businessRules"]["fixedScopes"][0]["exclusiveScope"] == {"income_nature": "开单收入"}
    assert value["analysisContext"]["profile"]["metrics"][0]["fieldRef"] == "rj.rj.income.amount"


def test_explicit_scope_comprehension_precedes_noisy_reviewer_scores():
    summaries = [
        {"variant": "baseline", "passRate": 1.0, "qualityScore": 70, "scopeUnderstood": False, "inputTokens": 1000, "seconds": 10},
        {"variant": "conservative", "passRate": 1.0, "qualityScore": 72, "scopeUnderstood": False, "inputTokens": 800, "seconds": 9},
        {"variant": "conservative_focus", "passRate": 1.0, "qualityScore": 68, "scopeUnderstood": True, "inputTokens": 810, "seconds": 10},
    ]
    assert select_winner(summaries) == "conservative_focus"


def test_assess_results_accepts_complete_baseline_and_reports_candidate_warnings():
    results = {
        "manifest": {
            "inputSha256": "a" * 64,
            "repetitions": 2,
        },
        "summaries": [
            {"variant": "baseline", "passRate": 1.0},
            {"variant": "candidate", "passRate": 0.5},
        ],
        "runs": [
            {"variant": "baseline", "error": None, "validation": {"valid": True}},
            {"variant": "baseline", "error": None, "validation": {"valid": True}},
            {"variant": "candidate", "error": None, "validation": {"valid": False}},
            {"variant": "candidate", "error": None, "validation": {"valid": True}},
        ],
        "reviews": [{}, {}],
    }

    assessment = assess_results(results, expected_input_sha256="a" * 64)

    assert assessment["valid"] is True
    assert assessment["errors"] == []
    assert any("candidate" in warning for warning in assessment["warnings"])


def test_assess_results_rejects_baseline_errors_and_identity_mismatch():
    results = {
        "manifest": {"inputSha256": "b" * 64, "repetitions": 1},
        "summaries": [{"variant": "baseline", "passRate": 0.0}],
        "runs": [{"variant": "baseline", "error": {"type": "TimeoutError"},
                  "validation": {"valid": False}}],
        "reviews": [{}],
    }

    assessment = assess_results(results, expected_input_sha256="a" * 64)

    assert assessment["valid"] is False
    assert any("inputSha256" in error for error in assessment["errors"])
    assert any("baseline" in error for error in assessment["errors"])
