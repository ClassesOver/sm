"""Agno function call 参数的有限 JSON 容错边界。"""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Mapping

from agno.tools.function import Function, FunctionCall
from agno.utils import functions as agno_functions
from agno.utils import tools as agno_tools

logger = logging.getLogger(__name__)

_ORIGINAL_GET_FUNCTION_CALL = agno_functions.get_function_call
_VALID_ESCAPES = frozenset('"\\/bfnrt')


def repair_function_call_arguments(value: str) -> str | None:
    """只修复可确定的字符串转义和缺失容器结尾，不补写截断字符串值。"""
    if not value or not value.strip():
        return None
    try:
        json.loads(value)
        return value
    except (TypeError, ValueError):
        pass

    repaired: list[str] = []
    stack: list[str] = []
    in_string = False
    changed = False
    index = 0
    while index < len(value):
        char = value[index]
        if not in_string:
            if char == '"':
                in_string = True
            elif char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in "}]":
                if not stack or stack.pop() != char:
                    return None
            repaired.append(char)
            index += 1
            continue

        if char == '"':
            in_string = False
            repaired.append(char)
            index += 1
            continue
        if char == "\\":
            next_char = value[index + 1] if index + 1 < len(value) else None
            if next_char is None:
                return None
            if next_char == "u":
                digits = value[index + 2 : index + 6]
                if len(digits) == 4 and all(item in "0123456789abcdefABCDEF" for item in digits):
                    repaired.extend(("\\u", digits))
                    index += 6
                    continue
            if next_char in _VALID_ESCAPES:
                repaired.extend(("\\", next_char))
                index += 2
                continue
            repaired.extend(("\\\\", next_char))
            changed = True
            index += 2
            continue
        if ord(char) <= 0x1F:
            repaired.append(json.dumps(char)[1:-1])
            changed = True
        else:
            repaired.append(char)
        index += 1

    # 未闭合字符串意味着字段值本身已经截断，不能通过补引号后执行有副作用的工具。
    if in_string:
        return None
    if stack:
        tail = "".join(repaired).rstrip()
        if tail.endswith((",", ":")):
            return None
        repaired.extend(reversed(stack))
        changed = True
    candidate = "".join(repaired)
    if not changed:
        return None
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return candidate if isinstance(parsed, dict) else None


def _get_function_call_with_repair(
    name: str,
    arguments: str | None = None,
    call_id: str | None = None,
    functions: Mapping[str, Function] | None = None,
) -> FunctionCall | None:
    candidate = arguments
    if isinstance(arguments, str) and arguments:
        try:
            json.loads(arguments)
        except (TypeError, ValueError):
            try:
                ast.literal_eval(arguments)
            except (SyntaxError, ValueError):
                repaired = repair_function_call_arguments(arguments)
                if repaired is not None:
                    candidate = repaired
                    logger.warning(
                        "agno_function_arguments_repaired tool=%s call_id=%s",
                        name,
                        call_id or "",
                    )
    return _ORIGINAL_GET_FUNCTION_CALL(
        name=name,
        arguments=candidate,
        call_id=call_id,
        functions=dict(functions) if functions is not None else None,
    )


def install_agno_function_argument_decoder() -> None:
    """幂等安装到 Agno 的公共工具调用转换入口。"""
    agno_functions.get_function_call = _get_function_call_with_repair
    # agno.utils.tools 使用模块级导入别名，必须同步替换该真实调用点。
    agno_tools.get_function_call = _get_function_call_with_repair
