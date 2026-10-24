"""写作时的计算引用：模型写出运算式，服务端按冻结原值求值并渲染。

正文中的完成率、差额、合计、占比若由模型手算再落成数字，核对端只能按中文写法猜测它
来自哪两个登记值；写作时改用 ``{{calc:...}}`` 声明运算，服务端用未舍入的冻结原值计算，
核对变成重算，不再解析措辞。

语法：``{{calc:<表达式>:<显示单位>}}``；表达式为 ``op(参数, ...)``，参数是另一个表达式或
冻结数值引用 ``fact-<16位十六进制>:<字段>``（即 ``{{value:...}}`` 去掉外壳与单位）。

- ``sum(a, b, ...)``：同单位族求和；``avg(a, b, ...)``：同单位族平均；
- ``diff(a, b)``：a − b，两个百分数之差为百分点；
- ``ratio(a, b)``：a ÷ b × 100%（完成率、占比）；
- ``growth(a, b)``：(a − b) ÷ |b| × 100%（增速）。

运算只组合已登记数值，不引入新的业务口径；单位族不同、操作数冲突或除数为零时不求值。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, localcontext

from ..units import unit_scales
from .numeric_text import (
    PERCENT_POINT,
    _frozen_number_entries,
    format_fact_value,
    frozen_number_catalog,
)

CALC_TOKEN = re.compile(r"\{\{calc:(?P<expr>[a-z]+\([^{}\r\n]*\)):(?P<unit>[^:(){},\s]+)\}\}")
_OPERAND = re.compile(r"(?P<fact>fact-[0-9a-f]{16}):(?P<field>[A-Za-z0-9_.]+)(?::[^,()\s]*)?")
_OPERATIONS = {"sum": (2, 12), "avg": (2, 12), "diff": (2, 2), "ratio": (2, 2), "growth": (2, 2)}
_MAX_DEPTH = 4
_MAX_OPERANDS = 12


@dataclass(frozen=True)
class CalcOperand:
    fact_id: str
    field: str
    value: Decimal
    unit: str


@dataclass(frozen=True)
class CalcResult:
    value: Decimal
    unit: str
    display_unit: str
    operands: tuple[CalcOperand, ...]
    formula: str

    @property
    def text(self) -> str:
        return format_fact_value(self.value, self.unit, self.display_unit)


class _Invalid(ValueError):
    pass


def _parse(expr: str) -> tuple:
    """递归下降解析为 (op, [子节点或 (fact, field)])；不接受字面数字。"""
    text = re.sub(r"\s+", "", expr)
    position = 0
    operands = 0

    def node(depth: int) -> tuple:
        nonlocal position, operands
        if depth > _MAX_DEPTH:
            raise _Invalid("运算嵌套过深")
        operand = _OPERAND.match(text, position)
        if operand:
            position = operand.end()
            operands += 1
            if operands > _MAX_OPERANDS:
                raise _Invalid("操作数过多")
            return ("ref", operand["fact"], operand["field"])
        name = re.match(r"[a-z]+", text[position:])
        if not name or name[0] not in _OPERATIONS:
            raise _Invalid("未知运算")
        position += len(name[0])
        if text[position:position + 1] != "(":
            raise _Invalid("缺少左括号")
        position += 1
        children = [node(depth + 1)]
        while text[position:position + 1] == ",":
            position += 1
            children.append(node(depth + 1))
        if text[position:position + 1] != ")":
            raise _Invalid("缺少右括号")
        position += 1
        low, high = _OPERATIONS[name[0]]
        if not low <= len(children) <= high:
            raise _Invalid("参数个数不符")
        return (name[0], children)

    parsed = node(1)
    if position != len(text):
        raise _Invalid("表达式有多余内容")
    return parsed


def _family(unit: str) -> dict[str, Decimal] | None:
    if unit in {"%", PERCENT_POINT}:
        return {unit: Decimal(1)}
    return unit_scales(unit)


def _align(values: list[tuple[Decimal, str]]) -> tuple[list[Decimal], str]:
    """同单位族换算到首个操作数的单位；百分数与百分点不能混算。"""
    unit = values[0][1]
    scales = _family(unit)
    if scales is None:
        if any(other != unit for _value, other in values):
            raise _Invalid("单位不一致")
        return [value for value, _unit in values], unit
    if any(other not in scales for _value, other in values):
        raise _Invalid("单位族不一致")
    return [value * scales[other] / scales[unit] for value, other in values], unit


class CalcEvaluator:
    """按一组已核验文件求值；冲突的冻结数值不能作为操作数。"""

    def __init__(self, contents: Iterable[str]):
        contents = tuple(contents)
        catalog = frozen_number_catalog(contents)
        self._values: dict[tuple[str, str], tuple[Decimal, str]] = {}
        blocked: set[tuple[str, str]] = set()
        for token, value, unit, _target in _frozen_number_entries(contents):
            parts = token[2:-2].split(":")
            if len(parts) < 3 or value is None or not unit:
                continue
            key = (parts[1], parts[2])
            if catalog.get(token) == "数值待核实":
                blocked.add(key)
                continue
            number = (Decimal(str(value)), unit)
            if self._values.setdefault(key, number) != number:
                blocked.add(key)
        for key in blocked:
            self._values.pop(key, None)

    def evaluate(self, token: str) -> CalcResult | None:
        result = self._run(token)
        return result if isinstance(result, CalcResult) else None

    def failure(self, token: str) -> str | None:
        """无法求值的原因（面向读者，不含内部编号）；可求值时返回 None。"""
        result = self._run(token)
        return None if isinstance(result, CalcResult) else result

    def _run(self, token: str) -> CalcResult | str:
        match = CALC_TOKEN.fullmatch(token.strip())
        if not match:
            return "计算引用格式无法识别"
        try:
            tree = _parse(match["expr"])
            operands: list[CalcOperand] = []
            with localcontext() as context:
                context.prec = 50
                value, unit, formula = self._evaluate(tree, operands)
        except _Invalid as error:
            return str(error)
        except ArithmeticError:
            return "数值运算溢出"
        display = match["unit"]
        if display == "百分点":
            display = PERCENT_POINT
        target_family = _family(unit)
        if target_family is None or display not in target_family:
            return f"结果单位为{unit}，与所写显示单位{match['unit']}不一致"
        return CalcResult(value, unit, display, tuple(operands), formula)

    def _evaluate(self, node: tuple, operands: list[CalcOperand]) -> tuple[Decimal, str, str]:
        if node[0] == "ref":
            _kind, fact_id, field = node
            found = self._values.get((fact_id, field))
            if found is None:
                raise _Invalid("操作数不是登记数值或存在冲突")
            operands.append(CalcOperand(fact_id, field, found[0], found[1]))
            return found[0], found[1], f"{fact_id}:{field}"
        name, children = node
        results = [self._evaluate(child, operands) for child in children]
        values, unit = _align([(value, unit) for value, unit, _formula in results])
        formula = f"{name}({', '.join(formula for _value, _unit, formula in results)})"
        if name == "sum":
            return sum(values, Decimal(0)), unit, formula
        if name == "avg":
            return sum(values, Decimal(0)) / len(values), unit, formula
        if name == "diff":
            if unit == PERCENT_POINT:
                raise _Invalid("百分点不能再求差")
            return values[0] - values[1], PERCENT_POINT if unit == "%" else unit, formula
        if values[1] == 0:
            raise _Invalid("除数为零")
        if name == "ratio":
            return values[0] / values[1] * 100, "%", formula
        return (values[0] - values[1]) / abs(values[1]) * 100, "%", formula


def calc_tokens(markdown: str) -> list[str]:
    return [match[0] for match in CALC_TOKEN.finditer(markdown)]
