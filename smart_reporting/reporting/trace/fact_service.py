"""FactRef 查询与一层依赖展开服务（B2，计划 5.1 GET /facts/{fact_ref_id}）。

纯函数层：输入冻结 bundle bytes + FactRefV1（分析层用 factId 定位，
Editor API 层负责把 resource_id 解析为 bundle 内容并复核文件身份），
输出 fact 记录与一层输入关系。深度/节点数按 B0 预算限制；展开不递归
返回整图（计划 5.1：依赖按需加载）。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..models import ReportingError
from .contracts_v1 import TRACE_BUDGETS_V1, FactRefV1
from .fact_index import fact_entry_from_pointer

_JSON = json.JSONDecoder()


def fact_display_value(entry: Mapping[str, Any]) -> Any:
    """从 fact 记录提取展示值（按 kind 取最自然的数值字段）。"""

    # 比率不可计算时保留空值，difference 是另一种指标，不能作为回退值。
    if "numeratorMetric" in entry:
        return entry.get("percentage") if entry.get("percentage") is not None else entry.get("value")
    for key in ("total", "percentage", "value", "change", "difference"):
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def fact_display_unit(entry: Mapping[str, Any]) -> str | None:
    """展示值与单位使用同一字段选择，预算完成率不能显示成元或人次。"""
    if entry.get("total") is None and entry.get("percentage") is not None:
        return "%"
    if entry.get("total") is None and "numeratorMetric" in entry:
        return None
    return entry.get("unit")


def resolve_fact(
    bundle_bytes: bytes,
    fact_ref: FactRefV1,
    *,
    with_inputs: bool = True,
) -> dict[str, Any]:
    """解析 FactRef → fact 记录 + 可选一层输入关系。

    未知指针、非事实数组的指针按 fact_binding_unavailable 处理；bundle 的
    analysisId 必须与 FactRef 一致（防御索引装配错位）。
    """

    try:
        document = json.loads(bundle_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReportingError(
            "snapshot_integrity_failed", "事实文件无法解析。"
        ) from error
    if not isinstance(document, Mapping):
        raise ReportingError("snapshot_integrity_failed", "事实文件结构无效。")
    document_analysis_id = document.get("analysisId")
    if document_analysis_id != fact_ref.analysis_id:
        raise ReportingError(
            "fact_binding_unavailable", "事实引用与文件身份不一致。"
        )
    try:
        kind, entry = fact_entry_from_pointer(document, fact_ref.json_pointer)
    except KeyError as error:
        raise ReportingError(
            "fact_binding_unavailable", "事实引用指针无法解析。"
        ) from error

    stored_fact_id = entry.get("factId")
    if fact_ref.fact_key and stored_fact_id and fact_ref.fact_key != stored_fact_id:
        # 位置漂移防御：指针命中但身份键不符，说明文件在冻结后被重排。
        raise ReportingError(
            "fact_binding_unavailable", "事实引用与记录身份不匹配。"
        )

    payload: dict[str, Any] = {
        "analysisId": fact_ref.analysis_id,
        "factId": stored_fact_id,
        "factKind": kind,
        "jsonPointer": fact_ref.json_pointer,
        "entry": entry,
        "displayValue": fact_display_value(entry),
        "displayUnit": fact_display_unit(entry),
        "warnings": entry.get("warnings", ()) if isinstance(entry, Mapping) else (),
    }
    if with_inputs:
        payload["inputFactRefs"] = _input_fact_refs(document, kind, entry)
    return payload


def _input_fact_refs(
    document: Mapping[str, Any], kind: str, entry: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    """一层输入 fact 引用（analysisId + factId），按 kind 语义取依赖。"""

    inputs: list[Mapping[str, Any]] = []
    metrics = document.get("metrics")
    if not isinstance(metrics, list):
        return ()
    if kind == "derived":
        for key in ("numeratorMetric", "denominatorMetric"):
            code = entry.get(key)
            for metric in metrics:
                if (
                    isinstance(metric, Mapping)
                    and code in (metric.get("metricCodes") or ())
                    and metric.get("datasetId") in (entry.get("datasetIds") or ())
                    and entry.get("periodRole") in (metric.get("periodRoles") or ())
                ):
                    inputs.append(
                        {"analysisId": document.get("analysisId"), "factId": metric.get("factId")}
                    )
    elif kind == "comparison":
        field_ref = entry.get("fieldRef")
        dataset_ids = (entry.get("currentDatasetId"), entry.get("baselineDatasetId"))
        for metric in metrics:
            if (
                isinstance(metric, Mapping)
                and metric.get("fieldRef") == field_ref
                and metric.get("datasetId") in dataset_ids
            ):
                inputs.append(
                    {"analysisId": document.get("analysisId"), "factId": metric.get("factId")}
                )
    elif kind == "reconciliation":
        for key in ("leftMetric", "rightMetric"):
            code = entry.get(key)
            for metric in metrics:
                if (
                    isinstance(metric, Mapping)
                    and code in (metric.get("metricCodes") or ())
                    and metric.get("datasetId") in (entry.get("datasetIds") or ())
                    and entry.get("periodRole") in (metric.get("periodRoles") or ())
                ):
                    inputs.append(
                        {"analysisId": document.get("analysisId"), "factId": metric.get("factId")}
                    )
    # 去重并保持顺序。
    seen: set[Any] = set()
    unique: list[Mapping[str, Any]] = []
    for item in inputs:
        key = (item.get("analysisId"), item.get("factId"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def expand_fact_tree(
    bundle_bytes: bytes,
    fact_ref: FactRefV1,
    *,
    depth: int = 1,
) -> dict[str, Any]:
    """按深度展开 fact 依赖（当前 bundle 内；跨 bundle 由 B4 计算记录承载）。

    深度与节点数受 B0 预算限制；重复展开（环）按已访问集合短路，不无限
    遍历（计划 5.3）。
    """

    max_depth = TRACE_BUDGETS_V1["fact_expand_max_depth"]
    max_nodes = TRACE_BUDGETS_V1["fact_expand_max_nodes"]
    if not 1 <= depth <= max_depth:
        raise ReportingError(
            "request_invalid", f"展开深度必须在 1~{max_depth} 之间。"
        )
    try:
        document = json.loads(bundle_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReportingError("snapshot_integrity_failed", "事实文件无法解析。") from error
    relations = fact_input_relations_from_document(document)

    node_count = 0

    def _node(pointer: str, remaining: int) -> dict[str, Any]:
        nonlocal node_count
        node_count += 1
        if node_count > max_nodes:
            raise ReportingError("resource_limit_exceeded", "事实展开节点数超限。")
        kind, entry = fact_entry_from_pointer(document, pointer)
        node: dict[str, Any] = {
            "factKind": kind,
            "jsonPointer": pointer,
            "factId": entry.get("factId"),
            "displayValue": fact_display_value(entry),
        "displayUnit": fact_display_unit(entry),
        }
        if remaining <= 0:
            return node
        children = []
        for input_ref in _input_fact_refs(document, kind, entry):
            input_fact_id = input_ref.get("factId")
            child_pointer = relations.get(input_fact_id)
            if child_pointer is None:
                continue
            children.append(_node(child_pointer, remaining - 1))
        if children:
            node["inputs"] = children
        return node

    return _node(fact_ref.json_pointer, depth - 1)


def fact_input_relations_from_document(
    document: Mapping[str, Any],
) -> dict[str, str]:
    """从已解析 bundle 提取 factId → JSON Pointer 的输入关系映射。"""

    metrics = document.get("metrics")
    metrics_by_code: dict[str, str] = {}
    pointers: dict[str, str] = {}
    if isinstance(metrics, list):
        for index, metric in enumerate(metrics):
            if not isinstance(metric, Mapping):
                continue
            pointer = f"/metrics/{index}"
            fact_id = metric.get("factId")
            if fact_id:
                pointers[fact_id] = pointer
            for code in metric.get("metricCodes") or ():
                metrics_by_code.setdefault(code, pointer)
    derived = document.get("derivedMetrics")
    if isinstance(derived, list):
        for index, fact in enumerate(derived):
            if not isinstance(fact, Mapping):
                continue
            fact_id = fact.get("factId")
            if fact_id:
                pointers[fact_id] = f"/derivedMetrics/{index}"
    comparisons = document.get("comparisons")
    if isinstance(comparisons, list):
        for index, fact in enumerate(comparisons):
            if not isinstance(fact, Mapping):
                continue
            fact_id = fact.get("factId")
            if fact_id:
                pointers[fact_id] = f"/comparisons/{index}"
    reconciliations = document.get("reconciliations")
    if isinstance(reconciliations, list):
        for index, fact in enumerate(reconciliations):
            if not isinstance(fact, Mapping):
                continue
            fact_id = fact.get("factId")
            if fact_id:
                pointers[fact_id] = f"/reconciliations/{index}"
    return pointers


__all__ = [
    "expand_fact_tree",
    "fact_input_relations_from_document",
    "resolve_fact",
]
