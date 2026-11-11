from io import BytesIO

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document(); style = doc.styles.add_style('RibbonCustom', WD_STYLE_TYPE.PARAGRAPH); style.base_style = doc.styles['Normal']
    p = doc.add_paragraph(); p.paragraph_format.keep_with_next = True
    a = p.add_run('ABC'); a.bold = True; a.font.size = Pt(20)
    rpr = a._r.get_or_add_rPr(); rpr.append(OxmlElement('w:noProof'))
    fonts = OxmlElement('w:rFonts')
    for key, value in [('ascii', 'Arial'), ('hAnsi', 'Arial'), ('eastAsia', 'SimSun'), ('cs', 'CS Keep'), ('cstheme', 'minorBidi'), ('eastAsiaTheme', 'minorEastAsia')]: fonts.set(qn('w:' + key), value)
    rpr.insert(0, fonts)
    b = p.add_run('D'); b.italic = True
    doc.add_paragraph('untouched'); out = BytesIO(); doc.save(out); return out.getvalue()


def operation(data, **fields):
    block = inspect_docx(data)['blocks'][0]
    return {'kind': 'setParagraphStyle', **{key: block[key] for key in ('blockId', 'expectedObjectSha256')}, 'styleId': 'RibbonCustom', **fields}


def test_ribbon_style_sheds_majority_preserving_minor_emphasis_and_opaque_source():
    data = source(); output = patch_docx(data, [operation(data, ribbon=True)])
    p = Document(BytesIO(output)).paragraphs[0]
    assert p.text == 'ABCD' and p.style.style_id == 'RibbonCustom'
    assert not p.runs[0].bold and p.runs[0].font.size is None
    assert p.runs[1].italic
    assert p.runs[0]._r.rPr.find(qn('w:noProof')) is not None
    fonts = p.runs[0]._r.rPr.find(qn('w:rFonts'))
    assert fonts.get(qn('w:cs')) == 'CS Keep'
    assert fonts.get(qn('w:cstheme')) == 'minorBidi'
    assert fonts.get(qn('w:eastAsia')) == 'SimSun'
    assert fonts.get(qn('w:eastAsiaTheme')) == 'minorEastAsia'
    assert fonts.get(qn('w:ascii')) is None and fonts.get(qn('w:hAnsi')) is None
    assert p.paragraph_format.keep_with_next


@pytest.mark.parametrize('flag', [False, None, 'true', 1])
def test_ribbon_style_rejects_non_true_flag(flag):
    data = source()
    with pytest.raises(ValueError): patch_docx(data, [operation(data, ribbon=flag)])


@pytest.mark.parametrize('count', [1, 2, 3])
def test_ribbon_style_strict_majority_and_legacy_style_only(count):
    doc = Document(); doc.styles.add_style('RibbonCustom', WD_STYLE_TYPE.PARAGRAPH)
    p = doc.add_paragraph(); p.add_run('A' * count).bold = True; p.add_run('B' * (4 - count))
    out = BytesIO(); doc.save(out); data = out.getvalue()
    legacy = Document(BytesIO(patch_docx(data, [operation(data)]))).paragraphs[0]
    assert legacy.runs[0].bold
    changed = patch_docx(data, [operation(data, ribbon=True)])
    assert bool(Document(BytesIO(changed)).paragraphs[0].runs[0].bold) == (count <= 2)
    # 已经应用相同styleId再应用依然是有效Ribbon操作，来源身份绑定新修订。
    again = patch_docx(changed, [operation(changed, ribbon=True)])
    assert Document(BytesIO(again)).paragraphs[0].text == 'A' * count + 'B' * (4 - count)


