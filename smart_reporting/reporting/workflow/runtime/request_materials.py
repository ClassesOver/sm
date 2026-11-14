"""冻结参考与模板登记身份；重试和恢复不得静默替换输入。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...contract import ReportRequestEnvelope
from ...models import ReportingError

REPORT_REQUEST_MATERIALS_STATE_KEY = "report_request_materials"


def _material_snapshot(request: Mapping[str, Any]) -> dict[str, Any]:
    return {"fileInputs": list(request.get("fileInputs") or ()),
        "templateInput": request.get("templateInput")}


def freeze_request_materials(state: dict[str, Any], envelope: ReportRequestEnvelope) -> None:
    """存入可随 Agno session 持久化的完整身份；旧运行按原请求迁移。"""
    snapshot = _material_snapshot(envelope.model_dump(mode="json", by_alias=True))
    previous = state.get(REPORT_REQUEST_MATERIALS_STATE_KEY)
    if previous is None:
        original = state.get("report_workflow_input")
        if isinstance(original, Mapping):
            previous = _material_snapshot(original)
    if previous is not None and previous != snapshot:
        raise ReportingError("report_context_restart_required",
            "参考文件或模板身份已变化，必须新建运行，不能沿用原分析状态。")
    state[REPORT_REQUEST_MATERIALS_STATE_KEY] = snapshot
