"""矩阵测试复用生产规划Agent与字段契约，不自动评价业务语义。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from agno.agent import Agent

from smart_reporting.reporting.agent import _report_model
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _runtime(settings):
    return ReportWorkflowRuntime(
        db=SimpleNamespace(), reporting_agent_template=Agent(model=_report_model(
            settings, enable_thinking=False, retries=0)),
        task_runner=SimpleNamespace(), workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(), profiles=SimpleNamespace(), state_repository=SimpleNamespace(),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
    )


def validate_plan(plan, baseline):
    issues = []
    metrics = baseline["analysisContext"]["profile"]["metrics"]
    purposes = sorted({item["purpose"] for item in metrics if item.get("purpose")})
    try:
        bundle = AnalysisBundle.model_validate(plan, context={
            "new_analysis_plan": True, "require_metric_purposes": bool(purposes),
            "registered_metric_purposes": purposes,
        })
    except ValueError as error:
        return {"valid": False, "issues": [str(error)[:4000]], "analysisCount": 0, "requirementCount": 0}
    tables = {(table["sourceId"], table["table"]): table
              for schema in baseline["schemas"] for table in schema["tables"]}
    approved = {semantic["fieldRef"] for schema in baseline["schemas"]
                for semantic in schema.get("measureSemantics", [])}
    requirements = {item.requirement_id: item for item in bundle.requirements}
    if len(requirements) != len(bundle.requirements):
        issues.append("重复requirementId")
    if len({item.code for item in bundle.analyses}) != len(bundle.analyses):
        issues.append("重复analysis code")
    roles = {item["role"] for item in baseline["periodWindows"]["windows"]}
    for requirement in bundle.requirements:
        for candidate in requirement.tables:
            table = tables.get((requirement.source_id, candidate.table))
            if table is None:
                issues.append(f"未知表 {candidate.table}")
                continue
            columns = {item["name"] for item in table["columns"]}
            for name in (*requirement.dimension_columns, *requirement.grain_columns, candidate.period_column):
                if name not in columns:
                    issues.append(f"未知字段 {candidate.table}.{name}")
            for name in candidate.measure_columns:
                ref = f"{requirement.source_id}.{candidate.table}.{name}"
                if ref not in approved:
                    issues.append(f"未批准指标 {ref}")
            if (candidate.period_column, candidate.period_granularity) != (
                table.get("periodColumn"), table.get("periodGranularity")
            ):
                issues.append(f"期间字段或粒度错误 {candidate.table}")
        if not set(requirement.grain_columns) <= set(requirement.dimension_columns):
            issues.append(f"grain不属于dimensions {requirement.requirement_id}")
        if not set(requirement.comparison_roles or ()) <= roles:
            issues.append(f"非法比较角色 {requirement.requirement_id}")
        if len(requirement.tables) == 1 and requirement.relations:
            issues.append(f"单表不得生成关系 {requirement.requirement_id}")
        for relation in requirement.relations:
            if {relation.left_table, relation.right_table} - {item.table for item in requirement.tables}:
                issues.append(f"关系引用未知表 {requirement.requirement_id}")
            if set(relation.join_columns) != set(requirement.grain_columns):
                issues.append(f"关系未保持共同粒度 {requirement.requirement_id}")
    metric_by_ref = {item.get("fieldRef"): item for item in metrics}
    for analysis in bundle.analyses:
        if analysis.domain not in baseline["domains"] or not set(analysis.period_roles) <= roles:
            issues.append(f"非法domain或期间角色 {analysis.code}")
        for requirement_id in analysis.requirement_ids:
            requirement = requirements.get(requirement_id)
            if requirement is None:
                issues.append(f"引用未知requirement {requirement_id}")
                continue
            for table in requirement.tables:
                for name in table.measure_columns:
                    ref = f"{requirement.source_id}.{table.table}.{name}"
                    if metric_by_ref.get(ref, {}).get("purpose") not in analysis.metric_purposes:
                        issues.append(f"指标用途未覆盖 {analysis.code}:{ref}")
    return {"valid": not issues, "issues": issues, "analysisCount": len(bundle.analyses),
            "requirementCount": len(bundle.requirements)}
