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
from typing import Any, Mapping, Sequence

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

    script_path = str(script_file.get("path", ""))
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


def detect_computation_cycles(records: Sequence[ComputationRecordV1]) -> list[list[str]]:
    """返回计算记录依赖图中的所有环（computationId 序列）；无环返回 []。

    依赖边：record A 的 inputFactRefs 指向 record B 的 outputFactRefs 所在
    analysis（同 analysisId 判定）。自环与多节点环都返回。
    """

    output_by_analysis: dict[str, list[str]] = {}
    for record in records:
        for ref in record.output_fact_refs:
            output_by_analysis.setdefault(ref.analysis_id, []).append(record.computation_id)

    graph: dict[str, set[str]] = {}
    for record in records:
        dependencies: set[str] = set()
        for ref in record.input_fact_refs:
            for provider in output_by_analysis.get(ref.analysis_id, ()):
                if provider != record.computation_id:
                    dependencies.add(provider)
        graph[record.computation_id] = dependencies

    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    for start in graph:
        path: list[str] = []
        visited: set[str] = set()

        def _walk(node: str) -> None:
            if node in visited:
                if node == start:
                    canonical = _canonical_cycle(path)
                    if canonical not in seen_cycles:
                        seen_cycles.add(canonical)
                        cycles.append(list(path))
                return
            if node not in graph:
                return
            visited.add(node)
            path.append(node)
            for dependency in sorted(graph[node]):
                _walk(dependency)
            path.pop()
            visited.discard(node)

        _walk(start)
    return cycles


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

    深度与节点数受 B0 预算限制；同一记录不重复展开（环短路）。
    """

    max_depth = TRACE_BUDGETS_V1["fact_expand_max_depth"]
    max_nodes = TRACE_BUDGETS_V1["fact_expand_max_nodes"]
    if not 1 <= depth <= max_depth:
        raise ReportingError("request_invalid", f"展开深度必须在 1~{max_depth} 之间。")
    by_id = {record.computation_id: record for record in records}
    if entry_computation_id not in by_id:
        raise ReportingError("source_missing", "计算记录不存在。")

    output_analysis: dict[str, str] = {}
    for record in records:
        for ref in record.output_fact_refs:
            output_analysis.setdefault(ref.analysis_id, record.computation_id)

    node_count = 0

    def _node(record: ComputationRecordV1, remaining: int) -> dict[str, Any]:
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
        if remaining <= 0:
            return node
        inputs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in record.input_fact_refs:
            provider_id = output_analysis.get(ref.analysis_id)
            if provider_id is None or provider_id in seen:
                continue
            provider = by_id.get(provider_id)
            if provider is None:
                continue
            seen.add(provider_id)
            inputs.append(_node(provider, remaining - 1))
        if inputs:
            node["inputs"] = inputs
        return node

    return _node(by_id[entry_computation_id], depth - 1)


__all__ = [
    "build_supplemental_computation_record",
    "detect_computation_cycles",
    "expand_computation_chain",
]
