"""六类首行缩进逐段进入原生演示文稿，分页与冻结字面值不丢失。"""

from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.delivery.templates import libreoffice_to_pdf
from smart_reporting.reporting.tests.test_pptx_native_tables import table_input


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
@pytest.mark.parametrize('indent', [0, 48])
def test_all_native_roles_keep_frozen_first_line_indent_across_continuations(tmp_path, aspect, indent):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    description = '\n'.join(f'DESC{i:02} 完整说明 ' + '长文本保留' * 4 for i in range(14))
    title = 'CAPTION 原始图注 ' * 38
    body = [f'BODY{i:02} ' + '正文持续完整 1234.5600 ' * 25 for i in range(5)]
    table = table_input(30)
    table['headers'] = ['期间首行\n期间次行', '收入金额']
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'SIGNER 冻结编制', 'dateFormat': 'iso'}, 'pptx': {
            'aspectRatio': aspect, 'footer': {'left': 'FOOTER 长页脚 ' * 4, 'right': 'PAGE {slide}/{slides}'},
            'footerStyle': {'indent': indent},
            'signature': {'indent': indent, 'size': 24, 'description': description},
            'typography': {role: {'indent': indent} for role in ('body', 'h1', 'table', 'caption')},
        }}), 'pptx')
    frozen = deepcopy(preferences)
    path = tmp_path / 'all-roles.pptx'
    result = build_editable_pptx(output_path=path, title='TITLE 冻结报告', period='PERIOD 2026', theme='executive',
        slides=({'title': 'BODY TITLE 正文标题', 'bullets': body},
            {'title': title, 'bullets': [], 'chartPath': str(chart), 'tables': [table]}),
        preferences=preferences, generated_date='2026-11-13')
    deck = Presentation(path)
    counts = {role: 0 for role in ('body', 'h1', 'table', 'caption', 'signature', 'footerStyle')}
    signatures, captions, body_fragments, rows = [], [], [], []
    for slide in deck.slides:
        for shape in slide.shapes:
            if shape.has_table:
                counts['table'] += 1
                for row in shape.table.rows:
                    for cell in row.cells:
                        for paragraph in cell.text_frame.paragraphs:
                            assert int(paragraph._p.get_or_add_pPr().get('indent', 0)) == indent * 12700
                rows.extend([[cell.text for cell in row.cells] for row in list(shape.table.rows)[1:]])
                continue
            if not shape.has_text_frame or not shape.text:
                continue
            value = shape.text
            if value.startswith(('FOOTER', 'PAGE ')):
                role = 'footerStyle'
            elif value.startswith(('SIGNER', '2026-11-13', 'DESC')):
                role = 'signature'
                signatures.append(value)
            elif value.startswith('图 1 ') and shape.top > 150 * 9525:
                role = 'caption'
                captions.append(value.removeprefix('图 1 '))
            elif shape.top == 76 * 9525 or value == 'TITLE 冻结报告':
                role = 'h1'
            else:
                role = 'body'
                if value.startswith('BODY') or '正文持续完整' in value:
                    body_fragments.append(value)
            counts[role] += 1
            for paragraph in shape.text_frame.paragraphs:
                assert int(paragraph._p.get_or_add_pPr().get('indent', 0)) == indent * 12700, (role, value)
    assert all(counts.values()), counts
    assert counts['signature'] > 10 and counts['table'] > 1 and counts['caption'] > 1
    assert ''.join(captions) == title
    assert ''.join(body_fragments) == ''.join(body)
    assert rows == table['rows']
    for line in description.splitlines():
        assert line in ''.join(signatures)
    assert preferences == frozen
    assert result.size == path.stat().st_size and result.sha256


