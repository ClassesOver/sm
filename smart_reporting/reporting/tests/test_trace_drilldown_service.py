from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import DrilldownMetricV1
from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService

CSV = """department,month,revenue,visits,patient_id,balance,zero_denominator,scope
A,2025-01,100,10,p1,100,0,current
A,2025-01,50,5,p2,50,0,current
B,2025-01,200,10,p3,200,0,current
A,2025-02,120,12,p1,110,0,current
B,2025-02,240,12,p1,230,0,current
,2025-02,40,4,p4,40,0,current
X,2025-02,999,1,p9,999,0,excluded
"""


@pytest.fixture
def snapshot(tmp_path: Path) -> TraceDatasetFile:
    path = tmp_path / "snapshot.csv"
    content = CSV.encode()
    path.write_bytes(content)
    return TraceDatasetFile(
        dataset_id="dataset-drill01",
        local_path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        row_count=7,
    )


def declaration(aggregation: str, **values: object) -> DrilldownMetricV1:
    payload: dict[str, object] = {
        "metricCode": f"metric_{aggregation}",
        "datasetId": "dataset-drill01",
        "aggregation": aggregation,
        "dimensions": [{"code": "department", "field": "department"}],
        "fixedScope": {"scope": "current"},
        "expectedValue": values.pop("expectedValue", None),
        **values,
    }
    return DrilldownMetricV1.model_validate(payload)


def run(snapshot: TraceDatasetFile, item: DrilldownMetricV1, **values: object):
    return TraceDrilldownService(secret=b"b7-secret").drilldown(
        snapshot,
        item,
        dimension_code=str(values.pop("dimension_code", "department")),
        report_id=str(values.pop("report_id", "report-1")),
        revision=int(values.pop("revision", 1)),
        **values,
    )


def row_map(page) -> dict[str, float | int | None]:
    return dict(page.rows)


def test_sum_uses_registered_scope_and_reconciles(snapshot: TraceDatasetFile) -> None:
    page = run(
        snapshot,
        declaration("sum", valueField="revenue", expectedValue=750.0),
    )

    assert row_map(page) == {"A": 270.0, "B": 440.0, "（空值）": 40.0}
    assert page.observed_value == 750.0
    assert page.reconciled is True
    payload = page.to_payload()
    assert payload["snapshot"] == {
        "datasetId": snapshot.dataset_id,
        "sha256": snapshot.sha256,
    }
    assert payload["scope"] == {
        "kind": "registered_snapshot",
        "fixed": {"scope": "current"},
        "period": None,
    }
    assert payload["calculation"] == {
        "aggregation": "sum",
        "description": "按登记范围对数值求和",
    }


def test_average_is_recomputed_not_average_of_group_averages(
    snapshot: TraceDatasetFile,
) -> None:
    page = run(
        snapshot,
        declaration("average", valueField="visits", expectedValue=53 / 6),
    )

    assert row_map(page) == {"A": 9.0, "B": 11.0, "（空值）": 4.0}
    assert page.observed_value == pytest.approx(53 / 6)
    assert page.reconciled is True


def test_count_distinct_uses_identifier_and_independent_total(
    snapshot: TraceDatasetFile,
) -> None:
    page = run(
        snapshot,
        declaration(
            "count_distinct", valueField="patient_id", expectedValue=4.0
        ),
    )

    # p1 同时存在于 A/B；组值不能相加冒充总体去重人数。
    assert row_map(page) == {"A": 2, "B": 2, "（空值）": 1}
    assert page.observed_value == 4
    assert page.reconciled is True


def test_ratio_uses_summed_numerator_and_denominator(
    snapshot: TraceDatasetFile,
) -> None:
    page = run(
        snapshot,
        declaration(
            "ratio",
            numeratorField="revenue",
            denominatorField="visits",
            expectedValue=750 / 53,
        ),
    )

    assert row_map(page)["A"] == 10.0
    assert row_map(page)["B"] == 20.0
    assert row_map(page)["（空值）"] == 10.0
    assert page.observed_value == pytest.approx(750 / 53)
    assert page.reconciled is True


def test_ratio_zero_denominator_returns_null_instead_of_infinity(
    snapshot: TraceDatasetFile,
) -> None:
    page = run(
        snapshot,
        declaration(
            "ratio",
            numeratorField="revenue",
            denominatorField="zero_denominator",
        ),
    )

    assert row_map(page) == {"A": None, "B": None, "（空值）": None}
    assert page.observed_value is None
    assert page.reconciled is None


def test_semi_additive_uses_one_latest_snapshot_period(
    snapshot: TraceDatasetFile,
) -> None:
    page = run(
        snapshot,
        declaration(
            "semi_additive_last",
            valueField="balance",
            periodField="month",
            expectedValue=380.0,
        ),
    )

    assert row_map(page) == {"A": 110.0, "B": 230.0, "（空值）": 40.0}
    assert page.observed_value == 380.0
    assert page.reconciled is True


def test_missing_input_and_unregistered_dimension_are_rejected(
    snapshot: TraceDatasetFile,
) -> None:
    with pytest.raises(ReportingError, match="未登记此下钻维度") as unavailable:
        run(
            snapshot,
            declaration("sum", valueField="revenue"),
            dimension_code="month",
        )
    assert unavailable.value.code == "drilldown_unavailable"

    missing = declaration("sum", valueField="not_in_snapshot")
    with pytest.raises(ReportingError, match="缺少下钻所需登记字段") as absent:
        run(snapshot, missing)
    assert absent.value.code == "drilldown_unavailable"


def test_cursor_is_stable_and_bound_to_revision_and_metric(
    snapshot: TraceDatasetFile,
) -> None:
    item = declaration("sum", valueField="revenue")
    first = run(snapshot, item, limit=1)
    assert first.next_cursor
    second = run(snapshot, item, limit=1, cursor=first.next_cursor)

    assert first.rows == (("A", 270.0),)
    assert second.rows == (("B", 440.0),)
    with pytest.raises(ReportingError) as replay:
        run(snapshot, item, limit=1, cursor=first.next_cursor, revision=2)
    assert replay.value.code == "cursor_invalid"


def test_contract_rejects_time_dimension_for_semi_additive() -> None:
    with pytest.raises(ValueError, match="不能沿期间维度"):
        DrilldownMetricV1.model_validate(
            {
                "metricCode": "balance",
                "datasetId": "dataset-drill01",
                "aggregation": "semi_additive_last",
                "valueField": "balance",
                "periodField": "month",
                "dimensions": [{"code": "month", "field": "month"}],
            }
        )
