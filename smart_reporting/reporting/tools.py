"""Report worker 工具装配。"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import json
import re
import shlex
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, cast

import jmespath
from agno.run import RunContext
from agno.tools import Function, Toolkit
from jmespath.exceptions import JMESPathError
from jsonpointer import EndOfList, JsonPointer, JsonPointerException, escape
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from ..agent_control import AGENT_PLAN_STATE_KEY, validated_agent_plan
from ..task_execution.execution import (
    MAX_TOOL_OUTPUT_READ_BYTES,
    WorkspaceTaskToolkit,
    _create_files_patch,
)
from ..task_execution.tools import parse_unified_diff
from ..workspace import (
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)
from .delivery.draft_v1 import (
    ReportChartRegistration,
    ReportDraftBlock,
    validate_report_draft_blocks,
)
from .models import ReportingError
from .phase import (
    ReportingPhase,
    ReportingTaskKind,
    reporting_phase_allows_tool,
    reporting_phase_from_run_context,
    reporting_task_kind_from_run_context,
)
from .vision import ReportVisionReviewer
from .workflow.checkpoint import (
    AnalysisArtifact,
    AnalysisChart,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    AnalysisReworkRequest,
    FileIdentity,
    MetricDefinition,
    ProfileReadReceipt,
    ReportBrief,
    SectionArtifact,
    SectionWorkItem,
)
from .workflow.repository import ReportingStateRepository
from .workflow.state import ReportingCommand, ReportingRunState, ReportingStateError

REPORT_PHASE_OUTPUT_STATE_KEY = "agentos_reporting_phase_output"
MAX_REPORT_CHART_BYTES = 10 * 1024 * 1024
MAX_PROFILE_POINTER_ITEMS = 200
MAX_PROFILE_POINTER_OUTPUT_BYTES = 16 * 1024
MAX_ANALYSIS_PYTHON_DEPENDENCIES = 100
MAX_ANALYSIS_PYTHON_SOURCE_BYTES = 2 * 1024 * 1024
MAX_ANALYSIS_WRITE_INTENT_BYTES = 4 * 1024 * 1024
REPORT_WORKER_TOOLKIT_INSTRUCTIONS = (
    "当前 Reporting Task 只能使用本轮实际注册的工具；未注册工具不存在。\n"
    "直接使用任务 JSON 中的受信工作区相对路径，不浏览根目录、不猜测路径。\n"
    "严格按工具 schema 直接传参，并以每次服务端回执决定下一步。"
)
ANALYSIS_WRITE_TOOL_NAMES = frozenset(
    {"overwrite_file", "replace_text", "create_files", "apply_patch"}
)
ANALYSIS_WRITE_PUBLIC_TOOL_NAMES = frozenset(
    {"create_file", "overwrite_file", "replace_text", "apply_patch"}
)
_ANALYSIS_WRITE_OPERATION_FIELDS = {
    "create_file": frozenset({"path", "content"}),
    "overwrite_file": frozenset({"path", "content", "expected_sha256"}),
    "replace_text": frozenset({"path", "old_string", "new_string", "replace_all"}),
    "apply_patch": frozenset({"patch"}),
}
JMESPATH_FUNCTION_NAMES = tuple(sorted(jmespath.functions.Functions.FUNCTION_TABLE))
ANALYSIS_CONTEXT_QUERY_EXAMPLES = (
    "datasets[].{datasetId: datasetId, rowCount: rowCount, periodCoverage: periodCoverage}",
    "datasets[].{datasetId: datasetId, metrics: metricSemantics[].fieldRef}",
)
_ANALYSIS_SUMMARY_PERIOD_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?:(?P<full>全年)|(?P<start>\d{1,2})(?:[-—–至到](?P<end>\d{1,2}))?月)"
)
_ANALYSIS_SUMMARY_SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？]?|\n")
_INCOMPARABLE_YOY_WARNING = "摘要中的比较期间长度不一致，已将“同比”规范为“参考对比”。"


def _normalize_analysis_summary_comparability(summary: str) -> tuple[str, tuple[str, ...]]:
    """只规范摘要中能确定识别为不等长月份窗口的“同比”表述。"""

    normalized: list[str] = []
    changed = False
    for sentence in _ANALYSIS_SUMMARY_SENTENCE_PATTERN.findall(summary):
        periods = list(_ANALYSIS_SUMMARY_PERIOD_PATTERN.finditer(sentence))
        lengths = [
            12
            if match.group("full")
            else int(match.group("end") or match.group("start")) - int(match.group("start")) + 1
            for match in periods[:2]
        ]
        if "同比" in sentence and len(lengths) == 2 and lengths[0] != lengths[1]:
            sentence = sentence.replace("同比", "参考对比")
            changed = True
        normalized.append(sentence)
    return "".join(normalized), ((_INCOMPARABLE_YOY_WARNING,) if changed else ())


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _profile_receipt_command_id(receipt: Mapping[str, Any]) -> str:
    return f"profile-receipt:{receipt['receiptId']}:{_stable_digest(receipt)}"


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
        and fc.result.get("status") == "accepted"
        and fc.result.get("taskFinished") is True
    )


def _derive_durable_analysis_binding(
    durable_item: Mapping[str, Any],
) -> dict[str, Any]:
    """从单项耐久账本派生 Finalize 绑定，忽略模型的过期精简副本。

    ProfileCoverage 由服务端独立证明完整性；只有单项结论实际读取并提交的 receipt
    才能绑定 evidence。Dataset 相同不能证明该查询被当前结论使用。
    """

    dataset_ids = [value for value in durable_item.get("datasetIds", ()) if isinstance(value, str)]
    explicit_receipt_ids = [
        value for value in durable_item.get("profileReadReceiptIds", ()) if isinstance(value, str)
    ]
    return {
        **dict(durable_item),
        "datasetIds": dataset_ids,
        "citationIds": [
            value for value in durable_item.get("citationIds", ()) if isinstance(value, str)
        ],
        "chartIds": [value for value in durable_item.get("chartIds", ()) if isinstance(value, str)],
        "profileReadReceiptIds": list(dict.fromkeys(explicit_receipt_ids)),
    }


def _analysis_context_projection(
    analysis_context: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """构造稳定、类型化的分析上下文视图，避免模型枚举大型装配 JSON。"""

    raw_plans = contract.get("analysisPlans")
    plans = raw_plans if isinstance(raw_plans, Mapping) else {}
    current_analysis_id = contract.get("currentAnalysisId")
    current_analysis = (
        plans.get(current_analysis_id)
        if isinstance(current_analysis_id, str)
        and isinstance(plans.get(current_analysis_id), Mapping)
        else None
    )
    task_kind = contract.get("taskKind")
    if task_kind == "analysis_item" and not isinstance(current_analysis, Mapping):
        raise ReportingError(
            "report_analysis_context_invalid",
            "当前 analysis item 缺少受信计划投影。",
        )
    selected_dataset_ids = {
        value
        for value in (
            current_analysis.get("datasetIds", ())
            if isinstance(current_analysis, Mapping)
            else contract.get("datasetIds", ())
        )
        if isinstance(value, str)
    }
    raw_contexts = analysis_context.get("datasetContexts")
    dataset_contexts = raw_contexts if isinstance(raw_contexts, list) else []
    dataset_fields = (
        "datasetId",
        "path",
        "size",
        "sha256",
        "rowCount",
        "columnCount",
        "fields",
        "numericFields",
        "periodCoverage",
        "periodValues",
        "organizationGrain",
        "metricSemantics",
        "sourceWarnings",
        "qualityWarnings",
        "timeSeriesSortField",
        "timeSeriesFields",
    )
    datasets = [
        {key: item[key] for key in dataset_fields if key in item}
        for item in dataset_contexts
        if isinstance(item, Mapping)
        and isinstance(item.get("datasetId"), str)
        and (not selected_dataset_ids or item["datasetId"] in selected_dataset_ids)
    ]
    return {
        "version": 1,
        "taskKind": task_kind,
        "currentAnalysis": dict(current_analysis)
        if isinstance(current_analysis, Mapping)
        else None,
        "datasets": datasets,
        "warnings": [
            value for value in analysis_context.get("warnings", ()) if isinstance(value, str)
        ],
    }


def _analysis_write_parameters(functions: Mapping[str, Function]) -> dict[str, Any]:
    """从底层 Function 生成唯一的扁平写入 schema。"""

    schemas: dict[str, dict[str, Any]] = {}
    for tool_name in ANALYSIS_WRITE_TOOL_NAMES:
        function = functions.get(tool_name)
        if function is None or not isinstance(function.parameters, dict):
            raise RuntimeError(f"缺少 analysis 写入原语 schema: {tool_name}")
        schemas[tool_name] = deepcopy(function.parameters)
    create_files = schemas["create_files"]["properties"]["files"]
    create_files["maxItems"] = 1
    create = create_files["items"]["properties"]
    create["content"]["description"] = (
        "完整文件内容。长脚本使用 content 单字符串一次提交；整体受 4 MiB 写入意图上限约束。"
    )
    overwrite = schemas["overwrite_file"]["properties"]
    replace = schemas["replace_text"]["properties"]
    patch = schemas["apply_patch"]["properties"]
    return {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": sorted(ANALYSIS_WRITE_PUBLIC_TOOL_NAMES),
                "description": (
                    "选择一次写入操作。新建完整脚本示例："
                    '{"operation":"create_file","path":"analysis/report.py",'
                    '"content":"def main():\\n    pass\\n"}。'
                ),
            },
            "path": deepcopy(create["path"]),
            "content": deepcopy(create["content"]),
            "expected_sha256": deepcopy(overwrite["expected_sha256"]),
            "old_string": deepcopy(replace["old_string"]),
            "new_string": deepcopy(replace["new_string"]),
            "replace_all": deepcopy(replace["replace_all"]),
            "patch": deepcopy(patch["patch"]),
        },
        "required": ["operation"],
        "additionalProperties": False,
    }


def _canonical_analysis_write_call(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """把公开简化入口映射到唯一的底层写入原语。"""

    raw = deepcopy(dict(arguments))
    if tool_name != "create_file":
        return tool_name, raw
    return "create_files", {"files": [raw]}


def _analysis_write_operation_arguments(
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """清除兼容模型为其他写入分支补出的中性空值，保留真实冲突供严格校验拒绝。"""

    allowed = _ANALYSIS_WRITE_OPERATION_FIELDS.get(operation, frozenset())
    normalized: dict[str, Any] = {}
    for key, value in arguments.items():
        # 公开入口是扁平 schema，模型可能同时填充其他操作的字段；操作已经
        # 明确选择后，只把当前分支字段映射到底层原语，避免无关字段触发严格 schema。
        if key not in allowed:
            continue
        if value is None:
            continue
        normalized[key] = value
    return normalized


def _jmespath_reporting_error(
    error: Exception,
    *,
    code: str,
    subject: str,
) -> ReportingError:
    """把 JMESPath 库异常收敛为短错误，避免工具日志展开第三方 traceback。"""

    details: dict[str, Any] = {"supportedFunctions": list(JMESPATH_FUNCTION_NAMES)}
    match = re.search(r"Unknown function:\s*([A-Za-z_][A-Za-z0-9_]*)\(\)", str(error))
    if match is not None:
        details["unsupportedFunction"] = match.group(1)
        message = (
            f"{subject} 使用了非标准函数 {match.group(1)}；"
            "请改用 details.supportedFunctions 中的标准 JMESPath 函数。"
        )
    else:
        message = f"{subject} 不是可执行的标准 JMESPath 表达式。"
    return ReportingError(code, message, details=details)


def _jsonschema_error_message(error: JsonSchemaValidationError) -> str:
    """只返回契约定位信息，禁止把可能包含整份脚本的 instance 回显给模型。"""

    if error.validator in {"required", "additionalProperties"}:
        return error.message[:300]
    messages = {
        "type": "字段类型不符合 schema。",
        "enum": "字段值不在允许集合中。",
        "oneOf": "字段必须且只能匹配一种允许结构。",
        "minLength": "文本长度小于允许下限。",
        "maxLength": "文本长度超过允许上限。",
        "minItems": "数组项目数小于允许下限。",
        "maxItems": "数组项目数超过允许上限。",
        "pattern": "字段格式不符合约束。",
    }
    return messages.get(str(error.validator), "字段不符合 schema 约束。")


def _collect_profile_pointers(value: Any) -> set[str]:
    pointers: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            pointers.update(_collect_profile_pointers(item))
    elif isinstance(value, list):
        for item in value:
            pointers.update(_collect_profile_pointers(item))
    elif isinstance(value, str) and value.startswith("/"):
        pointers.add(value)
    return pointers


def _decode_json_pointer(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReportingError(
            "report_profile_pointer_invalid", "Profile Pointer 必须是 RFC 6901 绝对指针。"
        )
    try:
        return tuple(JsonPointer(pointer).get_parts())
    except JsonPointerException as error:
        raise ReportingError(
            "report_profile_pointer_invalid", "Profile Pointer 包含无效转义。"
        ) from error


def _encode_json_pointer_token(value: str) -> str:
    return escape(value)


def _resolve_json_pointer(value: Any, tokens: tuple[str, ...]) -> Any:
    current = value
    try:
        for token in tokens:
            # jsonpointer 还支持任意 Python Sequence，并把数组末尾 '-' 解析为
            # EndOfList。Profile 是只读 JSON 文档，只允许 object/array 节点。
            if not isinstance(token, str) or not isinstance(current, dict | list):
                raise JsonPointerException("Profile Pointer 只能穿过 JSON object/array")
            current = JsonPointer.from_parts((token,)).resolve(current)
            if isinstance(current, EndOfList):
                raise JsonPointerException("只读 Profile Pointer 不接受数组末尾标记")
        return current
    except (JsonPointerException, TypeError, AttributeError) as error:
        raise ReportingError(
            "report_profile_pointer_unknown", "Profile Pointer 在完整 Profile 中不存在。"
        ) from error


def _bound_profile_pointer_value(value: Any, *, max_items: int) -> tuple[Any, bool]:
    remaining = max_items
    truncated = False

    high_signal_keys = {
        "value_counts_without_nan",
        "value_counts_index_sorted",
        "value_counts",
        "histogram",
        "histogram_length",
        "first_rows",
        "counts",
        "bin_edges",
    }
    low_signal_prefixes = (
        "block_alias_",
        "category_alias_",
        "character_counts",
        "word_counts",
    )

    def key_priority(key: Any, child: Any) -> tuple[int, str]:
        name = str(key)
        if not isinstance(child, (dict, list)):
            return (0, name)
        if name in high_signal_keys:
            return (1, name)
        if name.startswith(low_signal_prefixes):
            return (3, name)
        return (2, name)

    def visit_histogram(item: dict[Any, Any], depth: int) -> dict[str, Any] | None:
        nonlocal remaining, truncated
        counts = item.get("counts")
        edges = item.get("bin_edges")
        if not isinstance(counts, list) or not isinstance(edges, list):
            return None
        result: dict[str, Any] = {}
        for key in ("counts", "bin_edges"):
            if remaining <= 0:
                truncated = True
                return result
            remaining -= 1
            result[key] = []
        positions = {"counts": 0, "bin_edges": 0}
        sources = {"counts": counts, "bin_edges": edges}
        while remaining > 0 and any(
            positions[key] < len(sources[key]) for key in ("counts", "bin_edges")
        ):
            for key in ("counts", "bin_edges"):
                if remaining <= 0:
                    break
                index = positions[key]
                source = sources[key]
                if index >= len(source):
                    continue
                remaining -= 1
                result[key].append(visit(source[index], depth + 1))
                positions[key] += 1
        if any(positions[key] < len(sources[key]) for key in ("counts", "bin_edges")):
            truncated = True
        return result

    def visit(item: Any, depth: int) -> Any:
        nonlocal remaining, truncated
        if depth >= 8 and isinstance(item, (dict, list)):
            truncated = True
            return None
        if isinstance(item, dict):
            balanced_histogram = visit_histogram(item, depth)
            if balanced_histogram is not None:
                return balanced_histogram
            result: dict[str, Any] = {}
            for key, child in sorted(item.items(), key=lambda pair: key_priority(pair[0], pair[1])):
                if remaining <= 0:
                    truncated = True
                    break
                remaining -= 1
                result[str(key)] = visit(child, depth + 1)
            return result
        if isinstance(item, list):
            result_list: list[Any] = []
            for child in item:
                if remaining <= 0:
                    truncated = True
                    break
                remaining -= 1
                result_list.append(visit(child, depth + 1))
            return result_list
        if isinstance(item, str) and len(item.encode("utf-8")) > 4096:
            truncated = True
            return item.encode("utf-8")[:4096].decode("utf-8", errors="ignore")
        return item

    return visit(value, 0), truncated


class ReportWorkspaceTaskToolkit(WorkspaceTaskToolkit):
    """Report Worker 的专用工具门禁；底层锁、租约和审计复用通用 Kernel。"""

    def __init__(
        self,
        *args: Any,
        state_repository: ReportingStateRepository,
        vision_reviewer: ReportVisionReviewer | None = None,
        **kwargs: Any,
    ) -> None:
        self._vision_reviewer = vision_reviewer
        self._state_repository = state_repository
        super().__init__(*args, **kwargs)
        # Reporting 在 finalize 后由 Workflow 继续执行独立产物验收。Worker 收尾只绑定
        # 当前产物哈希，不重复要求 verify 或执行 Task acceptance validator。
        self.kernel.require_finish_verification = False
        self.kernel.evaluate_finish_acceptance = False
        self.async_functions["finish_task"].parameters["properties"].pop("verification_ids", None)
        self.functions.pop("verify", None)
        self.async_functions.pop("verify", None)
        self.async_functions["view_image"].description = (
            "使用独立视觉模型检查工作区最终图片，只返回 reviewed、modelId、summary、"
            "requiresRevision、criticalIssues、warnings 和 suggestions 等结构化文字；"
            "视觉模型不可用时返回非阻断 warning，不向 Report Worker 回传媒体。"
            '示例：{"path":"analysis/charts/trend.png","detail":"high"}'
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
        self.register(
            Function(
                name="write_analysis_files",
                description=(
                    "执行一次 analysis 文件写入；服务端保存写入意图，完成写入和 SHA-256 "
                    "校验后提交意图。公开参数使用扁平格式："
                    '{"operation":"create_file","path":"analysis/report.py",'
                    '"content":"def main():\\n    pass\\n"}。'
                    "create_file 的 content 可以一次提交完整长脚本，整体受 4 MiB 写入意图"
                    "上限约束。后续精确修改使用 apply_patch/replace_text。"
                ),
                parameters=_analysis_write_parameters(self.async_functions),
                strict=True,
                entrypoint=self.write_analysis_files,
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
                    '示例：{"datasetId":"dataset-001","query":'
                    '"variables.amount.{min: min, max: max, average: average}",'
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
                    "有界查询；常用正确示例：datasets[].{datasetId: datasetId, rowCount: rowCount, "
                    "periodCoverage: periodCoverage}；"
                    "datasets[].{datasetId: datasetId, metrics: metricSemantics[].fieldRef}。"
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
                    "JMESPath。单项示例：metrics[].{field: field, total: total}；"
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
                    "提交当前 analysisId 的摘要、Dataset、引用、Profile 回执和 Warning；"
                    "服务端自动把当前不可变固定事实绑定为 evidence。只有固定事实未覆盖时才在 "
                    "evidencePaths 提交补充 evidence；服务端接受后结束当前独立 run。"
                    "图表只能在后续 visualization 阶段登记。"
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
                name="finalize_report_analysis",
                description=(
                    "全部 analysisId 完成后一次冻结 ReportBrief、共享指标口径和全局 Warning；"
                    "服务端从 durable state 派生逐 analysis evidence、Profile 回执和已登记图表。"
                    '示例：{"reportBrief":{"objective":"分析经营表现","executiveSummary":'
                    '"收入增长但成本承压","managementQuestions":["增长是否可持续？"],'
                    '"warnings":[]},"metricDefinitions":[],"warnings":[]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "reportBrief": ReportBrief.model_json_schema(by_alias=True),
                        "metricDefinitions": {
                            "type": "array",
                            "maxItems": 500,
                            "items": MetricDefinition.model_json_schema(by_alias=True),
                        },
                        "warnings": {
                            "type": "array",
                            "maxItems": 500,
                            "items": {"type": "string", "maxLength": 2000},
                        },
                    },
                    "required": ["reportBrief"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.finalize_report_analysis,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_finished_phase_call,
            )
        )
        self.register(
            Function(
                name="request_analysis_rework",
                description=(
                    "仅当当前 SectionWorkItem 的证据不足以成稿时，提交缺口和受影响 analysisIds；"
                    "服务端只补全局分析并重跑当前章节。"
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
                name="register_report_charts",
                description=(
                    "在图表源文件最终定稿后一次登记 Coding 根据本轮不可变 CSV 生成的报告图表；"
                    "服务端校验文件身份、Dataset citation 并决定发布路径。登记后不得改写或复用"
                    "同一 chartId 的源文件。"
                    '示例：{"charts":[{"chartId":"income_trend","sourcePath":'
                    '"analysis/charts/income.png","title":"医疗收入月度趋势",'
                    '"altText":"2025年医疗收入月度变化","citationIds":["citation_001"]}]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "charts": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "items": ReportChartRegistration.model_json_schema(by_alias=True),
                        }
                    },
                    "required": ["charts"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.register_report_charts,
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
                    "图片通过 chartIds 引用。"
                    '示例：{"sectionCode":"executive_summary","blocks":[{"blockId":'
                    '"overview","markdown":"### 核心结论\n\n- 医疗收入同比增长 8.2%",'
                    '"citationIds":["citation_001"],"chartIds":["income_trend"]}]}'
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
                    },
                    "required": ["sectionCode", "blocks"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.render_report_section,
                pre_hook=_reset_stop_after_tool_call,
                post_hook=_stop_after_finished_phase_call,
            )
        )

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
        if task_kind not in {"analysis_item", "visualization", "section"}:
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
        )

    async def _record_and_bound_profile_result(
        self,
        *,
        scope: Any,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        bounded = await self._bound_analysis_result(
            scope=scope,
            tool_name=tool_name,
            result=result,
            run_context=run_context,
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

    async def read_profile_pointer(
        self,
        datasetId: str,
        profilePointer: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """核验三层文件身份后返回有界 Profile 节点。"""
        # Agno 会为名为 run_context 的普通工具入口回传 session_state
        # 快照；并行 Profile 调用按原调用顺序合并结果时，较早完成的旧快照可能覆盖
        # 其他调用已经写入的 receipt。使用框架保留的内部注入名后仍共享同一状态引用，
        # 但不会产生可回放快照，这是并行 checkpoint 写入不可绕过的不变量。
        run_context = _agno_run_context
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
        ):
            raise ReportingError(
                "report_profile_pointer_invalid", "maxItems 必须在 1 至 200 之间。"
            )
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="read_profile_pointer",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item"}),
        )
        self._require_current_analysis_dataset(contract, datasetId)
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        raw_contexts = analysis_context.get("datasetContexts")
        matches = (
            [
                item
                for item in raw_contexts
                if isinstance(item, dict) and item.get("datasetId") == datasetId
            ]
            if isinstance(raw_contexts, list)
            else []
        )
        if len(matches) != 1:
            raise ReportingError(
                "report_profile_dataset_unknown", "datasetId 不属于当前受信分析上下文。"
            )
        dataset_context = matches[0]
        profile_model_view = dataset_context.get("profileModelView")
        if not isinstance(profile_model_view, dict):
            raise ReportingError(
                "report_profile_context_invalid", "Dataset 缺少有界 Profile 索引。"
            )
        indexed_pointers = _collect_profile_pointers(profile_model_view)
        pointer_tokens = _decode_json_pointer(profilePointer)
        fields = dataset_context.get("fields")
        field_names = (
            {item for item in fields if isinstance(item, str)}
            if isinstance(fields, list)
            else set()
        )
        variable_pointer = (
            len(pointer_tokens) in {2, 3}
            and pointer_tokens[0] == "variables"
            and pointer_tokens[1] in field_names
        )
        if profilePointer not in indexed_pointers and not variable_pointer:
            raise ReportingError(
                "report_profile_pointer_unknown",
                "Profile Pointer 未在受信索引登记，或会展开禁止的完整结构。",
            )

        profile = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=dataset_context.get("profileFile"),
            identity_code="report_analysis_profile_changed",
            structure_code="report_analysis_profile_invalid",
        )
        value = _resolve_json_pointer(profile, pointer_tokens)
        receipt = ProfileReadReceipt.create(
            dataset_id=datasetId,
            profile_pointer=profilePointer,
            snapshot_hash=str(dataset_context["profileFile"]["sha256"]),
            purpose=purpose,
        )
        serialized_receipt = receipt.model_dump(mode="json", by_alias=True)
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        child_pointers = (
            {
                str(key): f"{profilePointer}/{_encode_json_pointer_token(str(key))}"
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
                if isinstance(child, (dict, list))
            }
            if isinstance(value, dict)
            else {}
        )
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "datasetId": datasetId,
                "profilePointer": profilePointer,
                "value": bounded_value,
                "childPointers": child_pointers,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "readReceipt": serialized_receipt,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                bounded = await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="read_profile_pointer",
                    arguments={
                        "datasetId": datasetId,
                        "profilePointer": profilePointer,
                        "purpose": purpose,
                        "maxItems": maxItems,
                    },
                    result=result,
                    run_context=run_context,
                )
                await self._apply_durable(
                    scope,
                    name="record_profile_receipt",
                    payload={"receipt": serialized_receipt},
                    command_id=_profile_receipt_command_id(serialized_receipt),
                )
                return bounded
            if effective_limit <= 1:
                raise ReportingError(
                    "report_profile_pointer_too_large", "Profile Pointer 标量超过工具输出边界。"
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_profile(
        self,
        datasetId: str,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """执行受限 JMESPath 查询，并把表达式绑定到完整 Profile 快照。"""

        run_context = _agno_run_context
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
        ):
            raise ReportingError(
                "report_profile_query_invalid", "JMESPath query 或 maxItems 无效。"
            )
        try:
            expression = jmespath.compile(query)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_profile_query_invalid",
                    subject="Profile query",
                )
            )
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_profile",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item"}),
        )
        self._require_current_analysis_dataset(contract, datasetId)
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        raw_contexts = analysis_context.get("datasetContexts")
        matches = (
            [
                item
                for item in raw_contexts
                if isinstance(item, dict) and item.get("datasetId") == datasetId
            ]
            if isinstance(raw_contexts, list)
            else []
        )
        if len(matches) != 1:
            raise ReportingError(
                "report_profile_dataset_unknown", "datasetId 不属于当前受信分析上下文。"
            )
        dataset_context = matches[0]
        profile = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=dataset_context.get("profileFile"),
            identity_code="report_analysis_profile_changed",
            structure_code="report_analysis_profile_invalid",
        )
        try:
            value = expression.search(profile)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_profile_query_invalid",
                    subject="Profile query",
                )
            )
        receipt = ProfileReadReceipt.create_query(
            dataset_id=datasetId,
            query=query,
            snapshot_hash=str(dataset_context["profileFile"]["sha256"]),
            purpose=purpose,
        )
        serialized_receipt = receipt.model_dump(mode="json", by_alias=True)
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "datasetId": datasetId,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "readReceipt": serialized_receipt,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                bounded = await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_profile",
                    arguments={
                        "datasetId": datasetId,
                        "query": query,
                        "purpose": purpose,
                        "maxItems": maxItems,
                    },
                    result=result,
                    run_context=run_context,
                )
                await self._apply_durable(
                    scope,
                    name="record_profile_receipt",
                    payload={"receipt": serialized_receipt},
                    command_id=_profile_receipt_command_id(serialized_receipt),
                )
                return bounded
            if effective_limit <= 1:
                raise ReportingError(
                    "report_profile_query_too_large", "JMESPath 查询标量超过工具输出边界。"
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_analysis_context(
        self,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """对受信 analysisContextFile 执行有界 JMESPath 查询。

        analysisContextFile 只承载 Dataset/期间/字段等装配事实，不属于 Profile 快照，
        因此这里只记录普通 analysis operation，不创建 ProfileReadReceipt。
        """
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 1000
        ):
            raise ReportingError(
                "report_analysis_context_query_invalid",
                "analysisContext JMESPath query、purpose 或 maxItems 无效。",
            )
        try:
            expression = jmespath.compile(query)
        except JMESPathError as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_context_query_invalid",
                    subject="analysisContext query",
                )
            )
        run_context = _agno_run_context
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_analysis_context",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item", "visualization"}),
        )
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        projection = _analysis_context_projection(analysis_context, contract)
        try:
            value = expression.search(projection)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_context_query_invalid",
                    subject="analysisContext query",
                )
            )
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "queryExamples": list(ANALYSIS_CONTEXT_QUERY_EXAMPLES),
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                return await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_analysis_context",
                    arguments={"query": query, "purpose": purpose, "maxItems": maxItems},
                    result=result,
                    run_context=run_context,
                )
            if effective_limit <= 1:
                raise ReportingError(
                    "report_analysis_context_query_too_large",
                    "analysisContext 查询标量超过工具输出边界。",
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_analysis_facts(
        self,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """校验当前任务的不可变 facts 身份后执行有界 JMESPath。"""

        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 1000
        ):
            raise ReportingError(
                "report_analysis_facts_query_invalid",
                "analysis facts JMESPath query、purpose 或 maxItems 无效。",
            )
        try:
            expression = jmespath.compile(query)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_facts_query_invalid",
                    subject="analysis facts query",
                )
            )
        run_context = _agno_run_context
        scope = await self.kernel.scope(run_context)
        _parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_analysis_facts",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item", "visualization"}),
        )
        raw_fact_files = contract.get("deterministicFactFiles")
        if not isinstance(raw_fact_files, dict):
            raise ReportingError(
                "report_analysis_facts_invalid", "当前 Task 缺少不可变 facts 注册表。"
            )
        task_kind = contract.get("taskKind")
        current_analysis_id = contract.get("currentAnalysisId")
        if task_kind == "analysis_item":
            analysis_ids = (
                [current_analysis_id]
                if isinstance(current_analysis_id, str) and current_analysis_id
                else []
            )
        else:
            raw_analysis_ids = contract.get("analysisIds")
            analysis_ids = [
                value for value in raw_analysis_ids or () if isinstance(value, str) and value
            ]
        if not analysis_ids or any(
            analysis_id not in raw_fact_files for analysis_id in analysis_ids
        ):
            raise ReportingError(
                "report_analysis_facts_invalid", "当前 Task 的 facts 注册表不完整。"
            )
        durable_items: Mapping[str, Any] = {}
        if task_kind == "visualization" and contract.get("visualizationBudgetVersion") == 1:
            durable = await self._durable_state(scope)
            raw_completed = durable.payload.get("completedAnalysisIds")
            completed_ids = [
                value for value in raw_completed or () if isinstance(value, str) and value
            ]
            if len(completed_ids) != len(analysis_ids) or set(completed_ids) != set(analysis_ids):
                raise ReportingError(
                    "report_analysis_facts_invalid",
                    "visualization facts 查询与 durable 完成集合不一致。",
                )
            raw_items = durable.payload.get("analysisItems")
            if not isinstance(raw_items, Mapping):
                raise ReportingError(
                    "report_analysis_facts_invalid", "durable analysisItems 注册表无效。"
                )
            durable_items = raw_items
        plans = (
            durable.payload.get("analysisPlans")
            if task_kind == "visualization" and contract.get("visualizationBudgetVersion") == 1
            else contract.get("analysisPlans")
        )
        plans = plans if isinstance(plans, Mapping) else {}
        documents = []
        for analysis_id in analysis_ids:
            document = await self._read_trusted_json(
                thread_id=scope.thread_id,
                identity=raw_fact_files[analysis_id],
                identity_code="report_analysis_facts_changed",
                structure_code="report_analysis_facts_invalid",
            )
            projected: dict[str, Any] = {"analysisId": analysis_id, "facts": document}
            if durable_items:
                item = durable_items.get(analysis_id)
                plan = plans.get(analysis_id)
                if not isinstance(item, Mapping):
                    raise ReportingError(
                        "report_analysis_facts_invalid",
                        "durable analysis item 注册表不完整。",
                    )
                projected.update(
                    {
                        "summary": item.get("summary"),
                        "plan": (
                            {
                                key: plan.get(key)
                                for key in (
                                    "analysisId",
                                    "domain",
                                    "step",
                                    "primaryMetricFamily",
                                    "datasetIds",
                                )
                                if key in plan
                            }
                            if isinstance(plan, Mapping)
                            else None
                        ),
                        "evidenceFiles": item.get("evidenceFiles", []),
                        "citationIds": item.get("citationIds", []),
                    }
                )
            documents.append(projected)
        search_value: Any = (
            documents[0]["facts"] if task_kind == "analysis_item" else {"analyses": documents}
        )
        try:
            value = expression.search(search_value)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_facts_query_invalid",
                    subject="analysis facts query",
                )
            )
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "analysisIds": analysis_ids,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                return await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_analysis_facts",
                    arguments={"query": query, "purpose": purpose, "maxItems": maxItems},
                    result=result,
                    run_context=run_context,
                )
            if effective_limit <= 1:
                raise ReportingError(
                    "report_analysis_facts_query_too_large",
                    "analysis facts 查询标量超过工具输出边界。",
                )
            effective_limit = max(1, effective_limit // 2)

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
        if contract.get("taskKind") == "visualization":
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

    async def _visualization_evidence_read_rejection(
        self, *, scope: Any, path: Any
    ) -> dict[str, Any] | None:
        if (
            self._active_reporting_phase(scope) != "analysis"
            or self._active_reporting_task_kind(scope) != "visualization"
        ):
            return None
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
            durable = await self._durable_state(scope)
            expected_by_path: dict[str, dict[str, Any]] = {}
            items = durable.payload.get("analysisItems")
            if isinstance(items, Mapping):
                for item in items.values():
                    files = item.get("evidenceFiles") if isinstance(item, Mapping) else None
                    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
                        continue
                    for identity in files:
                        if not isinstance(identity, Mapping):
                            continue
                        identity_path = identity.get("path")
                        if not isinstance(identity_path, str):
                            continue
                        canonical = WorkspaceService.normalize_path(
                            identity_path, allow_root=False
                        )[0]
                        frozen = {
                            "path": canonical,
                            "size": identity.get("size"),
                            "sha256": identity.get("sha256"),
                        }
                        existing = expected_by_path.get(canonical)
                        if existing is not None and existing != frozen:
                            raise ReportingError(
                                "report_visualization_evidence_identity_conflict",
                                "durable evidence 同一路径绑定了不同身份。",
                            )
                        expected_by_path[canonical] = frozen
            expected = expected_by_path.get(normalized)
            if expected is None:
                raise ReportingError(
                    "report_visualization_evidence_path_forbidden",
                    "visualization 只能读取 durable analysisItems 授权的 evidence 文件。",
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
                    "report_visualization_evidence_changed",
                    "visualization evidence 文件身份已变化。",
                )
            return None
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error, retryable=False)

    async def _visualization_terminal_rejection(
        self, *, scope: Any, arguments: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        if self._active_reporting_task_kind(scope) != "visualization":
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
            committed = [
                artifact
                for intent in durable.payload.get("writeIntents", {}).values()
                if isinstance(intent, Mapping) and intent.get("status") == "committed"
                for artifact in intent.get("artifacts", ())
                if isinstance(artifact, Mapping) and artifact.get("path") == normalized_script
            ]
            latest_committed = committed[-1] if committed else None
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
        if self._active_reporting_task_kind(scope) != "visualization":
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

    async def _apply_durable(
        self,
        scope: Any,
        *,
        name: str,
        payload: dict[str, Any],
        command_id: str,
    ) -> ReportingRunState:
        command = ReportingCommand(name=name, payload=payload, commandId=command_id)
        for _ in range(3):
            state = await self._durable_state(scope)
            try:
                result = await self._state_repository.apply(
                    state.report_run_id,
                    command,
                    expected_version=state.state_version,
                )
                return result.state
            except ReportingStateError as error:
                if error.code == "report_state_conflict":
                    continue
                raise ReportingError(error.code, error.message) from error
        raise ReportingError("report_state_conflict", "Reporting 状态并发更新冲突，请重试。")

    async def _section_work_item(
        self,
        *,
        scope: Any,
        contract: dict[str, Any],
    ) -> SectionWorkItem:
        inline = contract.get("sectionWorkItem")
        if isinstance(inline, dict):
            return SectionWorkItem.model_validate(inline)
        payload = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=contract.get("sectionWorkItemFile"),
            identity_code="report_section_work_item_changed",
            structure_code="report_section_work_item_invalid",
        )
        return SectionWorkItem.model_validate(payload)

    async def _section_evidence_read_rejection(
        self,
        *,
        scope: Any,
        path: Any,
    ) -> dict[str, Any] | None:
        try:
            if self._active_reporting_phase(scope) != "section":
                return None
            _parameters, contract = self._phase_parameters(scope, "section")
            work_item = await self._section_work_item(scope=scope, contract=contract)
            normalized_path = WorkspaceService.normalize_path(path, allow_root=False)[0]
            allowed_paths = {
                evidence_file.path
                for evidence in work_item.evidence
                for evidence_file in evidence.evidence_files
            }
            if normalized_path in allowed_paths:
                return None
            # 章节 run 的事实边界就是当前 WorkItem 冻结的 evidenceFiles。即使模型猜到
            # 其他章节或分析上下文的真实路径，也不能把那些内容重新带入当前章节历史。
            return self._failure(
                ReportingError(
                    "report_section_evidence_path_forbidden",
                    "section phase 只能读取当前 SectionWorkItem 授权的 evidence 文件。",
                ),
                retryable=False,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

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
                and task_kind == "visualization"
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

    def _validate_analysis_write_arguments(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[str, ...], dict[str, str], int]:
        """复用原工具 JSON Schema 与原生补丁解析器，冻结完整写入身份。"""

        function = self.async_functions.get(tool_name)
        if tool_name not in ANALYSIS_WRITE_TOOL_NAMES or function is None:
            raise ReportingError(
                "report_analysis_write_intent_invalid", "暂存工具不支持该写入类型。"
            )
        raw = deepcopy(dict(arguments))
        if tool_name == "create_files" and isinstance(raw.get("files"), list):
            if len(raw["files"]) != 1:
                raise ReportingError(
                    "report_analysis_write_intent_invalid",
                    "create_files 每次只能提交一个文件；单个完整长脚本可在一次调用中提交。",
                )
        try:
            Draft202012Validator(function.parameters).validate(raw)
        except JsonSchemaValidationError as error:
            path = "arguments"
            for part in error.absolute_path:
                path += f"[{part}]" if isinstance(part, int) else f".{part}"
            expected_fields = sorted(function.parameters.get("properties", {}).keys())
            raise ReportingError(
                "report_analysis_write_intent_invalid",
                f"{tool_name} 参数不符合公开 schema；请仅修正 details.path 指向的字段。",
                details={
                    "toolName": tool_name,
                    "path": path,
                    "validator": str(error.validator),
                    "message": _jsonschema_error_message(error),
                    "expectedFields": expected_fields,
                },
            ) from error
        if tool_name == "replace_text":
            raw.setdefault("replace_all", False)

        expected_states: dict[str, str] = {}

        def add_path(value: str, state: str) -> None:
            try:
                path = WorkspaceService.normalize_path(value, allow_root=False)[0]
            except WorkspaceError as error:
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "写入目标路径无效。"
                ) from error
            if path in expected_states:
                raise ReportingError(
                    "report_analysis_write_intent_invalid", "写入目标路径不能重复。"
                )
            expected_states[path] = state

        if tool_name in {"overwrite_file", "replace_text"}:
            add_path(raw["path"], "present")
        elif tool_name == "create_files":
            for item in raw["files"]:
                add_path(item["path"], "present")
        else:
            try:
                operations = parse_unified_diff(raw["patch"])
            except WorkspaceError as error:
                raise ReportingError("report_analysis_write_intent_invalid", str(error)) from error
            for operation in operations:
                if operation.operation == "delete":
                    add_path(operation.path, "absent")
                else:
                    add_path(operation.path, "present")

        payload_bytes = len(
            json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if payload_bytes > MAX_ANALYSIS_WRITE_INTENT_BYTES:
            raise ReportingError(
                "report_analysis_write_intent_too_large", "单次 analysis 写入意图超过大小上限。"
            )
        return raw, tuple(expected_states), expected_states, payload_bytes

    @staticmethod
    def _analysis_write_desired_identities(
        tool_name: str,
        canonical: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        contents: dict[str, str] = {}
        if tool_name == "create_files":
            contents = {
                item["path"]: item["content"]
                for item in canonical.get("files", ())
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and isinstance(item.get("content"), str)
            }
        elif tool_name == "overwrite_file":
            path = canonical.get("path")
            content = canonical.get("content")
            if isinstance(path, str) and isinstance(content, str):
                contents[path] = content
        return {
            WorkspaceService.normalize_path(path, allow_root=False)[0]: {
                "path": WorkspaceService.normalize_path(path, allow_root=False)[0],
                "size": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for path, content in contents.items()
        }

    async def _analysis_write_hash_files(
        self,
        *,
        thread_id: str,
        paths: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """读取写入回执；基础设施异常保留原类型交由 Agent retry。"""

        return await self.kernel.service.abatch_hash_files(thread_id, list(paths))

    async def _recover_pending_analysis_write(
        self,
        *,
        scope: Any,
        tool_name: str,
        canonical: Mapping[str, Any],
        paths: tuple[str, ...],
        intent_sha256: str,
        payload_bytes: int,
    ) -> dict[str, Any] | None:
        """提交已落盘但回执丢失的确定性写入；身份不一致时失败关闭。"""

        desired = self._analysis_write_desired_identities(tool_name, canonical)
        if not desired:
            return None
        current = await self._analysis_write_hash_files(
            thread_id=scope.thread_id,
            paths=paths,
        )
        current_by_path = {item.get("path"): item for item in current if isinstance(item, dict)}
        if all(current_by_path.get(path) == identity for path, identity in desired.items()):
            artifacts = [current_by_path[path] for path in paths]
            await self._apply_durable(
                scope,
                name="commit_write_intent",
                payload={"intentId": intent_sha256, "artifacts": artifacts},
                command_id=f"write-commit:{intent_sha256}",
            )
            return {
                "ok": True,
                "status": "committed",
                "intentSha256": intent_sha256,
                "bytes": payload_bytes,
                "artifacts": artifacts,
                "recovered": True,
            }
        present_paths = [
            path
            for path in desired
            if isinstance(current_by_path.get(path), dict)
            and current_by_path[path].get("missing") is not True
        ]
        if present_paths:
            raise ReportingError(
                "report_analysis_write_identity_mismatch",
                "待恢复写入的文件身份与已保存意图不一致。",
                details={"paths": present_paths},
            )
        return None

    async def write_analysis_files(
        self,
        operation: str,
        path: str | None = None,
        content: str | None = None,
        expected_sha256: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool | None = None,
        patch: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """在单次调用内保存写入意图、执行写入并返回文件身份。"""

        requested_arguments = _analysis_write_operation_arguments(
            operation,
            {
                "path": path,
                "content": content,
                "expected_sha256": expected_sha256,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
                "patch": patch,
            },
        )
        canonical_tool_name, canonical_input = _canonical_analysis_write_call(
            operation, requested_arguments
        )

        async def call(scope: Any) -> dict[str, Any]:
            _parameters, contract = self._phase_parameters(scope, "analysis")
            canonical, paths, expected_states, payload_bytes = (
                self._validate_analysis_write_arguments(canonical_tool_name, canonical_input)
            )
            self._require_analysis_task_output_paths(contract, paths)
            payload = json.dumps(
                {
                    "version": "1",
                    "toolName": canonical_tool_name,
                    "arguments": canonical,
                    "affectedPaths": list(paths),
                    "expectedStates": expected_states,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            intent_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            intent = json.loads(payload)
            intent["intentId"] = intent_sha256
            durable = await self._durable_state(scope)
            existing = durable.payload.get("writeIntents", {}).get(intent_sha256)
            if isinstance(existing, dict) and existing.get("status") == "committed":
                artifacts = existing.get("artifacts")
                if not isinstance(artifacts, list):
                    raise ReportingError(
                        "report_analysis_write_intent_invalid", "已提交写入意图缺少文件身份。"
                    )
                current = await self._analysis_write_hash_files(
                    thread_id=scope.thread_id,
                    paths=paths,
                )
                if current != artifacts:
                    raise ReportingError(
                        "report_analysis_write_identity_mismatch",
                        "已提交写入意图的文件身份发生变化。",
                    )
                return {
                    "ok": True,
                    "status": "committed",
                    "intentSha256": intent_sha256,
                    "bytes": payload_bytes,
                    "artifacts": artifacts,
                }
            if isinstance(existing, dict) and existing.get("status") == "pending":
                recovered = await self._recover_pending_analysis_write(
                    scope=scope,
                    tool_name=canonical_tool_name,
                    canonical=canonical,
                    paths=paths,
                    intent_sha256=intent_sha256,
                    payload_bytes=payload_bytes,
                )
                if recovered is not None:
                    return recovered
            await self._apply_durable(
                scope,
                name="record_write_intent",
                payload={"intent": intent},
                command_id=f"write-intent:{intent_sha256}",
            )
            try:
                if canonical_tool_name == "overwrite_file":
                    result = await self.kernel.patch(
                        "overwrite",
                        canonical["path"],
                        None,
                        None,
                        False,
                        None,
                        run_context,
                        content=canonical["content"],
                        expected_sha256=canonical["expected_sha256"],
                        _scope=scope,
                    )
                elif canonical_tool_name == "replace_text":
                    result = await self.kernel.patch(
                        "replace",
                        canonical["path"],
                        canonical["old_string"],
                        canonical["new_string"],
                        canonical["replace_all"],
                        None,
                        run_context,
                        _scope=scope,
                    )
                else:
                    patch = (
                        _create_files_patch(canonical["files"])
                        if canonical_tool_name == "create_files"
                        else canonical["patch"]
                    )
                    result = await self.kernel.patch(
                        "patch",
                        None,
                        None,
                        None,
                        False,
                        patch,
                        run_context,
                        _scope=scope,
                    )
            except WorkspacePathConflict as error:
                try:
                    current_files = await self._analysis_write_hash_files(
                        thread_id=scope.thread_id,
                        paths=paths,
                    )
                except Exception:
                    current_files = []
                recovery_operation = (
                    "overwrite_file"
                    if canonical_tool_name in {"create_files", "overwrite_file"}
                    else "apply_patch"
                )
                raise ReportingError(
                    "report_analysis_write_path_conflict",
                    "写入目标文件已存在或内容身份已变化。",
                    details={
                        "paths": list(paths),
                        "currentFiles": current_files,
                        "recoveryOperation": recovery_operation,
                    },
                ) from error
            if result.get("ok") is not True:
                return result
            identities = await self._analysis_write_hash_files(
                thread_id=scope.thread_id,
                paths=paths,
            )
            by_path = {item.get("path"): item for item in identities if isinstance(item, dict)}
            for path, expected_state in expected_states.items():
                identity = by_path.get(path, {})
                if (expected_state == "absent") != bool(identity.get("missing")):
                    raise ReportingError(
                        "report_analysis_write_identity_mismatch",
                        "写入后的文件身份与服务端意图不一致。",
                    )
            response = {
                "ok": True,
                "status": "committed",
                "intentSha256": intent_sha256,
                "bytes": payload_bytes,
                "artifacts": identities,
            }
            await self._apply_durable(
                scope,
                name="commit_write_intent",
                payload={"intentId": intent_sha256, "artifacts": identities},
                command_id=f"write-commit:{intent_sha256}",
            )
            if len(json.dumps(response, ensure_ascii=False).encode("utf-8")) > 8 * 1024:
                return await self.kernel.bound_tool_result(
                    scope, response, run_context, retain=True
                )
            return response

        try:
            external_run_id = self.kernel.bound_external_run_id(run_context)
            async with self.kernel.task_scheduler(external_run_id) as scheduler, scheduler.write():
                scope = await self.kernel.scope(run_context)
                self._require_phase_tool(
                    scope,
                    allowed=frozenset({"analysis"}),
                    tool_name="write_analysis_files",
                    run_context=run_context,
                )
                return await call(scope)
        except (ReportingError, WorkspaceError, ValueError) as error:
            return self._failure(error)

    @staticmethod
    def _direct_python_script_path(command: Any, workdir: Any) -> str | None:
        if not isinstance(command, str) or "\n" in command:
            return None
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
        if (
            not parts
            or re.fullmatch(r"python(?:3(?:\.\d+)?)?", PurePosixPath(parts[0]).name) is None
        ):
            return None
        script: str | None = None
        for argument in parts[1:]:
            if argument == "-m":
                return None
            if script is None and argument.startswith("-"):
                continue
            script = argument
            break
        if script is None or not script.endswith(".py"):
            return None
        base = PurePosixPath(str(workdir or ""))
        candidate = base / script
        return WorkspaceService.normalize_path(candidate.as_posix(), allow_root=False)[0]

    async def _installed_python_modules(
        self,
        *,
        thread_id: str,
        module_names: set[str],
    ) -> set[str]:
        if not module_names:
            return set()
        probe = (
            "import importlib.util,json,sys;"
            "names=json.loads(sys.argv[1]);"
            "print(json.dumps([name for name in names if importlib.util.find_spec(name) is not None]))"
        )
        command = shlex.join(["python3", "-I", "-c", probe, json.dumps(sorted(module_names))])
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            result = await sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=30)
        if getattr(result, "exit_code", None) != 0:
            raise ReportingError(
                "report_analysis_dependency_probe_failed",
                "无法确认分析脚本依赖是否完整，已拒绝执行脚本。",
            )
        try:
            parsed = json.loads(str(getattr(result, "result", "") or ""))
        except (TypeError, ValueError) as error:
            raise ReportingError(
                "report_analysis_dependency_probe_failed",
                "分析脚本依赖探测结果无效，已拒绝执行脚本。",
            ) from error
        return (
            {item for item in parsed if isinstance(item, str)}
            if isinstance(parsed, list)
            else set()
        )

    async def _analysis_python_source(self, *, thread_id: str, path: str) -> bytes:
        relative, remote = WorkspaceService.normalize_path(path, allow_root=False)
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            await self.kernel.service._avalidate_existing_path(sandbox, relative)
            info = await self.kernel.service._ainfo(sandbox, remote)
            if not self.kernel.service._is_regular_file(info):
                raise WorkspaceError("分析脚本依赖必须是普通文件。")
            if int(getattr(info, "size", 0) or 0) > MAX_ANALYSIS_PYTHON_SOURCE_BYTES:
                raise WorkspaceError("单个分析脚本依赖不能超过 2 MiB。")
            return await self.kernel.service._adownload_file(
                sandbox,
                remote,
                MAX_ANALYSIS_PYTHON_SOURCE_BYTES,
            )

    async def _analysis_python_dependency_rejection(
        self,
        *,
        scope: Any,
        command: Any,
        workdir: Any,
    ) -> dict[str, Any] | None:
        try:
            script_path = self._direct_python_script_path(command, workdir)
            if script_path is None:
                return None
            pending = [script_path]
            visited: set[str] = set()
            unresolved: dict[str, tuple[str, ...]] = {}
            while pending:
                current_path = pending.pop()
                if current_path in visited:
                    continue
                if len(visited) >= MAX_ANALYSIS_PYTHON_DEPENDENCIES:
                    raise ReportingError(
                        "report_analysis_dependency_limit",
                        "分析脚本本地依赖超过服务端预检上限，已拒绝执行。",
                    )
                visited.add(current_path)
                try:
                    content = await self._analysis_python_source(
                        thread_id=scope.thread_id,
                        path=current_path,
                    )
                except WorkspaceError as error:
                    raise ReportingError(
                        "report_analysis_script_missing",
                        f"待执行 Python 脚本不存在：{current_path}",
                    ) from error
                source = content.decode("utf-8")
                tree = ast.parse(source, filename=current_path)
                compile(tree, current_path, "exec")
                current_dir = PurePosixPath(current_path).parent
                imports: set[tuple[str, int]] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update((alias.name, 0) for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add((node.module, node.level))
                        elif node.level:
                            imports.update(
                                (alias.name, node.level)
                                for alias in node.names
                                if alias.name != "*"
                            )
                for module_name, level in imports:
                    module_parts = module_name.split(".")
                    base = current_dir
                    roots: tuple[PurePosixPath, ...]
                    if level:
                        for _index in range(level - 1):
                            base = base.parent
                        roots = (base,)
                    else:
                        roots = tuple(dict.fromkeys((current_dir, PurePosixPath("."))))
                    candidates: list[str] = []
                    for root in roots:
                        module_path = root.joinpath(*module_parts)
                        candidates.extend(
                            (
                                f"{module_path.as_posix()}.py",
                                (module_path / "__init__.py").as_posix(),
                            )
                        )
                    normalized = tuple(
                        WorkspaceService.normalize_path(path, allow_root=False)[0]
                        for path in dict.fromkeys(candidates)
                    )
                    identities = await self.kernel.service.abatch_hash_files(
                        scope.thread_id, list(normalized)
                    )
                    local_path = next(
                        (
                            str(item.get("path"))
                            for item in identities
                            if isinstance(item, Mapping) and item.get("missing") is not True
                        ),
                        None,
                    )
                    if local_path is not None:
                        pending.append(local_path)
                    elif level:
                        unresolved[module_name] = normalized
                    else:
                        unresolved.setdefault(module_name.split(".", 1)[0], normalized)
            installed = (
                await self._installed_python_modules(
                    thread_id=scope.thread_id,
                    module_names=set(unresolved),
                )
                if unresolved
                else set()
            )
            missing = {
                module_name: candidates
                for module_name, candidates in unresolved.items()
                if module_name not in installed
            }
            if not missing:
                return None
            missing_paths = sorted({paths[0] for paths in missing.values()})
            return self._failure(
                ReportingError(
                    "report_analysis_dependency_missing",
                    "分析脚本存在缺失的工作区本地 Python 依赖，已拒绝执行。",
                    details={
                        "scriptPath": script_path,
                        "missingModules": sorted(missing),
                        "missingPaths": missing_paths,
                    },
                ),
                retryable=False,
            )
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error, retryable=False)

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
        finish_function = self.async_functions.get("finish_task")
        if finish_function is None:
            raise ReportingError(
                "report_phase_contract_invalid",
                "Reporting Worker 缺少底层 finish_task。",
            )
        finish_result = await self.kernel.finish_task(
            summary,
            [identity["path"]],
            None,
            [],
            run_context,
            finish_function,
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

    async def finalize_report_analysis(
        self,
        reportBrief: dict[str, Any],
        metricDefinitions: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """冻结全局分析事实；后续章节只能消费该产物，不继承本 run 消息。"""

        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="finalize_report_analysis",
                run_context=run_context,
                task_kinds=frozenset({"visualization"}),
            )
            durable = await self._durable_state(scope)
            parameters, contract = self._phase_parameters(scope, "analysis")
            output_path = parameters.get("analysisOutputPath")
            expected_analysis_ids = contract.get("analysisIds")
            known_dataset_ids = contract.get("datasetIds")
            known_citation_ids = contract.get("citationIds")
            if (
                not isinstance(output_path, str)
                or not isinstance(expected_analysis_ids, list)
                or not isinstance(known_dataset_ids, list)
                or not isinstance(known_citation_ids, list)
            ):
                raise ReportingError(
                    "report_phase_contract_invalid", "Analysis Task 缺少冻结注册表。"
                )
            submitted = durable.payload.get("analysisItems")
            if not isinstance(submitted, dict) or any(
                not isinstance(submitted.get(item), dict) for item in expected_analysis_ids
            ):
                raise ReportingError(
                    "report_analysis_evidence_invalid", "耐久分析账本未完整覆盖全部 analysisId。"
                )
            # complete_analysis_item 已冻结 Dataset、fact 文件、Profile receipt、citation
            # 与 chart。Finalize 只按批准顺序从耐久账本派生，不接受模型重新提交 evidence。
            evidence = [
                {
                    **submitted[item],
                    "evidencePaths": [
                        entry.get("path")
                        for entry in submitted[item].get("evidenceFiles", ())
                        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
                    ],
                }
                for item in expected_analysis_ids
            ]
            metricDefinitions = metricDefinitions or []
            warnings = warnings or []

            receipts = tuple(
                ProfileReadReceipt.model_validate(item)
                for item in (durable.payload.get("profileReadReceipts", ()))
            )
            receipt_ids = {item.receipt_id for item in receipts}
            receipts_by_id = {item.receipt_id: item for item in receipts}
            chart_registry = {
                item["chartId"]: item
                for item in durable.payload.get("charts", ())
                if isinstance(item, dict) and isinstance(item.get("chartId"), str)
            }

            parsed_evidence: list[AnalysisEvidence] = []
            for item in evidence:
                if not isinstance(item, dict):
                    raise ReportingError(
                        "report_analysis_evidence_invalid", "analysis evidence 必须是对象。"
                    )
                allowed = {
                    "analysisId",
                    "summary",
                    "datasetIds",
                    "evidencePaths",
                    "citationIds",
                    "chartIds",
                    "profileReadReceiptIds",
                    "warnings",
                    "evidenceFiles",
                }
                if set(item) - allowed:
                    raise ReportingError(
                        "report_analysis_evidence_invalid", "analysis evidence 包含未注册字段。"
                    )
                analysis_id = item.get("analysisId")
                durable_item = (
                    submitted.get(analysis_id)
                    if isinstance(submitted, dict) and isinstance(analysis_id, str)
                    else None
                )
                if isinstance(durable_item, dict):
                    # CompleteAnalysisItem 已在 CAS 聚合中冻结 Dataset、引用、Profile
                    # receipt 和文件身份。Dataset coverage 不等于分布事实被结论使用，
                    # Finalize 因此只保留单项显式提交的 receipt，不按 Dataset 自动补齐。
                    item = _derive_durable_analysis_binding(durable_item)
                paths = item.get("evidencePaths")
                supplied_identities = item.get("evidenceFiles")
                if not paths and isinstance(supplied_identities, list):
                    paths = [
                        entry.get("path")
                        for entry in supplied_identities
                        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
                    ]
                if (
                    not isinstance(paths, list)
                    or not paths
                    or len(paths) > 50
                    or len(paths) != len(set(paths))
                    or any(not isinstance(path, str) or not path for path in paths)
                ):
                    raise ReportingError(
                        "report_analysis_evidence_invalid",
                        "每项 analysis 必须绑定 1 至 50 个不重复 evidencePaths。",
                    )
                identities = await asyncio.gather(
                    *(self.kernel.service.ahash_file(scope.thread_id, path) for path in paths)
                )
                if any(identity.get("missing") for identity in identities):
                    raise ReportingError(
                        "report_analysis_evidence_missing", "analysis evidence 文件不存在。"
                    )
                if isinstance(supplied_identities, list) and supplied_identities != identities:
                    raise ReportingError(
                        "report_analysis_evidence_identity_mismatch",
                        "analysis evidence 文件身份在单项完成后发生变化。",
                        details={"paths": paths},
                    )
                parsed = AnalysisEvidence.model_validate(
                    {
                        **{
                            key: value
                            for key, value in item.items()
                            if key not in {"evidencePaths", "evidenceFiles"}
                        },
                        "evidenceFiles": identities,
                    }
                )
                if set(parsed.dataset_ids) - set(known_dataset_ids):
                    raise ReportingError(
                        "report_analysis_dataset_unknown",
                        "analysis evidence 引用了未授权 Dataset。",
                    )
                if set(parsed.citation_ids) - set(known_citation_ids):
                    raise ReportingError(
                        "report_analysis_citation_unknown",
                        "analysis evidence 引用了未注册 citation。",
                    )
                if set(parsed.chart_ids) - set(chart_registry):
                    raise ReportingError(
                        "report_analysis_chart_unknown", "analysis evidence 引用了未登记图表。"
                    )
                if set(parsed.profile_read_receipt_ids) - receipt_ids:
                    raise ReportingError(
                        "report_profile_receipt_unknown",
                        "analysis evidence 引用了不存在的 ProfileReadReceipt。",
                    )
                if any(
                    receipts_by_id[receipt_id].dataset_id not in parsed.dataset_ids
                    for receipt_id in parsed.profile_read_receipt_ids
                ):
                    raise ReportingError(
                        "report_profile_receipt_dataset_mismatch",
                        "analysis evidence 绑定的 ProfileReadReceipt 不属于其 Dataset 范围。",
                    )
                parsed_evidence.append(parsed)
            if [item.analysis_id for item in parsed_evidence] != expected_analysis_ids:
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    "analysis evidence 必须按冻结顺序精确覆盖全部 analysisId。",
                )
            bound_profile_receipt_ids = {
                receipt_id
                for item in parsed_evidence
                for receipt_id in item.profile_read_receipt_ids
            }
            # Profile receipt 只有被 analysis 显式绑定时才能证明实际使用；Dataset 相同只
            # 能证明曾经读取，不能由服务端推断归属。图表仍可按 citation 交集确定性绑定，
            # 无法证明归属的图表保持未使用并由 finalize 排除。
            bound_chart_ids = {chart_id for item in parsed_evidence for chart_id in item.chart_ids}
            for chart_id, chart in chart_registry.items():
                if chart_id in bound_chart_ids or not isinstance(chart, dict):
                    continue
                raw_citation_ids = chart.get("citationIds")
                if not isinstance(raw_citation_ids, (list, tuple)):
                    continue
                chart_citation_ids = {
                    value for value in raw_citation_ids if isinstance(value, str) and value
                }
                selected_index: int | None = None
                selected_overlap = 0
                for index, candidate_evidence in enumerate(parsed_evidence):
                    overlap = len(chart_citation_ids.intersection(candidate_evidence.citation_ids))
                    if overlap > selected_overlap:
                        selected_index = index
                        selected_overlap = overlap
                if selected_index is None:
                    continue
                selected = parsed_evidence[selected_index]
                parsed_evidence[selected_index] = selected.model_copy(
                    update={"chart_ids": (*selected.chart_ids, chart_id)}
                )
                bound_chart_ids.add(chart_id)

            parsed_charts: list[AnalysisChart] = []
            for chart_id, chart in chart_registry.items():
                if not isinstance(chart, dict):
                    raise ReportingError("report_analysis_chart_invalid", "图表登记状态无效。")
                source_path = chart.get("sourcePath")
                if not isinstance(source_path, str):
                    raise ReportingError("report_analysis_chart_invalid", "图表缺少源路径。")
                current = await self.kernel.service.ahash_file(scope.thread_id, source_path)
                if (
                    current.get("missing")
                    or current.get("size") != chart.get("size")
                    or current.get("sha256") != chart.get("sha256")
                ):
                    raise ReportingError(
                        "report_analysis_chart_changed", f"图表 {chart_id} 在冻结前发生变化。"
                    )
                parsed_charts.append(
                    AnalysisChart.model_validate(
                        {
                            "chartId": chart_id,
                            "sourceFile": current,
                            "title": chart.get("title"),
                            "altText": chart.get("altText"),
                            "citationIds": chart.get("citationIds"),
                        }
                    )
                )

            artifact = AnalysisArtifact(
                reportBrief=ReportBrief.model_validate(reportBrief),
                evidenceManifest=AnalysisEvidenceManifest(
                    evidence=tuple(parsed_evidence),
                    metricDefinitions=tuple(
                        MetricDefinition.model_validate(item) for item in metricDefinitions
                    ),
                    charts=tuple(parsed_charts),
                    warnings=tuple(warnings),
                ),
                profileReadReceipts=tuple(
                    receipt
                    for receipt in receipts
                    if receipt.receipt_id in bound_profile_receipt_ids
                ),
            )
            serialized = artifact.model_dump(mode="json", by_alias=True)
            phase_state = (
                state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
            )
            if isinstance(phase_state, dict):
                if (
                    phase_state.get("phase") != "analysis"
                    or phase_state.get("payload") != serialized
                ):
                    raise ReportingError(
                        "report_analysis_already_submitted",
                        "当前 analysis run 已冻结阶段产物，不能替换。",
                    )
                identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                    mode="json", by_alias=True
                )
            else:
                identity = await self._write_phase_json(
                    scope=scope,
                    path=output_path,
                    payload=serialized,
                    run_context=run_context,
                )
                if state is not None:
                    state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                        "phase": "analysis",
                        "payload": serialized,
                        "artifactFile": identity,
                    }
            return await self._finish_phase_task(
                scope=scope,
                phase="analysis",
                identity=identity,
                summary="全局分析、证据清单和指标口径已冻结。",
                state=state,
                run_context=run_context,
                extra={
                    "analysisCount": len(parsed_evidence),
                    "profileReadReceiptCount": len(receipts),
                },
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def complete_analysis_item(
        self,
        analysisId: str,
        summary: str,
        datasetIds: list[str],
        evidencePaths: list[str],
        citationIds: list[str],
        profileReadReceiptIds: list[str],
        warnings: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """把不可变固定事实直接绑定为 evidence，并结束对应的独立 Task。

        模型只在固定事实存在缺口时提交补充 evidencePaths；服务端始终追加当前 analysis
        的 deterministic fact 文件，并按路径、大小和 SHA-256 校验 durable artifact 账本。
        durable 游标已推进但 Task 收尾中断时，只允许相同 payload 在新 attempt 中幂等恢复，
        任何字段或文件身份变化都拒绝。
        """

        try:
            scope = await self.kernel.scope(run_context)
            _parameters, contract = self._phase_parameters(scope, "analysis")
            if contract.get("taskKind") != "analysis_item":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "complete_analysis_item 只允许 analysis_item Task 调用。",
                )
            expected = contract.get("analysisIds")
            if not isinstance(expected, list) or expected != [analysisId]:
                raise ReportingError("report_analysis_item_unknown", "analysisId 不在冻结计划中。")
            durable_current = await self._durable_state(scope)
            analysis_items = durable_current.payload.get("analysisItems")
            durable_item = (
                analysis_items.get(analysisId) if isinstance(analysis_items, dict) else None
            )
            self._require_analysis_output_paths(contract, evidencePaths)
            summary, comparability_warnings = _normalize_analysis_summary_comparability(summary)
            warnings = list(dict.fromkeys((*warnings, *comparability_warnings)))
            payload: dict[str, Any] = {
                "analysisId": analysisId,
                "summary": summary,
                "datasetIds": datasetIds,
                "evidencePaths": evidencePaths,
                "citationIds": citationIds,
                "profileReadReceiptIds": profileReadReceiptIds,
                "warnings": warnings,
            }
            deterministic_files = contract.get("deterministicFactFiles")
            deterministic_identity = (
                deterministic_files.get(analysisId)
                if isinstance(deterministic_files, dict)
                else None
            )
            if isinstance(deterministic_identity, dict):
                deterministic_path = deterministic_identity.get("path")
                if isinstance(deterministic_path, str) and deterministic_path:
                    evidencePaths = list(dict.fromkeys((*evidencePaths, deterministic_path)))
                    payload["evidencePaths"] = evidencePaths
            if not evidencePaths:
                raise ReportingError(
                    "report_analysis_evidence_missing",
                    "当前 analysis 缺少可绑定的不可变固定事实或补充 evidence。",
                )
            expected_datasets = contract.get("analysisDatasetIds")
            if isinstance(expected_datasets, dict):
                planned = expected_datasets.get(analysisId)
                if isinstance(planned, list) and set(datasetIds) != set(planned):
                    raise ReportingError(
                        "report_analysis_dataset_mismatch",
                        "analysis item 必须精确绑定服务端计划中的 Dataset。",
                    )
            receipts = durable_current.payload.get("profileReadReceipts")
            receipt_by_id = {
                item.get("receiptId"): item
                for item in receipts or ()
                if isinstance(item, dict) and isinstance(item.get("receiptId"), str)
            }
            unknown_receipt_ids = set(profileReadReceiptIds) - set(receipt_by_id)
            if unknown_receipt_ids:
                raise ReportingError(
                    "report_profile_receipt_unknown",
                    "analysis item 引用了不存在的 ProfileReadReceipt。",
                )
            if any(
                receipt_by_id[receipt_id].get("datasetId") not in set(datasetIds)
                for receipt_id in profileReadReceiptIds
            ):
                raise ReportingError(
                    "report_profile_receipt_dataset_mismatch",
                    "analysis item 绑定的 ProfileReadReceipt 不属于其 Dataset 范围。",
                )
            identities = await self.kernel.service.abatch_hash_files(scope.thread_id, evidencePaths)
            await self._ensure_registered_analysis_evidence(scope=scope, identities=identities)
            payload["evidenceFiles"] = identities
            if isinstance(durable_item, dict):
                if durable_item != payload:
                    raise ReportingError(
                        "report_analysis_item_completion_conflict",
                        "analysisId 已绑定其他完成 payload，不能替换。",
                    )
                durable = durable_current
            else:
                durable = await self._apply_durable(
                    scope,
                    name="complete_analysis_item",
                    payload=payload,
                    command_id=f"analysis-item:{analysisId}:{_stable_digest(payload)}",
                )
            next_id = durable.payload.get("currentAnalysisId")
            self._complete_phase_plan(self._session_state(run_context))
            finish_function = self.async_functions.get("finish_task")
            if finish_function is None:
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Reporting Worker 缺少底层 finish_task。",
                )
            finish_result = await self.kernel.finish_task(
                f"分析项 {analysisId} 已提交冻结事实与证据。",
                [item["path"] for item in identities],
                None,
                [],
                run_context,
                finish_function,
                _scope=scope,
            )
            if finish_result.get("status") != "accepted":
                return finish_result
            return {
                "ok": True,
                "status": "accepted",
                "analysisId": analysisId,
                "readyToFinalize": next_id is None,
                "taskFinished": True,
            }
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error)

    @staticmethod
    def _analysis_evidence_registration_status(
        *,
        durable: ReportingRunState,
        identities: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        """返回缺失、未登记和身份变化的 evidence 路径。"""

        missing: list[str] = []
        for item in identities:
            path = item.get("path")
            if item.get("missing") is True and isinstance(path, str):
                missing.append(path)
        payload = durable.payload if isinstance(durable.payload, dict) else {}
        registered: list[dict[str, Any]] = []
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            registered.extend(item for item in artifacts if isinstance(item, dict))
        intents = payload.get("writeIntents")
        if isinstance(intents, dict):
            for intent in intents.values():
                if not isinstance(intent, dict) or intent.get("status") != "committed":
                    continue
                committed = intent.get("artifacts")
                if isinstance(committed, list):
                    registered.extend(item for item in committed if isinstance(item, dict))

        registered_by_path = {
            item.get("path"): item for item in registered if isinstance(item.get("path"), str)
        }
        unregistered: list[str] = []
        changed: list[str] = []
        for identity in identities:
            if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
                continue
            path = identity["path"]
            expected = registered_by_path.get(path)
            if expected is None:
                unregistered.append(path)
            elif expected.get("size") != identity.get("size") or expected.get(
                "sha256"
            ) != identity.get("sha256"):
                changed.append(path)
        return missing, unregistered, changed

    @classmethod
    def _validate_registered_analysis_evidence(
        cls,
        *,
        durable: ReportingRunState,
        identities: list[dict[str, Any]],
    ) -> None:
        """确认 evidence 当前身份与 durable 写入登记逐项一致。"""

        missing, unregistered, changed = cls._analysis_evidence_registration_status(
            durable=durable,
            identities=identities,
        )
        if missing:
            raise ReportingError(
                "report_analysis_evidence_missing",
                "analysis evidence 文件不存在。",
                details={"paths": missing},
            )
        if changed:
            raise ReportingError(
                "report_analysis_evidence_identity_mismatch",
                "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                details={"paths": changed},
            )
        if unregistered:
            raise ReportingError(
                "report_analysis_evidence_not_registered",
                "analysis evidence 必须先通过 write_analysis_files 登记。",
                details={
                    "paths": unregistered,
                    "missingRegistration": unregistered,
                },
            )

    async def _ensure_registered_analysis_evidence(
        self,
        *,
        scope: Any,
        identities: list[dict[str, Any]],
    ) -> ReportingRunState:
        """把 terminal 等工具已写出的 evidence 身份登记到唯一 durable 账本。"""

        durable = await self._durable_state(scope)
        missing, unregistered, changed = self._analysis_evidence_registration_status(
            durable=durable,
            identities=identities,
        )
        if missing:
            raise ReportingError(
                "report_analysis_evidence_missing",
                "analysis evidence 文件不存在。",
                details={"paths": missing},
            )
        if changed:
            raise ReportingError(
                "report_analysis_evidence_identity_mismatch",
                "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                details={"paths": changed},
            )
        identities_by_path = {
            item["path"]: item
            for item in identities
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for path in unregistered:
            identity = identities_by_path[path]
            try:
                durable = await self._apply_durable(
                    scope,
                    name="record_artifact",
                    payload={"artifact": identity},
                    command_id=f"analysis-evidence:{path}:{identity.get('sha256')}",
                )
            except ReportingError as error:
                if error.code != "report_artifact_identity_mismatch":
                    raise
                raise ReportingError(
                    "report_analysis_evidence_identity_mismatch",
                    "analysis evidence 文件身份已变化，请按当前 SHA-256 重新登记。",
                    details={"paths": [path]},
                ) from error
        self._validate_registered_analysis_evidence(
            durable=durable,
            identities=identities,
        )
        return durable

    async def _render_isolated_section(
        self,
        *,
        scope: Any,
        section_code: str,
        blocks: list[dict[str, Any]],
        state: dict[str, Any] | None,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        parameters, contract = self._phase_parameters(scope, "section")
        output_path = parameters.get("sectionOutputPath")
        work_item = await self._section_work_item(scope=scope, contract=contract)
        if not isinstance(output_path, str) or section_code != work_item.section_code:
            raise ReportingError(
                "report_section_order_invalid", "当前 Task 只能提交 SectionWorkItem 指定章节。"
            )
        artifact = SectionArtifact.model_validate({"sectionCode": section_code, "blocks": blocks})
        # 章节一旦签发完成就可能被 durable checkpoint 直接恢复，因此必须在写文件和
        # complete_section 之前拒绝服务端保留标记。模型仍可在当前 section run 内根据
        # 明确回执重试，只通过 chartIds 登记图表。
        validate_report_draft_blocks(artifact.blocks)
        known_citations = {item.citation_id for item in work_item.citations}
        known_charts = {item.chart_id for item in work_item.charts}
        referenced_citations = {
            citation_id for block in artifact.blocks for citation_id in block.citation_ids
        }
        referenced_charts = {chart_id for block in artifact.blocks for chart_id in block.chart_ids}
        if referenced_citations - known_citations:
            raise ReportingError(
                "report_section_citation_unknown", "当前章节引用了 SectionWorkItem 外的 citation。"
            )
        if known_citations - referenced_citations:
            raise ReportingError(
                "report_section_citation_missing", "当前章节没有覆盖全部相关 evidence citation。"
            )
        if referenced_charts - known_charts:
            raise ReportingError(
                "report_section_chart_unknown", "当前章节引用了 SectionWorkItem 外的 chart。"
            )
        phase_state = state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
        serialized = artifact.model_dump(mode="json", by_alias=True)
        if isinstance(phase_state, dict):
            if phase_state.get("phase") != "section" or phase_state.get("payload") != serialized:
                raise ReportingError(
                    "report_section_already_submitted", "当前独立章节 run 已提交，不能替换正文。"
                )
            identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                mode="json", by_alias=True
            )
        else:
            identity = await self._write_phase_json(
                scope=scope,
                path=output_path,
                payload=serialized,
                run_context=run_context,
            )
            if state is not None:
                state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                    "phase": "section",
                    "payload": serialized,
                    "artifactFile": identity,
                }
        return await self._finish_phase_task(
            scope=scope,
            phase="section",
            identity=identity,
            summary=f"章节 {section_code} 已按冻结证据完成。",
            state=state,
            run_context=run_context,
            extra={"sectionCode": section_code},
        )

    async def request_analysis_rework(
        self,
        analysisIds: list[str],
        reason: str,
        missingEvidence: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            parameters, contract = self._phase_parameters(scope, "section")
            output_path = parameters.get("reworkRequestPath")
            work_item = await self._section_work_item(scope=scope, contract=contract)
            if not isinstance(output_path, str) or not set(analysisIds).issubset(
                work_item.analysis_ids
            ):
                raise ReportingError(
                    "report_analysis_rework_invalid",
                    "返工请求只能引用当前 SectionWorkItem 的 analysisIds。",
                )
            request = AnalysisReworkRequest(
                sectionCode=work_item.section_code,
                analysisIds=tuple(analysisIds),
                reason=reason,
                missingEvidence=tuple(missingEvidence),
            )
            serialized = request.model_dump(mode="json", by_alias=True)
            phase_state = (
                state.get(REPORT_PHASE_OUTPUT_STATE_KEY) if isinstance(state, dict) else None
            )
            if isinstance(phase_state, dict):
                if (
                    phase_state.get("phase") != "analysis_rework"
                    or phase_state.get("payload") != serialized
                ):
                    raise ReportingError(
                        "report_section_already_submitted",
                        "当前章节 run 已产生阶段产物。",
                    )
                identity = FileIdentity.model_validate(phase_state.get("artifactFile")).model_dump(
                    mode="json", by_alias=True
                )
            else:
                identity = await self._write_phase_json(
                    scope=scope,
                    path=output_path,
                    payload=serialized,
                    run_context=run_context,
                )
                if state is not None:
                    state[REPORT_PHASE_OUTPUT_STATE_KEY] = {
                        "phase": "analysis_rework",
                        "payload": serialized,
                        "artifactFile": identity,
                    }
            return await self._finish_phase_task(
                scope=scope,
                phase="analysis_rework",
                identity=identity,
                summary=f"章节 {work_item.section_code} 已提交分析补证请求。",
                state=state,
                run_context=run_context,
                extra={"sectionCode": work_item.section_code},
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

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
            if error.details.get("recoveryOperation") == "overwrite_file":
                result["requiredActions"] = [
                    "只使用 details.currentFiles 中当前 64 位 sha256 调用 overwrite_file；不得用 create_file 覆盖。"
                ]
            else:
                result["requiredActions"] = [
                    "只基于 details.currentFiles 对当前内容提交非空 apply_patch；不得提交空 patch。"
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
            code
            in {
                "report_analysis_write_intent_invalid",
                "report_analysis_evidence_missing",
                "report_analysis_evidence_not_registered",
                "report_analysis_evidence_identity_mismatch",
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
                "先使用 write_analysis_files 写入真实 evidence，再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_not_registered":
            result["requiredActions"] = [
                "通过 write_analysis_files 对 details.missingRegistration 中的文件做幂等登记，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_evidence_identity_mismatch":
            result["requiredActions"] = [
                "文件已在登记后发生变化；通过 write_analysis_files 提交当前内容和 SHA-256，"
                "再重试当前 analysis 提交。"
            ]
        elif code == "report_analysis_dependency_missing":
            result["requiredActions"] = [
                "只创建 details.missingPaths 指向的缺失本地模块，再运行原脚本。"
            ]
        elif code == "report_analysis_write_intent_invalid":
            result["requiredActions"] = [
                "保持 toolName 不变，只按 details.expectedFields 和 details.path 修正 arguments；"
                "不要在 arguments 内嵌套 toolName 或第二层 arguments。"
            ]
        elif code == "report_chart_registration_closed":
            result["requiredActions"] = [
                "图表已完成不可变登记；不要改图或重复登记，立即调用 finalize_report_analysis。"
            ]
        elif code in {
            "report_profile_query_invalid",
            "report_analysis_context_query_invalid",
            "report_analysis_facts_query_invalid",
        }:
            result["requiredActions"] = [
                "只使用 details.supportedFunctions 中的标准 JMESPath 函数改写 query。"
            ]
        return result

    async def _inspect_chart(
        self,
        *,
        thread_id: str,
        registration: ReportChartRegistration,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source_path, remote = self.kernel.service.normalize_path(
            registration.source_path, allow_root=False
        )
        async with self.kernel.service._async_client() as client:
            sandbox = await self.kernel.service._asandbox_for(client, thread_id)
            await self.kernel.service._avalidate_existing_path(sandbox, source_path)
            info = await self.kernel.service._ainfo(sandbox, remote)
            if not self.kernel.service._is_regular_file(info):
                raise ReportingError("report_chart_source_invalid", "图表源路径必须指向普通文件。")
            size = int(getattr(info, "size", 0) or 0)
            if not 0 < size <= MAX_REPORT_CHART_BYTES:
                raise ReportingError(
                    "report_chart_source_invalid", "单张图表必须大于 0 且不超过 10 MiB。"
                )
            content = await self.kernel.service._adownload_file(
                sandbox, remote, MAX_REPORT_CHART_BYTES
            )
        digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                image_format = str(image.format or "").upper()
                width, height = image.size
                colors = image.convert("RGBA").getcolors(maxcolors=2)
        except (UnidentifiedImageError, OSError) as error:
            raise ReportingError(
                "report_chart_source_invalid", "图表源文件无法解码或图片签名无效。"
            ) from error
        suffix = PurePosixPath(source_path).suffix.lower()
        if image_format == "PNG" and suffix == ".png":
            media_type = "image/png"
            extension = ".png"
        elif image_format == "JPEG" and suffix in {".jpg", ".jpeg"}:
            media_type = "image/jpeg"
            extension = ".jpg"
        else:
            raise ReportingError(
                "report_chart_source_invalid", "图表仅允许签名与扩展名一致的 PNG 或 JPEG。"
            )
        if width < 1 or height < 1 or (colors is not None and len(colors) <= 1):
            raise ReportingError("report_chart_blank", "图表图片完全空白，不能登记。")
        warnings: list[dict[str, Any]] = []
        if width < 800 or height < 450:
            warnings.append(
                {
                    "code": "chart_low_resolution",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "message": "图表分辨率偏低，已进入发布质量审核。",
                }
            )
        ratio = width / height
        if ratio > 4 or ratio < 0.25:
            warnings.append(
                {
                    "code": "chart_extreme_aspect_ratio",
                    "chartId": registration.chart_id,
                    "width": width,
                    "height": height,
                    "message": "图表宽高比极端，已进入发布质量审核。",
                }
            )
        return (
            {
                **registration.model_dump(mode="json", by_alias=True),
                "sourcePath": source_path,
                "size": len(content),
                "sha256": digest,
                "format": image_format,
                "mediaType": media_type,
                "extension": extension,
                "width": width,
                "height": height,
            },
            warnings,
        )

    async def register_report_charts(
        self,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="register_report_charts",
                run_context=run_context,
                task_kinds=frozenset({"visualization"}),
            )
            if self._active_reporting_task_kind(scope) != "visualization":
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "register_report_charts 只允许 visualization Task 调用。",
                )
            _parameters, phase_contract = self._phase_parameters(scope, "analysis")
            raw_citation_ids = phase_contract.get("citationIds")
            if (
                not isinstance(raw_citation_ids, list)
                or len(raw_citation_ids) != len(set(raw_citation_ids))
                or any(not isinstance(item, str) or not item for item in raw_citation_ids)
            ):
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "Analysis Task citation 注册表无效。",
                )
            citation_ids = tuple(raw_citation_ids)
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            if len({item.chart_id for item in parsed}) != len(parsed):
                raise ReportingError(
                    "report_chart_registration_duplicate", "同一次登记的 chartId 不能重复。"
                )
            if any(set(item.citation_ids) - set(citation_ids) for item in parsed):
                raise ReportingError("report_chart_citation_unknown", "图表引用了未注册 citation。")
            durable = await self._durable_state(scope)
            registry = {
                item["chartId"]: item
                for item in durable.payload.get("charts", ())
                if isinstance(item, dict) and isinstance(item.get("chartId"), str)
            }
            warnings: list[dict[str, Any]] = []
            registered: list[dict[str, Any]] = []
            inspected: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            for registration in parsed:
                identity, chart_warnings = await self._inspect_chart(
                    thread_id=scope.thread_id,
                    registration=registration,
                )
                existing = registry.get(registration.chart_id)
                if isinstance(existing, dict):
                    immutable_file_keys = {
                        "sourcePath",
                        "size",
                        "sha256",
                        "format",
                        "mediaType",
                        "extension",
                        "width",
                        "height",
                    }
                    if any(existing.get(key) != identity.get(key) for key in immutable_file_keys):
                        raise ReportingError(
                            "report_chart_registration_conflict",
                            f"chartId {registration.chart_id} 已绑定不同图表身份。",
                        )
                inspected.append((identity, chart_warnings))
            registration_digest = _stable_digest([identity for identity, _ in inspected])
            await self._apply_durable(
                scope,
                name="register_charts",
                payload={"charts": [identity for identity, _ in inspected]},
                command_id=f"charts:{registration_digest}",
            )
            for identity, chart_warnings in inspected:
                warnings.extend(chart_warnings)
                registered.append(
                    {
                        "chartId": identity["chartId"],
                        "sourcePath": identity["sourcePath"],
                        "size": identity["size"],
                        "sha256": identity["sha256"],
                        "format": identity["format"],
                        "width": identity["width"],
                        "height": identity["height"],
                    }
                )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        return {
            "ok": True,
            "status": "completed",
            "charts": registered,
            "warnings": warnings,
            "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
        }

    async def render_report_section(
        self,
        sectionCode: str,
        blocks: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            if self._active_reporting_phase(scope) != "section":
                raise ReportingError(
                    "report_phase_tool_forbidden",
                    "render_report_section 只允许 section Task 调用。",
                )
            return await self._render_isolated_section(
                scope=scope,
                section_code=sectionCode,
                blocks=blocks,
                state=state,
                run_context=run_context,
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    state_repository: ReportingStateRepository,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    vision_reviewer: ReportVisionReviewer | None = None,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = ReportWorkspaceTaskToolkit(
        workspace_service,
        task_repository,
        state_repository=state_repository,
        validator_registry=validator_registry,
        vision_reviewer=vision_reviewer,
    )
    if vision_reviewer is None:
        toolkit.functions.pop("view_image", None)
        toolkit.async_functions.pop("view_image", None)
    phase = reporting_phase_from_run_context(run_context)
    task_kind = reporting_task_kind_from_run_context(run_context)
    if phase is not None:
        # Agent callable-tools 缓存键已包含 phase/taskKind，因此这里可以让实际
        # Toolkit、工具说明和模型 schema 使用同一最小能力集。执行入口仍保留受信
        # phase 复核，不能通过直接方法调用绕过服务端边界。finish_task 是阶段提交
        # 工具在服务端收尾时依赖的内部函数对象，即使当前模型不应直接调用，也不能
        # 从 Toolkit 删除；write_analysis_files 同样依赖四个底层写入原语完成校验与
        # 提交。模型请求层会按 phase 白名单继续隐藏这些内部依赖。
        for functions in (toolkit.functions, toolkit.async_functions):
            for name in tuple(functions):
                internal_dependency = name == "finish_task" or (
                    phase == "analysis" and name in ANALYSIS_WRITE_TOOL_NAMES
                )
                if not internal_dependency and not reporting_phase_allows_tool(
                    phase, name, task_kind=task_kind
                ):
                    functions.pop(name, None)
        toolkit.instructions = REPORT_WORKER_TOOLKIT_INSTRUCTIONS
    return [toolkit]
