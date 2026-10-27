"""复杂 facts 计算记录服务（B4，计划 4.3 与 B0 未决#8）。

- ``build_supplemental_computation_record``：从补充分析执行事实构造
  ComputationRecordV1（服务端构造，模型不参与——计划 3.4：模型不自由
  签发来源、hash、路径或权限）。
- ``expand_computation_chain``：按 outputFactRefs → inputFactRefs 展开
  计算链，深度/节点受 B0 预算限制。
- ``detect_computation_cycles``：记录集合的依赖环检测（计划 5.3：拒绝
  循环依赖造成的无限遍历）。

旧回执无 environment 时 reproducibility=limited（未决#8 倾向）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from graphlib import CycleError, TopologicalSorter
from typing import Any

from ..models import ReportingError
from .contracts_v1 import (
    TRACE_BUDGETS_V1,
    ComputationRecordV1,
    FactRefV1,
)


def build_supplemental_computation_record(
    *,
    analysis_id: str,
    dataset_ids: Sequence[str],
    script_file: Mapping[str, Any],
    evidence_file: Mapping[str, Any],
    execution: Mapping[str, Any] | None = None,
    requirements: Sequence[Mapping[str, Any]] = (),
    finding_count: int = 0,
    input_fact_refs: Sequence[FactRefV1] = (),
) -> ComputationRecordV1:
    """为补充分析执行构造 ComputationRecordV1。

    ``script_file``/``evidence_file`` 是服务端已登记的 FileIdentity 形态
    dict（path/size/sha256）；``execution`` 是 ExecutionReceipt 形态
    （runId + environment）。输出 facts 指向 evidence 文件内的 findings
    数组条目；finding_count=0 时记录仍登记（失败执行也有据可查），但
    reproducibility 按 environment 有无判定。
    """

    execution_id = str((execution or {}).get("runId", "")) or None
    environment = (execution or {}).get("environment")
    environment = dict(environment) if isinstance(environment, Mapping) else None

    output_refs = tuple(
        FactRefV1(
            analysisId=analysis_id,
            fileResourceId=_resource_id(evidence_file),
            jsonPointer=f"/findings/rows/{index}",
            factKind="supplemental_finding",
        )
        for index in range(max(finding_count, 0))
    )

    if not output_refs:
        # 无 findings 的执行仍需至少一个输出锚点：指向 findings 数组本身，
        # 读取层按空结果处理，不伪造数值。
        output_refs = (
            FactRefV1(
                analysisId=analysis_id,
                fileResourceId=_resource_id(evidence_file),
                jsonPointer="/findings",
                factKind="supplemental_finding",
            ),
        )

    parameters = {
        "requirements": [
            {
                key: requirement.get(key)
                for key in ("datasetId", "fields", "calculation", "outputName")
                if requirement.get(key) is not None
            }
            for requirement in requirements
            if isinstance(requirement, Mapping)
        ][:100],
    }
    return ComputationRecordV1(
        computationId=_computation_id(analysis_id, script_file, evidence_file, execution),
        method="supplemental_analysis",
        parameters=parameters,
        inputDatasetIds=tuple(dict.fromkeys(dataset_ids))[:100],
        inputFactRefs=tuple(input_fact_refs)[:200],
        intermediateFileResourceIds=(),
        scriptFileResourceId=_resource_id(script_file),
        executionId=execution_id,
        environment=environment,
        outputFactRefs=output_refs,
        limitations=(
            "补充分析由受控脚本执行生成；数值核对状态以独立复算记录为准",
        ),
        verification="not_checked",
        reproducibility="reproducible" if environment else "limited",
    )


def build_standard_supplemental_computation_record(
    *,
    analysis_id: str,
    dataset_ids: Sequence[str],
    input_files: Sequence[Mapping[str, Any]],
    evidence_file: Mapping[str, Any],
    method: str,
    method_version: str,
    parameters: Mapping[str, Any],
    execution_id: str,
    finding_count: int,
) -> ComputationRecordV1:
    """Build server-computation trace without inventing a script identity."""

    output_refs = tuple(
        FactRefV1(
            analysisId=analysis_id,
            fileResourceId=_resource_id(evidence_file),
            jsonPointer=f"/findings/0/rows/{index}",
            factKind="supplemental_finding",
        )
        for index in range(max(finding_count, 0))
    )
    if not output_refs:
        output_refs = (
            FactRefV1(
                analysisId=analysis_id,
                fileResourceId=_resource_id(evidence_file),
                jsonPointer="/findings",
                factKind="supplemental_finding",
            ),
        )
    input_identities = [
        {key: item[key] for key in ("path", "size", "sha256") if key in item}
        for item in input_files
    ]
    identity = "|".join(
        (
            analysis_id,
            method,
            method_version,
            execution_id,
            str(evidence_file.get("path", "")),
            str(evidence_file.get("sha256", "")),
        )
    )
    return ComputationRecordV1(
        computationId="comp-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        method=method,
        methodVersion=method_version,
        parameters={**dict(parameters), "inputFiles": input_identities},
        inputDatasetIds=tuple(dict.fromkeys(dataset_ids))[:100],
        scriptFileResourceId=None,
        executionId=execution_id,
        outputFactRefs=output_refs,
        limitations=("服务端确定性计算；verification 未经独立复算。",),
        verification="not_checked",
        reproducibility="limited",
    )


def _resource_id(file: Mapping[str, Any]) -> str:
    from .contracts_v1 import derive_resource_id

    return derive_resource_id(str(file.get("path", "")))


def _computation_id(
    analysis_id: str,
    script_file: Mapping[str, Any],
    evidence_file: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
) -> str:
    identity = "|".join(
        (
            analysis_id,
            str(script_file.get("path", "")),
            str(script_file.get("sha256", "")),
            str(evidence_file.get("path", "")),
            str(evidence_file.get("sha256", "")),
            str((execution or {}).get("runId", "")),
        )
    )
    return "comp-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


_FactIdentity = tuple[str, str, str, str]
_OutputProviders = dict[_FactIdentity, dict[str | None, set[str]]]


def _fact_identity(ref: FactRefV1) -> _FactIdentity:
    # 位置身份与可选核对键分别索引，兼容旧记录但拒绝已知的 factKey 冲突。
    return ref.analysis_id, ref.file_resource_id, ref.json_pointer, ref.fact_kind


def _output_providers(
    records: Sequence[ComputationRecordV1],
) -> _OutputProviders:
    providers: _OutputProviders = {}
    for record in records:
        for ref in record.output_fact_refs:
            providers.setdefault(_fact_identity(ref), {}).setdefault(ref.fact_key, set()).add(record.computation_id)
    return providers


def _matching_providers(providers: _OutputProviders, ref: FactRefV1) -> set[str]:
    candidates = providers.get(_fact_identity(ref), {})
    if ref.fact_key is None:
        return set().union(*candidates.values())
    return candidates.get(ref.fact_key, set()) | candidates.get(None, set())


def detect_computation_cycles(records: Sequence[ComputationRecordV1]) -> list[list[str]]:
    """返回一个足以判定依赖无效的环（computationId 序列）；无环返回 []。

    依赖边：record A 的 inputFactRefs 与 record B 的 outputFactRefs 位置
    相同且核对键不冲突。发布方只需判断是否有环，不枚举所有路径或所有环。
    """

    output_providers = _output_providers(records)

    graph: dict[str, set[str]] = {}
    for record in records:
        dependencies: set[str] = set()
        for ref in record.input_fact_refs:
            providers = _matching_providers(output_providers, ref)
            if len(providers) == 1:
                dependencies.update(providers)
        graph[record.computation_id] = dependencies

    # 标准库按节点和边访问一次，避免菱形依赖图上的指数级重复遍历。
    try:
        TopologicalSorter({node: sorted(graph[node]) for node in sorted(graph)}).prepare()
    except CycleError as error:
        cycle = error.args[1]
        return [list(_canonical_cycle(cycle[:-1]))]
    return []


def _canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
    if not cycle:
        return ()
    rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
    return min(rotations)


def expand_computation_chain(
    records: Sequence[ComputationRecordV1],
    entry_computation_id: str,
    *,
    depth: int = 2,
) -> dict[str, Any]:
    """从入口计算记录沿输入依赖展开计算链（计划 5.1：一层按需加载扩展）。

    深度与节点数受 B0 预算限制；同一路径中的记录不重复展开（环短路）。
    """

    max_depth = TRACE_BUDGETS_V1["fact_expand_max_depth"]
    max_nodes = TRACE_BUDGETS_V1["fact_expand_max_nodes"]
    if not 1 <= depth <= max_depth:
        raise ReportingError("request_invalid", f"展开深度必须在 1~{max_depth} 之间。")
    by_id = {record.computation_id: record for record in records}
    if entry_computation_id not in by_id:
        raise ReportingError("source_missing", "计算记录不存在。")

    output_providers = _output_providers(records)

    node_count = 0

    def _node(
        record: ComputationRecordV1, remaining: int, ancestors: frozenset[str]
    ) -> dict[str, Any]:
        nonlocal node_count
        node_count += 1
        if node_count > max_nodes:
            raise ReportingError("resource_limit_exceeded", "计算链展开节点数超限。")
        node: dict[str, Any] = {
            "computationId": record.computation_id,
            "method": record.method,
            "executionId": record.execution_id,
            "verification": record.verification,
            "reproducibility": record.reproducibility,
        }
        ancestors = ancestors | {record.computation_id}
        inputs: list[dict[str, Any]] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for ref in record.input_fact_refs:
            providers = _matching_providers(output_providers, ref)
            if not providers and _fact_identity(ref) in output_providers:
                warnings.append(
                    f"事实 {ref.analysis_id} {ref.json_pointer} 的核对键与登记输出不一致，"
                    "无法确认该输入的计算链。"
                )
                continue
            if len(providers) > 1:
                warnings.append(
                    f"事实 {ref.analysis_id} {ref.json_pointer} 的计算来源不唯一，"
                    "无法确认该输入的计算链。"
                )
                continue
            if remaining <= 0:
                continue
            for provider_id in providers:
                if provider_id in seen or provider_id in ancestors:
                    continue
                seen.add(provider_id)
                inputs.append(_node(by_id[provider_id], remaining - 1, ancestors))
        if inputs:
            node["inputs"] = inputs
        if warnings:
            node["warnings"] = list(dict.fromkeys(warnings))
        return node

    return _node(by_id[entry_computation_id], depth - 1, frozenset())


__all__ = [
    "build_supplemental_computation_record",
    "build_standard_supplemental_computation_record",
    "detect_computation_cycles",
    "expand_computation_chain",
]
