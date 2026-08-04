from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentos_dev.coding.reporting.contract import (
    ModelColumn,
    ModelTable,
    ReportPeriod,
    SourceSchemaSnapshot,
    schema_hash,
)
from agentos_dev.coding.reporting.data_source import DataShape, QueryResult
from agentos_dev.coding.reporting.profile import (
    ReportingProfileRegistry,
    build_outline_shape_view,
    collect_reconciliation_shapes,
    load_configured_reporting_profiles,
    resolve_capabilities,
    resolve_reporting_profile,
)


def _write_profile(root, relative: str, payload: dict[str, Any]) -> None:
    path = root / "reporting_profiles" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _documents(root) -> ReportingProfileRegistry:
    _write_profile(
        root,
        "base.json",
        {
            "version": "1",
            "profileId": "base",
            "revision": "1",
            "sections": [
                {"code": "executive_summary", "title": "执行摘要", "required": True},
                {
                    "code": "scope_and_methodology",
                    "title": "分析范围与方法",
                    "required": True,
                },
                {"code": "key_findings", "title": "关键发现", "required": True},
                {"code": "limitations", "title": "局限性", "required": True},
                {"code": "recommendations", "title": "建议", "required": True},
                {"code": "legacy", "title": "旧章节", "required": False},
            ],
        },
    )
    _write_profile(
        root,
        "hospitals/hospital-a.json",
        {
            "version": "1",
            "profileId": "hospital-a",
            "revision": "2",
            "extends": ["base"],
            "pageLayout": {
                "headerRight": "{title} · 医院 A",
                "footerLeft": "内部管理资料",
            },
            "dimensions": [
                {
                    "code": "month",
                    "kind": "time",
                    "fieldRefs": [
                        "operations.reporting.income.month",
                        "operations.reporting.budget.month",
                    ],
                }
            ],
            "metrics": [
                {
                    "code": "actual",
                    "kind": "amount",
                    "aggregation": "sum",
                    "fieldRef": "operations.reporting.income.amount",
                },
                {
                    "code": "budget",
                    "kind": "amount",
                    "aggregation": "sum",
                    "fieldRef": "operations.reporting.budget.amount",
                },
                {
                    "code": "achievement",
                    "kind": "ratio",
                    "aggregation": "ratio",
                    "numeratorMetric": "actual",
                    "denominatorMetric": "budget",
                },
            ],
            "reconciliations": [
                {
                    "code": "actual-vs-budget",
                    "leftMetric": "actual",
                    "rightMetric": "budget",
                    "grain": ["month"],
                    "absoluteTolerance": 1,
                    "relativeTolerance": 0.01,
                }
            ],
            "sections": [
                {"code": "executive_summary", "title": "医院管理摘要"},
                {"code": "legacy", "enabled": False},
                {
                    "code": "budget-analysis",
                    "title": "预算分析",
                    "required": True,
                    "requiredCapabilities": ["achievement", "actual-vs-budget"],
                },
            ],
        },
    )
    return load_configured_reporting_profiles(root)


def _snapshot_and_shape(*, include_budget: bool = True):
    table_names = ("income", "budget") if include_budget else ("income",)
    tables = tuple(
        ModelTable(
            sourceId="operations",
            database="reporting",
            name=name,
            columns=(
                ModelColumn(name="month", dataType="DATE", nullable=False),
                ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
            ),
        )
        for name in table_names
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash(tables),
        tables=tables,
    )
    shape = DataShape.model_validate(
        {
            "sourceId": "operations",
            "metadataRevision": "m1",
            "schemaHash": snapshot.schema_hash,
            "statisticsVersion": "1",
            "queryCount": 1,
            "periodStart": "2025-01-01",
            "periodEnd": "2025-12-31",
            "tables": [
                {
                    "sourceId": "operations",
                    "database": "reporting",
                    "table": name,
                    "totalRowCount": 2,
                    "periodRowCount": 2,
                    "outsidePeriodRowCount": 0,
                    "periodNullCount": 0,
                    "firstEffectiveDate": "2025-01-01",
                    "lastEffectiveDate": "2025-02-01",
                    "columnCount": 2,
                    "periodGranularity": "date",
                    "periodCoverage": ["2025-01", "2025-02"],
                    "missingPeriods": [],
                    "columns": [
                        {
                            "name": column,
                            "dataType": data_type,
                            "nullable": nullable,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 2,
                            "distinctMode": "exact",
                            "cardinalityRate": 1,
                            "unique": True,
                        }
                        for column, data_type, nullable in (
                            ("month", "DATE", False),
                            ("amount", "DECIMAL(18,2)", True),
                        )
                    ],
                }
                for name in table_names
            ],
        }
    )
    return snapshot, shape


