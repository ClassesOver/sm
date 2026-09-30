from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.contract import SourceSchemaSnapshot
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.profile import (
    bind_reporting_profile_sources,
    load_configured_reporting_profiles,
    resolve_reporting_profile,
)
from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.base import (
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY,
)

DIMENSIONS = (
    {
        "code": "department",
        "description": "院区",
        "fieldRefs": ["s.db.fact.department"],
    },
    {
        "code": "month",
        "description": "月份",
        "fieldRefs": ["s.db.fact.month"],
    },
)
METRICS = (
    {"code": "revenue", "aggregation": "sum", "fieldRef": "s.db.fact.revenue"},
    {"code": "visits", "aggregation": "sum", "fieldRef": "s.db.fact.visits"},
    {
        "code": "revenue_per_visit",
        "aggregation": "ratio",
        "numeratorMetric": "revenue",
        "denominatorMetric": "visits",
    },
    {"code": "balance", "aggregation": "sum", "fieldRef": "s.db.fact.balance"},
)
SEMANTICS = (
    {
        "fieldRef": "s.db.fact.revenue",
        "aggregation": "sum",
        "additiveAcross": ["department", "month"],
    },
    {
        "fieldRef": "s.db.fact.visits",
        "aggregation": "sum",
        "additiveAcross": ["department", "month"],
    },
    {
        "fieldRef": "s.db.fact.balance",
        "aggregation": "sum",
        "additiveAcross": ["department"],
    },
)


def metric(
    code: str,
    field: str,
    total: float,
    *,
    field_ref: str | None = None,
) -> dict:
    return {
        "datasetId": "dataset-drill01",
        "metricCodes": [code],
        "field": field,
        "fieldRef": field_ref or f"s.db.fact.{field}",
        "aggregation": "sum",
        "scope": {"scope": "current"},
        "periodField": "month",
        "periodStart": "2025-01",
        "periodEnd": "2025-02",
        "total": total,
        "unit": "元",
    }


def test_builder_freezes_base_ratio_and_semi_additive_capabilities() -> None:
    bundle = {
        "metrics": [
            metric("revenue", "revenue", 750),
            metric("visits", "visits", 53),
            metric("balance", "balance", 380),
        ],
        "derivedMetrics": [
            {
                "code": "revenue_per_visit",
                "numeratorMetric": "revenue",
                "denominatorMetric": "visits",
                "value": 750 / 53,
                "datasetIds": ["dataset-drill01"],
            }
        ],
    }

    result = build_drilldown_metrics(
        bundles=[bundle],
        dataset_columns={
            "dataset-drill01": (
                "department",
                "month",
                "revenue",
                "visits",
                "balance",
                "scope",
            )
        },
        profile_dimensions=DIMENSIONS,
        profile_metrics=METRICS,
        measure_semantics=SEMANTICS,
    )
    by_code = {item.metric_code: item for item in result}

    assert set(by_code) == {"revenue", "visits", "balance", "revenue_per_visit"}
    assert [item.code for item in by_code["revenue"].dimensions] == [
        "department",
        "month",
    ]
    assert by_code["balance"].aggregation == "semi_additive_last"
    assert [item.code for item in by_code["balance"].dimensions] == ["department"]
    assert by_code["revenue_per_visit"].numerator_field == "revenue"
    assert by_code["revenue_per_visit"].denominator_field == "visits"


def test_builder_skips_missing_dimensions_and_conflicting_facts() -> None:
    first = metric("revenue", "revenue", 750)
    conflicting = {**first, "total": 999}
    result = build_drilldown_metrics(
        bundles=[{"metrics": [first, conflicting]}],
        dataset_columns={"dataset-drill01": ("department", "revenue", "scope")},
        profile_dimensions=DIMENSIONS,
        profile_metrics=METRICS,
        measure_semantics=SEMANTICS,
    )

    assert result == ()


