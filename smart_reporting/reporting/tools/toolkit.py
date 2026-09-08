"""Reporting Agent 工具组合与 schema 注册。"""

from __future__ import annotations

from typing import Any

from agno.run import RunContext
from agno.tools import Function

from ...task_execution import (
    DEFAULT_TERMINAL_TIMEOUT,
    MAX_READ_FILE_BYTES,
    MAX_TOOL_OUTPUT_READ_BYTES,
    normalize_task_function_call_arguments,
)
from ...workspace import (
    MAX_BACKGROUND_EXECUTION_TIMEOUT,
    WorkspaceService,
)
from ..delivery.draft_v1 import ReportChartRegistration, ReportDraftBlock
from ..models import ReportingError
from ..phase import ReportingPhase, ReportingTaskKind
from ..vision import ReportVisionReviewer
from ..workflow.checkpoint import SectionClaimSubmission
from ..workflow.repository import ReportingStateRepository
from .analysis_item import RuntimeAnalysisMixin
from .base import ReportingToolkitBase, ReportingToolRuntime
from .capabilities import tools_for_task
from .profile import MAX_PROFILE_POINTER_ITEMS, RuntimeProfileMixin
from .sections import RuntimeSectionsMixin
from .validation import analysis_patch_parameters
from .visualization import RuntimeVisualizationMixin

REPORTING_TOOLKIT_INSTRUCTIONS = (
    "当前 Reporting Task 只能使用本轮实际注册的工具；未注册工具不存在。\\n"
    "直接使用任务 JSON 中的受信工作区相对路径，不浏览根目录、不猜测路径。\\n"
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


class ReportingToolkit(
    RuntimeProfileMixin,
    RuntimeAnalysisMixin,
    RuntimeVisualizationMixin,
    RuntimeSectionsMixin,
    ReportingToolkitBase,
):
    """Reporting Agent 的专用工具门禁；执行原语由中立任务 runtime 提供。"""

    def __init__(
        self,
        workspace_service: WorkspaceService,
        task_repository: Any,
        *,
        state_repository: ReportingStateRepository,
        validator_registry: Any = None,
        vision_reviewer: ReportVisionReviewer | None = None,
        phase: ReportingPhase | None = None,
        task_kind: ReportingTaskKind | None = None,
    ) -> None:
        self._vision_reviewer = vision_reviewer
        self._state_repository = state_repository
        self._assembly_allowed_tools = tools_for_task(phase, task_kind)
        self._assembly_internal_tools = {"finish_task"}
        self.runtime = ReportingToolRuntime(
            workspace_service,
            task_repository,
            validator_registry=validator_registry,
        )
        finish_function = Function(
            name="finish_task",
            description="提交当前 Reporting Task 的最终产物。",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "artifact_paths": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["summary", "artifact_paths"],
                "additionalProperties": False,
            },
        )

        async def finish_entrypoint(
            summary: str | None = None,
            artifact_paths: list[str] | None = None,
            run_context: RunContext | None = None,
        ) -> dict[str, Any]:
            return await self._invoke(
                "finish_task",
                {"summary": summary, "artifact_paths": artifact_paths},
                lambda scope: self.runtime.finish_task(
                    summary,
                    artifact_paths,
                    None,
                    [],
                    run_context,
                    finish_function,
                    _scope=scope,
                ),
                run_context,
            )

        finish_function.entrypoint = finish_entrypoint
        ReportingToolkitBase.__init__(
            self,
            name="report_workspace_task",
            tools=[
                Function(
                    name="run_python_script",
                    description=(
                        "执行已提交到当前工作区的 Python 脚本。参数必须直接位于顶层，"
                        "不要包 arguments，也不能与其他工具并发。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "script_path": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1024,
                                "pattern": "^[^\\x00]+\\.py$",
                            },
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_TERMINAL_TIMEOUT,
                            },
                        },
                        "required": ["script_path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.run_python_script,
                ),
                Function(
                    name="read_file",
                    description='读取文件字节片段。示例：{"path":"src/app.py","offset":0}',
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "offset": {"type": "integer", "minimum": 0, "default": 0},
                            "max_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_READ_FILE_BYTES,
                                "default": MAX_READ_FILE_BYTES,
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.read_file,
                ),
                Function(
                    name="read_tool_output",
                    description=(
                        "继续读取被截断的工具输出。"
                        '示例：{"handle":"tool-output-123","offset":65536}'
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "handle": {"type": "string", "minLength": 1},
                            "offset": {"type": "integer", "minimum": 0, "default": 0},
                            "max_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_TOOL_OUTPUT_READ_BYTES,
                                "default": MAX_TOOL_OUTPUT_READ_BYTES,
                            },
                        },
                        "required": ["handle"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.read_tool_output,
                ),
                Function(
                    name="view_image",
                    description=(
                        '检查工作区图片。示例：{"path":"analysis/charts/trend.png","detail":"high"}'
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                                "default": "high",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.view_image,
                ),
                finish_function,
            ],
            instructions=REPORTING_TOOLKIT_INSTRUCTIONS,
            add_instructions=True,
        )
        registered_finish_function = self.async_functions.get("finish_task")
        if registered_finish_function is None:
            raise ReportingError(
                "report_phase_contract_invalid",
                "Reporting Agent 缺少底层 finish_task。",
            )
        self._finish_function = registered_finish_function
        self.async_functions.pop("finish_task", None)
        for hidden_tool_name in ("create_files", "overwrite_file", "replace_text", "apply_patch"):
            self.functions.pop(hidden_tool_name, None)
            self.async_functions.pop(hidden_tool_name, None)
        self.functions.pop("verify", None)
        self.async_functions.pop("verify", None)
        view_image = self.async_functions.get("view_image")
        if view_image is not None:
            view_image.description = (
                "使用独立视觉模型临时查看工作区图片；正式图表必须改用 inspect_chart 生成"
                "绑定文件哈希的耐久检查回执。"
                '{"path":"analysis/charts/trend.png","detail":"high"}'
            )
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
        self.instructions = "\\n".join(reporting_instruction_lines)
        for name, description, parameters, entrypoint in (
            (
                "apply_analysis_patch",
                "使用标准 unified diff 原子修改 analysis 文件；已有文件的当前 SHA-256 "
                "通过 expected_sha256 映射提供，值必须是 64 位小写十六进制字符串；新增文件或不需要基线时省略，"
                "禁止填写 true、false 或其他布尔值。",
                analysis_patch_parameters,
                self.apply_analysis_patch,
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
        for function in tuple([*self.functions.values(), *self.async_functions.values()]):
            if function.pre_hook is None:
                function.pre_hook = normalize_task_function_call_arguments

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
