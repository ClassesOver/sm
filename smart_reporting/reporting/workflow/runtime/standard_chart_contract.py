"""规划器与标准编译器共享的机器契约；业务描述不参与类型推断。"""

from typing import Literal, NamedTuple, get_args

StandardChartForm = Literal[
    'line', 'bar', 'barh', 'stacked-bar', 'stacked-area', 'stacked-total',
    'summary-bars', 'scatter', 'bubble', 'heatmap', 'waterfall', 'boxplot',
    'pie', 'donut', 'radar', 'funnel', 'sankey', 'custom',
]
SourceLabelMode = Literal['exact', 'month', 'month_of_year']
SummaryAggregation = Literal['row', 'sum']

# 只兼容旧计划已支持的完整名称，不解析自然语言或扩展关键词规则。
_LEGACY_FORMS = {
    '折线图': 'line', '多系列折线图': 'line',
    '柱状图': 'bar', '分组柱状图': 'bar', '横向条形图': 'barh',
    '堆叠柱状图': 'stacked-bar', '堆叠面积图': 'stacked-area',
    '堆叠柱合计折线图': 'stacked-total', '单行指标对比图': 'summary-bars',
    '散点图': 'scatter', '气泡图': 'bubble', '热力图': 'heatmap',
    '瀑布图': 'waterfall', '箱线图': 'boxplot',
}
_FORMS = tuple(form for form in get_args(StandardChartForm) if form != 'custom')


def resolve_standard_form(chart):
    explicit = getattr(chart, 'standard_form', None)
    if explicit is not None:
        return explicit if explicit in _FORMS else None
    legacy = chart.visual_form
    return legacy if legacy in _FORMS else _LEGACY_FORMS.get(legacy)


def standard_chart_capabilities():
    return {
        'forms': list(get_args(StandardChartForm)),
        'sourceLabelModes': list(get_args(SourceLabelMode)),
        'summaryAggregations': list(get_args(SummaryAggregation)),
        # 非笛卡尔图族仅消费显示单位，不能承诺忽略其他坐标参数。
        'familyAxesOverrides': ['leftDisplayUnit'],
        'families': {
            'composition': {'forms': ['pie', 'donut'], 'denominatorModes': ['bound_sum', 'reference']},
            'radar': {'axes': [3, 8], 'maxEntities': 8, 'scaleEndpoints': 'frozen_scalar'},
            'funnel': {'ratioBases': ['none', 'first', 'previous'], 'order': ['source', 'explicit']},
            'sankey': {'topology': 'DAG', 'maxNodes': 60, 'maxEdges': 480,
                       'encodingFields': ['xField', 'yField', 'valueField']},
        },
    }


class StandardChartConfig(NamedTuple):
    """编译期逐图配置；写入脚本时转为普通元组，字段顺序即脚本解包顺序。"""

    input_path: str
    digest: str
    output_path: str
    title: str
    form: str
    label_column: str | None
    value_columns: list
    category_column: str | None
    unit: str | None
    is_percent: bool | None
    annotations: list
    axes_policy: dict
    metadata: list
    total_field: str | None
    policy: dict