def test_profile显式继承按code覆盖停用且hash稳定(tmp_path):
    registry = _documents(tmp_path)

    first = resolve_reporting_profile(registry, "hospital-a")
    second = resolve_reporting_profile(registry, "hospital-a")

    assert [item.profile_id for item in first.layers] == ["base", "hospital-a"]
    assert [item.code for item in first.sections] == [
        "executive_summary",
        "scope_and_methodology",
        "key_findings",
        "limitations",
        "recommendations",
        "budget-analysis",
    ]
    assert first.sections[0].title == "医院管理摘要"
    assert first.page_layout.header_left == "上海鼎医信息技术有限公司"
    assert first.page_layout.header_right == "{title} · 医院 A"
    assert first.page_layout.footer_left == "内部管理资料"
    assert first.page_layout.footer_right == "第 {page} / {pages} 页"
    assert first.effective_profile_hash == second.effective_profile_hash
    tampered = first.model_dump(mode="json", by_alias=True)
    tampered["sections"][0]["title"] = "被修改"
    with pytest.raises(ValueError, match="effectiveProfileHash"):
        type(first).model_validate(tampered)


def test_profile指标语义按field_ref继承覆盖并进入有效hash(tmp_path):
    base_sections = [
        {"code": "executive_summary", "title": "执行摘要"},
        {"code": "scope_and_methodology", "title": "分析范围与方法"},
        {"code": "key_findings", "title": "关键发现"},
        {"code": "limitations", "title": "局限性"},
        {"code": "recommendations", "title": "建议"},
    ]
    field_ref = "operations.reporting.income.amount"
    _write_profile(
        tmp_path,
        "base.json",
        {
            "version": "1",
            "profileId": "base",
            "revision": "1",
            "measureSemantics": [{"fieldRef": field_ref, "aggregation": "sum"}],
            "sections": base_sections,
        },
    )
    _write_profile(
        tmp_path,
        "hospital.json",
        {
            "version": "1",
            "profileId": "hospital",
            "revision": "2",
            "extends": ["base"],
            "measureSemantics": [{"fieldRef": field_ref, "aggregation": "average"}],
        },
    )

    registry = load_configured_reporting_profiles(tmp_path)
    base = resolve_reporting_profile(registry, "base")
    hospital = resolve_reporting_profile(registry, "hospital")

    assert hospital.measure_semantics[0].aggregation == "average"
    assert hospital.effective_profile_hash != base.effective_profile_hash


def test_部署默认profile覆盖医院院区条线和模板分层():
    root = Path(__file__).resolve().parents[4] / "deploy" / "agentos" / "reporting"
    registry = load_configured_reporting_profiles(root)

    assert set(registry.documents) == {
        "base",
        "ruijin",
        "ruijin-north",
        "finance",
        "monthly-operation",
        "budget-execution",
    }
    ruijin = resolve_reporting_profile(registry, "ruijin")
    north = resolve_reporting_profile(registry, "ruijin-north")
    finance = resolve_reporting_profile(registry, "finance")
    monthly = resolve_reporting_profile(registry, "monthly-operation")

    assert [item.profile_id for item in ruijin.layers] == ["base", "ruijin"]
    assert len(ruijin.dimensions) == 12
    assert ruijin.metrics == ()
    assert ruijin.measure_semantics == ()
    assert all(
        not item.required
        for item in ruijin.sections
        if item.code
        in {"income_and_budget", "cost_and_expenditure", "project_budget", "service_workload"}
    )
    assert north.scope_filters[0].value == "北部院区"
    assert north.scope_filters[0].required_for_all_tables is True
    assert "service_workload" not in {item.code for item in finance.sections}
    assert [item.code for item in monthly.sections][-3:] == [
        "key_findings",
        "limitations",
        "recommendations",
    ]


def test_不同医院profile在同一契约下解析出不同章节(tmp_path):
    registry = _documents(tmp_path)
    _write_profile(
        tmp_path,
        "hospitals/hospital-b.json",
        {
            "version": "1",
            "profileId": "hospital-b",
            "revision": "1",
            "extends": ["base"],
            "sections": [
                {"code": "executive_summary", "title": "分院执行摘要"},
            ],
        },
    )
    registry = load_configured_reporting_profiles(tmp_path)

    hospital_a = resolve_reporting_profile(registry, "hospital-a")
    hospital_b = resolve_reporting_profile(registry, "hospital-b")

    assert hospital_a.sections[0].title == "医院管理摘要"
    assert hospital_b.sections[0].title == "分院执行摘要"
    assert hospital_a.effective_profile_hash != hospital_b.effective_profile_hash


