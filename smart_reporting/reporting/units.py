"""确定性计算和显示共用的已确认单位倍率。"""

from decimal import Decimal

MONEY_UNITS = {"元": Decimal(1), "万元": Decimal(10_000), "亿元": Decimal(100_000_000)}
VISIT_UNITS = {"人次": Decimal(1), "万人次": Decimal(10_000)}

# 正文核对须读取完整量纲，不能把“30元/人次”截成“30元”。
REPORT_VALUE_UNIT_PATTERN = (
    r"(?:亿元|万元|元|万人次|人次|床日|%)"
    r"(?:[/／](?:万人次|人次|床日|人|次|床|日|天|月|年))?(?![/／])"
)


_UNIT_FAMILIES = {unit: family for family in (MONEY_UNITS, VISIT_UNITS) for unit in family}


def unit_scales(unit: str | None) -> dict[str, Decimal] | None:
    # 核对时每个候选值都要查一次量纲（整份报告上百万次），直接查表。
    return _UNIT_FAMILIES.get(unit) if unit is not None else None


# 只出现在数据源口径里的单位（财务明细常按“千元”“百万元”入账）：参与跨数据集换算，
# 不加入正文显示与核对的单位族，避免数值目录按这些单位展开候选写法。
_SOURCE_ONLY_SCALES = {
    "千元": ("元", Decimal(1_000)),
    "百万元": ("元", Decimal(1_000_000)),
}


def _base_scale(unit: str | None) -> tuple[dict[str, Decimal], Decimal] | None:
    if unit in _SOURCE_ONLY_SCALES:
        base, scale = _SOURCE_ONLY_SCALES[unit]
        return _UNIT_FAMILIES[base], scale
    scales = unit_scales(unit)
    return (scales, scales[unit]) if scales is not None and unit is not None else None


def unit_conversion_scale(source: str | None, target: str | None) -> Decimal | None:
    """同单位（含旧记录未登记单位）无需换算；不同量纲不猜测倍率。"""
    if source == target:
        return Decimal(1)
    source_scale, target_scale = _base_scale(source), _base_scale(target)
    if source_scale is None or target_scale is None or source_scale[0] is not target_scale[0]:
        return None
    return source_scale[1] / target_scale[1]
