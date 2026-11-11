from io import BytesIO
from pathlib import Path
import subprocess

import pytest
from docx import Document
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery import docx_native


@pytest.fixture(autouse=True)
def _source_bridge(monkeypatch):
    # 直接执行本轮 TypeScript，root 统一构建前不读取旧 dist。
    root = Path(__file__).resolve().parents[1] / 'doc_engine'
    def run(_engine, script, request_path, **_kwargs):
        return subprocess.run([str(root / 'node_modules/.bin/tsx'),
                               str(root / 'bridge' / f'{script}.ts'), str(request_path)],
                              cwd=root, capture_output=True, text=True, timeout=120)
    monkeypatch.setattr(docx_native, 'run_bridge', run)


def _source():
    doc = Document()
    run = doc.add_paragraph().add_run('中文ABC')
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for key, value in {'ascii': 'Calibri', 'hAnsi': 'Calibri', 'eastAsia': '宋体', 'cs': 'Arial'}.items():
        fonts.set(qn(f'w:{key}'), value)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize('kind', ['formatParagraph', 'formatRange'])
@pytest.mark.parametrize('font', ['微软雅黑', 'Noto Sans CJK SC', 'LXGW WenKai', 'Ma Shan Zheng', 'ZCOOL XiaoWei', 'Times New Roman', None])
def test_source_docx_font_pick_preserves_other_script_slot(kind, font):
    source = _source()
    block = docx_native.inspect_docx(source)['blocks'][0]
    operation = {'kind': kind, 'blockId': block['blockId'],
                 'expectedObjectSha256': block['expectedObjectSha256'], 'style': {'fontFamily': font}}
    if kind == 'formatRange':
        operation.update({'from': 0, 'to': 5})
    changed = docx_native.patch_docx(source, [operation])
    run = Document(BytesIO(changed)).paragraphs[0].runs[0]
    assert run.text == '中文ABC'
    fonts = run._element.rPr.rFonts if run._element.rPr is not None else None
    if font is None:
        assert fonts is None
    else:
        east_asian = font != 'Times New Roman'
        assert fonts.get(qn('w:eastAsia')) == (font if east_asian else '宋体')
        assert fonts.get(qn('w:ascii')) == ('Calibri' if east_asian else font)
        assert fonts.get(qn('w:hAnsi')) == ('Calibri' if east_asian else font)
        assert fonts.get(qn('w:cs')) == 'Arial'
