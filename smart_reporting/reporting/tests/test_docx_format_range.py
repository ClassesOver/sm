"""formatRange: partial-paragraph character formatting through the native docx bridge."""
from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from docx.shared import Pt, RGBColor

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source() -> bytes:
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run('前半部分')
    styled = paragraph.add_run('后半部分')
    styled.italic = True
    styled.font.size = Pt(14)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def op(block, start, end, style):
    return {'kind': 'formatRange', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'from': start, 'to': end, 'style': style}


def runs(content):
    paragraph = Document(BytesIO(content)).paragraphs[0]
    return [(run.text, bool(run.bold), bool(run.italic), run.font.size.pt if run.font.size else None,
             str(run.font.color.rgb) if run.font.color and run.font.color.type else None) for run in paragraph.runs]


def test_ranges_split_runs_and_keep_formatting_outside_them():
    data = source()
    block = inspect_docx(data)['blocks'][0]
    patched = patch_docx(data, [op(block, 2, 6, {'bold': True}), op(block, 6, 8, {'color': 'c00000'})])
    assert runs(patched) == [
        ('前半', False, False, None, None),
        ('部分', True, False, None, None),
        ('后半', True, True, 14.0, None),
        ('部分', False, True, 14.0, 'C00000'),
    ]
    assert ''.join(run[0] for run in runs(patched)) == '前半部分后半部分'


@pytest.mark.parametrize('bad', [
    {'from': 3, 'to': 3}, {'from': 0, 'to': 99}, {'from': -1, 'to': 2},
    {'style': {}}, {'style': {'highlight': 'yellow'}}, {'style': {'bold': 'yes'}}, {'extra': 1},
])
def test_invalid_ranges_and_styles_are_rejected(bad):
    data = source()
    block = inspect_docx(data)['blocks'][0]
    with pytest.raises(ValueError):
        patch_docx(data, [{**op(block, 0, 2, {'bold': True}), **bad}])
