"""Reporting Worker 工具的无状态输入校验与规范化。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import jmespath
from agno.tools import Function
from jsonpointer import EndOfList, JsonPointer, JsonPointerException, escape
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from ..models import ReportingError

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


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
