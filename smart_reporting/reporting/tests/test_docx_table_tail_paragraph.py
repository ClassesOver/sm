"""Original top-level table anchors may append plain body paragraphs without table rewrites."""
from datetime import datetime, timezone
from io import BytesIO
import re
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source(protected=False, with_body=True):
    doc = Document()
    if with_body:
        doc.add_paragraph('earlier body')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = 'table preserved'
    if protected:
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:enforcement'), '1')
        protection.set(qn('w:edit'), 'readOnly')
        doc.settings.element.append(protection)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def operation(data, text=''):
    table = next(b for b in inspect_docx(data)['blocks'] if b['type'] == 'table')
    return {'kind': 'insertParagraph', 'blockId': table['blockId'],
            'expectedObjectSha256': table['expectedObjectSha256'], 'position': 'after', 'text': text}


@pytest.mark.parametrize('with_body', [True, False])
def test_table_tail_empty_and_text_insert_preserves_original_table_and_all_other_parts(with_body):
    data = source(with_body=with_body)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    result = patch_docx(data, [operation(data), operation(data, 'first tail'), operation(data, 'second tail')])
    document = Document(BytesIO(result))
    assert [c.tag.rsplit('}', 1)[-1] for c in document.element.body] == (['p'] if with_body else []) + ['tbl', 'p', 'p', 'p', 'sectPr']
    assert [p.text for p in document.paragraphs] == (['earlier body'] if with_body else []) + ['', 'first tail', 'second tail']
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        parts = {item.filename for item in before.infolist() if not item.is_dir()}
        assert parts == {item.filename for item in after.infolist() if not item.is_dir()}
        for name in parts:
            if name == 'docProps/core.xml':
                # saveDocx increments revision and stamps modified time; every other byte is preserved.
                original, saved = before.read(name), after.read(name)
                revision = re.search(rb'<cp:revision>([0-9]+)</cp:revision>', original)
                next_revision = re.search(rb'<cp:revision>([0-9]+)</cp:revision>', saved)
                assert int(next_revision[1]) == int(revision[1]) + 1
                timestamp = rb'(<dcterms:modified[^>]*>)([^<]*)(</dcterms:modified>)'
                modified = re.search(timestamp, saved)[2]
                assert started <= datetime.fromisoformat(modified.decode().replace('Z', '+00:00')) <= datetime.now(timezone.utc)
                normalized = saved.replace(next_revision[0], revision[0])
                normalized = re.sub(timestamp, lambda m: re.search(timestamp, original)[0], normalized)
                assert normalized == original
            elif name != 'word/document.xml':
                assert before.read(name) == after.read(name), name
        table = re.search(rb'<w:tbl[\s>].*?</w:tbl>', before.read('word/document.xml'), re.S).group()
        assert table in after.read('word/document.xml')
    assert patch_docx(result, []) == result
    tail = inspect_docx(result)['blocks'][-1]
    changed = patch_docx(result, [{'kind': 'replaceParagraph', 'blockId': tail['blockId'],
                                'expectedObjectSha256': tail['expectedObjectSha256'], 'text': 'later typing'}])
    assert Document(BytesIO(changed)).paragraphs[-1].text == 'later typing'


@pytest.mark.parametrize('change', [{'position': 'before'}, {'expectedObjectSha256': '0' * 64}, {'pageBreakBefore': True}])
def test_table_tail_rejects_invalid_identity_or_nonplain_fields(change):
    data = source()
    with pytest.raises(ValueError):
        patch_docx(data, [{**operation(data), **change}])


def test_table_tail_rejects_protection():
    data = source(protected=True)
    with pytest.raises(ValueError):
        patch_docx(data, [operation(data, 'blocked')])
