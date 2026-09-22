"""交互式 Coding Agent 的 Workspace 与执行身份工具。"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from time import perf_counter
from typing import Any, NoReturn
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Function, Toolkit
from loguru import logger

from ...code_monitor.tools import log_tool_event
from ...workspace import WorkspaceError, WorkspaceService
from ..code_mode import ReportingCodeModeRuntime, ScriptProcessResult
from ..knowledge import KnowledgeIndexError, ReportingKnowledgeIndex
from ..models import ReportingError
from ..vision import ReportVisionReviewer
from ..workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .context import (
    OUTPUT_VALIDATION_UNAVAILABLE,
    ExecutionReceipt,
    OutputValidationState,
    OutputValidationStatus,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from .delivery import _visual_review_model_receipt, build_delivery_state
from .edit_patch import apply_edit_blocks, parse_edit_patch
from .formatting import format_python_source
from .lsp import ReportingWorkspaceLsp
from .lsp_process import ReportingLspProcessManager

MAX_DIAGNOSTIC_BYTES = 8 * 1024
MAX_EXPLORATION_VARIABLES = 32
MAX_EXPLORATION_VARIABLE_NAME_BYTES = 128
MAX_EXPLORATION_VARIABLE_TYPE_BYTES = 64
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


def _looks_like_code_text(value: str) -> bool:
    stripped = value.lstrip()
    return "\n" in value or stripped.startswith(
        (
            "import ",
            "from ",
            "def ",
            "class ",
            "if ",
            "for ",
            "while ",
            "try:",
            "with ",
            "print(",
            "%%bash",
        )
    ) or any(token in value for token in ("=", "(", ")", ";"))


def _reject_code_envelope(tree: ast.Module, tool_name: str) -> None:
    """只检查整个输入的代码包装；不解包执行，也不禁止普通字典表达式。"""
    wrapper_keys: list[str] = []
    while len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
        value = tree.body[0].value
        if not isinstance(value, ast.Dict) or len(value.keys) != 1:
            break
        key, content = value.keys[0], value.values[0]
        if not isinstance(key, ast.Constant) or key.value not in ("data", "code", "source"):
            break
        wrapper_keys.append(key.value)
        if isinstance(content, ast.Constant) and isinstance(content.value, str):
            try:
                nested = ast.parse(content.value)
            except SyntaxError:
                if _looks_like_code_text(content.value):
                    raise ReportingError(
                        "report_code_input_wrapped",
                        f"{tool_name} 需要原始代码文本，但收到包含代码的字典包装。"
                        "本次未执行代码或写入脚本。请直接重新调用，输入原始 Python/cell 文本，"
                        '不要添加 {"data": ...}、{"code": ...}、{"source": ...} 或 Markdown 围栏。',
                        details={
                            "reason": "code_envelope",
                            "tool": tool_name,
                            "wrapperKeys": wrapper_keys,
                            "nextTools": [tool_name],
                        },
                    ) from None
                return
        elif isinstance(content, ast.Dict):
            nested = ast.Module(body=[ast.Expr(value=content)], type_ignores=[])
        else:
            return
        tree = nested

    # 数字、普通文字、字典等数据仍可直接求值；语句、调用和运算说明内部是代码。
    executable = any(
        (isinstance(node, ast.stmt) and not isinstance(node, ast.Expr))
        or isinstance(node, (ast.Call, ast.Await, ast.NamedExpr, ast.BinOp, ast.BoolOp, ast.Compare))
        for node in ast.walk(tree)
    )
    if wrapper_keys and executable:
        raise ReportingError(
            "report_code_input_wrapped",
            f"{tool_name} 需要原始代码文本，但收到包含代码的字典包装。"
            "本次未执行代码或写入脚本。请直接重新调用，输入原始 Python/cell 文本，"
            '不要添加 {"data": ...}、{"code": ...}、{"source": ...} 或 Markdown 围栏。',
            details={"reason": "code_envelope", "tool": tool_name,
                     "wrapperKeys": wrapper_keys, "nextTools": [tool_name]},
        )


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
            "Python 源码超过大小限制；请精简脚本。",
            {
                "reason": "source_too_large",
                "actualBytes": len(raw),
                "limitBytes": context.max_source_bytes,
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


def _reject_unauthorized_paths(tree: ast.AST, path: str, authorized_paths: frozenset[str]) -> None:
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
            "源码内使用了未授权路径或目录推导操作；unsignedPaths 是未签发路径，"
            "forbiddenPathOperations 是禁止的操作。直接使用 task 中签发的完整路径，"
            "移除目录推导，不要通过 cwd、__file__ 或父目录拼接路径。",
            details={
                "path": path,
                "unsignedPaths": sorted(unsigned)[:20],
                "forbiddenPathOperations": sorted(forbidden),
            },
        )


def compile_script_source(path: str, source: str, authorized_paths: frozenset[str]) -> None:
    try:
        tree = ast.parse(source, filename=path)
        _reject_embedded_data(tree)
        _reject_unauthorized_paths(tree, path, authorized_paths)
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


def _bounded_exploration_variables(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for name in sorted(item for item in value if isinstance(item, str)):
        variable_type = value[name]
        if (
            len(result) >= MAX_EXPLORATION_VARIABLES
            or not name.isidentifier()
            or name.startswith("_")
            or len(name.encode("utf-8")) > MAX_EXPLORATION_VARIABLE_NAME_BYTES
            or not isinstance(variable_type, str)
        ):
            continue
        raw_type = variable_type.encode("utf-8")[:MAX_EXPLORATION_VARIABLE_TYPE_BYTES]
        result[name] = raw_type.decode("utf-8", errors="ignore")
    return result


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
        "used", "limit", "requiredNextTools", "nextTools", "kind", "bytes", "items",
        "actualBytes", "limitBytes", "missingPaths", "exitCode", "escalated",
        "status", "validationRunId", "executionRunId", "sourceSha256",
        "currentSha256", "expectedSha256", "action", "readRange",
        "sourceExcerpt", "sourceStartLine", "sourceEndLine", "errorLine", "blockIndex",
        "variableSummary", "explorationVariables", "allowedEditRegion", "forbiddenEditRegions",
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
            "unsignedPaths", "forbiddenPathOperations", "requiredNextTools", "nextTools", "missingPaths",
        }:
            if isinstance(value, list):
                result[key] = [bounded_text(str(item), 256) for item in value[:20]]
        elif key in {"retryable", "escalated"}:
            if isinstance(value, bool):
                result[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
        elif key == "readRange" and isinstance(value, Mapping):
            result[key] = {
                field: value[field]
                for field in ("path", "startLine", "endLine")
                if isinstance(value.get(field), (str, int))
                and not isinstance(value.get(field), bool)
            }
        elif key == "allowedEditRegion" and isinstance(value, Mapping):
            result[key] = {
                field: value[field]
                for field in ("path", "startLine", "endLine")
                if isinstance(value.get(field), (str, int))
                and not isinstance(value.get(field), bool)
            }
        elif key == "forbiddenEditRegions" and isinstance(value, list):
            result[key] = [
                {
                    "path": item.get("path"),
                    "outside": {
                        field: item["outside"][field]
                        for field in ("startLine", "endLine", "allowedStartLine", "allowedEndLine")
                        if isinstance(item.get("outside"), Mapping)
                        and isinstance(item["outside"].get(field), int)
                        and not isinstance(item["outside"].get(field), bool)
                    },
                }
                for item in value[:4]
                if isinstance(item, Mapping) and isinstance(item.get("path"), str)
            ]
        elif key == "variableSummary" and isinstance(value, Mapping):
            summary_result: dict[str, Any] = {}
            for name, summary in list(value.items())[:20]:
                safe_name = bounded_text(str(name), 128)
                if isinstance(summary, Mapping):
                    summary_result[safe_name] = {
                        str(field)[:64]: bounded_text(str(item), 256)
                        for field, item in list(summary.items())[:8]
                        if isinstance(item, (str, int, float, bool)) or item is None
                    }
                elif isinstance(summary, (str, int, float, bool)) or summary is None:
                    summary_result[safe_name] = bounded_text(str(summary), 256)
            result[key] = summary_result
        elif key == "explorationVariables" and isinstance(value, Mapping):
            result[key] = _bounded_exploration_variables(value)
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
    for key in reversed(tuple(result)):
        if encoded_size() <= MAX_DIAGNOSTIC_BYTES:
            break
        if key in {"nextTools", "requiredNextTools"}:
            continue
        result.pop(key)

    def add_output(key: str, value: str, max_bytes: int) -> None:
        result[key] = ""
        if encoded_size() > MAX_DIAGNOSTIC_BYTES:
            result.pop(key, None)
            return
        raw = value.encode("utf-8")
        if len(raw) <= max_bytes:
            result[key] = value
            if encoded_size() <= MAX_DIAGNOSTIC_BYTES:
                return
        keep_head = key in {"stdout", "result"}
        marker = "\n[... truncated ...]\n" if keep_head else ""
        low, high = 0, min(len(raw), max_bytes - len(marker.encode("utf-8")))
        best = ""
        while low <= high:
            middle = (low + high) // 2
            if keep_head:
                head_bytes = (middle + 1) // 2
                tail_bytes = middle // 2
                candidate = (
                    raw[:head_bytes].decode("utf-8", errors="ignore")
                    + marker
                    + (raw[-tail_bytes:].decode("utf-8", errors="ignore") if tail_bytes else "")
                )
            else:
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
            add_output(key, value, output_budgets[key])
    return result


def _bounded_failure(
    code: str,
    cell: Any,
    *,
    exploration_variables: Mapping[str, str] | None = None,
    next_tools: list[str] | None = None,
) -> dict[str, Any]:
    details = {
        name: str(_cell_field(cell, name, "") or "")
        for name in ("traceback", "stderr", "stdout")
    }
    variable_summary = _cell_field(cell, "variableSummary")
    if isinstance(variable_summary, Mapping):
        details["variableSummary"] = variable_summary
    else:
        details["variableSummary"] = {
            "status": "unknown",
            "reason": "runtime_did_not_expose_locals",
        }
    if exploration_variables is not None:
        details["explorationVariables"] = exploration_variables
    if next_tools is not None:
        details["nextTools"] = next_tools
    return _failure(code, "Coding Agent 脚本执行失败。", details)


def _visual_repair_diagnostic(
    receipt: ChartVisualInspectionReceipt,
) -> dict[str, Any] | None:
    if receipt.visual_review_status == "passed" and not receipt.requires_revision:
        return None
    critical_issues = [issue for issue in receipt.issues if issue.severity == "critical"]
    return {
        "code": "report_visualization_review_failed",
        "message": "图表独立视觉审查要求修订。",
        "details": {
            "sourcePath": receipt.source_path,
            "visualReviewStatus": receipt.visual_review_status,
            "requiresRevision": receipt.requires_revision,
            "issueCategories": sorted({issue.category for issue in critical_issues}),
            "issueSeverities": sorted({issue.severity for issue in critical_issues}),
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
        failure_artifact_recorder: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.binding = binding
        self.runtime = runtime
        self.knowledge_index = knowledge_index
        self.vision_reviewer = vision_reviewer
        self.lsp = ReportingWorkspaceLsp(binding, lsp_manager)
        self.submitted_receipt: ExecutionReceipt | None = None
        self.output_preflight = output_preflight
        self.failure_artifact_recorder = failure_artifact_recorder
        self.terminal_failure: ReportingError | None = None
        self.last_tool: str | None = None
        self.last_failure: dict[str, Any] | None = None
        self.completed_tool_calls = 0
        self._tool_call_counts: dict[str, int] = {}
        self.first_script_success: bool | str = "unknown"
        self.first_script_failure_code: str = "unknown"
        self.first_run_success: bool | str = "unknown"
        self.first_run_failure_code: str = "unknown"
        self.first_run_failure: dict[str, Any] | None = None
        self.first_patch_applied: bool | str = "unknown"
        self.first_repair_success: bool | str = "unknown"
        self._awaiting_first_repair_run = False
        self.visual_review_duration_ms = 0
        self._delivery_state: dict[str, Any] = {}
        self._failure_signature: str | None = None
        self._repeated_failure_count = 0
        tools = [
            Function(
                name="write_script",
                description=(
                    "这是正式 Python 脚本的首次创建工具；已有脚本的修复必须使用 edit_script，禁止重新生成整段源码。"
                    "调用时必须直接发送完整 Python 源码文本；语法错误草稿可保存供 LSP 修复。不要发送探索 cell、Bash、"
                    "JSON 对象、JSON 字符串、Markdown 围栏或自然语言。源码应通过 Workspace 路径读取数据，"
                    "不得内嵌 CSV 行、查询结果或大段数据文本。"
                    "源码中的文件路径必须逐字使用 task 签发路径，不得用 cwd、__file__ 或 os.path.dirname 推导目录。"
                    "输入示例：\n# Python\nimport pandas as pd\nprint(pd.__version__)\n示例结束。"
                    "合法 Python 源码会在本地格式化后保存；返回哈希对应保存内容；若发生格式化，"
                    "savedSource 是实际落盘源码，后续 edit_script 必须以它或 read_script 返回内容为准。"
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
            Function(
                name="edit_script",
                description=(
                    "对当前绑定脚本做精确局部编辑；输入为原始补丁，可含多个 SEARCH/REPLACE 块。"
                    '不要包裹成 JSON 或 {"data": ...}；evidence 文件的 JSON 与本工具输入无关。'
                    "从 read_script 或执行失败回执取得当前源码 sha256，必须把该哈希原样放在 *** SHA256: 后。"
                    "每个 SEARCH 必须在同一份原始源码中逐字匹配唯一位置，各块不得重叠。"
                    "先整体校验再一次提交；不得用前块生成的文本作为后块 SEARCH。"
                    "插入使用原文上下文作锚点；删除使用空 REPLACE；移动用删除块与目标处插入块。"
                    "禁止整份替换；不接受文件路径。"
                    "标记独占一行并使用 LF；分隔符前的一个换行属于协议，"
                    "如旧文本或新文本本身以换行结尾，需在分隔符前再保留一个换行。"
                    "输入示例（哈希必须替换为当前脚本的真实值）：\n"
                    "*** Begin Edit\n*** SHA256: " + "0" * 64 + "\n"
                    "<<<<<<< SEARCH\nvalue = 1\n=======\nvalue = 2\n"
                    ">>>>>>> REPLACE\n*** End Edit"
                ),
                parameters={
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.edit_script,
            ),
            Function(
                name="read_script",
                description=(
                    "读取当前任务绑定的脚本；不接受 path 参数，脚本路径由服务端绑定。"
                    "可用 start_line/end_line 局部读取，行号从 1 开始且包含首尾；"
                    "省略起点从首行读，省略终点读至末尾，均省略则读取全文。"
                    "返回原始源码片段、totalLines/startLine/endLine；size 和 sha256 始终对应整份文件，"
                    "可直接用于 edit_script 版本校验。终点超出末尾时截至末尾，起点越界则报错。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.read_script,
            ),
            Function(
                name="run",
                description=(
                    "这是探索工具，不是正式脚本写入工具。在当前任务的持久 Python 会话执行短小代码，"
                    "用于数据抽样、环境检查和假设验证；"
                    "变量和导入可在后续 run 调用中复用。Shell 使用以 %%bash 为第一行的 cell。"
                    "这是 free-form 工具：直接输入原始代码。"
                    "输入示例：\n# Python\nprint(1 + 1)\n示例结束。"
                    "不要 JSON 包装、字符串引号或 Markdown 围栏。"
                    "返回 stdout、stderr、末尾表达式的 result 和 truncated 标记；"
                    "explorationVariables 仅列出当前会话可复用的变量名和类型，后续 run 应直接复用，"
                    "不要重新读取同一文件；"
                    "ok 只表示本次 cell 执行成功。"
                    "不要用 run 保存或替代正式 Python 脚本；首次创建用 write_script，已有脚本用 edit_script，"
                    "然后依次调用 run_script、submit_script。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
                strict=True,
                entrypoint=self.run,
            ),
            Function(name="restart_code_mode", description="重启当前探索会话并清空执行回执；不会删除已保存的脚本。", entrypoint=self.restart_code_mode),
            Function(name="run_script", description="运行已保存的绑定脚本并校验声明输出；失败时按回执中的源码 SHA 与片段使用 edit_script 局部修复，随后重新运行。", entrypoint=self.run_script),
            Function(
                name="lsp_diagnostics",
                description="检查已保存脚本的语法和类型诊断；可用当前脚本 SHA 防止读取旧版本。",
                parameters=_lsp_parameters(path_required=False, include_position=False),
                entrypoint=self.lsp_diagnostics,
            ),
            Function(
                name="lsp_hover",
                description="查询已保存脚本指定位置的符号信息；line、character 从 0 开始，与 read_script 从 1 开始的行号不同。",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_hover,
            ),
            Function(
                name="lsp_definition",
                description="查询已保存脚本指定符号的定义位置；line、character 从 0 开始。",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_definition,
            ),
            Function(
                name="lsp_references",
                description="查询已保存脚本指定符号的引用位置；line、character 从 0 开始。",
                parameters=_lsp_parameters(path_required=True, include_position=True),
                entrypoint=self.lsp_references,
            ),
            Function(
                name="lsp_document_symbols",
                description="列出已保存脚本中的符号及位置。",
                parameters=_lsp_parameters(path_required=True, include_position=False),
                entrypoint=self.lsp_document_symbols,
            ),
            Function(
                name="submit_script",
                description="成功执行绑定脚本并完成输出校验后提交当前执行回执；不会写入或修复源码。",
                entrypoint=self.submit_script,
            ),
        ]
        if self.context.task_kind == "visualization":
            tools.append(
                Function(
                    name="view_image",
                    description="审查 run_script 生成的当前图片输出；仅对声明的图片路径使用，修复后重新运行再审查。",
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
            function.pre_hook = self._record_tool_start
            function.post_hook = self._record_tool_result
        super().__init__(name="reporting_code_mode", tools=tools)

    async def _source_sha256(self) -> str | None:
        try:
            identity = await self.workspace.ahash_file(self.context.task_id, self.context.script_path)
        except WorkspaceError:
            return None
        return identity["sha256"]

    async def _script_repair_details(
        self, details: Mapping[str, Any], expected_sha256: str
    ) -> dict[str, Any]:
        repair = dict(details)
        repair["nextTools"] = ["read_script", "edit_script", "run_script"]
        try:
            raw = await self.workspace.read_limited_regular_file(
                self.context.task_id,
                self.context.script_path,
                max_bytes=self.context.max_source_bytes,
            )
            source = raw.decode("utf-8")
        except (WorkspaceError, UnicodeDecodeError):
            return repair
        current_sha256 = hashlib.sha256(raw).hexdigest()
        if current_sha256 != expected_sha256:
            return repair

        error_line: int | None = None
        traceback_lines: list[int] = []
        script_path = self.context.script_path.replace("\\", "/")
        # 子进程 stderr 优先；类型与源码帧必须来自同一份诊断，不能混入外层 wrapper。
        for field in ("stderr", "traceback"):
            value = repair.get(field)
            if not isinstance(value, str):
                continue
            for match in re.finditer(r'File ["\']([^"\']+)["\'], line (\d+)', value):
                reported_path = match.group(1).replace("\\", "/")
                if reported_path == script_path or reported_path.endswith(f"/{script_path}"):
                    traceback_lines.append(int(match.group(2)))
            matches = re.findall(
                r"(?m)^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit))(?::|$)",
                value,
            )
            if matches:
                repair["errorType"] = matches[-1].rsplit(".", 1)[-1]
            if matches or traceback_lines:
                break

        if traceback_lines:
            # 最内层本文件帧才是实际报错位置；上层可能只是 main 调用入口。
            error_line = traceback_lines[-1]

        if error_line is None:
            related_path = repair.get("path")
            if isinstance(related_path, str) and related_path:
                matching_lines = [
                    index
                    for index, line in enumerate(source.splitlines(), 1)
                    if related_path in line
                ]
                if len(matching_lines) == 1:
                    error_line = matching_lines[0]

        repair["sourceSha256"] = current_sha256
        if error_line is None:
            return repair
        lines = source.splitlines(keepends=True)
        if not 1 <= error_line <= len(lines):
            return repair
        start_line = max(1, error_line - 12)
        end_line = min(len(lines), error_line + 12)
        region_start, region_end = start_line, end_line
        try:
            functions = [
                node for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.end_lineno is not None
                and node.lineno <= error_line <= node.end_lineno
            ]
        except SyntaxError:
            functions = []
        if functions:
            function = max(functions, key=lambda node: node.lineno)
            region_start, region_end = function.lineno, function.end_lineno
            assert region_end is not None
            function_source = "".join(lines[region_start - 1:region_end])
            if len(function_source.encode("utf-8")) <= 1800:
                start_line, end_line = region_start, region_end
            else:
                start_line = max(start_line, region_start)
                end_line = min(end_line, region_end)
        while len("".join(lines[start_line - 1:end_line]).encode("utf-8")) > 1800:
            if start_line == end_line:
                return repair
            if error_line - start_line >= end_line - error_line:
                start_line += 1
            else:
                end_line -= 1
        repair.update(
            {
                "sourceExcerpt": "".join(lines[start_line - 1:end_line]),
                "sourceStartLine": start_line,
                "sourceEndLine": end_line,
                "errorLine": error_line,
                "allowedEditRegion": {
                    "path": self.context.script_path,
                    "startLine": region_start,
                    "endLine": region_end,
                },
                "forbiddenEditRegions": [
                    {
                        "path": self.context.script_path,
                        "outside": {
                            "startLine": 1,
                            "endLine": len(lines),
                            "allowedStartLine": region_start,
                            "allowedEndLine": region_end,
                        },
                    }
                ],
                "nextTools": ["edit_script", "run_script"],
            }
        )
        if start_line > region_start or end_line < region_end:
            repair["readRange"] = dict(repair["allowedEditRegion"])
            repair["nextTools"] = ["read_script", "edit_script", "run_script"]
        return repair

    def _record_tool_start(self, fc: Any) -> None:
        if fc.function.name == "submit_script":
            _reset_stop_after_tool_call(fc)
        log_tool_event(
            session_id=self.context.code_mode_session_id,
            call_id=fc.call_id, tool=fc.function.name,
            status="started", payload=fc.arguments,
        )

    async def _record_tool_result(self, fc: Any) -> None:
        try:
            await self._update_tool_result(fc)
        finally:
            await self.refresh_delivery_state()

    async def refresh_delivery_state(self) -> None:
        self._delivery_state = await build_delivery_state(self)

    def delivery_state(self) -> dict[str, Any]:
        return deepcopy(self._delivery_state)

    def tool_call_metrics(self) -> dict[str, int]:
        """返回本次 Coding task 各工具的实际完成次数。"""
        return dict(sorted(self._tool_call_counts.items()))

    async def _record_failure_artifact(self, details: Mapping[str, Any]) -> None:
        if self.failure_artifact_recorder is None:
            return
        try:
            raw = await self.workspace.read_limited_regular_file(
                self.context.task_id, self.context.script_path,
                max_bytes=self.context.max_source_bytes,
            )
            digest = hashlib.sha256(raw).hexdigest()
            if digest != details.get("sourceSha256"):
                return
            # 审计源码只交给宿主回调，不进入工具回执、模型上下文或常规指标。
            self.failure_artifact_recorder({
                "taskId": self.context.task_id,
                "scriptPath": self.context.script_path,
                "sourceSha256": digest,
                "sourceBytes": len(raw),
                "source": raw.decode("utf-8"),
                "code": self.first_run_failure_code,
                "diagnostic": _safe_diagnostic_details(details),
            })
        except Exception as error:
            logger.warning(
                "report_code_failure_artifact_record_failed task_id={} error_type={}",
                self.context.task_id, type(error).__name__,
            )

    async def _update_tool_result(self, fc: Any) -> None:
        """使用 Agno 原生 hook 观测实际调用；未执行的批次回执不会覆盖根因。"""
        name = fc.function.name
        if fc.result is None and not fc.error:
            # Agno 在取消的 finally 中也调用 post-hook，缺失结果不能记为成功。
            log_tool_event(
                session_id=self.context.code_mode_session_id,
                call_id=fc.call_id, tool=name, status="cancelled", payload={},
            )
            return
        self.last_tool = name
        self.completed_tool_calls += 1
        self._tool_call_counts[name] = self._tool_call_counts.get(name, 0) + 1
        if name == "submit_script":
            _stop_after_success(fc)
        result = fc.result
        if isinstance(result, Mapping) and isinstance(result.get("outputValidation"), Mapping):
            result = result["outputValidation"]
        failed = bool(fc.error or (isinstance(result, Mapping) and result.get("ok") is False))
        if name == "write_script" and self.first_script_success == "unknown":
            self.first_script_success = not failed
            if failed:
                code = result.get("code") if isinstance(result, Mapping) else None
                self.first_script_failure_code = (
                    code[:128] if isinstance(code, str) and code else "tool_error"
                )
        if name == "run_script" and self.first_run_success == "unknown":
            self.first_run_success = not failed
            if failed:
                code = result.get("code") if isinstance(result, Mapping) else None
                self.first_run_failure_code = (
                    code[:128] if isinstance(code, str) and code else "tool_error"
                )
                details = result.get("details") if isinstance(result, Mapping) else None
                if isinstance(details, Mapping):
                    source_sha = details.get("sourceSha256")
                    self.first_run_failure = {
                        "code": self.first_run_failure_code,
                        "errorType": details.get("errorType", "unknown"),
                        "path": details.get("path", self.context.script_path),
                        "errorLine": details.get("errorLine"),
                        "exitCode": details.get("exitCode"),
                        "sourceSha256": source_sha
                        if isinstance(source_sha, str)
                        else "unknown",
                        "detailsBytes": len(
                            json.dumps(details, ensure_ascii=False, separators=(",", ":"))
                            .encode("utf-8")
                        ),
                    }
                    await self._record_failure_artifact(details)
        if name == "edit_script" and self.first_patch_applied == "unknown":
            self.first_patch_applied = not failed
        if name == "edit_script" and not failed and self.first_repair_success == "unknown":
            if self._awaiting_first_repair_run:
                self.first_repair_success = False
                self._awaiting_first_repair_run = False
            unresolved_tool_failure = bool(
                self.last_failure
                and not self.last_failure["resolved"]
                and self.last_failure["tool"] in {"write_script", "run_script"}
            )
            if self.first_repair_success == "unknown":
                self._awaiting_first_repair_run = bool(
                    unresolved_tool_failure
                    or self._delivery_state.get("outputValidation") == "failed"
                    or self._delivery_state.get("visualFailures")
                    or "edit_script" in self._delivery_state.get("nextTools", ())
                )
        if (
            name == "run_script"
            and self._awaiting_first_repair_run
            and self.first_repair_success == "unknown"
        ):
            if failed:
                self.first_repair_success = False
                self._awaiting_first_repair_run = False
        if (
            name == "view_image"
            and self._awaiting_first_repair_run
            and isinstance(fc.result, Mapping)
            and isinstance(fc.result.get("receipt"), Mapping)
            and (
                fc.result["receipt"].get("requiresRevision") is True
                or fc.result["receipt"].get("requires_revision") is True
            )
        ):
            self.first_repair_success = False
            self._awaiting_first_repair_run = False
        if (
            name == "submit_script"
            and self._awaiting_first_repair_run
            and not failed
            and self.first_repair_success == "unknown"
        ):
            self.first_repair_success = True
            self._awaiting_first_repair_run = False
        log_tool_event(
            session_id=self.context.code_mode_session_id,
            call_id=fc.call_id, tool=name,
            status="failed" if failed else "completed",
            payload={"result": fc.result, "error": fc.error},
        )
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
            if failure["code"] == "report_code_input_wrapped":
                # 草稿未写入时 sourceSha256 不变；必须比较本次输入，避免把修订误判为原样重试。
                input_text = json.dumps(fc.arguments, ensure_ascii=False, sort_keys=True)
                signature += hashlib.sha256(input_text.encode("utf-8")).hexdigest()
            self._repeated_failure_count = (
                self._repeated_failure_count + 1 if signature == self._failure_signature else 1
            )
            self._failure_signature = signature
            self.last_failure = {**failure, "resolved": False}
            if failure["code"] == "report_code_input_wrapped" and isinstance(result, dict):
                result["repairHint"] = (
                    f"重新调用 {name}，input 第一行写 # Python，真实换行后填写源码。"
                    "不要填写 JSON 对象或字符串引号。服务不会自动解包执行。"
                )
                result["rawInputExample"] = "# Python\nprint(1)\n"
                # 相同包装输入第二次出现时结束本次 Agent run，由 Workflow 的有限重试处理。
                # 再发起一次相同模型请求不会改变输入形状，只会浪费请求额度。
                # 不用异常中断 Agno，保证原调用以及同批剩余调用的回执完整。
                if self._repeated_failure_count >= 2:
                    self.terminal_failure = ReportingError(
                        "report_code_input_wrapped",
                        "相同代码包装输入连续两次被拒绝，已停止本次 Coding Agent。",
                        details={
                            "recovery": "retry_then_degrade",
                            "stopReason": "repeated_identical_input",
                        },
                    )
                    fc.function.stop_after_tool_call = True
            if self._repeated_failure_count > 1 and isinstance(result, dict):
                result["repeatedFailureCount"] = self._repeated_failure_count
                result.setdefault("repairHint", "相同源码再次出现相同错误；请检查输入与环境，并调整修复方法。")
                logger.warning(
                    "report_code_repeated_failure tool={} code={} count={}",
                    name, failure["code"], self._repeated_failure_count,
                )
        elif isinstance(result, Mapping) and result.get("ok") is True:
            if self.last_failure is not None and self.last_failure["tool"] == name:
                self.last_failure = {**self.last_failure, "resolved": True}
                self._failure_signature = None
                self._repeated_failure_count = 0
                terminal = self.terminal_failure
                if (
                    terminal is not None
                    and terminal.code == "report_code_input_wrapped"
                    and terminal.details.get("stopReason") == "repeated_identical_input"
                ):
                    self.terminal_failure = None
                    _reset_stop_after_tool_call(fc)

    async def submission_diagnostic(self) -> dict[str, Any]:
        receipt = self.binding.execution_receipt
        return {
            "lastTool": self.last_tool,
            "lastFailure": self.last_failure,
            "sourceSha256": await self._source_sha256(),
            "hasExecutionReceipt": receipt is not None,
            "completedToolCalls": self.completed_tool_calls,
            "pendingOutputValidation": self.pending_output_validation,
            "unreviewedOutputPaths": [
                item.path for item in (receipt.output_files if receipt else ())
                if self.context.task_kind == "visualization"
                and not item.path.endswith(".plotly.json")
                and (
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
    def pending_output_validation(self) -> dict[str, Any] | None:
        """预检结论只对签发它的执行有效；当前执行缺少通过结论时阻塞提交。"""

        receipt = self.binding.execution_receipt
        if receipt is None:
            return None
        validation = self.binding.output_validation
        diagnostic = validation.current_diagnostic(receipt.run_id)
        if diagnostic is not None:
            return diagnostic
        if self.output_preflight is None or (
            validation.status == "passed" and validation.run_id == receipt.run_id
        ):
            return None
        return _failure(
            str(OUTPUT_VALIDATION_UNAVAILABLE["code"]),
            str(OUTPUT_VALIDATION_UNAVAILABLE["message"]),
            {
                "status": validation.status,
                "validationRunId": validation.run_id,
                "executionRunId": receipt.run_id,
            },
        )

    def _set_output_validation(
        self,
        status: OutputValidationStatus,
        *,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> None:
        receipt = self.binding.execution_receipt
        self.binding.output_validation = OutputValidationState.for_run(
            status,
            receipt.run_id if receipt is not None else None,
            diagnostic,
        )

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

    async def read_script(
        self, path: str | None = None, run_context: RunContext | None = None,
        start_line: int | None = None, end_line: int | None = None,
    ) -> dict[str, Any]:
        del run_context
        if path is not None:
            return _failure(
                "report_code_script_path_forbidden",
                "脚本路径由当前任务绑定，read_script 不接受 path 参数。",
                {"nextTools": ["read_script"]},
            )
        if (
            any(value is not None and (type(value) is not int or value < 1)
                for value in (start_line, end_line))
            or (start_line is not None and end_line is not None and start_line > end_line)
        ):
            return _failure(
                "report_code_script_range_invalid",
                "行号必须为从 1 开始的整数，start_line 不得大于 end_line。",
                {"nextTools": ["read_script"]},
            )
        if not await self.workspace.apath_exists(self.context.task_id, self.context.script_path):
            return {
                "ok": True,
                "exists": False,
                "path": self.context.script_path,
                "details": {"nextTools": ["write_script"]},
            }
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
        # 只按 LF 分行，保留 CRLF 和块内其他字符，不修改用于补丁匹配的文本。
        lines = source.split("\n")
        lines = [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
        total_lines = len(lines)
        first = start_line if start_line is not None else 1
        if first > max(1, total_lines):
            return _failure(
                "report_code_script_range_invalid",
                "start_line 超出脚本末尾。",
                {"totalLines": total_lines, "nextTools": ["read_script"]},
            )
        last = min(end_line if end_line is not None else total_lines, total_lines)
        return {
            "ok": True,
            "exists": True,
            "path": self.context.script_path,
            "source": "".join(lines[first - 1:last]),
            "totalLines": total_lines,
            "startLine": first if total_lines else None,
            "endLine": last if total_lines else None,
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
        warnings: list[dict[str, str]] = []
        formatted = False
        try:
            source = validate_draft_source(self.context, source).decode("utf-8")
            try:
                tree = ast.parse(source, filename=self.context.script_path)
            except SyntaxError:
                # 草稿允许暂时存在语法错误，供 LSP 和后续修复使用。
                tree = None
                warnings.append(
                    {
                        "code": "report_code_formatting_skipped",
                        "reason": "syntax_error",
                        "message": "草稿存在语法错误，已保留原稿并跳过格式化。",
                    }
                )
            if tree is not None:
                _reject_code_envelope(tree, "write_script")
                _reject_embedded_data(tree)
                # 与 run_script 同一路径策略：draft 阶段即拒绝，避免"保存成功
                # → 执行被拒"浪费一整个写-跑循环后模型重试退化。
                _reject_unauthorized_paths(
                    tree,
                    self.context.script_path,
                    frozenset((*self.context.authorized_read_paths, *self.context.authorized_write_paths)),
                )
        except ReportingError as error:
            return _failure(error.code, error.message, error.details)
        if tree is not None:
            try:
                candidate = await format_python_source(source)
                candidate = validate_draft_source(self.context, candidate).decode("utf-8")
                candidate_tree = ast.parse(candidate, filename=self.context.script_path)
                if ast.dump(tree) != ast.dump(candidate_tree):
                    raise ValueError("格式化结果改变了源码 AST。")
                _reject_embedded_data(candidate_tree)
            except (
                OSError,
                subprocess.SubprocessError,
                ValueError,
                SyntaxError,
                ReportingError,
            ) as error:
                warnings.append(
                    {
                        "code": "report_code_formatting_failed",
                        "reason": type(error).__name__,
                        "message": "本地格式化未成功，已保留原稿；可继续诊断和运行。",
                    }
                )
            else:
                formatted = candidate != source
                source = candidate
        for warning in warnings:
            logger.warning(
                "report_code_formatting task_id={} code={} reason={}",
                self.context.task_id,
                warning["code"],
                warning["reason"],
            )
        exists = await self.workspace.apath_exists(self.context.task_id, self.context.script_path)
        await self.workspace.awrite_text(
            self.context.task_id,
            self.context.script_path,
            source,
            overwrite=exists,
        )
        self.binding.clear_execution_receipt()
        self.submitted_receipt = None
        identity = await self.workspace.ahash_file(
            self.context.task_id, self.context.script_path
        )
        return {
            "ok": True,
            "formatted": formatted,
            "readyForExecution": tree is not None,
            "warnings": warnings,
            # Ruff 可能改变换行和缩进；返回实际落盘文本，确保下一轮 edit_script
            # 基于当前源码生成 SEARCH，而不是基于模型最初提交的旧文本。
            "savedSource": source if formatted else None,
            "sourceSha256": identity["sha256"],
            "sourceBytes": identity["size"],
            "changeSummary": {
                "kind": "write",
                "formatted": formatted,
                "bytes": identity["size"],
            },
            **identity,
        }

    async def edit_script(
        self,
        patch: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """按 CodingTools 精确匹配语义，统一校验多个局部修改后原子提交。"""
        del run_context
        try:
            edits, expectedSourceSha256 = parse_edit_patch(
                patch, self.context.max_source_bytes,
            )
        except ReportingError as error:
            return _failure(error.code, error.message, error.details)
        try:
            source_bytes = await self.workspace.read_limited_regular_file(
                self.context.task_id,
                self.context.script_path,
                max_bytes=self.context.max_source_bytes,
            )
            source = source_bytes.decode("utf-8")
        except (WorkspaceError, UnicodeDecodeError) as error:
            return _failure(
                "report_code_script_edit_source_unavailable",
                "当前绑定脚本不可读取，请先调用 read_script。",
                {"nextTools": ["read_script"], "errorType": type(error).__name__},
            )
        # 哈希和匹配必须基于同一份读取内容，避免独立 hash/read 之间的竞态。
        current_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if expectedSourceSha256 != current_sha256:
            return _failure(
                "report_code_script_edit_conflict",
                "脚本在读取后已发生变化，请重新读取后再编辑。",
                {
                    "currentSha256": current_sha256,
                    "expectedSha256": expectedSourceSha256,
                    "action": "read_script",
                    "readRange": {"path": self.context.script_path, "startLine": 1},
                    "nextTools": ["read_script", "edit_script"],
                },
            )
        try:
            updated = apply_edit_blocks(source, edits)
        except ReportingError as error:
            return _failure(error.code, error.message, error.details)
        try:
            validate_draft_source(self.context, updated)
            tree = ast.parse(updated, filename=self.context.script_path)
        except SyntaxError:
            tree = None
        except ReportingError as error:
            return _failure(error.code, error.message, error.details)
        if tree is not None:
            try:
                _reject_code_envelope(tree, "edit_script")
                _reject_embedded_data(tree)
                _reject_unauthorized_paths(
                    tree,
                    self.context.script_path,
                    frozenset((*self.context.authorized_read_paths, *self.context.authorized_write_paths)),
                )
            except ReportingError as error:
                return _failure(error.code, error.message, error.details)
        try:
            await self.workspace.awrite_text(
                self.context.task_id,
                self.context.script_path,
                updated,
                overwrite=True,
                expected_sha256=current_sha256,
            )
        except WorkspaceError as error:
            return _failure(
                "report_code_script_edit_conflict",
                "脚本在编辑提交前已发生变化，请重新读取后再编辑。",
                {"nextTools": ["read_script", "edit_script"], "errorType": type(error).__name__},
            )
        self.binding.clear_execution_receipt()
        self.submitted_receipt = None
        identity = await self.workspace.ahash_file(
            self.context.task_id, self.context.script_path
        )
        if self.first_patch_applied == "unknown":
            self.first_patch_applied = True
        return {
            "ok": True,
            "status": "edited",
            "path": self.context.script_path,
            "replacedOccurrences": len(edits),
            "sourceSha256": identity["sha256"],
            "sourceBytes": identity["size"],
            "changeSummary": {
                "kind": "edit",
                "replacedOccurrences": len(edits),
            },
            **identity,
        }

    async def run(
        self, code: str, run_context: RunContext | None = None
    ) -> dict[str, Any]:
        del run_context
        try:
            try:
                tree = ast.parse(code)
            except SyntaxError:
                # IPython magic / Shell cell 及语法诊断继续交给 Agno CodeMode。
                pass
            else:
                _reject_code_envelope(tree, "run")
            cell = await self.runtime.execute(
                self.context.code_mode_session_id,
                self.workspace,
                code,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
        except ReportingError as error:
            details = dict(error.details) if isinstance(error.details, Mapping) else {}
            if details.get("errorType") == "KernelBusyError":
                details["nextTools"] = ["restart_code_mode"]
                return _failure(error.code, error.message, details)
            exploration_variables = await self._exploration_variables()
            if exploration_variables is not None:
                details["explorationVariables"] = exploration_variables
            if "nextTools" not in details:
                details["nextTools"] = ["read_script", "edit_script", "run_script"]
                try:
                    if not await self.workspace.apath_exists(self.context.task_id, self.context.script_path):
                        details["nextTools"] = ["write_script"]
                except WorkspaceError:
                    pass
            return _failure(error.code, error.message, details)
        if _cell_field(cell, "status") != "ok":
            if _cell_field(cell, "status") == "aborted":
                return _bounded_failure(
                    "report_code_mode_execution_failed",
                    cell,
                    next_tools=["restart_code_mode"],
                )
            exploration_variables = await self._exploration_variables()
            return _bounded_failure(
                "report_code_mode_execution_failed",
                cell,
                exploration_variables=exploration_variables,
            )
        exploration_variables = await self._exploration_variables()
        outputs = {
            name: str(_cell_field(cell, name, "") or "")
            for name in ("result", "stderr", "stdout")
        }
        diagnostics: dict[str, Any] = dict(outputs)
        if exploration_variables is not None:
            diagnostics["explorationVariables"] = exploration_variables
        bounded = _safe_diagnostic_details(diagnostics)
        truncated = set(_cell_field(cell, "truncated", ()) or ()) & outputs.keys()
        truncated.update(name for name, value in outputs.items() if bounded.get(name, "") != value)
        return {
            "ok": True,
            "status": "completed",
            **bounded,
            "truncated": sorted(truncated),
        }

    async def _exploration_variables(self) -> dict[str, str] | None:
        getter = getattr(self.runtime, "exploration_variables", None)
        if not callable(getter):
            return None
        try:
            variables = await getter(self.context.code_mode_session_id)
        except Exception as error:
            logger.warning(
                "report_code_exploration_variables_failed session_id={} error_type={}",
                self.context.code_mode_session_id,
                type(error).__name__,
            )
            return None
        return _bounded_exploration_variables(variables)

    async def restart_code_mode(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        self.binding.clear_execution_receipt()
        self.submitted_receipt = None
        await self.runtime.shutdown(self.context.code_mode_session_id)
        return {
            "ok": True,
            "explorationVariables": {},
            "variablesCleared": True,
        }

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
                "receipt": _visual_review_model_receipt(cached),
            }
        if self.vision_reviewer is None:
            return _failure(
                "report_code_visual_review_unavailable",
                "独立视觉审查暂不可用，请稍后重试。",
            )
        review_started_at = perf_counter()
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
        finally:
            self.visual_review_duration_ms += max(
                0, round((perf_counter() - review_started_at) * 1000)
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
            "receipt": _visual_review_model_receipt(reviewed),
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
        try:
            source_before = await self._validated_source_identity()
            await self._clear_declared_outputs()
            process = await self.runtime.execute_script_process(
                self.context.code_mode_session_id,
                self.workspace,
                self.context.script_path,
                matplotlib_agg=self.context.task_kind == "visualization",
            )
            if not isinstance(process, ScriptProcessResult):
                return _failure(
                    "report_code_exit_receipt_invalid",
                    "Coding Agent 脚本退出码回执缺失或无效。",
                    {"nextTools": ["read_script", "edit_script", "run_script"]},
                )
            cell, exit_code = process.cell, process.exit_code
            if _cell_field(cell, "status") != "ok" or exit_code not in (None, 0):
                details: dict[str, Any] = {
                    name: str(_cell_field(cell, name, "") or "")
                    for name in ("traceback", "stderr", "stdout")
                }
                variable_summary = _cell_field(cell, "variableSummary")
                details["variableSummary"] = (
                    variable_summary
                    if isinstance(variable_summary, Mapping)
                    else {"status": "unknown", "reason": "runtime_did_not_expose_locals"}
                )
                details["exitCode"] = exit_code
                return _failure(
                    "report_code_mode_execution_failed",
                    "Coding Agent 脚本子进程未正常退出。",
                    await self._script_repair_details(details, source_before.sha256),
                )
            if exit_code is None:
                return _failure(
                    "report_code_exit_receipt_invalid",
                    "Coding Agent 脚本退出码回执缺失或无效。",
                    {"nextTools": ["read_script", "edit_script", "run_script"]},
                )
            source_after = await self._validated_source_identity()
            if source_after != source_before:
                return _failure(
                    "report_code_script_modified_during_execution",
                    "脚本在执行期间发生变化。",
                    {"nextTools": ["read_script", "edit_script", "run_script"]},
                )
            try:
                outputs = await self._declared_output_identities()
            except ReportingError as error:
                # 交付校验失败也保留进程执行证据，供下一轮直接修复。
                outputs_text = {
                    name: str(_cell_field(cell, name, "") or "")
                    for name in ("stdout", "stderr")
                }
                details = dict(error.details) if isinstance(error.details, Mapping) else {}
                variable_summary = _cell_field(cell, "variableSummary")
                details.setdefault(
                    "variableSummary",
                    variable_summary
                    if isinstance(variable_summary, Mapping)
                    else {"status": "unknown", "reason": "runtime_did_not_expose_locals"},
                )
                details.update(outputs_text)
                details["exitCode"] = exit_code
                details = await self._script_repair_details(details, source_before.sha256)
                result = _failure(error.code, error.message, details)
                truncated = set(_cell_field(cell, "truncated", ()) or ()) & outputs_text.keys()
                truncated.update(
                    name for name, value in outputs_text.items()
                    if result["details"].get(name, "") != value
                )
                result["truncated"] = sorted(truncated)
                return result
        except WorkspaceError:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
                {"nextTools": ["write_script"]},
            )
        except ReportingError as error:
            details = dict(error.details) if isinstance(error.details, Mapping) else {}
            details.setdefault("nextTools", ["read_script", "edit_script", "run_script"])
            return _failure(error.code, error.message, details)
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
        if self.output_preflight is None:
            self._set_output_validation("not_required")
        else:
            # 预检本身失败时不能默认放行：未获得结论等于未通过，必须阻塞提交。
            self._set_output_validation("checking")
            try:
                diagnostic = await self.output_preflight(receipt)
            except Exception as error:  # noqa: BLE001 - 预检异常必须降级为阻塞状态
                self._set_output_validation(
                    "unavailable",
                    diagnostic=_failure(
                        str(OUTPUT_VALIDATION_UNAVAILABLE["code"]),
                        str(OUTPUT_VALIDATION_UNAVAILABLE["message"]),
                        {
                            "errorType": type(error).__name__,
                            "reason": str(error)[:512],
                        },
                    ),
                )
                logger.warning(
                    "report_code_output_preflight_failed error_type={}",
                    type(error).__name__,
                )
                # 即使预检自身异常，产物身份门禁仍优先；不得把篡改降级成
                # 可重试的 validation unavailable。
                await self.require_current_receipt(receipt)
                result["outputValidation"] = self.pending_output_validation
                result["ok"] = False
                result["nextTools"] = ["read_script", "edit_script", "run_script"]
                result["repairHint"] = "输出结构预检不可用，请重新执行脚本；最终验收由 Workflow 处理。"
                return result
            await self.require_current_receipt(receipt)
            if diagnostic is not None:
                self._set_output_validation(
                    "failed",
                    diagnostic=_failure(
                        str(diagnostic["code"]),
                        str(diagnostic["message"]),
                        diagnostic.get("details"),
                    ),
                )
                result["outputValidation"] = self.pending_output_validation
                result["ok"] = False
                result["nextTools"] = ["read_script", "edit_script", "run_script"]
                result["repairHint"] = "输出结构校验未通过，请修复后重新执行；最终验收与降级由 Workflow 处理。"
            else:
                self._set_output_validation("passed")
        return result

    async def submit_script(self, run_context: RunContext | None = None) -> dict[str, Any]:
        del run_context
        receipt = self.binding.execution_receipt
        if receipt is None:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
                {"nextTools": ["run_script"]},
            )
        blocking = self.pending_output_validation
        if blocking is not None:
            return _failure(
                "report_code_output_validation_pending",
                "最近一次执行的输出结构校验未通过；请修复并重新执行后再提交。",
                {
                    **(blocking.get("details") or {}),
                    "nextTools": ["read_script", "edit_script", "run_script"],
                },
            )
        try:
            source = await self._validated_source_identity()
            outputs = await self._declared_output_identities()
        except WorkspaceError:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
                {"path": self.context.script_path, "nextTools": ["write_script"]},
            )
        except ReportingError as error:
            details = dict(error.details) if isinstance(error.details, Mapping) else {}
            details.setdefault("nextTools", ["read_script", "edit_script", "run_script"])
            return _failure(
                error.code,
                error.message,
                details,
            )
        if source != receipt.source_file:
            return _failure(
                "report_code_submission_not_executed",
                "当前脚本内容尚未成功执行。",
                {"nextTools": ["read_script", "edit_script", "run_script"]},
            )
        if outputs != receipt.output_files:
            return _failure(
                "report_code_output_modified_after_execution",
                "脚本输出在执行后发生变化。",
                {"nextTools": ["read_script", "edit_script", "run_script"]},
            )
        if self.context.task_kind == "visualization":
            output_by_path = {
                item.path: item
                for item in receipt.output_files
                if not item.path.endswith(".plotly.json")
            }
            reviews = self.binding.visual_inspection_receipts
            if set(reviews) != set(output_by_path):
                return _failure(
                    "report_code_visual_review_required",
                    "每个当前图片输出都必须完成独立视觉审查。",
                    {"nextTools": ["view_image"]},
                )
            for path, output in output_by_path.items():
                reviewed = reviews[path]
                if reviewed.source_path != path:
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                        {"nextTools": ["view_image"]},
                    )
                if reviewed.sha256 != output.sha256:
                    return _failure(
                        "report_code_visual_output_changed",
                        "图片输出在执行或视觉审查后发生变化。",
                        {"nextTools": ["run_script", "view_image"]},
                    )
                if not reviewed.reviewed or reviewed.visual_review_status != "passed":
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                        {"nextTools": ["view_image"]},
                    )
                if reviewed.requires_revision:
                    return _failure(
                        "report_code_visual_revision_required",
                        "独立视觉审查要求修订当前图片输出。",
                        {"nextTools": ["read_script", "edit_script", "run_script"]},
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
