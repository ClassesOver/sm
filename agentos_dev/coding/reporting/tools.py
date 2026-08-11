"""Report worker 工具装配。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from collections.abc import Awaitable, Callable
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, cast

from agno.exceptions import RetryAgentRun
from agno.run import RunContext
from agno.tools import Function, Toolkit
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from ...agent_control import AGENT_PLAN_STATE_KEY, validated_agent_plan
from ...task_execution.execution import WorkspaceTaskToolkit, normalize_function_call_arguments
from ...workspace import MAX_PATCH_FILES, WorkspaceError, WorkspaceService
from .delivery.draft_v1 import (
    ReportChartInput,
    ReportChartRegistration,
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)
from .delivery.report_runtime import REPORT_VISUAL_THEME
from .models import ReportingError
from .phase import ReportingPhase, reporting_phase_allows_tool
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

REPORT_DRAFT_STATE_KEY = "agentos_reporting_structured_draft"
REPORT_CHART_STATE_KEY = "agentos_reporting_registered_charts"
REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY = "agentos_reporting_tool_argument_autofixes"
REPORT_PROFILE_READ_RECEIPTS_STATE_KEY = "agentos_reporting_profile_read_receipts"
REPORT_PHASE_OUTPUT_STATE_KEY = "agentos_reporting_phase_output"
MAX_REPORT_CHART_BYTES = 10 * 1024 * 1024
MAX_PROFILE_POINTER_ITEMS = 200
MAX_PROFILE_POINTER_OUTPUT_BYTES = 16 * 1024
MAX_PROFILE_INDEX_FIELDS = 100


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw):
            raise ReportingError("report_profile_pointer_invalid", "Profile Pointer 包含无效转义。")
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _encode_json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _resolve_json_pointer(value: Any, tokens: tuple[str, ...]) -> Any:
    current = value
    for token in tokens:
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            index = int(token)
            if index < len(current):
                current = current[index]
                continue
        raise ReportingError(
            "report_profile_pointer_unknown", "Profile Pointer 在完整 Profile 中不存在。"
        )
    return current


def _bound_profile_pointer_value(value: Any, *, max_items: int) -> tuple[Any, bool]:
    remaining = max_items
    truncated = False

    def visit(item: Any, depth: int) -> Any:
        nonlocal remaining, truncated
        if depth >= 8 and isinstance(item, (dict, list)):
            truncated = True
            return None
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, child in item.items():
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


def normalize_reporting_function_call_arguments(
    fc: Any,
    run_context: RunContext | None = None,
) -> None:
    """在 Agno 2.8.2 建立工具执行链前按 strict schema 规范化 JSON 参数。"""
    normalize_function_call_arguments(
        fc,
        run_context,
        state_key=REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
        autofix_code="report_tool_arguments_unwrapped",
    )


class ReportWorkspaceTaskToolkit(WorkspaceTaskToolkit):
    """Report Worker 的专用工具门禁；底层锁、租约和审计复用通用 Kernel。"""

    def __init__(
        self,
        *args: Any,
        vision_reviewer: ReportVisionReviewer | None = None,
        **kwargs: Any,
    ) -> None:
        self._vision_reviewer = vision_reviewer
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
        self.instructions = "\n".join(
            line.replace("、verify", "")
            for line in toolkit_instructions.splitlines()
            if "verification_ids" not in line and "成功 verify" not in line
        )
        self.register(
            Function(
                name="inspect_profile_index",
                description=(
                    "读取单个 Dataset 的紧凑 Profile coverage、告警摘要和 Pointer 目录；"
                    "按章节分析时先调用本工具，再用 read_profile_pointer 定点读取所需节点。"
                    "宽表通过 nextFieldOffset 分页，不展开完整 Profile。"
                    '示例：{"datasetId":"dataset-001","fieldOffset":0,"maxFields":100}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "datasetId": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "fieldOffset": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 499,
                            "default": 0,
                        },
                        "maxFields": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PROFILE_INDEX_FIELDS,
                            "default": MAX_PROFILE_INDEX_FIELDS,
                        },
                    },
                    "required": ["datasetId"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.inspect_profile_index,
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
                name="complete_report_analysis",
                description=(
                    "全局分析完成后一次冻结 ReportBrief、逐 analysis evidence、共享指标口径、"
                    "Profile 读取回执和已登记图表；服务端写入 AnalysisEvidenceManifest。"
                    '示例：{"reportBrief":{"objective":"分析经营表现","executiveSummary":'
                    '"收入增长但成本承压","managementQuestions":["增长是否可持续？"],'
                    '"warnings":[]},"evidence":[{"analysisId":"analysis_001",'
                    '"summary":"收入同比增长","datasetIds":["dataset-001"],'
                    '"evidencePaths":["analysis/evidence.json"],'
                    '"citationIds":["citation_001"]}],"metricDefinitions":[],"warnings":[]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "reportBrief": ReportBrief.model_json_schema(by_alias=True),
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 200,
                            "items": {"type": "object"},
                        },
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
                    "required": [
                        "reportBrief",
                        "evidence",
                        "metricDefinitions",
                        "warnings",
                    ],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.complete_report_analysis,
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
            )
        )
        self.register(
            Function(
                name="discard_report_charts",
                description=(
                    "在 finalize_report_draft 前丢弃误登记且尚未被任何章节引用的预览图或"
                    "被替代图表；已引用、未知或已进入最终拼装的图表拒绝丢弃。"
                    '示例：{"chartIds":["cost_structure_preview"]}'
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "chartIds": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 100,
                            "uniqueItems": True,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 128,
                            },
                        }
                    },
                    "required": ["chartIds"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.discard_report_charts,
            )
        )
        self.register(
            Function(
                name="begin_report_draft",
                description=(
                    "开始当前报告的逐章 Markdown 成稿，返回服务端冻结的章节顺序"
                    "和供封面、正文及图表共用的 visualTheme。示例：{}"
                ),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                strict=True,
                entrypoint=self.begin_report_draft,
            )
        )
        self.register(
            Function(
                name="render_report_section",
                description=(
                    "按 begin_report_draft 返回的顺序提交一个章节。每个 block 的 markdown "
                    "不得重复服务端返回的章节 title，内部标题从 ### 开始；可直接使用列表、"
                    "引用、强调和表格；图片通过 chartIds 插入；"
                    "evidencePaths 可选，提供时服务端记录证据文件的路径、大小和 SHA-256；"
                    "finalize 前可用同一 sectionCode 重新提交并替换该章节；全部章节完成时，"
                    "必须先补齐回执 unreferencedChartIds 再定稿。"
                    '示例：{"sectionCode":"executive_summary","blocks":[{"blockId":'
                    '"overview","markdown":"### 核心结论\n\n- 医疗收入同比增长 8.2%",'
                    '"citationIds":["citation_001"],"analysisIds":["analysis_001"],'
                    '"chartIds":["income_trend"]}],"evidencePaths":'
                    '["analysis/evidence/executive_summary.json"]}'
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
                        "evidencePaths": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 50,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 512},
                        },
                    },
                    "required": ["sectionCode", "blocks"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.render_report_section,
            )
        )
        self.register(
            Function(
                name="finalize_report_draft",
                description=(
                    "全部章节提交且没有 unreferencedChartIds 后，按冻结顺序拼装最终 Markdown、"
                    "归档图表并完成服务端收尾。示例：{}"
                ),
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                strict=True,
                entrypoint=self.finalize_report_draft,
            )
        )
        for function in (*self.functions.values(), *self.async_functions.values()):
            if function.pre_hook is None:
                function.pre_hook = normalize_reporting_function_call_arguments

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

    async def _render_contract(
        self,
        scope: Any,
    ) -> tuple[
        str,
        str,
        tuple[Any, ...],
        tuple[str, ...],
        bool,
    ]:
        parameters = self._artifact_parameters(scope)
        expected = parameters.get("expectedIdentity") if isinstance(parameters, dict) else None
        contract = parameters.get("renderContract") if isinstance(parameters, dict) else None
        if (
            not isinstance(parameters, dict)
            or not isinstance(expected, dict)
            or not isinstance(contract, dict)
        ):
            raise ReportingError(
                "report_draft_contract_missing", "当前 Reporting Task 缺少服务端渲染契约。"
            )
        title = contract.get("title")
        markdown_path = expected.get("markdownPath")
        raw_sections = contract.get("sections")
        raw_citations = contract.get("citationIds")
        require_table = contract.get("requireTable")
        if contract.get("contextFileBacked") is True:
            context_file = parameters.get("validationContextFile")
            if not isinstance(context_file, dict) or not isinstance(context_file.get("path"), str):
                raise ReportingError(
                    "report_draft_contract_missing", "当前 Reporting Task 缺少渲染上下文文件。"
                )
            content, _mime = await asyncio.to_thread(
                self.kernel.service.file_bytes,
                scope.thread_id,
                context_file["path"],
            )
            if len(content) != context_file.get("size") or hashlib.sha256(
                content
            ).hexdigest() != context_file.get("sha256"):
                raise ReportingError(
                    "report_draft_contract_invalid", "渲染上下文文件身份校验失败。"
                )
            try:
                stored_context = json.loads(content)
            except (TypeError, ValueError) as error:
                raise ReportingError(
                    "report_draft_contract_invalid", "渲染上下文文件不是合法 JSON。"
                ) from error
            stored_contract = stored_context.get("renderContract")
            if not isinstance(stored_contract, dict):
                raise ReportingError(
                    "report_draft_contract_invalid", "渲染上下文缺少服务端注册表。"
                )
        if (
            not isinstance(title, str)
            or not isinstance(markdown_path, str)
            or not isinstance(raw_sections, list)
            or not isinstance(raw_citations, list)
            or not isinstance(require_table, bool)
        ):
            raise ReportingError(
                "report_draft_contract_invalid", "当前 Reporting Task 的服务端渲染契约无效。"
            )
        sections = tuple(ReportSectionDefinition.model_validate(item) for item in raw_sections)
        if any(not isinstance(item, str) for item in raw_citations):
            raise ReportingError(
                "report_draft_contract_invalid", "当前 Reporting Task 的 citation 注册表无效。"
            )
        return (
            title,
            markdown_path,
            sections,
            tuple(raw_citations),
            require_table,
        )

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
    def _active_reporting_phase(cls, scope: Any) -> ReportingPhase | None:
        task = getattr(scope, "task", None)
        if getattr(task, "acceptance_contract", None) is None:
            return None
        phase = cls._artifact_parameters(scope).get("phase")
        if phase is None:
            return None
        if phase not in {"analysis", "section"}:
            raise ReportingError("report_phase_contract_invalid", "Reporting phase 参数无效。")
        return cast(ReportingPhase, phase)

    @classmethod
    def _require_phase_tool(
        cls,
        scope: Any,
        *,
        allowed: frozenset[str],
        tool_name: str,
    ) -> None:
        # phase 来自服务端 acceptance contract，不采信模型参数。旧无 phase 草稿测试仍可调用原方法，
        # 新 analysis/section run 则只能使用本阶段工具，不能绕回共享 Draft 状态机。
        phase = cls._active_reporting_phase(scope)
        if phase is not None and phase not in allowed:
            raise ReportingError(
                "report_phase_tool_forbidden",
                f"phase={phase} 不能调用 {tool_name}。",
            )

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
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """核验三层文件身份后返回有界 Profile 节点。"""
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
        ):
            raise ReportingError(
                "report_profile_pointer_invalid", "maxItems 必须在 1 至 200 之间。"
            )
        scope = await self.kernel.scope(run_context)
        parameters = self._artifact_parameters(scope)
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="read_profile_pointer",
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
        state = self._session_state(run_context)
        serialized_receipt = receipt.model_dump(mode="json", by_alias=True)
        if state is not None:
            stored_receipts = state.get(REPORT_PROFILE_READ_RECEIPTS_STATE_KEY)
            receipts = list(stored_receipts) if isinstance(stored_receipts, list) else []
            if not any(
                isinstance(item, dict) and item.get("receiptId") == receipt.receipt_id
                for item in receipts
            ):
                receipts.append(serialized_receipt)
            state[REPORT_PROFILE_READ_RECEIPTS_STATE_KEY] = receipts[-1000:]
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "datasetId": datasetId,
                "profilePointer": profilePointer,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "readReceipt": serialized_receipt,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                return result
            if effective_limit <= 1:
                raise ReportingError(
                    "report_profile_pointer_too_large", "Profile Pointer 标量超过工具输出边界。"
                )
            effective_limit = max(1, effective_limit // 2)

    async def inspect_profile_index(
        self,
        datasetId: str,
        fieldOffset: int = 0,
        maxFields: int = MAX_PROFILE_INDEX_FIELDS,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """返回章节分析所需的紧凑 Profile 首屏和可分页字段 Pointer。"""
        if (
            isinstance(fieldOffset, bool)
            or not isinstance(fieldOffset, int)
            or fieldOffset < 0
            or isinstance(maxFields, bool)
            or not isinstance(maxFields, int)
            or not 1 <= maxFields <= MAX_PROFILE_INDEX_FIELDS
        ):
            raise ReportingError("report_profile_index_invalid", "Profile 字段分页参数无效。")
        scope = await self.kernel.scope(run_context)
        parameters = self._artifact_parameters(scope)
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="inspect_profile_index",
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
        model_view = dataset_context.get("profileModelView")
        if not isinstance(model_view, dict):
            raise ReportingError(
                "report_profile_context_invalid", "Dataset 缺少有界 Profile 索引。"
            )
        coverage = model_view.get("coverage")
        fields = dataset_context.get("fields")
        if not isinstance(coverage, dict) or not isinstance(fields, list):
            raise ReportingError("report_profile_context_invalid", "Dataset Profile 索引结构无效。")
        field_names = [item for item in fields if isinstance(item, str)]
        if fieldOffset > len(field_names):
            raise ReportingError("report_profile_index_invalid", "fieldOffset 超出字段范围。")
        page_size = min(maxFields, len(field_names) - fieldOffset)
        while True:
            selected = field_names[fieldOffset : fieldOffset + page_size]
            next_offset = fieldOffset + page_size
            correlation_pointers = {
                str(item.get("method")): item.get("profilePointer")
                for item in model_view.get("correlations", ())
                if isinstance(item, dict)
                and isinstance(item.get("method"), str)
                and isinstance(item.get("profilePointer"), str)
            }
            time_series = model_view.get("timeSeries")
            result = {
                "ok": True,
                "datasetId": datasetId,
                "coverage": {
                    **coverage,
                    "fullAlertCount": coverage.get("alertCount", 0),
                    "indexedAlertCount": len(model_view.get("alerts", ())),
                },
                "alerts": model_view.get("alerts", []),
                "truncation": {
                    key: bool(coverage.get(key, False))
                    for key in (
                        "variableIndexTruncated",
                        "detailIndexTruncated",
                        "alertIndexTruncated",
                    )
                },
                "pointerCatalog": {
                    "fieldOffset": fieldOffset,
                    "fieldCount": len(field_names),
                    "variableRoots": {
                        name: f"/variables/{_encode_json_pointer_token(name)}" for name in selected
                    },
                    "indexedFieldTypes": {
                        item["name"]: item.get("type", "Unknown")
                        for item in model_view.get("variables", ())
                        if isinstance(item, dict) and isinstance(item.get("name"), str)
                    },
                    "nextFieldOffset": next_offset if next_offset < len(field_names) else None,
                    "table": model_view.get("table", {}).get("profilePointer"),
                    "alerts": model_view.get("alertsPointer"),
                    "correlations": correlation_pointers,
                    "timeSeries": (
                        time_series.get("profilePointer") if isinstance(time_series, dict) else None
                    ),
                    "timeSeriesFields": (
                        time_series.get("fields", []) if isinstance(time_series, dict) else []
                    ),
                    "numericDetailTemplates": [
                        "/variables/{field}/histogram",
                        "/variables/{field}/skewness",
                        "/variables/{field}/kurtosis",
                    ],
                    "textDetailTemplates": [
                        "/variables/{field}/length_histogram",
                        "/variables/{field}/character_counts",
                        "/variables/{field}/word_counts",
                    ],
                },
                "highlights": model_view.get("highlights", {}),
                "chartOpportunities": model_view.get("chartOpportunities", []),
            }
            if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) <= (
                MAX_PROFILE_POINTER_OUTPUT_BYTES
            ):
                return result
            if page_size <= 1:
                raise ReportingError(
                    "report_profile_index_too_large", "Profile 索引摘要超过工具输出边界。"
                )
            page_size = max(1, page_size // 2)

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
            if phase is not None and not reporting_phase_allows_tool(phase, tool_name):
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
            return await call(scope)

        return await super()._invoke(tool_name, arguments, guarded_call, run_context)

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

    @classmethod
    def _phase_finish_response(
        cls,
        *,
        phase: str,
        identity: dict[str, Any],
        summary: str,
        state: dict[str, Any] | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cls._complete_phase_plan(state)
        return {
            "ok": True,
            "status": "accepted",
            "phase": phase,
            "artifactFile": identity,
            **(extra or {}),
            "nextToolCall": {
                "name": "finish_task",
                "arguments": {
                    "summary": summary,
                    "artifact_paths": [identity["path"]],
                },
            },
        }

    async def complete_report_analysis(
        self,
        reportBrief: dict[str, Any],
        evidence: list[dict[str, Any]],
        metricDefinitions: list[dict[str, Any]],
        warnings: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """冻结全局分析事实；后续章节只能消费该产物，不继承本 run 消息。"""

        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
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
            if not isinstance(evidence, list) or not evidence:
                raise ReportingError(
                    "report_analysis_evidence_invalid", "全局分析 evidence 不能为空。"
                )

            receipts = tuple(
                ProfileReadReceipt.model_validate(item)
                for item in (
                    state.get(REPORT_PROFILE_READ_RECEIPTS_STATE_KEY, ())
                    if isinstance(state, dict)
                    else ()
                )
            )
            receipt_ids = {item.receipt_id for item in receipts}
            chart_state = self._attempt_state(
                state, REPORT_CHART_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            raw_charts = chart_state.get("charts")
            chart_registry = raw_charts if isinstance(raw_charts, dict) else {}

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
                }
                if set(item) - allowed:
                    raise ReportingError(
                        "report_analysis_evidence_invalid", "analysis evidence 包含未注册字段。"
                    )
                paths = item.get("evidencePaths")
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
                parsed = AnalysisEvidence.model_validate(
                    {
                        **{key: value for key, value in item.items() if key != "evidencePaths"},
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
                parsed_evidence.append(parsed)
            if [item.analysis_id for item in parsed_evidence] != expected_analysis_ids:
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    "analysis evidence 必须按冻结顺序精确覆盖全部 analysisId。",
                )

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
                profileReadReceipts=receipts,
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
            return self._phase_finish_response(
                phase="analysis",
                identity=identity,
                summary="全局分析、证据清单和指标口径已冻结。",
                state=state,
                extra={
                    "analysisCount": len(parsed_evidence),
                    "profileReadReceiptCount": len(receipts),
                },
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

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
        return self._phase_finish_response(
            phase="section",
            identity=identity,
            summary=f"章节 {section_code} 已按冻结证据完成。",
            state=state,
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
            return self._phase_finish_response(
                phase="analysis_rework",
                identity=identity,
                summary=f"章节 {work_item.section_code} 已提交分析补证请求。",
                state=state,
                extra={"sectionCode": work_item.section_code},
            )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    @staticmethod
    def _failure(error: Exception, *, retryable: bool = True) -> dict[str, Any]:
        validation_errors: list[dict[str, str]] = []
        if isinstance(error, ReportingError):
            code = error.code
            message = error.message
        elif isinstance(error, ValidationError):
            code = "report_draft_invalid"
            message = "结构化报告参数不符合严格 schema。"
            # 只返回定位修复所需的稳定结构，不回显 input、ctx 或文档 URL，避免把整份
            # Draft 和内部校验细节再次塞回模型上下文。错误数量也必须有界。
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:20]:
                path = "draft"
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
        elif isinstance(error, (WorkspaceError, UnidentifiedImageError, OSError)):
            code = "report_draft_workspace_error"
            message = str(error)[:1000]
        else:
            code = "report_draft_workspace_error"
            message = "报告草稿处理失败。"
        if code in {
            "report_analysis_already_submitted",
            "report_section_already_submitted",
            "report_draft_already_submitted",
            "report_draft_already_rendered",
            "report_chart_discard_after_finalize",
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
        if validation_errors:
            result["validationErrors"] = validation_errors
            result["requiredActions"] = ["仅修正 validationErrors 指向的字段后重新调用当前工具。"]
        elif code == "report_draft_chart_unregistered":
            result["requiredActions"] = [
                "仅登记错误消息列出的缺失图表；登记齐全后服务端会自动恢复草稿。"
            ]
        elif code == "report_draft_chart_citation_invalid":
            result["requiredActions"] = [
                "使图表 citation 成为每个引用该图表的正文块 citation 子集后重试。"
            ]
        elif code == "report_draft_citation_missing":
            result["requiredActions"] = [
                "把错误消息列出的每个 citationId 添加到实际使用对应数据的正文块，"
                "再重新调用 finalize_report_draft。"
            ]
        elif code == "report_draft_already_submitted":
            result["requiredActions"] = [
                "不得重传已冻结章节；完成缺失图表登记后重新调用 finalize_report_draft。"
            ]
        return result

    @staticmethod
    def _attempt_state(
        state: dict[str, Any] | None,
        key: str,
        attempt_no: int,
    ) -> dict[str, Any]:
        if state is None:
            raise ReportingError("report_draft_state_missing", "当前工具缺少可持久化会话状态。")
        value = state.get(key)
        if not isinstance(value, dict) or value.get("attemptNo") != attempt_no:
            value = {"attemptNo": attempt_no}
            state[key] = value
        return value

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
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset({"analysis"}),
                tool_name="register_report_charts",
            )
            phase = self._active_reporting_phase(scope)
            title = ""
            markdown_path = ""
            sections: tuple[Any, ...] = ()
            require_table = False
            if phase == "analysis":
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
            else:
                (
                    title,
                    markdown_path,
                    sections,
                    citation_ids,
                    require_table,
                ) = await self._render_contract(scope)
            parsed = tuple(ReportChartRegistration.model_validate(item) for item in charts)
            if len({item.chart_id for item in parsed}) != len(parsed):
                raise ReportingError(
                    "report_chart_registration_duplicate", "同一次登记的 chartId 不能重复。"
                )
            if any(set(item.citation_ids) - set(citation_ids) for item in parsed):
                raise ReportingError("report_draft_citation_unknown", "图表引用了未注册 citation。")
            attempt_no = int(getattr(scope, "attempt_no", 0))
            registry_state = self._attempt_state(state, REPORT_CHART_STATE_KEY, attempt_no)
            raw_registry = registry_state.get("charts")
            registry = dict(raw_registry) if isinstance(raw_registry, dict) else {}
            candidate_registry = dict(registry)
            draft_state = (
                state.get(REPORT_DRAFT_STATE_KEY)
                if phase is None and isinstance(state, dict)
                else None
            )
            if not isinstance(draft_state, dict) or draft_state.get("attemptNo") != attempt_no:
                draft_state = None
            pending_bindings: dict[str, list[str]] = {}
            if draft_state is not None and draft_state.get("status") == "awaiting_charts":
                raw_pending = draft_state.get("pendingChartBindings")
                if not isinstance(raw_pending, dict) or any(
                    not isinstance(chart_id, str)
                    or not isinstance(values, list)
                    or any(not isinstance(value, str) for value in values)
                    for chart_id, values in raw_pending.items()
                ):
                    raise ReportingError(
                        "report_draft_state_invalid", "待登记图表的 citation 约束状态无效。"
                    )
                pending_bindings = {
                    str(chart_id): list(values) for chart_id, values in raw_pending.items()
                }
            warnings: list[dict[str, Any]] = []
            registered: list[dict[str, Any]] = []
            inspected: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            for registration in parsed:
                identity, chart_warnings = await self._inspect_chart(
                    thread_id=scope.thread_id,
                    registration=registration,
                )
                existing = candidate_registry.get(registration.chart_id)
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
                    # 登记后不可改写图表文件，但标题、替代文本和 citation 属于报表绑定
                    # 元数据。允许模型在同一文件哈希上原位校正这些字段，避免为了修正
                    # citation 创建新的 chartId；候选 registry 仍会在下方完整重放 Draft
                    # 约束后一次提交，不能绕过正文与来源绑定。
                    candidate_registry[registration.chart_id] = identity
                else:
                    candidate_registry[registration.chart_id] = identity
                allowed = pending_bindings.get(registration.chart_id)
                if allowed is not None and not set(identity["citationIds"]).issubset(allowed):
                    raise ReportingError(
                        "report_draft_chart_citation_invalid",
                        f"图表 {registration.chart_id} 的 citation 必须属于已冻结的正文块绑定："
                        + ", ".join(allowed),
                    )
                inspected.append((identity, chart_warnings))

            pending_chart_ids: list[str] = []
            resume_after_commit = False
            if draft_state is not None and draft_state.get("status") == "awaiting_charts":
                pending_chart_ids = sorted(set(pending_bindings) - set(candidate_registry))
                if not pending_chart_ids:
                    pending_draft = ReportDraft.model_validate(draft_state.get("draft"))
                    candidate_inputs = tuple(
                        self._archived_chart_input(identity)
                        for identity in candidate_registry.values()
                        if isinstance(identity, dict)
                    )
                    assemble_report_markdown(
                        pending_draft,
                        expected_title=title,
                        markdown_path=markdown_path,
                        sections=sections,
                        citation_ids=citation_ids,
                        charts=candidate_inputs,
                        require_table=require_table,
                    )
                    resume_after_commit = True

            # 图表解码、不可变身份和待恢复 Draft 约束全部通过后才一次性替换 registry；
            # 补齐最后一张图时还会先用候选 registry 完整重放 Draft 校验。任一失败都不能
            # 留下半批身份或推进 Draft，否则后续正确输入会被不可变状态永久阻断。
            registry_state["charts"] = candidate_registry
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
            draft_result: dict[str, Any] | None = None
            if resume_after_commit and draft_state is not None:
                draft_state["status"] = "validated"
                draft_state["pendingChartBindings"] = {}
                draft_result = await self._resume_saved_draft(
                    scope=scope,
                    state=state,
                    draft_state=draft_state,
                    run_context=run_context,
                )
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)
        if draft_result is not None and draft_result.get("ok") is not True:
            return {
                **draft_result,
                "registeredCharts": registered,
                "chartWarnings": warnings,
                "draftSaved": True,
            }
        result: dict[str, Any] = {
            "ok": True,
            "status": "completed",
            "charts": registered,
            "warnings": warnings,
            "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
        }
        if pending_chart_ids:
            result["pendingChartIds"] = pending_chart_ids
        if draft_result is not None:
            result["draftResult"] = draft_result
        return result

    async def discard_report_charts(
        self,
        chartIds: list[str],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """在最终拼装前移除没有正文引用的误登记图表。"""
        state = self._session_state(run_context)
        try:
            if (
                not isinstance(chartIds, list)
                or not 1 <= len(chartIds) <= 100
                or len(chartIds) != len(set(chartIds))
                or any(not isinstance(chart_id, str) or not chart_id for chart_id in chartIds)
            ):
                raise ReportingError(
                    "report_chart_discard_invalid",
                    "chartIds 必须是 1 至 100 个不重复图表标识。",
                )
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset(),
                tool_name="discard_report_charts",
            )
            attempt_no = int(getattr(scope, "attempt_no", 0))
            registry_state = self._attempt_state(state, REPORT_CHART_STATE_KEY, attempt_no)
            raw_registry = registry_state.get("charts")
            registry = dict(raw_registry) if isinstance(raw_registry, dict) else {}
            unknown = sorted(set(chartIds) - set(registry))
            if unknown:
                raise ReportingError(
                    "report_chart_discard_unknown",
                    "待丢弃图表未登记：" + ", ".join(unknown),
                )

            draft_state = state.get(REPORT_DRAFT_STATE_KEY) if isinstance(state, dict) else None
            if isinstance(draft_state, dict) and draft_state.get("attemptNo") == attempt_no:
                if draft_state.get("submitted") is True:
                    raise ReportingError(
                        "report_chart_discard_after_finalize",
                        "报告已经进入最终拼装，不能再丢弃图表。",
                    )
                referenced = {
                    chart_id
                    for section in draft_state.get("sections", ())
                    if isinstance(section, dict)
                    for block in section.get("blocks", ())
                    if isinstance(block, dict)
                    for chart_id in block.get("chartIds", ())
                    if isinstance(chart_id, str)
                }
                conflicts = sorted(set(chartIds) & referenced)
                if conflicts:
                    raise ReportingError(
                        "report_chart_discard_referenced",
                        "待丢弃图表已被章节引用：" + ", ".join(conflicts),
                    )

            for chart_id in chartIds:
                registry.pop(chart_id)
            registry_state["charts"] = registry
            return {
                "ok": True,
                "status": "discarded",
                "chartIds": chartIds,
            }
        except (ReportingError, WorkspaceError) as error:
            return self._failure(error)

    @staticmethod
    def _draft_chart_ids(draft: ReportDraft) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                chart_id
                for section in draft.sections
                for block in section.blocks
                for chart_id in block.chart_ids
            )
        )

    @staticmethod
    def _require_all_draft_citations(
        draft: ReportDraft,
        citation_ids: tuple[str, ...],
    ) -> None:
        referenced = {
            citation_id
            for section in draft.sections
            for block in section.blocks
            for citation_id in block.citation_ids
        }
        missing = tuple(
            citation_id for citation_id in citation_ids if citation_id not in referenced
        )
        if not missing:
            return
        # PDF/Word 验收会把全部权威 DatasetLineage citation 与 Markdown marker 做精确集合
        # 比对。草稿若只引用子集，图表和章节工具都可能成功，却必然在后续渲染阶段失败。
        # 因此必须在草稿仍可替换章节时拒绝，并只返回缺失的稳定 citationId 供定点修正。
        raise ReportingError(
            "report_draft_citation_missing",
            "正文未覆盖服务端注册 citation：" + ", ".join(missing),
        )

    @classmethod
    def _with_chart_reference_feedback(
        cls,
        result: dict[str, Any],
        *,
        stored_sections: list[Any],
        registry: dict[str, Any],
        section_count: int,
    ) -> dict[str, Any]:
        # 未引用图表不属于正文完整性错误。服务端最终装配会把它们标记为
        # unused_chart_excluded 并排除，不能要求模型为了消除预览资产而重写章节。
        del cls, stored_sections, registry, section_count
        return result

    @staticmethod
    def _unused_chart_ids(warnings: Any) -> tuple[str, ...]:
        if not isinstance(warnings, list):
            return ()
        chart_ids: set[str] = set()
        for warning in warnings:
            if not isinstance(warning, dict) or warning.get("code") != "unused_chart_excluded":
                continue
            values = warning.get("chartIds")
            if isinstance(values, list):
                chart_ids.update(item for item in values if isinstance(item, str))
        return tuple(sorted(chart_ids))

    @staticmethod
    def _draft_chart_bindings(draft: ReportDraft) -> dict[str, tuple[str, ...]]:
        bindings: dict[str, set[str]] = {}
        for section in draft.sections:
            for block in section.blocks:
                for chart_id in block.chart_ids:
                    if chart_id in bindings:
                        bindings[chart_id].intersection_update(block.citation_ids)
                    else:
                        bindings[chart_id] = set(block.citation_ids)
        if any(not values for values in bindings.values()):
            raise ReportingError(
                "report_draft_chart_citation_invalid",
                "同一图表在全部正文块中必须具有共同 citation 绑定。",
            )
        return {chart_id: tuple(sorted(citations)) for chart_id, citations in bindings.items()}

    @classmethod
    def _placeholder_charts(
        cls,
        draft: ReportDraft,
        chart_ids: set[str] | None = None,
    ) -> tuple[ReportChartInput, ...]:
        bindings = cls._draft_chart_bindings(draft)
        return tuple(
            ReportChartInput(
                chartId=chart_id,
                fileName=f"chart-{hashlib.sha256(chart_id.encode()).hexdigest()[:16]}.png",
                title="待登记图表",
                altText="待登记图表",
                citationIds=citations,
            )
            for chart_id, citations in bindings.items()
            if chart_ids is None or chart_id in chart_ids
        )

    async def _validate_and_store_draft(
        self,
        *,
        scope: Any,
        state: dict[str, Any] | None,
        draft: dict[str, Any],
    ) -> tuple[ReportDraft, str, tuple[Any, ...], tuple[str, ...], dict[str, Any]]:
        attempt_no = int(getattr(scope, "attempt_no", 0))
        draft_state = self._attempt_state(state, REPORT_DRAFT_STATE_KEY, attempt_no)
        if draft_state.get("submitted") is True:
            status = draft_state.get("status")
            raise ReportingError(
                "report_draft_already_submitted",
                (
                    "当前 Attempt 的完整 ReportDraft 已冻结并等待缺失图表登记；"
                    "不得重传，登记齐全后服务端会自动恢复。"
                    if status == "awaiting_charts"
                    else "当前 Attempt 已进入最终拼装，不能再次提交章节。"
                ),
            )
        (
            title,
            markdown_path,
            sections,
            citation_ids,
            require_table,
        ) = await self._render_contract(scope)
        parsed = ReportDraft.model_validate(draft)
        self._require_all_draft_citations(parsed, citation_ids)
        chart_state = self._attempt_state(state, REPORT_CHART_STATE_KEY, attempt_no)
        raw_registry = chart_state.get("charts")
        registry = raw_registry if isinstance(raw_registry, dict) else {}
        bindings = self._draft_chart_bindings(parsed)
        missing = set(bindings) - set(registry)
        chart_inputs = tuple(
            self._archived_chart_input(identity)
            for identity in registry.values()
            if isinstance(identity, dict)
        ) + self._placeholder_charts(parsed, missing)
        # 已登记图表必须在持久化 Draft 前用真实 citation 身份校验。只有确实缺图时
        # 才使用服务端占位身份，并冻结允许集合；语义不匹配不能把 Attempt 推入不可修改状态。
        assemble_report_markdown(
            parsed,
            expected_title=title,
            markdown_path=markdown_path,
            sections=sections,
            citation_ids=citation_ids,
            charts=chart_inputs,
            require_table=require_table,
        )
        serialized = parsed.model_dump(mode="json", by_alias=True)
        draft_id = _stable_digest(serialized)
        draft_state.update(
            {
                "submitted": True,
                "status": "awaiting_charts" if missing else "validated",
                "draftId": draft_id,
                "draft": serialized,
                "markdownPath": markdown_path,
                "pendingChartBindings": {
                    chart_id: list(bindings[chart_id]) for chart_id in sorted(missing)
                },
            }
        )
        return parsed, markdown_path, sections, citation_ids, draft_state

    @staticmethod
    def _archived_chart_input(identity: dict[str, Any]) -> ReportChartInput:
        target_name = (
            f"chart-{hashlib.sha256(str(identity['chartId']).encode()).hexdigest()[:16]}"
            f"{identity['extension']}"
        )
        return ReportChartInput(
            chartId=identity["chartId"],
            fileName=target_name,
            title=identity["title"],
            altText=identity["altText"],
            citationIds=identity["citationIds"],
        )

    async def _write_rendered_draft(
        self,
        *,
        scope: Any,
        markdown_path: str,
        markdown: str,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        current = (await self.kernel.service.abatch_hash_files(scope.thread_id, [markdown_path]))[0]
        mode = "create" if current.get("missing") is True else "overwrite"
        return await self.kernel.patch(
            mode,
            markdown_path,
            None,
            None,
            False,
            None,
            run_context,
            content=markdown,
            expected_sha256=current.get("sha256") if mode == "overwrite" else None,
            _scope=scope,
        )

    async def _resume_saved_draft(
        self,
        *,
        scope: Any,
        state: dict[str, Any] | None,
        draft_state: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        (
            title,
            markdown_path,
            sections,
            citation_ids,
            require_table,
        ) = await self._render_contract(scope)
        parsed = ReportDraft.model_validate(draft_state.get("draft"))
        self._require_all_draft_citations(parsed, citation_ids)
        attempt_no = int(getattr(scope, "attempt_no", 0))
        chart_state = self._attempt_state(state, REPORT_CHART_STATE_KEY, attempt_no)
        registry = chart_state.get("charts")
        registry = registry if isinstance(registry, dict) else {}
        referenced = self._draft_chart_ids(parsed)
        missing = [chart_id for chart_id in referenced if chart_id not in registry]
        if missing:
            raise ReportingError(
                "report_draft_chart_unregistered",
                "草稿引用了尚未登记的图表：" + ", ".join(missing),
            )
        chart_inputs = tuple(
            self._archived_chart_input(identity)
            for identity in registry.values()
            if isinstance(identity, dict)
        )
        rendered = assemble_report_markdown(
            parsed,
            expected_title=title,
            markdown_path=markdown_path,
            sections=sections,
            citation_ids=citation_ids,
            charts=chart_inputs,
            require_table=require_table,
        )
        rendered_markdown = rendered.markdown
        input_by_id = {item.chart_id: item for item in chart_inputs}
        report_parent = PurePosixPath(markdown_path).parent
        copies = []
        for chart_id in referenced:
            identity = registry[chart_id]
            destination = report_parent.joinpath(input_by_id[chart_id].file_name).as_posix()
            copies.append(
                {
                    "source": identity["sourcePath"],
                    "destination": destination,
                    "expected_sha256": identity["sha256"],
                    "expected_size": identity["size"],
                }
            )
        copied_files: list[dict[str, Any]] = []
        copy_result: dict[str, Any] = {
            "ok": True,
            "files": copied_files,
            "mutation_sequence": getattr(scope.task, "mutation_sequence", 0),
            "execution_id": None,
        }
        # 图表登记契约允许最多 100 张，而通用工作区原语为控制单次 mutation 的影响面，
        # 每批最多复制 MAX_PATCH_FILES 个文件。报告层只负责按该既有边界分批并合并回执；
        # 任一批失败都会在写 Markdown 前停止，不能留下已签发正文引用但未归档的图表。
        for offset in range(0, len(copies), MAX_PATCH_FILES):
            batch_result = await self.kernel.batch_copy_files(
                copies[offset : offset + MAX_PATCH_FILES],
                run_context,
                _scope=scope,
            )
            if batch_result.get("ok") is not True:
                return batch_result
            copied_files.extend(cast(list[dict[str, Any]], batch_result.get("files", [])))
            copy_result["mutation_sequence"] = batch_result.get(
                "mutation_sequence", copy_result["mutation_sequence"]
            )
            copy_result["execution_id"] = batch_result.get("execution_id")
        mutation = await self._write_rendered_draft(
            scope=scope,
            markdown_path=markdown_path,
            markdown=rendered_markdown,
            run_context=run_context,
        )
        if mutation.get("ok") is not True:
            return mutation
        markdown_sha256 = hashlib.sha256(rendered_markdown.encode("utf-8")).hexdigest()
        draft_state.update(
            {
                "status": "rendered",
                "markdownSha256": markdown_sha256,
                "artifactPaths": [markdown_path, *rendered.chart_paths],
                "analysisIds": list(rendered.analysis_ids),
                "archiveReceipt": copy_result.get("files", []),
                "warnings": list(rendered.warnings),
            }
        )
        return {
            "ok": True,
            "status": "completed",
            "draftId": draft_state["draftId"],
            "markdownPath": markdown_path,
            "markdownSha256": markdown_sha256,
            "artifactPaths": [markdown_path, *rendered.chart_paths],
            "analysisIds": list(rendered.analysis_ids),
            "warnings": list(rendered.warnings),
            "autoFixes": list(rendered.auto_fixes),
            "archiveReceipts": copy_result.get("files", []),
            "execution_id": mutation.get("execution_id"),
            "mutation_sequence": mutation.get("mutation_sequence"),
        }

    async def begin_report_draft(self, run_context: RunContext | None = None) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset(),
                tool_name="begin_report_draft",
            )
            (
                title,
                markdown_path,
                sections,
                _citation_ids,
                _require_table,
            ) = await self._render_contract(scope)
            draft_state = self._attempt_state(
                state, REPORT_DRAFT_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            if draft_state.get("started") is not True:
                draft_state.update(
                    {
                        "started": True,
                        "submitted": False,
                        "status": "collecting",
                        "title": title,
                        "markdownPath": markdown_path,
                        "sections": [],
                    }
                )
            accepted = draft_state.get("sections")
            accepted = accepted if isinstance(accepted, list) else []
            next_index = len(accepted)
            return {
                "ok": True,
                "status": "ready" if next_index < len(sections) else "sections_completed",
                "title": title,
                "sectionCount": len(sections),
                "acceptedSectionCount": next_index,
                "visualTheme": deepcopy(REPORT_VISUAL_THEME),
                "sections": [
                    {
                        "sectionCode": item.code,
                        "title": item.title,
                        "analysisIds": list(item.analysis_ids),
                    }
                    for item in sections
                ],
                "nextSectionCode": sections[next_index].code
                if next_index < len(sections)
                else None,
            }
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)

    async def render_report_section(
        self,
        sectionCode: str,
        blocks: list[dict[str, Any]],
        run_context: RunContext | None = None,
        *,
        evidencePaths: list[str] | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            phase = self._active_reporting_phase(scope)
            if phase == "section":
                return await self._render_isolated_section(
                    scope=scope,
                    section_code=sectionCode,
                    blocks=blocks,
                    state=state,
                    run_context=run_context,
                )
            if phase == "analysis":
                raise ReportingError(
                    "report_phase_tool_forbidden",
                    "phase=analysis 不能调用 render_report_section。",
                )
            (
                _title,
                _markdown_path,
                definitions,
                citation_ids,
                _require_table,
            ) = await self._render_contract(scope)
            draft_state = self._attempt_state(
                state, REPORT_DRAFT_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            if draft_state.get("started") is not True:
                raise ReportingError("report_draft_not_started", "必须先调用 begin_report_draft。")
            revising_unused_charts = (
                draft_state.get("submitted") is True
                and draft_state.get("status") == "rendered"
                and bool(self._unused_chart_ids(draft_state.get("warnings")))
            )
            if draft_state.get("submitted") is True and not revising_unused_charts:
                raise ReportingError("report_draft_already_finalized", "报告已经进入最终拼装阶段。")
            parsed = ReportDraftSection.model_validate(
                {"sectionCode": sectionCode, "blocks": blocks}
            )
            stored_sections = draft_state.get("sections")
            if not isinstance(stored_sections, list):
                raise ReportingError("report_draft_state_invalid", "逐章草稿状态无效。")
            existing = next(
                (
                    item
                    for item in stored_sections
                    if isinstance(item, dict) and item.get("sectionCode") == sectionCode
                ),
                None,
            )
            serialized = parsed.model_dump(mode="json", by_alias=True)
            chart_state = self._attempt_state(
                state, REPORT_CHART_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            registry = chart_state.get("charts")
            registry = registry if isinstance(registry, dict) else {}
            unknown_citations = {
                citation_id
                for block in parsed.blocks
                for citation_id in block.citation_ids
                if citation_id not in citation_ids
            }
            unknown_charts = {
                chart_id
                for block in parsed.blocks
                for chart_id in block.chart_ids
                if chart_id not in registry
            }
            if unknown_citations:
                raise ReportingError(
                    "report_section_citation_unknown",
                    "当前章节引用了未注册 citation：" + ", ".join(sorted(unknown_citations)),
                )
            if unknown_charts:
                raise ReportingError(
                    "report_section_chart_unknown",
                    "当前章节引用了未登记图表：" + ", ".join(sorted(unknown_charts)),
                )
            if evidencePaths is not None and (
                not isinstance(evidencePaths, list)
                or not 1 <= len(evidencePaths) <= 50
                or len(set(evidencePaths)) != len(evidencePaths)
                or any(not isinstance(path, str) or not path for path in evidencePaths)
            ):
                raise ReportingError(
                    "report_section_evidence_invalid",
                    "evidencePaths 必须是 1 至 50 个不重复的工作区相对文件路径。",
                )
            evidence_state = draft_state.get("sectionEvidence")
            if evidence_state is None:
                evidence_state = {}
            if not isinstance(evidence_state, dict):
                raise ReportingError("report_draft_state_invalid", "章节证据状态无效。")
            evidence_files = evidence_state.get(sectionCode, [])
            if evidencePaths is not None:
                # evidence 只提供可选的过程回执。工具记录文件身份而不读取文件内容，
                # 既保留可追溯性，也避免把大型分析结果重新展开到模型上下文。
                evidence_files = list(
                    await asyncio.gather(
                        *(
                            self.kernel.service.ahash_file(scope.thread_id, path)
                            for path in evidencePaths
                        )
                    )
                )
            if existing is not None:
                if evidencePaths is not None:
                    evidence_state[sectionCode] = evidence_files
                    draft_state["sectionEvidence"] = evidence_state
                replaced = existing != serialized
                if replaced:
                    stored_sections[stored_sections.index(existing)] = serialized
                    draft_state["draftId"] = _stable_digest(stored_sections)
                    if revising_unused_charts:
                        # unused_chart_excluded 不签发 finish，因此此时最终产物尚未交付。只允许
                        # 通过完整章节替换重新打开草稿，并清除全部旧渲染身份；下一次 finalize
                        # 必须从新 sections 重建 Markdown 与 artifactPaths，不能复用冻结回执。
                        draft_state["submitted"] = False
                        draft_state["status"] = "sections_completed"
                        for key in (
                            "draft",
                            "pendingChartBindings",
                            "markdownSha256",
                            "artifactPaths",
                            "analysisIds",
                            "archiveReceipt",
                            "warnings",
                        ):
                            draft_state.pop(key, None)
                next_index = len(stored_sections)
                return self._with_chart_reference_feedback(
                    {
                        "ok": True,
                        "status": "replaced" if replaced else "accepted",
                        "idempotent": not replaced,
                        "replaced": replaced,
                        "sectionCode": sectionCode,
                        "acceptedSectionCount": next_index,
                        "sectionCount": len(definitions),
                        "nextSectionCode": (
                            definitions[next_index].code if next_index < len(definitions) else None
                        ),
                        "evidenceFiles": evidence_files,
                    },
                    stored_sections=stored_sections,
                    registry=registry,
                    section_count=len(definitions),
                )
            next_index = len(stored_sections)
            if next_index >= len(definitions) or definitions[next_index].code != sectionCode:
                expected = definitions[next_index].code if next_index < len(definitions) else None
                raise ReportingError(
                    "report_section_order_invalid",
                    f"当前只接受章节 {expected or '无'}。",
                )
            if evidencePaths is not None:
                evidence_state[sectionCode] = evidence_files
                draft_state["sectionEvidence"] = evidence_state
            stored_sections.append(serialized)
            draft_state["draftId"] = _stable_digest(stored_sections)
            draft_state["status"] = (
                "sections_completed" if len(stored_sections) == len(definitions) else "collecting"
            )
            next_index = len(stored_sections)
            return self._with_chart_reference_feedback(
                {
                    "ok": True,
                    "status": "accepted",
                    "sectionCode": sectionCode,
                    "acceptedSectionCount": next_index,
                    "sectionCount": len(definitions),
                    "nextSectionCode": (
                        definitions[next_index].code if next_index < len(definitions) else None
                    ),
                    "evidenceFiles": evidence_files,
                },
                stored_sections=stored_sections,
                registry=registry,
                section_count=len(definitions),
            )
        except ValidationError as error:
            issues = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )[:8]
            )
            raise RetryAgentRun(
                "当前章节参数不符合基础 schema。仅修正本章后重试 render_report_section。"
                + (f" 错误：{issues}" if issues else "")
            ) from error
        except ReportingError as error:
            if error.code in {
                "report_draft_not_started",
                "report_draft_already_finalized",
                "report_section_order_invalid",
                "report_section_citation_unknown",
                "report_section_chart_unknown",
                "report_section_evidence_invalid",
            }:
                raise RetryAgentRun(
                    f"{error.code}: {error.message} 按服务端返回的章节顺序和注册 ID 调整后重试。"
                ) from error
            return self._failure(error)
        except WorkspaceError as error:
            return self._failure(error)

    async def finalize_report_draft(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        state = self._session_state(run_context)
        try:
            scope = await self.kernel.scope(run_context)
            self._require_phase_tool(
                scope,
                allowed=frozenset(),
                tool_name="finalize_report_draft",
            )
            _title, _path, definitions, _citations, _require_table = await self._render_contract(
                scope
            )
            draft_state = self._attempt_state(
                state, REPORT_DRAFT_STATE_KEY, int(getattr(scope, "attempt_no", 0))
            )
            stored_sections = draft_state.get("sections")
            if draft_state.get("started") is not True or not isinstance(stored_sections, list):
                raise ReportingError("report_draft_not_started", "必须先调用 begin_report_draft。")
            if draft_state.get("submitted") is not True:
                received_codes = [
                    item.get("sectionCode") for item in stored_sections if isinstance(item, dict)
                ]
                expected_codes = [item.code for item in definitions]
                if received_codes != expected_codes:
                    raise ReportingError(
                        "report_draft_sections_incomplete",
                        "全部冻结章节提交完成后才能最终拼装。",
                    )
                (
                    _parsed,
                    _markdown_path,
                    _sections,
                    _citation_ids,
                    draft_state,
                ) = await self._validate_and_store_draft(
                    scope=scope,
                    state=state,
                    draft={"sections": stored_sections},
                )
            rendered = await self._resume_saved_draft(
                scope=scope,
                state=state,
                draft_state=draft_state,
                run_context=run_context,
            )
            if rendered.get("ok") is not True:
                return rendered
            trusted_paths = rendered.get("artifactPaths")
            if not isinstance(trusted_paths, list) or any(
                not isinstance(path, str) or not path for path in trusted_paths
            ):
                raise ReportingError(
                    "report_draft_state_missing",
                    "最终拼装没有生成可信产物路径。",
                )
            plan = validated_agent_plan(state.get(AGENT_PLAN_STATE_KEY)) if state else None
            if plan is not None and state is not None:
                state[AGENT_PLAN_STATE_KEY] = {
                    "plan": [
                        {"step": item["step"], "status": "completed"} for item in plan["plan"]
                    ],
                    "explanation": plan["explanation"],
                }
            title = draft_state.get("title")
            rendered["nextToolCall"] = {
                "name": "finish_task",
                "arguments": {
                    "summary": (
                        f"报告《{title}》已完成逐章拼装。"
                        if isinstance(title, str) and title
                        else "结构化报告已完成逐章拼装。"
                    ),
                    "artifact_paths": list(trusted_paths),
                },
            }
            return rendered
        except (ReportingError, ValidationError, WorkspaceError) as error:
            return self._failure(error)


def build_report_worker_tools(
    workspace_service: WorkspaceService,
    task_repository: Any,
    validator_registry: Any = None,
    *,
    run_context: RunContext | None = None,
    agent: Any | None = None,
    vision_reviewer: ReportVisionReviewer | None = None,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """Report Worker 只执行 Coding 分析，不持有数据库或 SQL 工具。"""
    toolkit = ReportWorkspaceTaskToolkit(
        workspace_service,
        task_repository,
        validator_registry=validator_registry,
        vision_reviewer=vision_reviewer,
    )
    for name in ("begin_report_draft", "discard_report_charts", "finalize_report_draft"):
        toolkit.functions.pop(name, None)
        toolkit.async_functions.pop(name, None)
    if vision_reviewer is None:
        toolkit.functions.pop("view_image", None)
        toolkit.async_functions.pop("view_image", None)
    # Agno 2.8.2 会跨内部 run 复用同名动态 Toolkit。若按首次 run_context 的 phase
    # 删除函数，后续 analysis/section run 会继承残缺工具集，无法提交合法阶段产物。
    # Toolkit 因此必须保持 phase 无关的能力全集；模型请求仍逐次投影允许工具，执行时
    # _invoke 还会依据受信 phase 状态复核，不能通过直接调用绕过阶段边界。
    return [toolkit]