@pytest.mark.parametrize('fault', ['hash', 'style', 'body', 'format', 'layout', 'notes', 'duplicate', 'protection'])
def test_ribbon_style_keeps_source_catalog_and_same_paragraph_guards(fault):
    data = source(); op = operation(data, ribbon=True); operations = [op]
    if fault == 'hash': op['expectedObjectSha256'] = 'foreign'
    elif fault == 'style': op['styleId'] = 'foreign'
    elif fault == 'body': operations.append({**{key: op[key] for key in ('blockId', 'expectedObjectSha256')}, 'kind': 'patchParagraphRuns', 'runs': [{'text': 'forged', 'inheritFrom': 0}]})
    elif fault == 'format': operations.append({**{key: op[key] for key in ('blockId', 'expectedObjectSha256')}, 'kind': 'formatParagraph', 'style': {'bold': True}})
    elif fault == 'layout': operations.append({**{key: op[key] for key in ('blockId', 'expectedObjectSha256')}, 'kind': 'setParagraphAlignment', 'alignment': 'center'})
    elif fault == 'duplicate': operations.append(operation(data))
    elif fault == 'notes': operations.append({**{key: op[key] for key in ('blockId', 'expectedObjectSha256')}, 'kind': 'insertNote', 'offset': 4, 'noteKind': 'footnote', 'text': 'note'})
    else:
        doc = Document(BytesIO(data)); protection = OxmlElement('w:documentProtection'); protection.set(qn('w:enforcement'), '1'); doc.settings.element.append(protection)
        out = BytesIO(); doc.save(out); data = out.getvalue()
    with pytest.raises(ValueError): patch_docx(data, operations)


def test_ribbon_style_preserves_ppr_run_defaults_and_all_other_parts():
    from zipfile import ZipFile
    from lxml import etree
    data = source(); doc = Document(BytesIO(data)); ppr = doc.paragraphs[0]._p.get_or_add_pPr()
    defaults = OxmlElement('w:rPr'); defaults.append(OxmlElement('w:b')); ppr.append(defaults)
    out = BytesIO(); doc.save(out); data = out.getvalue()
    output = patch_docx(data, [operation(data, ribbon=True)])
    saved = Document(BytesIO(output)); assert saved.paragraphs[0]._p.pPr.find(qn('w:rPr')).find(qn('w:b')) is not None
    before, after = Document(BytesIO(data)).paragraphs[0]._p.pPr, saved.paragraphs[0]._p.pPr
    after.remove(after.find(qn('w:pStyle')))
    assert etree.tostring(before) == etree.tostring(after)
    with ZipFile(BytesIO(data)) as original, ZipFile(BytesIO(output)) as changed:
        assert {name for name in original.namelist() if not name.endswith('/')} == {name for name in changed.namelist() if not name.endswith('/')}
        assert all(original.read(name) == changed.read(name) for name in original.namelist() if name != 'word/document.xml')


@pytest.mark.parametrize('key', ['color', 'underline', 'strike', 'italic'])
def test_ribbon_style_clears_each_majority_property_without_touching_opaque(key):
    doc = Document(); doc.styles.add_style('RibbonCustom', WD_STYLE_TYPE.PARAGRAPH); p = doc.add_paragraph()
    a = p.add_run('ABC'); b = p.add_run('D')
    if key == 'color':
        from docx.shared import RGBColor
        a.font.color.rgb = RGBColor(0x12, 0x34, 0x56)
    else: setattr(a, key, True)
    a._r.get_or_add_rPr().append(OxmlElement('w:noProof')); out = BytesIO(); doc.save(out); data = out.getvalue()
    output = patch_docx(data, [operation(data, ribbon=True)]); saved = Document(BytesIO(output)).paragraphs[0]
    assert saved.runs[0]._r.rPr.find(qn('w:' + {'color': 'color', 'underline': 'u', 'strike': 'strike', 'italic': 'i'}[key])) is None
    assert saved.runs[0]._r.rPr.find(qn('w:noProof')) is not None and saved.text == 'ABCD'


def test_ribbon_style_keeps_explicit_off_runs_outside_the_shed_mark():
    doc = Document(); doc.styles.add_style('RibbonCustom', WD_STYLE_TYPE.PARAGRAPH); p = doc.add_paragraph()
    p.add_run('ABC').bold = True; p.add_run('D').bold = False
    out = BytesIO(); doc.save(out); data = out.getvalue()
    saved = Document(BytesIO(patch_docx(data, [operation(data, ribbon=True)]))).paragraphs[0]
    assert saved.runs[0].bold is None
    assert saved.runs[1].bold is False
