"""冻结 planner 输出到现有 Coding runner 输入的确定性投影。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from ..agent import create_reporting_generator_agent
from ..models import ReportingError
from .benchmark_variants import (
    BenchmarkPlannerSpec,
    BenchmarkProjection,
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
    LegacyVisualizationPlanDraft,
    build_benchmark_planner_spec,
)
from .runtime.analysis import (
    adapt_legacy_visualization_plan,
    visualization_coding_facts,
    visualization_coding_plan,
)
from .runtime.analysis_item_workflow import AnalysisEvidenceDecision
from .runtime.base import (
    _ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS,
    _ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS,
)
from .runtime.phase_models import VisualizationPlanDraft

_VISUALIZATION_BENCHMARK_IDENTITY_INSTRUCTIONS = (
    "planner 请求中的 requiredCharts 是冻结的图表身份契约：必须逐字使用每项的 "
    "chartId、sourcePath、interactivePath（null 表示无交互产物）；"
    "不得新增、删除、改名图表或改动任何路径。",
)


def _identity_projection(payload):
    return payload


def build_benchmark_planner_agent(
    *,
    model: Any,
    task_kind: str,
    variant: BenchmarkVariant,
    planner_request: Mapping[str, Any] | None = None,
) -> tuple[BenchmarkPlannerSpec, Any]:
    """在首个 provider 请求前选择冻结 benchmark 的 schema 和指令。"""

    identity_instructions: tuple[str, ...] = ()
    if isinstance(planner_request, Mapping) and isinstance(
        planner_request.get("requiredCharts"), list
    ):
        identity_instructions = _VISUALIZATION_BENCHMARK_IDENTITY_INSTRUCTIONS
    if task_kind == "analysis":
        spec = build_benchmark_planner_spec(
            task_kind="analysis",
            variant=variant,
            legacy_output_schema=LegacyAnalysisEvidenceDecision,
            candidate_output_schema=AnalysisEvidenceDecision,
            legacy_instructions=_ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS,
            candidate_instructions=_ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS,
            legacy_project_coding_facts=_identity_projection,
            candidate_project_coding_facts=_identity_projection,
        )
    elif task_kind == "visualization":
        spec = build_benchmark_planner_spec(
            task_kind="visualization",
            variant=variant,
            legacy_output_schema=LegacyVisualizationPlanDraft,
            candidate_output_schema=VisualizationPlanDraft,
            legacy_instructions=identity_instructions,
            candidate_instructions=identity_instructions,
            legacy_project_coding_facts=_identity_projection,
            candidate_project_coding_facts=_identity_projection,
        )
    else:
        raise ValueError("task_kind 必须是 analysis 或 visualization")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=spec.output_schema,
        name=f"benchmark-{task_kind}-{variant.value}-planner",
        stage_instructions=spec.instructions,
    )
    return spec, agent


def _visualization_paths(plan: VisualizationPlanDraft) -> set[str]:
    return {
        path
        for chart in plan.charts
        for path in (chart.source_path, chart.interactive_path)
        if path is not None
    }


def _validate_required_charts_identity(
    plan: VisualizationPlanDraft, planner_request: Mapping[str, Any] | None
) -> None:
    """planner 签发计划与冻结 requiredCharts 的逐字身份校验（benchmark-only）。

    比 declared_output_paths 集合门禁更强：绑定 chartId ↔ 路径对，改名即拒绝。
    planner_request 缺 requiredCharts 时不校验（旧 bundle 兼容）。
    """
    if not isinstance(planner_request, Mapping):
        return
    required = planner_request.get("requiredCharts")
    if not isinstance(required, list):
        return
    for item in required:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("chartId"), str)
            or not item.get("chartId")
        ):
            raise ReportingError(
                "report_phase_contract_invalid",
                "requiredCharts 存在畸形条目（缺少非空字符串 chartId），应先修复冻结输入。",
            )
    required_by_id = {
        item["chartId"]: item
        for item in required
        if isinstance(item, Mapping) and isinstance(item.get("chartId"), str)
    }
    planned_by_id = {chart.chart_id: chart for chart in plan.charts}
    missing = sorted(set(required_by_id) - set(planned_by_id))
    unexpected = sorted(set(planned_by_id) - set(required_by_id))
    mismatches = []
    for chart_id in sorted(set(required_by_id) & set(planned_by_id)):
        required_item = required_by_id[chart_id]
        chart = planned_by_id[chart_id]
        if (
            chart.source_path != required_item.get("sourcePath")
            or chart.interactive_path != required_item.get("interactivePath")
        ):
            mismatches.append(chart_id)
    if missing or unexpected or mismatches:
        raise ReportingError(
            "report_phase_contract_invalid",
            "planner 图表身份与冻结 requiredCharts 不一致。",
            details={
                "missingChartIds": missing,
                "unexpectedChartIds": unexpected,
                "pathMismatches": mismatches,
            },
        )


def prepare_benchmark_coding_payload(
    *,
    task_kind: str,
    variant: BenchmarkVariant,
    execution_context: dict[str, Any],
    acceptance: dict[str, Any],
    planner_output: BaseModel,
    planner_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """生成现有 Coding replay payload；不执行模型、文件或工具调用。

    可视化路径在 declared_output_paths 差集门禁之前先执行 requiredCharts
    逐字身份校验（planner_request 携带该字段时）；改名或增删图表即拒绝。
    """

    coding_payload = deepcopy(execution_context.get("codingPayload"))
    if not isinstance(coding_payload, dict):
        raise ReportingError(
            "report_phase_contract_invalid", "benchmark executionContext 缺少 codingPayload。"
        )
    task = coding_payload.get("task")
    facts = coding_payload.get("facts")
    if not isinstance(task, dict) or not isinstance(facts, dict):
        raise ReportingError(
            "report_phase_contract_invalid", "benchmark codingPayload 缺少 task 或 facts。"
        )
    if task.get("task_kind") != task_kind:
        raise ReportingError(
            "report_phase_contract_invalid", "benchmark Coding taskKind 不一致。"
        )
    projection = BenchmarkProjection.for_variant(variant)

    if task_kind == "analysis":
        if "codingRequirements" in facts or "evidenceDecision" in facts:
            raise ReportingError(
                "report_phase_contract_invalid",
                "冻结分析 Coding 基础 facts 不得预置 evidenceDecision 或 codingRequirements。",
            )
        if variant is BenchmarkVariant.CANDIDATE:
            if not isinstance(planner_output, AnalysisEvidenceDecision):
                raise ReportingError(
                    "report_structured_output_invalid", "candidate 分析 planner 输出类型无效。"
                )
            if not planner_output.requires_supplemental_evidence:
                raise ReportingError(
                    "report_benchmark_coding_not_required",
                    "分析 planner 已确认无需 Coding，不应启动补证脚本阶段。",
                )
            facts["codingRequirements"] = [
                item.model_dump(mode="json", by_alias=True)
                for item in planner_output.coding_requirements
            ]
        else:
            if not isinstance(planner_output, LegacyAnalysisEvidenceDecision):
                raise ReportingError(
                    "report_structured_output_invalid", "legacy 分析 planner 输出类型无效。"
                )
            if not planner_output.requires_supplemental_evidence:
                raise ReportingError(
                    "report_benchmark_coding_not_required",
                    "分析 planner 已确认无需 Coding，不应启动补证脚本阶段。",
                )
            facts["evidenceDecision"] = planner_output.model_dump(
                mode="json", by_alias=True
            )
        return coding_payload

    if task_kind != "visualization":
        raise ReportingError(
            "report_phase_contract_invalid", "benchmark taskKind 必须是 analysis 或 visualization。"
        )
    if "visualizationPlan" in facts:
        raise ReportingError(
            "report_phase_contract_invalid",
            "冻结可视化 Coding 基础 facts 不得预置 visualizationPlan。",
        )
    if variant is BenchmarkVariant.CANDIDATE:
        if not isinstance(planner_output, VisualizationPlanDraft):
            raise ReportingError(
                "report_structured_output_invalid", "candidate 可视化 planner 输出类型无效。"
            )
        plan = planner_output
    else:
        if not isinstance(planner_output, LegacyVisualizationPlanDraft):
            raise ReportingError(
                "report_structured_output_invalid", "legacy 可视化 planner 输出类型无效。"
            )
        decisions = acceptance.get("decisionsByChartId")
        if not isinstance(decisions, dict):
            raise ReportingError(
                "report_phase_contract_invalid", "legacy 可视化验收缺少 decisionsByChartId。"
            )
        plan = adapt_legacy_visualization_plan(planner_output, decisions)

    _validate_required_charts_identity(plan, planner_request)

    declared_outputs = task.get("declared_output_paths")
    expected_paths = set(declared_outputs) if isinstance(declared_outputs, (list, tuple)) else set()
    planned_paths = _visualization_paths(plan)
    if not isinstance(declared_outputs, (list, tuple)) or expected_paths != planned_paths:
        raise ReportingError(
            "report_phase_contract_invalid", "planner 图表输出路径与冻结 Coding 上下文不一致。",
            details={
                "missingPaths": sorted(expected_paths - planned_paths),
                "unexpectedPaths": sorted(planned_paths - expected_paths),
            },
        )
    visualization_facts = facts.get("visualizationFacts")
    if not isinstance(visualization_facts, list):
        raise ReportingError(
            "report_phase_contract_invalid", "冻结可视化 Coding facts 缺少 visualizationFacts。"
        )
    facts["visualizationFacts"] = visualization_coding_facts(
        visualization_facts,
        plan=plan if projection.include_visual_bindings else None,
    )
    facts["visualizationPlan"] = visualization_coding_plan(
        plan, benchmark_projection=projection
    )
    return coding_payload
