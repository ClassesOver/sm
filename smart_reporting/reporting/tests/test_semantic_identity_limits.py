"""API先拒绝超过存储长度的标识，不能等到PG写入后变成500。"""

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.semantics.models import MetricDefinition
from smart_reporting.reporting.tests.test_semantic_models import metric_payload


def test_metric_id_that_exceeds_database_limit_is_rejected_before_persistence():
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric_payload("m" * 129))
