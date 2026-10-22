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


def unit_conversion_scale(source: str | None, target: str | None) -> Decimal | None:
    """同单位（含旧记录未登记单位）无需换算；不同量纲不猜测倍率。"""
    if source == target:
        return Decimal(1)
    scales = unit_scales(source)
    return scales[source] / scales[target] if scales is not None and target in scales else None
