"""对同一冻结输入比较原始、保守去重、按表聚合三种真实模型规划输入。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger
from pydantic import BaseModel, Field


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _without_empty_defaults(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_empty_defaults(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _without_empty_defaults(item) for key, item in value.items()
            if not (key in {"numeratorMetric", "denominatorMetric", "reconcileWith", "tolerance"}
                    and item is None)
            and not (key in {"reasons", "reconciliations"} and item == [])}


def _usage_groups(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for metric in metrics:
        if metric.get("purpose"):
            groups.setdefault(metric["purpose"], []).append(metric["code"])
    return [{"purpose": purpose, "metricCodes": codes} for purpose, codes in groups.items()]


def build_variants(original: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """仅变换模型投影，不生成业务事实，不修改原始输入。"""
    conservative = _without_empty_defaults(deepcopy(original))
    context = conservative.get("analysisContext", {})
    profile = context.get("profile", {})
    if context.get("metricUsageGroups") == _usage_groups(profile.get("metrics", [])):
        context.pop("metricUsageGroups", None)
    definitions = {(kind, item["code"]): item
                   for kind, key in (("metric", "metrics"), ("dimension", "dimensions"))
                   for item in profile.get(key, [])}
    unmatched = []
    for capability in context.pop("capabilities", []):
        target = definitions.get((capability.get("kind"), capability.get("code")))
        if target is None or "capability" in target:
            unmatched.append(capability)
        else:
            target["capability"] = {key: value for key, value in capability.items()
                                    if key not in {"kind", "code"}}
    if unmatched:
        context["capabilities"] = unmatched
    conservative["inputNotes"] = (
        "指标用途见 metrics[].purpose；可用能力就近列在指标或维度的 capability。"
        "省略的 null 计算引用及空 reasons/reconciliations 没有额外声明；"
        "additiveAcross 空数组仍表示未声明可加维度，不得扩大为任意可加。"
    )
    grouped = {key: deepcopy(value) for key, value in conservative.items()
               if key not in {"schemas", "analysisContext", "inputNotes"}}
    grouped["inputNotes"] = (
        "tables 每项绑定 sourceId 与 database.table；columns[].metrics 是已登记指标，"
        "columns[].measureSemantic 是已批准的数值语义，字段身份由 sourceId.table.column 完整恢复。"
        "columns[].dimensions 是逻辑维度；capability 就近声明可用性。"
        "measureColumns 只选具有 measureSemantic 的列。unboundMetrics/unboundDimensions"
        "未绑定当前候选 Schema，不能据此虚构可查询表。空 additiveAcross 不代表任意可加。"
        "observedDataFacts 保持原观测范围，未给出的同比覆盖不能从本期推断。"
    )
    grouped["profileIdentity"] = {key: deepcopy(value) for key, value in profile.items()
                                  if key not in {"metrics", "dimensions", "reconciliations"}}
    for key, value in context.items():
        if key not in {"profile", "observedDataFacts"}:
            grouped[key] = deepcopy(value)
    if profile.get("reconciliations"):
        grouped["profileReconciliations"] = deepcopy(profile["reconciliations"])
    all_metrics = profile.get("metrics", [])
    all_dimensions = profile.get("dimensions", [])
    bound_metric_ids: set[int] = set()
    bound_dimension_refs: set[str] = set()
    bound_semantics: set[str] = set()
    bound_observed: set[int] = set()
    grouped["tables"] = []
    for schema in conservative.get("schemas", []):
        semantics = {item["fieldRef"]: item for item in schema.get("measureSemantics", [])}
        for source_table in schema.get("tables", []):
            table = deepcopy(source_table)
            prefix = f"{table["sourceId"]}.{table["table"]}."
            for column in table["columns"]:
                ref = prefix + column["name"]
                semantic = semantics.get(ref)
                if semantic is not None:
                    column["measureSemantic"] = {key: deepcopy(value) for key, value in semantic.items()
                                                  if key != "fieldRef"}
                    bound_semantics.add(ref)
                metrics = []
                for index, metric in enumerate(all_metrics):
                    if metric.get("fieldRef") == ref:
                        metrics.append({key: deepcopy(value) for key, value in metric.items()
                                        if key != "fieldRef"})
                        bound_metric_ids.add(index)
                if metrics:
                    column["metrics"] = metrics
                dimensions = []
                for dimension in all_dimensions:
                    if ref in dimension.get("fieldRefs", []):
                        dimensions.append({key: deepcopy(value) for key, value in dimension.items()
                                           if key != "fieldRefs"})
                        bound_dimension_refs.add(ref)
                if dimensions:
                    column["dimensions"] = dimensions
            for index, observed in enumerate(context.get("observedDataFacts", [])):
                if (observed.get("sourceId"), observed.get("table")) == (table["sourceId"], table["table"]):
                    table["observedDataFacts"] = {key: deepcopy(value) for key, value in observed.items()
                                                  if key not in {"sourceId", "table"}}
                    bound_observed.add(index)
            grouped["tables"].append(table)
    unbound_metrics = [deepcopy(item) for index, item in enumerate(all_metrics)
                       if index not in bound_metric_ids]
    if unbound_metrics:
        grouped["unboundMetrics"] = unbound_metrics
    unbound_dimensions = [{**deepcopy(item), "fieldRefs": [ref for ref in item.get("fieldRefs", [])
                                                          if ref not in bound_dimension_refs]}
                          for item in all_dimensions
                          if any(ref not in bound_dimension_refs for ref in item.get("fieldRefs", []))]
    if unbound_dimensions:
        grouped["unboundDimensions"] = unbound_dimensions
    unbound_semantics = [deepcopy(item) for schema in conservative.get("schemas", [])
                         for item in schema.get("measureSemantics", [])
                         if item["fieldRef"] not in bound_semantics]
    if unbound_semantics:
        grouped["unboundMeasureSemantics"] = unbound_semantics
    extra_observed = [deepcopy(item) for index, item in enumerate(context.get("observedDataFacts", []))
                      if index not in bound_observed]
    if extra_observed:
        grouped["otherObservedDataFacts"] = extra_observed
    focused = {key: deepcopy(value) for key, value in grouped.items()
               if key not in {"profileIdentity", "terms", "tables", "inputNotes"}}
    semantics = [item for schema in original["schemas"]
                 for item in schema.get("measureSemantics", [])]
    focused["businessRules"] = {
        "terms": deepcopy(context.get("terms", [])),
        "fixedScopes": [{"fieldRef": item["fieldRef"], "exclusiveScope": deepcopy(item["exclusiveScope"])}
                        for item in semantics if item.get("exclusiveScope")],
        "additivity": "每个指标仅声明 additiveAcross 中的可加维度；空数组表示尚未声明，不能理解为全部可加。",
    }
    focused["dimensionDefinitions"] = [{key: deepcopy(value) for key, value in item.items()
                                        if key != "fieldRefs"} for item in all_dimensions]
    focused["tables"] = deepcopy(grouped["tables"])
    for table in focused["tables"]:
        for column in table["columns"]:
            if "dimensions" in column:
                column["dimensions"] = [item["code"] for item in column["dimensions"]]
    focused["inputNotes"] = (
        "businessRules 是输入已有业务口径的前置摘要，必须与对应字段语义共同遵守。"
        "tables 按 sourceId 与 database.table 定位，columns.name 为裸列名；"
        "columns.metrics 为已登记指标，measureSemantic 为已批准数值语义，"
        "measureColumns 只选具有 measureSemantic 的列。columns.dimensions 引用 "
        "dimensionDefinitions 的 code；其余未绑定项不能证明存在可查询表。"
        "原始输入未提供的期间覆盖、组织映射不能自行推断。"
    )
    conservative_focus = {"reportGoal": original["reportGoal"],
                          "businessRules": deepcopy(focused["businessRules"]),
                          **deepcopy(conservative)}
    conservative_focus["analysisContext"].pop("terms", None)
    return {"baseline": deepcopy(original), "conservative": conservative,
            "table_grouped": grouped, "semantic_focus": focused,
            "conservative_focus": conservative_focus}


def validate_plan(plan: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle

    issues: list[str] = []
    metrics = baseline["analysisContext"]["profile"]["metrics"]
    purposes = sorted({item["purpose"] for item in metrics if item.get("purpose")})
    try:
        bundle = AnalysisBundle.model_validate(plan, context={
            "new_analysis_plan": True, "require_metric_purposes": bool(purposes),
            "registered_metric_purposes": purposes,
        })
    except Exception as error:
        return {"valid": False, "issues": [str(error)[:4000]], "analysisCount": 0, "requirementCount": 0}
    tables = {(table["sourceId"], table["table"]): table
              for schema in baseline["schemas"] for table in schema["tables"]}
    approved = {semantic["fieldRef"] for schema in baseline["schemas"]
                for semantic in schema.get("measureSemantics", [])}
    requirements = {item.requirement_id: item for item in bundle.requirements}
    if len(requirements) != len(bundle.requirements):
        issues.append("重复 requirementId")
    if len({item.code for item in bundle.analyses}) != len(bundle.analyses):
        issues.append("重复 analysis code")
    roles = {item["role"] for item in baseline["periodWindows"]["windows"]}
    for requirement in bundle.requirements:
        for candidate in requirement.tables:
            table = tables.get((requirement.source_id, candidate.table))
            if table is None:
                issues.append(f"未知表 {requirement.source_id}.{candidate.table}")
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
            issues.append(f"grain 不属于 dimensions {requirement.requirement_id}")
        if requirement.comparison_roles and not set(requirement.comparison_roles) <= roles:
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
        if analysis.domain not in baseline["domains"]:
            issues.append(f"未知 domain {analysis.code}")
        if not set(analysis.period_roles) <= roles:
            issues.append(f"非法期间角色 {analysis.code}")
        for requirement_id in analysis.requirement_ids:
            requirement = requirements.get(requirement_id)
            if requirement is None:
                issues.append(f"引用未知 requirement {requirement_id}")
                continue
            for table in requirement.tables:
                for name in table.measure_columns:
                    ref = f"{requirement.source_id}.{table.table}.{name}"
                    metric = metric_by_ref.get(ref, {})
                    if metric.get("purpose") not in analysis.metric_purposes:
                        issues.append(f"指标用途未覆盖 {analysis.code}:{ref}")
    return {"valid": not issues, "issues": issues, "analysisCount": len(bundle.analyses),
            "requirementCount": len(bundle.requirements)}


def select_winner(summaries: list[dict[str, Any]]) -> str:
    baseline = next(item for item in summaries if item["variant"] == "baseline")
    eligible = [item for item in summaries if item["passRate"] >= baseline["passRate"]
                and item.get("criticalIssueCount", 0) == 0]
    if any("scopeUnderstood" in item for item in eligible):
        understood = [item for item in eligible if item.get("scopeUnderstood")]
        if understood:
            eligible = understood
    else:
        eligible = [item for item in eligible if item["qualityScore"] >= baseline["qualityScore"]]
    if not eligible:
        return "baseline"
    best_quality = max((item["passRate"], item["qualityScore"]) for item in eligible)
    eligible = [item for item in eligible if (item["passRate"], item["qualityScore"]) == best_quality]
    return min(eligible, key=lambda item: (item["inputTokens"], item["seconds"]))["variant"]


class Comprehension(BaseModel):
    annualBudgetDenominator: str
    expectedIncomeFormula: str
    incomeScope: str
    emptyAdditivityMeaning: str
    organizationAggregationRisk: str
    currentCoverage: str
    yoyCoverageKnown: bool
    yoyCoverageEvidence: str
    unsupportedDimensionMappings: list[str]
    projectBudgetAvailability: str
    costAndExpenditureInterchangeable: bool
    attributionEvidenceRequirement: str


class ReviewItem(BaseModel):
    candidateId: str
    requestCoverage: int = Field(ge=0, le=4)
    metricPurposes: int = Field(ge=0, le=4)
    periodsAndYoy: int = Field(ge=0, le=4)
    budgetDenominators: int = Field(ge=0, le=4)
    scopeAndGrain: int = Field(ge=0, le=4)
    evidenceAndGaps: int = Field(ge=0, le=4)
    atomicPlanQuality: int = Field(ge=0, le=4)
    criticalIssues: list[str]
    explanation: str


class ReviewBatch(BaseModel):
    reviews: list[ReviewItem]


COMPREHENSION_PROMPT = (
    "本次仅测输入理解，不生成报告、不执行工具。请仅依据输入如实说明：预算执行率分母、"
    "应完成收入公式、收入固定范围、空可加维度含义、组织重复累计风险、本期覆盖、"
    "是否有证据证明同比数据覆盖、条线与收入大类的映射缺口、项目预算可用性、"
    "全成本与实际支出是否可直接互换、归因证据要求。缺失信息明确未提供，不自行补全。"
)
REVIEW_PROMPT = (
    "你独立复核同一冻结输入产生的候选规划，候选ID不表示优劣。每项0至4分："
    "0缺失或错误，1严重不足，2部分覆盖，3基本正确，4完整且口径明确。"
    "评价需求覆盖、指标用途、本期同比角色、全年预算分母及应完成收入公式、固定开单收入范围"
    "与组织粒度、证据与未映射维度、原子问题与取数规划质量。不能要求规划输出契约"
    "不存在的字段；固定范围可由输入约束继承，未复述不自动判错。"
    "不能因输入本身缺少字段或数据而惩罚诚实披露；明确把条线/收入大类随意映射、"
    "把本期覆盖当同比覆盖、把1至9月预算当全年预算、成本支出直接互换为criticalIssues。"
    "同时参考候选的独立理解回答，回答正确不能抵消计划中的明确错误。"
    "criticalIssues必须给出候选原文逐字引句，不能把未提及当成明确断言，不能虚构引句。"
    "例如仅periodRoles含yoy不表示声称同比覆盖完整；未复述全年预算定义不等于使用了同期预算。"
    "原子分析数量多不等于章节多，不因数量本身加减分。"
    "每个candidateId恰好评价一次，解释给出具体依据。"
)


def _runtime(settings: Any) -> Any:
    from agno.agent import Agent
    from smart_reporting.reporting.agent import _report_model
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    return ReportWorkflowRuntime(
        db=SimpleNamespace(), reporting_agent_template=Agent(model=_report_model(
            settings, enable_thinking=False, retries=0)),
        task_runner=SimpleNamespace(), workspace_service=SimpleNamespace(),
        registry=SimpleNamespace(), profiles=SimpleNamespace(), state_repository=SimpleNamespace(),
        planner_enable_thinking=settings.report_enable_thinking,
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        planner_thinking_budget=settings.report_planner_thinking_budget,
    )


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(args: argparse.Namespace) -> int:
    from agno.run import RunContext
    from smart_reporting.reporting.structured_output.execution import StructuredOutputCallBudget
    from smart_reporting.runtime.settings import AgentSettings

    settings = AgentSettings.from_environment()
    baseline = json.loads(args.input.read_text(encoding="utf-8"))
    variants = build_variants(baseline)
    args.output.mkdir(parents=True, exist_ok=True)
    logger.add(args.output / "benchmark.log", encoding="utf-8")
    runtime = _runtime(settings)
    planner = runtime._analysis_agent
    # 无传输重试；框架协议降级若发生则完整记入 providerRequests。
    planner.model.retries = 0
    comprehension_agent = runtime._planning_agent(
        runtime.reporting_agent_template, "input-comprehension-benchmark", Comprehension,
        thinking_policy=planner._reporting_thinking, stage_instructions=(COMPREHENSION_PROMPT,),
    )
    review_agent = runtime._planning_agent(
        runtime.reporting_agent_template, "input-review-benchmark", ReviewBatch,
        thinking_policy=planner._reporting_thinking, stage_instructions=(REVIEW_PROMPT,),
    )
    comprehension_agent.model.retries = review_agent.model.retries = 0
    grouped_planner = planner.deep_copy()
    grouped_planner._reporting_thinking = planner._reporting_thinking
    replacements = {
        "measureColumns 只能复制 schemas[].measureSemantics[].fieldRef 最后一段中已批准的数值指标；分类字段放入 dimensionColumns；某张表没有任何 measureSemantics 时不得为该表生成 requirement":
        "measureColumns 只能从 tables[].columns 中具有 measureSemantic 的列复制 name；分类字段放入 dimensionColumns；没有批准指标的表不得生成 requirement",
    }
    grouped_planner.instructions = [replacements.get(item, item) for item in planner.instructions]
    semaphore = asyncio.Semaphore(args.concurrency)
    manifest = {
        "model": settings.model_standard_id, "structuredMode": settings.model_standard_structured_mode,
        "thinkingEnabled": settings.report_enable_thinking,
        "thinkingBudget": settings.report_planner_thinking_budget,
        "reasoningEffort": settings.report_planner_reasoning_effort,
        "repetitions": args.repetitions, "concurrency": args.concurrency,
        "inputSha256": hashlib.sha256(json_text(baseline).encode()).hexdigest(),
        "policy": "同输出契约、零业务纠错、记录协议请求；先质量后token；仅测试规划，不执行报告或SQL",
    }
    _write(args.output / "manifest.json", manifest)
    for name, payload in variants.items():
        _write(args.output / f"input-{name}.json", payload)
    _write(args.output / "planner-instructions.json", {
        "baseline": planner.instructions, "table_grouped": grouped_planner.instructions,
    })

    async def call(agent: Any, payload: dict[str, Any], label: str) -> dict[str, Any]:
        cached_path = args.output / f"{label}.json"
        if cached_path.exists():
            cached = json.loads(cached_path.read_text(encoding="utf-8"))
            same_review = not label.startswith("review-") or cached.get("requestSha256") == hashlib.sha256(json_text(payload).encode()).hexdigest()
            if not cached.get("error") and same_review:
                logger.info("benchmark_call_reused label={}", label)
                return cached
            if cached.get("error") and "report_thinking_policy_missing" not in cached["error"].get("message", ""):
                return cached
            if cached.get("error"):
                _write(args.output / f"{label}-harness-error.json", cached)
        async with semaphore:
            logger.info("benchmark_call_started label={} model={}", label, settings.model_standard_id)
            context = RunContext(run_id=str(uuid4()), session_id=f"benchmark-{uuid4()}",
                                 user_id="planner-input-benchmark", session_state={})
            metrics: dict[str, Any] = {}
            started = perf_counter()
            result: dict[str, Any] = {"label": label, "output": None, "error": None,
                                      "requestSha256": hashlib.sha256(json_text(payload).encode()).hexdigest()}
            def record(output: Any, count: int) -> None:
                value = getattr(output, "metrics", None)
                metrics.update(value.to_dict() if value is not None else {})
                metrics["modelRequestCount"] = count
            try:
                output = await asyncio.wait_for(runtime._run_planner(
                    agent, payload, context, call_budget=StructuredOutputCallBudget(max_model_calls=1),
                    model_metrics_recorder=record), timeout=args.timeout)
                result["output"] = output.model_dump(mode="json", by_alias=True)
            except Exception as error:
                result["error"] = {"type": type(error).__name__, "message": str(error)[:2000]}
            result.update({"seconds": round(perf_counter() - started, 3), "metrics": metrics,
                           "providerRequests": context.session_state.get("planner_request_metrics", [])})
            _write(args.output / f"{label}.json", result)
            logger.info("benchmark_call_finished label={} seconds={} error={}",
                        label, result["seconds"], result["error"])
            return result

    comprehensions = dict(zip(variants, await asyncio.gather(*(
        call(comprehension_agent, payload, f"comprehension-{name}")
        for name, payload in variants.items()
    ))))
    comprehension_repeats = {name: [value] for name, value in comprehensions.items()}
    for repetition in range(2, args.repetitions + 1):
        values = await asyncio.gather(*(
            call(comprehension_agent, payload, f"comprehension-{repetition}-{name}")
            for name, payload in variants.items()))
        for name, value in zip(variants, values):
            comprehension_repeats[name].append(value)
    runs: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for repetition in range(args.repetitions):
        # 轮换提交顺序，控制批次和时间偏差。
        names = list(variants)
        names = names[repetition % len(names):] + names[:repetition % len(names)]
        results = await asyncio.gather(*(
            call(grouped_planner if name in {"table_grouped", "semantic_focus"} else planner, variants[name],
                 f"plan-{repetition + 1}-{name}") for name in names))
        candidates = []
        mapping = {}
        for index, (name, result) in enumerate(zip(names, results)):
            validation = validate_plan(result["output"], baseline) if result["output"] else {
                "valid": False, "issues": ["模型未返回可用规划"], "analysisCount": 0, "requirementCount": 0}
            result.update({"variant": name, "repetition": repetition + 1, "validation": validation})
            runs.append(result)
            candidate_id = f"candidate-{index + 1}"
            mapping[candidate_id] = name
            candidates.append({"candidateId": candidate_id, "plan": result["output"],
                               "inputUnderstanding": comprehensions[name]["output"]})
        reviewed = await call(review_agent, {"originalInput": baseline, "candidates": candidates},
                              f"review-{repetition + 1}")
        reviewed["candidateMapping"] = mapping
        reviews.append(reviewed)
        _write(args.output / "progress.json", {"runs": runs, "reviews": reviews})
    summaries = []
    for name in variants:
        selected_runs = [item for item in runs if item["variant"] == name]
        ratings = [rating for review in reviews if review["output"]
                   for rating in review["output"]["reviews"]
                   if review["candidateMapping"].get(rating["candidateId"]) == name]
        scores = [sum(rating[key] for key in (
            "requestCoverage", "metricPurposes", "periodsAndYoy", "budgetDenominators",
            "scopeAndGrain", "evidenceAndGaps", "atomicPlanQuality")) / 28 * 100 for rating in ratings]
        if len(ratings) != args.repetitions or comprehensions[name]["error"]:
            quality = 0.0
        else:
            quality = statistics.mean(scores)
        critical_count = sum(len(rating["criticalIssues"]) for rating in ratings)
        scope_values = [str(value) for schema in baseline["schemas"]
                        for semantic in schema.get("measureSemantics", [])
                        for value in semantic.get("exclusiveScope", {}).values()]
        understood_count = sum(
            bool(item["output"]) and all(value in item["output"]["incomeScope"] for value in scope_values)
            for item in comprehension_repeats[name])
        # 模型复核发现明确关键口径错误时，限制为不具备推荐资格。
        passed = sum(item["validation"]["valid"] for item in selected_runs)
        input_tokens = [item["metrics"].get("input_tokens") for item in selected_runs
                        if isinstance(item["metrics"].get("input_tokens"), (int, float))]
        summaries.append({
            "variant": name, "passRate": passed / args.repetitions,
            "qualityScore": round(quality, 3), "criticalIssueCount": critical_count,
            "scopeUnderstood": understood_count == args.repetitions,
            "scopeComprehensionPasses": understood_count,
            "inputTokens": statistics.mean(input_tokens) if input_tokens else float("inf"),
            "inputCharacters": len(json_text(variants[name])),
            "inputUtf8Bytes": len(json_text(variants[name]).encode()),
            "seconds": statistics.mean(item["seconds"] for item in selected_runs),
            "analysisCounts": [item["validation"]["analysisCount"] for item in selected_runs],
            "requirementCounts": [item["validation"]["requirementCount"] for item in selected_runs],
        })
    winner = select_winner(summaries)
    report = {"manifest": manifest, "summaries": summaries, "winner": winner,
              "selectionNote": "有关键错误时不自动推荐；小样本结果不代表完整工作流验证",
              "comprehensions": comprehensions, "comprehensionRepeats": comprehension_repeats,
              "runs": runs, "reviews": reviews}
    _write(args.output / "results.json", report)
    logger.info("benchmark_finished summaries={} winner={}", summaries, winner)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10 or not 1 <= args.concurrency <= 3 or args.timeout < 1:
        parser.error("repetitions须为1—10，concurrency须为1—3，timeout须为正数")
    os.environ["AGENT_ENV_FILE"] = args.env_file
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
