"""Office 偏好必须作用于实际原生文件，不能改动业务值或公式。"""
import zipfile

import pytest
from openpyxl import load_workbook
from pptx import Presentation

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.delivery.xlsx import build_workbook


@pytest.mark.parametrize('accent,contrast', [('#654321', 'FFFFFFFF'), ('#ffffff', 'FF000000')])
def test_workbook_common_font_and_accent_reach_native_header_with_task_override(tmp_path, accent, contrast):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {
        'signer': '样式验证', 'font': 'serif', 'accentColor': accent}}), 'xlsx')
    path = tmp_path / 'common.xlsx'
    build_workbook(output_path=path, title='样式', period='2026', sheets=({'name': '数据',
        'rows': [['标题', {'value': '单次指定', 'style': {'fillColor': '#123456'}}], ['原值', 1234.56]]},),
        preferences=prefs, generated_date='2026-11-12')
    sheet = load_workbook(path)['数据']
    assert sheet['A1'].fill.fgColor.rgb == 'FF' + accent[1:].upper()
    assert sheet['A1'].font.color.rgb == contrast
    assert sheet['B1'].fill.fgColor.rgb == 'FF123456'
    assert sheet['A1'].font.name == 'Noto Serif CJK SC'
    assert sheet['B2'].font.name == 'Noto Serif CJK SC'
    assert sheet['B2'].value == 1234.56


def test_workbook_preferences_preserve_values_formulas_and_add_native_printed_signature(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({"common": {"signer": "报告编制人"}, "xlsx": {
        "numbers": {"decimalPlaces": 3, "negativeStyle": "parentheses"}, "body": {"size": 12},
        "print": {"page": {"paper": "A3", "orientation": "landscape"},
            "headerFooter": {"header": {"center": "{title}"}, "footer": {"right": "{page}/{pages}"}}}}}), "xlsx")
    path = tmp_path / "report.xlsx"
    result = build_workbook(output_path=path, title="测试报告", period="2026年", sheets=({"name": "业务数据",
        "rows": [["指标", "金额"], ["收入", -1234.5678], ["合计", {"value": -1234.5678, "formula": "B2"}]]},),
        preferences=prefs, generated_date="2026-11-12")
    book = load_workbook(path)
    sheet = book['业务数据']
    assert sheet['B2'].value == -1234.5678 and sheet['B3'].value == '=B2'
    assert sheet['B2'].number_format == '#,##0.000;(#,##0.000)'
    assert sheet['B2'].font.sz == 12
    assert sheet.freeze_panes == 'A2' and sheet.auto_filter.ref == 'A1:B3'
    assert sheet.page_setup.paperSize == 8 and sheet.page_setup.orientation == 'landscape'
    assert sheet.oddHeader.center.text == '测试报告'
    assert sheet.oddFooter.right.text == '&P/&N'
    assert sheet.page_margins.left == pytest.approx(22 / 25.4)
    assert '说明' in book.sheetnames
    notes = book['说明']
    assert notes['A2'].value == '报告编制人' and notes['A3'].value == '2026年11月12日'
    assert notes.print_area
    assert result.sheet_count == 2
    with zipfile.ZipFile(path) as archive:
        assert b'<v>-1234.5678</v>' in archive.read('xl/worksheets/sheet1.xml')


def test_slides_preferences_add_editable_closing_signature_and_native_page_fields(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({"common": {"signer": "报告编制人"}, "pptx": {
        "aspectRatio": "4:3", "signature": {"description": "复核通过后使用"},
        "footer": {"left": "{date}", "right": "第 {slide}/{slides} 页"}}}), "pptx")
    path = tmp_path / "report.pptx"
    built = build_editable_pptx(output_path=path, title="分析报告", period="2026年", theme="executive",
        slides=({"title": "本期情况", "bullets": ["保留正文"], "evidenceIds": ["a1"]},),
        preferences=prefs, generated_date="2026-11-12")
    deck = Presentation(path)
    assert deck.slide_width / deck.slide_height == pytest.approx(4 / 3)
    last = '\n'.join(shape.text for shape in deck.slides[-1].shapes if shape.has_text_frame)
    assert '报告编制人' in last and '2026年11月12日' in last and '复核通过后使用' in last
    assert any('保留正文' in shape.text for shape in deck.slides[1].shapes if shape.has_text_frame)
    with zipfile.ZipFile(path) as archive:
        assert b'type="slidenum"' in archive.read('ppt/slides/slide2.xml')
    assert built.slide_count == 3


