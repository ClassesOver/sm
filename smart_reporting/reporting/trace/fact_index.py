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
from typing import Any, Mapping

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle

FACT_ID_PATTERN = r"^fact-[0-9a-f]{16}$"

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
    return ";".join(f"{key}={scope[key]}" for key in sorted(scope))


def metric_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "metric",
            fact.dataset_id,
            fact.field_ref,
            fact.aggregation,
            _scope_identity(fact.scope),
            fact.period_start or "",
            fact.period_end or "",
            fact.dataset_sha256,
        )
    )


def comparison_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "comparison",
            fact.comparison_type,
            fact.field_ref,
            fact.current_dataset_id,
            fact.baseline_dataset_id,
            fact.current_dataset_sha256,
            fact.baseline_dataset_sha256,
        )
    )


def derived_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "derived",
            fact.code,
            fact.period_role,
            fact.numerator_metric,
            fact.denominator_metric,
            ";".join(fact.dataset_sha256s),
        )
    )


def reconciliation_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "reconciliation",
            fact.code,
            fact.period_role,
            fact.left_metric,
            fact.right_metric,
            ";".join(fact.dataset_sha256s),
        )
    )


def correlation_fact_identity(fact: Any) -> str:
    return "|".join(
        (
            "correlation",
            fact.dataset_id,
            fact.dataset_sha256,
            fact.left_field,
            fact.right_field,
            fact.method,
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
    comparisons = tuple(
        fact.model_copy(update={"fact_id": _unique(comparison_fact_identity(fact))})
        for fact in bundle.comparisons
    )
    derived = tuple(
        fact.model_copy(update={"fact_id": _unique(derived_fact_identity(fact))})
        for fact in bundle.derived_metrics
    )
    reconciliations = tuple(
        fact.model_copy(update={"fact_id": _unique(reconciliation_fact_identity(fact))})
        for fact in bundle.reconciliations
    )
    correlation_details = tuple(
        fact.model_copy(update={"fact_id": _unique(correlation_fact_identity(fact))})
        for fact in bundle.correlation_details
    )
    return bundle.model_copy(
        update={
            "metrics": metrics,
            "comparisons": comparisons,
            "derived_metrics": derived,
            "reconciliations": reconciliations,
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
        inputs = [
            metric.fact_id
            for code in (fact.numerator_metric, fact.denominator_metric)
            for metric in metrics_by_code.get(code, ())
            if metric.dataset_id in fact.dataset_ids and fact.period_role in metric.period_roles
        ]
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    for fact in bundle.comparisons:
        inputs: list[str] = []
        for metric_fact in bundle.metrics:
            if (
                metric_fact.field_ref == fact.field_ref
                and metric_fact.dataset_id in (fact.current_dataset_id, fact.baseline_dataset_id)
            ):
                inputs.append(metric_fact.fact_id)
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    for fact in bundle.reconciliations:
        inputs = [
            metric.fact_id
            for code in (fact.left_metric, fact.right_metric)
            for metric in metrics_by_code.get(code, ())
            if metric.dataset_id in fact.dataset_ids and fact.period_role in metric.period_roles
        ]
        relations[fact.fact_id] = tuple(dict.fromkeys(inputs))
    return relations


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


def correlation_pointer(correlation_key: str) -> str:
    return f"/correlations/{_escape_pointer_token(correlation_key)}"


def bundle_to_storable_json(bundle: DeterministicAnalysisBundle) -> bytes:
    """与既有落盘一致的 canonical JSON（analysis.py 使用的同款序列化）。"""

    return json.dumps(
        bundle.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
