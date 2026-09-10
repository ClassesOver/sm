"""受控 Reporting Coding Agent 的脚本签发与两阶段修复协议。"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import perf_counter
from typing import Any, NoReturn

from agno.agent import Agent
from agno.run import RunContext
from agno.tools.function import Function
from loguru import logger

from ...model_policy import current_reporting_thinking_decision
from ...models import ReportingError
from ..checkpoint import FileIdentity

ToolCallable = Callable[..., Awaitable[Mapping[str, Any]] | Mapping[str, Any]]
MAX_CODE_READ_BYTES = 128 * 1024
MAX_DIAGNOSTIC_MESSAGE_LENGTH = 512
MAX_DIAGNOSTIC_OUTPUT_LENGTH = 2000
MAX_DIAGNOSTIC_PATH_LENGTH = 1024
MAX_DIAGNOSTIC_POSITION = 1_000_000_000
MAX_PHYSICAL_LINE_BYTES = 8 * 1024
MAX_TASK_MISSING_FACTS = 20
MAX_TASK_MISSING_FACT_LENGTH = 512
MAX_TASK_MISSING_CHARTS = 100
MAX_TASK_CHART_ID_LENGTH = 128
MAX_TASK_CHART_SOURCE_PATH_LENGTH = 1024
MAX_TASK_CHART_TITLE_LENGTH = 200
MAX_TASK_INSPECTIONS = 100
MAX_TASK_INSPECTION_ISSUES = 20
MAX_TASK_INSPECTION_TEXTS = 20
MAX_TASK_INSPECTION_TEXT_LENGTH = 500
MAX_TASK_INSPECTION_SUMMARY_LENGTH = 2000
_STABLE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity


def _tool_parameters(name: str) -> dict[str, Any]:
    if name == "read_file":
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }
    if name == "submit_python_source":
        return {
            "type": "object",
            "properties": {"source": {"type": "string", "minLength": 1}},
            "required": ["source"],
            "additionalProperties": False,
        }
    raise ValueError(f"未知 Coding 工具：{name}")


def _python_source_shape_details(path: str, source: Any) -> dict[str, Any]:
    if isinstance(source, str):
        try:
            raw_source = source.encode("utf-8")
        except UnicodeEncodeError:
            raw_source = b""
        lines = source.splitlines()
    else:
        raw_source = b""
        lines = []
    return {
        "path": path,
        "size": len(raw_source),
        "lineCount": len(lines),
        "maxLineLength": max(
            (len(line.encode("utf-8", errors="replace")) for line in lines),
            default=0,
        ),
    }


def _reject_python_source(path: str, source: Any) -> NoReturn:
    raise ReportingError(
        "report_python_source_shape_invalid",
        "签发 Python 源码形状无效，已拒绝写入。",
        details=_python_source_shape_details(path, source),
    )


def _reject_python_syntax(path: str, source: str, error: SyntaxError) -> NoReturn:
    details = _python_source_shape_details(path, source)
    for field, value in (("line", error.lineno), ("offset", error.offset)):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            details[field] = value
    syntax_message = str(error.msg or "invalid syntax")[:200].rstrip(".。")
    raise ReportingError(
        "report_python_source_shape_invalid",
        f"签发 Python 源码存在 Python 3.12 语法错误，已拒绝写入：{syntax_message}。",
        details=details,
    ) from None


def _validate_python_source_shape(path: str, source: Any, max_source_bytes: int) -> str:
    if not isinstance(source, str):
        _reject_python_source(path, source)
    if source and "\r" not in source and not source.endswith("\n"):
        source += "\n"
    try:
        raw_source = source.encode("utf-8")
    except UnicodeEncodeError:
        _reject_python_source(path, source)
    lines = source.split("\n")
    if (
        len(raw_source) > max_source_bytes
        or "\r" in source
        or not source.endswith("\n")
        or len(source.splitlines()) < 2
        or any(len(line.encode("utf-8")) > MAX_PHYSICAL_LINE_BYTES for line in lines)
    ):
        _reject_python_source(path, source)
    return source


def _compile_python_source(path: str, source: str) -> None:
    try:
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
    except SyntaxError as error:
        _reject_python_syntax(path, source, error)
    except (TypeError, ValueError):
        _reject_python_source(path, source)


def _diff_content_lines(content: str, prefix: str) -> list[str]:
    result: list[str] = []
    for line in content.splitlines(keepends=True):
        result.append(f"{prefix}{line}" if line.endswith("\n") else f"{prefix}{line}\n")
        if not line.endswith("\n"):
            result.append("\\ No newline at end of file\n")
    return result


def _python_source_patch(
    path: str,
    source: str,
    *,
    operation: str,
    previous_source: str | None,
) -> str:
    source_lines = source.splitlines(keepends=True)
    if operation == "create":
        return "".join(
            [
                "--- /dev/null\n",
                f"+++ b/{path}\n",
                f"@@ -0,0 +1,{len(source_lines)} @@\n",
                *_diff_content_lines(source, "+"),
            ]
        )
    if not isinstance(previous_source, str):
        raise ReportingError(
            "report_code_generation_read_invalid",
            "脚本更新缺少受信原始源码。",
            details={"path": path},
        )
    previous_lines = previous_source.splitlines(keepends=True)
    return "".join(
        [
            f"--- a/{path}\n",
            f"+++ b/{path}\n",
            f"@@ -1,{len(previous_lines)} +1,{len(source_lines)} @@\n",
            *_diff_content_lines(previous_source, "-"),
            *_diff_content_lines(source, "+"),
        ]
    )


async def _invoke(
    callback: ToolCallable, arguments: dict[str, Any], run_context: RunContext | None
) -> Mapping[str, Any]:
    if run_context is not None:
        try:
            signature = inspect.signature(callback)
            if "run_context" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                arguments = {**arguments, "run_context": run_context}
        except (TypeError, ValueError):
            pass
    result = callback(**arguments)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise ReportingError("report_code_generation_tool_invalid", "Coding 工具回执不是对象。")
    return result


class ReportingCodeGenerationRunner:
    """每次阶段调用都创建独立上下文，并以唯一源码提交和 patch 回执收口。"""

    def __init__(
        self,
        *,
        agent: Agent | Callable[[], Agent] | None = None,
        agent_factory: Callable[[], Agent] | None = None,
    ):
        agent_source = agent_factory if agent_factory is not None else agent
        if agent_source is None:
            raise TypeError("ReportingCodeGenerationRunner requires agent or agent_factory")
        self._agent_source: Agent | Callable[[], Agent] | None = agent_source

    def _fresh_agent(self) -> Agent:
        agent_source = self._agent_source
        if agent_source is None:
            raise RuntimeError("Coding Agent source is not configured")
        agent = (
            agent_source()
            if callable(agent_source) and not isinstance(agent_source, Agent)
            else copy.copy(agent_source)
        )
        decision = current_reporting_thinking_decision()
        if decision is not None and not decision.enabled:
            agent.reasoning_model = None
            agent.reasoning_agent = None
        return agent

    @staticmethod
    def _configure(agent: Agent, function: Function, tool_choice: str) -> None:
        agent.tools = [function]
        agent.tool_choice = {"type": "function", "function": {"name": tool_choice}}
        agent.tool_call_limit = 1
        agent.add_history_to_context = False
        agent.num_history_runs = 0
        agent.store_history_messages = False
        agent.session_state = {}
        agent.session_id = None

    @staticmethod
    def _prompt(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _validate_script_path(path: str) -> None:
        candidate = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.suffix != ".py"
        ):
            raise ReportingError(
                "report_code_generation_path_invalid", "脚本路径不是安全的工作区相对 Python 文件。"
            )

    @staticmethod
    def _error(code: str, message: str, script_path: str) -> ReportingError:
        return ReportingError(code, message, details={"path": script_path})

    @staticmethod
    def _stable_code(value: Any, fallback: str) -> str:
        return value if isinstance(value, str) and _STABLE_CODE_RE.fullmatch(value) else fallback

    @classmethod
    def _short_diagnostic(cls, diagnostic: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        code = diagnostic.get("code")
        if cls._stable_code(code, ""):
            result["code"] = code
        message = diagnostic.get("message")
        if isinstance(message, str) and message:
            result["message"] = message[:MAX_DIAGNOSTIC_MESSAGE_LENGTH]
        details = diagnostic.get("details")
        if isinstance(details, Mapping):
            safe_details: dict[str, Any] = {}
            path = details.get("path")
            if isinstance(path, str) and 0 < len(path) <= MAX_DIAGNOSTIC_PATH_LENGTH:
                safe_details["path"] = path
            for field in ("line", "offset", "size", "lineCount", "maxLineLength"):
                value = details.get(field)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 <= value <= MAX_DIAGNOSTIC_POSITION
                ):
                    safe_details[field] = value
            exit_code = details.get("exitCode")
            if (
                isinstance(exit_code, int)
                and not isinstance(exit_code, bool)
                and -MAX_DIAGNOSTIC_POSITION <= exit_code <= MAX_DIAGNOSTIC_POSITION
            ):
                safe_details["exitCode"] = exit_code
            output = details.get("output")
            if isinstance(output, str) and output:
                safe_details["output"] = output[:MAX_DIAGNOSTIC_OUTPUT_LENGTH]
            output_truncated = details.get("outputTruncated")
            if isinstance(output_truncated, bool):
                safe_details["outputTruncated"] = output_truncated
            tool_code = details.get("toolCode")
            if cls._stable_code(tool_code, ""):
                safe_details["toolCode"] = tool_code
            tool_message = details.get("toolMessage")
            if isinstance(tool_message, str) and tool_message:
                safe_details["toolMessage"] = tool_message[:MAX_DIAGNOSTIC_MESSAGE_LENGTH]
            if safe_details:
                result["details"] = safe_details
        return result

    @classmethod
    def _repair_task_facts(cls, task_facts: Any, script_path: str) -> dict[str, Any]:
        if task_facts is None:
            return {}
        if not isinstance(task_facts, Mapping):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "修复任务事实必须是对象。",
                script_path,
            )
        missing_facts = task_facts.get("missingFacts")
        if missing_facts is not None and (
            not isinstance(missing_facts, list)
            or any(not isinstance(item, str) for item in missing_facts)
        ):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "修复任务事实必须是受限的 missingFacts 字符串数组。",
                script_path,
            )
        result: dict[str, Any] = {}
        if missing_facts is not None:
            result["missingFacts"] = [
                item[:MAX_TASK_MISSING_FACT_LENGTH]
                for item in missing_facts[:MAX_TASK_MISSING_FACTS]
            ]
        missing_charts = task_facts.get("missingCharts")
        if missing_charts is not None:
            result["missingCharts"] = cls._repair_missing_charts(missing_charts, script_path)
        inspections = task_facts.get("inspections")
        if inspections is not None:
            result["inspections"] = cls._repair_inspections(inspections, script_path)
        return result

    @classmethod
    def _repair_missing_charts(cls, missing_charts: Any, script_path: str) -> list[dict[str, str]]:
        if not isinstance(missing_charts, list):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "修复任务事实必须是受限的 missingCharts 数组。",
                script_path,
            )
        result: list[dict[str, str]] = []
        for chart in missing_charts[:MAX_TASK_MISSING_CHARTS]:
            if not isinstance(chart, Mapping):
                raise cls._error(
                    "report_code_generation_task_facts_invalid",
                    "缺失图表必须是对象。",
                    script_path,
                )
            chart_id = chart.get("chartId")
            source_path = chart.get("sourcePath")
            title = chart.get("title")
            if (
                not isinstance(chart_id, str)
                or not isinstance(source_path, str)
                or not isinstance(title, str)
            ):
                raise cls._error(
                    "report_code_generation_task_facts_invalid",
                    "缺失图表身份字段必须是字符串。",
                    script_path,
                )
            result.append(
                {
                    "chartId": chart_id[:MAX_TASK_CHART_ID_LENGTH],
                    "sourcePath": source_path[:MAX_TASK_CHART_SOURCE_PATH_LENGTH],
                    "title": title[:MAX_TASK_CHART_TITLE_LENGTH],
                }
            )
        return result

    @classmethod
    def _repair_inspections(cls, inspections: Any, script_path: str) -> list[dict[str, Any]]:
        if not isinstance(inspections, list):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "修复任务事实必须是受限的 inspections 数组。",
                script_path,
            )
        return [
            cls._repair_inspection(inspection, script_path)
            for inspection in inspections[:MAX_TASK_INSPECTIONS]
        ]

    @classmethod
    def _repair_inspection(cls, inspection: Any, script_path: str) -> dict[str, Any]:
        if not isinstance(inspection, Mapping):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "视觉检查记录必须是对象。",
                script_path,
            )
        source_path = inspection.get("sourcePath")
        status = inspection.get("visualReviewStatus")
        requires_revision = inspection.get("requiresRevision")
        if (
            not isinstance(source_path, str)
            or not isinstance(status, str)
            or _STABLE_CODE_RE.fullmatch(status) is None
            or not isinstance(requires_revision, bool)
        ):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "视觉检查核心字段无效。",
                script_path,
            )
        result: dict[str, Any] = {
            "sourcePath": source_path[:MAX_TASK_CHART_SOURCE_PATH_LENGTH],
            "visualReviewStatus": status,
            "requiresRevision": requires_revision,
        }
        issues = inspection.get("issues", [])
        if not isinstance(issues, list):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "视觉检查 issues 必须是数组。",
                script_path,
            )
        result["issues"] = [
            cls._repair_inspection_issue(issue, script_path)
            for issue in issues[:MAX_TASK_INSPECTION_ISSUES]
        ]
        for field in ("warnings", "suggestions"):
            values = inspection.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise cls._error(
                    "report_code_generation_task_facts_invalid",
                    f"视觉检查 {field} 必须是字符串数组。",
                    script_path,
                )
            result[field] = [
                value[:MAX_TASK_INSPECTION_TEXT_LENGTH]
                for value in values[:MAX_TASK_INSPECTION_TEXTS]
            ]
        summary = inspection.get("summary")
        if summary is not None:
            if not isinstance(summary, str):
                raise cls._error(
                    "report_code_generation_task_facts_invalid",
                    "视觉检查 summary 必须是字符串。",
                    script_path,
                )
            result["summary"] = summary[:MAX_TASK_INSPECTION_SUMMARY_LENGTH]
        return result

    @classmethod
    def _repair_inspection_issue(cls, issue: Any, script_path: str) -> dict[str, str]:
        if not isinstance(issue, Mapping):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "视觉检查 issue 必须是对象。",
                script_path,
            )
        category = issue.get("category")
        severity = issue.get("severity")
        description = issue.get("description")
        if (
            not isinstance(category, str)
            or _STABLE_CODE_RE.fullmatch(category) is None
            or not isinstance(severity, str)
            or _STABLE_CODE_RE.fullmatch(severity) is None
            or not isinstance(description, str)
        ):
            raise cls._error(
                "report_code_generation_task_facts_invalid",
                "视觉检查 issue 字段无效。",
                script_path,
            )
        return {
            "category": category,
            "severity": severity,
            "description": description[:MAX_TASK_INSPECTION_TEXT_LENGTH],
        }

    @classmethod
    def _trusted_read_receipt(
        cls, receipt: Mapping[str, Any], script_file: FileIdentity
    ) -> dict[str, Any]:
        content = receipt.get("content")
        if receipt.get("ok", True) is not True or not isinstance(content, str):
            raise cls._error(
                "report_code_generation_read_invalid", "脚本读取回执无效。", script_file.path
            )
        if receipt.get("path") != script_file.path:
            raise cls._error(
                "report_code_generation_read_invalid", "脚本读取回执路径不匹配。", script_file.path
            )
        positions: dict[str, int] = {}
        for field in ("offset", "nextOffset", "totalBytes"):
            value = receipt.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise cls._error(
                    "report_code_generation_read_invalid",
                    "脚本读取回执分页字段无效。",
                    script_file.path,
                )
            positions[field] = value
        if positions["offset"] != 0 or positions["nextOffset"] != positions["totalBytes"]:
            raise cls._error(
                "report_code_generation_read_incomplete",
                "脚本读取回执分页不完整。",
                script_file.path,
            )
        content_bytes = content.encode("utf-8")
        if (
            positions["totalBytes"] != len(content_bytes)
            or positions["totalBytes"] != script_file.size
        ):
            raise cls._error(
                "report_code_generation_read_invalid",
                "脚本读取回执字节数不匹配。",
                script_file.path,
            )
        if len(content_bytes) > MAX_CODE_READ_BYTES:
            raise cls._error(
                "report_code_generation_read_too_large",
                "脚本读取回执超过 Coding Agent 上下文上限。",
                script_file.path,
            )
        content_sha256 = hashlib.sha256(content_bytes).hexdigest()
        if receipt.get("sha256") != script_file.sha256 or content_sha256 != script_file.sha256:
            raise cls._error(
                "report_code_generation_read_invalid",
                "脚本读取回执身份不匹配。",
                script_file.path,
            )
        return {
            "path": script_file.path,
            "sha256": script_file.sha256,
            "content": content,
            "totalBytes": positions["totalBytes"],
        }

    async def generate(
        self,
        script_path: str,
        task_facts: Mapping[str, Any],
        apply_analysis_patch: ToolCallable,
        run_context: RunContext | None = None,
        *,
        diagnostic: Mapping[str, Any] | None = None,
        max_source_bytes: int = MAX_CODE_READ_BYTES,
        _operation: str = "create",
        _previous_source: str | None = None,
        _log_base_info: bool = True,
    ) -> CodeGenerationResult:
        """运行一次写阶段；模型只提交源码，diff 由服务端构造。"""
        self._validate_script_path(script_path)
        if (
            isinstance(max_source_bytes, bool)
            or not isinstance(max_source_bytes, int)
            or not 1 <= max_source_bytes <= MAX_CODE_READ_BYTES
        ):
            raise self._error(
                "report_code_generation_limit_invalid", "脚本源码上限无效。", script_path
            )
        if _operation not in {"create", "update"}:
            raise self._error(
                "report_code_generation_operation_invalid", "脚本签发操作无效。", script_path
            )
        result: CodeGenerationResult | None = None
        patch_error: ReportingError | None = None
        generation_started_at = perf_counter()
        model_started_at: float | None = None

        def log_step(step: int, step_name: str, started_at: float) -> None:
            completed_at = perf_counter()
            logger.info(
                "report_code_generation_step_completed step={} step_name={} duration_ms={} "
                "total_duration_ms={} operation={} path={}",
                step,
                step_name,
                max(0, round((completed_at - started_at) * 1000)),
                max(0, round((completed_at - generation_started_at) * 1000)),
                _operation,
                script_path,
            )

        async def capture_source(**kwargs: Any) -> Mapping[str, Any]:
            nonlocal patch_error, result
            if model_started_at is not None:
                log_step(1, "model_generate_source", model_started_at)
            try:
                step_started_at = perf_counter()
                source = _validate_python_source_shape(
                    script_path,
                    kwargs.get("source"),
                    max_source_bytes,
                )
                log_step(2, "source_shape_validate", step_started_at)
                step_started_at = perf_counter()
                _compile_python_source(script_path, source)
                log_step(3, "python_compile", step_started_at)
                step_started_at = perf_counter()
                patch = _python_source_patch(
                    script_path,
                    source,
                    operation=_operation,
                    previous_source=_previous_source,
                )
                log_step(4, "patch_build", step_started_at)
            except ReportingError as error:
                patch_error = error
                raise
            try:
                step_started_at = perf_counter()
                receipt = await _invoke(apply_analysis_patch, {"patch": patch}, run_context)
                log_step(5, "patch_apply", step_started_at)
            except ReportingError as error:
                bounded = self._short_diagnostic(
                    {"code": error.code, "message": error.message, "details": error.details}
                )
                patch_error = ReportingError(
                    self._stable_code(error.code, "report_code_generation_patch_failed"),
                    bounded.get("message", "脚本 patch 未被接受。"),
                    details=bounded.get("details", {"path": script_path}),
                )
                raise patch_error from error
            except Exception as error:
                patch_error = self._error(
                    "report_code_generation_patch_failed", "脚本 patch 未被接受。", script_path
                )
                raise patch_error from error
            if receipt.get("ok") is not True:
                bounded = self._short_diagnostic(receipt)
                patch_error = ReportingError(
                    self._stable_code(receipt.get("code"), "report_code_generation_patch_failed"),
                    bounded.get("message", "脚本 patch 未被接受。"),
                    details=bounded.get("details", {"path": script_path}),
                )
                raise patch_error
            step_started_at = perf_counter()
            artifacts = receipt.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1:
                raise self._error(
                    "report_code_generation_artifact_invalid",
                    "脚本 patch 必须返回唯一文件身份。",
                    script_path,
                )
            try:
                identity = FileIdentity.model_validate(artifacts[0])
            except Exception as error:
                raise self._error(
                    "report_code_generation_artifact_invalid",
                    "脚本 patch 文件身份无效。",
                    script_path,
                ) from error
            if identity.path != script_path:
                raise self._error(
                    "report_code_generation_path_mismatch",
                    "脚本写入回执路径与签发路径不一致。",
                    script_path,
                )
            result = CodeGenerationResult(identity)
            log_step(6, "receipt_validate", step_started_at)
            return receipt

        calls = 0

        async def wrapped_source(**kwargs: Any) -> Mapping[str, Any]:
            nonlocal calls, patch_error
            calls += 1
            if calls > 1:
                patch_error = self._error(
                    "report_code_generation_multiple_sources",
                    "单轮 Coding Agent 只能提交一次 Python 源码。",
                    script_path,
                )
                raise patch_error
            try:
                return await capture_source(**kwargs)
            except ReportingError as error:
                patch_error = patch_error or error
                raise

        agent = self._fresh_agent()
        self._configure(
            agent,
            Function(
                name="submit_python_source",
                description="提交签发路径的完整 Python 源码；不要提交 diff 或 Markdown 围栏。",
                parameters=_tool_parameters("submit_python_source"),
                strict=True,
                entrypoint=wrapped_source,
                stop_after_tool_call=True,
            ),
            "submit_python_source",
        )
        try:
            prompt = {
                "scriptPath": script_path,
                "facts": dict(task_facts),
                "sourceProtocol": {
                    "path": script_path,
                    "maxSourceBytes": max_source_bytes,
                    "maxPhysicalLineBytes": MAX_PHYSICAL_LINE_BYTES,
                    "minPhysicalLines": 2,
                    "lineEnding": "LF",
                    "trailingNewline": True,
                    "pythonVersion": "3.12",
                    "compilationRequired": True,
                    "syntaxRequirements": [
                        "提交前确保完整源码可通过 ast.parse 和 compile",
                        "使用普通赋值和显式 if；不得使用 := 赋值表达式或 if False/if True 死代码分支",
                    ],
                },
            }
            if diagnostic is not None:
                prompt["diagnostic"] = self._short_diagnostic(diagnostic)
            model_started_at = perf_counter()
            await agent.arun(self._prompt(prompt), run_context=run_context)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "report_code_generation_agent_failed", "Coding Agent 调用失败。"
            ) from error
        if result is None and patch_error is not None:
            raise patch_error
        if result is None:
            raise ReportingError(
                "report_code_generation_no_source",
                "Coding Agent 未提交完整 Python 源码。",
            )
        if _log_base_info:
            logger.info(
                "report_code_generation_base_info script={}",
                json.dumps(
                    {
                        "operation": _operation,
                        "path": result.script_file.path,
                        "size": result.script_file.size,
                        "sha256": result.script_file.sha256,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        return result

    async def repair(
        self,
        script_file: FileIdentity,
        diagnostic: Mapping[str, Any],
        read_file: ToolCallable,
        apply_analysis_patch: ToolCallable,
        run_context: RunContext | None = None,
        *,
        task_facts: Mapping[str, Any] | None = None,
        max_source_bytes: int = MAX_CODE_READ_BYTES,
    ) -> CodeGenerationResult:
        """直接读取一次受信脚本回执，再用 fresh Agent 提交完整修复源码。"""
        self._validate_script_path(script_file.path)
        bounded_task_facts = self._repair_task_facts(task_facts, script_file.path)
        try:
            receipt = await _invoke(
                read_file,
                {"path": script_file.path, "max_bytes": max_source_bytes},
                run_context,
            )
        except ReportingError as error:
            raise self._error(
                self._stable_code(error.code, "report_code_generation_read_failed"),
                "脚本读取失败。",
                script_file.path,
            ) from error
        except Exception as error:
            raise self._error(
                "report_code_generation_read_failed", "脚本读取失败。", script_file.path
            ) from error
        read_receipt = self._trusted_read_receipt(receipt, script_file)
        result = await self.generate(
            script_file.path,
            {
                "readReceipt": read_receipt,
                "diagnostic": self._short_diagnostic(diagnostic),
                "taskFacts": bounded_task_facts,
            },
            apply_analysis_patch,
            run_context,
            diagnostic=diagnostic,
            max_source_bytes=max_source_bytes,
            _operation="update",
            _previous_source=read_receipt["content"],
            _log_base_info=False,
        )
        logger.info(
            "report_code_repair_base_info script={}",
            json.dumps(
                {
                    "operation": "repair",
                    "path": result.script_file.path,
                    "size": result.script_file.size,
                    "sha256": result.script_file.sha256,
                    "diagnosticCode": self._stable_code(diagnostic.get("code"), "unknown"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return result
