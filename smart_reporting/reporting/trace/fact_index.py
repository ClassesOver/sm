"""确定性 facts 的稳定 ID、JSON Pointer 索引与输入关系（B2，未决#3 关闭）。

factId 是 bundle 内内容寻址的稳定标识：同一冻结 bundle 重读/重放得到相同
ID，条目顺序变化不影响（按内容而非位置寻址）。JSON Pointer 定位在冻结
文件身份内有效；旧 bundle（无 factId）仅可位置寻址，factKey 留空。

输入关系按 B0 未决#3 倾向实现：派生 fact 通过 metric code 关联分子/分母
对应的 metric facts；比较 fact 关联本期/基期 metric facts；对账 fact 关联
左右 metric facts。关系是数据依赖记录，不是可执行表达式（计划 3.1）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle

_POINTER_KIND_PREFIX = {
    "metric": "/metrics/",
    "comparison": "/comparisons/",
    "derived": "/derivedMetrics/",
    "reconciliation": "/reconciliations/",
    "correlation": "/correlationDetails/",
}


def _fact_id(identity: str) -> str:
    return "fact-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _scope_identity(scope: Mapping[str, str]) -> str:
    # 字段和值可含分隔符，必须编码结构，不能把单个值误读成另一个范围条件。
    return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _period_granularity_identity(fact: Any) -> str:
    grain = getattr(fact, "period_granularity", None)
    return f"|periodGranularity={grain}" if grain else ""


def metric_fact_identity(fact: Any) -> str:
    identity = "|".join(
        (
            "metric",
            fact.dataset_id,
            fact.field_ref,
            fact.aggregation,
            _scope_identity(fact.scope),
            fact.period_start or "",
            fact.period_end or "",
            fact.dataset_sha256,
            # 同一 CSV 在不同分析中可按不同组织粒度生成分组选择器。
            # topGroups.0 等 token 的含义取决于完整、有序的冻结分组结果。
            json.dumps({
                "topGroups": [(item.group, item.value) for item in fact.top_groups],
                "bottomGroups": [(item.group, item.value) for item in fact.bottom_groups],
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )
    )
    period_aggregation = getattr(fact, "period_aggregation", None)
    if any(item.group_values for item in (*fact.top_groups, *fact.bottom_groups)):
        identity += "|groupValues=" + json.dumps({
            "topGroups": [item.group_values for item in fact.top_groups],
            "bottomGroups": [item.group_values for item in fact.bottom_groups],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (identity + (f"|periodAggregation={period_aggregation}" if period_aggregation else "")
            + _period_granularity_identity(fact))


def comparison_fact_identity(fact: Any) -> str:
    identity = "|".join(
        (
            "comparison",
            fact.comparison_type,
            fact.field_ref,
            fact.current_dataset_id,
            fact.baseline_dataset_id,
            fact.current_dataset_sha256,
            fact.baseline_dataset_sha256,
        )
    ) + _period_granularity_identity(fact)
    start, end = getattr(fact, "baseline_period_start", None), getattr(fact, "baseline_period_end", None)
    if start or end:
        identity += f"|baselinePeriod={start or ''}:{end or ''}"
    inputs = getattr(fact, "input_fact_ids", ())
    if inputs:
        identity += "|inputFactIds=" + json.dumps(inputs, separators=(",", ":"))
    scale = getattr(fact, "baseline_scale", 1)
    return identity + (f"|baselineScale={scale}" if scale != 1 else "")


def derived_fact_identity(fact: Any) -> str:
    identity = "|".join(
        (
            "derived",
            fact.code,
            fact.period_role,
            fact.numerator_metric,
            fact.denominator_metric,
            ";".join(fact.dataset_sha256s),
        )
    ) + _period_granularity_identity(fact)
    inputs = getattr(fact, "input_fact_ids", ())
    if inputs:
        identity += "|inputFactIds=" + json.dumps(inputs, separators=(",", ":"))
    scale = getattr(fact, "denominator_scale", 1)
    return identity + (f"|denominatorScale={scale}" if scale != 1 else "")


def reconciliation_fact_identity(fact: Any) -> str:
    identity = "|".join(
        (
            "reconciliation",
            fact.code,
            fact.period_role,
            fact.left_metric,
            fact.right_metric,
            ";".join(fact.dataset_sha256s),
        )
    )
    inputs = getattr(fact, "input_fact_ids", ())
    if inputs:
        identity += "|inputFactIds=" + json.dumps(inputs, separators=(",", ":"))
    scale = getattr(fact, "right_scale", 1)
    if scale != 1:
        identity += f"|rightScale={scale}"
    unit = getattr(fact, "unit", None)
    if unit:
        identity += "|unit=" + json.dumps(unit, ensure_ascii=False)
    start, end = getattr(fact, "period_start", None), getattr(fact, "period_end", None)
    return (identity + (f"|period={start or ''}:{end or ''}" if start or end else "")
            + _period_granularity_identity(fact))


def correlation_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "correlation",
            fact.dataset_id,
            fact.dataset_sha256,
            fact.left_field,
            fact.right_field,
            fact.method,
            _scope_identity(fact.scope),
        )
    )


def assign_fact_ids(bundle: DeterministicAnalysisBundle) -> DeterministicAnalysisBundle:
    """为 bundle 四类条目赋 factId（内容寻址、bundle 内唯一）。

    同一身份在同一 bundle 内出现多次（理论上不该发生）时追加序号去重，
    保证 factId 唯一性不因重复数据破坏。
    """

    used: set[str] = set()

    def _unique(base_identity: str) -> str:
        fact_id = _fact_id(base_identity)
        suffix = 0
        while fact_id in used:
            suffix += 1
            fact_id = _fact_id(f"{base_identity}|#{suffix}")
        used.add(fact_id)
        return fact_id

    metrics = tuple(
        fact.model_copy(update={"fact_id": _unique(metric_fact_identity(fact))})
        for fact in bundle.metrics
    )
    comparisons = []
    for fact in bundle.comparisons:
        operands = [
            [metric for metric in metrics
             if metric.field_ref == fact.field_ref and metric.dataset_id == dataset_id]
            for dataset_id in (fact.current_dataset_id, fact.baseline_dataset_id)
        ]
        input_ids = tuple(items[0].fact_id for items in operands) if all(len(items) == 1 for items in operands) else ()
        frozen = fact.model_copy(update={"input_fact_ids": input_ids})
        comparisons.append(frozen.model_copy(update={"fact_id": _unique(comparison_fact_identity(frozen))}))
    derived = []
    for fact in bundle.derived_metrics:
        # 在基础事实签发后冻结有序依赖；相同 CSV、代码和比值也可能来自不同固定范围。
        operands = [
            [metric.fact_id for metric in metrics
             if code in metric.metric_codes and metric.dataset_id in fact.dataset_ids
             and fact.period_role in metric.period_roles]
            for code in (fact.numerator_metric, fact.denominator_metric)
        ]
        input_ids = tuple(ids[0] for ids in operands) if all(len(ids) == 1 for ids in operands) else ()
        frozen = fact.model_copy(update={"input_fact_ids": input_ids})
        derived.append(frozen.model_copy(update={"fact_id": _unique(derived_fact_identity(frozen))}))
    reconciliations = []
    for fact in bundle.reconciliations:
        operands = [
            [metric.fact_id for metric in metrics
             if code in metric.metric_codes and metric.dataset_id in fact.dataset_ids
             and fact.period_role in metric.period_roles]
            for code in (fact.left_metric, fact.right_metric)
        ]
        input_ids = tuple(ids[0] for ids in operands) if all(len(ids) == 1 for ids in operands) else ()
        frozen = fact.model_copy(update={"input_fact_ids": input_ids})
        reconciliations.append(frozen.model_copy(update={"fact_id": _unique(reconciliation_fact_identity(frozen))}))
    correlation_details = tuple(
        fact.model_copy(update={"fact_id": _unique(correlation_fact_identity(fact))})
        for fact in bundle.correlation_details
    )
    return bundle.model_copy(
        update={
            "metrics": metrics,
            "comparisons": tuple(comparisons),
            "derived_metrics": tuple(derived),
            "reconciliations": tuple(reconciliations),
            "correlation_details": correlation_details,
        }
    )


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def fact_pointer(bundle: DeterministicAnalysisBundle, fact_id: str) -> str | None:
    """factId → bundle 文件内的 JSON Pointer；未知 ID 返回 None。"""

    for index, fact in enumerate(bundle.metrics):
        if fact.fact_id == fact_id:
            return f"/metrics/{index}"
    for index, fact in enumerate(bundle.comparisons):
        if fact.fact_id == fact_id:
            return f"/comparisons/{index}"
    for index, fact in enumerate(bundle.derived_metrics):
        if fact.fact_id == fact_id:
            return f"/derivedMetrics/{index}"
    for index, fact in enumerate(bundle.reconciliations):
        if fact.fact_id == fact_id:
            return f"/reconciliations/{index}"
    for index, fact in enumerate(bundle.correlation_details):
        if fact.fact_id == fact_id:
            return f"/correlationDetails/{index}"
    return None


def fact_input_relations(
    bundle: DeterministicAnalysisBundle,
) -> dict[str, tuple[str, ...]]:
    """factId → 一层输入 factIds（派生/比较/对账 → metric facts）。

    匹配依据是权威 metric code（bundle 冻结时已拒绝无 metricCodes 的数值
    fact），不是含义可能重复的展示名。找不到输入 metric 时关系为空元组，
    读取层按 fact_binding_unavailable 处理，不伪造依赖。
    """

    metrics_by_code: dict[str, list[Any]] = {}
    for fact in bundle.metrics:
        for code in fact.metric_codes:
            metrics_by_code.setdefault(code, []).append(fact)

    relations: dict[str, tuple[str, ...]] = {}
    for fact in bundle.derived_metrics:
        if fact.input_fact_ids:
            known_ids = {metric.fact_id for metric in bundle.metrics}
            relations[fact.fact_id] = tuple(dict.fromkeys(
                fact_id for fact_id in fact.input_fact_ids if fact_id in known_ids
            ))
            continue
        inputs = [
            metric.fact_id
            for code in (fact.numerator_metric, fact.denominator_metric)
            for metric in metrics_by_code.get(code, ())
            if metric.dataset_id in fact.dataset_ids and fact.period_role in metric.period_roles
        ]
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    for fact in bundle.comparisons:
        if fact.input_fact_ids:
            known_ids = {metric.fact_id for metric in bundle.metrics}
            relations[fact.fact_id] = tuple(dict.fromkeys(
                fact_id for fact_id in fact.input_fact_ids if fact_id in known_ids
            ))
            continue
        inputs: list[str] = []
        for metric_fact in bundle.metrics:
            if (
                metric_fact.field_ref == fact.field_ref
                and metric_fact.dataset_id in (fact.current_dataset_id, fact.baseline_dataset_id)
            ):
                inputs.append(metric_fact.fact_id)
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    for fact in bundle.reconciliations:
        if fact.input_fact_ids:
            known_ids = {metric.fact_id for metric in bundle.metrics}
            relations[fact.fact_id] = tuple(dict.fromkeys(
                fact_id for fact_id in fact.input_fact_ids if fact_id in known_ids
            ))
            continue
        inputs = [
            metric.fact_id
            for code in (fact.left_metric, fact.right_metric)
            for metric in metrics_by_code.get(code, ())
            if metric.dataset_id in fact.dataset_ids and fact.period_role in metric.period_roles
        ]
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    return relations


def fact_binding_records(bundle: DeterministicAnalysisBundle) -> dict[str, dict[str, Any]]:
    """跨文件合并引用时连同实际输入身份比较，兼容尚未冻结 inputFactIds 的旧事实。"""
    inputs = fact_input_relations(bundle)
    # 新比较、对账已冻结输入身份，文件缺少输入条目时也不能把依赖签名改成子集。
    # 未冻结身份的旧记录仍从实际输入推导，以识别跨范围的旧 ID 冲突。
    inputs.update({fact.fact_id: fact.input_fact_ids
                   for fact in (*bundle.comparisons, *bundle.reconciliations) if fact.input_fact_ids})
    dependent_ids = {fact.fact_id for fact in (*bundle.derived_metrics, *bundle.comparisons,
                                              *bundle.reconciliations)}
    return {
        fact.fact_id: {"entry": fact.model_dump(mode="json", by_alias=True),
                       "inputs": inputs.get(fact.fact_id, ()) if fact.fact_id in dependent_ids else ()}
        for fact in (*bundle.metrics, *bundle.comparisons, *bundle.derived_metrics,
                     *bundle.reconciliations, *bundle.correlation_details)
        if fact.fact_id
    }


# 事实身份按数据集、字段、口径、期间与冻结值签发；以下字段是各分析自己的描述
# （未声明序列粒度的分析把月初标签记为 day，声明按月的分析记为 month），不改变冻结数值。
_ANALYSIS_LOCAL_FACT_FIELDS = frozenset({"periodGranularity", "displayName", "aliases", "metricCodes", "warnings"})
_GRANULARITY_RANK = {"day": 1, "month": 2, "year": 3}


def frozen_fact_content(record: Mapping[str, Any]) -> dict[str, Any]:
    """去掉分析级描述后的冻结内容，用于跨分析判断两条事实记录是否相同。"""
    return {key: value for key, value in record.items() if key not in _ANALYSIS_LOCAL_FACT_FIELDS}


def merge_frozen_fact(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """同一事实身份的两条记录：只差分析级描述时返回保留的一条，冻结数值或口径不同返回 None。"""
    if frozen_fact_content(existing) != frozen_fact_content(candidate):
        return None
    # 期间值相同而一方声明为月或年：标签已满足该粒度，采用声明的较粗粒度，与按月核对的分析一致。
    rank = _GRANULARITY_RANK.get
    return candidate if (rank(candidate.get("periodGranularity")) or 0) > (rank(existing.get("periodGranularity")) or 0) \
        else existing


def merge_binding_records(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """跨文件合并同一事实的绑定记录：实际输入与冻结内容一致时返回保留的一条，否则返回 None。"""
    if existing["inputs"] != candidate["inputs"]:
        return None
    entry = merge_frozen_fact(existing["entry"], candidate["entry"])
    return None if entry is None else existing if entry is existing["entry"] else candidate


def resolve_pointer_value(document: Any, pointer: str) -> Any:
    """在已解析的 bundle dict 上求值 RFC 6901 pointer；越界抛 KeyError。"""

    if pointer == "":
        return document
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            index = int(token)
            if not 0 <= index < len(current):
                raise KeyError(pointer)
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(pointer)
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def fact_entry_from_pointer(
    document: Mapping[str, Any], pointer: str
) -> tuple[str, Mapping[str, Any]]:
    """pointer → (factKind, fact 记录)；指针必须落在已知事实数组内。"""

    for kind, prefix in _POINTER_KIND_PREFIX.items():
        if pointer.startswith(prefix) and pointer[len(prefix) :].isdigit():
            index = int(pointer[len(prefix) :])
            array_name = {
                "metric": "metrics",
                "comparison": "comparisons",
                "derived": "derivedMetrics",
                "reconciliation": "reconciliations",
                "correlation": "correlationDetails",
            }[kind]
            array = document.get(array_name)
            if not isinstance(array, list) or index >= len(array):
                raise KeyError(pointer)
            entry = array[index]
            if not isinstance(entry, Mapping):
                raise KeyError(pointer)
            return kind, entry
    raise KeyError(pointer)

