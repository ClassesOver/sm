from __future__ import annotations

import json
from pathlib import Path

import pytest

from smart_reporting.reporting.profile import (
    bind_reporting_profile_sources,
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
        "sections": [
            {"code": code, "title": title}
            for code, title in (
                ("executive_summary", "执行摘要"),
                ("scope_and_methodology", "分析范围与方法"),
                ("key_findings", "关键发现"),
                ("limitations", "局限性"),
                ("recommendations", "建议"),
            )
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


def test_ruijin_profile包含工作量非住院口径权威指标定义() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )

    metrics = {item.code: item for item in profile.metrics}
    assert metrics["outpatient_visits_non"].field_ref == (
        "rj.rj.dm_hdc_gongzuoliang_view.mantime_outpatient_non"
    )
    assert metrics["discharges_non"].field_ref == (
        "rj.rj.dm_hdc_gongzuoliang_view.mantime_discharges_non"
    )
    assert metrics["outpatient_visits_non"].aggregation == "sum"
    assert metrics["discharges_non"].aggregation == "sum"


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
