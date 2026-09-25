"""交互式 Coding Agent 的 Workspace 与执行身份工具。"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any, NoReturn
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Function, Toolkit
from loguru import logger

from ...code_monitor.tools import log_tool_event
from ...workspace import WorkspaceError, WorkspaceService
from ..code_mode import ReportingCodeModeRuntime, ScriptProcessResult
from ..contract import interactive_spec_path
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
from .delivery import (
    SOURCE_EXCERPT_MAX_BYTES,
    _visual_review_model_receipt,
    build_delivery_state,
)
from .edit_patch import apply_edit_blocks, parse_script_patch
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
_PATH_ARGUMENT_CALLS = frozenset(
    {"open", "io.open", "os.makedirs", "os.mkdir", "pathlib.Path", "plotly.offline.plot"}
)
_PATH_ARGUMENT_METHODS = frozenset(
    {
        # Plotly 写出（fig.write_image(path) / pio.write_image(fig, path)）；
        # 不含 write_text/write_bytes：pathlib 这两个方法的首参是内容而非路径。
        "write_html",
        "write_image",
        "write_json",
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

# 占位脚本（零产物探索脚本）的启发式标识：遍历文件系统、打印 facts/supplement 结构，
# 且不包含任何产物写出调用。检测到后应在 declared_output_missing 时直接打开重写闸门。
_PLACEHOLDER_EXPLORATION_CALLS = frozenset(
    {
        "os.walk",
        "os.listdir",
        "os.scandir",
        "glob.glob",
        "glob.iglob",
        "pathlib.Path.cwd",
        "os.getcwd",
    }
)
_PLACEHOLDER_OUTPUT_METHODS = frozenset(
    {
        "savefig",
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_pickle",
        "write_text",
        "write_bytes",
        "write_image",
        "write_html",
        "write_json",
    }
)
_PLACEHOLDER_OUTPUT_CALLS = frozenset(
    {
        "plotly.offline.plot",
        "plotly.io.write_image",
        "plotly.io.write_html",
        "plotly.io.write_json",
    }
)

# 声明产物写出调用的静态识别（write_script/edit_script 结构预检与软告警共用）。
_OUTPUT_WRITE_METHODS = _PLACEHOLDER_OUTPUT_METHODS
_OUTPUT_WRITE_CALLS = _PLACEHOLDER_OUTPUT_CALLS
# 这些方法名在 pathlib/plotly 中都出现，但路径位置不同：
# Path("charts/a.png").write_bytes(...) 的路径在 receiver 上；
# fig.write_image("charts/a.png") 的路径在第一个位置参数上。
# 静态分析无法区分 receiver 是 Path 还是 Figure，两个位置都尝试解析。
_PATH_OWNER_WRITE_METHODS = frozenset(
    {"write_text", "write_bytes", "write_image", "write_html", "write_json"}
)
_DECLARED_OUTPUT_REVIEW_CHUNK_SIZE = 5

# 本地图片检查（文件缺失、解码失败、空白）的拒绝码：属于脚本产物问题，
# 由模型修复，不重试视觉审查，也不判为审查不可用。
_LOCAL_CHART_REJECTION_CODES = frozenset(
    {"report_chart_file_missing", "report_chart_source_invalid", "report_chart_blank"}
)

# 连续局部编辑失败且无成功运行达到该阈值时，交付状态放行一次 write_script
# 整段重写（真实回放 candidate-3：占位脚本 + 禁止重写 = 预算空转死局）。
REWRITE_GATE_EDIT_FAILURES = 2
# 对齐 codex 熔断语义：连续（非累计）要求修订的视觉审查轮次达到该阈值时，
# 剩余 critical 问题降级为软告警并收敛到 submit_script，避免视觉修复循环耗尽预算。
VISUALIZATION_CRITICAL_REVIEW_ROUNDS_LIMIT = 3


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


# 路径不在首个位置参数的调用：plotly.io 模块级写出函数签名为 (fig, path)。
_PATH_ARGUMENT_POSITION = {
    "plotly.io.write_image": 1,
    "plotly.io.write_json": 1,
    "plotly.io.write_html": 1,
}


def _call_path_arguments(call: ast.Call, qualified_name: str) -> list[ast.AST]:
    """调用中承载路径的实参：按签名取位置参数，并加上路径关键字参数。"""

    position = _PATH_ARGUMENT_POSITION.get(qualified_name, 0)
    arguments = list(call.args[position:position + 1])
    arguments.extend(
        keyword.value for keyword in call.keywords if keyword.arg in _PATH_ARGUMENT_KEYWORDS
    )
    return arguments


def _path_arguments(call: ast.Call, qualified_name: str) -> tuple[ast.AST, ...]:
    method_name = qualified_name.rsplit(".", 1)[-1]
    if qualified_name not in _PATH_ARGUMENT_CALLS and method_name not in _PATH_ARGUMENT_METHODS:
        return ()
    return tuple(_call_path_arguments(call, qualified_name))


def _normalize_literal_path(value: str) -> str:
    """只消除与签发相对路径无歧义等价的写法：前导 ./、重复斜杠与中间的 /./。

    脚本在工作区根执行，"./analysis/out.json" 与签发的 "analysis/out.json" 是同一
    文件；绝对路径、反斜杠与 .. 保持原样，由白名单继续拒绝。
    """

    if not value or value.startswith("/") or "\\" in value:
        return value
    parts = [part for part in value.split("/") if part not in {"", "."}]
    return "/".join(parts) if parts else value


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
                paths.add(_normalize_literal_path(literal))
    return paths


def _resolved_path_literal(
    node: ast.AST,
    aliases: Mapping[str, str],
    bindings: Mapping[str, str] | Mapping[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _resolved_path_literal(
            bindings[node.id], aliases, bindings, seen | {node.id}
        )
    literal = _literal_string(node, bindings)
    if literal is not None:
        return _normalize_literal_path(literal)
    if isinstance(node, ast.Call):
        qualified_name = _qualified_name(node.func, aliases)
        if qualified_name == "pathlib.Path" and node.args:
            first = _literal_string(node.args[0], bindings)
            return _normalize_literal_path(first) if first is not None else None
        if qualified_name == "os.path.join" and not node.keywords:
            parts = [_literal_string(argument, bindings) for argument in node.args]
            if parts and all(part is not None for part in parts):
                return _normalize_literal_path(os.path.join(*parts))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        # pathlib 斜杠拼接：Path("charts") / "a.png"；左侧是 os.path.join
        # 解析出的 POSIX 路径时也按同风格拼接。
        left = _resolved_path_literal(node.left, aliases, bindings, seen)
        right = _literal_string(node.right, bindings)
        if left is not None and right is not None:
            return _normalize_literal_path(f"{left.rstrip('/')}/{right}")
    return None


def _all_referenced_literal_paths(tree: ast.AST) -> set[str]:
    paths = _referenced_literal_paths(tree)
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _qualified_name(node.func, aliases) != "os.path.join":
            continue
        parts = [_literal_string(argument, bindings) for argument in node.args]
        if parts and all(part is not None for part in parts):
            paths.add(_normalize_literal_path(os.path.join(*parts)))
    return paths


def _declared_output_literals(tree: ast.AST, declared_paths: frozenset[str]) -> set[str]:
    literals = {
        _normalize_literal_path(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    literals |= _all_referenced_literal_paths(tree)
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            resolved = _resolved_path_literal(node, aliases, bindings)
            if resolved is not None:
                literals.add(resolved)
    return literals & set(declared_paths)


def _declared_output_write_paths(tree: ast.AST, declared_paths: frozenset[str]) -> set[str]:
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified_name = _qualified_name(node.func, aliases)
        if qualified_name is None:
            continue
        method_name = qualified_name.rsplit(".", 1)[-1]
        path_node: ast.AST | None = None
        if qualified_name in _OUTPUT_WRITE_CALLS or method_name in _OUTPUT_WRITE_METHODS:
            if method_name in _PATH_OWNER_WRITE_METHODS and isinstance(node.func, ast.Attribute):
                resolved = _resolved_path_literal(node.func.value, aliases, bindings)
                if resolved in declared_paths:
                    found.add(resolved)
                # 继续尝试位置参数（plotly 的 fig.write_image / pio.write_image 风格）。
            # 位置参数与路径关键字都可能承载路径（plotly.offline.plot 的首参是
            # figure，路径在 filename=），逐个解析而不是只看第一个。
            for argument in _call_path_arguments(node, qualified_name):
                resolved = _resolved_path_literal(argument, aliases, bindings)
                if resolved in declared_paths:
                    found.add(resolved)
            continue
        elif qualified_name in {"open", "io.open"} and node.args:
            mode_node = (
                node.args[1]
                if len(node.args) > 1
                else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                    None,
                )
            )
            mode = _literal_string(mode_node, bindings) if mode_node is not None else None
            if mode and any(char in mode for char in "wax+"):
                path_node = node.args[0]
        if path_node is None:
            continue
        resolved = _resolved_path_literal(path_node, aliases, bindings)
        if resolved in declared_paths:
            found.add(resolved)
    return found


def _reject_output_write_contract(tree: ast.Module, declared_paths: tuple[str, ...]) -> None:
    declared = frozenset(declared_paths)
    if not declared:
        return
    if _declared_output_literals(tree, declared):
        return
    first_output = declared_paths[0] if declared_paths else "<首个签发产物路径>"
    raise ReportingError(
        "report_code_script_no_output_write",
        "脚本未引用任何声明产物路径，疑似占位/探索脚本；必须在脚本中真实写出全部声明产物。"
        "首轮 write_script 就应完整实现全部图表；最小可接受骨架（路径逐字替换）：\n"
        f'import json\nOUT = "{first_output}"\n'
        'data = json.load(open("<task 签发的 factFile 字面路径>", encoding="utf-8"))\n'
        'rows = data["metrics"][0]["periodValues"]\n'
        "import matplotlib\nmatplotlib.use(\"Agg\")\nimport matplotlib.pyplot as plt\n"
        'plt.plot([r["value"] for r in rows])\nplt.savefig(OUT)\n'
        "每张图的真实绘制都必须落盘到各自的签发输出路径。",
        details={"declaredOutputCount": len(declared), "detectedOutputWrites": []},
    )


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return True


def _patch_path_matches(path: str | None, script_path: str) -> bool:
    """apply_patch 路径可写相对、带 ./ 或工作区绝对路径，只要唯一指向绑定脚本。"""

    if not path:
        return False
    normalized = path.strip().strip("`\"'").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return (
        normalized == script_path
        or normalized.endswith("/" + script_path)
        or script_path.endswith("/" + normalized)
    )


def _syntax_edit_failure(
    error: SyntaxError,
    sha256: str,
    *,
    draft: bool = False,
) -> dict[str, Any]:
    message = (
        "补丁后的草稿存在语法错误，仍保留为隔离草稿、未写入正式脚本；"
        "请以新的 draftSha256 继续用 edit_script 修正。"
        if draft
        else "补丁应用后脚本出现语法错误，本次编辑未写入，脚本保持不变；"
        "请以同一 SHA256 重新提交修正后的补丁（SEARCH 仍以当前脚本为准）。"
    )
    return _failure(
        "report_code_source_invalid",
        message,
        {
            "errorType": "SyntaxError",
            **_syntax_error_details(error),
            ("draftSha256" if draft else "sourceSha256"): sha256,
            "nextTools": ["edit_script"],
        },
    )


@dataclass(slots=True)
class _RejectedDraft:
    """被拒整稿的隔离草稿：只在内存中，run_script 永远不执行。"""

    sha256: str
    source: str
    # 草稿链开始时正式脚本的 SHA（None 表示尚不存在）；正式脚本变化后草稿作废。
    base_sha256: str | None
    # 草稿存在期间补丁未能应用的连续次数；达到阈值即作废改走整稿重写。
    edit_failures: int = 0


def _mark_draft_discarded(result: dict[str, Any]) -> None:
    """草稿作废后改写回执：不再指向已作废草稿或推荐草稿补丁。"""

    result["draftDiscarded"] = True
    details = result.get("details")
    if isinstance(details, dict):
        details.pop("draftSha256", None)
        details["nextTools"] = ["write_script"]
    result["message"] = (
        f"{result.get('message', '')}草稿补丁已连续失败，草稿已作废；"
        "请用 write_script 重新提交完整脚本，并修正全部 violations。"
    )


_MISSING_OUTPUT_HINTS = (
    (
        "notReferencedPaths",
        "notReferencedPaths 在脚本中没有出现签发路径字面量：为这些图补上完整绘制与写出，"
        "路径逐字使用签发值（见 writeExample）。",
    ),
    (
        "writeNotExecutedPaths",
        "writeNotExecutedPaths 的写出调用存在但运行时未执行到：检查它是否位于未被调用的"
        "函数、if __name__ 之外的死分支、提前 return/continue，或被 try/except 吞掉的异常之后。",
    ),
    (
        "unresolvedWritePaths",
        "unresolvedWritePaths 在脚本中出现，但宿主未识别到对它的写出调用（路径经变量传入，"
        "或使用了未识别的写出方式如 PIL Image.save）：改为在 savefig/write_image/write_json "
        "调用中直接使用签发路径字面量。",
    ),
)


def _missing_output_diagnosis(
    source: str, missing_paths: list[str], declared_paths: tuple[str, ...]
) -> dict[str, Any]:
    """静态区分"脚本未引用签发路径""写出调用存在但运行时未执行到"与"路径非字面量"。"""

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    declared = frozenset(declared_paths)
    referenced = _declared_output_literals(tree, declared)
    written = _declared_output_write_paths(tree, declared)
    groups = {
        "notReferencedPaths": [path for path in missing_paths if path not in referenced],
        "writeNotExecutedPaths": [path for path in missing_paths if path in written],
        "unresolvedWritePaths": [
            path for path in missing_paths if path in referenced and path not in written
        ],
    }
    result: dict[str, Any] = {}
    hints: list[str] = []
    for key, hint in _MISSING_OUTPUT_HINTS:
        if groups[key]:
            result[key] = groups[key][:20]
            hints.append(hint)
    if hints:
        result["outputHint"] = " ".join(hints)
    return result


def _declared_output_write_example(path: str, declared_paths: tuple[str, ...]) -> str:
    """零产物回执附带缺失产物的完整写出示例，路径逐字使用签发值。

    图片与交互产物的配对沿用交付校验规则：image.with_suffix(".plotly.json")。
    """

    images = [item for item in declared_paths if not item.endswith(".plotly.json")]
    if path.endswith(".plotly.json"):
        image = next((item for item in images if interactive_spec_path(item) == path), None)
        interactive: str | None = path
    else:
        image = path
        interactive = interactive_spec_path(path) if interactive_spec_path(path) in declared_paths else None
    if interactive is not None:
        lines = [f"fig.write_image({image!r})"] if image is not None else []
        return "\n".join([*lines, f"fig.write_json({interactive!r})"])
    return (
        "fig, ax = plt.subplots(figsize=(10, 6))\n"
        "# ... 按本图 chartInputs 绘制 ...\n"
        f"fig.savefig({path!r}, dpi=150, bbox_inches='tight')\n"
        "plt.close(fig)"
    )


def _output_write_warning(tree: ast.Module, declared_paths: tuple[str, ...]) -> dict[str, str] | None:
    declared = frozenset(declared_paths)
    if not declared or not _declared_output_literals(tree, declared):
        return None
    if _declared_output_write_paths(tree, declared):
        return None
    return {
        "code": "report_code_script_output_write_unverified",
        "reason": "no_resolvable_output_write",
        "message": "脚本引用了声明产物路径，但宿主未能静态确认写出调用；请确保运行后会真实写出全部声明产物。",
    }


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


# candidate-18/19 长修复循环的形态：模型无视指令写出 navigate/read_rows 这类
# 通用动态路径解析器，运行期对 facts 做 cur[key] 触发 KeyError。这里只在
# “path/data_path 参数 + 对该参数的解析调用 + 解析结果驱动的下标访问”三者
# 同时命中时才拒绝，避免误伤普通数据处理函数。
_DYNAMIC_PATH_PARAMETER_NAMES = frozenset({"path", "data_path"})
_DYNAMIC_PATH_SPLIT_METHODS = frozenset({"split", "rsplit"})
_DYNAMIC_PATH_REGEX_CALLS = frozenset({"re.fullmatch", "re.match", "re.search"})


def _function_parameter_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = func.args
    names = [item.arg for item in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _loaded_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _bound_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_bound_names(element))
        return names
    return []


def _function_scope_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """函数自有节点；嵌套函数/lambda 的局部变量不参与本函数的派生分析。"""
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def _dynamic_path_parser_details(tree: ast.AST) -> dict[str, Any] | None:
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parameters = _function_parameter_names(node)
        path_param = next(
            (name for name in parameters if name in _DYNAMIC_PATH_PARAMETER_NAMES),
            None,
        )
        if path_param is None:
            continue
        scope = _function_scope_nodes(node)
        derived = {path_param}
        containers = set(parameters)
        changed = True
        while changed:
            changed = False
            for item in scope:
                targets: list[ast.AST] = []
                value: ast.AST | None = None
                if isinstance(item, (ast.Assign, ast.AugAssign)):
                    targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                    value = item.value
                elif isinstance(item, (ast.AnnAssign, ast.NamedExpr)):
                    targets = [item.target]
                    value = item.value
                elif isinstance(item, (ast.For, ast.AsyncFor, ast.comprehension)):
                    targets = [item.target]
                    value = item.iter
                for target in targets:
                    bound = _bound_names(target)
                    if not bound:
                        continue
                    containers.update(bound)
                    if value is not None and _loaded_names(value) & derived:
                        if not set(bound) <= derived:
                            derived.update(bound)
                            changed = True
        has_parse_signal = False
        for item in scope:
            if not isinstance(item, ast.Call):
                continue
            if (
                isinstance(item.func, ast.Attribute)
                and item.func.attr in _DYNAMIC_PATH_SPLIT_METHODS
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id in derived
            ):
                sep = (
                    item.args[0]
                    if item.args
                    else next(
                        (keyword.value for keyword in item.keywords if keyword.arg == "sep"),
                        None,
                    )
                )
                if (
                    isinstance(sep, ast.Constant)
                    and isinstance(sep.value, str)
                    and "." in sep.value
                ):
                    has_parse_signal = True
            if _qualified_name(item.func, aliases) in _DYNAMIC_PATH_REGEX_CALLS:
                subject = (
                    item.args[1]
                    if len(item.args) > 1
                    else next(
                        (keyword.value for keyword in item.keywords if keyword.arg == "string"),
                        None,
                    )
                )
                if subject is not None and _loaded_names(subject) & derived:
                    has_parse_signal = True
        has_subscript_signal = any(
            isinstance(item, ast.Subscript)
            and isinstance(item.value, ast.Name)
            and item.value.id in containers
            and _loaded_names(item.slice) & derived
            for item in scope
        )
        if has_parse_signal and has_subscript_signal:
            return {
                "reason": "dynamic_path_parser",
                "functionName": node.name,
                "parameterName": path_param,
                "line": node.lineno,
            }
    return None


def _reject_dynamic_path_parser(tree: ast.AST) -> None:
    details = _dynamic_path_parser_details(tree)
    if details is None:
        return
    raise ReportingError(
        "report_code_dynamic_path_parser",
        "禁止编写通用动态路径解析器：函数 {functionName} 接收 {parameterName} 并按解析结果"
        "对数据做下标访问。逐字使用 binding.dataPath（如 findings[0].rows）读取数据，"
        "用显式链式访问替代运行期路径解析，不要写通用路径解析器。".format(**details),
        details=details,
    )


def _simple_assignment_targets_value(item: ast.AST) -> tuple[list[ast.AST], ast.AST | None]:
    if isinstance(item, ast.Assign):
        return item.targets, item.value
    if isinstance(item, ast.AnnAssign):
        return [item.target], item.value
    if isinstance(item, ast.NamedExpr):
        return [item.target], item.value
    return [], None


def _read_text_call(node: ast.AST, aliases: Mapping[str, str]) -> bool:
    """Detect Path(...).read_text()."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_text"
        and isinstance(node.func.value, ast.Call)
        and _qualified_name(node.func.value.func, aliases) == "pathlib.Path"
    )


