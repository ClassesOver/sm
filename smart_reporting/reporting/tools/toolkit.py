"""Report worker 工具装配。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from agno.run import RunContext
from agno.tools import Function
from pydantic import ValidationError

from ...agent_control import AGENT_PLAN_STATE_KEY, validated_agent_plan
from ...task_execution.execution import (
    MAX_TOOL_OUTPUT_READ_BYTES,
    WorkspaceTaskToolkit,
)
from ...task_execution.repository_impl import TERMINAL_EXECUTION_STATUSES
from ...workspace import (
    WorkspaceError,
    WorkspaceService,
)
from ..delivery.draft_v1 import (
    ReportChartRegistration,
    ReportDraftBlock,
)
from ..models import ReportingError
from ..phase import (
    ReportingPhase,
    ReportingTaskKind,
    reporting_phase_allows_tool,
)
from ..vision import ReportVisionReviewer
from ..workflow.checkpoint import (
    FileIdentity,
    SectionClaimSubmission,
)
from ..workflow.repository import ReportingStateRepository
from ..workflow.state import (
    ReportingCommand,
    ReportingReducerResult,
    ReportingRunState,
    ReportingStateError,
)
from .analysis import MAX_VISUALIZATION_SCRIPT_BYTES, RuntimeAnalysisMixin
from .capabilities import tools_for_task
from .profile import MAX_PROFILE_POINTER_ITEMS, RuntimeProfileMixin
from .sections import RuntimeSectionsMixin
from .validation import analysis_file_create_parameters, analysis_file_overwrite_parameters

SUPPLEMENTAL_EVIDENCE_READ_BYTES = 128 * 1024

REPORT_WORKER_TOOLKIT_INSTRUCTIONS = (
    "当前 Reporting Task 只能使用本轮实际注册的工具；未注册工具不存在。\n"
    "直接使用任务 JSON 中的受信工作区相对路径，不浏览根目录、不猜测路径。\n"
    "严格按工具 schema 直接传参，并以每次服务端回执决定下一步。"
)


def _reset_stop_after_tool_call(fc: Any) -> None:
    """Function 会跨内部 run 复用，每次执行前必须清除上一轮接受状态。"""

    fc.function.stop_after_tool_call = False


def _stop_after_accepted_tool_call(fc: Any) -> None:
    """仅正式 accepted 回执使用 Agno 公共 stop_after_tool_call 收敛当前 run。"""

    fc.function.stop_after_tool_call = bool(
        isinstance(fc.result, dict) and fc.result.get("status") == "accepted"
    )


def _stop_after_nonretryable_tool_call(fc: Any) -> None:
    """不可重试的工具回执结束当前 run，避免同一错误继续膨胀上下文。"""

    fc.function.stop_after_tool_call = bool(
        isinstance(fc.result, dict)
        and fc.result.get("ok") is False
        and fc.result.get("retryable") is False
    )


def _stop_after_finished_phase_call(fc: Any) -> None:
    """只有已由服务端完成底层 Task 的阶段回执才能结束当前模型 run。"""

    fc.function.stop_after_tool_call = bool(
        isinstance(fc.result, dict)
        and fc.result.get("ok") is True
        and fc.result.get("taskFinished") is True
    )


class ReportWorkspaceTaskToolkit(
    RuntimeProfileMixin,
    RuntimeAnalysisMixin,
    RuntimeSectionsMixin,
    WorkspaceTaskToolkit,
):
    """Report Worker 的专用工具门禁；底层锁、租约和审计复用通用 Kernel。"""

    def __init__(
        self,
        *args: Any,
        state_repository: ReportingStateRepository,
        vision_reviewer: ReportVisionReviewer | None = None,
        phase: ReportingPhase | None = None,
        task_kind: ReportingTaskKind | None = None,
        **kwargs: Any,
    ) -> None:
        self._vision_reviewer = vision_reviewer
        self._state_repository = state_repository
        allowed_tools = tools_for_task(phase, task_kind)
        self._assembly_allowed_tools = allowed_tools
        self._assembly_internal_tools = {"finish_task"}
        super().__init__(*args, **kwargs)
        finish_function = self.async_functions.get("finish_task")
        if finish_function is None:
            raise ReportingError(
                "report_phase_contract_invalid",
                "Reporting Worker 缺少底层 finish_task。",
            )
        self._finish_function: Function = finish_function
        # finish_task 由服务端阶段提交逻辑调用，不能进入模型可见工具 schema。
        self.async_functions.pop("finish_task", None)
        for hidden_tool_name in ("create_files", "overwrite_file", "replace_text", "apply_patch"):
            self.functions.pop(hidden_tool_name, None)
            self.async_functions.pop(hidden_tool_name, None)
        # Reporting 在 finalize 后由 Workflow 继续执行独立产物验收。Worker 收尾只绑定
        # 当前产物哈希，不重复要求 verify 或执行 Task acceptance validator。
        self.kernel.require_finish_verification = False
        self.kernel.evaluate_finish_acceptance = False
        self._finish_function.parameters["properties"].pop("verification_ids", None)
        self.functions.pop("verify", None)
        self.async_functions.pop("verify", None)
        view_image = self.async_functions.get("view_image")
        if view_image is not None:
            view_image.description = (
                "使用独立视觉模型临时查看工作区图片；正式图表必须改用 inspect_chart 生成"
                "绑定文件哈希的耐久检查回执。"
                '{"path":"analysis/charts/trend.png","detail":"high"}'
            )
        # Toolkit 指令由通用 Coding 实现注入，其中仍声明了已删除的 verify 工具。
        # Reporting 必须让模型看到与实际 schema 一致的能力，避免 finalize 后进入
        # 不可满足的 verify -> finish_task 循环。
        raw_toolkit_instructions = getattr(self, "instructions", None)
        toolkit_instructions = (
            raw_toolkit_instructions if isinstance(raw_toolkit_instructions, str) else ""
        )
        reporting_instruction_lines: list[str] = []
        for line in toolkit_instructions.splitlines():
            if "verification_ids" in line or "成功 verify" in line:
                continue
            if "探测工作区根目录时调用 list_files" in line:
                reporting_instruction_lines.append(
                    "- Reporting 任务 JSON 已提供受信输入与阶段输出路径；直接使用这些工作区"
                    "相对路径，禁止浏览工作区根目录或猜测路径。"
                )
                continue
            updated = line.replace("、verify", "")
            for unused_tool_name in ("list_files", "tree", "git_status", "git_diff"):
                updated = updated.replace(f"、{unused_tool_name}", "")
            updated = updated.replace("、目录列举及 Git 状态或差异", "")
            reporting_instruction_lines.append(updated)
        self.instructions = "\n".join(reporting_instruction_lines)
        for name, description, parameters, entrypoint in (
            (
                "create_analysis_file",
                "创建此前不存在的 analysis 文件。只传 path 和 content；目标已存在时读取当前 "
                "SHA-256 后改用 overwrite_analysis_file。服务端完成写入和 SHA-256 校验后提交意图。",
                analysis_file_create_parameters,
                self.create_analysis_file,
            ),
            (
                "overwrite_analysis_file",
                "使用读取回执中的 expected_sha256 CAS 覆盖已有 analysis 文件。目标不存在时改用 "
                "create_analysis_file；服务端完成写入和 SHA-256 校验后提交意图。",
                analysis_file_overwrite_parameters,
                self.overwrite_analysis_file,
            ),
        ):
            self.register(
                Function(
                    name=name,
                    description=description,
                    parameters=(
                        parameters()
                        if phase != "section"
                        else {"type": "object", "properties": {}, "additionalProperties": False}
                    ),
                    strict=True,
                    entrypoint=entrypoint,
                    pre_hook=_reset_stop_after_tool_call,
                    post_hook=_stop_after_nonretryable_tool_call,
                )
            )

        self.register(
            Function(
                name="read_profile_pointer",
                description=(
                    "从当前 Task 的受信分析上下文按 JSON Pointer 定点读取完整 Dataset Profile；"
                    "每次返回均有界，禁止读取完整 variables、correlations 或整份 Profile。"
                    '示例：{"datasetId":"dataset-001","profilePointer":'
                    '"/variables/amount/histogram","purpose":"核验金额分布与异常值",'
                    '"maxItems":50}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "datasetId": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "profilePointer": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1024,
                            "pattern": "^/",
                        },
                        "purpose": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "maxItems": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROFILE_POINTER_ITEMS,
                            "default": 50,
                        },
                    },
                    "required": ["datasetId", "profilePointer", "purpose"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.read_profile_pointer,
            )
        )
        self.register(
            Function(
                name="query_profile",
                description=(
                    "使用标准 JMESPath 对当前 Dataset 的完整 Profile 执行有界结构化查询；"
                    "适合字段筛选、列表过滤和投影。精确节点引用仍使用 read_profile_pointer。"
                    "可复制的 query 范例：数组首项 values(variables)[0]；字段投影 "
                    "variables.amount.{min: min, max: max}；空值不补值，只过滤空值 "
                    "values(variables)[?min != `null`].{min: min, max: max}。"
                    '完整参数示例：{"datasetId":"dataset-001","query":'
                    '"values(variables)[0]",'
                    '"purpose":"读取金额分布摘要","maxItems":50}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "datasetId": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1024,
                        },
                        "purpose": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "maxItems": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROFILE_POINTER_ITEMS,
                            "default": 50,
                        },
                    },
                    "required": ["datasetId", "query", "purpose"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.query_profile,
            )
        )
        self.register(
            Function(
                name="query_analysis_context",
                description=(
                    "currentAnalysis 已在任务 JSON，禁止通过本工具重复读取；本工具仅用于按需读取 "
                    "Dataset 元数据。使用标准 JMESPath 对当前任务的类型化 analysisContext 投影执行"
                    "有界查询；可复制的 query 范例：数组首项 datasets[0]；字段投影 "
                    "datasets[].{datasetId: datasetId, rowCount: rowCount, periodCoverage: periodCoverage}；"
                    "空值不补值，只过滤空值 datasets[?rowCount != `null`].{datasetId: datasetId, "
                    "rowCount: rowCount}。"
                    '完整参数示例：{"query":"datasets[0]","purpose":"读取首个 Dataset 元数据",'
                    '"maxItems":1}。'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "purpose": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "maxItems": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROFILE_POINTER_ITEMS,
                            "default": 50,
                        },
                    },
                    "required": ["query", "purpose"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.query_analysis_context,
            )
        )
        self.register(
            Function(
                name="query_analysis_facts",
                description=(
                    "由服务端定位并校验当前 analysis 的不可变 facts 文件，再执行有界标准 "
                    "JMESPath。可复制的 query 范例：数组首项 metrics[0]；字段投影 "
                    "metrics[].{field: field, total: total}；空值不补值，只过滤空值 "
                    "metrics[?total != `null`].{field: field, total: total}。"
                    "单项 facts 根节点没有 analyses 包装；"
                    '完整参数示例：{"query":"metrics[0]","purpose":"读取首个指标事实",'
                    '"maxItems":1}。'
                    "visualization 示例：analyses[].{analysisId: analysisId, "
                    "metrics: facts.metrics[].{field: field, total: total}}。visualization 的 "
                    "analyses[].facts 只存在于本工具聚合回执；deterministicFactFiles 指向的"
                    "单个文件根节点就是对应 analysis 的 facts，不包含 analyses 包装。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "purpose": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "maxItems": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROFILE_POINTER_ITEMS,
                            "default": 50,
                        },
                    },
                    "required": ["query", "purpose"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.query_analysis_facts,
            )
        )
        self.register(
            Function(
                name="complete_analysis_item",
                description=(
                    "提交当前 analysisId 的摘要、Dataset、引用、Profile 回执、图表绑定和 Warning；"
                    "服务端自动把当前不可变固定事实绑定为 evidence。只有固定事实未覆盖时才在 "
                    "evidencePaths 提交补充 evidence；服务端接受后结束当前独立 run。"
                    "chartIds 仅用于绑定已有图表，不会触发图表生成。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "analysisId": {"type": "string", "pattern": "^analysis_[0-9]{3,6}$"},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 8000},
                        "datasetIds": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "evidencePaths": {
                            "type": "array",
                            "description": (
                                "可选补充 evidence 路径；固定事实足够时传空数组，服务端自动绑定"
                                "当前 analysis 的不可变固定事实文件。"
                            ),
                            "minItems": 0,
                            "maxItems": 50,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "citationIds": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "chartIds": {
                            "type": "array",
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "profileReadReceiptIds": {
                            "type": "array",
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "warnings": {
                            "type": "array",
                            "maxItems": 500,
                            "items": {"type": "string", "maxLength": 2000},
                        },
                    },
                    "required": [
                        "analysisId",
                        "summary",
                        "datasetIds",
                        "evidencePaths",
                        "citationIds",
                        "profileReadReceiptIds",
                        "warnings",
                    ],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.complete_analysis_item,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_accepted_tool_call,
            )
        )
        self.register(
            Function(
                name="request_analysis_rework",
                description=(
                    "仅当当前 SectionWorkItem 的证据不足以成稿时，提交缺口和受影响 analysisIds；"
                    "服务端只按该 analysis 的冻结 Dataset、期间和指标口径补算，reason 与 missingEvidence "
                    "不能新增数据源、扩大期间或改变口径；零行 Dataset 无法通过重复补算解决。"
                    '示例：{"analysisIds":["analysis_001"],"reason":"缺少同比基准",'
                    '"missingEvidence":["补充上年同期收入"]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "analysisIds": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 200,
                            "uniqueItems": True,
                            "items": {"type": "string", "pattern": "^analysis_[0-9]{3,6}$"},
                        },
                        "reason": {"type": "string", "minLength": 1, "maxLength": 4000},
                        "missingEvidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 2000},
                        },
                    },
                    "required": ["analysisIds", "reason", "missingEvidence"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.request_analysis_rework,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_finished_phase_call,
            )
        )
        self.register(
            Function(
                name="inspect_chart",
                description=(
                    "只读检查 visualizationWorkspace.chartOutputRoot 内的最终 PNG/JPEG。"
                    "服务端执行文件类型、大小、解码、空白像素和视觉模型检查，并耐久保存"
                    "绑定 sourcePath、sha256 与 modelId 的回执；文件修改后必须重新检查。"
                    '示例：{"path":"analysis/charts/income.png","detail":"high"}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 512},
                        "detail": {
                            "type": "string",
                            "enum": ["high", "original"],
                            "default": "high",
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.inspect_chart,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_nonretryable_tool_call,
            )
        )
        self.register(
            Function(
                name="render_report_section",
                description=(
                    "提交当前 SectionWorkItem 指定章节。每个 block 的 markdown 不得重复"
                    "服务端章节 title，内部标题从 ### 开始；可使用列表、引用、强调和表格，"
                    "图片必须通过 chartIds 显式引用；每个实际使用的 chartId 同时填入对应 block 和 claim。"
                    "claim 使用 managementQuestionRef 绑定当前章节"
                    "问题目录；periodBasis 和问题全文由服务端补齐，绑定图表时周期、比较语义、"
                    "可比性和图表 citation 也由服务端补齐。metricCode 必须逐字取自当前"
                    "SectionWorkItem.metricDefinitions.code，禁止使用 income、revenue 等自然语言别名；"
                    "comparisonType 非 none 时必须填写 comparisonPeriod。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "sectionCode": {"type": "string", "minLength": 1, "maxLength": 128},
                        "blocks": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 200,
                            "items": ReportDraftBlock.model_json_schema(by_alias=True),
                        },
                        "claims": {
                            "type": "array",
                            "maxItems": 500,
                            "items": SectionClaimSubmission.model_json_schema(by_alias=True),
                        },
                    },
                    "required": ["sectionCode", "blocks", "claims"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.render_report_section,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_finished_phase_call,
            )
        )
        self.register(
            Function(
                name="submit_visualization_charts",
                description=(
                    "提交当前 visualization_section 章节生成的全部图表草案；允许提交空数组，"
                    "每张图必须先调用 inspect_chart，且必须来自当前章节签发的 chartOutputRoot；"
                    "服务端会检查每个图表文件身份"
                    "并按章节持久化，成功后结束当前 Task。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "sectionCode": {"type": "string", "minLength": 1, "maxLength": 128},
                        "charts": {
                            "type": "array",
                            "maxItems": 100,
                            "items": ReportChartRegistration.model_json_schema(by_alias=True),
                        },
                    },
                    "required": ["sectionCode", "charts"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.submit_visualization_charts,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_finished_phase_call,
            )
        )

    def register(self, function: Any, name: str | None = None) -> None:
        """按阶段能力在注册瞬间过滤工具，避免先暴露再删除。"""

        allowed = self._assembly_allowed_tools
        if allowed is not None:
            tool_name = (
                name or getattr(function, "name", None) or getattr(function, "__name__", None)
            )
            if (
                isinstance(tool_name, str)
                and tool_name not in allowed
                and tool_name not in self._assembly_internal_tools
            ):
                return
        super().register(function, name=name)

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")
        reviewer = self._vision_reviewer
        if reviewer is None:
            raise WorkspaceError("当前 Reporting Worker 未启用图片视觉审查。")

        async def call(scope: Any) -> dict[str, Any]:
            return await reviewer.review(
                scope.thread_id,
                path,
                detail=detail,
            )

        return await self._invoke("view_image", {"path": path, "detail": detail}, call, run_context)

    @staticmethod
    def _session_state(run_context: RunContext | None) -> dict[str, Any] | None:
        if run_context is not None and isinstance(run_context.session_state, dict):
            return run_context.session_state
        return None

    @staticmethod
    def _artifact_parameters(scope: Any) -> dict[str, Any]:
        acceptance_contract = scope.task.acceptance_contract
        requirements = (
            acceptance_contract.get("requirements")
            if isinstance(acceptance_contract, dict)
            else None
        )
        requirement = (
            requirements[0] if isinstance(requirements, list) and len(requirements) == 1 else None
        )
        parameters = requirement.get("parameters") if isinstance(requirement, dict) else None
        if not isinstance(parameters, dict):
            raise ReportingError(
                "report_draft_contract_missing", "当前 Reporting Task 缺少服务端验收参数。"
            )
        return parameters

    @classmethod
    def _active_reporting_phase(cls, scope: Any) -> ReportingPhase:
        phase = cls._artifact_parameters(scope).get("phase")
        if phase not in {"analysis", "section"}:
            raise ReportingError("report_phase_contract_invalid", "Reporting phase 参数无效。")
        return cast(ReportingPhase, phase)

    @classmethod
    def _active_reporting_task_kind(cls, scope: Any) -> ReportingTaskKind:
        parameters = cls._artifact_parameters(scope)
        phase_contract = parameters.get("phaseContract")
        task_kind = phase_contract.get("taskKind") if isinstance(phase_contract, dict) else None
        if task_kind not in {
            "analysis_item",
            "visualization_section",
            "section",
        }:
            raise ReportingError("report_phase_contract_invalid", "Reporting taskKind 参数无效。")
        return cast(ReportingTaskKind, task_kind)

    @classmethod
    def _require_phase_tool(
        cls,
        scope: Any,
        *,
        allowed: frozenset[str],
        tool_name: str,
        run_context: RunContext | None = None,
        task_kinds: frozenset[ReportingTaskKind] | None = None,
    ) -> None:
        phase = cls._active_reporting_phase(scope)
        if phase not in allowed:
            raise ReportingError(
                "report_phase_tool_forbidden",
                f"phase={phase} 不能调用 {tool_name}。",
            )
        task_kind = cls._active_reporting_task_kind(scope)
        if task_kinds is not None and task_kind not in task_kinds:
            raise ReportingError(
                "report_phase_tool_forbidden",
                f"taskKind={task_kind} 不能调用 {tool_name}。",
            )

    def _retain_bounded_tool_result(self, scope: Any, tool_name: str) -> bool:
        return self._active_reporting_phase(scope) == "analysis" and tool_name not in {
            "read_tool_output",
            "finish_task",
        }

    def _tool_preview_bytes(
        self,
        scope: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: Any,
    ) -> int | None:
        _ = result
        if self._active_reporting_phase(scope) != "analysis" or tool_name != "read_file":
            return None
        task_kind = self._active_reporting_task_kind(scope)
        try:
            requested = WorkspaceService.normalize_path(arguments.get("path"), allow_root=False)[0]
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if task_kind == "analysis_item":
                analysis_id = contract.get("currentAnalysisId")
                fact_files = contract.get("deterministicFactFiles")
                fact_file = (
                    fact_files.get(analysis_id)
                    if isinstance(analysis_id, str) and isinstance(fact_files, Mapping)
                    else None
                )
                signed = WorkspaceService.normalize_path(
                    fact_file.get("path") if isinstance(fact_file, Mapping) else None,
                    allow_root=False,
                )[0]
                # 五阶段子流程会直接校验完整固定 facts；仅该签发文件可避开
                # 通用模型回显截断，其他路径仍保持默认上下文边界。
                if requested == signed:
                    return MAX_TOOL_OUTPUT_READ_BYTES
                evidence_root = contract.get("analysisOutputRoot")
                evidence_path = WorkspaceService.normalize_path(
                    f"{str(evidence_root or '').rstrip('/')}/supplement.json",
                    allow_root=False,
                )[0]
                return SUPPLEMENTAL_EVIDENCE_READ_BYTES if requested == evidence_path else None
            if task_kind != "visualization_section":
                return None
            workspace = contract.get("visualizationWorkspace")
            script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            signed = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
        except WorkspaceError:
            return None
        return MAX_VISUALIZATION_SCRIPT_BYTES if requested == signed else None

    def _no_progress_exempt(
        self,
        *,
        scope: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
        run_context: RunContext | None,
    ) -> bool:
        _ = scope, tool_name, arguments, run_context
        return False

    async def _bound_analysis_result(
        self,
        *,
        scope: Any,
        tool_name: str,
        result: dict[str, Any],
        run_context: RunContext | None,
        preview_bytes: int | None = None,
    ) -> dict[str, Any]:
        if (
            self._active_reporting_phase(scope) != "analysis"
            or tool_name == "read_tool_output"
            or isinstance(result.get("outputHandle"), str)
        ):
            return result
        return await self.kernel.bound_tool_result(
            scope,
            result,
            run_context,
            retain=True,
            preview_bytes=preview_bytes,
        )

    async def _record_and_bound_profile_result(
        self,
        *,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        run_context: RunContext | None,
        preview_bytes: int | None = None,
    ) -> dict[str, Any]:
        bounded = await self._bound_analysis_result(
            scope=scope,
            tool_name=tool_name,
            result=result,
            run_context=run_context,
            preview_bytes=preview_bytes,
        )
        return bounded

    async def read_tool_output(
        self,
        handle: str,
        offset: int = 0,
        max_bytes: int = MAX_TOOL_OUTPUT_READ_BYTES,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """用 Agno 内部注入上下文原子累计恢复分页。"""

        result = await super().read_tool_output(
            handle,
            offset,
            max_bytes,
            run_context=_agno_run_context,
        )
        return result

    async def _read_trusted_json(
        self,
        *,
        thread_id: str,
        identity: Any,
        identity_code: str,
        structure_code: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("path"), str)
            or not isinstance(identity.get("size"), int)
            or identity["size"] <= 0
            or not isinstance(identity.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]) is None
        ):
            raise ReportingError(identity_code, "受信 JSON 文件身份缺失或无效。")
        content, _mime = await asyncio.to_thread(
            self.kernel.service.file_bytes,
            thread_id,
            identity["path"],
        )
        if (
            len(content) != identity["size"]
            or hashlib.sha256(content).hexdigest() != identity["sha256"]
        ):
            raise ReportingError(identity_code, "受信 JSON 文件身份校验失败。")
        try:
            value = json.loads(content)
        except (TypeError, ValueError) as error:
            raise ReportingError(structure_code, "受信 JSON 文件无法解析。") from error
        if not isinstance(value, dict):
            raise ReportingError(structure_code, "受信 JSON 文件必须为对象。")
        return value

    async def _write_phase_json(
        self,
        *,
        scope: Any,
        path: str,
        payload: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.kernel.service._validate_content(content)
        current = (await self.kernel.service.abatch_hash_files(scope.thread_id, [path]))[0]
        mode = "create" if current.get("missing") is True else "overwrite"
        result = await self.kernel.patch(
            mode,
            path,
            None,
            None,
            False,
            None,
            run_context,
            content=content.decode("utf-8"),
            expected_sha256=current.get("sha256") if mode == "overwrite" else None,
            _scope=scope,
        )
        if result.get("ok") is not True:
            raise ReportingError("report_phase_artifact_write_failed", "阶段产物写入失败。")
        identity = await self.kernel.service.ahash_file(scope.thread_id, path)
        if (
            identity.get("missing")
            or identity.get("size") != len(content)
            or identity.get("sha256") != hashlib.sha256(content).hexdigest()
        ):
            raise ReportingError("report_phase_artifact_changed", "阶段产物写入后发生变化。")
        return FileIdentity.model_validate(identity).model_dump(mode="json", by_alias=True)

    @staticmethod
    def _phase_parameters(scope: Any, expected_phase: str) -> tuple[dict[str, Any], dict[str, Any]]:
        parameters = ReportWorkspaceTaskToolkit._artifact_parameters(scope)
        phase_contract = parameters.get("phaseContract")
        if parameters.get("phase") != expected_phase or not isinstance(phase_contract, dict):
            raise ReportingError(
                "report_phase_contract_invalid", f"当前 Task 不是有效的 {expected_phase} 阶段。"
            )
        return parameters, phase_contract

    @staticmethod
    def _require_current_analysis_dataset(contract: Mapping[str, Any], dataset_id: str) -> None:
        """analysis item 只能读取当前计划项绑定的 Dataset。"""

        if contract.get("taskKind") != "analysis_item":
            return
        current_analysis_id = contract.get("currentAnalysisId")
        datasets_by_analysis = contract.get("analysisDatasetIds")
        allowed = (
            datasets_by_analysis.get(current_analysis_id)
            if isinstance(current_analysis_id, str) and isinstance(datasets_by_analysis, Mapping)
            else None
        )
        if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
            raise ReportingError(
                "report_phase_contract_invalid",
                "analysis item 缺少当前 Dataset 授权范围。",
            )
        if dataset_id not in allowed:
            raise ReportingError(
                "report_profile_dataset_unknown",
                "datasetId 不属于当前 analysis item。",
            )

    async def _durable_state(self, scope: Any) -> ReportingRunState:
        parameters = self._artifact_parameters(scope)
        contract = parameters.get("phaseContract")
        report_run_id = contract.get("reportRunId") if isinstance(contract, dict) else None
        if not isinstance(report_run_id, str) or not report_run_id:
            raise ReportingError(
                "report_phase_contract_invalid", "phase contract 缺少 reportRunId。"
            )
        state = await self._state_repository.get(report_run_id)
        if state is None:
            raise ReportingError("report_state_not_found", "Reporting 运行状态不存在。")
        return state

    async def _ensure_visualization_terminal_settled(self, scope: Any) -> None:
        """拒绝在签发脚本的 terminal execution 仍运行时推进生产阶段。

        terminal 默认只等待有限时间，超时后会返回 ``status=running``；模型随后可能在同一
        工具批次提交 register/finalize。文件尚未写完时，登记会得到 Daytona NotFound，
        finalize 还可能绕过图表登记。执行记录是服务端唯一受信的完成状态，因此这里按当前
        externalRunId、internalRunId 和 terminal kind 精确筛选未终态执行，要求模型先用
        process poll/wait 收敛会话，再重试后续工具。
        """

        repository = getattr(self, "repository", None)
        list_executions = getattr(repository, "list_executions", None)
        external_run_id = getattr(scope, "external_run_id", None)
        internal_run_id = getattr(scope, "internal_run_id", None)
        if (
            not callable(list_executions)
            or not isinstance(external_run_id, str)
            or not external_run_id
            or not isinstance(internal_run_id, str)
            or not internal_run_id
        ):
            return
        executions = await list_executions(external_run_id)
        pending = [
            execution
            for execution in executions
            if getattr(execution, "internal_run_id", None) == internal_run_id
            and getattr(execution, "kind", None) == "terminal"
            and getattr(execution, "status", None) not in TERMINAL_EXECUTION_STATUSES
        ]
        if pending:
            raise ReportingError(
                "report_visualization_script_running",
                "可视化脚本仍在执行，请先使用 process 等待同一脚本会话结束后再登记或完成。",
                details={
                    "executions": [
                        {
                            "executionId": str(getattr(item, "execution_id", "")),
                            "status": str(getattr(item, "status", "")),
                        }
                        for item in pending[:10]
                    ]
                },
            )

    @staticmethod
    def _analysis_output_root(contract: Mapping[str, Any]) -> str:
        value = contract.get("analysisOutputRoot")
        if not isinstance(value, str) or not value:
            raise ReportingError(
                "report_phase_contract_invalid", "analysis item 缺少专属输出目录。"
            )
        try:
            return WorkspaceService.normalize_path(value, allow_root=False)[0]
        except WorkspaceError as error:
            raise ReportingError(
                "report_phase_contract_invalid", "analysis item 专属输出目录无效。"
            ) from error

    @classmethod
    def _require_analysis_output_paths(
        cls,
        contract: Mapping[str, Any],
        paths: Iterable[str],
    ) -> None:
        root = cls._analysis_output_root(contract)
        prefix = f"{root}/"
        for value in paths:
            try:
                path = WorkspaceService.normalize_path(value, allow_root=False)[0]
            except (TypeError, WorkspaceError) as error:
                raise ReportingError(
                    "report_analysis_output_path_invalid", "analysis 输出路径无效。"
                ) from error
            if not path.startswith(prefix):
                raise ReportingError(
                    "report_analysis_output_path_invalid",
                    "analysis 补充文件必须写入当前 analysisId 的专属目录。",
                    details={"outputRoot": root, "path": path},
                )

    @classmethod
    def _require_analysis_task_output_paths(
        cls,
        contract: Mapping[str, Any],
        paths: Iterable[str],
    ) -> None:
        if contract.get("taskKind") == "analysis_item":
            cls._require_analysis_output_paths(contract, paths)
            return
        if contract.get("taskKind") == "visualization_section":
            workspace = contract.get("visualizationWorkspace")
            script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            try:
                normalized_script = WorkspaceService.normalize_path(script_path, allow_root=False)[
                    0
                ]
            except WorkspaceError as error:
                raise ReportingError(
                    "report_phase_contract_invalid", "visualization scriptPath 无效。"
                ) from error
            normalized_paths = tuple(
                WorkspaceService.normalize_path(path, allow_root=False)[0] for path in paths
            )
            if normalized_paths != (normalized_script,):
                raise ReportingError(
                    "report_visualization_write_forbidden",
                    "visualization 只允许写入签发的图表脚本。",
                    details={"scriptPath": normalized_script},
                )

    @staticmethod
    def _latest_committed_write_identity(
        payload: Mapping[str, Any], path: str
    ) -> dict[str, Any] | None:
        """返回同一路径最后一次 committed write intent 冻结的文件身份。"""

        latest_sequenced: dict[str, Any] | None = None
        latest_sequence: int | None = None
        latest_legacy: dict[str, Any] | None = None
        intents = payload.get("writeIntents")
        if not isinstance(intents, Mapping):
            return None
        # intent 的映射位置只反映 record 顺序。新状态以 reducer 冻结的 commitSequence
        # 为提交顺序事实；旧状态没有该字段时才按历史映射顺序回退，避免升级后中断恢复。
        for intent in intents.values():
            if not isinstance(intent, Mapping) or intent.get("status") != "committed":
                continue
            artifacts = intent.get("artifacts")
            if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
                continue
            for artifact in artifacts:
                if isinstance(artifact, Mapping) and artifact.get("path") == path:
                    identity = {
                        "path": path,
                        "size": artifact.get("size"),
                        "sha256": artifact.get("sha256"),
                    }
                    commit_sequence = intent.get("commitSequence")
                    if (
                        isinstance(commit_sequence, int)
                        and not isinstance(commit_sequence, bool)
                        and commit_sequence >= 0
                    ):
                        if latest_sequence is None or commit_sequence > latest_sequence:
                            latest_sequence = commit_sequence
                            latest_sequenced = identity
                    else:
                        latest_legacy = identity
        return latest_sequenced if latest_sequence is not None else latest_legacy

    async def _visualization_evidence_read_rejection(
        self, *, scope: Any, path: Any
    ) -> dict[str, Any] | None:
        if (
            self._active_reporting_phase(scope) != "analysis"
            or self._active_reporting_task_kind(scope) != "visualization_section"
        ):
            return None
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
            durable = await self._durable_state(scope)
            expected = None
            committed_script = self._latest_committed_write_identity(durable.payload, normalized)
            if committed_script is not None:
                _parameters, contract = self._phase_parameters(scope, "analysis")
                workspace = contract.get("visualizationWorkspace")
                script_path = (
                    workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
                )
                normalized_script = WorkspaceService.normalize_path(script_path, allow_root=False)[
                    0
                ]
                if normalized == normalized_script:
                    expected = committed_script
            if expected is None:
                raise ReportingError(
                    "report_visualization_evidence_path_forbidden",
                    "visualization 只能读取签发的最新已提交脚本；冻结事实只能通过查询工具访问。",
                )
            current = (await self.kernel.service.abatch_hash_files(scope.thread_id, [normalized]))[
                0
            ]
            actual = {
                "path": current.get("path"),
                "size": current.get("size"),
                "sha256": current.get("sha256"),
            }
            if current.get("missing") is True or actual != expected:
                raise ReportingError(
                    "report_visualization_script_identity_changed",
                    "visualization 签发脚本身份已变化。",
                )
            return None
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error, retryable=False)

    async def _visualization_terminal_rejection(
        self, *, scope: Any, arguments: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        if self._active_reporting_task_kind(scope) != "visualization_section":
            return None
        command = arguments.get("command")
        workdir = arguments.get("workdir")
        try:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            workspace = contract.get("visualizationWorkspace")
            script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
            normalized_script = WorkspaceService.normalize_path(script_path, allow_root=False)[0]
            parts = shlex.split(command) if isinstance(command, str) and "\n" not in command else []
            if workdir not in {None, ""} or parts != ["python3", normalized_script]:
                raise ReportingError(
                    "report_visualization_terminal_forbidden",
                    "visualization terminal 只允许从工作区根目录执行签发脚本。",
                    details={"allowedCommand": f"python3 {normalized_script}"},
                )
            durable = await self._durable_state(scope)
            latest_committed = self._latest_committed_write_identity(
                durable.payload, normalized_script
            )
            current = (
                await self.kernel.service.abatch_hash_files(scope.thread_id, [normalized_script])
            )[0]
            if (
                current.get("missing") is True
                or latest_committed is None
                or latest_committed.get("size") != current.get("size")
                or latest_committed.get("sha256") != current.get("sha256")
            ):
                raise ReportingError(
                    "report_visualization_script_identity_changed",
                    "签发脚本身份未提交或已发生变化。",
                )
            return None
        except (ReportingError, WorkspaceError, ValueError) as error:
            return self._failure(error, retryable=False)

    def _visualization_process_rejection(
        self,
        *,
        scope: Any,
        arguments: Mapping[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any] | None:
        if self._active_reporting_task_kind(scope) != "visualization_section":
            return None
        state = self._session_state(run_context)
        sessions = state.get("reportingVisualizationSessions", ()) if state is not None else ()
        action = arguments.get("action")
        session_id = arguments.get("session_id")
        if action not in {"poll", "wait", "kill"}:
            return self._failure(
                ReportingError(
                    "report_visualization_process_forbidden",
                    "visualization process 只允许查询、等待或终止签发脚本 session。",
                ),
                retryable=False,
            )
        if not isinstance(session_id, str) or session_id not in sessions:
            return self._failure(
                ReportingError(
                    "report_visualization_process_session_forbidden",
                    "process session 不属于当前 visualization Task。",
                ),
                retryable=False,
            )
        return None

    async def _apply_durable_command(
        self,
        scope: Any,
        *,
        name: str,
        payload: dict[str, Any],
        command_id: str,
    ) -> ReportingReducerResult:
        """应用持久化 command，并保留 CAS 重试后的幂等语义。"""

        command = ReportingCommand(name=name, payload=payload, commandId=command_id)
        for _ in range(3):
            state = await self._durable_state(scope)
            try:
                result = await self._state_repository.apply(
                    state.report_run_id,
                    command,
                    expected_version=state.state_version,
                )
                return result
            except ReportingStateError as error:
                if error.code == "report_state_conflict":
                    continue
                raise ReportingError(error.code, error.message) from error
        raise ReportingError("report_state_conflict", "Reporting 状态并发更新冲突，请重试。")

    async def _apply_durable(
        self,
        scope: Any,
        *,
        name: str,
        payload: dict[str, Any],
        command_id: str,
    ) -> ReportingRunState:
        """兼容既有工具调用方，只返回持久化后的状态。"""

        result = await self._apply_durable_command(
            scope,
            name=name,
            payload=payload,
            command_id=command_id,
        )
        return result.state

    async def _invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[Any], Awaitable[Any]],
        run_context: RunContext | None,
    ) -> Any:
        async def guarded_call(scope: Any) -> Any:
            phase = self._active_reporting_phase(scope)
            task_kind = self._active_reporting_task_kind(scope)
            if phase is not None and not reporting_phase_allows_tool(
                phase, tool_name, task_kind=task_kind
            ):
                # Toolkit 为避免 Agno 跨 run 缓存污染而保留能力全集，但执行权限只来自
                # 当前 Task 的受信 acceptance contract；模型投影或旧历史都不能绕过。
                return self._failure(
                    ReportingError(
                        "report_phase_tool_forbidden",
                        f"phase={phase} 不能调用 {tool_name}。",
                    ),
                    retryable=False,
                )
            if tool_name in {"read_file", "read_lines"}:
                rejection = await self._section_evidence_read_rejection(
                    scope=scope,
                    path=arguments.get("path"),
                )
                if rejection is not None:
                    return rejection
                rejection = await self._visualization_evidence_read_rejection(
                    scope=scope, path=arguments.get("path")
                )
                if rejection is not None:
                    return rejection
            if phase == "analysis" and tool_name == "terminal":
                visualization_rejection = await self._visualization_terminal_rejection(
                    scope=scope, arguments=arguments
                )
                if visualization_rejection is not None:
                    return visualization_rejection
                dependency_rejection = await self._analysis_python_dependency_rejection(
                    scope=scope,
                    command=arguments.get("command"),
                    workdir=arguments.get("workdir"),
                )
                if dependency_rejection is not None:
                    return dependency_rejection
            if phase == "analysis" and tool_name == "process":
                process_rejection = self._visualization_process_rejection(
                    scope=scope, arguments=arguments, run_context=run_context
                )
                if process_rejection is not None:
                    return process_rejection
            result = await call(scope)
            if (
                phase == "analysis"
                and task_kind == "visualization_section"
                and tool_name == "terminal"
                and isinstance(result, Mapping)
                and result.get("status") == "running"
                and isinstance(result.get("session_id"), str)
                and (state := self._session_state(run_context)) is not None
            ):
                sessions = set(state.get("reportingVisualizationSessions", ()))
                sessions.add(result["session_id"])
                state["reportingVisualizationSessions"] = sorted(sessions)
            return result

        return await super()._invoke(tool_name, arguments, guarded_call, run_context)

    async def _state_admission_rejection(
        self,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Reporting 不进入通用 Coding 的 mutation/verify/finish 状态机。"""

        # Report Worker 必须在同一 mutation 上连续完成脚本写入、执行、evidence
        # 落盘和 checkpoint；其 verify 工具已被移除，事实校验由当前 phase 白名单、
        # analysis recovery/cursor、文件 SHA-256、阶段提交工具和 Workflow 最终验收共同
        # 承担。若继续继承通用门禁，首次写文件后下一次 terminal 会被要求调用一个并不
        # 存在的 verify，形成不可恢复活锁。这里只关闭那套互斥状态机，所有 Reporting
        # 专属门禁仍由上面的 guarded_call 和各阶段提交工具执行，不能从此入口绕过。
        _ = scope, tool_name, arguments, state
        return None

    @staticmethod
    def _complete_phase_plan(state: dict[str, Any] | None) -> None:
        if state is None:
            return
        plan = validated_agent_plan(state.get(AGENT_PLAN_STATE_KEY))
        if plan is None or all(item["status"] == "completed" for item in plan["plan"]):
            return
        # phase 产物已通过严格 schema、文件身份和幂等冻结校验，此时当前 run 的工作
        # 已由服务端确认完成。必须在签发 finish_task 前同步关闭模型计划，否则通用
        # Coding 门禁会要求模型在冻结后继续 update_plan，而 Reporting 又不暴露 verify。
        state[AGENT_PLAN_STATE_KEY] = {
            "plan": [{"step": item["step"], "status": "completed"} for item in plan["plan"]],
            "explanation": plan["explanation"],
        }

    async def _finish_phase_task(
        self,
        *,
        scope: Any,
        phase: str,
        identity: dict[str, Any],
        summary: str,
        state: dict[str, Any] | None,
        run_context: RunContext | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._complete_phase_plan(state)
        finish_result = await self.kernel.finish_task(
            summary,
            [identity["path"]],
            None,
            [],
            run_context,
            self._finish_function,
            _scope=scope,
        )
        if finish_result.get("status") != "accepted":
            return finish_result
        return {
            "ok": True,
            "status": "accepted",
            "phase": phase,
            "artifactFile": identity,
            "taskFinished": True,
            **(extra or {}),
        }

    @staticmethod
    def _failure(error: Exception, *, retryable: bool = True) -> dict[str, Any]:
        if not isinstance(error, (ReportingError, ValidationError)):
            # 只有稳定的业务拒绝和严格 schema 错误可以进入模型上下文。Workspace、
            # Daytona、文件解码、图片解析及其他运行时异常必须保留原对象，交给外层
            # tool hook 和 Agno Agent retry；否则包装回执会把基础设施故障误判成模型错误。
            raise error
        validation_errors: list[dict[str, str]] = []
        if isinstance(error, ReportingError):
            code = error.code
            message = error.message
        else:
            code = "report_tool_arguments_invalid"
            message = "Reporting 工具参数不符合严格 schema。"
            # 只返回定位修复所需的稳定结构，不回显 input、ctx 或文档 URL。
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:20]:
                path = "arguments"
                for part in item["loc"]:
                    path += f"[{part}]" if isinstance(part, int) else f".{part}"
                validation_errors.append(
                    {
                        "path": path,
                        "code": str(item["type"]),
                        "message": str(item["msg"])[:300],
                    }
                )
            validation_errors = [
                item
                for item in validation_errors
                if not any(
                    other["path"].startswith((f"{item['path']}.", f"{item['path']}["))
                    for other in validation_errors
                    if other is not item
                )
            ]
        if code in {
            "report_analysis_already_submitted",
            "report_section_already_submitted",
            "report_chart_registration_closed",
        }:
            retryable = False
        result: dict[str, Any] = {
            "ok": False,
            "status": "rejected",
            "code": code,
            "message": message,
            "requiredActions": ["按服务端错误反馈修正后重试。"],
            "retryable": retryable,
        }
        if (
            code == "report_analysis_write_path_conflict"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            paths = error.details.get("paths")
            if isinstance(paths, list):
                result["details"] = {
                    "paths": [path for path in paths if isinstance(path, str)],
                    "currentFiles": error.details.get("currentFiles", []),
                    "recoveryOperation": error.details.get("recoveryOperation"),
                }
            result["requiredActions"] = [
                "只使用 details.currentFiles 中当前 64 位 sha256 调用 overwrite_analysis_file 覆盖。"
            ]
        elif (
            code == "report_analysis_dependency_missing"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("scriptPath", "missingModules", "missingPaths")
                if key in error.details
            }
        elif (
            code in {"report_replace_target_not_found", "report_replace_target_ambiguous"}
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("path", "matchCount", "preview")
                if key in error.details
            }
        elif (
            code == "report_chart_citation_dataset_mismatch"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = {
                key: error.details[key]
                for key in ("chartId", "sourceDatasetId", "citationDatasetIds")
                if key in error.details
            }
        elif (
            code
            in {
                "report_period_basis_conflict",
                "report_section_claim_brief_conflict",
                "report_section_claim_chart_conflict",
                "report_cross_source_inference_unsupported",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            # Section 语义校验可能一次发现多个 claim/chart 冲突；完整保留受信
            # expected/actual 字段，避免模型只能看到第一个错误后重新生成整个章节。
            result["details"] = dict(error.details)
        elif (
            code
            in {
                "report_analysis_write_intent_invalid",
                "report_analysis_python_syntax_invalid",
                "report_analysis_evidence_missing",
                "report_analysis_evidence_not_registered",
                "report_analysis_evidence_identity_mismatch",
                "report_analysis_overwrite_target_missing",
                "report_profile_query_invalid",
                "report_analysis_context_query_invalid",
                "report_analysis_facts_query_invalid",
            }
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            result["details"] = dict(error.details)
        if validation_errors:
            result["validationErrors"] = validation_errors
            result["requiredActions"] = ["仅修正 validationErrors 指向的字段后重新调用当前工具。"]
        elif code == "report_analysis_evidence_missing":
            result["requiredActions"] = [
                "先使用 create_analysis_file 或 overwrite_analysis_file 写入真实 evidence，再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_not_registered":
            result["requiredActions"] = [
                "通过 create_analysis_file 或 overwrite_analysis_file 对 details.missingRegistration 中的文件做幂等登记，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_identity_mismatch":
            result["requiredActions"] = [
                "文件已在登记后发生变化；通过 overwrite_analysis_file 提交当前内容和 SHA-256，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_overwrite_target_missing":
            result["requiredActions"] = ["改用 create_analysis_file 创建该目标文件。"]
        elif code == "report_analysis_dependency_missing":
            result["requiredActions"] = [
                "只创建 details.missingPaths 指向的缺失本地模块，再运行原脚本。"
            ]
        elif code == "report_analysis_write_intent_invalid":
            result["requiredActions"] = [
                "保持 toolName 不变，只按 details.expectedFields 和 details.path 修正 arguments；"
                "不要在 arguments 内嵌套 toolName 或第二层 arguments。"
            ]
        elif code == "report_analysis_python_syntax_invalid":
            result["requiredActions"] = [
                "修正 details.path 指向的 Python 语法错误后，使用原 operation 重新提交。"
            ]
        elif code == "report_chart_registration_closed":
            result["requiredActions"] = ["图表已完成不可变登记；不要改图或重复提交。"]
        elif (
            code == "report_visualization_terminal_forbidden"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            allowed_command = error.details.get("allowedCommand")
            if isinstance(allowed_command, str) and allowed_command:
                result["details"] = {"allowedCommand": allowed_command}
            result["requiredActions"] = [
                "保持 workdir 为空，仅使用 details.allowedCommand 原样执行签发脚本；不要改写命令、添加 cd 或执行其他 terminal 命令。"
            ]
        elif (
            code == "report_chart_file_missing"
            and isinstance(error, ReportingError)
            and isinstance(error.details, Mapping)
        ):
            # 图表源文件未生成时给模型明确可恢复指引:不得原样重试触发
            # tool_no_progress 终态。details 只回显 sourcePath,便于定位清单项。
            result["details"] = {
                "sourcePath": error.details.get("sourcePath"),
            }
            result["requiredActions"] = [
                "从清单中移除该图表,或先生成 chartOutputRoot 下的真实 PNG 后再提交登记。"
            ]
        elif code in {
            "report_profile_query_invalid",
            "report_analysis_context_query_invalid",
            "report_analysis_facts_query_invalid",
        }:
            result["requiredActions"] = [
                "只使用 details.supportedFunctions 中的标准 JMESPath 函数改写 query。"
            ]
        result["recovery"] = ReportWorkspaceTaskToolkit._recovery_for_failure(
            code=code,
            details=result.get("details"),
            validation_errors=validation_errors,
        )
        if result["requiredActions"] == ["按服务端错误反馈修正后重试。"]:
            result["requiredActions"] = [
                "只依据 details 和 recovery 指向的受信字段修正当前提交；不得原样重试。"
            ]
        return result

    @staticmethod
    def _recovery_for_failure(
        *,
        code: str,
        details: Any,
        validation_errors: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        """构造与文案分离的恢复事实，避免调度层或模型改写具体纠错步骤。

        ``requiredActions`` 面向模型阅读，允许按上下文补充；本字段则只表达服务端已知的
        稳定恢复目标。无法安全推导参数变换时保留定位信息，禁止猜测并自动改写业务参数。
        """

        normalized_details = details if isinstance(details, Mapping) else {}
        tool_name = normalized_details.get("toolName")
        path = normalized_details.get("path")
        validator = normalized_details.get("validator")
        expected_fields = normalized_details.get("expectedFields")
        if validation_errors:
            return {
                "kind": "schema_validation",
                "validationErrors": [dict(item) for item in validation_errors],
            }
        if (
            code == "report_analysis_write_intent_invalid"
            and isinstance(tool_name, str)
            and isinstance(path, str)
            and isinstance(validator, str)
        ):
            recovery: dict[str, Any] = {
                "kind": "schema_validation",
                "toolName": tool_name,
                "path": path,
                "validator": validator,
            }
            if isinstance(expected_fields, list):
                recovery["expectedFields"] = [
                    field for field in expected_fields if isinstance(field, str)
                ]
            return recovery
        if code == "report_analysis_write_path_conflict":
            return {
                "kind": "overwrite_current_file",
                "toolName": "overwrite_analysis_file",
                "currentFiles": normalized_details.get("currentFiles", []),
            }
        if code == "report_analysis_overwrite_target_missing":
            return {
                "kind": "create_missing_file",
                "toolName": "create_analysis_file",
                "paths": normalized_details.get("paths", []),
            }
        if code == "report_analysis_dependency_missing":
            return {
                "kind": "create_missing_dependencies",
                "missingPaths": normalized_details.get("missingPaths", []),
            }
        if code in {
            "report_profile_query_invalid",
            "report_analysis_context_query_invalid",
            "report_analysis_facts_query_invalid",
        }:
            return {
                "kind": "rewrite_jmespath_query",
                "supportedFunctions": normalized_details.get("supportedFunctions", []),
            }
        if code == "report_analysis_evidence_missing":
            return {"kind": "create_required_evidence"}
        if code == "report_analysis_evidence_not_registered":
            return {
                "kind": "register_evidence",
                "missingRegistration": normalized_details.get("missingRegistration", []),
            }
        if code == "report_analysis_evidence_identity_mismatch":
            return {"kind": "refresh_evidence_identity"}
        if code == "report_analysis_python_syntax_invalid":
            return {
                "kind": "fix_python_syntax",
                "path": normalized_details.get("path"),
                "line": normalized_details.get("line"),
            }
        if code == "report_chart_file_missing":
            return {
                "kind": "generate_or_remove_chart",
                "sourcePath": normalized_details.get("sourcePath"),
            }
        if code == "report_analysis_rework_unresolvable":
            return {"kind": "submit_limited_claim"}
        return {
            "kind": "review_error_details",
            "code": code,
        }
