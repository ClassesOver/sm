"""从已登记 chart-input 恢复事实引用，不按名称、数值或数据集猜配。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

from ..workflow.runtime.chart_inputs import _table_for_binding, parse_data_path, ranked_detail_scope
from ..workflow.runtime.phase_models import ChartDataBinding
from .contracts_v1 import (
    ChartTraceV1,
    FactRefV1,
    RevisionTraceIndexV1,
    TraceFileRefV1,
    canonical_json_bytes,
)
from .fact_index import FACT_ARRAYS, fact_entry_from_pointer


def _registered_source_path(source: str, registered: str, markdown: str) -> bool:
    """快照不改冻结 JSON；只接受发布/编辑导出的固定目录迁移。"""
    if not isinstance(source, str):
        return False
    if source == registered:
        return True
    target_root = PurePosixPath(markdown).parent
    if not re.fullmatch(r"revision-\d+", target_root.name):
        return False
    try:
        relative = PurePosixPath(source).relative_to(target_root.parent)
    except ValueError:
        return registered == str(target_root / "trace-resources" / source)
    if relative.parts and re.fullmatch(r"revision-\d+", relative.parts[0]):
        relative = PurePosixPath(*relative.parts[1:])
    return registered == str(target_root / relative)


async def recover_chart_fact_refs(
    index: RevisionTraceIndexV1, chart: ChartTraceV1,
    read_file: Callable[[TraceFileRefV1], Awaitable[bytes]],
) -> tuple[FactRefV1, ...]:
    """仅从冻结来源恢复缺失绑定；所有输入都核验成功后才返回整组引用。"""
    files = {file.resource_id: file for file in index.files}
    documents = {}

    async def document(resource_id):
        if resource_id not in documents:
            file = files[resource_id]
            raw = await read_file(file)
            if len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
                raise ValueError("chart_source_integrity_failed")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("chart_source_invalid")
            documents[resource_id] = value
        return documents[resource_id]

    refs = {}
    for resource_id in chart.plot_data_file_resource_ids:
        plot = await document(resource_id)
        if plot.get("schema") != "chart-input/v1" or plot.get("chartId") != chart.chart_id:
            raise ValueError("chart_input_identity_mismatch")
        source = plot.get("source")
        if not isinstance(source, dict):
            raise ValueError("chart_input_source_missing")
        origins = [entry for entry in index.fact_files
                   if entry.analysis_id == source.get("analysisId")
                   and isinstance(source.get("path"), str)
                   and _registered_source_path(source["path"], files[entry.file_resource_id].path,
                       files[index.markdown_file_resource_id].path)
                   and files[entry.file_resource_id].sha256 == source.get("sha256")]
        if len(origins) != 1:
            raise ValueError("chart_input_source_ambiguous")
        origin = origins[0]
        payload = await document(origin.file_resource_id)
        if payload.get("analysisId") != origin.analysis_id and not (
            origin.content_kind == "supplemental_evidence" and payload.get("analysisId") is None
        ):
            raise ValueError("chart_input_analysis_mismatch")
        binding = ChartDataBinding(analysisId=origin.analysis_id, factPath=source["path"],
            dataPath=source["dataPath"], fields=plot["columns"], role=plot["role"])
        columns, rows, metadata = _table_for_binding(payload, binding)
        expected = (columns, rows, metadata or {}, ranked_detail_scope(binding.data_path) or {})
        actual = (plot.get("columns"), plot.get("rows"), plot.get("columnMeta") or {}, plot.get("dataScope") or {})
        if canonical_json_bytes(expected) != canonical_json_bytes(actual) or plot.get("rowCount") != len(rows):
            raise ValueError("chart_input_projection_mismatch")
        tokens = parse_data_path(binding.data_path)
        if origin.content_kind == "deterministic_bundle":
            if tokens[0] not in {array for _, array in FACT_ARRAYS}:
                raise ValueError("chart_fact_selector_unregistered")
            if len(tokens) == 1:
                positions = range(len(payload[tokens[0]]))
            elif isinstance(tokens[1], int):
                positions = (tokens[1],)
            else:
                raise ValueError("chart_fact_selector_unregistered")
            for position in positions:
                pointer = f"/{tokens[0]}/{position}"
                kind, entry = fact_entry_from_pointer(payload, pointer)
                ref = FactRefV1(analysisId=origin.analysis_id, fileResourceId=origin.file_resource_id,
                    jsonPointer=pointer, factKind=kind, factKey=entry.get("factId"))
                refs[(ref.file_resource_id, ref.json_pointer)] = ref
        elif origin.content_kind == "supplemental_evidence" and len(tokens) >= 2 and tokens[0] == "findings" and isinstance(tokens[1], int):
            pointer = f"/findings/{tokens[1]}"
            # 保留补证身份，不把补证结果冒充基础 metric；只有已登记输出才可恢复。
            if not any(ref.analysis_id == origin.analysis_id and ref.file_resource_id == origin.file_resource_id
                       and (ref.json_pointer == pointer or ref.json_pointer.startswith(pointer + "/"))
                       for record in index.computations for ref in record.output_fact_refs):
                raise ValueError("chart_fact_selector_unregistered")
            ref = FactRefV1(analysisId=origin.analysis_id, fileResourceId=origin.file_resource_id,
                jsonPointer=pointer, factKind="supplemental_finding")
            refs[(ref.file_resource_id, ref.json_pointer)] = ref
            # 标准补证才有服务端登记的指标关系；自由补证不推断父指标。
            from .standard_chart_alignment import _standard_finding_parents

            bundles = [entry for entry in index.fact_files if entry.analysis_id == origin.analysis_id
                       and entry.content_kind == "deterministic_bundle"]
            if len(bundles) == 1:
                parent_origin = bundles[0]
                parent_document = await document(parent_origin.file_resource_id)
                if parent_document.get("analysisId") != parent_origin.analysis_id:
                    raise ValueError("chart_input_analysis_mismatch")
                entries = [item for _, array in FACT_ARRAYS for item in parent_document.get(array, ())]
                try:
                    parents = _standard_finding_parents(index, origin, tokens, entries,
                        path_matches=lambda source, target: _registered_source_path(
                            source, target, files[index.markdown_file_resource_id].path))
                except (ValueError, KeyError, TypeError, IndexError):
                    parents = {}
                parent_ids = {item.get("factId") for field in columns for item in parents.get(field, ())}
                for kind, array in FACT_ARRAYS:
                    for position, entry in enumerate(parent_document.get(array, ())):
                        if entry.get("factId") in parent_ids:
                            ref = FactRefV1(analysisId=parent_origin.analysis_id,
                                fileResourceId=parent_origin.file_resource_id, jsonPointer=f"/{array}/{position}",
                                factKind=kind, factKey=entry["factId"])
                            refs[(ref.file_resource_id, ref.json_pointer)] = ref
        else:
            raise ValueError("chart_fact_selector_unregistered")
    # 比较只能沿冻结的 inputFactIds 关联；必须已绑定全部操作数。
    for origin in index.fact_files:
        bound_ids = {ref.fact_key for ref in refs.values()
                     if ref.file_resource_id == origin.file_resource_id and ref.fact_key}
        if origin.content_kind != "deterministic_bundle" or not bound_ids:
            continue
        payload = await document(origin.file_resource_id)
        for position, comparison in enumerate(payload.get("comparisons", ())):
            inputs = set(comparison.get("inputFactIds") or ())
            if inputs and inputs.issubset(bound_ids):
                ref = FactRefV1(analysisId=origin.analysis_id, fileResourceId=origin.file_resource_id,
                    jsonPointer=f"/comparisons/{position}", factKind="comparison", factKey=comparison.get("factId"))
                refs[(ref.file_resource_id, ref.json_pointer)] = ref
    if not refs or len(refs) > 100:
        raise ValueError("chart_fact_bindings_unavailable")
    return tuple(refs.values())