def test_builder_requires_additivity_or_row_preserving_inputs() -> None:
    average = {
        **metric("avg_visits", "visits", 10),
        "aggregation": "average",
        "metricCodes": ["avg_visits"],
    }
    non_additive = metric("revenue", "revenue", 750)
    profile_metrics = (*METRICS, {
        "code": "avg_visits",
        "aggregation": "average",
        "fieldRef": "s.db.fact.visits",
    })
    no_additivity = tuple(
        {**item, "additiveAcross": []}
        if item["fieldRef"] == "s.db.fact.revenue"
        else item
        for item in SEMANTICS
    )
    common = {
        "bundles": [{"metrics": [average, non_additive]}],
        "dataset_columns": {
            "dataset-drill01": (
                "department",
                "month",
                "revenue",
                "visits",
                "scope",
            )
        },
        "profile_dimensions": DIMENSIONS,
        "profile_metrics": profile_metrics,
        "measure_semantics": no_additivity,
    }

    assert build_drilldown_metrics(**common) == ()
    raw = build_drilldown_metrics(
        **common, row_preserving_dataset_ids=("dataset-drill01",)
    )
    assert [item.metric_code for item in raw] == ["avg_visits"]


def test_g7_capability_and_algorithm_matrix_uses_one_frozen_snapshot(
    tmp_path: Path,
) -> None:
    content = (
        b"department,month,revenue,visits,patient_id,balance,scope\n"
        b"A,2025-01,100,10,p1,100,current\n"
        b"A,2025-01,-20,5,p2,50,current\n"
        b"B,2025-01,200,10,p3,200,current\n"
        b"A,2025-02,120,12,p1,110,current\n"
        b"B,2025-02,240,12,p1,230,current\n"
        b",2025-02,40,4,p4,40,current\n"
        b"X,2025-02,999,1,p9,999,excluded\n"
    )
    path = tmp_path / "frozen.csv"
    path.write_bytes(content)
    dataset_id = "dataset-g7-matrix"
    columns = (
        "department",
        "month",
        "revenue",
        "visits",
        "patient_id",
        "balance",
        "scope",
    )
    profile_metrics = (
        {"code": "revenue", "aggregation": "sum", "fieldRef": "s.db.fact.revenue"},
        {"code": "visits", "aggregation": "sum", "fieldRef": "s.db.fact.visits"},
        {
            "code": "average_visits",
            "aggregation": "average",
            "fieldRef": "s.db.fact.visits",
        },
        {
            "code": "patient_count",
            "aggregation": "count_distinct",
            "fieldRef": "s.db.fact.patient_id",
        },
        {"code": "row_count", "aggregation": "count", "fieldRef": "s.db.fact.visits"},
        {"code": "balance", "aggregation": "sum", "fieldRef": "s.db.fact.balance"},
        {
            "code": "revenue_per_visit",
            "aggregation": "ratio",
            "numeratorMetric": "revenue",
            "denominatorMetric": "visits",
        },
    )

    def fact(code: str, field: str, aggregation: str, total: float) -> dict:
        return {
            "factId": f"fact-{code}",
            "datasetId": dataset_id,
            "metricCodes": [code],
            "field": field,
            "fieldRef": f"s.db.fact.{field}",
            "aggregation": aggregation,
            "scope": {"scope": "current"},
            "periodField": "month",
            "periodStart": "2025-01",
            "periodEnd": "2025-02",
            "total": total,
        }

    bundle = {
        "metrics": [
            fact("revenue", "revenue", "sum", 680),
            fact("visits", "visits", "sum", 53),
            fact("average_visits", "visits", "average", 53 / 6),
            fact("patient_count", "patient_id", "count_distinct", 4),
            fact("row_count", "visits", "count", 6),
            fact("balance", "balance", "sum", 380),
        ],
        "derivedMetrics": [
            {
                "factId": "fact-revenue-per-visit",
                "code": "revenue_per_visit",
                "numeratorMetric": "revenue",
                "denominatorMetric": "visits",
                "value": 680 / 53,
                "datasetIds": [dataset_id],
            }
        ],
    }
    declarations = build_drilldown_metrics(
        bundles=[bundle],
        dataset_columns={dataset_id: columns},
        profile_dimensions=DIMENSIONS,
        profile_metrics=profile_metrics,
        measure_semantics=SEMANTICS,
        row_preserving_dataset_ids=(dataset_id,),
    )
    by_code = {item.metric_code: item for item in declarations}
    assert set(by_code) == {
        "average_visits",
        "balance",
        "patient_count",
        "revenue",
        "revenue_per_visit",
        "row_count",
        "visits",
    }

    snapshot = TraceDatasetFile(
        dataset_id=dataset_id,
        local_path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        row_count=7,
    )
    service = TraceDrilldownService(secret=b"g7-matrix-secret")
    expected = {
        "revenue": 680.0,
        "revenue_per_visit": 680 / 53,
        "average_visits": 53 / 6,
        "patient_count": 4,
        "row_count": 6,
        "balance": 380.0,
    }
    for code, answer in expected.items():
        page = service.drilldown(
            snapshot,
            by_code[code],
            dimension_code="department",
            report_id="report-g7",
            revision=7,
        )
        assert page.observed_value == answer
        assert page.reconciled is True
        assert page.fixed_scope == (("scope", "current"),)
        assert page.period_start == "2025-01"
        assert page.period_end == "2025-02"

    # 没有行保留快照时，AVG/COUNT/COUNT DISTINCT 均不得被签发；保存一个
    # 聚合答案不能代替其权重、原始记录或去重标识。
    without_raw_rows = build_drilldown_metrics(
        bundles=[bundle],
        dataset_columns={dataset_id: columns},
        profile_dimensions=DIMENSIONS,
        profile_metrics=profile_metrics,
        measure_semantics=SEMANTICS,
    )
    assert {
        item.metric_code for item in without_raw_rows
    }.isdisjoint({"average_visits", "patient_count", "row_count"})


