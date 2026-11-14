"""隔离样例预览复用正式生成器，不发布版本或改变任务默认。"""
from __future__ import annotations

import base64
import hashlib
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from ..preferences.document_adapter import document_design
from ..preferences.markdown_adapter import append_signature
from ..preferences.markdown_captions import image_caption_markdown
from ..preferences.models import FormatPreferences, resolve_format_preferences
from ..reporting.delivery.office_engine import libreoffice_to_pdf
from ..reporting.delivery.pptx import build_editable_pptx
from ..reporting.delivery.report_runtime.runtime import ReportRuntime
from ..reporting.delivery.xlsx import build_workbook

TITLE = '格式偏好预览'
PERIOD = '样例期间'
SAMPLE_CITATIONS = [{'citationId': 'preview-source', 'label': '固定排版样例，非业务数据', 'coverageItems': []}]
MARKDOWN = '# 格式偏好预览\n\n## 1. 样例概览\n\n[[section:overview]]\n以下仅为排版样例，不代表真实业务数据。\n\n| 指标 | 金额 |\n| --- | ---: |\n| 示例收入 | 1234.56 |\n| 示例支出 | -234.56 |\n'
MEDIA = {'md': 'text/markdown', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'pdf': 'application/pdf', 'word': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
MD_SAMPLE_PNG = ('iVBORw0KGgoAAAANSUhEUgAAAFAAAAAgCAIAAAAKUWg7AAAARklEQVR4nO3PAQ3AIADAMMAEnhCCfwl38Sd7q2Cb'
    '+9zxJ+vrgLcZrjNcZ7jOcJ3hOsN1husM1xmuM1xnuM5wneE6w3WG6x5MuAEHCFYHIQAAAABJRU5ErkJggg==')


def _artifact(content, filename, media_type):
    return {'filename': filename, 'mediaType': media_type, 'size': len(content),
        'sha256': hashlib.sha256(content).hexdigest(), 'base64': base64.b64encode(content).decode('ascii')}


def _sample_chart(root, color):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8, 4), layout='constrained')
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.bar(['A', 'B', 'C'], [120, 180, 150], color=color)
    axes.set_ylabel('Sample value')
    path = root / 'sample-chart.png'
    figure.savefig(path, dpi=150)
    return path


def render_preference_preview(document: dict, format: str, *, generated_date: str) -> dict:
    preferences = FormatPreferences.model_validate(document)
    resolved = resolve_format_preferences(preferences, format)
    suffix = '.docx' if format == 'word' else '.' + format
    issues = []
    pdf = None
    pages = []
    with tempfile.TemporaryDirectory(prefix='configuration-preview-') as directory:
        root = Path(directory)
        output = root / ('preview' + suffix)
        if format == 'md':
            sample = MARKDOWN + '\n- 列表样例：正文与业务原值保持不变。\n\n' + chr(96) * 3 + 'text\n固定代码样例\n' + chr(96) * 3 + '\n'
            sample += '\n' + image_caption_markdown(
                '![示例图片](data:image/png;base64,' + MD_SAMPLE_PNG + ' "示例图片说明")',
                '*图表：示例图片说明*', visible=resolved['imageCaptions']) + '\n'
            sample += '\n排版样例来源[[citation:preview-source]]\n'
            output.write_text(append_signature(sample, resolved, generated_date,
                heading_numbers=[{'level': 2, 'number': '1', 'title': '样例概览'}],
                citation_presentations=SAMPLE_CITATIONS), encoding='utf-8')
        elif format == 'xlsx':
            built = build_workbook(output_path=output, title=TITLE, period=PERIOD,
                sheets=({'name': '示例数据', 'rows': [['项目', '金额'], ['示例收入', 1234.56],
                    ['示例支出', -234.56], ['合计', {'formula': 'SUM(B2:B3)', 'value': 1000}],
                    ['示例百分数', {'value': 12.5, 'valueType': 'percentPoints'}],
                    ['示例日期', {'value': '2026-11-12', 'valueType': 'date'}]]},),
                preferences=resolved, generated_date=generated_date)
            issues.extend(built.issues)
        elif format == 'pptx':
            chart = _sample_chart(root, resolved['common']['accentColor'])
            built = build_editable_pptx(output_path=output, title=TITLE, period=PERIOD, theme=resolved['theme'],
                slides=({'title': '样例概览', 'bullets': ['仅供排版验证', '正文保留原生可编辑文字'], 'chartPath': str(chart)},),
                preferences=resolved, generated_date=generated_date)
            issues.extend(built.issues)
        else:
            chart = _sample_chart(root, resolved['common']['accentColor'])
            source = root / 'sample.md'
            source.write_text(MARKDOWN + '\n![固定排版示例](sample-chart.png)\n\n*图表：固定排版示例*\n\n'
                '排版样例来源[[citation:preview-source]]\n', encoding='utf-8')
            context = {'title': TITLE, 'periodLabel': PERIOD, 'organizationName': resolved['common']['signer'],
                'generatedByLabel': resolved['common']['generatedByLabel'], 'watermarkText': '',
                'generatedDate': generated_date, 'sectionNumbers': ['1'],
                'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '样例概览'}],
                'headingNumbers': [{'level': 2, 'number': '1', 'title': '样例概览',
                    'sectionCode': 'overview', 'anchor': 'report-section-overview'}]}
            formats = {key: resolve_format_preferences(preferences, key) for key in ('pdf', 'word')}
            state = {'jobId': 'configuration-preview', 'sources': [{'path': path.name, 'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in (source, chart)], '_documentContext': context,
                '_citationPresentations': SAMPLE_CITATIONS,
                '_formatPreferences': formats, '_formatDesigns': {key: document_design(value).compact() for key, value in formats.items()}}
            result = ReportRuntime(root).render_markdown(state, 'sample.md', 'revision/preview.pdf',
                '.reporting-tmp/workspace-report-preview-render/render.pdf')
            issues.extend(result.get('renderIssues', []))
            output = root / 'revision' / ('preview' + suffix)
        content = output.read_bytes()
        native = _artifact(content, 'preview' + suffix, MEDIA[format])
        if format != 'md':
            try:
                pdf_bytes = content if format == 'pdf' else libreoffice_to_pdf(content, suffix=suffix, timeout=60)
                pdf = _artifact(pdf_bytes, 'preview.pdf', 'application/pdf')
                preview_pdf = root / 'page-preview.pdf'
                preview_pdf.write_bytes(pdf_bytes)
                subprocess.run(['pdftoppm', '-scale-to', '1100', '-png', str(preview_pdf), str(root / 'page')],
                    capture_output=True, check=True, timeout=60)
                pages = [_artifact(page.read_bytes(), page.name, 'image/png') for page in
                    sorted(root.glob('page-*.png'), key=lambda path: int(path.stem.split('-')[-1]))]
            except Exception:
                logger.opt(exception=True).warning('configuration_preference_preview_conversion_failed format={}', format)
                issues.append({'code': 'management_preference_preview_conversion_failed',
                    'message': '原生文件已生成，但 PDF 预览转换失败；可读取原生样例后重试。'})
    return {'format': format, 'generatedDate': generated_date, 'artifact': native, 'pdf': pdf, 'pages': pages, 'issues': issues,
        'scope': '固定排版样例，不代表业务报告验收；未实现的偏好仍待执行适配。'}
