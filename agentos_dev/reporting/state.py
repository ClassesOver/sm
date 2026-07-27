from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from typing import Any

from ..report_data_sources import REPORT_DATASET_HANDLES_STATE_KEY, DatasetHandle
from .models import ReportingError, ReportSourceBinding

REPORT_SOURCE_BINDING_STATE_KEY = "report_source_binding"
REPORT_OUTLINE_STATE_KEY = "report_outline"
REPORT_ANALYSIS_PLAN_STATE_KEY = "report_analysis_plan"
REPORT_REVIEW_STATE_KEY = "report_review_state"
REPORT_ARTIFACTS_STATE_KEY = "report_artifacts"
_DOWNSTREAM_KEYS = (
    REPORT_OUTLINE_STATE_KEY,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_DATASET_HANDLES_STATE_KEY,
    REPORT_REVIEW_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    "report_delivery",
    "report_jobs",
)


def bind_report_source(state: MutableMapping[str, Any], binding: ReportSourceBinding) -> bool:
    """保存来源；来源范围或元数据变化时原子清空所有下游状态。"""

    serialized = binding.public_dict()
    previous = state.get(REPORT_SOURCE_BINDING_STATE_KEY)
    changed = _binding_identity(previous) != _binding_identity(serialized)
    if changed:
        for key in _DOWNSTREAM_KEYS:
            state.pop(key, None)
    state[REPORT_SOURCE_BINDING_STATE_KEY] = serialized
    return changed


def _binding_identity(value: Any) -> tuple[Any, ...] | None:
    if not isinstance(value, dict):
        return None
    return tuple(
        json_value(value.get(key))
        for key in (
            "bindingId",
            "sourceMode",
            "database",
            "allowedTables",
            "metadataFingerprint",
            "threadId",
            "userId",
            "sessionId",
        )
    )


def json_value(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def require_current_binding(
    state: MutableMapping[str, Any], *, binding_id: str, metadata_fingerprint: str
) -> ReportSourceBinding:
    raw = state.get(REPORT_SOURCE_BINDING_STATE_KEY)
    try:
        binding = ReportSourceBinding.model_validate(raw)
    except Exception as error:
        raise ReportingError("source_binding_missing", "报表来源尚未绑定。") from error
    if binding.binding_id != binding_id or binding.metadata_fingerprint != metadata_fingerprint:
        raise ReportingError("source_binding_stale", "报表来源已经变化，请重新开始。")
    return binding


def validate_hybrid_lineage(
    handles: Sequence[DatasetHandle], expected_binding_ids: Sequence[str]
) -> None:
    expected = set(expected_binding_ids)
    if not handles or not expected:
        raise ReportingError("dataset_lineage_incomplete", "混合来源血缘不完整。")
    actual: set[str] = set()
    for handle in handles:
        binding_id = handle.provenance.get("bindingId")
        if not isinstance(binding_id, str) or binding_id not in expected:
            raise ReportingError("dataset_lineage_incomplete", "数据集来源不属于当前混合绑定。")
        actual.add(binding_id)
    if actual != expected:
        raise ReportingError("dataset_lineage_incomplete", "混合来源数据集不完整。")
