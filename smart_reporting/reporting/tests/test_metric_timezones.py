"""本地业务日边界显式转换为登记存储时区，不依赖数据库会话默认值。"""

from datetime import datetime
from decimal import Decimal

import pytest

from smart_reporting.reporting.contract import ModelColumn
from smart_reporting.reporting.semantics.models import MetricDefinition
from smart_reporting.reporting.tests.test_metric_compilation import (
    catalog,
    execute,
    policy,
    request,
)
from smart_reporting.reporting.tests.test_metric_compilation import warehouse as warehouse
from smart_reporting.reporting.tests.test_metric_execution import anyio_backend as anyio_backend
from smart_reporting.reporting.tests.test_metric_execution import (
    execution_context as execution_context,
)
from smart_reporting.reporting.tests.test_semantic_models import metric_payload


def timestamp_catalog():
    return tuple(table.model_copy(update={"columns": tuple(ModelColumn(name=column.name, dataType="DATETIME", nullable=False)
        if column.name == "period" else column for column in table.columns)}) for table in catalog())


def test_shanghai_month_is_half_open_in_utc_storage(warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    warehouse.execute("DROP TABLE test.budget")
    warehouse.execute("CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period TIMESTAMP)")
    warehouse.execute("INSERT INTO test.budget VALUES ('A',999,'2025-12-31 15:59:59'),('A',100,'2025-12-31 16:00:00'),('B',200,'2026-01-31 15:59:59'),('B',999,'2026-01-31 16:00:00')")
    metric = MetricDefinition.model_validate(metric_payload(timeZone="Asia/Shanghai", storageTimeZone="UTC"))
    plan = compile_metric(request(), policy(), (metric,), timestamp_catalog())
    assert plan.issues == ()
    assert execute(warehouse, plan.queries[0])[0]["value"] == Decimal(300)
    assert [item.value for item in plan.queries[0].parameters] == [datetime(2025, 12, 31, 16), datetime(2026, 1, 31, 16)]


def test_timestamp_without_registered_timezones_is_unavailable():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    metric = MetricDefinition.model_validate(metric_payload())
    plan = compile_metric(request(), policy(), (metric,), timestamp_catalog())
    assert plan.queries == ()
    assert [item.code for item in plan.issues] == ["metric_timezone_unknown"]


@pytest.mark.parametrize("changes", [{"timeZone": "Unknown/Place", "storageTimeZone": "UTC"}, {"timeZone": "Asia/Shanghai"}])
def test_invalid_or_incomplete_timezone_definition_is_rejected(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric_payload(**changes))


def test_dst_business_day_uses_calendar_boundaries_instead_of_fixed_24_hours():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    metric = MetricDefinition.model_validate(metric_payload(timeZone="America/New_York", storageTimeZone="UTC"))
    plan = compile_metric(request(period={"start": "2026-03-08", "end": "2026-03-09"}), policy(), (metric,), timestamp_catalog())
    assert plan.issues == ()
    assert [item.value for item in plan.queries[0].parameters] == [datetime(2026, 3, 8, 5), datetime(2026, 3, 9, 4)]


@pytest.mark.anyio
async def test_readiness_observed_dates_use_business_zone(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("DROP TABLE test.budget")
    warehouse.execute("CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period TIMESTAMP)")
    warehouse.execute("INSERT INTO test.budget VALUES ('A',100,'2025-12-31 16:00:00'),('B',200,'2026-01-31 15:59:59')")
    metric = MetricDefinition.model_validate(metric_payload(timeZone="Asia/Shanghai", storageTimeZone="UTC"))
    selected = policy(readinessPolicy={"expectedPeriods": [{"start": "2026-01-01", "end": "2026-02-01"}]})
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request(), selected, (metric,), timestamp_catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-tz")
    observed = receipt.readiness[0].observed_period
    assert observed.start.isoformat() == "2026-01-01" and observed.end.isoformat() == "2026-02-01"
