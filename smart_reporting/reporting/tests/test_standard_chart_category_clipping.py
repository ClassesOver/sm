"""固定画布的中文分类标签不能通过未重叠检查后被静默裁切。"""

import json

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartCanvas


def chinese_label_plan(form, crop, layout='manual'):
    label = '合成机构超长中文分类标签用于验证画布边缘完整显示'
    document = {'columns': ['label', 'actual'], 'rows': [[label, -12]],
                'columnMeta': {'actual': {'unit': '人次'}}}
    plan, inputs = build(document, form=form)
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_canvas = StandardChartCanvas(
        sizeMode='fixed', width=4, height=3, crop=crop, layout=layout, labelWrap=40,
    )
    return plan, inputs, label


@pytest.mark.parametrize('form', ['bar', 'barh'])
def test_fixed_canvas_rejects_clipped_chinese_category_without_label_overlap(render, form):  # noqa: F811
    plan, inputs, _ = chinese_label_plan(form, 'canvas')
    with pytest.raises(ValueError, match='standard_chart_layout_unresolved: 分类标签超出画布'):
        render(plan, inputs)


@pytest.mark.parametrize('form', ['bar', 'barh'])
def test_tight_crop_keeps_long_chinese_label_and_negative_value(render, form):  # noqa: F811
    from PIL import Image

    plan, inputs, label = chinese_label_plan(form, 'tight')
    figure = render(plan, inputs)
    axis = figure.axes[0]
    ticks = axis.get_xticklabels() if form == 'bar' else axis.get_yticklabels()
    assert [tick.get_text() for tick in ticks] == [label]
    bar, = axis.containers[0]
    assert (bar.get_height() if form == 'bar' else bar.get_width()) == -12
    assert json.loads(inputs.files[0].content)['rows'] == [[label, -12]]
    # tight 导出按图元边界扩大文件；不以 nominal canvas 限制其标签。
    with Image.open('chart.png') as image:
        assert image.width > figure.bbox.width or image.height > figure.bbox.height
