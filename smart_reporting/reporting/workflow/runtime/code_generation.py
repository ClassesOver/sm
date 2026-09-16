"""Reporting Coding Agent V1 的交互式运行器。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from agno.agent import Agent
from agno.exceptions import ModelRateLimitError
from agno.run import RunContext
from agno.tools.function import Function
from loguru import logger

from ...code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskContext,
    ReportingCodingTaskRegistry,
)
from ...code_agent.lsp_process import ReportingLspProcessManager
from ...code_agent.toolkit import ReportingCodeModeToolkit
from ...code_mode import ReportingCodeModeRuntime
from ...host_workspace import HostReportingWorkspace
from ...knowledge import ReportingKnowledgeIndex
from ...model_policy import ThinkingFailureKind
from ...models import ReportingError
from ...phase import bounded_python_script_diagnostic
from ...vision import ReportVisionReviewer
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity

MAX_DIAGNOSTIC_MESSAGE_LENGTH = 512
MAX_DIAGNOSTIC_OUTPUT_LENGTH = 2000
MAX_DIAGNOSTIC_PATH_LENGTH = 1024
MAX_DIAGNOSTIC_UNSIGNED_PATHS = 20
MAX_DIAGNOSTIC_POSITION = 1_000_000_000
ANALYSIS_TOOL_CALL_LIMIT = 20
VISUALIZATION_TOOL_CALL_BASE = 29
MAX_TOOL_CALL_LIMIT = 140


def _bounded_unsigned_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str) and 0 < len(item) <= MAX_DIAGNOSTIC_PATH_LENGTH
    ][:MAX_DIAGNOSTIC_UNSIGNED_PATHS]


def _bounded_forbidden_path_operations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str)})[:MAX_DIAGNOSTIC_UNSIGNED_PATHS]


def _code_failure_kind(diagnostic: Mapping[str, Any] | None) -> ThinkingFailureKind | None:
    code = diagnostic.get("code") if isinstance(diagnostic, Mapping) else None
    if code in {"report_python_source_shape_invalid", "report_python_source_path_invalid"}:
        return "python_compile_failure"
    if code in {
        "execution_output_error",
        "report_analysis_script_failed",
        "report_visualization_script_failed",
    }:
        return "python_execution_failure"
    if code == "report_visualization_review_failed":
        return "visual_review_failure"
    return None


@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity
    execution_receipt: ExecutionReceipt
    visual_inspection_receipts: tuple[ChartVisualInspectionReceipt, ...] = ()
    visual_repair_diagnostic: Mapping[str, Any] | None = None


class ReportingCodeGenerationRunner:
    """为单个 Coding task 创建 Agent 并签发一次交互式执行回执。"""

    def __init__(
        self,
        agent_factory: Callable[[tuple[Function, ...]], Agent],
        code_mode_runtime: ReportingCodeModeRuntime,
        lsp_manager: ReportingLspProcessManager,
        registry: ReportingCodingTaskRegistry | None = None,
        knowledge_index: ReportingKnowledgeIndex | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
    ) -> None:
        self.agent_factory = agent_factory
        self.code_mode_runtime = code_mode_runtime
        self.registry = registry or ReportingCodingTaskRegistry()
        self.knowledge_index = knowledge_index
        self.lsp_manager = lsp_manager
        self.vision_reviewer = vision_reviewer

    async def run(
        self,
        task_context: ReportingCodingTaskContext,
        workspace: HostReportingWorkspace,
        task_facts: Mapping[str, Any],
        *,
        run_context: RunContext,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> CodeGenerationResult:
        if task_context.task_kind == "visualization" and self.vision_reviewer is None:
            raise ReportingError(
                "report_code_visual_reviewer_missing",
                "章节图表 Coding Agent 未配置独立视觉审查模型。",
            )
        requested_tool_call_limit = (
            VISUALIZATION_TOOL_CALL_BASE + len(task_context.declared_output_paths)
            if task_context.task_kind == "visualization"
            else ANALYSIS_TOOL_CALL_LIMIT
        )
        if requested_tool_call_limit > MAX_TOOL_CALL_LIMIT:
            raise ReportingError(
                "report_code_tool_call_limit_exceeded",
                "章节图表数量超过 Coding Agent 工具调用硬上限。",
                details={
                    "declaredOutputCount": len(task_context.declared_output_paths),
                    "requestedToolCallLimit": requested_tool_call_limit,
                    "maxToolCallLimit": MAX_TOOL_CALL_LIMIT,
                },
            )
        async with self.registry.bind(task_context, workspace) as binding:
            toolkit = ReportingCodeModeToolkit(
                binding,
                self.code_mode_runtime,
                knowledge_index=self.knowledge_index,
                lsp_manager=self.lsp_manager,
                vision_reviewer=self.vision_reviewer,
            )
            task_payload = asdict(task_context)
            task_payload["workspace_root"] = str(task_context.workspace_root)
            payload = {
                "task": task_payload,
                "facts": dict(task_facts),
                "diagnostic": self._short_diagnostic(diagnostic) if diagnostic else None,
            }
            started_at = perf_counter()
            try:
                agent = self.agent_factory(toolkit.tool_functions)
                agent.tool_call_limit = min(MAX_TOOL_CALL_LIMIT, requested_tool_call_limit)
                await agent.arun(self._prompt(payload), run_context=run_context)
                receipt = toolkit.submitted_receipt
                if receipt is None:
                    raise ReportingError(
                        "report_code_generation_no_submission",
                        "Coding Agent 未签发成功执行的 Python 脚本。",
                    )
            except ReportingError:
                raise
            except Exception as error:
                raise self._agent_failure(error) from error
            finally:
                await self.code_mode_runtime.shutdown(task_context.code_mode_session_id)
            await toolkit.require_current_receipt(receipt)
            visual_receipts = tuple(
                binding.visual_inspection_receipts[path]
                for path in sorted(binding.visual_inspection_receipts)
            )
            logger.info(
                "report_code_generation_completed task_id={} path={} duration_ms={}",
                task_context.task_id,
                receipt.source_file.path,
                max(0, round((perf_counter() - started_at) * 1000)),
            )
            return CodeGenerationResult(
                script_file=receipt.source_file,
                execution_receipt=receipt,
                visual_inspection_receipts=visual_receipts,
                visual_repair_diagnostic=(
                    binding.visual_repair_diagnostic
                    if task_context.task_kind == "visualization"
                    else None
                ),
            )

    @staticmethod
    def _prompt(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _agent_failure(error: Exception) -> ReportingError:
        if isinstance(error, ModelRateLimitError):
            return ReportingError(
                "report_code_generation_rate_limited",
                "Coding Agent 模型调用受限，请稍后重试。",
                details={"statusCode": error.status_code},
            )
        return ReportingError("report_code_generation_agent_failed", "Coding Agent 调用失败。")

    @classmethod
    def _short_diagnostic(cls, diagnostic: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        code = diagnostic.get("code")
        if isinstance(code, str) and code:
            result["code"] = code[:128]
        message = diagnostic.get("message")
        if isinstance(message, str) and message:
            result["message"] = message[:MAX_DIAGNOSTIC_MESSAGE_LENGTH]
        details = diagnostic.get("details")
        if not isinstance(details, Mapping):
            return result
        safe: dict[str, Any] = {}
        path = details.get("path")
        if isinstance(path, str) and 0 < len(path) <= MAX_DIAGNOSTIC_PATH_LENGTH:
            safe["path"] = path
        unsigned = _bounded_unsigned_paths(details.get("unsignedPaths"))
        if unsigned:
            safe["unsignedPaths"] = unsigned
        forbidden = _bounded_forbidden_path_operations(details.get("forbiddenPathOperations"))
        if forbidden:
            safe["forbiddenPathOperations"] = forbidden
        for field in ("line", "offset", "size", "lineCount", "maxLineLength", "exitCode"):
            value = details.get(field)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and abs(value) <= MAX_DIAGNOSTIC_POSITION
            ):
                safe[field] = value
        output = details.get("output")
        if isinstance(output, str) and output:
            safe["output"], truncated = bounded_python_script_diagnostic(
                output, MAX_DIAGNOSTIC_OUTPUT_LENGTH
            )
            safe["outputTruncated"] = truncated
        if safe:
            result["details"] = safe
        return result


__all__ = ["CodeGenerationResult", "ReportingCodeGenerationRunner"]
