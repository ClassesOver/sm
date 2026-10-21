"""Backportable pr80 frozen-fact reader, depending only on Pydantic and stdlib.

This is a read-only bridge, not a monkey patch or a workflow-resume adapter. The
caller supplies the original strict pr80 metric and bundle model classes. Only
four known schema additions are admitted; all other old validation remains.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from types import GenericAlias
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model

# Pin the old wire shape, rather than guessing which arbitrary model was given.
PR80_METRIC_FIELDS = frozenset(
    {
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
    }
)
PR80_BUNDLE_FIELDS = frozenset(
    {
        "version",
        "analysis_id",
        "analysis_name",
        "metrics",
        "derived_metrics",
        "comparisons",
        "reconciliations",
        "correlations",
        "correlation_details",
        "warnings",
    }
)
FACT_ARRAYS = (
    "metrics",
    "comparisons",
    "derived_metrics",
    "reconciliations",
    "correlation_details",
)
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


class _CumulativeSnapshotPolicy(BaseModel):
    # Kept local so copying this reader into pr80 never imports current code.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: Literal["1"] = "1"
    reset: Literal["calendar_year_zero"]
    observation: Literal["closed_month_end"]
    changes: Literal["signed_snapshot_delta"]


@dataclass(frozen=True)
class CompatibleFactModels:
    metric: type[BaseModel]
    bundle: type[BaseModel]


@lru_cache(maxsize=4)
def compatible_pr80_models(
    legacy_metric: type[BaseModel],
    legacy_bundle: type[BaseModel],
) -> CompatibleFactModels:
    """Explicit adapter construction never mutates the supplied model classes."""
    if (
        frozenset(legacy_metric.model_fields) != PR80_METRIC_FIELDS
        or legacy_metric.model_config.get("extra") != "forbid"
        or legacy_bundle.model_config.get("extra") != "forbid"
        or legacy_metric.model_fields["period_aggregation"].annotation != Literal["last"] | None
    ):
        raise ValueError("unsupported_legacy_metric_model")
    if frozenset(legacy_bundle.model_fields) != PR80_BUNDLE_FIELDS:
        raise ValueError("unsupported_legacy_bundle_model")
    metric_args = get_args(legacy_bundle.model_fields["metrics"].annotation)
    group_args = get_args(legacy_metric.model_fields["top_groups"].annotation)
    if (
        len(metric_args) != 2
        or metric_args != (legacy_metric, Ellipsis)
        or len(group_args) != 2
        or group_args[1] is not Ellipsis
        or not isinstance(group_args[0], type)
        or not issubclass(group_args[0], BaseModel)
        or set(group_args[0].model_fields) != {"group", "value", "group_values"}
        or group_args[0].model_config.get("extra") != "forbid"
    ):
        raise ValueError("unsupported_legacy_bundle_model")
    period = deepcopy(legacy_metric.model_fields["period_aggregation"])
    metric = create_model(
        "ReadCompatiblePr80Metric",
        __base__=legacy_metric,
        period_aggregation=(Literal["sum", "last"] | None, period),
        series_missing_count=(int | None, Field(default=None, alias="seriesMissingCount", ge=0)),
        group_population=(
            GenericAlias(tuple, (group_args[0], Ellipsis)) | None,
            Field(default=None, alias="groupPopulation", max_length=2000),
        ),
        cumulative_policy=(
            _CumulativeSnapshotPolicy | None,
            Field(default=None, alias="cumulativePolicy", exclude_if=lambda value: value is None),
        ),
    )
    metrics_field = deepcopy(legacy_bundle.model_fields["metrics"])
    bundle = create_model(
        "ReadCompatiblePr80Bundle",
        __base__=legacy_bundle,
        metrics=(GenericAlias(tuple, (metric, Ellipsis)), metrics_field),
    )
    return CompatibleFactModels(metric=metric, bundle=bundle)


@dataclass(frozen=True)
class CompatibleFactSnapshot:
    """Original bytes are the artifact; model dumps are never replacement files."""

    raw: bytes
    sha256: str
    required_features: tuple[str, ...]
    semantic_status: Literal["unknown"] = field(default="unknown", init=False)
    semantic_support_reused: Literal[False] = field(default=False, init=False)
    workflow_resume_supported: Literal[False] = field(default=False, init=False)

    @property
    def document(self) -> dict[str, Any]:
        # Each consumer gets its own view. Mutating it cannot alter verified bytes.
        return json.loads(
            self.raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("snapshot_duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise ValueError("snapshot_nonfinite_json_number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("snapshot_nonfinite_json_number")
    return number


def _assert_finite_tree(value):
    # Old Pydantic float fields may coerce strings such as "NaN" into floats.
    # Checking the validated model also covers nested groups/correlations.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("snapshot_nonfinite_model_number")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_finite_tree(item)


def read_compatible_snapshot(
    raw: bytes,
    models: CompatibleFactModels,
    *,
    expected_sha256: str,
    expected_size: int,
) -> CompatibleFactSnapshot:
    """Expected identity must come from an authorized manifest, never this file."""
    if (
        not isinstance(raw, bytes)
        or type(expected_size) is not int
        or not 0 <= expected_size <= MAX_SNAPSHOT_BYTES
        or len(raw) != expected_size
        or not isinstance(expected_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("snapshot_identity_mismatch")
    document = json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_nonfinite,
        parse_float=_finite_float,
    )
    if not isinstance(document, dict) or document.get("version", "1") != "1":
        raise ValueError("snapshot_version_unsupported")
    # Validate through the supplied pinned old reader plus exact known additions.
    # Keep the parsed original document: reserializing defaults changes identity.
    bundle = models.bundle.model_validate(document)
    _assert_finite_tree(bundle.model_dump(mode="python"))
    ids = set()
    for name in FACT_ARRAYS:
        for entry in getattr(bundle, name):
            fact_id = entry.fact_id
            if fact_id is not None:
                if fact_id in ids:
                    raise ValueError("snapshot_duplicate_fact_id")
                ids.add(fact_id)
    features = set()
    for metric in getattr(bundle, "metrics"):
        if metric.period_aggregation == "sum":
            features.add("period_aggregation_sum")
        if metric.series_missing_count is not None:
            features.add("series_missing_count")
        if metric.group_population is not None:
            features.add("complete_group_population")
        if metric.cumulative_policy is not None:
            features.add("cumulative_snapshot_policy")
    return CompatibleFactSnapshot(
        raw=raw,
        sha256=expected_sha256,
        required_features=tuple(sorted(features)),
    )


def main(argv=None) -> int:
    """Read-only backport probe; never changes a snapshot or deploys anything."""
    import argparse
    import importlib
    from pathlib import Path

    from pydantic import ValidationError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-module",
        default="smart_reporting.reporting.hospital_operation.deterministic_analysis",
    )
    parser.add_argument("--fact-file", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        module = importlib.import_module(args.legacy_module)
        models = compatible_pr80_models(
            module.DeterministicMetricFact, module.DeterministicAnalysisBundle
        )
        with Path(args.fact_file).open("rb") as stream:
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        snapshot = read_compatible_snapshot(
            raw, models, expected_sha256=args.expected_sha256, expected_size=args.expected_size
        )
        result = {
            "version": "1",
            "readCompatible": True,
            "sourceSha256": snapshot.sha256,
            "requiredFeatures": snapshot.required_features,
            "semanticStatus": snapshot.semantic_status,
            "semanticSupportReused": snapshot.semantic_support_reused,
            "workflowResumeSupported": snapshot.workflow_resume_supported,
            "rollbackReady": False,
        }
        code = 0
    except (ValidationError, ValueError, TypeError, ImportError, AttributeError, OSError):
        # Validation errors may contain source cell values. Do not expose them in
        # deployment diagnostics; no read failure makes a report undownloadable.
        result = {
            "version": "1",
            "readCompatible": False,
            "reason": "snapshot_unreadable_or_incompatible",
            "rollbackReady": False,
        }
        code = 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
