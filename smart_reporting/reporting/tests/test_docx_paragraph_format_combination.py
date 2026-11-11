from io import BytesIO
from hashlib import sha256
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.delivery.office_engine import last_json_line, run_bridge
from smart_reporting.reporting.tests.test_docx_paragraph_borders import W, make_doc, op as border_op, pbdr_of, single
from smart_reporting.reporting.tests.test_docx_paragraph_shading import op as shade_op, shd_of


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("fill,clear", [("edf5fc", False), (None, True), (None, False)])
def test_paragraph_border_and_shading_compose_without_losing_source(reverse, fill, clear):
    data = make_doc(f'<w:shd xmlns:w="{W}" w:val="clear" w:color="auto" w:fill="FFF2CC"/>')
    ops = [shade_op(data, fill, clear), border_op(data, [single("bottom", "FF0000", 1)])]
    result = patch_docx(data, ops[::-1] if reverse else ops)
    assert pbdr_of(result) == {"bottom": {"val": "single", "sz": "8", "space": "0", "color": "FF0000"}}
    assert shd_of(result) == (("clear", "auto", fill or "auto") if fill or clear else None)
    before_doc, after_doc = Document(BytesIO(data)), Document(BytesIO(result))
    assert etree.tostring(before_doc.paragraphs[1]._p) == etree.tostring(after_doc.paragraphs[1]._p)
    assert [etree.tostring(run._r) for run in before_doc.paragraphs[0].runs] == [etree.tostring(run._r) for run in after_doc.paragraphs[0].runs]
    assert after_doc.paragraphs[0].paragraph_format.keep_with_next is True
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        assert {name for name in before.namelist() if not name.endswith('/')} == {name for name in after.namelist() if not name.endswith('/')}
        assert {name for name in before.namelist() if before.read(name) != after.read(name)} == {"word/document.xml"}
    removed = patch_docx(result, [border_op(result, None), shade_op(result)])
    assert pbdr_of(removed) is None and shd_of(removed) is None


def test_pair_keeps_duplicates_other_edits_forged_identity_and_fields_rejected():
    data = make_doc()
    ops = [shade_op(data, "edf5fc"), border_op(data, [single("bottom")])]
    for bad in [
        ops + [dict(ops[0])], ops + [dict(ops[1])],
        [{**ops[0], "expectedObjectSha256": "foreign"}, ops[1]],
        [ops[0], {**ops[1], "expectedObjectSha256": "foreign"}],
        [{**ops[0], "extra": 1}, ops[1]], [ops[0], {**ops[1], "extra": 1}],
        ops + [{**{key: value for key, value in ops[0].items() if key in ("blockId", "expectedObjectSha256")}, "kind": "setParagraphAlignment", "alignment": "center"}],
        ops + [{**{key: value for key, value in ops[0].items() if key in ("blockId", "expectedObjectSha256")}, "kind": "insertNote", "noteKind": "footnote", "offset": 1, "text": "note"}],
    ]:
        with pytest.raises(ValueError):
            patch_docx(data, bad)


def test_pair_cannot_write_a_protected_document():
    doc = Document(BytesIO(make_doc()))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings.element.append(protection)
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    block = inspect_docx(data)['blocks'][0]
    assert block['paragraphShadingEditable'] is False
    assert block['paragraphBordersEditable'] is False
    ops = [shade_op(data, "edf5fc"), border_op(data, [single("bottom")])]
    for batch in [ops, [ops[0]], [ops[1]]]:
        with pytest.raises(ValueError, match='paragraph_unsupported'):
            patch_docx(data, batch)


@pytest.mark.parametrize("source,capability", [
    (f'<w:shd xmlns:w="{W}" w:val="pct10" w:fill="FFF2CC"/>', 'paragraphShadingEditable'),
    (f'<w:pBdr xmlns:w="{W}"><w:top w:val="double"/></w:pBdr>', 'paragraphBordersEditable'),
])
def test_pair_does_not_relax_unsupported_source_properties(source, capability):
    data = make_doc(source)
    source_hash = sha256(data).hexdigest()
    model = inspect_docx(data)
    assert model['sourceSha256'] == source_hash
    block = model['blocks'][0]
    assert block[capability] is False
    other = 'paragraphBordersEditable' if capability == 'paragraphShadingEditable' else 'paragraphShadingEditable'
    assert block[other] is True
    assert block['editable'] is True
    assert sha256(data).hexdigest() == source_hash
    with pytest.raises(ValueError):
        patch_docx(data, [shade_op(data, "edf5fc"), border_op(data, [single("bottom")])])


def test_inspect_decoration_probes_leave_actual_source_and_output_path_untouched(tmp_path):
    import json

    source = tmp_path / 'source.docx'
    output = tmp_path / 'not-created.docx'
    request = tmp_path / 'inspect.json'
    data = make_doc()
    source.write_bytes(data)
    original = source.stat()
    request.write_text(json.dumps({'kind': 'inspect', 'input': str(source), 'output': str(output)}))
    result = run_bridge('doc', 'edit-docx', request)
    assert result.returncode == 0, result.stderr
    model = last_json_line(result.stdout)
    assert model['sourceSha256'] == sha256(data).hexdigest()
    assert model['blocks'][0]['paragraphShadingEditable'] is True
    assert model['blocks'][0]['paragraphBordersEditable'] is True
    assert source.read_bytes() == data
    assert source.stat().st_mtime_ns == original.st_mtime_ns
    assert source.stat().st_ino == original.st_ino
    assert not output.exists()
