"""交互式 Coding Agent 的 Workspace 与执行身份工具。"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NoReturn
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Function, Toolkit
from loguru import logger

from ...workspace import WorkspaceError, WorkspaceService
from ..code_mode import ReportingCodeModeRuntime, script_process_exit_code
from ..knowledge import KnowledgeIndexError, ReportingKnowledgeIndex
from ..models import ReportingError
from ..vision import ReportVisionReviewer
from ..workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from .lsp import ReportingWorkspaceLsp
from .lsp_process import ReportingLspProcessManager

MAX_PHYSICAL_LINE_BYTES = 8 * 1024
MAX_DIAGNOSTIC_BYTES = 8 * 1024
ANALYSIS_SNIPPET_LIMIT = 4
VISUALIZATION_SNIPPET_LIMIT = 8
# 数据属于正式 Workspace；源码中的大字面量通常意味着模型把查询结果直接
# 粘贴进脚本。阈值保持足够高，避免误伤普通 SQL、配置或少量示例数据。
MAX_INLINE_LITERAL_BYTES = 32 * 1024
MAX_INLINE_COLLECTION_ITEMS = 512
MAX_INLINE_COLLECTION_BYTES = 64 * 1024
_FORBIDDEN_PATH_CALLS = frozenset(
    {
        "os.chdir",
        "os.fchdir",
        "os.getcwd",
        "os.getcwdb",
        "os.path.abspath",
        "os.path.dirname",
        "os.path.join",
        "os.path.normpath",
        "os.path.realpath",
        "os.path.relpath",
        "pathlib.Path.cwd",
    }
)
_PATH_ARGUMENT_CALLS = frozenset({"open", "io.open", "os.makedirs", "os.mkdir", "pathlib.Path"})
_PATH_ARGUMENT_METHODS = frozenset(
    {
        "imread",
        "imsave",
        "read_csv",
        "read_excel",
        "read_feather",
        "read_json",
        "read_parquet",
        "read_pickle",
        "savefig",
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_pickle",
    }
)
_PATH_ARGUMENT_KEYWORDS = frozenset(
    {"file", "filename", "filepath_or_buffer", "fname", "path", "path_or_buf"}
)


def _reject_source(message: str, details: Mapping[str, Any] | None = None) -> NoReturn:
    raise ReportingError("report_code_source_invalid", message, details=details)


def validate_draft_source(context: ReportingCodingTaskContext, source: Any) -> bytes:
    if not isinstance(source, str) or not source:
        _reject_source("Python 源码形状无效。")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    if not source.endswith("\n"):
        source += "\n"
    try:
        raw = source.encode("utf-8")
    except UnicodeEncodeError:
        _reject_source("Python 源码必须是有效的 UTF-8 文本。")
    if len(raw) > context.max_source_bytes:
        _reject_source(
            "Python 源码体积过大。不得把数据内嵌到源码；请将数据保留在 Workspace，"
            "脚本仅按已授权路径读取并执行聚合。",
            {
                "reason": "source_too_large",
                "actualBytes": len(raw),
                "limitBytes": context.max_source_bytes,
            },
        )
    for line_number, line in enumerate(source.split("\n"), start=1):
        line_bytes = len(line.encode("utf-8"))
        if line_bytes > MAX_PHYSICAL_LINE_BYTES:
            _reject_source(
                "Python 源码包含超长物理行，疑似内嵌数据。不得把数据内嵌到源码；"
                "请将数据保留在 Workspace，脚本仅按已授权路径读取。",
                {
                    "reason": "physical_line_too_long",
                    "line": line_number,
                    "actualBytes": line_bytes,
                    "limitBytes": MAX_PHYSICAL_LINE_BYTES,
                },
            )
    return raw


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".", 1)[0]
                aliases[bound] = item.name if item.asname else bound
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _qualified_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value, aliases)
        return f"{owner}.{node.attr}" if owner else node.attr
    return None


def _literal_bindings(tree: ast.AST) -> dict[str, ast.AST]:
    values: dict[str, ast.AST] = {}
    ambiguous: set[str] = set()
    for node in ast.walk(tree):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, (ast.Assign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) == 1:
                target, value = targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            if target.id in values:
                ambiguous.add(target.id)
            else:
                values[target.id] = value
    for name in ambiguous:
        values.pop(name, None)
    return values


def _literal_string(
    node: ast.AST,
    bindings: Mapping[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _literal_string(bindings[node.id], bindings, seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left, bindings, seen)
        right = _literal_string(node.right, bindings, seen)
        return left + right if left is not None and right is not None else None
    return None


def _path_arguments(call: ast.Call, qualified_name: str) -> tuple[ast.AST, ...]:
    method_name = qualified_name.rsplit(".", 1)[-1]
    if qualified_name not in _PATH_ARGUMENT_CALLS and method_name not in _PATH_ARGUMENT_METHODS:
        return ()
    arguments = list(call.args[:1])
    arguments.extend(
        keyword.value for keyword in call.keywords if keyword.arg in _PATH_ARGUMENT_KEYWORDS
    )
    return tuple(arguments)


def _referenced_literal_paths(tree: ast.AST) -> set[str]:
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified_name = _qualified_name(node.func, aliases)
        if qualified_name is None:
            continue
        for argument in _path_arguments(node, qualified_name):
            literal = _literal_string(argument, bindings)
            if literal is not None:
                paths.add(literal)
    return paths


def _embedded_data_details(tree: ast.AST) -> dict[str, Any] | None:
    """识别疑似被模型直接嵌入源码的大型数据字面量。

    这里只拦截可静态确认的形状：超大字符串/字节串，或包含大量常量项的
    列表、元组、集合、字典。真实数据应写入 Workspace，由脚本按路径读取。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            size = len(node.value if isinstance(node.value, bytes) else node.value.encode("utf-8"))
            if size > MAX_INLINE_LITERAL_BYTES:
                return {
                    "kind": "large_literal",
                    "bytes": size,
                    "line": node.lineno,
                    "column": node.col_offset,
                }

    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            continue
        item_count = len(node.elts) if not isinstance(node, ast.Dict) else len(node.values)
        if item_count <= MAX_INLINE_COLLECTION_ITEMS:
            continue
        literal_bytes = 0
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, (str, bytes, int, float)):
                value = child.value
                literal_bytes += len(value if isinstance(value, bytes) else str(value).encode("utf-8"))
                if literal_bytes > MAX_INLINE_COLLECTION_BYTES:
                    return {
                        "kind": "large_collection",
                        "items": item_count,
                        "bytes": literal_bytes,
                        "line": node.lineno,
                        "column": node.col_offset,
                    }
    return None


