"""正式计算与数据画像共用有限筛选运算，值始终通过参数绑定。"""

from collections.abc import Callable

from sqlglot import exp

from ..models import ReportingError
from .models import PolicyFilter, Scalar


def compile_filter(condition: PolicyFilter, column: exp.Column,
    parameter: Callable[[Scalar], exp.Expression]) -> exp.Expression:
    if condition.operator == 'is_null':
        return exp.Is(this=column, expression=exp.Null())
    if condition.operator == 'in':
        return exp.In(this=column, expressions=[parameter(value) for value in condition.values])
    if condition.values[0] is None:
        raise ReportingError('metric_filter_null_comparison', '空值筛选须使用明确的is_null规则。')
    operations = {'eq': exp.EQ, 'ne': exp.NEQ, 'lt': exp.LT, 'le': exp.LTE, 'gt': exp.GT, 'ge': exp.GTE}
    return operations[condition.operator](this=column, expression=parameter(condition.values[0]))