def test_distinct_role_indents_keep_native_frame_and_pdf_continuation_origin(tmp_path):
    import pymupdf

    charts = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(charts)
    table = table_input(2)
    body = 'FIRSTLINE ' + 'continuous body words ' * 12
    roles = {'h1': 7, 'body': 19, 'table': 29, 'caption': 37}
    outputs = []
    for enabled in (False, True):
        preferences = resolve_format_preferences(FormatPreferences.model_validate({
            'common': {'signer': 'SIGNER native', 'dateFormat': 'iso'}, 'pptx': {
                'footer': {'left': 'FOOTER native'}, 'footerStyle': {'indent': 43 if enabled else 0},
                'signature': {'indent': 48 if enabled else 0, 'align': 'left', 'description': 'DESC native'},
                'typography': {role: {'indent': value if enabled else 0} for role, value in roles.items()},
            }}), 'pptx')
        path = tmp_path / f'distinct-{enabled}.pptx'
        build_editable_pptx(output_path=path, title='TITLE native', period='PERIOD native', theme='executive',
            slides=({'title': 'CONTENT native', 'bullets': [body]},
                {'title': 'CAPTION native', 'bullets': [], 'chartPath': str(charts), 'tables': [table]}),
            preferences=preferences, generated_date='2026-11-13')
        pdf = libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)
        path.with_suffix('.pdf').write_bytes(pdf)
        assert len(PdfReader(BytesIO(pdf)).pages) == len(Presentation(path).slides)
        outputs.append((Presentation(path), pymupdf.open(stream=pdf, filetype='pdf')))
    zero, changed = outputs
    for expected, text in [(7, 'TITLE native'), (19, body), (37, '图 1 CAPTION native'),
            (48, 'SIGNER native\n2026-11-13'), (43, 'FOOTER native')]:
        before = next(shape for slide in zero[0].slides for shape in slide.shapes
            if shape.has_text_frame and shape.text == text)
        after = next(shape for slide in changed[0].slides for shape in slide.shapes
            if shape.has_text_frame and shape.text == text)
        assert (before.left, before.width) == (after.left, after.width)
        assert int(after.text_frame.paragraphs[0]._p.get_or_add_pPr().get('indent')) == expected * 12700
    for slide in changed[0].slides:
        for shape in slide.shapes:
            if shape.has_table:
                assert all(int(p._p.get_or_add_pPr().get('indent')) == 29 * 12700
                    for row in shape.table.rows for cell in row.cells for p in cell.text_frame.paragraphs)
    def body_lines(pdf):
        lines = [line for block in pdf[1].get_text('dict')['blocks'] if 'lines' in block for line in block['lines']]
        return [line for line in lines if any('FIRSTLINE' in span['text'] or 'continuous body' in span['text']
            for span in line['spans'])]
    first, indented = body_lines(zero[1]), body_lines(changed[1])
    assert len(first) > 1 and len(indented) > 1
    assert indented[0]['bbox'][0] - first[0]['bbox'][0] == pytest.approx(19, abs=.1)
    assert indented[1]['bbox'][0] == pytest.approx(first[1]['bbox'][0], abs=.1)


def test_table_hard_paragraphs_use_first_line_indent_in_height_measurement(tmp_path):
    import json
    import subprocess
    from pathlib import Path

    table = table_input(2)
    table['headers'] = ['A', 'B', 'C', 'D', 'E', 'F']
    table['rows'] = [['A\nWWWWWWWW' for _ in range(6)] for _ in range(2)]
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'TableSigner'}, 'pptx': {
        'aspectRatio': '4:3',
        'typography': {'table': {'indent': 48, 'size': 18, 'lineHeight': 1.3}}}}), 'pptx')
    path = tmp_path / 'hard-paragraphs.pptx'
    build_editable_pptx(output_path=path, title='Table paragraphs', period='2026', theme='executive',
        slides=({'title': 'Table paragraphs', 'bullets': [], 'tables': [table]},),
        preferences=prefs, generated_date='2026-11-13')
    # 直接复用引擎回读成品和原有layoutText；不另造文字测量器。
    script = """
import {readFile} from 'node:fs/promises';
import {openPptx} from '@genoffice/pptx-engine';
import {layoutText,HeuristicMetrics} from '@genoffice/pptx-render';
const opened=await openPptx(await readFile(process.argv[1]));
const result=[];
for(const slide of opened.deck.slides) for(const element of slide.elements) {
 if(element.type!=='table') continue;
 for(let r=1;r<element.rows.length;r++) for(let c=0;c<element.rows[r].length;c++) {
  const cell=element.rows[r][c];
  const measured=layoutText({body:{...cell.text,insets:{l:0,t:0,r:0,b:0}},
   boxWidthPx:element.colWidths[c]/9525-20,boxHeightPx:720,
   metrics:new HeuristicMetrics(),vp:{widthPx:1280,heightPx:720,scale:1}});
  result.push({actual:element.rowHeights[r]/9525,
   required:Math.ceil(Math.max(measured.contentHeight,measured.inkBottom??0))+16});
 }
}
console.log(JSON.stringify(result));
"""
    engine = Path(__file__).resolve().parents[1] / 'slides_engine'
    result = subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', script, str(path)],
        cwd=engine, capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)
    assert values and all(item['actual'] >= item['required'] - .01 for item in values), values