def test_g7_current_ruijin_profile_has_explicit_capability_for_all_metrics() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )
    dimensions_by_table: dict[str, list[str]] = {}
    for dimension in profile.dimensions:
        for field_ref in dimension.field_refs:
            dimensions_by_table.setdefault(field_ref.rsplit(".", 1)[0], []).append(
                field_ref.rsplit(".", 1)[1]
            )
    metrics_by_table: dict[str, list[object]] = {}
    for metric in profile.metrics:
        assert metric.field_ref is not None
        metrics_by_table.setdefault(metric.field_ref.rsplit(".", 1)[0], []).append(
            metric
        )

    tables = []
    semantics = []
    for table_ref, metrics in sorted(metrics_by_table.items()):
        source_id, database, table = table_ref.split(".")
        dimension_fields = tuple(dict.fromkeys(dimensions_by_table[table_ref]))
        assert dimension_fields, f"生产指标表缺少登记维度: {table_ref}"
        metric_fields = tuple(
            dict.fromkeys(metric.field_ref.rsplit(".", 1)[1] for metric in metrics)
        )
        tables.append(
            {
                "sourceId": source_id,
                "database": database,
                "name": table,
                "columns": [
                    {
                        "name": field,
                        "dataType": "DECIMAL(20,2)" if field in metric_fields else "VARCHAR",
                        "nullable": True,
                    }
                    for field in (*metric_fields, *dimension_fields)
                ],
            }
        )
        semantics.extend(
            {
                "fieldRef": metric.field_ref,
                "aggregation": metric.aggregation,
                "additiveAcross": list(dimension_fields),
            }
            for metric in metrics
        )
    snapshot = SourceSchemaSnapshot.model_validate(
        {
            "source": "metadata_api",
            "revision": "g7-production-profile",
            "schemaHash": "a" * 64,
            "tables": tables,
            "measureSemantics": semantics,
        }
    )
    dataset_columns = {}
    facts = []
    for metric in profile.metrics:
        assert metric.field_ref is not None
        table_ref, field = metric.field_ref.rsplit(".", 1)
        dataset_id = "dataset-" + hashlib.sha256(metric.code.encode()).hexdigest()[:16]
        dataset_columns[dataset_id] = (
            field,
            *dimensions_by_table[table_ref],
        )
        facts.append(
            {
                "factId": f"fact-{metric.code}",
                "datasetId": dataset_id,
                "metricCodes": [metric.code],
                "field": field,
                "fieldRef": metric.field_ref,
                "aggregation": metric.aggregation,
                "scope": {},
                "total": 1.0,
            }
        )
    profile_dimensions = [
        item.model_dump(mode="json", by_alias=True) for item in profile.dimensions
    ]
    profile_metrics = [
        item.model_dump(mode="json", by_alias=True) for item in profile.metrics
    ]
    semantic_payloads = [
        item.model_dump(mode="json", by_alias=True)
        for item in snapshot.measure_semantics
    ]

    declarations = build_drilldown_metrics(
        bundles=[{"metrics": facts}],
        dataset_columns=dataset_columns,
        profile_dimensions=profile_dimensions,
        profile_metrics=profile_metrics,
        measure_semantics=semantic_payloads,
    )

    assert len(profile.metrics) == 25
    assert {item.metric_code for item in declarations} == {
        item.code for item in profile.metrics
    }
    assert all(item.dimensions for item in declarations)
    without_first_semantic = build_drilldown_metrics(
        bundles=[{"metrics": facts}],
        dataset_columns=dataset_columns,
        profile_dimensions=profile_dimensions,
        profile_metrics=profile_metrics,
        measure_semantics=semantic_payloads[1:],
    )
    assert len(without_first_semantic) == 24
    assert semantic_payloads[0]["fieldRef"] not in {
        next(
            fact["fieldRef"]
            for fact in facts
            if fact["metricCodes"] == [item.metric_code]
        )
        for item in without_first_semantic
    }


