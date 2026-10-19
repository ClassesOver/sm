"""正文复核共用的分句规则、数值写法与事实包解析。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from ..units import REPORT_VALUE_UNIT_PATTERN

_VALUE = re.compile(
    r"(?<![\d.,])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    rf"({REPORT_VALUE_UNIT_PATTERN})"
)


# 百分点核对按两两相减，候选过多时跳过以免复核耗时失控。
_MAX_PERCENT_POINT_CANDIDATES = 400


# 分句边界：千分位逗号（“34,567”“1,234,567”）不是分句符，否则“同比增加1,234.56万元”
# 会拆成“同比增加1”与“234.56万元”，口径与语境检查都看不到完整数值。
_CLAUSE_BREAK = re.compile(r"[。；，\n]|(?<!\d),|,(?!\d{3}(?!\d))")


_CLAUSE_BREAK_WITH_MARKS = re.compile(r"[。！？；，\n]|(?<!\d),|,(?!\d{3}(?!\d))")


def _documents(contents: Iterable[str]) -> list[dict[str, Any]]:
    documents = []
    for content in contents:
        try:
            value = json.loads(content)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            documents.append(value)
    return documents


def _numeric_literals(value: Any) -> set[Decimal]:
    """补充 evidence 的原始数值也可用；不从模型摘要文字反推数字。"""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        return {number} if number.is_finite() else set()
    if isinstance(value, dict):
        return set().union(*(_numeric_literals(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_numeric_literals(item) for item in value))
    return set()


_AGGREGATION_NOUNS = {
    "sum": "合计", "count": "计数", "average": "平均值", "min": "最小值", "max": "最大值",
    "count_distinct": "去重计数",
}


_CHINESE_DIGITS = {**{word: index for index, word in enumerate("一二三四五六七八九", 1)}, "两": 2}
