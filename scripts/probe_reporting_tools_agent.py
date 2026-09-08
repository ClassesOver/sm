"""用真实模型验证当前 Reporting 工具 schema 的受控 test agent。"""
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Literal, cast

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))

from agno.models.message import Message  # noqa: E402 - 同上
from agno.run import RunContext  # noqa: E402 - 同上
from agno.tools import Function  # noqa: E402 - 同上

from smart_reporting.integrations.model_config import (  # noqa: E402 - 同上
    OPENAI_COMPATIBLE_ROLE_MAP,
    openai_compatible_extra_body,
)
from smart_reporting.model_routing.policy import build_model_profiles  # noqa: E402 - 同上
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
)  # noqa: E402 - 同上
from smart_reporting.reporting.instructions import (  # noqa: E402 - 同上
    REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS,
    REPORT_SECTION_AGENT_INSTRUCTIONS,
    REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS,
)
from smart_reporting.reporting.agent import (  # noqa: E402 - 同上
    ReportingPhaseOpenAIChat,
    _phase_filtered_report_tools,
    _report_model_tool_name,
    create_reporting_generator_agent,
)
from smart_reporting.reporting.phase import (  # noqa: E402 - 同上
    REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY,
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY,
    ReportingPhase,
    ReportingTaskKind,
    bind_reporting_run_context,
)
from smart_reporting.reporting.vision import ReportVisionReviewer  # noqa: E402 - 同上
from smart_reporting.reporting.tools.context import ReportingOutputPolicy  # noqa: E402 - 同上
from smart_reporting.reporting.tools.mock_workspace import MockReportingToolRuntime  # noqa: E402 - 同上
from smart_reporting.reporting.tools.toolkit import ReportingToolkit  # noqa: E402 - 同上
from smart_reporting.reporting.structured_output import (  # noqa: E402 - 同上
    REPORTING_STRUCTURED_MODES_MODEL_ATTR,
    ReportingStructuredOutputExecutor,
)
from smart_reporting.reporting.workflow.repository import ReportingStateRepository  # noqa: E402 - 同上
from smart_reporting.reporting.workflow.checkpoint import (  # noqa: E402 - 同上
    ChartVisualInspectionReceipt,
    FileIdentity,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (  # noqa: E402 - 同上
    AnalysisReworkDecision,
    ChartDraft,
    RenderSectionDecision,
    SectionDecision,
    SectionDecisionOutput,
    VisualizationScriptDraft,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (  # noqa: E402 - 同上
    AnalysisEvidenceDecision,
    AnalysisEvidencePlan,
    AnalysisItemWorkflow,
    AnalysisScriptDraft,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.section_workflow import (  # noqa: E402 - 同上
    SectionWorkflow,
)
from smart_reporting.reporting.workflow.runtime.sections import (  # noqa: E402 - 同上
    _generate_section_in_blocks,
    _section_claim_authoring_contract,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (  # noqa: E402 - 同上
    VisualizationSectionWorkflow,
)
from smart_reporting.runtime.settings import AgentSettings  # noqa: E402 - 同上
from smart_reporting.workspace import WorkspaceService  # noqa: E402 - 同上
from smart_reporting.task_execution import TaskExecutionScope  # noqa: E402 - 同上


@dataclass(frozen=True, slots=True)
class ProbeScenario:
    """一次真实模型调用应完成的、由回执驱动的 CLI 分支。"""

    name: str
    phase: ReportingPhase
    task_kind: ReportingTaskKind
    required_tools: tuple[str, ...]
    completion_tool: str
    branch: Literal[
        "fixed_facts",
        "profile",
        "script",
        "truncated",
        "inspection",
        "recovery",
        "preview",
        "render",
        "rework",
    ]

    @property
    def tool_names(self) -> tuple[str, ...]:
        """兼容探针报告的旧字段名，实际语义为当前分支的必要调用。"""

        return self.required_tools


@dataclass(slots=True)
class ProbeToolProjection:
    """记录每次真实模型请求可见的动态工具集合。"""

    batches: list[list[str]] = field(default_factory=list)
    not_visible_calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tools: Any) -> None:
        self.batches.append(
            sorted(name for name in (_report_model_tool_name(tool) for tool in tools or ()) if name)
        )


class ProbeReportingPhaseOpenAIChat(ReportingPhaseOpenAIChat):
    """仅记录探针观测值，动态过滤仍委托生产模型实现。"""

    _probe_projection: ProbeToolProjection

    def _project(self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]):
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        self._probe_projection.record(_phase_filtered_report_tools(messages, tools))
        return super()._project(messages, args, kwargs)

    def get_function_calls_to_run(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None = None,
    ) -> list[Any]:
        visible_tools = self._probe_projection.batches[-1] if self._probe_projection.batches else []
        for tool_call in assistant_message.tool_calls or ():
            function = tool_call.get("function") if isinstance(tool_call, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str) and name not in visible_tools:
                self._probe_projection.not_visible_calls.append(
                    {
                        "name": name,
                        "call_id": tool_call.get("id"),
                        "visible_tools": list(visible_tools),
                    }
                )
        return super().get_function_calls_to_run(assistant_message, messages, functions)


_TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "run_python_script": {"script_path": "analysis/output/probe.py", "timeout": 30},
    "read_file": {"path": "inputs/source.txt", "offset": 0, "max_bytes": 1024},
    "read_tool_output": {"handle": "mock-output-1", "offset": 0, "max_bytes": 1024},
    "apply_analysis_patch": {
        "patch": "--- /dev/null\n+++ b/analysis/output/probe_patch.txt\n@@ -0,0 +1 @@\n+value = 1"
    },
    "query_profile": {
        "datasetId": "dataset-001",
        "query": "values(variables)[0]",
        "purpose": "读取测试画像",
        "maxItems": 1,
    },
    "query_analysis_context": {
        "query": "datasets[0]",
        "purpose": "读取测试上下文",
        "maxItems": 1,
    },
    "query_analysis_facts": {
        "query": "metrics[0]",
        "purpose": "读取测试事实",
        "maxItems": 1,
    },
    "complete_analysis_item": {
        "analysisId": "analysis_001",
        "summary": "测试摘要。",
        "datasetIds": ["dataset-001"],
        "evidencePaths": [],
        "citationIds": ["citation-001"],
        "profileReadReceiptIds": [],
        "warnings": [],
    },
    "view_image": {"path": "analysis/charts/probe.png", "detail": "high"},
    "inspect_chart": {"path": "analysis/charts/probe.png", "detail": "high"},
    "submit_visualization_charts": {"sectionCode": "overview", "charts": []},
    "request_analysis_rework": {
        "analysisIds": ["analysis_001"],
        "reason": "测试返工。",
        "missingEvidence": ["测试证据"],
    },
    "render_report_section": {
        "sectionCode": "overview",
        "blocks": [{"blockId": "block-1", "markdown": "测试正文。"}],
        "claims": [],
    },
}


def probe_scenarios() -> tuple[ProbeScenario, ...]:
    """十个复杂 CLI 样本，覆盖三个 Reporting 固定工作流的主要分支。"""

    return (
        ProbeScenario(
            "analysis-fixed-facts",
            "analysis",
            "analysis_item",
            ("read_file", "complete_analysis_item"),
            "complete_analysis_item",
            "fixed_facts",
        ),
        ProbeScenario(
            "analysis-profile-bound-facts",
            "analysis",
            "analysis_item",
            ("read_file", "complete_analysis_item"),
            "complete_analysis_item",
            "profile",
        ),
        ProbeScenario(
            "analysis-script-foreground",
            "analysis",
            "analysis_item",
            (
                "read_file",
                "apply_analysis_patch",
                "run_python_script",
                "complete_analysis_item",
            ),
            "complete_analysis_item",
            "script",
        ),
        ProbeScenario(
            "analysis-truncated-output",
            "analysis",
            "analysis_item",
            ("read_file", "complete_analysis_item"),
            "complete_analysis_item",
            "truncated",
        ),
        ProbeScenario(
            "analysis-script-context",
            "analysis",
            "analysis_item",
            (
                "read_file",
                "apply_analysis_patch",
                "run_python_script",
                "complete_analysis_item",
            ),
            "complete_analysis_item",
            "script",
        ),
        ProbeScenario(
            "visualization-recovery",
            "analysis",
            "visualization_section",
            (
                "read_file",
                "apply_analysis_patch",
                "run_python_script",
                "inspect_chart",
                "submit_visualization_charts",
            ),
            "submit_visualization_charts",
            "recovery",
        ),
        ProbeScenario(
            "visualization-preview-truncated",
            "analysis",
            "visualization_section",
            (
                "apply_analysis_patch",
                "run_python_script",
                "view_image",
                "submit_visualization_charts",
            ),
            "submit_visualization_charts",
            "preview",
        ),
        ProbeScenario(
            "visualization-inspection",
            "analysis",
            "visualization_section",
            (
                "apply_analysis_patch",
                "run_python_script",
                "inspect_chart",
                "submit_visualization_charts",
            ),
            "submit_visualization_charts",
            "inspection",
        ),
        ProbeScenario(
            "section-render-truncated-evidence",
            "section",
            "section",
            ("read_file", "render_report_section"),
            "render_report_section",
            "render",
        ),
        ProbeScenario(
            "section-evidence-rework",
            "section",
            "section",
            ("read_file", "request_analysis_rework"),
            "request_analysis_rework",
            "rework",
        ),
    )


def _deterministic_facts_payload() -> dict[str, Any]:
    """返回可被生产 AnalysisItemWorkflow 严格校验的冻结 facts。"""

    dataset_sha256 = "d" * 64
    return {
        "version": "1",
        "analysisId": "analysis_001",
        "metrics": [
            {
                "datasetId": "dataset-001",
                "datasetSha256": dataset_sha256,
                "profileHash": "e" * 64,
                "periodRoles": ["current"],
                "metricCodes": ["outpatient_revenue"],
                "field": "revenue",
                "fieldRef": "revenue",
                "aggregation": "sum",
                "unit": "CNY",
                "formula": "sum(revenue)",
                "scope": {},
                "periodStart": "2025-01",
                "periodEnd": "2025-06",
                "total": 812,
                "missingCount": 0,
                "zeroCount": 0,
                "negativeCount": 0,
                "periodValues": [
                    {"period": "2025-01", "value": 120},
                    {"period": "2025-06", "value": 156},
                ],
                "topGroups": [],
                "bottomGroups": [],
                "warnings": [],
            }
        ],
        "derivedMetrics": [
            {
                "code": "outpatient_cost_rate",
                "kind": "ratio",
                "periodRole": "current",
                "numeratorMetric": "outpatient_cost",
                "denominatorMetric": "outpatient_revenue",
                "numerator": 482,
                "denominator": 812,
                "percentage": 0.594,
                "difference": 0.016,
                "unit": "%",
                "formula": "cost / revenue",
                "datasetIds": ["dataset-001"],
                "datasetSha256s": [dataset_sha256],
                "warnings": [],
            }
        ],
        "comparisons": [
            {
                "comparisonType": "yoy",
                "field": "revenue",
                "fieldRef": "revenue",
                "currentDatasetId": "dataset-001",
                "baselineDatasetId": "dataset-001",
                "currentDatasetSha256": dataset_sha256,
                "baselineDatasetSha256": dataset_sha256,
                "currentTotal": 812,
                "baselineTotal": 750,
                "change": 62,
                "changeRate": 0.082,
                "formula": "(812 - 750) / 750",
                "unit": "CNY",
                "warnings": [],
            }
        ],
        "reconciliations": [],
        "correlations": {},
        "warnings": ["2025-04 成本记录缺失，不能用零值替代。"],
    }


def _deterministic_facts_bytes() -> bytes:
    return json.dumps(
        _deterministic_facts_payload(), ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")


def _section_evidence_bytes(*, complete: bool) -> bytes:
    payload = {
        "evidencePath": (
            "analysis/evidence/complete_analysis_001.json"
            if complete
            else "analysis/evidence/analysis_001.json"
        ),
        "validated": True,
    }
    if complete:
        payload["periodCoverage"] = "2025-01 至 2025-06"
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _cli_stage_input(scenario: ProbeScenario) -> dict[str, Any]:
    """构造等价于 CLI 下发的阶段任务投影，不使用只为探针服务的工具清单字段。"""

    deterministic_facts = _deterministic_facts_payload()
    fact_bytes = _deterministic_facts_bytes()
    common = {
        "phase": scenario.phase,
        "taskKind": scenario.task_kind,
        "reportGoal": "识别某院 2025 年上半年门诊收入与成本变化，形成可执行的经营改进建议。",
        "sectionGoal": {
            "sectionCode": "outpatient_operation",
            "title": "门诊运营与收入质量",
            "focus": ["收入同比", "次均费用", "成本率", "异常波动"],
            "analysisIds": ["analysis_001"],
        },
        "datasets": [
            {
                "datasetId": "dataset-001",
                "path": "inputs/outpatient_monthly.csv",
                "period": "2025-01 至 2025-06",
                "organizationGrain": "院区-月份",
            }
        ],
    }
    fact_file = {
        "path": "analysis/facts/analysis_001.json",
        "size": len(fact_bytes),
        "sha256": hashlib.sha256(fact_bytes).hexdigest(),
    }
    evidence_bytes = _section_evidence_bytes(complete=False)
    complete_evidence_bytes = _section_evidence_bytes(complete=True)
    evidence_file = {
        "path": "analysis/evidence/analysis_001.json",
        "size": len(evidence_bytes),
        "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
    }
    complete_evidence_file = {
        "path": "analysis/evidence/complete_analysis_001.json",
        "size": len(complete_evidence_bytes),
        "sha256": hashlib.sha256(complete_evidence_bytes).hexdigest(),
    }
    if scenario.task_kind == "analysis_item":
        result: dict[str, Any] = {
            **common,
            "analysisId": "analysis_001",
            "currentAnalysisId": "analysis_001",
            "currentAnalysis": {
                "analysisId": "analysis_001",
                "managementQuestion": "门诊收入增长是否伴随成本率恶化，以及主要异常月份是什么？",
                "datasetIds": ["dataset-001"],
                "metrics": ["outpatient_revenue", "outpatient_cost", "cost_rate"],
                "limitations": ["4 月有一条成本记录缺失，不能用零值替代。"],
            },
            "deterministicFactFile": fact_file,
            "deterministicFacts": deterministic_facts,
            "analysisOutputRoot": "analysis/output",
            "citationRegistry": [{"citationId": "citation-001", "datasetId": "dataset-001"}],
            "completionConditions": ["对缺失成本记录失败关闭。", "提交绑定引用的分析终态。"],
        }
        if scenario.branch == "fixed_facts":
            result["executionDirective"] = (
                "固定 Workflow 必须先校验 deterministicFactFile；完整固定事实已足够，"
                "规划阶段不得补证，随后生成摘要并提交。"
            )
        elif scenario.branch == "profile":
            result["executionDirective"] = (
                "冻结 facts 已绑定已确认 Profile，当前管理问题不需要额外事实；规划阶段不得补证，"
                "随后生成摘要并提交。"
            )
        elif scenario.branch == "script":
            result["executionDirective"] = (
                "规划阶段必须返回最小补证脚本；由固定 Workflow 写入后通过 run_python_script "
                "执行 supplement.py、"
                "校验 supplement.json，随后生成摘要并提交。"
            )
            result["executionPlan"] = {"waitForCompletion": True}
        elif scenario.branch == "truncated":
            result["executionDirective"] = (
                "deterministicFactFile 必须按 offset 完整读取并校验；固定事实已足够，"
                "不得补证，随后生成摘要并提交。"
            )
        return result
    if scenario.task_kind == "visualization_section":
        result = {
            **common,
            "reportVisualTheme": {
                "name": "enterprise-tech-blue",
                "primary": "#0B4F8A",
                "accent": "#007EA7",
                "highlight": "#F2B134",
                "ink": "#1B2A41",
                "muted": "#5B6B7A",
                "grid": "#C7D7E5",
                "surface": "#EDF5FC",
                "chartPalette": ["#0B4F8A", "#007EA7", "#2F80ED"],
            },
            "visualInspectionMode": "vision",
            "visualizationFacts": [
                {
                    "analysisId": "analysis_001",
                    "factFile": fact_file,
                    "summary": "门诊收入同比增长 8.2%，成本率上升 1.6 个百分点。",
                    "metrics": [
                        {
                            "metricIndex": 0,
                            "datasetId": "dataset-001",
                            "field": "revenue",
                            "metricCodes": ["outpatient_revenue"],
                            "aggregation": "sum",
                            "unit": "CNY",
                            "periodRoles": ["current"],
                            "periodValueCount": 2,
                            "topGroupCount": 0,
                            "bottomGroupCount": 0,
                            "dataPaths": {
                                "metric": "metrics[0]",
                                "periodValues": "metrics[0].periodValues",
                                "topGroups": "metrics[0].topGroups",
                                "bottomGroups": "metrics[0].bottomGroups",
                            },
                        }
                    ],
                    "derivedMetrics": [],
                    "comparisons": [],
                    "evidenceFiles": [evidence_file],
                    "citationIds": ["citation-001"],
                }
            ],
            "visualizationWorkspace": {
                "scriptPath": "analysis/output/outpatient_chart.py",
                "chartOutputRoot": "analysis/charts/outpatient_operation",
            },
            "completionConditions": ["生成收入与成本率趋势图。", "提交本章图表。"],
        }
        if scenario.branch == "recovery":
            result["visualizationRecovery"] = True
            result["executionDirective"] = (
                "当前签发脚本来自上次失败尝试。先读取一次 visualizationWorkspace.scriptPath，"
                "再用回执中的文件 SHA 覆盖修复该脚本；执行签发脚本、正式审查最终图表后提交。"
            )
        elif scenario.branch == "preview":
            result["executionDirective"] = (
                "严格按以下顺序各调用一次：apply_analysis_patch 写入签发脚本，"
                "run_python_script 执行脚本，"
                "view_image 做临时预览，最后 submit_visualization_charts；不得调用 inspect_chart、"
                "read_file、read_tool_output 或重复执行。"
            )
        else:
            result["executionDirective"] = (
                "写入签发脚本并调用 run_python_script 执行；正式审查最终图表后提交。"
            )
            result["executionPlan"] = {"waitForCompletion": True}
        return result
    result = {
        **common,
        "sectionWorkItem": {
            "version": "1",
            "sectionCode": "outpatient_operation",
            "sectionNumber": "1",
            "title": "门诊运营与收入质量",
            "objective": "形成可执行的门诊经营改进建议。",
            "completionConditions": ["基于冻结证据提交章节正文，或在证据不足时提交返工请求。"],
            "analysisIds": ["analysis_001"],
            "evidence": [
                {
                    "analysisId": "analysis_001",
                    "summary": (
                        "门诊收入同比增长 8.2%，成本率上升 1.6 个百分点，证据已覆盖完整期间。"
                        if scenario.branch == "render"
                        else "门诊收入同比增长 8.2%，但 4 月成本证据缺失。"
                    ),
                    "datasetIds": ["dataset-001"],
                    "evidenceFiles": [
                        complete_evidence_file if scenario.branch == "render" else evidence_file
                    ],
                    "citationIds": ["citation-001"],
                    "metrics": ["outpatient_revenue", "outpatient_cost_rate"],
                    "chartIds": [],
                    "profileReadReceiptIds": [],
                    "warnings": [],
                }
            ],
            "metricDefinitions": [
                {
                    "code": "outpatient_revenue",
                    "name": "门诊收入",
                    "definition": "报告期间门诊收入合计。",
                    "unit": "CNY",
                    "periodBasis": "2025-01 至 2025-06",
                },
                {
                    "code": "outpatient_cost_rate",
                    "name": "门诊成本率",
                    "definition": "门诊成本除以门诊收入。",
                    "unit": "%",
                    "periodBasis": "2025-01 至 2025-06",
                },
            ],
            "managementQuestionCatalog": [
                {
                    "ref": "analysis_001",
                    "question": "门诊收入增长是否伴随成本率恶化，以及主要异常月份是什么？",
                }
            ],
            "profileReadReceipts": [],
            "profileReadReceiptIds": [],
            "citations": [
                {
                    "citationId": "citation-001",
                    "datasetId": "dataset-001",
                    "requirementId": "requirement-001",
                    "snapshotHash": "d" * 64,
                }
            ],
            "factSummaries": [
                "门诊收入同比增长 8.2%，成本率上升 1.6 个百分点，证据已覆盖完整期间。"
                if scenario.branch == "render"
                else "门诊收入同比增长 8.2%，但 4 月成本证据缺失。"
            ],
            "charts": [],
            "markdownRequirements": ["明确说明数据缺失限制。"],
        },
        "completionConditions": ["基于冻结证据提交章节正文，或在证据不足时提交返工请求。"],
    }
    if scenario.branch == "render":
        result["executionDirective"] = (
            "只读取 evidenceFiles 中的完整 evidence；首段会截断，必须按回执继续恢复。"
            "数值使用内联 factSummaries，不得读取 factFiles；当前 evidence 已覆盖所有期间，"
            "证据足够时只调用 render_report_section，禁止 request_analysis_rework。"
        )
    else:
        result["executionDirective"] = (
            "只读取 evidenceFiles 中的 evidence；数值使用内联 factSummaries，不得读取 factFiles。"
            "确认缺少 4 月成本证据后提交分析返工请求；读取回执完整且不含 handle。"
        )
    return result


def complex_cli_prompt(scenario: ProbeScenario) -> str:
    """用复杂阶段 JSON 模拟 CLI 转交给 Reporting Agent 的单个任务。"""

    task_json = json.dumps(_cli_stage_input(scenario), ensure_ascii=False, separators=(",", ":"))
    return f"""以下是 CLI 已签发的当前阶段任务 JSON。只处理该任务，不得访问未签发数据或调用未注册能力：
{task_json}

每次调用后以服务端回执决定下一步；只有回执给出 handle 时才使用对应续读能力。
终态提交后立即停止。不得输出解释文字。"""


def _agent_instructions(scenario: ProbeScenario) -> list[str]:
    if scenario.task_kind == "analysis_item":
        return list(REPORT_ANALYSIS_ITEM_AGENT_INSTRUCTIONS)
    if scenario.task_kind == "visualization_section":
        return list(REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS)
    return list(REPORT_SECTION_AGENT_INSTRUCTIONS)


def _probe_visible_tool_names(context: RunContext, tools: list[Function]) -> set[str]:
    with bind_reporting_run_context(context):
        return {
            name
            for name in (
                _report_model_tool_name(tool)
                for tool in _phase_filtered_report_tools(
                    [Message(role="user", content="probe")], tools
                )
            )
            if name
        }


@dataclass(slots=True)
class ProbeRecorder:
    """保留 test agent 的工具调用，不持有任何生产连接。"""

    runtime: MockReportingToolRuntime
    scenario: ProbeScenario | None = None
    run_context: RunContext | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    output_handle: str | None = None
    output_consumed: bool = False
    script_completed: bool = False
    committed_script_path: str | None = None
    committed_script_sha256: str | None = None
    tools: list[Function] = field(default_factory=list)

    async def prepare(self) -> None:
        if self.scenario is None or self.scenario.branch != "recovery":
            return
        identity = await self.runtime.workspace.write_text(
            "analysis/output/outpatient_chart.py",
            "raise RuntimeError('previous attempt failed')\n",
        )
        self.committed_script_path = identity.path
        self.committed_script_sha256 = identity.sha256

    def _truncated(self) -> bool:
        return self.scenario is not None and self.scenario.branch in {
            "truncated",
            "preview",
            "render",
        }

    def _file_read_truncated(self) -> bool:
        return self.scenario is not None and self.scenario.branch in {"preview", "render"}

    def _stage_read_paths(self) -> set[str] | None:
        """返回当前阶段可消费的冻结文件；None 仅用于无场景的 schema 单测。"""

        if self.scenario is None:
            return None
        if self.scenario.task_kind == "analysis_item":
            paths = {"analysis/facts/analysis_001.json"}
            if self.committed_script_path is not None:
                paths.add(self.committed_script_path)
            if self.script_completed:
                paths.add("analysis/output/supplement.json")
            return paths
        if self.scenario.task_kind == "visualization_section":
            return {self.committed_script_path} if self.committed_script_path is not None else set()
        work_item = _cli_stage_input(self.scenario)["sectionWorkItem"]
        return {
            str(file["path"])
            for evidence in work_item["evidence"]
            for file in evidence["evidenceFiles"]
        }

    def _issued_script_path(self) -> str | None:
        if self.scenario is None:
            return None
        if self.scenario.task_kind == "visualization_section":
            return "analysis/output/outpatient_chart.py"
        if self.scenario.task_kind == "analysis_item" and self.scenario.branch in {
            "profile",
            "script",
        }:
            return "analysis/output/supplement.py"
        return None

    def _reject(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        required_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        result = {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "retryable": True,
        }
        if details is not None:
            result["details"] = details
        if required_actions is not None:
            result["requiredActions"] = required_actions
        self.failures.append(result)
        return result

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        visible_tools = (
            sorted(_probe_visible_tool_names(self.run_context, self.tools))
            if self.run_context is not None
            else sorted(tool.name for tool in self.tools)
        )
        self.calls.append(
            {
                "name": name,
                "arguments": deepcopy(arguments),
                "visible_tools": visible_tools,
            }
        )
        workspace = self.runtime.workspace
        if name == "read_file":
            path = str(arguments["path"])
            allowed_paths = self._stage_read_paths()
            if allowed_paths is not None and path not in allowed_paths:
                return self._reject(
                    "probe_stage_read_path_forbidden",
                    "当前阶段只能读取 CLI 已签发的冻结文件。",
                    details={"allowedPaths": sorted(allowed_paths)},
                    required_actions=["只读取 details.allowedPaths 中的当前阶段文件。"],
                )
            try:
                raw_content = await workspace.read_bytes(path)
            except Exception:
                # 生产脚本可以在签发输出根目录生成补充 evidence。探针只在脚本已完成后
                # 接受这类派生文件，避免将任意不存在路径误报为有效输入。
                if not self.script_completed or not path.startswith("analysis/output/evidence/"):
                    if not self.script_completed or path != "analysis/output/supplement.json":
                        raise
                identity = await workspace.write_text(
                    path,
                    json.dumps(
                        {
                            "analysisId": "analysis_001",
                            "datasetIds": ["dataset-001"],
                            "findings": [
                                {
                                    "metricCode": "outpatient_cost_rate",
                                    "value": 0.594,
                                    "missingMonth": "2025-04",
                                }
                            ],
                            "reconciliations": [{"name": "outpatient_cost_rate", "passed": True}],
                            "warnings": ["2025-04 成本缺失，未按零值填充。"],
                        },
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                )
                raw_content = await workspace.read_bytes(identity.path)
            if self.scenario is not None and self.scenario.task_kind == "analysis_item":
                offset = int(arguments.get("offset", 0))
                max_bytes = int(arguments.get("max_bytes", len(raw_content)))
                end = min(len(raw_content), offset + max_bytes)
                if self.scenario.branch == "truncated" and path.endswith("analysis_001.json"):
                    end = min(end, offset + max(1, len(raw_content) // 2))
                return {
                    "ok": True,
                    "content": raw_content[offset:end].decode("ascii"),
                    "sha256": hashlib.sha256(raw_content).hexdigest(),
                    "totalBytes": len(raw_content),
                    "nextOffset": end,
                    "hasMore": end < len(raw_content),
                    "outputTruncated": False,
                }
            if self.scenario is not None and self.scenario.task_kind == "section":
                offset = int(arguments.get("offset", 0))
                end = len(raw_content)
                if self.scenario.branch == "render" and offset == 0:
                    end = max(1, len(raw_content) // 2)
                return {
                    "ok": True,
                    "path": path,
                    "offset": offset,
                    "content": raw_content[offset:end].decode("utf-8"),
                    "sha256": hashlib.sha256(raw_content).hexdigest(),
                    "totalBytes": len(raw_content),
                    "nextOffset": end,
                    "hasMore": end < len(raw_content),
                }
            content = raw_content.decode("utf-8")
            if (
                self._file_read_truncated()
                and not self.output_consumed
                and self.output_handle is None
            ):
                self.output_handle = "mock-output-1"
                return {
                    "ok": True,
                    "content": content[:24],
                    "truncated": True,
                    "handle": self.output_handle,
                    "nextOffset": 24,
                }
            response = {"ok": True, "content": content}
            if self.scenario is not None and self.scenario.branch == "recovery":
                # 生产 Reporting 包装会在 recovery 读取成功后追加同一机器可读契约；
                # probe 绕过 Toolkit 执行包装，因此必须在 mock 边界保持回执同形。
                response["nextTool"] = "apply_analysis_patch"
                response["requiredFields"] = ["patch", "expected_sha256"]
            return response
        if name == "run_python_script":
            script_path = str(arguments["script_path"])
            issued_script_path = self._issued_script_path()
            if issued_script_path is not None and script_path != issued_script_path:
                return self._reject(
                    "probe_script_path_forbidden",
                    "当前阶段 run_python_script 只允许执行签发脚本。",
                    details={"scriptPath": issued_script_path},
                    required_actions=[
                        "仅将 details.scriptPath 原样作为 run_python_script.script_path。"
                    ],
                )
            if self.scenario is not None and self.scenario.task_kind == "visualization_section":
                if self.committed_script_path is None:
                    return self._reject(
                        "probe_script_not_committed",
                        "必须先提交 CLI 签发的可视化脚本。",
                        required_actions=[
                            "先用 apply_analysis_patch 提交 visualizationWorkspace.scriptPath。"
                        ],
                    )
            if (
                self.scenario is not None
                and self.scenario.branch == "script"
                and self.committed_script_path is None
            ):
                return self._reject(
                    "probe_script_not_committed",
                    "必须先提交核验脚本。",
                    required_actions=["先用 apply_analysis_patch 提交核验脚本。"],
                )
            result = await workspace.execute_script(
                script_path,
                timeout=int(arguments.get("timeout", 30)),
            )
            response = {"ok": True, **dict(result)}
            if ".py" in script_path:
                self.script_completed = True
                response["stdout"] = (
                    "script completed; generated evidence and chart artifacts are ready"
                )
            if (
                self.scenario is not None
                and self.scenario.branch == "truncated"
                and not self.output_consumed
                and self.output_handle is None
            ):
                self.output_handle = "mock-output-1"
                response.update({"truncated": True, "handle": self.output_handle})
            return response
        if name == "apply_analysis_patch":
            match = re.search(r"^\+\+\+ b/(.+)$", str(arguments["patch"]), re.MULTILINE)
            path = match.group(1) if match is not None else "analysis/output/probe.py"
            if (
                self.scenario is not None
                and self.scenario.task_kind == "visualization_section"
                and path != "analysis/output/outpatient_chart.py"
            ):
                return self._reject(
                    "probe_visualization_write_forbidden",
                    "visualization 只能写入 CLI 签发的图表脚本。",
                    details={"scriptPath": "analysis/output/outpatient_chart.py"},
                    required_actions=["只使用 apply_analysis_patch 写入 details.scriptPath。"],
                )
            overwrite = path == self.committed_script_path
            identity = await workspace.write_text(
                path,
                "print('probe')\n",
                overwrite=overwrite,
                expected_sha256=self.committed_script_sha256 if overwrite else None,
            )
            self.committed_script_path = identity.path
            self.committed_script_sha256 = identity.sha256
            state = self.run_context.session_state if self.run_context is not None else None
            if isinstance(state, dict):
                state[REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY] = True
            return {
                "ok": True,
                "status": "committed",
                "artifacts": [{"path": identity.path, "sha256": identity.sha256}],
            }
        if name == "query_profile":
            return {
                "ok": True,
                "datasetId": "dataset-001",
                "query": "values(variables)[0]",
                "value": {
                    "revenue": {"min": 120, "max": 156, "nullCount": 0},
                    "cost": {"min": 78, "max": 101, "nullCount": 1},
                },
                "truncated": False,
                "readReceipt": {
                    "receiptId": "profile-receipt-1",
                    "datasetId": "dataset-001",
                    "query": "values(variables)[0]",
                },
            }
        if name == "query_analysis_context":
            return {
                "ok": True,
                "items": [{"datasetId": "dataset-001", "period": "2025-01 至 2025-06"}],
            }
        if name == "query_analysis_facts":
            return {
                "ok": True,
                "analysisIds": ["analysis_001"],
                "query": arguments["query"],
                "value": [
                    {
                        "metricCodes": ["outpatient_cost"],
                        "total": 482,
                        "missingCount": 1,
                        "periodValues": [
                            {"period": "2025-01", "value": 78},
                            {"period": "2025-04", "value": None},
                            {"period": "2025-06", "value": 101},
                        ],
                        "warnings": ["2025-04 成本缺失，不能用零值替代。"],
                    },
                ],
                "truncated": False,
                "itemLimit": min(int(arguments.get("maxItems", 50)), 50),
            }
        if name == "read_tool_output":
            if self.output_handle is None or arguments.get("handle") != self.output_handle:
                if self.scenario is not None and self.scenario.branch == "rework":
                    return {"ok": True, "status": "complete", "content": "无额外截断输出。"}
                return self._reject(
                    "probe_output_handle_invalid", "必须使用本轮截断回执给出的 handle。"
                )
            self.output_consumed = True
            return {"ok": True, "content": "剩余受信输出。", "truncated": False}
        if name == "view_image":
            return {"ok": True, "status": "previewed", "path": arguments.get("path")}
        if name == "inspect_chart":
            return {
                "ok": True,
                "status": "passed",
                "path": arguments.get("path"),
                "sha256": "a" * 64,
                "receiptId": "chart-receipt-1",
            }
        if name in {
            "complete_analysis_item",
            "render_report_section",
            "submit_visualization_charts",
            "request_analysis_rework",
        }:
            # 生产阶段终态回执带 taskFinished，Toolkit 的 post_hook 据此停止当前 run；
            # mock 必须保留同一终态语义，否则会把已接受后的追加调用误判成模型不稳定。
            return {"ok": True, "status": "accepted", "taskFinished": True, "tool": name}
        return {"ok": True, "status": "accepted", "tool": name}


def build_mock_probe_tools(
    phase: ReportingPhase,
    task_kind: ReportingTaskKind,
    runtime: MockReportingToolRuntime,
    scenario: ProbeScenario | None = None,
    run_context: RunContext | None = None,
) -> tuple[list[Function], ProbeRecorder]:
    """从当前 Toolkit 提取 schema，并以 mock workspace 替换执行入口。"""

    toolkit = ReportingToolkit(
        cast(WorkspaceService, object()),
        object(),
        state_repository=cast(ReportingStateRepository, object()),
        vision_reviewer=cast(ReportVisionReviewer, object()),
        phase=phase,
        task_kind=task_kind,
    )
    recorder = ProbeRecorder(runtime, scenario, run_context)
    tools: list[Function] = []
    for source in toolkit.async_functions.values():
        name = source.name

        async def entrypoint(_name: str = name, **arguments: Any) -> dict[str, Any]:
            return await recorder.invoke(_name, arguments)

        tools.append(
            Function(
                name=name,
                description=source.description,
                parameters=deepcopy(source.parameters),
                strict=source.strict,
                entrypoint=entrypoint,
                pre_hook=source.pre_hook,
                post_hook=source.post_hook,
            )
        )
    recorder.tools = tools
    return tools, recorder


def _build_probe_run_context(
    scenario: ProbeScenario,
    *,
    model_tier: Literal["fast", "standard"],
    model_id: str,
    thinking: bool,
) -> RunContext:
    """构造与生产 Task executor 同形、但不连接持久化层的受信上下文。"""

    binding: dict[str, Any] = {
        "externalRunId": f"probe-{scenario.name}",
        "threadId": f"probe-thread-{scenario.name}",
        "sandboxId": f"probe-sandbox-{scenario.name}",
        "leaseOwner": "reporting-tool-probe",
        "leaseEpoch": 1,
        "attemptNo": 1,
        REPORTING_PHASE_DEPENDENCY_KEY: scenario.phase,
        REPORTING_TASK_KIND_DEPENDENCY_KEY: scenario.task_kind,
        REPORTING_MODEL_TIER_DEPENDENCY_KEY: model_tier,
        REPORTING_MODEL_ID_DEPENDENCY_KEY: model_id,
        REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "high" if thinking else "off",
    }
    if thinking:
        binding[REPORTING_THINKING_BUDGET_DEPENDENCY_KEY] = 8192
    if scenario.task_kind == "analysis_item":
        binding.update(
            {
                REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY: 1,
                REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY: 4,
                REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY: 0,
                REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY: False,
            }
        )
    elif scenario.task_kind == "visualization_section":
        binding.update(
            {
                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: 0,
                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: 0,
                REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY: 1,
                REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY: 0,
                REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY: 12,
                REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY: 4,
                REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY: 48,
                REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY: 64,
                REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY: 0,
                REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY: 0,
                REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY: "vision",
            }
        )
        if scenario.branch == "recovery":
            binding[REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY] = True
    return RunContext(
        run_id=f"probe-run-{scenario.name}",
        session_id=f"probe-session-{scenario.name}",
        user_id="reporting-tool-probe",
        session_state={},
        dependencies={REPORTING_TASK_DEPENDENCY: binding},
    )


def _build_model(
    settings: AgentSettings,
    *,
    model_tier: Literal["fast", "standard"],
    thinking: bool,
    projection: ProbeToolProjection,
) -> ReportingPhaseOpenAIChat:
    profiles = build_model_profiles(
        fast_model_id=settings.model_fast_id,
        standard_model_id=settings.model_standard_id,
        strong_model_id=settings.model_strong_id,
    )
    profile = profiles[model_tier]  # argparse 已限制为有效档位。
    model = ProbeReportingPhaseOpenAIChat(
        id=profile.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body=openai_compatible_extra_body(
            enable_thinking=thinking,
            use_vllm_reasoning=settings.model_vllm_reasoning,
        ),
        strict_output=settings.model_structured_strict,
        temperature=1.0,
        top_p=1.0,
        retries=0,
    )
    model._probe_projection = projection
    setattr(
        model,
        REPORTING_STRUCTURED_MODES_MODEL_ATTR,
        {
            "fast": settings.model_fast_structured_mode,
            "standard": settings.model_standard_structured_mode,
            "strong": settings.model_strong_structured_mode,
        },
    )
    thinking_profile = (
        ReportingThinkingProfile.on(
            reasoning_effort="high",
            thinking_budget=settings.report_phase_thinking_budget,
            temperature=settings.report_phase_temperature,
        )
        if thinking
        else ReportingThinkingProfile.off(temperature=0.0)
    )
    model.max_tokens = min(settings.report_output_token_reserve, 8192)
    return apply_reporting_thinking_profile(model, thinking_profile)


def _runtime() -> MockReportingToolRuntime:
    return MockReportingToolRuntime(
        input_snapshot={"datasets": [{"datasetId": "dataset-001"}], "metrics": [{}]},
        inputs={
            "inputs/source.txt": b"source",
            "inputs/outpatient_monthly.csv": (
                b"month,revenue,cost\n2025-01,120,78\n2025-04,139,\n2025-06,156,101\n"
            ),
            "analysis/facts/analysis_001.json": _deterministic_facts_bytes(),
            "analysis/evidence/analysis_001.json": _section_evidence_bytes(complete=False),
            "analysis/evidence/complete_analysis_001.json": _section_evidence_bytes(complete=True),
        },
        output_policy=ReportingOutputPolicy(roots=("analysis/output", "analysis/charts")),
    )


async def _run_fixed_analysis_scenario(
    scenario: ProbeScenario,
    model: ReportingPhaseOpenAIChat,
    recorder: ProbeRecorder,
    run_context: RunContext,
) -> None:
    """用生产同形的五阶段 AnalysisItemWorkflow 执行 analysis probe。"""

    stage_input = _cli_stage_input(scenario)
    supplemental = scenario.branch == "script"
    scope = TaskExecutionScope(
        str(run_context.run_id),
        str(run_context.user_id),
        "probe-thread",
        "probe-sandbox",
        "reporting-analysis-agent",
    )
    decision_agent = create_reporting_generator_agent(
        model=model,
        output_schema=AnalysisEvidenceDecision,
        name=f"probe-{scenario.name}-decision",
    )
    script_agent = create_reporting_generator_agent(
        model=model,
        output_schema=AnalysisScriptDraft,
        name=f"probe-{scenario.name}-script",
    )
    summarizer = create_reporting_generator_agent(
        model=model,
        output_schema=AnalysisSummaryDraft,
        name=f"probe-{scenario.name}-summarizer",
    )

    async def plan_evidence(payload: Mapping[str, Any], *, repair: bool) -> AnalysisEvidencePlan:
        previous_plan = None
        if repair:
            correction = payload.get("correction")
            if isinstance(correction, Mapping):
                previous_plan = AnalysisEvidencePlan.model_validate(correction.get("previousPlan"))
        decision = (
            AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason=previous_plan.reason,
                missingFacts=previous_plan.missing_facts,
            )
            if previous_plan is not None
            else cast(
                AnalysisEvidenceDecision,
                await ReportingStructuredOutputExecutor(decision_agent).run(
                    json.dumps(
                        {
                            "stage": "decide_supplemental_evidence",
                            "requiredDecision": {
                                "requiresSupplementalEvidence": supplemental,
                                "missingFacts": (
                                    ["2025-04 outpatient cost"] if supplemental else []
                                ),
                            },
                            "task": stage_input,
                            "input": payload,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    scope=scope,
                    run_context=run_context,
                ),
            )
        )
        if not decision.requires_supplemental_evidence:
            return AnalysisEvidencePlan(
                requiresSupplementalEvidence=False,
                reason=decision.reason,
                missingFacts=(),
                script=None,
            )
        instruction = json.dumps(
            {
                "stage": "repair_evidence_script" if repair else "write_evidence_script",
                "evidenceDecision": decision.model_dump(mode="json", by_alias=True),
                "previousScript": previous_plan.script if previous_plan is not None else None,
                "scriptRequirement": (
                    "Return a Python script that writes the signed evidencePath as valid JSON."
                ),
                "task": stage_input,
                "input": payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        draft = cast(
            AnalysisScriptDraft,
            await ReportingStructuredOutputExecutor(script_agent).run(
                instruction,
                scope=scope,
                run_context=run_context,
            ),
        )
        return AnalysisEvidencePlan(
            requiresSupplementalEvidence=True,
            reason=decision.reason,
            missingFacts=decision.missing_facts,
            script=draft.script,
        )

    async def summarize(payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
        instruction = json.dumps(
            {
                "stage": "summarize_analysis",
                "requirements": [
                    "Only summarize the supplied deterministic facts and validated evidence.",
                    "State the 2025-04 missing-cost limitation explicitly.",
                ],
                "input": payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return cast(
            AnalysisSummaryDraft,
            await ReportingStructuredOutputExecutor(summarizer).run(
                instruction,
                scope=scope,
                run_context=run_context,
            ),
        )

    async def read_file(**arguments: Any) -> dict[str, Any]:
        arguments.pop("run_context", None)
        return await recorder.invoke("read_file", arguments)

    async def apply_patch(**arguments: Any) -> dict[str, Any]:
        arguments.pop("run_context", None)
        return await recorder.invoke("apply_analysis_patch", arguments)

    async def run_script(**arguments: Any) -> dict[str, Any]:
        arguments.pop("run_context", None)
        execution = await recorder.invoke(
            "run_python_script",
            {**arguments, "timeout": 30},
        )
        return {"exitCode": execution.get("exit_code", 0), **execution}

    async def complete(**arguments: Any) -> dict[str, Any]:
        arguments.pop("run_context", None)
        return await recorder.invoke("complete_analysis_item", arguments)

    await AnalysisItemWorkflow(
        plan_evidence=plan_evidence,
        summarize=summarize,
        read_file=read_file,
        apply_patch=apply_patch,
        run_script=run_script,
        complete=complete,
    ).run(stage_input, run_context)


async def _run_fixed_visualization_scenario(
    scenario: ProbeScenario,
    prompt: str,
    model: ReportingPhaseOpenAIChat,
    recorder: ProbeRecorder,
    run_context: RunContext,
) -> None:
    """用生产同形的固定 Workflow 执行可视化 probe。"""

    signed_script = "analysis/output/outpatient_chart.py"
    baseline_source: str | None = None
    if scenario.branch == "recovery":
        receipt = await recorder.invoke("read_file", {"path": signed_script})
        if receipt.get("ok") is not True:
            raise RuntimeError("visualization recovery script read failed")
        baseline_source = str(receipt.get("content") or "")

    generator = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationScriptDraft,
        name=f"probe-{scenario.name}-generator",
    )

    async def generate(
        _payload: Mapping[str, Any], task_context: RunContext
    ) -> VisualizationScriptDraft:
        return cast(
            VisualizationScriptDraft,
            await ReportingStructuredOutputExecutor(generator).run(
                prompt,
                scope=TaskExecutionScope(
                    str(task_context.run_id),
                    str(task_context.user_id),
                    "probe-thread",
                    "probe-sandbox",
                    "reporting-visualization-agent",
                ),
                run_context=task_context,
            ),
        )

    async def write_script(path: str, source: str, _task_context: RunContext) -> FileIdentity:
        if path != signed_script:
            raise RuntimeError("visualization generator changed signed script path")
        patch = "".join(
            difflib.unified_diff(
                [] if baseline_source is None else baseline_source.splitlines(keepends=True),
                source.splitlines(keepends=True),
                fromfile="/dev/null" if baseline_source is None else f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        receipt = await recorder.invoke(
            "apply_analysis_patch",
            {
                "patch": patch,
                **(
                    {"expected_sha256": {path: recorder.committed_script_sha256}}
                    if recorder.committed_script_sha256 is not None
                    else {}
                ),
            },
        )
        artifacts = receipt.get("artifacts")
        if receipt.get("ok") is not True or not isinstance(artifacts, list) or len(artifacts) != 1:
            raise RuntimeError("visualization script write failed")
        artifact = dict(artifacts[0])
        artifact.setdefault("size", len(source.encode("utf-8")))
        return FileIdentity.model_validate(artifact)

    async def execute_script(script_path: str, _task_context: RunContext) -> Mapping[str, Any]:
        execution = await recorder.invoke(
            "run_python_script",
            {"script_path": script_path},
        )
        if execution.get("ok") is not True:
            return {"exitCode": 1, **execution}
        return {"exitCode": 0, **execution}

    async def inspect_chart(
        chart: ChartDraft, _task_context: RunContext
    ) -> ChartVisualInspectionReceipt:
        tool_name = "view_image" if scenario.branch == "preview" else "inspect_chart"
        receipt = await recorder.invoke(tool_name, {"path": chart.source_path, "detail": "high"})
        if receipt.get("ok") is not True:
            raise RuntimeError("visualization inspection failed")
        return ChartVisualInspectionReceipt(
            sourcePath=chart.source_path,
            sha256=str(receipt.get("sha256") or "a" * 64),
            inspectionMode="vision",
            visualReviewStatus="passed",
            modelId=model.id,
            reviewed=True,
            requiresRevision=False,
        )

    async def submit(
        draft: VisualizationScriptDraft,
        _inspections: tuple[ChartVisualInspectionReceipt, ...],
        _task_context: RunContext,
    ) -> Mapping[str, Any]:
        return await recorder.invoke(
            "submit_visualization_charts",
            {
                "sectionCode": "outpatient_operation",
                "charts": [chart.model_dump(mode="json", by_alias=True) for chart in draft.charts],
            },
        )

    await VisualizationSectionWorkflow(
        generate=generate,
        recover=None,
        write_script=write_script,
        execute_script=execute_script,
        inspect_chart=inspect_chart,
        submit=submit,
    ).run(_cli_stage_input(scenario), run_context)


async def _run_fixed_section_scenario(
    scenario: ProbeScenario,
    model: ReportingPhaseOpenAIChat,
    recorder: ProbeRecorder,
    run_context: RunContext,
) -> None:
    """用生产同形的固定 Workflow 执行章节 probe。"""

    stage_input = _cli_stage_input(scenario)
    work_item = SectionWorkItem.model_validate(stage_input["sectionWorkItem"])
    generator = create_reporting_generator_agent(
        model=model,
        output_schema=SectionDecisionOutput,
        name=f"probe-{scenario.name}-generator",
    )
    scope = TaskExecutionScope(
        str(run_context.run_id),
        str(run_context.user_id),
        "probe-thread",
        "probe-sandbox",
        "reporting-section-agent",
    )
    instruction_payload = {
        "phase": "section",
        "reportGoal": "分析 2025 年门诊收入趋势、成本效率与改进重点。",
        "sectionGoal": {
            "sectionCode": work_item.section_code,
            "title": work_item.title,
            "focus": list(work_item.completion_conditions),
            "analysisIds": list(work_item.analysis_ids),
        },
        "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
        "completionConditions": list(work_item.completion_conditions),
        "claimAuthoringContract": _section_claim_authoring_contract(work_item),
        "sectionOutputPath": "analysis/output/outpatient_operation.json",
        "reworkRequestPath": "analysis/output/outpatient_operation.rework.json",
    }

    async def read_evidence(path: str, offset: int, _task_context: RunContext) -> Mapping[str, Any]:
        return await recorder.invoke("read_file", {"path": path, "offset": offset})

    async def generate(evidence: Any, task_context: RunContext) -> SectionDecision:
        return await _generate_section_in_blocks(
            generator,
            instruction_payload,
            evidence,
            work_item,
            scope=scope,
            run_context=task_context,
        )

    async def render(
        decision: RenderSectionDecision, _task_context: RunContext
    ) -> Mapping[str, Any]:
        return await recorder.invoke(
            "render_report_section",
            {
                "sectionCode": decision.section_code,
                "blocks": [item.model_dump(mode="json", by_alias=True) for item in decision.blocks],
                "claims": [item.model_dump(mode="json", by_alias=True) for item in decision.claims],
            },
        )

    async def rework(
        decision: AnalysisReworkDecision, _task_context: RunContext
    ) -> Mapping[str, Any]:
        return await recorder.invoke(
            "request_analysis_rework",
            {
                "analysisIds": list(decision.analysis_ids),
                "reason": decision.reason,
                "missingEvidence": list(decision.missing_evidence),
            },
        )

    await SectionWorkflow(
        read_evidence=read_evidence,
        generate=generate,
        recover=None,
        render=render,
        rework=rework,
    ).run(work_item, run_context)


async def _run_scenario(
    settings: AgentSettings,
    scenario: ProbeScenario,
    *,
    model_tier: Literal["fast", "standard"],
    thinking: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    runtime = _runtime()
    prompt = complex_cli_prompt(scenario)
    projection = ProbeToolProjection()
    model = _build_model(
        settings,
        model_tier=model_tier,
        thinking=thinking,
        projection=projection,
    )
    run_context = _build_probe_run_context(
        scenario,
        model_tier=model_tier,
        model_id=model.id,
        thinking=thinking,
    )
    tools, recorder = build_mock_probe_tools(
        scenario.phase,
        scenario.task_kind,
        runtime,
        scenario,
        run_context,
    )
    await recorder.prepare()

    async def run_agent() -> Any:
        if scenario.task_kind == "analysis_item":
            return await _run_fixed_analysis_scenario(scenario, model, recorder, run_context)
        if scenario.task_kind == "visualization_section":
            return await _run_fixed_visualization_scenario(
                scenario, prompt, model, recorder, run_context
            )
        return await _run_fixed_section_scenario(scenario, model, recorder, run_context)

    started = time.perf_counter()
    error: str | None = None
    try:
        with bind_reporting_run_context(run_context):
            await asyncio.wait_for(run_agent(), timeout=timeout_seconds)
    except TimeoutError:
        error = f"task_timeout: exceeded {timeout_seconds} seconds"
    except Exception as exc:  # noqa: BLE001 - 探针必须保留模型或协议失败类型。
        error = f"{type(exc).__name__}: {exc}"
    called_names = [call["name"] for call in recorder.calls]
    expected_names = list(scenario.tool_names)
    missing_tools = sorted(set(expected_names) - set(called_names))
    completion_tools = {
        "complete_analysis_item",
        "submit_visualization_charts",
        "render_report_section",
        "request_analysis_rework",
    }
    expected_completion = {scenario.completion_tool}
    actual_completion = set(called_names) & completion_tools
    unexpected_tools = sorted(set(called_names) - set(expected_names))
    task_completed = error is None and called_names[-1:] == [scenario.completion_tool]
    protocol_compliant = (
        task_completed
        and not missing_tools
        and actual_completion == expected_completion
        and not recorder.failures
        and not unexpected_tools
        and not projection.not_visible_calls
    )
    valid = task_completed
    if not valid and error is None:
        error = (
            "cli_task_contract_failed: "
            f"missing_tools={missing_tools!r}, "
            f"expected_completion={sorted(expected_completion)!r}, "
            f"actual_completion={sorted(actual_completion)!r}, failures={recorder.failures!r}, "
            f"final_call={called_names[-1:]!r}"
        )
    return {
        "scenario": scenario.name,
        "phase": scenario.phase,
        "task_kind": scenario.task_kind,
        "expected_tools": expected_names,
        "missing_tools": missing_tools,
        "expected_completion": sorted(expected_completion),
        "actual_completion": sorted(actual_completion),
        "unexpected_tools": unexpected_tools,
        "visible_tool_batches": projection.batches,
        "not_visible_calls": projection.not_visible_calls,
        "protocol_failures": recorder.failures,
        "task_completed": task_completed,
        "protocol_compliant": protocol_compliant,
        "calls": recorder.calls,
        "workspace_calls": runtime.calls,
        "seconds": round(time.perf_counter() - started, 2),
        "valid": valid,
        "error": error,
    }


async def _run(args: argparse.Namespace) -> int:
    os.environ["AGENT_ENV_FILE"] = args.env_file
    settings = AgentSettings.from_environment()
    scenarios = probe_scenarios()
    if args.runs != len(scenarios):
        raise ValueError(f"--runs 必须为 {len(scenarios)}，以覆盖全部固定场景")
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        result = await _run_scenario(
            settings,
            scenario,
            model_tier=cast(Literal["fast", "standard"], args.model_tier),
            thinking=args.thinking,
            timeout_seconds=args.task_timeout,
        )
        results.append(result)
        if args.progress_file:
            with open(args.progress_file, "a", encoding="utf-8") as progress:
                progress.write(json.dumps(result, ensure_ascii=False) + "\n")
    selected_model = (
        settings.model_fast_id if args.model_tier == "fast" else settings.model_standard_id
    )
    valid_count = sum(result["valid"] for result in results)
    protocol_compliant_count = sum(result["protocol_compliant"] for result in results)
    print(
        json.dumps(
            {
                "model_tier": args.model_tier,
                "model": selected_model,
                "thinking": args.thinking,
                "runs": results,
                "valid_count": valid_count,
                "task_completed_count": sum(result["task_completed"] for result in results),
                "protocol_compliant_count": protocol_compliant_count,
                "required_tool_coverage": sorted(
                    {
                        tool
                        for result in results
                        for tool in result["expected_tools"]
                        if tool in {call["name"] for call in result["calls"]}
                    }
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if valid_count == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="使用真实模型探测 Reporting 固定工作流")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model-tier", choices=("fast", "standard"), required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--task-timeout", type=int, default=45)
    parser.add_argument("--progress-file")
    args = parser.parse_args()
    if args.task_timeout < 1 or args.task_timeout > 300:
        parser.error("--task-timeout 必须在 1 到 300 之间")
    try:
        exit_code = asyncio.run(_run(args))
    except ValueError as error:
        parser.error(str(error))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()


__all__ = ["ProbeRecorder", "ProbeScenario", "build_mock_probe_tools", "probe_scenarios"]
