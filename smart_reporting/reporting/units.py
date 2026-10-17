"""确定性计算和显示共用的已确认单位倍率。"""

from decimal import Decimal

MONEY_UNITS = {"元": Decimal(1), "万元": Decimal(10_000), "亿元": Decimal(100_000_000)}
VISIT_UNITS = {"人次": Decimal(1), "万人次": Decimal(10_000)}


def unit_scales(unit: str | None) -> dict[str, Decimal] | None:
    return next((family for family in (MONEY_UNITS, VISIT_UNITS) if unit in family), None)


def unit_conversion_scale(source: str | None, target: str | None) -> Decimal | None:
    """同单位（含旧记录未登记单位）无需换算；不同量纲不猜测倍率。"""
    if source == target:
        return Decimal(1)
    scales = unit_scales(source)
    return scales[source] / scales[target] if scales is not None and target in scales else None
