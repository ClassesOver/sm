"""Executable rollback risk probe for the pre-quality-workflow fact reader.

A passing probe detects the incompatibility; it does not claim a rollback passed.
"""

from copy import deepcopy
from typing import Literal

import pytest
from pydantic import ValidationError, create_model

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    AnalysisModel,
    DeterministicMetricFact,
)

from .test_trace_server_tables import _bundle

# Metric field names and period enum in pr80@743b7100, before this worktree.
_LEGACY_FIELDS = (
    "fact_id",
    "dataset_id",
    "dataset_sha256",
    "profile_hash",
    "period_roles",
    "metric_codes",
    "field",
    "field_ref",
    "display_name",
    "aliases",
    "aggregation",
    "period_aggregation",
    "unit",
    "formula",
    "scope",
    "period_field",
    "period_granularity",
    "period_start",
    "period_end",
    "total",
    "average",
    "minimum",
    "maximum",
    "missing_count",
    "period_missing_count",
    "zero_count",
    "negative_count",
    "period_values",
    "top_groups",
    "bottom_groups",
    "warnings",
)


def _old_reader():
    fields = {}
    for name in _LEGACY_FIELDS:
        field = deepcopy(DeterministicMetricFact.model_fields[name])
        annotation = Literal["last"] | None if name == "period_aggregation" else field.annotation
        fields[name] = (annotation, field)
    return create_model("Pr80MetricReader", __base__=AnalysisModel, **fields)


@pytest.mark.parametrize("fault", ["sum_enum", "series_field", "both"])
def test_pre_quality_fact_reader_rejects_new_semantics_instead_of_silently_downgrading(fault):
    metric = _bundle().metrics[0].model_dump(mode="json", by_alias=True)
    metric["periodAggregation"] = "sum" if fault in {"sum_enum", "both"} else None
    if fault == "sum_enum":
        metric.pop("seriesMissingCount", None)
    else:
        metric["seriesMissingCount"] = 0
    # Current reader accepts the new facts; the prior reader does not.
    assert DeterministicMetricFact.model_validate(metric)
    with pytest.raises(ValidationError):
        _old_reader().model_validate(metric)


def test_current_reader_preserves_historical_unknown_semantics_without_upgrading_identity():
    metric = _bundle().metrics[0].model_dump(mode="json", by_alias=True)
    metric.pop("seriesMissingCount", None)
    metric.pop("groupPopulation", None)
    metric["periodAggregation"] = None
    old = _old_reader().model_validate(metric)
    current = DeterministicMetricFact.model_validate(old.model_dump(mode="json", by_alias=True))
    assert current.period_aggregation is None
    assert current.series_missing_count is None
    assert current.fact_id == old.fact_id


def test_old_reader_does_not_silently_accept_a_new_complete_group_population():
    metric = _bundle().metrics[0].model_dump(mode="json", by_alias=True)
    metric.pop("seriesMissingCount", None)
    metric["periodAggregation"] = None
    assert metric["groupPopulation"]
    with pytest.raises(ValidationError):
        _old_reader().model_validate(metric)
