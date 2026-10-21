"""The supplied metric catalog controls names and purpose-based fact selection."""

import hashlib
from pathlib import Path

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.profile import (
    Capability,
    CapabilitySet,
    bind_reporting_profile_sources,
    build_outline_shape_view,
    load_configured_reporting_profiles,
    resolve_reporting_profile,
)
from smart_reporting.reporting.profile.metric_usage import (
    select_metrics_by_usage,
    usage_schema_candidates,
)
from smart_reporting.reporting.profile.models import EffectiveMetric
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.workflow.runtime.datasets import _analysis_context_payload
from smart_reporting.reporting.workflow.runtime.models import AnalysisItem


def hospital_profile():
    return bind_reporting_profile_sources(
        resolve_reporting_profile(load_configured_reporting_profiles(Path("deploy/agentos/reporting")), "ruijin"),
        {"rj": "rj"},
    )


def test_catalog_uses_all_confirmed_names_and_removes_the_requested_metric():
    expected = {
        "actual_medical_income": "医疗收入实际数", "actual_medicine_income": "药品收入实际数",
        "actual_material_income": "材料收入实际数", "actual_service_income": "医疗服务收入实际数",
        "actual_test_income": "检查化验收入实际数", "income_summary_total": "科室数据数",
        "budget_income": "医疗收入预算数", "budget_medicine_income": "药品收入实际数",
        "budget_material_income": "材料收入实际数", "budget_service_income": "医疗服务收入实际数",
        "budget_test_income": "检查化验收入实际数", "budget_person_time": "预算人次",
        "actual_person_time": "实际人次", "outpatient_visits": "门急诊人次", "discharges": "出院人次",
        "outpatient_visits_non": "门诊人次（不含体检和急诊）", "actual_open_bed": "开放床日数",
        "discharges_bed": "实际占用床日数", "budget_expenditure": "支出预算数",
        "actual_expenditure": "支出实际数", "total_cost": "科室成本数", "project_budget": "项目预算金额",
        "project_contract_amount": "项目合同金额", "project_payment_amount": "项目付款金额",
    }
    metrics = {metric.code: metric for metric in hospital_profile().metrics}
    assert {code: metric.description for code, metric in metrics.items()} == expected
    assert {metric.purpose for metric in metrics.values()} == {
        "预算或预实对比", "收入多维分析", "工作量分析", "成本多维分析", "项目预算分析",
    }
    assert all(metric.business_category for metric in metrics.values())
    assert metrics["budget_medicine_income"].business_category == "预算收入"
    assert metrics["actual_medicine_income"].business_category == "实际收入"
    assert metrics["budget_medicine_income"].field_ref != metrics["actual_medicine_income"].field_ref
    assert "discharges_non" not in metrics


def test_available_usage_groups_survive_actual_planner_projection():
    profile = hospital_profile()
    capabilities = CapabilitySet(effectiveProfileHash=profile.effective_profile_hash, capabilities=tuple(
        Capability(code=metric.code, kind="metric", available=metric.code != "actual_medical_income")
        for metric in profile.metrics
    ))
    view = build_outline_shape_view(profile, capabilities, (), (), ())
    projected = _analysis_context_payload(view)
    groups = {group["purpose"]: group["metricCodes"] for group in projected["metricUsageGroups"]}
    assert groups["收入多维分析"] == ["income_summary_total"]
    assert "actual_medical_income" not in groups["预算或预实对比"]
    assert "discharges_non" not in str(projected)
    assert projected["profile"]["metrics"][0]["purpose"] == "预算或预实对比"


def test_historical_metric_serialization_does_not_add_an_unconfirmed_purpose():
    metric = EffectiveMetric(code="income", kind="currency", description="原名称", aggregation="sum",
                             fieldRef="source.db.table.income")
    payload = metric.model_dump(mode="json", by_alias=True)
    assert not {"purpose", "businessCategory", "aliases"} & payload.keys()


def test_deleted_metric_cannot_return_through_raw_schema_measure_candidates():
    from copy import deepcopy

    metrics = tuple(metric.model_dump(mode="json", by_alias=True) for metric in hospital_profile().metrics)
    removed = "rj.rj.dm_hdc_gongzuoliang_view.mantime_discharges_non"
    schemas = [{"tables": [{"table": "rj.dm_hdc_gongzuoliang_view", "columns": [
        {"name": "mantime_discharges_non", "dataType": "DECIMAL"},
    ]}], "measureSemantics": [
        {"fieldRef": metrics[0]["fieldRef"]}, {"fieldRef": removed},
    ]}]
    before = deepcopy(schemas)
    view = usage_schema_candidates(schemas, metrics)
    assert view[0]["measureSemantics"] == [{"fieldRef": metrics[0]["fieldRef"]}]
    assert view[0]["tables"] == schemas[0]["tables"]
    assert schemas == before


