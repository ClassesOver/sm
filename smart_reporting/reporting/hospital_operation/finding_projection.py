"""把冻结分析事实投影为可编排的管理发现。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .deterministic_analysis import DeterministicAnalysisBundle
from .findings import FindingCard, FindingGraph, FindingSourceRef


def _stable_id(analysis_id: str, path: str, snapshot_hash: str) -> str:
    digest = hashlib.sha256(f"{snapshot_hash}:{analysis_id}:{path}".encode()).hexdigest()[:16]
    return f"finding_{digest}"


def _source(analysis_id: str, path: str, file_sha256: str, pointer: str) -> FindingSourceRef:
    return FindingSourceRef(analysisId=analysis_id, path=path, fileSha256=file_sha256, pointer=pointer)


def project_analysis_findings(
    analysis_id: str,
    deterministic_facts: DeterministicAnalysisBundle | Mapping[str, Any],
    supplemental_evidence: Mapping[str, Any] | None,
    metric_definitions: Sequence[Mapping[str, Any]] = (),
    *,
    snapshot_hash: str,
    citation_ids: tuple[str, ...],
    fact_file_path: str = "deterministic-facts.json",
    fact_file_sha256: str | None = None,
    supplemental_file_path: str | None = None,
    supplemental_file_sha256: str | None = None,
) -> tuple[FindingCard, ...]:
    """只从已验证事实生成发现；缺失事实不会被改成零。"""

    payload = deterministic_facts.model_dump(mode="json", by_alias=True) if isinstance(deterministic_facts, DeterministicAnalysisBundle) else dict(deterministic_facts)
    file_sha256 = fact_file_sha256 or hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    definitions = {str(item.get("code")): item for item in metric_definitions if item.get("code")}
    findings: list[FindingCard] = []

    def add(kind: str, path: str, title: str, summary: str, *, priority: str = "medium", evidence: str = "verified_fact", impact: float | None = None, unit: str | None = None, metrics: tuple[str, ...] = (), periods: tuple[str, ...] = ("current",), grain: tuple[str, ...] = (), limitations: tuple[str, ...] = ()) -> None:
        locator = path.strip("/").split("/")
        source_fact = {}
        if len(locator) >= 2 and locator[1].isdigit():
            collection = payload.get(locator[0]) or ()
            index = int(locator[1])
            if index < len(collection) and isinstance(collection[index], Mapping):
                source_fact = collection[index]
        metrics = tuple(source_fact.get("metricCodes") or metrics)
        periods = tuple(source_fact.get("periodRoles") or periods)
        display_unit = unit or next((str(definitions[code].get("unit")) for code in metrics if definitions.get(code, {}).get("unit")), None)
        findings.append(FindingCard(
            findingId=_stable_id(analysis_id, path, snapshot_hash), analysisIds=(analysis_id,), kind=kind,
            title=title, summary=summary, metricCodes=metrics or (analysis_id,), periodRoles=periods,
            periodStart=source_fact.get("periodStart"), periodEnd=source_fact.get("periodEnd"),
            scope=dict(source_fact.get("scope") or {}),
            grain=tuple(source_fact.get("grain") or grain), priority=priority, evidenceLevel=evidence, impactValue=impact,
            impactUnit=display_unit, actionability="unknown", citationIds=citation_ids,
            sourceRefs=(_source(analysis_id, fact_file_path, file_sha256, path),), limitations=limitations,
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
        if relation.get("passed") is True:
            add("data_quality", f"/reconciliations/{index}", "指标对账通过", f"{relation.get('code', '指标')}已通过对账。", priority="low", metrics=(str(relation.get("leftMetric") or "指标"),))
        else:
            add("data_quality", f"/reconciliations/{index}", "指标对账待核对", f"{relation.get('code', '指标')}未通过对账。", priority="medium", evidence="evidence_missing", metrics=(str(relation.get("leftMetric") or "指标"),), limitations=("指标对账未通过",))

    for index, detail in enumerate(payload.get("correlationDetails") or ()):
        if isinstance(detail, Mapping):
            add("impact", f"/correlationDetails/{index}", "指标存在统计关系", f"{detail.get('leftField', '指标')}与{detail.get('rightField', '指标')}存在统计关系，不能据此确认因果。", evidence="statistical_relation", metrics=(str(detail.get("leftField") or "指标"), str(detail.get("rightField") or "指标")), limitations=("仅有统计关系证据",))

    if supplemental_evidence is not None:
        if not supplemental_file_path or not supplemental_file_sha256:
            raise ValueError("补证发现必须绑定冻结文件身份")
        if supplemental_evidence.get("analysisId") != analysis_id:
            raise ValueError("补证文件的分析身份不一致")
        for index, item in enumerate(supplemental_evidence.get("findings") or ()):
            if not isinstance(item, Mapping):
                continue
            pointer = f"/findings/{index}"
            name = str(item.get("name") or "补充分析发现")
            reconciliation_code = item.get("reconciliationCode")
            reconciliation = next(
                (
                    candidate for candidate in supplemental_evidence.get("reconciliations", ())
                    if isinstance(candidate, Mapping)
                    and candidate.get("code") == reconciliation_code
                ),
                None,
            )
            components = item.get("components")
            total = item.get("total")
            component_total = (
                sum(float(component.get("value")) for component in components)
                if isinstance(components, Sequence)
                and not isinstance(components, (str, bytes))
                and all(isinstance(component, Mapping) and isinstance(component.get("value"), (int, float))
                        for component in components)
                else None
            )
            direct_decomposition = (
                item.get("kind") == "attribution"
                and item.get("directDecomposition") is True
                and isinstance(total, (int, float))
                and component_total is not None
                and math.isclose(component_total, float(total), rel_tol=1e-12, abs_tol=1e-9)
                and isinstance(reconciliation, Mapping)
                and reconciliation.get("passed") is True
                and reconciliation.get("grain") == item.get("grain")
                and reconciliation.get("scope") == item.get("scope")
                and isinstance(reconciliation.get("leftTotal"), (int, float))
                and isinstance(reconciliation.get("rightTotal"), (int, float))
                and math.isclose(float(reconciliation["leftTotal"]), float(total), rel_tol=1e-12, abs_tol=1e-9)
                and math.isclose(float(reconciliation["rightTotal"]), float(total), rel_tol=1e-12, abs_tol=1e-9)
            )
            if direct_decomposition:
                findings.append(FindingCard(
                    findingId=_stable_id(analysis_id, f"{supplemental_file_path}:{pointer}", snapshot_hash),
                    analysisIds=(analysis_id,), kind="attribution", title=name[:200],
                    summary=f"{name}已按登记分项完成闭合对账。"[:4000],
                    metricCodes=tuple(item.get("metricCodes") or (analysis_id,)),
                    periodRoles=tuple(item.get("periodRoles") or ("current",)),
                    periodStart=item.get("periodStart"), periodEnd=item.get("periodEnd"),
                    grain=tuple(item.get("grain") or ()), scope=dict(item.get("scope") or {}),
                    priority="high", evidenceLevel="direct_decomposition", actionability="high",
                    citationIds=citation_ids,
                    sourceRefs=(_source(analysis_id, supplemental_file_path, supplemental_file_sha256, pointer),),
                ))
                continue
            # 只登记证据的存在及原始位置，不从表格重新计算指标或因标题升级归因。
            kind = item.get("kind")
            if kind not in {"scale", "trend", "comparison", "anomaly", "impact", "data_quality"}:
                kind = "impact"
            findings.append(FindingCard(
                findingId=_stable_id(analysis_id, f"{supplemental_file_path}:{pointer}", snapshot_hash),
                analysisIds=(analysis_id,), kind=kind, title=name[:200],
                summary=f"已登记补充证据：{name}"[:4000],
                metricCodes=tuple(item.get("metricCodes") or (analysis_id,)),
                periodRoles=tuple(item.get("periodRoles") or ("current",)),
                periodStart=item.get("periodStart"), periodEnd=item.get("periodEnd"),
                grain=tuple(item.get("grain") or ()), scope=dict(item.get("scope") or {}),
                priority="medium", evidenceLevel="verified_fact", actionability="unknown",
                citationIds=citation_ids,
                sourceRefs=(_source(analysis_id, supplemental_file_path, supplemental_file_sha256, pointer),),
                limitations=tuple(str(warning) for warning in supplemental_evidence.get("warnings", ()) if warning),
            ))
    if not findings:
        add("data_quality", "/warnings", "当前分析缺少可编排发现", "当前分析没有形成可用于正文的确定性发现。", priority="low", evidence="evidence_missing", limitations=tuple(str(item) for item in payload.get("warnings", ()) if item))
    return tuple(findings)


def build_finding_graph(
    fact_bundles: Sequence[DeterministicAnalysisBundle | Mapping[str, Any]],
    supplemental_evidence: Mapping[str, Mapping[str, Any]] | None,
    metric_definitions: Sequence[Mapping[str, Any]],
    *,
    snapshot_hash: str,
    citation_ids_by_analysis: Mapping[str, tuple[str, ...]],
    fact_file_paths: Mapping[str, str] | None = None,
    fact_file_sha256s: Mapping[str, str] | None = None,
    supplemental_file_paths: Mapping[str, str] | None = None,
    supplemental_file_sha256s: Mapping[str, str] | None = None,
    supplemental_sources: Mapping[str, Sequence[tuple[Mapping[str, Any], str, str]]] | None = None,
) -> FindingGraph:
    cards: dict[str, FindingCard] = {}
    for bundle in fact_bundles:
        analysis_id = str(bundle.analysis_id if isinstance(bundle, DeterministicAnalysisBundle) else bundle.get("analysisId"))
        sources = (supplemental_sources or {}).get(analysis_id) or ((
            (supplemental_evidence or {}).get(analysis_id),
            (supplemental_file_paths or {}).get(analysis_id),
            (supplemental_file_sha256s or {}).get(analysis_id),
        ),)
        for evidence, path, sha256 in sources:
            projected = project_analysis_findings(
                analysis_id, bundle, evidence, metric_definitions, snapshot_hash=snapshot_hash,
                citation_ids=citation_ids_by_analysis[analysis_id],
                supplemental_file_path=path, supplemental_file_sha256=sha256,
                fact_file_path=(fact_file_paths or {}).get(analysis_id, "deterministic-facts.json"),
                fact_file_sha256=(fact_file_sha256s or {}).get(analysis_id),
            )
            for card in projected:
                # 多个补证文件共享原子 facts；同一事实只登记一次，补证身份各自保留。
                cards.setdefault(card.finding_id, card)
    return FindingGraph(snapshotHash=snapshot_hash, findings=tuple(cards.values()))


__all__ = ["build_finding_graph", "project_analysis_findings"]