@pytest.mark.parametrize('places,thousands,negative,expected', [
    (0, False, 'minus', '0;-0'),
    (1, True, 'red', '#,##0.0;[Red]-#,##0.0'),
    (4, False, 'parentheses', '0.0000;(0.0000)'),
])
def test_workbook_numeric_display_keeps_raw_values_formula_cache_and_explicit_task_style(
    tmp_path, places, thousands, negative, expected,
):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'xlsx': {'numbers': {'decimalPlaces': places, 'thousandsSeparator': thousands,
            'negativeStyle': negative}}}), 'xlsx')
    path = tmp_path / 'numeric.xlsx'
    build_workbook(output_path=path, title='数字格式', period='2026年', sheets=({'name': '数据',
        'rows': [['项目', '数值'], ['原值', -1234.5678],
            ['公式', {'value': -2469.1356, 'formula': 'B2*2'}],
            ['任务指定', {'value': 0.125, 'style': {'numberFormat': '0.0%'}}]]},),
        preferences=prefs, generated_date='2026-11-12')
    sheet = load_workbook(path)['数据']
    assert sheet['B2'].value == -1234.5678
    assert sheet['B2'].number_format == expected
    assert sheet['B3'].value == '=B2*2' and sheet['B3'].number_format == expected
    assert load_workbook(path, data_only=True)['数据']['B3'].value == -2469.1356
    assert sheet['B4'].value == 0.125 and sheet['B4'].number_format == '0.0%'


def test_workbook_custom_margins_are_native_print_settings_without_touching_cells(tmp_path):
    margins = {'top': 12.7, 'bottom': 16.5, 'left': 30, 'right': 12.7}
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'xlsx': {'print': {'page': {'paper': 'Letter', 'orientation': 'landscape', 'margins': margins}}}}), 'xlsx')
    path = tmp_path / 'margins.xlsx'
    build_workbook(output_path=path, title='页边距', period='2026', sheets=({'name': '数据',
        'rows': [['项目', '数值'], ['原值', 1234.56]]},), preferences=prefs, generated_date='2026-11-12')
    sheet = load_workbook(path)['数据']
    for side, value in margins.items():
        assert getattr(sheet.page_margins, side) == pytest.approx(value / 25.4)
    assert sheet.page_setup.paperSize == 1
    assert sheet.page_setup.orientation == 'landscape'
    assert sheet['B2'].value == 1234.56


@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
def test_signature_style_controls_actual_native_text(format, tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '样式编制'},
        format: {'signature': {'font': 'serif', 'size': 14, 'color': '#123456', 'align': 'left', 'bold': True}}}), format)
    path = tmp_path / ('signature.' + format)
    if format == 'xlsx':
        build_workbook(output_path=path, title='样式', period='2026', sheets=({'name': '数据', 'rows': [['数值'], [123]]},),
            preferences=prefs, generated_date='2026-11-12')
        cell = load_workbook(path)['说明']['A2']
        assert cell.value == '样式编制'
        assert cell.font.name == 'Noto Serif CJK SC' and cell.font.sz == 14 and cell.font.bold
        assert cell.font.color.rgb[-6:] == '123456' and cell.alignment.horizontal == 'left'
    else:
        build_editable_pptx(output_path=path, title='样式', period='2026', theme='executive',
            slides=({'title': '正文', 'bullets': ['原文']},), preferences=prefs, generated_date='2026-11-12')
        from pptx.enum.text import PP_ALIGN

        paragraph = next(paragraph for shape in Presentation(path).slides[-1].shapes if shape.has_text_frame
            for paragraph in shape.text_frame.paragraphs if paragraph.text == '样式编制')
        assert paragraph.alignment == PP_ALIGN.LEFT
        font = paragraph.runs[0].font
        assert font.name == 'Noto Serif CJK SC' and font.size.pt == 14 and font.bold
        assert str(font.color.rgb) == '123456'


@pytest.mark.parametrize('scale,width,height,repeat', [(75, None, None, 0), (None, 1, 1, 2), (None, 2, None, 1)])
def test_workbook_print_modes_preserve_values_and_native_settings(tmp_path, scale, width, height, repeat):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '打印编制'},
        'xlsx': {'print': {'scalePercent': scale, 'fitToWidth': width, 'fitToHeight': height, 'repeatTitleRows': repeat}}}), 'xlsx')
    path = tmp_path / 'print.xlsx'
    build_workbook(output_path=path, title='打印', period='2026', sheets=({'name': '数据',
        'rows': [['项目', '数值'], ['原值', 1234.56], ['合计', {'formula': 'B2', 'value': 1234.56}]]},),
        preferences=prefs, generated_date='2026-11-12')
    book = load_workbook(path)
    sheet = book['数据']
    assert bool(sheet.sheet_properties.pageSetUpPr.fitToPage) == (scale is None)
    if scale is not None:
        assert sheet.page_setup.scale == scale
    else:
        # OOXML 未写出时默认1，原生引擎省略默认属性。
        assert (1 if sheet.page_setup.fitToWidth is None else sheet.page_setup.fitToWidth) == (width or 0)
        assert (1 if sheet.page_setup.fitToHeight is None else sheet.page_setup.fitToHeight) == (height or 0)
    assert sheet.print_title_rows == ('$1:$' + str(repeat) if repeat else None)
    assert sheet.print_area
    assert book['说明'].print_title_rows is None and book['说明'].print_area
    assert sheet['B2'].value == 1234.56 and sheet['B3'].value == '=B2'