@pytest.mark.anyio
async def test_publication_uses_confirmed_snapshot_semantics_not_static_profile() -> None:
    registry = load_configured_reporting_profiles(Path("deploy/agentos/reporting"))
    profile = bind_reporting_profile_sources(
        resolve_reporting_profile(registry, "ruijin"), {"rj": "rj"}
    )
    assert profile.measure_semantics == ()
    metric = next(item for item in profile.metrics if item.code == "actual_medical_income")
    assert metric.field_ref is not None
    table_ref, value_field = metric.field_ref.rsplit(".", 1)
    source_id, database, table = table_ref.split(".")
    dimension_ref = next(
        field_ref
        for dimension in profile.dimensions
        for field_ref in dimension.field_refs
        if field_ref.rsplit(".", 1)[0] == table_ref
    )
    dimension_field = dimension_ref.rsplit(".", 1)[1]
    snapshot = SourceSchemaSnapshot.model_validate(
        {
            "source": "metadata_api",
            "revision": "confirmed-semantics",
            "schemaHash": "b" * 64,
            "tables": [
                {
                    "sourceId": source_id,
                    "database": database,
                    "name": table,
                    "columns": [
                        {
                            "name": value_field,
                            "dataType": "DECIMAL(20,2)",
                            "nullable": True,
                        },
                        {
                            "name": dimension_field,
                            "dataType": "VARCHAR",
                            "nullable": True,
                        },
                    ],
                }
            ],
            "measureSemantics": [
                {
                    "fieldRef": metric.field_ref,
                    "aggregation": "sum",
                    "additiveAcross": [dimension_field],
                }
            ],
        }
    )
    dataset_id = "dataset-confirmed01"
    facts = json.dumps(
        {
            "metrics": [
                {
                    "factId": "fact-confirmed0000001",
                    "datasetId": dataset_id,
                    "metricCodes": [metric.code],
                    "field": value_field,
                    "fieldRef": metric.field_ref,
                    "aggregation": "sum",
                    "scope": {},
                    "total": 10.0,
                }
            ]
        }
    ).encode()
    identity = ArtifactFile(
        path="facts.json",
        mediaType="application/json",
        size=len(facts),
        sha256=hashlib.sha256(facts).hexdigest(),
    )

    async def read_file(*_args, **_kwargs):
        return facts

    state = {
        REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [
            {"datasetId": dataset_id, "fields": [value_field, dimension_field]}
        ],
        REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY: [],
    }
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(read_limited_regular_file=read_file)
    runtime._state = lambda _context: state
    runtime._scope = lambda _context: {"threadId": "thread-1"}
    runtime._profile = lambda _context: profile
    runtime._snapshots = lambda _context: (snapshot,)
    runtime._workflow_result = lambda _state: {"datasets": []}

    declarations = await runtime._build_drilldown_metrics(
        fact_files={"analysis_001": identity}, run_context=SimpleNamespace()
    )

    assert [item.metric_code for item in declarations] == [metric.code]
    runtime._snapshots = lambda _context: (
        snapshot.model_copy(update={"measure_semantics": ()}),
    )
    assert await runtime._build_drilldown_metrics(
        fact_files={"analysis_001": identity}, run_context=SimpleNamespace()
    ) == ()
