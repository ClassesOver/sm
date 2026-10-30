"""Recheck registered chart arrays against frozen source projections, per chart."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Literal

from loguru import logger

from ..contract import StrictModel
from ..workflow.runtime.chart_inputs import (
    _table_for_binding,
    ranked_detail_scope,
)
from ..workflow.runtime.phase_models import ChartDataBinding
from .chart_subjects import chart_fingerprints, chart_presentations
from .contracts_v1 import RevisionTraceIndexV1, canonical_json_bytes

QUALITY_IMAGE_BYTE_BUDGET = 16 * 1024 * 1024


class ChartQualityCheck(StrictModel):
    status: Literal["verified", "unknown"] = "unknown"
    scope: Literal["registered_arrays"] = "registered_arrays"
    reason: str


def standard_proof_source_ids(index: RevisionTraceIndexV1) -> set[str]:
    """发布和编辑器使用同一份标准绘制证明依赖清单。"""
    ids = {chart.script_file_resource_id for chart in index.chart_traces
           if chart.standard_render_proof is not None and chart.script_file_resource_id is not None}
    digests = {entry.get("sha256") for chart in index.chart_traces
               if chart.standard_render_proof is not None for entry in chart.standard_render_proof.inputs}
    ids.update(file.resource_id for file in index.files if file.sha256 in digests)
    return ids


def evaluate_chart_quality(
    index: RevisionTraceIndexV1,
    markdown: str,
    sources: Mapping[str, bytes],
) -> dict[str, ChartQualityCheck]:
    if not index.chart_traces:
        return {}
    files = {file.resource_id: file for file in index.files}
    by_path = {file.path: file for file in index.files}
    presentations = None
    results = {}
    verified_bytes: dict[str, bytes] = {}
    unavailable: set[str] = set()
    documents = {}

    def read(resource_id: str) -> bytes:
        if resource_id in unavailable:
            raise ValueError("chart_source_unavailable")
        if resource_id in verified_bytes:
            return verified_bytes[resource_id]
        file = files[resource_id]
        raw = sources.get(resource_id)
        if raw is None or len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
            unavailable.add(resource_id)
            raise ValueError("chart_source_unavailable")
        verified_bytes[resource_id] = raw
        return raw

    def read_json(resource_id: str):
        if resource_id not in documents:
            documents[resource_id] = json.loads(read(resource_id))
        return documents[resource_id]

    for chart in index.chart_traces:
        reason = "chart_check_failed"
        try:
            image = files[chart.image_file_resource_id]
            reason = "chart_source_unavailable"
            if not image.media_type.startswith("image/"):
                raise ValueError(reason)
            read(chart.image_file_resource_id)
            reason = "chart_presentation_changed"
            if presentations is None:
                presentations = chart_presentations(markdown)
            unique = (
                sum(
                    PurePosixPath(files[item.image_file_resource_id].path).name
                    == PurePosixPath(image.path).name
                    for item in index.chart_traces
                )
                == 1
            )
            fingerprints = chart_fingerprints(presentations, image.path, allow_filename=unique,
                                              markdown_path=files[index.markdown_file_resource_id].path)
            if chart.presentation_sha256 is None or fingerprints != [chart.presentation_sha256]:
                raise ValueError(reason)
            if chart.standard_render_proof is None:
                reason = "static_image_not_evaluated"
                raise ValueError(reason)
            inputs = []
            for resource_id in chart.plot_data_file_resource_ids:
                plot = read_json(resource_id)
                reason = "chart_input_identity_mismatch"
                if (
                    not isinstance(plot, dict)
                    or plot.get("schema") != "chart-input/v1"
                    or plot.get("chartId") != chart.chart_id
                ):
                    raise ValueError(reason)
                source = plot.get("source")
                if not isinstance(source, dict):
                    raise ValueError(reason)
                matches = [
                    entry
                    for entry in index.fact_files
                    if entry.analysis_id == source.get("analysisId")
                    and files[entry.file_resource_id].sha256 == source.get("sha256")
                ]
                if len(matches) != 1:
                    raise ValueError(reason)
                origin = matches[0]
                document = read_json(origin.file_resource_id)
                if (
                    not isinstance(document, dict)
                    or (document.get("analysisId") != origin.analysis_id and not (
                        origin.content_kind == "supplemental_evidence"
                        and document.get("analysisId") is None
                    ))
                ):
                    raise ValueError(reason)
                data_path = source.get("dataPath")
                selected_columns = plot.get("columns")
                if (
                    not isinstance(data_path, str)
                    or not isinstance(selected_columns, list)
                    or not all(isinstance(column, str) for column in selected_columns)
                ):
                    raise ValueError(reason)
                binding = ChartDataBinding(
                    analysisId=origin.analysis_id,
                    factPath=files[origin.file_resource_id].path,
                    dataPath=data_path,
                    fields=tuple(selected_columns),
                    role="quality_check",
                )
                columns, rows, metadata = _table_for_binding(document, binding)
                reason = "chart_input_projection_mismatch"
                expected = (
                    columns,
                    rows,
                    metadata or {},
                    ranked_detail_scope(binding.data_path) or {},
                )
                actual = (
                    plot.get("columns"),
                    plot.get("rows"),
                    plot.get("columnMeta") or {},
                    plot.get("dataScope") or {},
                )
                if canonical_json_bytes(expected) != canonical_json_bytes(actual) or plot.get(
                    "rowCount"
                ) != len(rows):
                    raise ValueError(reason)
                inputs.append(plot)
            from ..workflow.runtime.standard_chart_proof import recompile_standard_render_proof

            proof = chart.standard_render_proof
            reason = "standard_render_identity_mismatch"
            script = files.get(chart.script_file_resource_id)
            if (proof is None or proof.image_sha256 != image.sha256 or script is None
                    or script.media_type != "text/x-python" or script.sha256 != proof.script_sha256):
                raise ValueError(reason)
            compiled_inputs = {}
            for entry in proof.inputs:
                matches = [file for file in index.files
                           if file.sha256 == entry.get("sha256") and file.media_type == "application/json"]
                if not matches:
                    raise ValueError(reason)
                compiled_inputs[entry["sha256"]] = read(matches[0].resource_id)
            expected_inputs = {entry["sha256"] for entry in proof.inputs
                               if entry.get("chartId") == chart.chart_id}
            actual_inputs = {files[resource_id].sha256 for resource_id in chart.plot_data_file_resource_ids}
            plan_charts = proof.plan.get("charts", ())
            if (actual_inputs != expected_inputs
                    or sum(item.get("chartId") == chart.chart_id for item in plan_charts) != 1):
                raise ValueError(reason)
            reason = "standard_render_source_unproven"
            compiled = recompile_standard_render_proof(proof, compiled_inputs)
            if compiled is None or compiled != read(script.resource_id):
                raise ValueError(reason)
            results[chart.chart_id] = ChartQualityCheck(
                status="verified", reason="standard_render_matches_frozen_inputs"
            )
        except Exception as error:
            if isinstance(error, ValueError) and str(error) == "chart_source_unavailable":
                reason = "chart_source_unavailable"
            logger.warning("chart_quality_unknown chart_id={} reason={}", chart.chart_id, reason)
            results[chart.chart_id] = ChartQualityCheck(reason=reason)
    return results