def _reject_embedded_data(tree: ast.AST) -> None:
    embedded = _embedded_data_details(tree)
    if embedded is not None:
        raise ReportingError(
            "report_code_source_invalid",
            "源码疑似内嵌大数据；请将数据留在 Workspace，并在脚本中按授权路径读取。",
            details={"reason": "embedded_data", **embedded},
        )


def compile_script_source(path: str, source: str, authorized_paths: frozenset[str]) -> None:
    try:
        tree = ast.parse(source, filename=path)
        _reject_embedded_data(tree)
        aliases = _import_aliases(tree)
        forbidden = {
            qualified
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (qualified := _qualified_name(node.func, aliases)) in _FORBIDDEN_PATH_CALLS
        }
        if any(
            isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "__file__"
            for node in ast.walk(tree)
        ):
            forbidden.add("__file__")
        unsigned = _referenced_literal_paths(tree) - set(authorized_paths)
        if forbidden or unsigned:
            raise ReportingError(
                "report_python_source_path_invalid",
                "脚本使用了未授权路径或目录推导操作。",
                details={
                    "path": path,
                    "unsignedPaths": sorted(unsigned)[:20],
                    "forbiddenPathOperations": sorted(forbidden),
                },
            )
        compile(tree, path, "exec")
    except ReportingError:
        raise
    except (SyntaxError, TypeError, ValueError) as error:
        details: dict[str, Any] = {"path": path, "errorType": type(error).__name__}
        if isinstance(error, SyntaxError):
            details.update(
                {
                    "line": error.lineno,
                    "column": error.offset,
                    "endLine": error.end_lineno,
                    "endColumn": error.end_offset,
                    "sourceLine": (error.text or "").rstrip("\n"),
                    "reason": error.msg,
                }
            )
        else:
            details["reason"] = str(error)[:512]
        raise ReportingError(
            "report_code_source_invalid", "Python 源码无法编译。", details=details
        ) from error


