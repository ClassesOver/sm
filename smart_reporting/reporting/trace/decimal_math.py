"""新旧计算路径共享的有限Decimal数学；不加载旧业务配置。"""

from decimal import Decimal, localcontext


def snapshot_difference(current: Decimal, baseline: Decimal) -> Decimal:
    if not current.is_finite() or not baseline.is_finite():
        raise ValueError("累计快照必须是有限数")
    with localcontext() as context:
        # 同时覆盖高精度Decimal和旧路径的完整有限float范围。
        context.prec = max(700, max(current.adjusted(), baseline.adjusted()) - min(current.as_tuple().exponent, baseline.as_tuple().exponent) + 2)
        return current - baseline
