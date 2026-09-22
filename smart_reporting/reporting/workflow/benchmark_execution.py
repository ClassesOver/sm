"""冻结 planner 输出到现有 Coding runner 输入的确定性投影。"""

from __future__ import annotations

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


def _identity_projection(payload):
    return payload


def build_benchmark_planner_agent(
    *, model: Any, task_kind: str, variant: BenchmarkVariant
) -> tuple[BenchmarkPlannerSpec, Any]:
    """在首个 provider 请求前选择冻结 benchmark 的 schema 和指令。"""

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
            legacy_instructions=(),
            candidate_instructions=(),
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


def prepare_benchmark_coding_payload(
    *,
    task_kind: str,
    variant: BenchmarkVariant,
    execution_context: dict[str, Any],
    acceptance: dict[str, Any],
    planner_output: BaseModel,
) -> dict[str, Any]:
    """生成现有 Coding replay payload；不执行模型、文件或工具调用。"""

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
