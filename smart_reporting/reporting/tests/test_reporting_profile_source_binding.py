from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from smart_reporting.reporting.profile import (
    Capability,
    CapabilitySet,
    bind_reporting_profile_sources,
    build_outline_shape_view,
    load_configured_reporting_profiles,
    resolve_reporting_profile,
)


def _profile(tmp_path: Path, field_ref: str):
    root = tmp_path / "reporting_profiles"
    root.mkdir()
    payload = {
        "version": "1",
        "profileId": "test-profile",
        "revision": "1",
        "dimensions": [
            {
                "code": "period",
                "kind": "time",
                "fieldRefs": [field_ref],
            }
        ],
    }
    (root / "test-profile.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    registry = load_configured_reporting_profiles(tmp_path)
    return resolve_reporting_profile(registry, "test-profile")


def test_profile三段式字段引用按环境数据源补全数据库(tmp_path: Path) -> None:
    profile = _profile(tmp_path, "rj.dwd_income_budget_view.data_date")

    test_profile = bind_reporting_profile_sources(profile, {"rj": "dwd_test"})
    production_profile = bind_reporting_profile_sources(profile, {"rj": "dwd"})

    assert test_profile.dimensions[0].field_refs == (
        "rj.dwd_test.dwd_income_budget_view.data_date",
    )
    assert production_profile.dimensions[0].field_refs == (
        "rj.dwd.dwd_income_budget_view.data_date",
    )
    assert test_profile.effective_profile_hash != production_profile.effective_profile_hash


def test_profile旧四段式数据库与当前环境不一致时拒绝(tmp_path: Path) -> None:
    profile = _profile(tmp_path, "rj.rj.dwd_income_budget_view.data_date")

    with pytest.raises(ValueError, match="数据库与当前数据源不一致"):
        bind_reporting_profile_sources(profile, {"rj": "dwd"})


def test_profile字段引用未知数据源时拒绝(tmp_path: Path) -> None:
    profile = _profile(tmp_path, "unknown.dwd_income_budget_view.data_date")

    with pytest.raises(ValueError, match="引用了未选择的数据源"):
        bind_reporting_profile_sources(profile, {"rj": "dwd"})


def test_ruijin_profile包含收入汇总权威指标定义() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )

    metric = next(item for item in profile.metrics if item.code == "income_summary_total")
    assert metric.field_ref == "rj.rj.dwd_hdc_income_summary_view.indicator_value"
    assert metric.aggregation == "sum"


@pytest.mark.parametrize("table", ["dwd_hdc_income_summary_view", "dwd_hdc_cost_table_view"])
def test_ruijin_additive_semantics_produce_executable_standard_grouping(table):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )
    from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context
    from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
        StandardSupplementalRequest,
        run_standard_supplemental,
        standard_computation_catalog,
    )

    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"})
    semantic = next((item for item in profile.measure_semantics
                     if item.field_ref == f"rj.rj.{table}.indicator_value"), None)
    assert semantic is not None, f"{table} 缺少受信时间可加语义，标准补证目录会为空"
    csv = b"data_date,area,indicator_value\n2025-01-01,A,10\n2025-01-01,B,20\n2025-02-01,A,30\n"
    digest = hashlib.sha256(csv).hexdigest()
    ctx = context("current").model_copy(update={
        "fields": ("data_date", "area", "indicator_value"), "numeric_fields": ("indicator_value",),
        "metric_semantics": (semantic.model_dump(mode="json", by_alias=True),),
        "organization_grain": ("area",), "time_series_sort_field": "data_date",
        "period_granularities": {"data_date": "month"}, "sha256": digest,
    })
    item = analysis(fields=("indicator_value",)).model_copy(update={
        "dataset_ids": ("current",), "organization_grain": ("area",),
        "periods": ("2025-01", "2025-02"),
    })
    bundle = build_deterministic_analysis_bundle(item, (("current", csv, ctx, ("current",)),))
    parent, = bundle.metrics
    assert parent.period_aggregation == "sum"
    catalog = standard_computation_catalog(bundle, [{
        "datasetId": "current", "sha256": digest,
        "columns": ["data_date", "area", "indicator_value"],
    }], item.periods)
    assert catalog["groupingSources"]["totalItems"] == 1
    assert any(candidate["standardComputation"]["operation"] == "group_period_series"
               for candidate in catalog["candidates"])
    result = run_standard_supplemental(
        analysis_id=item.analysis_id, dataset_ids=("current",),
        authorized_fields=ctx.fields, csv_content=csv,
        request=StandardSupplementalRequest(
            operation="group_summary", datasetId="current", outputName="院区收入",
            measureField="indicator_value", measureUnit="元", dimensionField="area",
            periodField="data_date", periodGranularity="month",
            currentPeriods=("2025-01-01", "2025-02-01"), parentTotal=60,
        ),
    )
    finding = result["findings"][0]
    rows = [dict(zip(finding["columns"], row)) for row in finding["rows"]]
    assert {row["area"]: row["value"] for row in rows} == {"A": 40, "B": 20}


def test_ruijin_profile工作量排除口径与真实字段说明一致() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )

    metrics = {item.code: item for item in profile.metrics}
    assert metrics["outpatient_visits_non"].field_ref == (
        "rj.rj.dm_hdc_gongzuoliang_view.mantime_outpatient_non"
    )
    assert "discharges_non" not in metrics
    assert metrics["outpatient_visits_non"].aggregation == "sum"
    assert metrics["outpatient_visits_non"].description == "门诊人次（不含体检和急诊）"
    assert "不含体检和急诊门诊人次" in metrics["outpatient_visits_non"].aliases


def test_ruijin_profile覆盖收入预算取数指标() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )

    metrics = {item.code: item for item in profile.metrics}
    expected = {
        "budget_medicine_income": "rj.rj.dwd_income_budget_view.budget_medicine_income",
        "budget_material_income": "rj.rj.dwd_income_budget_view.budget_material_income",
        "budget_service_income": "rj.rj.dwd_income_budget_view.budget_service_income",
        "budget_test_income": "rj.rj.dwd_income_budget_view.budget_test_income",
        "actual_person_time": "rj.rj.dwd_income_budget_view.actual_person_time",
    }
    assert {code: metrics[code].field_ref for code in expected} == expected
    assert all(metrics[code].aggregation == "sum" for code in expected)


def test_ruijin_profile覆盖项目预算三个权威金额指标() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )

    metrics = {item.code: item for item in profile.metrics}
    expected = {
        "project_budget": "rj.rj.dwd_project_budget_view.budget_project_amount",
        "project_contract_amount": "rj.rj.dwd_project_budget_view.contract_amount",
        "project_payment_amount": "rj.rj.dwd_project_budget_view.payment_amount",
    }
    assert {code: metrics[code].field_ref for code in expected} == expected
    assert all(metrics[code].aggregation == "sum" for code in expected)


def test_提纲上下文只包含可用能力() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )
    capabilities = CapabilitySet(
        effectiveProfileHash=profile.effective_profile_hash,
        capabilities=(
            Capability(code="month", kind="dimension", available=True),
            Capability(
                code="year",
                kind="dimension",
                available=False,
                reasons=("报告期间没有数据: rj.rj.dwd_project_budget_view",),
            ),
        ),
    )

    context = build_outline_shape_view(profile, capabilities, (), (), ())

    assert [item["code"] for item in context["capabilities"]] == ["month"]