def test_profile拒绝连接字段和循环继承(tmp_path):
    _write_profile(
        tmp_path,
        "bad.json",
        {
            "version": "1",
            "profileId": "bad",
            "revision": "1",
            "password": "secret",
        },
    )
    with pytest.raises(ValueError, match="连接字段"):
        load_configured_reporting_profiles(tmp_path)

    other = tmp_path / "cycle"
    for profile_id, parent in (("a", "b"), ("b", "a")):
        _write_profile(
            other,
            f"{profile_id}.json",
            {
                "version": "1",
                "profileId": profile_id,
                "revision": "1",
                "extends": [parent],
                "sections": [{"code": "summary", "title": "摘要"}],
            },
        )
    with pytest.raises(ValueError, match="循环"):
        resolve_reporting_profile(load_configured_reporting_profiles(other), "a")


def test_profile页面格式拒绝未知占位符和缺少页码(tmp_path):
    for profile_id, page_layout in (
        ("unknown", {"headerLeft": "{organization}"}),
        ("no-pages", {"footerRight": "第 {page} 页", "footerLeft": ""}),
    ):
        root = tmp_path / profile_id
        _write_profile(
            root,
            "profile.json",
            {
                "version": "1",
                "profileId": profile_id,
                "revision": "1",
                "pageLayout": page_layout,
                "sections": [
                    {"code": "executive_summary", "title": "执行摘要"},
                    {"code": "scope_and_methodology", "title": "范围"},
                    {"code": "key_findings", "title": "发现"},
                    {"code": "limitations", "title": "限制"},
                    {"code": "recommendations", "title": "建议"},
                ],
            },
        )
        with pytest.raises(ValueError):
            registry = load_configured_reporting_profiles(root)
            resolve_reporting_profile(registry, profile_id)


def test_capability由snapshot和datashape确定性缩小(tmp_path):
    profile = resolve_reporting_profile(_documents(tmp_path), "hospital-a")
    snapshot, shape = _snapshot_and_shape(include_budget=False)

    capabilities = resolve_capabilities(profile, (snapshot,), (shape,)).by_code()

    assert capabilities["actual"].available is True
    assert capabilities["budget"].available is False
    assert capabilities["achievement"].available is False
    assert capabilities["actual-vs-budget"].available is False
    assert capabilities["budget-analysis"].available is False


def test_提纲上下文保留事实但不携带完整列画像(tmp_path):
    profile = resolve_reporting_profile(_documents(tmp_path), "hospital-a")
    snapshot, shape = _snapshot_and_shape()
    capabilities = resolve_capabilities(profile, (snapshot,), (shape,))

    context = build_outline_shape_view(profile, capabilities, (snapshot,), (shape,), ())

    assert context["profile"]["sections"]
    assert context["capabilities"]
    assert context["tables"] == [
        {
            "sourceId": "operations",
            "table": f"reporting.{name}",
            "description": "",
            "periodRowCount": 2,
            "periodGranularity": "date",
            "periodCoverage": ["2025-01", "2025-02"],
            "missingPeriods": [],
        }
        for name in ("income", "budget")
    ]
    assert all("columns" not in table for table in context["tables"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("period_granularity", "expected_bounds"),
    [
        ("date", ("'20250101'", "'20251231'")),
        ("month", ("'202501'", "'202512'")),
        ("year", ("'2025'", "'2025'")),
    ],
)
async def test_reconciliation按profile共同粒度和期间语义聚合并输出差异(
    tmp_path, period_granularity, expected_bounds
):
    profile = resolve_reporting_profile(_documents(tmp_path), "hospital-a")
    snapshot, shape = _snapshot_and_shape()
    capabilities = resolve_capabilities(profile, (snapshot,), (shape,))

    queries: list[str] = []

    class Adapter:
        async def query(self, sql: str) -> QueryResult:
            queries.append(sql)
            if "`income`" in sql:
                return QueryResult(("g0", "metric_value"), (("2025-01", 120), ("2025-02", 80)), 10)
            return QueryResult(("g0", "metric_value"), (("2025-01", 100), ("2025-03", 90)), 10)

    shapes = await collect_reconciliation_shapes(
        profile,
        capabilities,
        adapters={"operations": Adapter()},
        period_semantics={
            ("operations", "reporting.income"): ("month", period_granularity),
            ("operations", "reporting.budget"): ("month", period_granularity),
        },
        period=ReportPeriod(start="2025-01-01", end="2025-12-31"),
    )

    assert shapes[0].status == "completed"
    assert shapes[0].left_total == "200"
    assert shapes[0].right_total == "190"
    assert shapes[0].common_key_count == 1
    assert shapes[0].left_only_key_count == 1
    assert shapes[0].right_only_key_count == 1
    assert all("SUBSTRING(REPLACE(REPLACE(CAST(`month` AS CHAR)" in sql for sql in queries)
    assert all(expected_bounds[0] in sql and expected_bounds[1] in sql for sql in queries)