def validate_script_source(context: ReportingCodingTaskContext, source: str) -> bytes:
    raw = validate_draft_source(context, source)
    authorized = frozenset((*context.authorized_read_paths, *context.authorized_write_paths))
    compile_script_source(context.script_path, source, authorized)
    return raw


def _cell_field(cell: Any, name: str, default: Any = None) -> Any:
    if isinstance(cell, Mapping):
        return cell.get(name, default)
    return getattr(cell, name, default)


def _failure(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = {"ok": False, "status": "rejected", "code": code, "message": message}
    if details:
        result["details"] = _safe_diagnostic_details(details)
    return result


def _safe_diagnostic_details(details: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "path", "line", "column", "endLine", "endColumn", "sourceLine", "reason",
        "errorType", "retryable", "unsignedPaths", "forbiddenPathOperations",
        "traceback", "result", "stderr", "stdout", "issueSummary",
        "used", "limit", "requiredNextTools", "kind", "bytes", "items",
        "actualBytes", "limitBytes", "missingPaths", "exitCode", "escalated",
    )
    output_fields = {"traceback", "result", "stderr", "stdout"}
    result: dict[str, Any] = {}

    def bounded_text(value: str, max_bytes: int, *, tail: bool = False) -> str:
        raw = value.encode("utf-8")
        if len(raw) <= max_bytes:
            return value
        selected = raw[-max_bytes:] if tail else raw[:max_bytes]
        return selected.decode("utf-8", errors="ignore")

    for key in allowed:
        value = details.get(key)
        if key in {
            "unsignedPaths", "forbiddenPathOperations", "requiredNextTools", "missingPaths",
        }:
            if isinstance(value, list):
                result[key] = [bounded_text(str(item), 256) for item in value[:20]]
        elif key in {"retryable", "escalated"}:
            if isinstance(value, bool):
                result[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
        elif isinstance(value, str) and key not in output_fields:
            result[key] = bounded_text(value, 2048)

    def encoded_size() -> int:
        return len(json.dumps(result, ensure_ascii=False).encode("utf-8"))

    # 极端元数据也必须满足硬上限；优先保留路径、位置和 retryable。
    for key in (
        "forbiddenPathOperations", "unsignedPaths", "sourceLine", "reason",
        "errorType", "endColumn", "endLine", "column", "line", "path",
    ):
        if encoded_size() <= MAX_DIAGNOSTIC_BYTES:
            break
        result.pop(key, None)

    def add_tail(key: str, value: str, max_bytes: int) -> None:
        result[key] = ""
        if encoded_size() > MAX_DIAGNOSTIC_BYTES:
            result.pop(key, None)
            return
        raw = value.encode("utf-8")[-max_bytes:]
        low, high = 0, len(raw)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = raw[-middle:].decode("utf-8", errors="ignore") if middle else ""
            result[key] = candidate
            if encoded_size() <= MAX_DIAGNOSTIC_BYTES:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        result[key] = best

    # 为 stderr 保留最大份额，避免深 traceback 把真正根因完全挤掉。
    output_budgets = {
        "stderr": 3 * 1024,
        "traceback": 2 * 1024,
        "stdout": 1536,
        "result": 1024,
    }
    for key in ("stderr", "traceback", "stdout", "result"):
        value = details.get(key)
        if isinstance(value, str):
            add_tail(key, value, output_budgets[key])
    return result


def _bounded_failure(code: str, cell: Any) -> dict[str, Any]:
    details = {
        name: str(_cell_field(cell, name, "") or "")
        for name in ("traceback", "stderr", "stdout")
    }
    return _failure(code, "Coding Agent 脚本执行失败。", details)


def _visual_repair_diagnostic(
    receipt: ChartVisualInspectionReceipt,
) -> dict[str, Any] | None:
    if receipt.visual_review_status == "passed" and not receipt.requires_revision:
        return None
    return {
        "code": "report_visualization_review_failed",
        "message": "图表独立视觉审查要求修订。",
        "details": {
            "sourcePath": receipt.source_path,
            "visualReviewStatus": receipt.visual_review_status,
            "requiresRevision": receipt.requires_revision,
            "issueCategories": sorted({issue.category for issue in receipt.issues}),
            "issueSeverities": sorted({issue.severity for issue in receipt.issues}),
        },
    }


def _reset_stop_after_tool_call(fc: Any) -> None:
    fc.function.stop_after_tool_call = False


def _stop_after_success(fc: Any) -> None:
    fc.function.stop_after_tool_call = bool(
        isinstance(fc.result, dict) and fc.result.get("ok") is True
    )


def _lsp_parameters(*, path_required: bool, include_position: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "path": {"type": "string", "minLength": 1},
        "expectedSourceSha256": {"type": "string", "minLength": 64, "maxLength": 64},
    }
    if include_position:
        properties.update(
            {
                "line": {"type": "integer", "minimum": 0},
                "character": {"type": "integer", "minimum": 0},
            }
        )
    required = ["path"] if path_required else []
    if include_position:
        required.extend(("line", "character"))
    return {"type": "object", "properties": properties, "required": required}


class ReportingCodeModeToolkit(Toolkit):
    """把固定 task binding 暴露为执行与只读代码理解工具。"""

    def __init__(
        self,
        binding: ReportingCodingTaskBinding,
        runtime: ReportingCodeModeRuntime,
        lsp_manager: ReportingLspProcessManager,
        knowledge_index: ReportingKnowledgeIndex | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
        output_preflight: Callable[[ExecutionReceipt], Awaitable[Mapping[str, Any] | None]] | None = None,
    ) -> None:
        self.binding = binding
        self.runtime = runtime
        self.knowledge_index = knowledge_index
        self.vision_reviewer = vision_reviewer
        self.lsp = ReportingWorkspaceLsp(binding, lsp_manager)
        self.submitted_receipt: ExecutionReceipt | None = None
        self.output_preflight = output_preflight
        self.pending_output_validation: dict[str, Any] | None = None
        self.terminal_failure: ReportingError | None = None
        self.last_tool: str | None = None
        self.last_failure: dict[str, Any] | None = None
        self.completed_tool_calls = 0
        self._snippet_calls = 0
        self._snippet_limit = (
            VISUALIZATION_SNIPPET_LIMIT
            if self.context.task_kind == "visualization"
            else ANALYSIS_SNIPPET_LIMIT
        )
        self._failure_signature: str | None = None
        self._repeated_failure_count = 0
        tools = [
            Function(
                name="write_script",
                description=(
                    "将完整 Python 源码写入当前任务脚本。源码应通过 Workspace 路径读取数据，"
                    "不得内嵌 CSV 行、查询结果或大段数据文本。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.write_script,
            ),
            Function(name="read_script", entrypoint=self.read_script),
            Function(
                name="run_snippet",
                description=(
                    "执行短小的探索性 Python 或 Shell 代码，用于数据抽样、环境检查和假设验证。"
                    "不得用于生成最终交付脚本；探索后必须调用 write_script、run_script、submit_script。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.run_snippet,
            ),
            Function(name="restart_code_mode", entrypoint=self.restart_code_mode),
            Function(name="run_script", entrypoint=self.run_script),
            Function(
                name="lsp_diagnostics",
                parameters=_lsp_parameters(path_required=False, include_position=False),
                entrypoint=self.lsp_diagnostics,
            ),
            Function(
                name="lsp_hover",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_hover,
            ),
            Function(
                name="lsp_definition",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_definition,
            ),
            Function(
                name="lsp_references",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_references,
            ),
            Function(
                name="lsp_document_symbols",
                parameters=_lsp_parameters(path_required=True, include_position=False),
                entrypoint=self.lsp_document_symbols,
            ),
            Function(
                name="submit_script",
                entrypoint=self.submit_script,
                pre_hook=_reset_stop_after_tool_call,
            ),
        ]
        if self.context.task_kind == "visualization":
            tools.append(
                Function(
                    name="view_image",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    strict=True,
                    entrypoint=self.view_image,
                )
            )
        if knowledge_index is not None:
            tools.append(
                Function(
                    name="search_knowledge",
                    description="检索当前 Workspace 可见的项目文档、规范和成功修复记录。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1, "maxLength": 4096}
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    strict=True,
                    entrypoint=self.search_knowledge,
                )
            )
        for function in tools:
            function.post_hook = self._record_tool_result
        super().__init__(name="reporting_code_mode", tools=tools)

    async def _source_sha256(self) -> str | None:
        try:
            identity = await self.workspace.ahash_file(self.context.task_id, self.context.script_path)
        except WorkspaceError:
            return None
        return identity["sha256"]

    async def _record_tool_result(self, fc: Any) -> None:
        """使用 Agno 原生 hook 观测实际调用；未执行的批次回执不会覆盖根因。"""
        name = fc.function.name
        self.last_tool = name
        self.completed_tool_calls += 1
        if name == "submit_script":
            _stop_after_success(fc)
        result = fc.result
        if isinstance(result, Mapping) and isinstance(result.get("outputValidation"), Mapping):
            result = result["outputValidation"]
        if fc.error or (isinstance(result, Mapping) and result.get("ok") is False):
            payload = result if isinstance(result, Mapping) else {}
            if (
                payload.get("code") == "report_code_submission_not_executed"
                and self.last_failure is not None
                and not self.last_failure["resolved"]
            ):
                return
            details = payload.get("details")
            failure = {
                "tool": name,
                "sourceSha256": await self._source_sha256(),
                "code": str(payload.get("code", "tool_error"))[:128],
                "message": str(fc.error or payload.get("message", ""))[:512],
                "details": _safe_diagnostic_details(details) if isinstance(details, Mapping) else {},
            }
            signature = json.dumps(failure, ensure_ascii=False, sort_keys=True)
            self._repeated_failure_count = (
                self._repeated_failure_count + 1 if signature == self._failure_signature else 1
            )
            self._failure_signature = signature
            self.last_failure = {**failure, "resolved": False}
            if self._repeated_failure_count > 1 and isinstance(result, dict):
                result["repeatedFailureCount"] = self._repeated_failure_count
                result["repairHint"] = "相同源码再次出现相同错误；请检查输入与环境，并调整修复方法。"
                logger.warning(
                    "report_code_repeated_failure tool={} code={} count={}",
                    name, failure["code"], self._repeated_failure_count,
                )
        elif isinstance(result, Mapping) and result.get("ok") is True:
            if self.last_failure is not None and self.last_failure["tool"] == name:
                self.last_failure = {**self.last_failure, "resolved": True}
                self._failure_signature = None
                self._repeated_failure_count = 0

    async def submission_diagnostic(self) -> dict[str, Any]:
        receipt = self.binding.execution_receipt
        return {
            "lastTool": self.last_tool,
            "lastFailure": self.last_failure,
            "sourceSha256": await self._source_sha256(),
            "hasExecutionReceipt": receipt is not None,
            "completedToolCalls": self.completed_tool_calls,
            "unreviewedOutputPaths": [
                item.path for item in (receipt.output_files if receipt else ())
                if self.context.task_kind == "visualization" and (
                    (review := self.binding.visual_inspection_receipts.get(item.path)) is None
                    or review.sha256 != item.sha256 or not review.reviewed
                    or review.visual_review_status != "passed" or review.requires_revision
                )
            ],
        }

    @property
    def context(self) -> ReportingCodingTaskContext:
        return self.binding.context

    @property
    def workspace(self):
        return self.binding.workspace

    @property
    def tool_functions(self) -> tuple[Function, ...]:
        return tuple([*self.functions.values(), *self.async_functions.values()])

    def has_current_visual_review(self, path: str) -> bool:
        """供协议预算门禁判断指定图片是否已经完成当前内容审查。"""
        try:
            path = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except WorkspaceError:
            return False
        execution = self.binding.execution_receipt
        if execution is None:
            return False
        output = next((item for item in execution.output_files if item.path == path), None)
        review = self.binding.visual_inspection_receipts.get(path)
        return bool(
            output is not None
            and review is not None
            and review.source_path == path
            and review.sha256 == output.sha256
            and review.reviewed
            and review.visual_review_status == "passed"
            and not review.requires_revision
        )

    async def read_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        if not await self.workspace.apath_exists(self.context.task_id, self.context.script_path):
            return {"ok": True, "exists": False, "path": self.context.script_path}
        raw = await self.workspace.read_limited_regular_file(
            self.context.task_id,
            self.context.script_path,
            max_bytes=self.context.max_source_bytes,
        )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportingError(
                "report_code_source_invalid", "Python 脚本不是有效的 UTF-8 文本。"
            ) from error
        return {
            "ok": True,
            "exists": True,
            "path": self.context.script_path,
            "source": source,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    async def search_knowledge(
        self, query: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        if self.knowledge_index is None:
            return _failure("report_knowledge_unavailable", "知识索引未配置。")
        try:
            results = await self.knowledge_index.search(
                query,
                workspace_key=self.context.workspace_key,
            )
        except KnowledgeIndexError as error:
            return _failure(error.code, str(error))
        return {
            "ok": True,
            "results": [
                {
                    "identity": item.identity,
                    "kind": item.kind,
                    "snippet": item.snippet,
                    "score": item.score,
                    "contentSha256": item.content_sha256,
                }
                for item in results
            ],
        }

    async def write_script(
        self, source: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        source = validate_draft_source(self.context, source).decode("utf-8")
        try:
            tree = ast.parse(source, filename=self.context.script_path)
        except SyntaxError:
            # 草稿允许暂时存在语法错误，供 LSP 和后续修复使用。
            pass
        else:
            _reject_embedded_data(tree)
        exists = await self.workspace.apath_exists(self.context.task_id, self.context.script_path)
        await self.workspace.awrite_text(
            self.context.task_id,
            self.context.script_path,
            source,
            overwrite=exists,
        )
        self.binding.clear_execution_receipt()
        self.submitted_receipt = None
        self.pending_output_validation = None
        return {
            "ok": True,
            **await self.workspace.ahash_file(self.context.task_id, self.context.script_path),
        }

    async def run_snippet(
        self, code: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        if self._snippet_calls >= self._snippet_limit:
            return _failure(
                "report_code_exploration_budget_exhausted",
                "交互探索额度已用尽；请立即更新并运行正式脚本，然后提交交付结果。",
                {
                    "used": self._snippet_calls,
                    "limit": self._snippet_limit,
                    "requiredNextTools": ["write_script", "run_script", "submit_script"],
                },
            )
        self._snippet_calls += 1
        try:
            cell = await self.runtime.execute(
                self.context.code_mode_session_id,
                self.workspace,
                code,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
        except ReportingError as error:
            return _failure(error.code, error.message, error.details if isinstance(error.details, Mapping) else None)
        if _cell_field(cell, "status") != "ok":
            return _bounded_failure("report_code_mode_execution_failed", cell)
        outputs = {
            name: str(_cell_field(cell, name, "") or "")
            for name in ("result", "stderr", "stdout")
        }
        bounded = _safe_diagnostic_details(outputs)
        truncated = set(_cell_field(cell, "truncated", ()) or ()) & outputs.keys()
        truncated.update(name for name, value in outputs.items() if bounded.get(name, "") != value)
        return {
            "ok": True,
            "status": "completed",
            **bounded,
            "truncated": sorted(truncated),
        }

    async def restart_code_mode(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        self.binding.clear_execution_receipt()
        self.submitted_receipt = None
        self.pending_output_validation = None
        await self.runtime.shutdown(self.context.code_mode_session_id)
        return {"ok": True}

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        try:
            source_path = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except WorkspaceError:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片路径不属于当前 Coding task 的声明输出。",
            )
        if source_path not in self.context.declared_output_paths:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片路径不属于当前 Coding task 的声明输出。",
            )
        execution = self.binding.execution_receipt
        if execution is None:
            return _failure(
                "report_code_visual_review_required_execution",
                "图片必须先由当前脚本成功执行生成。",
            )
        output = next(
            (item for item in execution.output_files if item.path == source_path),
            None,
        )
        if output is None:
            return _failure(
                "report_code_visual_path_forbidden",
                "图片不属于最近一次成功执行的输出。",
            )
        try:
            before = FileIdentity.model_validate(
                await self.workspace.ahash_file(self.context.task_id, source_path)
            )
        except (TypeError, ValueError, WorkspaceError):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        if before != output:
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        cached = self.binding.visual_inspection_receipts.get(source_path)
        if cached is not None and cached.sha256 == output.sha256:
            return {
                "ok": True,
                "receipt": cached.model_dump(mode="json", by_alias=True),
            }
        if self.vision_reviewer is None:
            return _failure(
                "report_code_visual_review_unavailable",
                "独立视觉审查暂不可用，请稍后重试。",
            )
        try:
            reviewed = ChartVisualInspectionReceipt.model_validate(
                await self.vision_reviewer.review(
                    self.context.workspace_key,
                    source_path,
                    detail=detail,
                )
            )
        except Exception:
            return _failure(
                "report_code_visual_review_unavailable",
                "独立视觉审查暂不可用，请稍后重试。",
            )
        try:
            after = FileIdentity.model_validate(
                await self.workspace.ahash_file(self.context.task_id, source_path)
            )
        except (TypeError, ValueError, WorkspaceError):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        if (
            reviewed.source_path != source_path
            or before.sha256 != reviewed.sha256
            or reviewed.sha256 != after.sha256
            or after != output
        ):
            self.binding.visual_inspection_receipts.pop(source_path, None)
            return _failure(
                "report_code_visual_output_changed",
                "图片输出在执行或视觉审查后发生变化。",
            )
        self.binding.visual_inspection_receipts[source_path] = reviewed
        diagnostic = _visual_repair_diagnostic(reviewed)
        if diagnostic is not None:
            self.binding.visual_repair_diagnostic = diagnostic
        return {
            "ok": True,
            "receipt": reviewed.model_dump(mode="json", by_alias=True),
        }

    async def lsp_diagnostics(
        self,
        path: str | None = None,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.diagnostics(
            path,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_hover(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.hover(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_definition(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.definition(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_references(
        self,
        path: str,
        line: int,
        character: int,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.references(
            path,
            line=line,
            character=character,
            expected_source_sha256=expectedSourceSha256,
        )

    async def lsp_document_symbols(
        self,
        path: str,
        expectedSourceSha256: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        return await self.lsp.document_symbols(
            path,
            expected_source_sha256=expectedSourceSha256,
        )

    async def _validated_source_identity(self) -> FileIdentity:
        raw = await self.workspace.read_limited_regular_file(
            self.context.task_id,
            self.context.script_path,
            max_bytes=self.context.max_source_bytes,
        )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportingError(
                "report_code_source_invalid", "Python 脚本不是有效的 UTF-8 文本。"
            ) from error
        validate_script_source(self.context, source)
        return FileIdentity(
            path=self.context.script_path,
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    async def _clear_declared_outputs(self) -> None:
        for path in self.context.declared_output_paths:
            await self.workspace.adelete_file(self.context.task_id, path)

    async def _declared_output_identities(self) -> tuple[FileIdentity, ...]:
        identities: list[FileIdentity] = []
        for path in self.context.declared_output_paths:
            try:
                value = await self.workspace.ahash_file(self.context.task_id, path)
            except WorkspaceError as error:
                raise ReportingError(
                    "report_code_declared_output_missing",
                    "Coding Agent 声明输出不存在。",
                    details={"path": path},
                ) from error
            identities.append(FileIdentity.model_validate(value))
        return tuple(identities)

    async def run_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        previous_visual_reviews = dict(self.binding.visual_inspection_receipts)
        self.binding.clear_execution_state()
        self.submitted_receipt = None
        self.pending_output_validation = None
        try:
            source_before = await self._validated_source_identity()
            await self._clear_declared_outputs()
            cell = await self.runtime.execute_script_process(
                self.context.code_mode_session_id,
                self.workspace,
                self.context.script_path,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
            if _cell_field(cell, "status") != "ok":
                return _bounded_failure("report_code_mode_execution_failed", cell)
            exit_code = script_process_exit_code(cell)
            if exit_code is None or exit_code != 0:
                details: dict[str, Any] = {
                    name: str(_cell_field(cell, name, "") or "")
                    for name in ("traceback", "stderr", "stdout")
                }
                if exit_code is not None:
                    details["exitCode"] = exit_code
                return _failure(
                    "report_code_mode_execution_failed",
                    "Coding Agent 脚本子进程未正常退出。",
                    details,
                )
            source_after = await self._validated_source_identity()
            if source_after != source_before:
                return _failure(
                    "report_code_script_modified_during_execution",
                    "脚本在执行期间发生变化。",
                )
            outputs = await self._declared_output_identities()
        except WorkspaceError:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
            )
        except ReportingError as error:
            return _failure(error.code, error.message, error.details if isinstance(error.details, Mapping) else None)
        receipt = ExecutionReceipt(
            runId=uuid4().hex,
            sourceFile=source_after,
            outputFiles=outputs,
        )
        self.binding.execution_receipt = receipt
        output_by_path = {item.path: item for item in outputs}
        self.binding.visual_inspection_receipts.update(
            {
                path: review
                for path, review in previous_visual_reviews.items()
                if (
                    (output := output_by_path.get(path)) is not None
                    and review.source_path == path
                    and review.sha256 == output.sha256
                    and review.reviewed
                    and review.visual_review_status == "passed"
                    and not review.requires_revision
                )
            }
        )
        result = {
            "ok": True,
            "executionReceipt": receipt.model_dump(mode="json", by_alias=True),
        }
        if self.output_preflight is not None:
            diagnostic = await self.output_preflight(receipt)
            await self.require_current_receipt(receipt)
            if diagnostic is not None:
                self.pending_output_validation = _failure(
                    str(diagnostic["code"]), str(diagnostic["message"]), diagnostic.get("details"),
                )
                result["outputValidation"] = self.pending_output_validation
                result["ok"] = False
                result["repairHint"] = "输出结构校验未通过，请修复后重新执行；最终验收与降级由 Workflow 处理。"
            else:
                self.pending_output_validation = None
        return result

    async def submit_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        if self.pending_output_validation is not None:
            return _failure(
                "report_code_output_validation_pending",
                "最近一次执行的输出结构校验未通过；请修复并重新执行后再提交。",
                self.pending_output_validation.get("details"),
            )
        receipt = self.binding.execution_receipt
        if receipt is None:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
            )
        try:
            source = await self._validated_source_identity()
            outputs = await self._declared_output_identities()
        except WorkspaceError:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
                {"path": self.context.script_path},
            )
        except ReportingError as error:
            return _failure(
                error.code,
                error.message,
                error.details if isinstance(error.details, Mapping) else None,
            )
        if source != receipt.source_file:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
            )
        if outputs != receipt.output_files:
            return _failure(
                "report_code_output_modified_after_execution",
                "脚本输出在执行后发生变化。",
            )
        if self.context.task_kind == "visualization":
            output_by_path = {item.path: item for item in receipt.output_files}
            reviews = self.binding.visual_inspection_receipts
            if set(reviews) != set(output_by_path):
                return _failure(
                    "report_code_visual_review_required",
                    "每个当前图片输出都必须完成独立视觉审查。",
                )
            for path, output in output_by_path.items():
                reviewed = reviews[path]
                if reviewed.source_path != path:
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                    )
                if reviewed.sha256 != output.sha256:
                    return _failure(
                        "report_code_visual_output_changed",
                        "图片输出在执行或视觉审查后发生变化。",
                    )
                if not reviewed.reviewed or reviewed.visual_review_status != "passed":
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                    )
                if reviewed.requires_revision:
                    return _failure(
                        "report_code_visual_revision_required",
                        "独立视觉审查要求修订当前图片输出。",
                    )
        self.submitted_receipt = receipt
        return {
            "ok": True,
            "executionReceipt": receipt.model_dump(mode="json", by_alias=True),
        }

    async def require_current_receipt(self, receipt: ExecutionReceipt) -> None:
        try:
            source = await self._validated_source_identity()
            outputs = await self._declared_output_identities()
        except (ReportingError, WorkspaceError) as error:
            terminal = ReportingError(
                "report_phase_artifact_changed",
                "Coding Agent 签发产物在阶段交接前发生变化。",
            )
            self.terminal_failure = terminal
            raise terminal from error
        if source != receipt.source_file or outputs != receipt.output_files:
            terminal = ReportingError(
                "report_phase_artifact_changed",
                "Coding Agent 签发产物在阶段交接前发生变化。",
            )
            self.terminal_failure = terminal
            raise terminal


__all__ = [
    "ReportingCodeModeToolkit",
    "compile_script_source",
    "validate_draft_source",
    "validate_script_source",
]
