"""把冻结分析事实投影为可编排的管理发现。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..profile.metric_usage import supplemental_metric_scope_issue
from .deterministic_analysis import DeterministicAnalysisBundle
from .findings import (
    EvidenceLevel,
    FindingCard,
    FindingGraph,
    FindingKind,
    FindingPriority,
    FindingSourceRef,
)

_CORRELATION_FINDING_MIN = 0.5
_CORRELATION_FINDING_LIMIT = 5


def _stable_id(analysis_id: str, path: str, snapshot_hash: str) -> str:
    digest = hashlib.sha256(f"{snapshot_hash}:{analysis_id}:{path}".encode()).hexdigest()[:16]
    return f"finding_{digest}"


def _source(analysis_id: str, path: str, file_sha256: str, pointer: str) -> FindingSourceRef:
    return FindingSourceRef(analysisId=analysis_id, path=path, fileSha256=file_sha256, pointer=pointer)


def _tuple_values(value: Any, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Normalize grain strings without fabricating dimensions from other types."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = tuple(value)
        for index, item in enumerate(values):
            if not isinstance(item, str):
                raise ValueError(f"grain[{index}] 必须是字符串")
        return values
    return fallback


def _direct_decomposition_source(
    item: Mapping[str, Any], reconciliation: Mapping[str, Any] | None,
    payload: Mapping[str, Any], partition_cache: dict[str, bool],
) -> tuple[int, Mapping[str, Any]] | None:
    """One complete registered partition must prove every part of the claim.

    A matching total from one fact and matching Top-N from another are not a
    decomposition. Supplemental passed flags never establish the population.
    """
    from ..trace.top_sets import registered_top_sets

    def number(value: Any) -> bool:
        try:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        except OverflowError:
            return False

    ids = item.get("sourceFactIds")
    if (not isinstance(ids, (list, tuple)) or len(ids) != 1 or not isinstance(ids[0], str)
            or reconciliation is None or reconciliation.get("passed") is not True
            or reconciliation.get("warnings") or item.get("directDecomposition") is not True):
        return None
    fact_id = ids[0]
    candidates = [(index, metric) for index, metric in enumerate(payload.get("metrics") or ())
                  if isinstance(metric, Mapping) and metric.get("factId") == fact_id]
    occurrences = sum(
        1 for collection in ("metrics", "derivedMetrics", "comparisons", "reconciliations", "correlationDetails")
        for entry in payload.get(collection) or ()
        if isinstance(entry, Mapping) and entry.get("factId") == fact_id
    )
    if len(candidates) != 1 or occurrences != 1:
        return None
    index, metric = candidates[0]
    if metric.get("aggregation") != "sum":
        return None
    for key in ("periodStart", "periodEnd", "unit"):
        if not isinstance(metric.get(key), str) or not metric[key].strip() or item.get(key) != metric[key]:
            return None
        if key in reconciliation and reconciliation[key] != metric[key]:
            return None
    for key in ("metricCodes", "periodRoles"):
        declared, registered = item.get(key), metric.get(key)
        if (not isinstance(declared, (list, tuple)) or not isinstance(registered, (list, tuple))
                or not registered or tuple(declared) != tuple(registered)):
            return None
    if (not metric.get("scope") or item.get("scope") != metric["scope"]
            or reconciliation.get("scope") != metric["scope"]
            or _tuple_values(reconciliation.get("grain")) != _tuple_values(item.get("grain"))):
        return None
    total = item.get("total")
    if (not number(total) or not number(metric.get("total")) or total != metric["total"]
            or any(not number(reconciliation.get(key)) or reconciliation[key] != total
                   for key in ("leftTotal", "rightTotal"))
            or ("difference" in reconciliation and (
                not number(reconciliation["difference"]) or reconciliation["difference"] != 0))):
        return None
    if fact_id not in partition_cache:
        try:
            _, reasons = registered_top_sets(metric)
            partition_cache[fact_id] = not reasons
        except (ValueError, TypeError, KeyError, ArithmeticError):
            partition_cache[fact_id] = False
    if not partition_cache[fact_id]:
        return None
    grain = set(_tuple_values(item.get("grain")))
    population = metric["groupPopulation"]
    if (not grain or grain != set(population[0]["groupValues"])
            or any(not number(group["value"]) for group in population)):
        return None
    expected = {tuple(sorted(group["groupValues"].items())): group["value"] for group in population}
    components = item.get("components")
    if not isinstance(components, (list, tuple)) or len(components) != len(expected):
        return None
    seen = set()
    for component in components:
        if not isinstance(component, Mapping) or not isinstance(component.get("groupValues"), Mapping):
            return None
        values = component["groupValues"]
        if set(values) != grain or any(not isinstance(value, str) for value in values.values()):
            return None
        identity = tuple(sorted(values.items()))
        if (identity in seen or identity not in expected or not number(component.get("value"))
                or component["value"] != expected[identity]):
            return None
        seen.add(identity)
    return index, metric


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
    metric_scope: Mapping[str, Any] | None = None,
) -> tuple[FindingCard, ...]:
    """只从已验证事实生成发现；缺失事实不会被改成零。"""

    payload = deterministic_facts.model_dump(mode="json", by_alias=True) if isinstance(deterministic_facts, DeterministicAnalysisBundle) else dict(deterministic_facts)
    partition_cache: dict[str, bool] = {}
    file_sha256 = fact_file_sha256 or hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    definitions = {str(item.get("code")): item for item in metric_definitions if item.get("code")}
    findings: list[FindingCard] = []
    rejected: list[str] = []

    def metric_label(fact: Mapping[str, Any]) -> str:
        # 显示名常带别名（“收入金额，也称医疗收入金额”）：发现标题只用主名称，别名进标题后会被
        # 拼进章节名和核心结论。
        if main := re.split(r"[，,；;]", str(fact.get('displayName') or ''), maxsplit=1)[0].strip():
            return main
        labels = {str(definitions[code]['description']) for code in fact.get('metricCodes', ())
                  if definitions.get(code, {}).get('description')}
        if not labels and fact.get('fieldRef'):
            labels = {
                str(item['displayName']) for item in payload.get('metrics', ())
                if isinstance(item, Mapping) and item.get('displayName')
                and item.get('fieldRef') == fact['fieldRef']
                and (not fact.get('currentDatasetId')
                     or item.get('datasetId') == fact['currentDatasetId'])
            }
        return next(iter(labels)) if len(labels) == 1 else str(fact.get('field') or '指标')

    def add(kind: FindingKind, path: str, title: str, summary: str, *, priority: FindingPriority = "medium", evidence: EvidenceLevel = "verified_fact", impact: float | None = None, unit: str | None = None, metrics: tuple[str, ...] = (), periods: tuple[str, ...] = ("current",), grain: tuple[str, ...] = (), limitations: tuple[str, ...] = ()) -> None:
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
            grain=_tuple_values(source_fact.get("grain"), grain), priority=priority, evidenceLevel=evidence, impactValue=impact,
            impactUnit=display_unit, actionability="unknown", citationIds=citation_ids,
            sourceRefs=(_source(analysis_id, fact_file_path, file_sha256, path),), limitations=limitations,
        ))

    for index, comparison in enumerate(payload.get("comparisons") or ()):
        if not isinstance(comparison, Mapping):
            continue
        change = comparison.get("change")
        metric = metric_label(comparison)
        unit = comparison.get("unit") if isinstance(comparison.get("unit"), str) else None
        add("comparison", f"/comparisons/{index}", f"{metric}比较变化", f"{metric}比较变化为 {change}。", priority="high" if isinstance(change, (int, float)) and abs(change) > 0 else "medium", impact=change if isinstance(change, (int, float)) else None, unit=unit, metrics=(metric,), periods=("current", "yoy" if comparison.get("comparisonType") == "yoy" else "mom"))

    for index, metric in enumerate(payload.get("metrics") or ()):
        if not isinstance(metric, Mapping):
            continue
        periods = metric.get("periodValues")
        if isinstance(periods, Sequence) and not isinstance(periods, (str, bytes)) and len(periods) >= 2:
            constant = len({item.get('value') for item in periods if isinstance(item, Mapping)}) == 1
            label = metric_label(metric)
            add("data_quality" if constant else "trend", f"/metrics/{index}/periodValues",
                f"{label}期间值一致" if constant else f"{label}趋势",
                f"已登记 {len(periods)} 个期间值，期间值一致。" if constant else f"已登记 {len(periods)} 个期间值，可用于趋势分析。",
                priority="low" if constant else "medium", metrics=(str(metric.get("field") or "指标"),),
                unit=metric.get("unit") if isinstance(metric.get("unit"), str) else None)

    for index, relation in enumerate(payload.get("reconciliations") or ()):
        if not isinstance(relation, Mapping):
            continue
        if relation.get("passed") is True:
            add("data_quality", f"/reconciliations/{index}", "指标对账通过", f"{relation.get('code', '指标')}已通过对账。", priority="low", metrics=(str(relation.get("leftMetric") or "指标"),))
        else:
            add("data_quality", f"/reconciliations/{index}", "指标对账待核对", f"{relation.get('code', '指标')}未通过对账。", priority="medium", evidence="evidence_missing", metrics=(str(relation.get("leftMetric") or "指标"),), limitations=("指标对账未通过",))

    # 每对指标的相关系数都成为发现时，回放中 183 条发现有 102 条是统计关系（含 r=0.005），
    # 规划出整章“相关不等于因果”的重复说明。只保留中等以上相关（|r|≥0.5）中最强的几对。
    correlations = sorted(
        ((index, detail) for index, detail in enumerate(payload.get("correlationDetails") or ())
         if isinstance(detail, Mapping) and isinstance(detail.get("value"), (int, float))
         and math.isfinite(detail["value"]) and abs(detail["value"]) >= _CORRELATION_FINDING_MIN),
        key=lambda item: abs(item[1]["value"]), reverse=True,
    )[:_CORRELATION_FINDING_LIMIT]
    for index, detail in sorted(correlations, key=lambda item: item[0]):
        add("impact", f"/correlationDetails/{index}", "指标存在统计关系", f"{detail.get('leftField', '指标')}与{detail.get('rightField', '指标')}相关系数{detail['value']:.2f}，存在统计关系，不能据此确认因果。", evidence="statistical_relation", metrics=(str(detail.get("leftField") or "指标"), str(detail.get("rightField") or "指标")), limitations=("仅有统计关系证据",))

    if supplemental_evidence is not None:
        if not supplemental_file_path or not supplemental_file_sha256:
            raise ValueError("补证发现必须绑定冻结文件身份")
        if supplemental_evidence.get("analysisId") != analysis_id:
            raise ValueError("补证文件的分析身份不一致")
        for index, item in enumerate(supplemental_evidence.get("findings") or ()):
            if not isinstance(item, Mapping):
                continue
            scope_codes = (metric_scope or {}).get("allowedMetricCodes")
            if scope_codes is None and any(metric.get("purpose") for metric in metric_definitions):
                # Without an explicit server scope, authorize only codes actually
                # present in frozen facts, never the whole multi-purpose catalog.
                scope_codes = tuple({
                    code for metric in payload.get("metrics", ()) if isinstance(metric, Mapping)
                    for code in metric.get("metricCodes", ()) if isinstance(code, str) and code in definitions
                })
            issue = supplemental_metric_scope_issue(
                item, allowed_codes=scope_codes,
                allowed_field_refs=(metric_scope or {}).get("allowedFieldRefs"),
            )
            if issue or item.get("metricScopeRejected") is True:
                rejected.append(f"补证 findings/{index} 未用于正文：{issue or '指标用途不匹配'}")
                continue
            pointer = f"/findings/{index}"
            name = str(item.get("name") or "补充分析发现")
            raw_scope = item.get("scope")
            scope_valid = raw_scope is None or (
                isinstance(raw_scope, Mapping)
                and len(raw_scope) <= 100
                and all(isinstance(key, str) and isinstance(value, str)
                        for key, value in raw_scope.items())
            )
            scope = dict(raw_scope or {}) if scope_valid else {}
            scope_limitations = () if scope_valid else (
                "范围字段 scope 格式无效，未用于范围匹配或直接归因；原始值保留在来源证据中。",
            )
            reconciliation_code = item.get("reconciliationCode")
            reconciliations = [
                    candidate for candidate in supplemental_evidence.get("reconciliations", ())
                    if isinstance(candidate, Mapping)
                    and isinstance(reconciliation_code, str) and reconciliation_code.strip()
                    and candidate.get("code") == reconciliation_code
            ]
            direct_source = (
                _direct_decomposition_source(item, reconciliations[0], payload, partition_cache)
                if item.get("kind") == "attribution" and scope_valid and len(reconciliations) == 1
                and not supplemental_evidence.get("warnings") else None
            )
            if direct_source is not None:
                source_index, source_metric = direct_source
                label = metric_label(source_metric)
                findings.append(FindingCard(
                    findingId=_stable_id(analysis_id, f"{supplemental_file_path}:{pointer}", snapshot_hash),
                    analysisIds=(analysis_id,), kind="attribution", title=f"{label}分组数值分解"[:200],
                    summary=f"{label}的完整分组数值与同一冻结指标登记合计闭合；不证明分类归属或业务因果。"[:4000],
                    metricCodes=tuple(item.get("metricCodes") or (analysis_id,)),
                    periodRoles=tuple(item.get("periodRoles") or ("current",)),
                    periodStart=item.get("periodStart"), periodEnd=item.get("periodEnd"),
                    grain=_tuple_values(item.get("grain")), scope=scope,
                    priority="high", evidenceLevel="direct_decomposition", actionability="unknown",
                    citationIds=citation_ids,
                    sourceRefs=(
                        _source(analysis_id, supplemental_file_path, supplemental_file_sha256, pointer),
                        _source(analysis_id, fact_file_path, file_sha256, f"/metrics/{source_index}"),
                    ),
                ))
                continue
            # 只登记证据的存在及原始位置，不从表格重新计算指标或因标题升级归因。
            kind = item.get("kind")
            attribution_unproven = kind == "attribution" or item.get("directDecomposition") is True
            if kind not in {"scale", "trend", "comparison", "anomaly", "impact", "data_quality"}:
                kind = "impact"
            findings.append(FindingCard(
                findingId=_stable_id(analysis_id, f"{supplemental_file_path}:{pointer}", snapshot_hash),
                analysisIds=(analysis_id,), kind=cast(FindingKind, kind), title=name[:200],
                summary=f"已登记补充证据：{name}"[:4000],
                metricCodes=tuple(item.get("metricCodes") or (analysis_id,)),
                periodRoles=tuple(item.get("periodRoles") or ("current",)),
                periodStart=item.get("periodStart"), periodEnd=item.get("periodEnd"),
                grain=_tuple_values(item.get("grain")), scope=scope,
                priority="medium", evidenceLevel="evidence_missing", actionability="unknown",
                citationIds=citation_ids,
                sourceRefs=(_source(analysis_id, supplemental_file_path, supplemental_file_sha256, pointer),),
                limitations=(tuple(str(warning) for warning in supplemental_evidence.get("warnings", ()) if warning)
                             + scope_limitations + (("直接分解未证明同期间、同范围、同单位及完整分组身份；不能据此归因或安排整改。",)
                                                    if attribution_unproven else ("补证仅完成文件登记，数值与业务表述尚未得到确定性验证。",)))[:100],
            ))
    if not findings:
        add("data_quality", "/warnings", "当前分析缺少可编排发现", "当前分析没有形成可用于正文的确定性发现。", priority="low", evidence="evidence_missing", limitations=tuple([*rejected, *(str(item) for item in payload.get("warnings", ()) if item)][:100]))
    elif rejected:
        add("data_quality", "/warnings", "部分补证指标用途不匹配", "部分补证超出分析指标用途，已保留其他有效发现。", evidence="evidence_missing", limitations=tuple(rejected[:100]))
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
    metric_scopes: Mapping[str, Mapping[str, Any]] | None = None,
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
                metric_scope=(metric_scopes or {}).get(analysis_id),
            )
            for card in projected:
                # 多个补证文件共享原子 facts；同一事实只登记一次，补证身份各自保留。
                cards.setdefault(card.finding_id, card)
    return FindingGraph(snapshotHash=snapshot_hash, findings=tuple(cards.values()))


__all__ = ["build_finding_graph", "project_analysis_findings"]
