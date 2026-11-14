"""同一登记图表多次引用也需保持各自版面尺寸并执行DPI限制。"""

from hashlib import sha256

from PIL import Image
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_runtime.chart_image_dpi import (
    ChartImageSource,
    apply_chart_derivatives,
    chart_image_boxes,
    derive_chart_image,
    read_pdf_chart_dpi,
)
from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
from smart_reporting.reporting.tests.test_report_runtime_full_render import _build_image_workspace


def test_repeated_chart_derivatives_keep_each_measured_box(tmp_path):
    path = tmp_path / 'chart.png'
    Image.new('RGB', (1000, 500), '#345678').save(path)
    raw = path.read_bytes()
    source = ChartImageSource('chart', path.name, len(raw), sha256(raw).hexdigest())
    derived = derive_chart_image(path, source, display_width_css_px=96, display_height_css_px=48, target_dpi=96)
    original = '<img src="chart.png" data-pdf-chart-id="chart"><img src="chart.png" data-pdf-chart-id="chart">'
    rendered = apply_chart_derivatives(original, {'chart': derived}, {'chart': [(96, 48), (192, 96)]})
    assert rendered.count('data:image/png;base64,') == 2
    assert 'width:96.000000px;height:48.000000px' in rendered
    assert 'width:192.000000px;height:96.000000px' in rendered


def test_actual_pdf_different_repeated_boxes_keep_geometry_and_dpi(tmp_path):
    from weasyprint import HTML

    path = tmp_path / 'chart.png'
    Image.new('RGB', (1000, 500), '#345678').save(path)
    raw = path.read_bytes()
    source = ChartImageSource('chart', path.name, len(raw), sha256(raw).hexdigest())
    original = ('<html lang="zh"><body>'
        f'<img src="{path.as_uri()}" data-pdf-chart-id="chart" style="width:96px;height:48px">'
        f'<img src="{path.as_uri()}" data-pdf-chart-id="chart" style="width:192px;height:96px">'
        '</body></html>')
    before = chart_image_boxes(HTML(string=original).render())
    assert before == {'chart': [(96, 48), (192, 96)]}
    derived = derive_chart_image(path, source, display_width_css_px=96, display_height_css_px=48, target_dpi=96)
    final = HTML(string=apply_chart_derivatives(original, {'chart': derived}, before)).render()
    assert chart_image_boxes(final) == before
    output = tmp_path / 'different-boxes.pdf'
    final.write_pdf(output)
    rows = read_pdf_chart_dpi(output, {'chart': derived})['chart']
    assert len(rows) == 2
    assert sorted(round(row['widthDpi']) for row in rows) == [48, 96]
    assert all(max(row['widthDpi'], row['heightDpi']) <= 96.05 for row in rows)
    assert path.read_bytes() == raw


def test_actual_pdf_repeated_registered_chart_is_resampled_without_changing_source(tmp_path):
    root = tmp_path / 'workspace'
    state = _build_image_workspace(root)
    chart = root / 'reports/r1/chart.png'
    Image.new('RGB', (1920, 800), '#345678').save(chart)
    raw = chart.read_bytes()
    markdown = root / 'reports/r1/revision-1/draft/report.md'
    text = markdown.read_text()
    text += '\n\n![第二次图表](../../../r1/chart.png)\n'
    # 沿用夹具已有的相对图片路径，避免引入另一套路径授权。
    import re

    original_path = re.search(r'!\[[^]]*\]\(([^)]+)\)', text).group(1)
    markdown.write_text(text.replace('../../../r1/chart.png', original_path))
    state['_formatPreferences'] = {'pdf': resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'DPI验证编制'}, 'pdf': {'cover': False, 'toc': False,
            'sources': False, 'charts': {'imageDpi': 96}}}), 'pdf')}
    result = ReportRuntime(root).render_markdown(state,
        'reports/r1/revision-1/draft/report.md', 'reports/r1/revision-1/report.pdf',
        '.reporting-tmp/workspace-report-repeated-chart-render/render.pdf',
        chart_images=[{'chartId': 'repeated-chart', 'path': 'reports/r1/chart.png',
            'size': len(raw), 'sha256': sha256(raw).hexdigest()}])
    evidence = result['render']['chartImageDpi']
    assert len(evidence) == 1
    assert len(evidence[0]['draws']) == 2
    assert all(max(row['widthDpi'], row['heightDpi']) <= 96.05 for row in evidence[0]['draws'])
    assert chart.read_bytes() == raw
    assert PdfReader(root / 'reports/r1/revision-1/report.pdf').pages
