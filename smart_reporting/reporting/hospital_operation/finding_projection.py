"""把冻结分析事实投影为可编排的管理发现。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .deterministic_analysis import DeterministicAnalysisBundle
from .findings import FindingCard, FindingGraph, FindingSourceRef


def _stable_id(analysis_id: str, path: str, snapshot_hash: str) -> str:
    digest = hashlib.sha256(f"{snapshot_hash}:{analysis_id}:{path}".encode()).hexdigest()[:16]
    return f"finding_{digest}"


def _source(analysis_id: str, path: str, file_sha256: str) -> FindingSourceRef:
    return FindingSourceRef(analysisId=analysis_id, path=path, fileSha256=file_sha256, pointer="/")


def project_analysis_findings(
    analysis_id: str,
    deterministic_facts: DeterministicAnalysisBundle | Mapping[str, Any],
    supplemental_evidence: Mapping[str, Any] | None,
    metric_definitions: Sequence[Mapping[str, Any]] = (),
    *,
    snapshot_hash: str,
    fact_file_path: str = "deterministic-facts.json",
    fact_file_sha256: str | None = None,
) -> tuple[FindingCard, ...]:
    """只从已验证事实生成发现；缺失事实不会被改成零。"""

    payload = deterministic_facts.model_dump(mode="json", by_alias=True) if isinstance(deterministic_facts, DeterministicAnalysisBundle) else dict(deterministic_facts)
    file_sha256 = fact_file_sha256 or hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    definitions = {str(item.get("code")): item for item in metric_definitions if item.get("code")}
    findings: list[FindingCard] = []

    def add(kind: str, path: str, title: str, summary: str, *, priority: str = "medium", evidence: str = "verified_fact", impact: float | None = None, unit: str | None = None, metrics: tuple[str, ...] = (), periods: tuple[str, ...] = ("current",), grain: tuple[str, ...] = (), limitations: tuple[str, ...] = ()) -> None:
        display_unit = unit or next((str(definitions[code].get("unit")) for code in metrics if definitions.get(code, {}).get("unit")), None)
        findings.append(FindingCard(
            findingId=_stable_id(analysis_id, path, snapshot_hash), analysisIds=(analysis_id,), kind=kind,
            title=title, summary=summary, metricCodes=metrics or (analysis_id,), periodRoles=periods,
            grain=grain, priority=priority, evidenceLevel=evidence, impactValue=impact,
            impactUnit=display_unit, actionability="unknown", citationIds=(f"{analysis_id}:{path}",),
            sourceRefs=(_source(analysis_id, fact_file_path, file_sha256),), limitations=limitations,
        ))

    for index, comparison in enumerate(payload.get("comparisons") or ()):
        if not isinstance(comparison, Mapping):
            continue
        change = comparison.get("change")
        metric = str(comparison.get("field") or "指标")
        unit = comparison.get("unit") if isinstance(comparison.get("unit"), str) else None
        add("comparison", f"/comparisons/{index}", f"{metric}比较变化", f"{metric}比较变化为 {change}。", priority="high" if isinstance(change, (int, float)) and abs(change) > 0 else "medium", impact=change if isinstance(change, (int, float)) else None, unit=unit, metrics=(metric,), periods=("current", "yoy" if comparison.get("comparisonType") == "yoy" else "mom"))

    for index, metric in enumerate(payload.get("metrics") or ()):
        if not isinstance(metric, Mapping):
            continue
        periods = metric.get("periodValues")
        if isinstance(periods, Sequence) and not isinstance(periods, (str, bytes)) and len(periods) >= 2:
            add("trend", f"/metrics/{index}/periodValues", f"{metric.get('field', '指标')}趋势", f"已登记 {len(periods)} 个期间值，可用于趋势分析。", metrics=(str(metric.get("field") or "指标"),), unit=metric.get("unit") if isinstance(metric.get("unit"), str) else None)

    for index, relation in enumerate(payload.get("reconciliations") or ()):
        if not isinstance(relation, Mapping):
            continue
        if relation.get("passed") is True and (
            str(relation.get("code", "")).casefold().find("contrib") >= 0
            or str(relation.get("code", "")).casefold().find("归因") >= 0
        ):
            add("attribution", f"/reconciliations/{index}", "贡献分解已闭合", f"{relation.get('code', '贡献分解')}已通过对账。", priority="high", evidence="direct_decomposition", metrics=(str(relation.get("leftMetric") or "指标"),), limitations=())
        else:
            add("data_quality", f"/reconciliations/{index}", "贡献分解待核对", f"{relation.get('code', '贡献分解')}未通过对账，不能形成确定归因。", priority="medium", evidence="evidence_missing", metrics=(str(relation.get("leftMetric") or "指标"),), limitations=("归因对账未通过",))

    for index, detail in enumerate(payload.get("correlationDetails") or ()):
        if isinstance(detail, Mapping):
            add("impact", f"/correlationDetails/{index}", "指标存在统计关系", f"{detail.get('leftField', '指标')}与{detail.get('rightField', '指标')}存在统计关系，不能据此确认因果。", evidence="statistical_relation", metrics=(str(detail.get("leftField") or "指标"), str(detail.get("rightField") or "指标")), limitations=("仅有统计关系证据",))

    if not findings:
        add("data_quality", "/warnings", "当前分析缺少可编排发现", "当前分析没有形成可用于正文的确定性发现。", priority="low", evidence="evidence_missing", limitations=tuple(str(item) for item in payload.get("warnings", ()) if item))
    return tuple(findings)


def build_finding_graph(
    fact_bundles: Sequence[DeterministicAnalysisBundle | Mapping[str, Any]],
    supplemental_evidence: Mapping[str, Mapping[str, Any]] | None,
    metric_definitions: Sequence[Mapping[str, Any]],
    *,
    snapshot_hash: str,
) -> FindingGraph:
    cards = [
        card
        for bundle in fact_bundles
        for card in project_analysis_findings(
            str(bundle.analysis_id if isinstance(bundle, DeterministicAnalysisBundle) else bundle.get("analysisId")),
            bundle,
            (supplemental_evidence or {}).get(str(bundle.analysis_id if isinstance(bundle, DeterministicAnalysisBundle) else bundle.get("analysisId"))),
            metric_definitions,
            snapshot_hash=snapshot_hash,
        )
    ]
    return FindingGraph(snapshotHash=snapshot_hash, findings=tuple(cards))


__all__ = ["build_finding_graph", "project_analysis_findings"]
