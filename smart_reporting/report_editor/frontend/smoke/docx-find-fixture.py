"""查找替换 UI 的真实 DOCX 夹具；授权和修订登记由浏览器路由明确模拟。"""
import base64
import hashlib
import json
import sys
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    document = Document()
    document.add_heading('查找示例 cat', 1)
    paragraph = document.add_paragraph()
    paragraph.add_run('cat').bold = True
    paragraph.add_run(' cat')
    for index in range(8):
        document.add_paragraph(f'正文{index+1:02} cat ' + '用于检查较长匹配结果的换行与完整阅读。' * 4)
    table = document.add_table(rows=2, cols=1)
    table.cell(0, 0).text = 'cat 表格第一行'
    table.cell(1, 0).text = 'cat 表格第二行'
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
else:
    content = base64.b64decode(payload['bytes'])
    if payload.get('operations'):
        content = patch_docx(content, payload['operations'])
document = Document(BytesIO(content))
def paragraph_info(paragraph):
    return {'text': paragraph.text, 'style': paragraph.style.style_id,
            'runs': [{'text': run.text, 'bold': run.bold, 'italic': run.italic, 'underline': run.underline} for run in paragraph.runs]}
with ZipFile(BytesIO(content)) as archive:
    parts = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if not archive.getinfo(name).is_dir()}
print(json.dumps({'bytes': base64.b64encode(content).decode(), 'sha256': hashlib.sha256(content).hexdigest(),
                  'model': inspect_docx(content), 'independent': {'paragraphs': [paragraph_info(p) for p in document.paragraphs],
                  'tables': [[[paragraph_info(p) for p in cell.paragraphs] for row in table.rows for cell in row.cells] for table in document.tables], 'parts': parts}}, ensure_ascii=False))
