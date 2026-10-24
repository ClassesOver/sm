"""模型可见的短编号引用。

模型照抄 ``{{value:fact-<16位>:<选择器>:<单位>}}`` 与 64 位断言编号时常抄错编号、自造选择器或写错
嵌套编号。提示边界把引用身份换成短编号，模型输出入口再换回完整引用；服务端内部（对齐、复核、
渲染、溯源索引、编辑器）始终使用完整引用：

- 数值引用 ``{{value:事实:选择器:单位}}`` ↔ ``{{N编号:单位}}``，同一身份的元、万元、亿元共用编号；
- 计算引用操作数 ``事实:选择器`` ↔ ``N编号``；
- 受控断言 ``{{assert:assert-<64位>}}`` ↔ ``{{A编号}}``。

编号按提示正文中首次出现的顺序分配，单次模型调用内稳定；只为已登记的引用身份分配编号，
未登记的完整写法原样保留。未知编号解码为可识别的未登记引用，由数值引用关口交回模型纠正，
不会以原样残留在正文中。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .value_references import REVOKED_SELECTOR, UNKNOWN_FACT

_FULL_VALUE = re.compile(r"\{\{value:(?P<fact>[^:{}\s]+):(?P<selector>[^:{}\s]+):(?P<unit>[^:{}\s]*)\}\}")
_FULL_ASSERT = re.compile(r"\{\{assert:(?P<id>assert-[0-9a-f]{64})\}\}")
_CALC = re.compile(r"\{\{calc:(?P<expr>[^{}\r\n]*\)):(?P<unit>[^:(){},\s]+)\}\}")
_FULL_OPERAND = re.compile(r"(?<![\w-])(?P<fact>fact-[0-9a-f]{16}):(?P<selector>[A-Za-z0-9_.\-]+)")

_VALUE_HANDLE = re.compile(r"\{\{\s*[Nn](?P<number>\d+)\s*(?:[:：]\s*(?P<unit>[^{}\s:：]*)\s*)?\}\}")
_ASSERT_HANDLE = re.compile(r"\{\{\s*[Aa](?P<number>\d+)\s*\}\}")
_OPERAND_HANDLE = re.compile(r"(?<![\w-])[Nn](?P<number>\d+)(?![\w])")
# 模型偶尔在计算式里写带外壳的编号 ratio({{N3:元}},{{N7:元}})；先去掉外壳再解析。
_NESTED_HANDLE = re.compile(r"(\{\{calc:[^{}]*?)\{\{\s*([Nn]\d+)(?:\s*[:：][^{}]*?)?\s*\}\}")


class NumberHandles:
    """单次模型调用内的短编号表：提示边界编码，模型输出入口解码。"""

    def __init__(self, catalog: Iterable[str] | None = None) -> None:
        # 给定数值目录时只为其中的引用身份分配编号；不给时（单元测试）为所有完整引用分配。
        self._registered = None if catalog is None else {
            (match["fact"], match["selector"]) for token in catalog if (match := _FULL_VALUE.fullmatch(token))
        }
        self._identities: dict[str, tuple[str, str]] = {}
        self._handles: dict[tuple[str, str], str] = {}
        self._assertions: dict[str, str] = {}
        self._assertion_handles: dict[str, str] = {}

    def _value_handle(self, fact: str, selector: str) -> str | None:
        identity = (fact, selector.removeprefix(REVOKED_SELECTOR))
        if self._registered is not None and identity not in self._registered:
            return None
        handle = self._handles.get(identity)
        if handle is None:
            handle = f"N{len(self._handles) + 1}"
            self._handles[identity] = handle
            self._identities[handle] = identity
        return handle

    def _assertion_handle(self, assertion_id: str) -> str:
        handle = self._assertion_handles.get(assertion_id)
        if handle is None:
            handle = f"A{len(self._assertion_handles) + 1}"
            self._assertion_handles[assertion_id] = handle
            self._assertions[handle] = assertion_id
        return handle

    def encode(self, text: str) -> str:
        """完整引用 → 短编号；模型写错的未知编号还原为模型原写法。"""

        def value(match: re.Match[str]) -> str:
            if match["fact"] == UNKNOWN_FACT:
                handle = match["selector"]
            else:
                handle = self._value_handle(match["fact"], match["selector"])
            if handle is None:
                return match[0]
            return "{{" + handle + (":" + match["unit"] if match["unit"] else "") + "}}"

        def calc(match: re.Match[str]) -> str:
            expr = _FULL_OPERAND.sub(
                lambda item: self._value_handle(item["fact"], item["selector"]) or item[0], match["expr"],
            )
            return "{{calc:" + expr + ":" + match["unit"] + "}}"

        text = _FULL_VALUE.sub(value, text)
        text = _CALC.sub(calc, text)
        return _FULL_ASSERT.sub(lambda match: "{{" + self._assertion_handle(match["id"]) + "}}", text)

    def decode(self, text: str) -> str:
        """短编号 → 完整引用；已是完整写法的引用原样保留。"""
        while True:
            collapsed = _NESTED_HANDLE.sub(r"\1\2", text)
            if collapsed == text:
                break
            text = collapsed

        def calc(match: re.Match[str]) -> str:
            def operand(item: re.Match[str]) -> str:
                identity = self._identities.get(f"N{int(item['number'])}")
                # 未知编号保留原样，由计算引用求值报告“引用编号不存在”。
                return f"{identity[0]}:{identity[1]}" if identity else item[0]

            return "{{calc:" + _OPERAND_HANDLE.sub(operand, match["expr"]) + ":" + match["unit"] + "}}"

        def value(match: re.Match[str]) -> str:
            handle = f"N{int(match['number'])}"
            fact, selector = self._identities.get(handle, (UNKNOWN_FACT, handle))
            return "{{value:" + fact + ":" + selector + ":" + (match["unit"] or "") + "}}"

        def assertion(match: re.Match[str]) -> str:
            handle = f"A{int(match['number'])}"
            assertion_id = self._assertions.get(handle)
            if assertion_id is None:
                # 未知断言编号解码为不存在的断言，展开时按证据不足处理；再编码时还原为模型原写法。
                assertion_id = "assert-" + hashlib.sha256(f"unknown:{handle}".encode()).hexdigest()
                self._assertions[handle] = assertion_id
                self._assertion_handles[assertion_id] = handle
            return "{{assert:" + assertion_id + "}}"

        text = _CALC.sub(calc, text)
        text = _VALUE_HANDLE.sub(value, text)
        return _ASSERT_HANDLE.sub(assertion, text)


__all__ = ["NumberHandles"]
