"""六域 DDL 指标的单位、期间边界和标准分组回归。"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.profile import (
    bind_reporting_profile_sources,
    load_configured_reporting_profiles,
    resolve_reporting_profile,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisCodingRequirement,
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    run_standard_supplemental,
    standard_computation_catalog,
)

# 预算数不凭 DATE 列猜测跨月可加；项目按年度快照，不相加跨年金额。
FIELDS = [
    ("dwd_hdc_income_summary_view", "indicator_value", "元", "sum"),
    ("dwd_hdc_cost_table_view", "indicator_value", "元", "sum"),
    *[("dm_hdc_gongzuoliang_view", field, unit, "sum") for field, unit in (
        ("mantime_outpatient", "人次"), ("mantime_discharges", "人次"),
        ("mantime_outpatient_non", "人次"), ("actual_open_bed", "床日"), ("discharges_bed", "床日"),
    )],
    *[("dwd_income_budget_view", f"{prefix}_{field}", "人次" if field == "person_time" else "元",
       "sum" if prefix == "actual" else None)
      for prefix in ("budget", "actual") for field in (
          "person_time", "medical_income", "medicine_income", "material_income", "service_income", "test_income",
      )],
    ("dwd_expenditure_budget_view", "actual_expenditure", "元", "sum"),
    ("dwd_expenditure_budget_view", "budget_expenditure", "元", None),
    *[("dwd_project_budget_view", field, "元", "last")
      for field in ("budget_project_amount", "contract_amount", "payment_amount")],
]


@pytest.mark.parametrize("table,field,unit,period_aggregation", FIELDS)
def test_six_domain_metrics_freeze_units_and_execute_only_safe_periods(table, field, unit, period_aggregation):
    profile = bind_reporting_profile_sources(resolve_reporting_profile(
        load_configured_reporting_profiles(Path("deploy/agentos/reporting")), "ruijin",
    ), {"rj": "rj"})
    ref = f"rj.rj.{table}.{field}"
    semantic = next((item for item in profile.measure_semantics if item.field_ref == ref), None)
    assert semantic is not None, f"六域指标缺少受信语义：{ref}"
    assert semantic.unit == unit
    period_field = "period_year" if table == "dwd_project_budget_view" else "data_date"
    periods = ("2024", "2025") if period_field == "period_year" else ("2025-01-01", "2025-02-01")
    grain = "year" if period_field == "period_year" else "month"
    csv = (f"{period_field},area,{field}\n{periods[0]},A,10\n{periods[0]},B,20\n"
           f"{periods[1]},A,40\n").encode()
    for selected in (periods, (periods[-1],), (periods[0],)):
        content = csv
        if period_aggregation is None and len(selected) == 1:
            # 未知预算口径的单期事实只能从实际单期输入冻结，不能借多期错误合计。
            lines = csv.decode().splitlines()
            content = (lines[0] + "\n" + "\n".join(
                line for line in lines[1:] if line.split(",")[0] in selected
            ) + "\n").encode()
        digest = hashlib.sha256(content).hexdigest()
        ctx = context("current", fields=(period_field, "area", field), semantics=(semantic.model_dump(
            mode="json", by_alias=True,
        ),), sha256=digest).model_copy(update={
            "numeric_fields": (field,), "organization_grain": ("area",),
            "time_series_sort_field": period_field, "period_granularities": {period_field: grain},
        })
        item = analysis(fields=(field,)).model_copy(update={
            "dataset_ids": ("current",), "organization_grain": ("area",), "periods": selected,
        })
        bundle = build_deterministic_analysis_bundle(item, (("current", content, ctx, ("current",)),))
        datasets = [{"datasetId": "current", "sha256": digest, "columns": list(ctx.fields)}]
        catalog = standard_computation_catalog(bundle, datasets, selected)
        summaries = [candidate for candidate in catalog["candidates"]
                     if candidate["standardComputation"]["operation"] == "group_summary"]
        if len(selected) > 1 and period_aggregation != "sum":
            assert summaries == []
            if period_aggregation is None:
                assert bundle.metrics == ()
                assert any("时间可加性未确认" in warning for warning in bundle.warnings)
            continue
        parent, = bundle.metrics
        assert parent.period_aggregation == period_aggregation
        assert parent.unit == unit
        candidate = next(candidate for candidate in summaries
                         if candidate["standardComputation"]["dimensionField"] == "area")
        requirement = AnalysisCodingRequirement(
            datasetId="current", fields=tuple(candidate["fields"]), calculation="按院区汇总登记期间指标",
            outputName="area_value", requiredColumns=candidate["outputColumns"],
            standardCandidateId=candidate["candidateId"],
        )
        state = SimpleNamespace(facts=bundle, instruction={
            "datasets": datasets, "currentAnalysis": {"datasetIds": ["current"], "periods": selected},
        }, decision=AnalysisEvidenceDecision(requiresSupplementalEvidence=True, reason="分组补证",
            missingFacts=("院区完整分组",), codingRequirements=(requirement,)))
        spec, = AnalysisItemWorkflow._standard_plan(state)
        total = 70 if len(selected) == 2 else 40 if selected == (periods[-1],) else 30
        result = run_standard_supplemental(analysis_id=item.analysis_id, dataset_ids=("current",),
            authorized_fields=ctx.fields, csv_content=content, request=StandardSupplementalRequest(
                **spec.model_dump(by_alias=True, exclude={
                    "parent_fact_id", "baseline_parent_fact_id", "denominator_parent_fact_id",
                }), datasetId="current", outputName="area_value",
                measureUnit=unit, parentTotal=total,
            ))
        assert result["findings"][0]["rows"] == (
            [["A", 50.0, 1, 5 / 7], ["B", 20.0, 2, 2 / 7]] if len(selected) == 2
            else [["A", 40.0, 1, 1.0]] if selected == (periods[-1],)
            else [["B", 20.0, 1, 2 / 3], ["A", 10.0, 2, 1 / 3]]
        )
        assert all(check["passed"] for check in result["reconciliations"])


def test_six_domain_semantics_cover_exactly_approved_metrics():
    profile = bind_reporting_profile_sources(resolve_reporting_profile(
        load_configured_reporting_profiles(Path("deploy/agentos/reporting")), "ruijin",
    ), {"rj": "rj"})
    assert {item.field_ref for item in profile.measure_semantics} == {item.field_ref for item in profile.metrics}
    assert len(profile.measure_semantics) == 24
    assert not any(item.field_ref.endswith(".mantime_discharges_non") for item in profile.measure_semantics)
