"""数据点配色界面使用真实 PPTX 引擎；授权与附件 PDF 由 smoke 显式模拟。"""
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from smart_reporting.report_editor.native_office import inspect_office, patch_office

payload = json.load(sys.stdin)
if payload['mode'] != 'create':
    # 复用已有 inspect/render/patch 及独立 python-pptx/ZIP 读取器。
    from runpy import run_path
    sys.stdin = __import__('io').StringIO(json.dumps(payload))
    run_path(str(Path(__file__).with_name('pptx-parallel-fixture.py')), run_name='__main__')
else:
    presentation = Presentation()
    for label in ['Bar source', 'Pie source', 'Scatter source', 'Untouched slide']:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(.4), Inches(.2), Inches(8), Inches(.5)).text = label
    stream = BytesIO()
    presentation.save(stream)
    categories = ['第一季度 / '+ '长类别名称' * 8, 'Second category', '第三季度', 'Fourth category']
    charts = [{'slideIndex': 0, 'kind': 'bar', 'categories': categories, 'series': [
        {'name': '收入系列 / '+ '长系列名称' * 7, 'values': [10, 20, 30, 40]},
        {'name': '成本系列', 'values': [5, 9, 12, 15]}]},
        {'slideIndex': 1, 'kind': 'pie', 'categories': categories, 'series': [{'name': '构成系列', 'values': [10, 20, 30, 40]}]},
        {'slideIndex': 2, 'kind': 'scatter', 'categories': ['1', '2', '3', '4'], 'series': [{'name': '散点来源', 'values': [10, 20, 30, 40]}]}]
    content = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': charts}])
    model = inspect_office('pptx', content)
    edits = [{'slideIndex': index, 'elementId': next(item['id'] for item in model['slides'][index]['elements'] if item.get('type') == 'chart'), 'pointColors': {'0': {'0': '#123ABC'}}} for index in [0, 1]]
    content = patch_office('pptx', content, [{'kind': 'editSlides', 'chartEdits': edits}])
    preview = BytesIO()
    Image.new('RGB', (48, 32), 'white').save(preview, 'PDF')
    print(json.dumps({'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content), 'previewPdf': base64.b64encode(preview.getvalue()).decode()}))