def test_historical_profiles_keep_their_unclassified_candidates():
    schemas = [{"measureSemantics": [{"fieldRef": "source.db.table.value"}]}]
    assert usage_schema_candidates(schemas, ()) == schemas
    assert select_metrics_by_usage((), domain="income").allowed_field_refs is None


def test_ambiguous_budget_domain_requires_purpose_instead_of_using_ordinary_budget():
    metrics = tuple(metric.model_dump(mode="json", by_alias=True) for metric in hospital_profile().metrics)
    missing = select_metrics_by_usage(metrics, domain="budget")
    assert missing.metrics == () and missing.warnings
    project = select_metrics_by_usage(metrics, domain="budget", purposes=("项目预算分析",))
    assert {metric["code"] for metric in project.metrics} == {
        "project_budget", "project_contract_amount", "project_payment_amount",
    }
    ordinary = select_metrics_by_usage(metrics, domain="budget", purposes=("预算或预实对比",))
    assert ordinary.metrics and not ordinary.warnings
    assert not {metric["code"] for metric in project.metrics} & {metric["code"] for metric in ordinary.metrics}


@pytest.mark.parametrize("domain,expected", [
    ("income", {"income_summary_total"}),
    ("workload", {"outpatient_visits", "outpatient_visits_non", "discharges", "actual_open_bed", "discharges_bed"}),
    ("full_cost", {"total_cost"}),
])
def test_selection_uses_purpose_and_never_display_name(domain, expected):
    metrics = tuple(metric.model_dump(mode="json", by_alias=True) for metric in hospital_profile().metrics)
    selection = select_metrics_by_usage(metrics, domain=domain)
    assert {metric["code"] for metric in selection.metrics} == expected


@pytest.mark.parametrize("purposes,expected", [
    ((), {"income"}),
    (("收入多维分析", "工作量分析"), {"income", "visits"}),
    (("不存在的用途",), set()),
])
def test_fact_generation_excludes_other_purposes_and_deleted_fields_even_when_csv_contains_them(purposes, expected):
    fields = ("income", "budget_actual", "visits", "deleted")
    raw = b"month,department,income,budget_actual,visits,deleted\n2025-01,A,100,900,2,999\n2025-02,A,200,800,4,888\n"
    semantics = tuple(semantic(field, unit="元" if field != "visits" else "人次") for field in fields)
    ctx = context("current", fields=("month", "department", *fields), semantics=semantics,
                  sha256=hashlib.sha256(raw).hexdigest())
    metrics = tuple({
        "code": field, "kind": "currency", "description": "相同名称", "aggregation": "sum",
        "fieldRef": semantics[index]["fieldRef"], "purpose": purpose,
    } for index, (field, purpose) in enumerate(zip(fields, (
        "收入多维分析", "预算或预实对比", "工作量分析",
    ))))
    plan = analysis(fields=fields).model_copy(update={"metric_purposes": purposes})
    bundle = build_deterministic_analysis_bundle(plan, (("current", raw, ctx, ("current",)),),
                                                  profile_metrics=metrics)
    assert {fact.field for fact in bundle.metrics} == expected
    assert all(fact.display_name == "相同名称" for fact in bundle.metrics)
    assert all("deleted" not in (detail.left_field, detail.right_field) for detail in bundle.correlation_details)
    assert bundle.warnings


def test_explicit_purpose_survives_analysis_contract_roundtrip():
    item = AnalysisItem(code="income", domain="income", description="分析收入与工作量",
                        managementQuestion="次均收入如何变化", primaryMetricFamily="income",
                        requirementIds=["req_001"], metricPurposes=["收入多维分析", "工作量分析"])
    assert AnalysisItem.model_validate(item.model_dump(by_alias=True)).metric_purposes == (
        "收入多维分析", "工作量分析",
    )


def test_new_plans_with_usage_policy_must_route_explicitly_but_legacy_remains_readable():
    from pydantic import ValidationError

    item = dict(code="project", domain="budget", analysisName="项目执行分析",
                description="分析项目预算、合同、付款", managementQuestion="项目执行如何",
                primaryMetricFamily="project_budget", requirementIds=["req_001"],
                periodRoles=["current"], seriesGranularity=None)
    assert AnalysisItem.model_validate(item).metric_purposes == ()
    with pytest.raises(ValidationError, match="metricPurposes"):
        AnalysisItem.model_validate(item, context={"new_analysis_plan": True, "require_metric_purposes": True})
    valid = AnalysisItem.model_validate({**item, "metricPurposes": ["项目预算分析"]},
                                      context={"new_analysis_plan": True, "require_metric_purposes": True})
    assert valid.metric_purposes == ("项目预算分析",)