def test_workbook_actual_pdf_pagination_and_repeated_title_follow_print_preferences(tmp_path):
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    pages = {}
    for mode, height in [('width', None), ('page', 1)]:
        prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'PrintSigner'},
            'xlsx': {'rowHeight': 24, 'print': {'fitToWidth': 1, 'fitToHeight': height,
                'repeatTitleRows': 1}}}), 'xlsx')
        path = tmp_path / (mode + '.xlsx')
        build_workbook(output_path=path, title='PrintTest', period='2026', sheets=({'name': 'Data',
            'rows': [['HEADER_SENTINEL', 'Value'], *[[f'Row{index:03}', index] for index in range(100)]]},),
            preferences=prefs, generated_date='2026-11-12')
        actual = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.xlsx', timeout=60)))
        pages[mode] = [page.extract_text() for page in actual.pages]
        assert 'Row099' in ''.join(pages[mode])
        assert 'PrintSigner' in pages[mode][-1]
    assert len(pages['width']) > len(pages['page'])
    assert len(pages['page']) == 2  # 业务表一页，独立说明落款一页。
    assert 'HEADER_SENTINEL' in pages['width'][1]


def test_slides_four_three_preferences_preserve_chart_proportions_and_original_bytes(tmp_path):
    from PIL import Image
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '报告编制人'}, 'pptx': {'aspectRatio': '4:3'}}), 'pptx')
    destination = tmp_path / 'chart-report.pptx'
    build_editable_pptx(output_path=destination, title='图表报告', period='2026年', theme='executive',
        slides=({'title': '本期情况', 'bullets': ['保持图像比例'], 'chartPath': str(chart)},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(destination)
    picture = next(shape for shape in deck.slides[1].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert picture.width / picture.height == pytest.approx(2, rel=1e-5)
    assert picture.image.blob == chart.read_bytes()
    assert picture.left + picture.width <= deck.slide_width
    assert picture.top + picture.height <= deck.slide_height


@pytest.mark.parametrize('key', ['generatedByLabel', 'watermarkText'])
def test_optional_document_labels_may_be_empty_without_losing_required_signature(key):
    from smart_reporting.reporting.delivery.report_runtime.markdown import _document_context
    from smart_reporting.reporting.delivery.report_runtime.validation import ReportFailure

    from .test_report_runtime import _docx_postprocess_context

    context = _docx_postprocess_context()
    context['sectionNumbers'] = ['1']
    context['sections'][0]['sectionNumber'] = '1'
    context['headingNumbers'] = [{'level': 2, 'number': '1', 'title': '经营概览',
        'sectionCode': 'overview', 'anchor': 'report-section-overview'}]
    context[key] = ''
    assert _document_context(context)[key] == ''
    context['organizationName'] = ''
    with pytest.raises(ReportFailure, match='文档展示契约无效'):
        _document_context(context)


@pytest.mark.parametrize('layout', ['image_left', 'image_right', 'text'])
@pytest.mark.parametrize('aspect_ratio', ['16:9', '4:3'])
def test_slides_actual_layout_preferences_place_chart_and_preserve_body(tmp_path, layout, aspect_ratio):
    from PIL import Image
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    chart = tmp_path / 'layout.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '布局编制人'},
        'pptx': {'layout': layout, 'aspectRatio': aspect_ratio}}), 'pptx')
    path = tmp_path / (layout + '.pptx')
    build_editable_pptx(output_path=path, title='布局报告', period='2026年', theme='executive',
        slides=({'title': '图文布局', 'bullets': ['正文段落甲', '正文段落乙'], 'chartPath': str(chart)},),
        preferences=prefs, generated_date='2026-11-12')
    slide = Presentation(path).slides[1]
    image = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    paragraphs = [shape for shape in slide.shapes if shape.has_text_frame and shape.text in {'正文段落甲', '正文段落乙'}]
    assert len(paragraphs) == 2
    assert image.width / image.height == pytest.approx(2, rel=1e-5)
    assert image.image.blob == chart.read_bytes()
    if layout == 'image_left':
        assert all(image.left + image.width <= shape.left for shape in paragraphs)
    elif layout == 'image_right':
        assert all(shape.left + shape.width <= image.left for shape in paragraphs)
    else:
        assert all(shape.top + shape.height <= image.top for shape in paragraphs)


def test_slide_density_changes_spacing_without_dropping_sixth_body_item(tmp_path):
    gaps = []
    for density in ('comfortable', 'compact'):
        prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '密度编制人'},
            'pptx': {'density': density}}), 'pptx')
        path = tmp_path / (density + '.pptx')
        bullets = [f'正文条目{i}' for i in range(6)]
        build_editable_pptx(output_path=path, title='密度报告', period='2026年', theme='executive',
            slides=({'title': '内容密度', 'bullets': bullets},), preferences=prefs, generated_date='2026-11-12')
        slide = Presentation(path).slides[1]
        texts = [shape for shape in slide.shapes if shape.has_text_frame and shape.text in bullets]
        assert [shape.text for shape in texts] == bullets
        assert max(shape.top + shape.height for shape in texts) < Presentation(path).slide_height
        gaps.append(texts[1].top - texts[0].top)
    assert gaps[1] < gaps[0]