def _is_load_expression(
    node: ast.AST,
    aliases: Mapping[str, str],
    derived: set[str],
    loaded_sources: Mapping[str, str],
) -> bool:
    if isinstance(node, ast.Name) and node.id in loaded_sources:
        return True
    if not isinstance(node, ast.Call):
        return False
    qn = _qualified_name(node.func, aliases)
    if qn == "open" and node.args and _loaded_names(node.args[0]) & derived:
        return True
    if qn in ("json.load", "json.loads") and node.args:
        if _is_load_expression(node.args[0], aliases, derived, loaded_sources):
            return True
    if _read_text_call(node, aliases):
        path_arg = node.func.value.args[0] if node.func.value.args else None
        if path_arg is not None and _loaded_names(path_arg) & derived:
            return True
    return False


def _path_source_parameter(
    node: ast.AST,
    aliases: Mapping[str, str],
    derived: set[str],
    loaded_sources: Mapping[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        return loaded_sources.get(node.id)
    if not isinstance(node, ast.Call):
        return None
    qn = _qualified_name(node.func, aliases)
    if qn == "open" and node.args:
        names = _loaded_names(node.args[0]) & derived
        if names:
            return min(names)
    if qn in ("json.load", "json.loads") and node.args:
        return _path_source_parameter(node.args[0], aliases, derived, loaded_sources)
    if _read_text_call(node, aliases):
        path_arg = node.func.value.args[0] if node.func.value.args else None
        if path_arg is not None:
            names = _loaded_names(path_arg) & derived
            if names:
                return min(names)
    return None


def _findings_decoder_root(node: ast.AST, parameters: set[str]) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    chain: list[ast.Subscript] = []
    current: ast.AST = node
    while isinstance(current, ast.Subscript):
        chain.append(current)
        current = current.value
    if len(chain) < 3:
        return None
    innermost = chain[-1]
    key = innermost.slice
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or key.value != "findings":
        return None
    if not isinstance(current, ast.Name) or current.id not in parameters:
        return None
    return current.id


def _reject_generic_data_helpers(tree: ast.AST) -> None:
    details = _generic_data_helper_details(tree)
    if details is None:
        return
    if details["reason"] == "generic_loader":
        message = (
            "禁止编写通用数据加载函数：函数 {functionName} 接收 {parameterName} 并直接返回"
            "加载后的原始数据。请内联使用 json.load(open(LITERAL_PATH)) 读取数据，"
            "不要封装通用加载器。".format(**details)
        )
    else:
        message = (
            "禁止编写通用 findings 解码函数：函数 {functionName} 接收 {parameterName} 并直接返回"
            "原始行数据。请使用显式链式访问如 data['findings'][0]['rows']，"
            "不要封装通用数据解码器。".format(**details)
        )
    raise ReportingError("report_code_generic_data_helper", message, details=details)


def _generic_data_helper_details(tree: ast.AST) -> dict[str, Any] | None:
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        param_list = _function_parameter_names(node)
        if not param_list:
            continue
        parameters = set(param_list)
        first_param = param_list[0]
        scope = _function_scope_nodes(node)

        # Propagate parameter-derived names (e.g., path = p).
        derived: set[str] = set(parameters)
        changed = True
        while changed:
            changed = False
            for item in scope:
                targets, value = _simple_assignment_targets_value(item)
                if value is not None and _loaded_names(value) & derived:
                    for target in targets:
                        for name in _bound_names(target):
                            if name not in derived:
                                derived.add(name)
                                changed = True

        # Generic file loader detection.
        loaded_sources: dict[str, str] = {}
        changed = True
        while changed:
            changed = False
            for item in scope:
                targets, value = _simple_assignment_targets_value(item)
                if value is not None and _is_load_expression(
                    value, aliases, derived, loaded_sources
                ):
                    source = _path_source_parameter(value, aliases, derived, loaded_sources)
                    for target in targets:
                        for name in _bound_names(target):
                            if name not in loaded_sources:
                                loaded_sources[name] = source or first_param
                                changed = True
                if isinstance(item, ast.With):
                    for withitem in item.items:
                        if withitem.optional_vars is None:
                            continue
                        if _is_load_expression(
                            withitem.context_expr, aliases, derived, loaded_sources
                        ):
                            source = _path_source_parameter(
                                withitem.context_expr, aliases, derived, loaded_sources
                            )
                            for name in _bound_names(withitem.optional_vars):
                                if name not in loaded_sources:
                                    loaded_sources[name] = source or first_param
                                    changed = True

        for item in scope:
            if isinstance(item, ast.Return) and item.value is not None:
                if _is_load_expression(item.value, aliases, derived, loaded_sources):
                    source = _path_source_parameter(
                        item.value, aliases, derived, loaded_sources
                    )
                    if source is None and isinstance(item.value, ast.Name):
                        source = loaded_sources.get(item.value.id)
                    return {
                        "reason": "generic_loader",
                        "functionName": node.name,
                        "parameterName": source or first_param,
                        "line": node.lineno,
                    }

        # Generic findings decoder detection.
        decoder_roots: dict[str, str] = {}
        changed = True
        while changed:
            changed = False
            for item in scope:
                targets, value = _simple_assignment_targets_value(item)
                if value is None:
                    continue
                root = _findings_decoder_root(value, parameters)
                if root is None and isinstance(value, ast.Name):
                    root = decoder_roots.get(value.id)
                if root is not None:
                    for target in targets:
                        for name in _bound_names(target):
                            if name not in decoder_roots:
                                decoder_roots[name] = root
                                changed = True

        for item in scope:
            if isinstance(item, ast.Return) and item.value is not None:
                root = _findings_decoder_root(item.value, parameters)
                if root is None and isinstance(item.value, ast.Name):
                    root = decoder_roots.get(item.value.id)
                if root is not None:
                    return {
                        "reason": "generic_findings_decoder",
                        "functionName": node.name,
                        "parameterName": root,
                        "line": node.lineno,
                    }
    return None


def _safe_join_call(
    node: ast.Call,
    aliases: Mapping[str, str],
    bindings: Mapping[str, ast.AST],
    authorized_paths: frozenset[str],
) -> bool:
    """os.path.join 只在所有参数都是静态字面量且结果命中签发路径时放行。"""
    if _qualified_name(node.func, aliases) != "os.path.join" or node.keywords:
        return False
    parts: list[str] = []
    for arg in node.args:
        lit = _literal_string(arg, bindings)
        if lit is None:
            return False
        parts.append(lit)
    if not parts:
        return False
    return os.path.join(*parts) in authorized_paths


def _is_placeholder_script(
    source: str,
    declared_output_paths: frozenset[str],
    task_kind: str,
) -> bool:
    """启发式识别占位/探索脚本：不引用声明产物且无产物写出调用，但存在目录遍历。

    用于在 declared_output_missing 时快速打开重写闸门，避免预算空转。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)

    referenced_paths = _all_referenced_literal_paths(tree)
    if referenced_paths & declared_output_paths:
        return False

    has_exploration = any(
        isinstance(node, ast.Call)
        and _qualified_name(node.func, aliases) in _PLACEHOLDER_EXPLORATION_CALLS
        for node in ast.walk(tree)
    )
    if not has_exploration:
        return False

    has_output_call = any(
        isinstance(node, ast.Call)
        and (
            _qualified_name(node.func, aliases) in _PLACEHOLDER_OUTPUT_CALLS
            or (
                (qualified := _qualified_name(node.func, aliases)) is not None
                and qualified.rsplit(".", 1)[-1] in _PLACEHOLDER_OUTPUT_METHODS
            )
            or _looks_like_output_open(node, aliases, bindings)
        )
        for node in ast.walk(tree)
    )
    if has_output_call:
        return False

    if task_kind == "visualization":
        viz_roots = {"matplotlib", "plotly", "seaborn"}
        if any(
            module.split(".")[0] in viz_roots for module in aliases.values()
        ) or any(
            isinstance(node, ast.Import)
            and any(alias.name.split(".")[0] in viz_roots for alias in node.names)
            for node in ast.walk(tree)
        ):
            return False

    return True


def _looks_like_output_open(
    node: ast.Call, aliases: Mapping[str, str], bindings: Mapping[str, ast.AST]
) -> bool:
    qualified = _qualified_name(node.func, aliases)
    if qualified not in ("open", "io.open"):
        return False
    if not node.args or len(node.args) < 2:
        return False
    mode = _literal_string(node.args[1], bindings)
    if mode is None:
        return False
    return any(char in mode for char in "wax+")


def _reject_unauthorized_paths(tree: ast.AST, path: str, authorized_paths: frozenset[str]) -> None:
    aliases = _import_aliases(tree)
    bindings = _literal_bindings(tree)
    forbidden: set[str] = set()
    # 记录违规出现的行，便于模型直接按行打补丁而不必再 read_script 定位。
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, aliases)
        if qualified not in _FORBIDDEN_PATH_CALLS:
            continue
        if qualified == "os.path.join" and _safe_join_call(
            node, aliases, bindings, authorized_paths
        ):
            continue
        forbidden.add(qualified)
        lines.append(node.lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "__file__":
            forbidden.add("__file__")
            lines.append(node.lineno)
    unsigned = _referenced_literal_paths(tree) - set(authorized_paths)
    # pathlib 斜杠拼接与安全 os.path.join 同语义：完整拼接结果命中签发路径时，
    # 其组成部分（如目录名 "charts"）不按未签发路径报告。
    if unsigned:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                continue
            resolved = _resolved_path_literal(node, aliases, bindings)
            if resolved is None or resolved not in authorized_paths:
                continue
            parts: set[str] = set()
            left = _literal_string(node.left, bindings)
            if isinstance(node.left, ast.Call) and _qualified_name(node.left.func, aliases) == "pathlib.Path":
                left = _literal_string(node.left.args[0], bindings) if node.left.args else None
            right = _literal_string(node.right, bindings)
            if left is not None:
                parts.add(_normalize_literal_path(left))
            if right is not None:
                parts.add(_normalize_literal_path(right))
            unsigned -= parts
    if unsigned:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            qualified_name = _qualified_name(node.func, aliases)
            if qualified_name is None:
                continue
            if any(
                (literal := _literal_string(argument, bindings)) is not None
                and _normalize_literal_path(literal) in unsigned
                for argument in _path_arguments(node, qualified_name)
            ):
                lines.append(node.lineno)
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
                **({"line": min(lines), "violationLines": sorted(set(lines))[:20]} if lines else {}),
            },
        )


def _syntax_error_details(error: SyntaxError) -> dict[str, Any]:
    return {
        "line": error.lineno,
        "column": error.offset,
        "endLine": error.end_lineno,
        "endColumn": error.end_offset,
        "sourceLine": (error.text or "").rstrip("\n"),
        "reason": error.msg,
    }


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
            details.update(_syntax_error_details(error))
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


_MAX_PREFLIGHT_VIOLATIONS = 8
_PREFLIGHT_SNIPPET_BYTES = 300


def _violation_line(details: Mapping[str, Any]) -> int | None:
    for key in ("line", "errorLine"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    operations = details.get("forbiddenPathOperations")
    if isinstance(operations, list):
        for item in operations:
            if isinstance(item, Mapping):
                value = item.get("line")
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
    return None


def _preflight_violation(error: ReportingError, source: str) -> dict[str, Any]:
    details = error.details if isinstance(error.details, Mapping) else {}
    violation: dict[str, Any] = {"code": error.code, "hint": error.message[:300]}
    line = _violation_line(details)
    if line is not None:
        violation["line"] = line
        lines = source.splitlines()
        if line <= len(lines):
            snippet = lines[line - 1].strip().encode("utf-8")[:_PREFLIGHT_SNIPPET_BYTES]
            violation["snippet"] = snippet.decode("utf-8", errors="ignore")
    for key in ("unsignedPaths", "forbiddenPathOperations"):
        value = details.get(key)
        if isinstance(value, list) and value:
            violation[key] = [str(item)[:256] for item in value[:5]]
    extra_lines = details.get("violationLines")
    if isinstance(extra_lines, list) and len(extra_lines) > 1:
        violation["lines"] = [item for item in extra_lines[:10] if isinstance(item, int)]
    return violation


def _collect_preflight(
    tree: ast.Module,
    source: str,
    tool_name: str,
    context: Any,
) -> tuple[list[ReportingError], list[dict[str, str]]]:
    """一次执行全部预检，返回 (违规列表, 软告警)；主失败码沿用第一个违规。"""

    checks: list[Callable[[], None]] = [
        lambda: _reject_code_envelope(tree, tool_name),
        lambda: _reject_embedded_data(tree),
        lambda: _reject_dynamic_path_parser(tree),
        lambda: _reject_generic_data_helpers(tree),
        lambda: _reject_unauthorized_paths(
            tree,
            context.script_path,
            frozenset((*context.authorized_read_paths, *context.authorized_write_paths)),
        ),
    ]
    if context.task_kind == "visualization":
        checks.append(
            lambda: _reject_output_write_contract(tree, context.declared_output_paths)
        )
    violations: list[ReportingError] = []
    for check in checks:
        try:
            check()
        except ReportingError as error:
            violations.append(error)
    warnings: list[dict[str, str]] = []
    helper = _generic_data_helper_details(tree)
    if helper is not None:
        # 统一形状输入下通用 helper 本身无害；真正的风险路径由字面路径白名单兜底。
        warnings.append(
            {
                "code": "report_code_generic_data_helper",
                "reason": str(helper.get("reason") or "generic_helper"),
                "message": "检测到通用数据读取 helper；请确认只读取签发路径中的逐字字符串。",
            }
        )
    return violations, warnings


def _preflight_failure(
    violations: list[ReportingError],
    source: str,
    *,
    draft_sha256: str | None = None,
) -> dict[str, Any]:
    primary = violations[0]
    details = dict(primary.details) if isinstance(primary.details, Mapping) else {}
    details["violations"] = [
        _preflight_violation(item, source) for item in violations[:_MAX_PREFLIGHT_VIOLATIONS]
    ]
    if draft_sha256 is not None:
        details["draftSha256"] = draft_sha256
        details["nextTools"] = ["edit_script"]
    message = primary.message
    if len(violations) > 1:
        message = f"{message}（另有 {len(violations) - 1} 项违规，见 details.violations）"
    if draft_sha256 is not None:
        message += (
            "被拒整稿已保存为隔离草稿，不会执行；请用 edit_script 以 draftSha256 作为 "
            "*** SHA256: 对草稿打补丁修正全部违规，无需重新生成整稿。"
        )
    return _failure(primary.code, message, details)


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
        "actualBytes", "limitBytes", "missingPaths", "presentPaths", "exitCode", "escalated",
        "status", "validationRunId", "executionRunId", "sourceSha256",
        "currentSha256", "expectedSha256", "action", "readRange",
        "sourceExcerpt", "sourceStartLine", "sourceEndLine", "errorLine", "blockIndex",
        "variableSummary", "explorationVariables", "allowedEditRegion", "forbiddenEditRegions",
        "isPlaceholderScript", "allDeclaredOutputsMissing", "declaredOutputCount",
        "detectedOutputWrites", "functionName", "parameterName",
        "violations", "draftSha256", "violationLines", "writeExample",
        "notReferencedPaths", "writeNotExecutedPaths", "unresolvedWritePaths", "outputHint",
        "hint",
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
            "unsignedPaths", "forbiddenPathOperations", "requiredNextTools", "nextTools", "missingPaths", "presentPaths",
            "detectedOutputWrites", "violationLines", "notReferencedPaths",
            "writeNotExecutedPaths", "unresolvedWritePaths",
        }:
            if isinstance(value, list):
                result[key] = [bounded_text(str(item), 256) for item in value[:20]]
        elif key in {"retryable", "escalated", "isPlaceholderScript", "allDeclaredOutputsMissing"}:
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
        elif key == "violations" and isinstance(value, list):
            result[key] = [
                {
                    field: (
                        bounded_text(item[field], _PREFLIGHT_SNIPPET_BYTES)
                        if isinstance(item[field], str)
                        else item[field]
                    )
                    for field in (
                        "code", "hint", "line", "lines", "snippet", "unsignedPaths",
                        "forbiddenPathOperations",
                    )
                    if field in item
                }
                for item in value[:_MAX_PREFLIGHT_VIOLATIONS]
                if isinstance(item, Mapping)
            ]
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


def _bounded_edit_context(
    source: str, anchor_line: int, script_path: str
) -> dict[str, Any] | None:
    """以 anchor_line 为中心计算模型可直接局部编辑的有界源码上下文。"""
    lines = source.splitlines(keepends=True)
    if not 1 <= anchor_line <= len(lines):
        return None
    start_line = max(1, anchor_line - 12)
    end_line = min(len(lines), anchor_line + 12)
    region_start, region_end = start_line, end_line
    try:
        functions = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.end_lineno is not None
            and node.lineno <= anchor_line <= node.end_lineno
        ]
    except SyntaxError:
        functions = []
    if functions:
        function = max(functions, key=lambda node: node.lineno)
        region_start, region_end = function.lineno, function.end_lineno
        assert region_end is not None
        function_source = "".join(lines[region_start - 1:region_end])
        if len(function_source.encode("utf-8")) <= SOURCE_EXCERPT_MAX_BYTES:
            start_line, end_line = region_start, region_end
        else:
            start_line = max(start_line, region_start)
            end_line = min(end_line, region_end)
    while (
        len("".join(lines[start_line - 1:end_line]).encode("utf-8"))
        > SOURCE_EXCERPT_MAX_BYTES
    ):
        if start_line == end_line:
            return None
        if anchor_line - start_line >= end_line - anchor_line:
            start_line += 1
        else:
            end_line -= 1
    context: dict[str, Any] = {
        "sourceExcerpt": "".join(lines[start_line - 1:end_line]),
        "sourceStartLine": start_line,
        "sourceEndLine": end_line,
        "errorLine": anchor_line,
        "allowedEditRegion": {
            "path": script_path,
            "startLine": region_start,
            "endLine": region_end,
        },
        "forbiddenEditRegions": [
            {
                "path": script_path,
                "outside": {
                    "startLine": 1,
                    "endLine": len(lines),
                    "allowedStartLine": region_start,
                    "allowedEndLine": region_end,
                },
            }
        ],
    }
    if start_line > region_start or end_line < region_end:
        context["readRange"] = dict(context["allowedEditRegion"])
    return context


def _search_anchor_line(source: str, search_text: str) -> int | None:
    """用 SEARCH 首个非空行在当前源码中定位锚点行；未命中返回 None。"""
    anchor_lines = [line for line in search_text.split("\n") if line.strip()]
    if not anchor_lines:
        return None
    first_line = anchor_lines[0].rstrip("\r")
    source_lines = source.splitlines()
    for index, line in enumerate(source_lines, 1):
        if line == first_line:
            return index
    for index, line in enumerate(source_lines, 1):
        if first_line in line:
            return index
    return None


_EDIT_ANCHOR_FAILURE_CODES = frozenset(
    {
        "report_code_script_edit_not_found",
        "report_code_script_edit_ambiguous",
        "report_code_script_edit_overlap",
    }
)


def _edit_failure_anchor_details(
    source: str,
    edits: list[tuple[str, str]],
    details: Mapping[str, Any],
    script_path: str,
    current_sha256: str,
) -> dict[str, Any]:
    """not_found/ambiguous/overlap 回执：锚点命中附上有界上下文，未命中退回 readRange。"""
    repair = dict(details)
    block_index = repair.get("blockIndex")
    search_text = (
        edits[block_index - 1][0]
        if isinstance(block_index, int) and not isinstance(block_index, bool)
        and 1 <= block_index <= len(edits)
        else (edits[0][0] if edits else "")
    )
    anchor_line = _search_anchor_line(source, search_text)
    context = (
        _bounded_edit_context(source, anchor_line, script_path)
        if anchor_line is not None
        else None
    )
    if context is None:
        # 锚点未命中：excerpt 无法定位，退回整份读取范围。
        repair["readRange"] = {
            "path": script_path,
            "startLine": 1,
            "endLine": len(source.splitlines()),
        }
        return repair
    repair.update(context)
    repair["sourceSha256"] = current_sha256
    repair["nextTools"] = (
        ["read_script", "edit_script", "run_script"]
        if "readRange" in context
        else ["edit_script", "run_script"]
    )
    return repair


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
        # edit_script 输入格式分布（含无效原因），用于评估原生 apply_patch 的实际占比。
        self.patch_format_counts: dict[str, int] = {}
        self.first_repair_success: bool | str = "unknown"
        self._awaiting_first_repair_run = False
        self.visual_review_duration_ms = 0
        self._delivery_state: dict[str, Any] = {}
        self._failure_signature: str | None = None
        self._repeated_failure_count = 0
        self._edit_failures_since_progress = 0
        self._consecutive_critical_review_rounds = 0
        self._critical_review_run_id: str | None = None
        # V3：被拒整稿只保存在内存隔离草稿中，run_script 永远不执行草稿。
        self._rejected_draft: _RejectedDraft | None = None
        # 最近一次 edit_script 是否以草稿 SHA 为目标（补丁无法解析时按原文中的 SHA 判断）。
        self._last_edit_targeted_draft = False
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
                    "定位或冲突失败回执可能附带当前源码的有界 sourceExcerpt 与行号范围；"
                    "据此修正 SEARCH 并使用回执中的 sourceSha256/currentSha256 直接重试，无需重新 read_script。"
                    "write_script 预检被拒时回执给出 draftSha256 与全部 violations；把 draftSha256 放在 "
                    "*** SHA256: 后即可对被拒草稿打补丁，通过全部预检后草稿才成为签发脚本。"
                    "插入使用原文上下文作锚点；删除使用空 REPLACE；移动用删除块与目标处插入块。"
                    "禁止整份替换。"
                    "也可使用 Codex apply_patch 格式：*** Begin Patch\n*** Update File: <绑定脚本路径>\n"
                    "@@\n 上下文行（行首一个空格）\n-删除行\n+新增行\n*** End Patch；"
                    "每个 hunk 至少含一行原文上下文，只能更新绑定脚本，可在 Begin Patch 后加 *** SHA256: 行。"
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
                description=(
                    "检查已保存脚本的语法和类型诊断；可用当前脚本 SHA 防止读取旧版本。"
                    "回执中的 line/column 从 1 开始，与 read_script 和 traceback 一致，并附 sourceLine。"
                ),
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
                    description="审查 run_script 生成的图片输出。为减少模型往返，请把所有待审查图片路径"
                                "放入 `paths` 数组一次性调用；超过 5 张时宿主会自动按 5 张分批审查，"
                                "无需自行拆分。只有单张图时才使用 `path`。"
                                "禁止重复审查已通过的图片，修复后重新运行再审查。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                # 宿主按 5 张分批审查，此处不限上限，
                                # 与描述“超过 5 张宿主自动分批”口径一致。
                            },
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                            },
                        },
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
        context = _bounded_edit_context(source, error_line, self.context.script_path)
        if context is None:
            return repair
        repair.update(context)
        # excerpt 覆盖整个允许区域时可直接局部修复；收缩过则需先读取缺失部分。
        repair["nextTools"] = (
            ["read_script", "edit_script", "run_script"]
            if "readRange" in context
            else ["edit_script", "run_script"]
        )
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
        # 编辑失败计数只在真正取得进展（成功运行或整段重写落盘）时清零；
        # 成功但未带来运行通过的编辑不算进展，避免在"编辑空转"死局里反复重置。
        if name == "edit_script" and failed:
            self._edit_failures_since_progress += 1
            failure_code = result.get("code") if isinstance(result, Mapping) else None
            patch_not_applied = isinstance(failure_code, str) and failure_code.startswith(
                "report_code_script_edit_"
            )
            draft = self._rejected_draft
            if draft is not None and self._last_edit_targeted_draft:
                # 补丁已应用但仍有违规或语法错误，属于逐步修正的进展，不计入空转；
                # 针对正式脚本的编辑不影响草稿计数。
                draft.edit_failures = draft.edit_failures + 1 if patch_not_applied else 0
                if draft.edit_failures >= REWRITE_GATE_EDIT_FAILURES:
                    # 草稿补丁连续失败（多为补丁格式 edit_invalid）：继续推荐草稿
                    # 补丁只会空转，作废草稿，交付状态随之只推荐 write_script。
                    self._rejected_draft = None
                    if isinstance(fc.result, dict):
                        _mark_draft_discarded(fc.result)
        elif name in {"run_script", "write_script"} and not failed:
            self._edit_failures_since_progress = 0
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
        if name == "view_image" and isinstance(fc.result, Mapping):
            receipt_payloads: list[Mapping[str, Any]] = []
            if isinstance(fc.result.get("receipt"), Mapping):
                receipt_payloads.append(fc.result["receipt"])
            receipts = fc.result.get("receipts")
            if isinstance(receipts, list):
                receipt_payloads.extend(
                    item for item in receipts if isinstance(item, Mapping)
                )
            requires_any_revision = any(
                item.get("requiresRevision") is True or item.get("requires_revision") is True
                for item in receipt_payloads
            )
            fresh_count = fc.result.get("freshReviewCount")
            has_fresh_review = (
                isinstance(fresh_count, int) and fresh_count > 0
            ) or (fresh_count is None and bool(receipt_payloads))
            if has_fresh_review:
                # 对齐 codex 熔断语义：一次 run_script 的产物审查算一轮，同一执行
                # 分多次 view_image 不重复累计；只有当前执行全部图片都不再要求
                # 修订时才清零。缓存回执不清零、也不累计。
                execution = self.binding.execution_receipt
                run_id = execution.run_id if execution is not None else None
                if requires_any_revision:
                    if run_id is None or run_id != self._critical_review_run_id:
                        self._consecutive_critical_review_rounds += 1
                        self._critical_review_run_id = run_id
                elif not self._current_run_requires_revision():
                    self._consecutive_critical_review_rounds = 0
                    self._critical_review_run_id = None
            if self._awaiting_first_repair_run and requires_any_revision:
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
            elif name == "edit_script" and failure["code"] in {
                "report_code_script_edit_invalid",
                "report_code_script_edit_not_local",
            }:
                # edit_script 的诊断通常只有源码身份和块错误；把原始 patch 纳入签名，
                # 这样只有同一源码上的同一无效 patch 才会触发终止，不会误杀已修改的修复。
                input_text = json.dumps(fc.arguments, ensure_ascii=False, sort_keys=True)
                signature += hashlib.sha256(input_text.encode("utf-8")).hexdigest()
            self._repeated_failure_count = (
                self._repeated_failure_count + 1 if signature == self._failure_signature else 1
            )
            self._failure_signature = signature
            # callId 只标识失败调用身份，不进入签名，避免不同 call id 的相同失败绕过重复检测。
            call_id = fc.call_id if isinstance(fc.call_id, str) and fc.call_id else "unknown"
            self.last_failure = {**failure, "callId": call_id[:256], "resolved": False}
            if self.terminal_failure is not None:
                fc.function.stop_after_tool_call = True
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
            if (
                name == "edit_script"
                and failure["code"] in {
                    "report_code_script_edit_invalid",
                    "report_code_script_edit_not_local",
                }
                and self._repeated_failure_count >= 2
                and isinstance(result, dict)
            ):
                self.terminal_failure = ReportingError(
                    failure["code"],
                    "相同源码上的相同 edit_script 补丁连续两次失败，已停止本次 Coding Agent。",
                    details={
                        "recovery": "retry_then_degrade",
                        "stopReason": "repeated_identical_patch",
                        "sourceSha256": failure["sourceSha256"],
                        "nextTools": ["read_script", "edit_script"],
                    },
                )
                result["repeatedFailureCount"] = self._repeated_failure_count
                result["repairHint"] = (
                    "相同补丁已连续失败两次；本轮已停止。下一轮先 read_script 获取当前源码，"
                    "再生成更小的局部 SEARCH/REPLACE 补丁。"
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
    def rewrite_gate_open(self) -> bool:
        """连续局部编辑失败且无成功运行；允许一次 write_script 整段重写。"""

        return self._edit_failures_since_progress >= REWRITE_GATE_EDIT_FAILURES

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
            and (not review.requires_revision or self.visual_review_gate_tripped)
        )

    def _current_run_requires_revision(self) -> bool:
        execution = self.binding.execution_receipt
        if execution is None:
            return False
        outputs = {item.path: item.sha256 for item in execution.output_files}
        return any(
            review.requires_revision and outputs.get(path) == review.sha256
            for path, review in self.binding.visual_inspection_receipts.items()
        )

    @property
    def rejected_draft_sha256(self) -> str | None:
        return self._rejected_draft.sha256 if self._rejected_draft is not None else None

    @property
    def consecutive_critical_review_rounds(self) -> int:
        """连续要求修订的视觉审查轮次；干净通过的轮次会清零。"""
        return self._consecutive_critical_review_rounds

    @property
    def visual_review_gate_tripped(self) -> bool:
        return (
            self._consecutive_critical_review_rounds
            >= VISUALIZATION_CRITICAL_REVIEW_ROUNDS_LIMIT
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
        return await self._write_source(source)

    async def _store_draft(self, source: str) -> str:
        """保存被拒整稿为隔离草稿；同一草稿链沿用首次被拒时的正式脚本 SHA。"""

        sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        draft = self._rejected_draft
        if draft is None:
            self._rejected_draft = _RejectedDraft(
                sha256, source, await self._current_script_sha256()
            )
        else:
            draft.sha256, draft.source = sha256, source
        return sha256

    async def _write_source(
        self, source: str, *, promote_draft: bool = False
    ) -> dict[str, Any]:
        """write_script 与草稿提升共用的预检、格式化与落盘。

        promote_draft=True 时语法错误不落盘：补丁后的草稿必须先能解析，否则语法错误
        （及因无法解析而跳过的路径违规）会漏到 run_script 才暴露。
        """
        warnings: list[dict[str, Any]] = []
        formatted = False
        try:
            source = validate_draft_source(self.context, source).decode("utf-8")
            try:
                tree = ast.parse(source, filename=self.context.script_path)
            except SyntaxError as error:
                if promote_draft:
                    return _syntax_edit_failure(
                        error, await self._store_draft(source), draft=True
                    )
                # 草稿允许暂时存在语法错误，供 LSP 和后续修复使用；回执直接给出
                # 错误位置，模型无需再跑一次 run_script 才能定位。
                tree = None
                warnings.append(
                    {
                        "code": "report_code_formatting_skipped",
                        "reason": "syntax_error",
                        "message": "草稿存在语法错误，已保留原稿并跳过格式化。",
                        "syntaxError": _syntax_error_details(error),
                    }
                )
            if tree is not None:
                # 与 run_script 同一路径策略：draft 阶段即拒绝，避免"保存成功
                # → 执行被拒"浪费一整个写-跑循环后模型重试退化。一次返回全部违规。
                violations, preflight_warnings = _collect_preflight(
                    tree, source, "write_script", self.context
                )
                if violations:
                    return _preflight_failure(
                        violations, source, draft_sha256=await self._store_draft(source)
                    )
                warnings.extend(preflight_warnings)
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
        if tree is not None and self.context.task_kind == "visualization":
            output_write_warning = _output_write_warning(
                tree, self.context.declared_output_paths
            )
            if output_write_warning is not None:
                warnings.append(output_write_warning)
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
        self._rejected_draft = None
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
        draft = self._rejected_draft
        try:
            parsed = parse_script_patch(patch, self.context.max_source_bytes)
        except ReportingError as error:
            # 补丁格式无效时无法解析出 SHA，按原文是否携带草稿 SHA 判断目标。
            self._last_edit_targeted_draft = (
                draft is not None and isinstance(patch, str) and draft.sha256 in patch
            )
            self._record_patch_format(
                "invalid:" + str((error.details or {}).get("reason", "unknown"))
            )
            return _failure(error.code, error.message, error.details)
        self._record_patch_format(parsed.patch_format)
        edits, expectedSourceSha256 = parsed.edits, parsed.sha256
        if expectedSourceSha256 is None:
            # 原生 apply_patch 可省略 SHA：此时目标只能由 Update File 路径确认，
            # 存在被拒草稿时补丁基于模型最近提交的草稿文本。
            if not _patch_path_matches(parsed.path, self.context.script_path):
                self._last_edit_targeted_draft = False
                return _failure(
                    "report_code_script_edit_invalid",
                    "apply_patch 的 *** Update File 路径必须是当前绑定脚本。",
                    {
                        "reason": "apply_patch_path_mismatch",
                        "patchFormat": parsed.patch_format,
                        "path": (parsed.path or "")[:256],
                        "expectedPath": self.context.script_path,
                        "nextTools": ["edit_script"],
                    },
                )
            self._last_edit_targeted_draft = draft is not None
        else:
            self._last_edit_targeted_draft = (
                draft is not None and expectedSourceSha256 == draft.sha256
            )
        if draft is not None and self._last_edit_targeted_draft:
            return await self._edit_rejected_draft(
                draft, edits, anchors=parsed.anchors, ordered=parsed.ordered
            )
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
        if expectedSourceSha256 is not None and expectedSourceSha256 != current_sha256:
            details: dict[str, Any] = {
                "currentSha256": current_sha256,
                "expectedSha256": expectedSourceSha256,
                "action": "read_script",
                "readRange": {
                    "path": self.context.script_path,
                    "startLine": 1,
                    "endLine": len(source.splitlines()),
                },
                "nextTools": ["read_script", "edit_script"],
            }
            # SEARCH 首行仍能命中当前源码时附上有界 excerpt，模型可据此直接重试。
            anchor_line = _search_anchor_line(source, edits[0][0] if edits else "")
            context = (
                _bounded_edit_context(source, anchor_line, self.context.script_path)
                if anchor_line is not None
                else None
            )
            if context is not None:
                details.update(context)
                details["sourceSha256"] = current_sha256
            return _failure(
                "report_code_script_edit_conflict",
                "脚本在读取后已发生变化，请重新读取后再编辑。",
                details,
            )
        try:
            updated, fuzzy_matches = apply_edit_blocks(
                source, edits, anchors=parsed.anchors, ordered=parsed.ordered
            )
        except ReportingError as error:
            if error.code in _EDIT_ANCHOR_FAILURE_CODES:
                return _failure(
                    error.code,
                    error.message,
                    _edit_failure_anchor_details(
                        source, edits, error.details,
                        self.context.script_path, current_sha256,
                    ),
                )
            return _failure(error.code, error.message, error.details)
        remaining_syntax_error: dict[str, Any] | None = None
        try:
            validate_draft_source(self.context, updated)
            tree = ast.parse(updated, filename=self.context.script_path)
        except SyntaxError as error:
            if _parses(source):
                # 与 SWE-agent 的编辑 lint 护栏一致：原本可解析的脚本不接受引入语法
                # 错误的补丁，文件保持不变，避免错误拖到 run_script 才暴露。
                return _syntax_edit_failure(error, current_sha256)
            # 原稿本就无法解析（写入时保留的语法错误草稿）时允许逐步修复，但回执
            # 必须说明仍不可执行及剩余错误位置。
            tree = None
            remaining_syntax_error = {"errorType": "SyntaxError", **_syntax_error_details(error)}
        except ReportingError as error:
            return _failure(error.code, error.message, error.details)
        preflight_warnings: list[dict[str, str]] = []
        if tree is not None:
            violations, preflight_warnings = _collect_preflight(
                tree, updated, "edit_script", self.context
            )
            if violations:
                return _preflight_failure(violations, updated)
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
        # 正式脚本已前进，旧草稿基于过期源码，不得再被提升覆盖当前脚本。
        self._rejected_draft = None
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
            **({"warnings": preflight_warnings} if preflight_warnings else {}),
            "readyForExecution": tree is not None,
            **(
                {"syntaxError": remaining_syntax_error, "nextTools": ["edit_script"]}
                if remaining_syntax_error is not None
                else {}
            ),
            # 精确匹配失败后按行尾空白/统一缩进容错定位的块，提示模型下次逐字复制。
            **({"fuzzyMatches": fuzzy_matches} if fuzzy_matches else {}),
            **identity,
        }

    def _record_patch_format(self, key: str) -> None:
        key = key[:64]
        self.patch_format_counts[key] = self.patch_format_counts.get(key, 0) + 1

    async def _current_script_sha256(self) -> str | None:
        try:
            if not await self.workspace.apath_exists(
                self.context.task_id, self.context.script_path
            ):
                return None
            identity = await self.workspace.ahash_file(
                self.context.task_id, self.context.script_path
            )
        except WorkspaceError:
            return None
        sha256 = identity.get("sha256") if isinstance(identity, Mapping) else None
        return sha256 if isinstance(sha256, str) else None

    async def _edit_rejected_draft(
        self,
        draft: _RejectedDraft,
        edits: Any,
        *,
        anchors: tuple[str | None, ...] = (),
        ordered: bool = False,
    ) -> dict[str, Any]:
        """对隔离草稿打补丁，再按 write_script 同一路径预检、格式化并落盘。"""

        draft_sha256, draft_source = draft.sha256, draft.source
        if await self._current_script_sha256() != draft.base_sha256:
            self._rejected_draft = None
            return _failure(
                "report_code_script_draft_stale",
                "正式脚本在草稿被拒后已发生变化，草稿已作废；请基于 read_script 的当前源码继续局部编辑。",
                {"nextTools": ["read_script", "edit_script"]},
            )
        try:
            updated, fuzzy_matches = apply_edit_blocks(
                draft_source, edits, anchors=anchors, ordered=ordered
            )
        except ReportingError as error:
            if error.code in _EDIT_ANCHOR_FAILURE_CODES:
                details = _edit_failure_anchor_details(
                    draft_source, edits, error.details, self.context.script_path, draft_sha256,
                )
            else:
                details = dict(error.details) if isinstance(error.details, Mapping) else {}
            # 草稿不在磁盘上，read_script 读不到；定位只能依据 sourceExcerpt。
            details.pop("readRange", None)
            details["draftSha256"] = draft_sha256
            details["nextTools"] = ["edit_script"]
            return _failure(error.code, error.message, details)
        result = await self._write_source(updated, promote_draft=True)
        if result.get("ok") is not True:
            # 语法错误或仍有违规时，补丁后的草稿已存为新的隔离草稿。
            return result
        if self.first_patch_applied == "unknown":
            self.first_patch_applied = True
        return {
            **result,
            "status": "draft_promoted",
            "path": self.context.script_path,
            "replacedOccurrences": len(edits),
            "changeSummary": {
                "kind": "draft_edit",
                "replacedOccurrences": len(edits),
                "formatted": result.get("formatted"),
            },
            **({"fuzzyMatches": fuzzy_matches} if fuzzy_matches else {}),
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
        # 只重置探索内核；正式脚本回执基于文件哈希，任何文件变化都会在交付
        # 校验中被识别，无需让模型为未改动的脚本重跑与重审。
        await self.runtime.shutdown(self.context.code_mode_session_id)
        return {
            "ok": True,
            "explorationVariables": {},
            "variablesCleared": True,
        }

    async def view_image(
        self,
        path: str | None = None,
        paths: list[str] | None = None,
        detail: str = "high",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        del run_context
        if detail not in {"high", "original"}:
            return _failure("report_code_visual_detail_invalid", "detail 必须是 high 或 original。")
        target_paths: list[str] = []
        if isinstance(path, str) and path:
            target_paths.append(path)
        if isinstance(paths, list):
            target_paths.extend(str(item) for item in paths if isinstance(item, str) and item)
        if not target_paths:
            return _failure(
                "report_code_visual_path_missing",
                "必须提供 path 或 paths 参数。",
            )

        normalized_paths: list[str] = []
        for raw_path in target_paths:
            try:
                source_path = WorkspaceService.normalize_path(raw_path, allow_root=False)[0]
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
            normalized_paths.append(source_path)
        # 同一路径并发审查会重复调用视觉模型并重复计数。
        normalized_paths = list(dict.fromkeys(normalized_paths))
        # Plotly 交互规格不是图片，交付状态也不要求审查；送入图片检查会得到
        # report_chart_source_invalid，并把模型误导去修复本无问题的脚本。
        skipped_paths = [item for item in normalized_paths if item.endswith(".plotly.json")]
        normalized_paths = [item for item in normalized_paths if item not in skipped_paths]
        if not normalized_paths:
            return _failure(
                "report_code_visual_path_not_image",
                "Plotly 交互规格（.plotly.json）无需视觉审查；只审查 PNG/JPEG 图片输出。",
                {"path": skipped_paths[0]},
            )

        receipts: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        fresh_review_count = 0
        for start in range(0, len(normalized_paths), _DECLARED_OUTPUT_REVIEW_CHUNK_SIZE):
            chunk = normalized_paths[start : start + _DECLARED_OUTPUT_REVIEW_CHUNK_SIZE]
            results = await asyncio.gather(
                *(self._review_one_image(source_path, detail) for source_path in chunk),
                return_exceptions=True,
            )
            chunk_receipts: list[dict[str, Any]] = []
            for index, result in enumerate(results):
                if isinstance(result, asyncio.CancelledError):
                    # 取消异常必须继续向上传播，不能被视觉审查失败回执吞掉。
                    raise result
                if isinstance(result, BaseException) and not isinstance(result, Exception):
                    raise result
                if isinstance(result, dict) and result.get("ok") is False:
                    failures.append(result)
                    continue
                if isinstance(result, dict):
                    chunk_receipts.append(result["receipt"])
                    if result.get("cached") is not True:
                        fresh_review_count += 1
                else:
                    failures.append(self._visual_review_unavailable(chunk[index], result))
            receipts.extend(chunk_receipts)
        if failures:
            # 主失败沿用第一项；同批已完成的审查结论一并返回，不丢弃 critical 问题。
            primary = dict(failures[0])
            if receipts:
                primary["receipts"] = receipts
                primary["freshReviewCount"] = fresh_review_count
            if len(failures) > 1:
                primary["additionalFailures"] = [
                    {
                        "code": item.get("code"),
                        "path": (item.get("details") or {}).get("path"),
                    }
                    for item in failures[1:8]
                ]
            return primary
        skipped = {"skippedInteractivePaths": skipped_paths} if skipped_paths else {}
        if len(normalized_paths) == 1:
            return {
                "ok": True,
                "receipt": receipts[0],
                "freshReviewCount": fresh_review_count,
                **skipped,
            }
        return {
            "ok": True,
            "receipts": receipts,
            "freshReviewCount": fresh_review_count,
            **skipped,
        }

    async def _review_one_image(
        self,
        source_path: str,
        detail: str,
    ) -> dict[str, Any]:
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
                "cached": True,
            }
        if self.vision_reviewer is None:
            return self._visual_review_unavailable(source_path, None)
        review_started_at = perf_counter()
        try:
            reviewed = await self._review_with_retry(source_path, detail)
        except Exception as error:
            if isinstance(error, ReportingError) and error.code in _LOCAL_CHART_REJECTION_CODES:
                logger.warning(
                    "report_code_visual_file_rejected path={} code={}", source_path, error.code,
                )
                return _failure(
                    error.code,
                    "图片未通过本地检查；局部修复生成该图片的代码，再运行和审查。",
                    details={"path": source_path, "reason": error.code},
                )
            return self._visual_review_unavailable(source_path, error)
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

    async def _review_with_retry(self, source_path: str, detail: str) -> ChartVisualInspectionReceipt:
        """视觉审查失败先重试一次，再判为不可用。

        模型层重试只覆盖 API 错误，不覆盖输出解析/校验失败；单次失败即判不可用会
        终止整个 Coding 任务并触发整章 fresh attempt。本地图片检查失败不重试。
        """

        assert self.vision_reviewer is not None
        for attempt in range(2):
            try:
                return ChartVisualInspectionReceipt.model_validate(
                    await self.vision_reviewer.review(
                        self.context.workspace_key, source_path, detail=detail
                    )
                )
            except Exception as error:
                if attempt == 1 or (
                    isinstance(error, ReportingError)
                    and error.code in _LOCAL_CHART_REJECTION_CODES
                ):
                    raise
                logger.warning(
                    "report_code_visual_review_retry path={} error_type={}",
                    source_path,
                    type(error).__name__,
                )
        raise AssertionError("视觉审查重试循环未终止")

    def _visual_review_unavailable(self, path: str, error: Exception | None) -> dict[str, Any]:
        error_type = type(error).__name__ if error is not None else "ReviewerMissing"
        cause = error.__cause__ if error is not None else None
        logger.warning(
            "report_code_visual_review_unavailable path={} error_type={} cause_type={}",
            path, error_type, type(cause).__name__ if cause is not None else "-",
        )
        self.terminal_failure = ReportingError(
            "report_code_visual_review_unavailable",
            "独立视觉审查不可用，已停止当前 Coding 任务；未通过审查的图片不能提交。",
            details={"path": path, "errorType": error_type, "retryable": False},
        )
        return _failure(
            self.terminal_failure.code, str(self.terminal_failure),
            details=self.terminal_failure.details,
        )

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
        # 源码禁止目录推导且只放行签发的完整文件路径，脚本无法自行创建产物父目录；
        # 声明产物位于 chartOutputRoot 子目录时由宿主预先创建，避免 savefig 必然失败。
        for parent in sorted(
            {path.rsplit("/", 1)[0] for path in self.context.declared_output_paths if "/" in path}
        ):
            await self.workspace.aensure_directory(self.context.task_id, parent)

    async def _declared_output_identities(
        self, *, open_rewrite_gate: bool = False
    ) -> tuple[FileIdentity, ...]:
        identities: list[FileIdentity] = []
        missing_paths: list[str] = []
        for path in self.context.declared_output_paths:
            try:
                value = await self.workspace.ahash_file(self.context.task_id, path)
            except WorkspaceError:
                missing_paths.append(path)
                continue
            identities.append(FileIdentity.model_validate(value))
        if missing_paths:
            present_paths = [item.path for item in identities]
            # 同一失败路径上的占位判定与静态诊断共用一次脚本读取。
            source = await self._read_script_source()
            is_placeholder = source is not None and _is_placeholder_script(
                source,
                frozenset(self.context.declared_output_paths),
                self.context.task_kind,
            )
            all_missing = not present_paths
            # 只有 run_script 的产物校验可以据此放行重写；交付状态刷新、提交等
            # 只读校验不得改变重写闸门。
            if open_rewrite_gate and (is_placeholder or all_missing):
                # 占位脚本或零产物脚本：局部编辑契约已被证明难以生效，
                # 直接打开重写闸门，避免在打印 facts/探索结构上消耗预算。
                self._edit_failures_since_progress = REWRITE_GATE_EDIT_FAILURES
            rewrite_hint = (
                "已连续多次局部编辑失败或全部产物缺失，可调用 write_script 整段重写一次，"
                "重写必须完整实现并写出全部声明产物。"
                if self.rewrite_gate_open
                else "不得调用 write_script 整段重写。"
            )
            details: dict[str, Any] = {
                "path": missing_paths[0],
                "missingPaths": missing_paths[:20],
                "presentPaths": present_paths[:20],
            }
            if is_placeholder:
                details["isPlaceholderScript"] = True
            if all_missing:
                details["allDeclaredOutputsMissing"] = True
            example = (
                _declared_output_write_example(
                    missing_paths[0], self.context.declared_output_paths
                )
                if self.context.task_kind == "visualization"
                and missing_paths[0].lower().endswith((".png", ".jpg", ".jpeg", ".plotly.json"))
                else ""
            )
            if example:
                details["writeExample"] = example
            if open_rewrite_gate and source is not None:
                details.update(
                    _missing_output_diagnosis(
                        source, missing_paths, self.context.declared_output_paths
                    )
                )
            raise ReportingError(
                "report_code_declared_output_missing",
                "声明产物不存在，不代表脚本不存在。检查缺失路径对应的写出逻辑，"
                "使用 edit_script 局部修复现有脚本，再 run_script；" + rewrite_hint,
                details=details,
            )
        return tuple(identities)

    async def _declared_output_progress(self) -> dict[str, Any]:
        """脚本中途失败时，给出崩溃前已写出与仍缺失的声明产物。

        多图脚本中单张图的断言失败会中断全部后续写出；模型据此定位出错的那张图
        局部修复，而不是改写已成功的部分。
        """

        present: list[str] = []
        missing: list[str] = []
        for path in self.context.declared_output_paths:
            try:
                await self.workspace.ahash_file(self.context.task_id, path)
            except WorkspaceError:
                missing.append(path)
            else:
                present.append(path)
        progress: dict[str, Any] = {"presentPaths": present, "missingPaths": missing}
        if present and missing:
            progress["outputHint"] = (
                "presentPaths 已在崩溃前写出；只局部修复 traceback 指向的那张图及其后续写出，"
                "不要改动已成功的部分。单张图的数据校验失败应跳过该图的断言或改为软告警，"
                "不得中断其他图的写出。"
            )
        return progress

    async def _read_script_source(self) -> str | None:
        try:
            raw = await self.workspace.read_limited_regular_file(
                self.context.task_id,
                self.context.script_path,
                max_bytes=self.context.max_source_bytes,
            )
            return raw.decode("utf-8")
        except (WorkspaceError, UnicodeDecodeError):
            return None

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
                details.update(await self._declared_output_progress())
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
                outputs = await self._declared_output_identities(open_rewrite_gate=True)
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
        except WorkspaceError as error:
            return await self._workspace_failure(error)
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

    async def _workspace_failure(self, error: WorkspaceError) -> dict[str, Any]:
        """脚本确实不存在时才引导 write_script；其他工作区错误（产物路径是符号链接、
        目录无法创建等）如实回报，避免模型整段重写一个本来存在的脚本。"""

        try:
            script_exists = await self.workspace.apath_exists(
                self.context.task_id, self.context.script_path
            )
        except WorkspaceError:
            script_exists = False
        if not script_exists:
            return _failure(
                "report_code_source_missing",
                "Coding Agent 脚本不存在。",
                {"path": self.context.script_path, "nextTools": ["write_script"]},
            )
        return _failure(
            "report_code_workspace_error",
            "工作区操作失败，脚本本身仍存在；请按 reason 处理后重新运行，不要整段重写脚本。",
            {
                "reason": str(error)[:300],
                "errorType": type(error).__name__,
                "nextTools": ["read_script", "edit_script", "run_script"],
            },
        )

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
        except WorkspaceError as error:
            return await self._workspace_failure(error)
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
                    {"nextTools": ["view_image", "submit_script"]},
                )
            for path, output in output_by_path.items():
                reviewed = reviews[path]
                if reviewed.source_path != path:
                    return _failure(
                        "report_code_visual_review_required",
                        "每个当前图片输出都必须完成独立视觉审查。",
                        {"nextTools": ["view_image", "submit_script"]},
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
                        {"nextTools": ["view_image", "submit_script"]},
                    )
                if reviewed.requires_revision and not self.visual_review_gate_tripped:
                    return _failure(
                        "report_code_visual_revision_required",
                        "独立视觉审查要求修订当前图片输出。",
                        {"nextTools": ["read_script", "edit_script", "run_script"]},
                    )
        submit_warnings: list[dict[str, Any]] = []
        if (
            self.visual_review_gate_tripped
            and self.context.task_kind == "visualization"
        ):
            flagged = [
                path
                for path, reviewed in self.binding.visual_inspection_receipts.items()
                if reviewed.requires_revision
                and path in output_by_path
                and reviewed.sha256 == output_by_path[path].sha256
            ]
            if flagged:
                submit_warnings.append(
                    {
                        "code": "report_code_visual_review_rounds_exhausted",
                        "details": {
                            "criticalRounds": self.consecutive_critical_review_rounds,
                            "flaggedCharts": flagged[:20],
                        },
                    }
                )
                logger.bind(
                    reporting_progress="code_visual_review_gate",
                    critical_rounds=self.consecutive_critical_review_rounds,
                    flagged_charts=len(flagged),
                ).warning(
                    "report_code_visual_review_rounds_exhausted critical_rounds={} flagged={}",
                    self.consecutive_critical_review_rounds,
                    len(flagged),
                )
        self.submitted_receipt = receipt
        return {
            "ok": True,
            "executionReceipt": receipt.model_dump(mode="json", by_alias=True),
            **({"warnings": submit_warnings} if submit_warnings else {}),
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
