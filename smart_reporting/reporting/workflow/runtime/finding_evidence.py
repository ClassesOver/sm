"""发现来源的模型视图；完整文件和 JSON 指针始终保持原始身份。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ...trace.fact_index import resolve_pointer_value
from ...trace.numeric_text import (
    budget_comparison_values,
    frozen_fact_bundles,
    project_ratio_values,
)
from ..checkpoint import SectionWorkItem
from .phase_models import SectionEvidenceFile

_ATOMIC_ARRAYS = {"metrics", "derivedMetrics", "comparisons", "reconciliations", "correlationDetails", "findings"}


def finding_evidence_view(
    files: Sequence[SectionEvidenceFile], work_item: SectionWorkItem,
) -> tuple[tuple[SectionEvidenceFile, ...], set[str] | None, list[dict[str, Any]]]:
    """只展示分配发现引用的原子记录，不重编号、不改来源文件、不回退到完整正文。"""
    if not work_item.finding_ids:
        return tuple(files), None, []
    by_path = {item.identity.path: item for item in files}
    documents: dict[str, dict[str, Any]] = {}
    selected: dict[str, dict[str, Any]] = {}
    fact_ids: set[str] = set()
    warnings: list[dict[str, Any]] = []
    for finding in work_item.finding_summaries:
        refs = finding.get("sourceRefs") or ()
        if not refs:
            refs = ({},)
        for ref in refs:
            source = by_path.get(ref.get("path"))
            try:
                if (source is None or source.identity.sha256 != ref.get("fileSha256")
                        or ref.get("analysisId") not in work_item.analysis_ids):
                    raise ValueError("来源文件身份或分析身份不匹配")
                if source.identity.path not in documents:
                    document = json.loads(source.content)
                    if not isinstance(document, dict):
                        raise ValueError("来源不是 JSON 对象")
                    documents[source.identity.path] = document
                document = documents[source.identity.path]
                if document.get("analysisId") not in (None, ref["analysisId"]):
                    raise ValueError("来源正文分析身份不匹配")
                pointer = ref.get("pointer")
                if not isinstance(pointer, str) or not pointer.startswith("/"):
                    raise ValueError("来源指针无效")
                # 先核实完整指针存在，再携带所属原子记录的单位、期间和 factId。
                resolve_pointer_value(document, pointer)
                tokens = pointer.split("/")
                if len(tokens) >= 3 and tokens[1] in _ATOMIC_ARRAYS and tokens[2].isdigit():
                    pointer = "/".join(tokens[:3])
                value = resolve_pointer_value(document, pointer)
            except (KeyError, ValueError, TypeError, IndexError):
                warnings.append({
                    "code": "report_section_finding_source_unavailable",
                    "message": "章节发现的来源身份或指针不可用，已省略该证据视图并保留其他内容。",
                    "details": {"sectionCode": work_item.section_code, "findingId": finding["findingId"],
                                "path": ref.get("path"), "pointer": ref.get("pointer")},
                })
                continue
            selected.setdefault(source.identity.path, {})[pointer] = value
            if isinstance(value, dict) and isinstance(value.get("factId"), str):
                fact_ids.add(value["factId"])
    projected = []
    # 文件与原子记录顺序遵循冻结来源；selected 内显式保留原始 JSON 指针。
    for source in files:
        values = selected.get(source.identity.path)
        if not values:
            continue
        # 复用同数据集、快照、范围、单位和期间的配对规则。
        # 预算比较仍由实际值补分母；项目比例在分子或分母已入选时补齐另一侧。
        local_ids = {value["factId"] for value in values.values()
                     if isinstance(value, dict) and isinstance(value.get("factId"), str)}
        for bundle in frozen_fact_bundles((source.content,)):
            ratio_entries = tuple(project_ratio_values(bundle))
            dependencies = {
                entry["budgetFactId"] for entry in budget_comparison_values(bundle)
                if entry["actualFactId"] in local_ids
            } | {
                entry["budgetFactId"] for entry in ratio_entries
                if entry["numeratorFactId"] in local_ids
            } | {
                entry["numeratorFactId"] for entry in ratio_entries
                if entry["budgetFactId"] in local_ids
            }
            for index, metric in enumerate(documents[source.identity.path].get("metrics", ())):
                if isinstance(metric, dict) and metric.get("factId") in dependencies:
                    values[f"/metrics/{index}"] = metric
                    fact_ids.add(metric["factId"])
        content = {"analysisId": documents[source.identity.path].get("analysisId")}
        content["selected"] = [
            {"pointer": pointer, "value": value} for pointer, value in values.items()
        ]
        projected.append(source.model_copy(update={
            "content": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        }))
    return tuple(projected), fact_ids, warnings


__all__ = ["finding_evidence_view"]
