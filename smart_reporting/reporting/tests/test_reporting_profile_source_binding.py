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
