"""Reporting 工具的无状态输入校验与规范化。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import jmespath
from jsonpointer import EndOfList, JsonPointer, JsonPointerException, escape
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from ..models import ReportingError

JMESPATH_FUNCTION_NAMES = tuple(sorted(jmespath.functions.Functions.FUNCTION_TABLE))


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def analysis_patch_parameters() -> dict[str, Any]:
    """返回受限标准 unified diff 的 schema。"""
    return {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "minLength": 1,
                "description": "标准 unified diff；路径必须使用 a/ 与 b/ 前缀。",
            },
            "expected_sha256": {
                "type": "object",
                "description": "已有文件的基线 SHA-256 映射；新增文件不填写对应项。",
                "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        },
        "required": ["patch"],
        "additionalProperties": False,
    }


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
        result: dict[str, Any] = {"counts": [], "bin_edges": []}
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
                # maxItems 是数组输出的元素上限，不得把 object 的标量字段当作待裁剪项。
                # facts 的指标对象必须完整返回 total、期间和聚合方式，否则模型会把同一
                # 受信事实误判为缺失并重复查询；深度、长字符串和数组元素仍受下方边界约束。
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
