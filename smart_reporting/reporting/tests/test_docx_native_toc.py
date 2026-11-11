"""Exercise native TOC insert/update via the production DOCX bridge."""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def test_insert_and_refresh_native_toc_preserve_other_package_parts(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = Document()
    source.add_paragraph('目录前言')
    source.add_heading('业务概览 & 总览', level=1)
    source.add_paragraph('正文不要被改写')
    source.add_heading('区域说明', level=2)
    stream = BytesIO()
    source.save(stream)
    data = stream.getvalue()
    model = docx_native.inspect_docx(data)
    identity = ('blockId', 'expectedObjectSha256')
    insert = {**{key: model['blocks'][0][key] for key in identity}, 'kind': 'insertToc', 'position': 'after'}
    inserted = docx_native.patch_docx(data, [insert])
    assert inserted != data
    toc_block = next(block for block in docx_native.inspect_docx(inserted)['blocks'] if block['blockId'] != model['blocks'][0]['blockId'] and block['expectedObjectSha256'] not in {old['expectedObjectSha256'] for old in model['blocks']})
    update = {**{key: toc_block[key] for key in identity}, 'kind': 'updateToc'}
    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(data, [update])
    refreshed = docx_native.patch_docx(inserted, [update])
    for output in (inserted, refreshed):
        with ZipFile(BytesIO(data)) as original, ZipFile(BytesIO(output)) as edited:
            assert set(edited.namelist()) == set(original.namelist())
            assert [name for name in original.namelist() if original.read(name) != edited.read(name)] == ['word/document.xml']
            document = etree.fromstring(edited.read('word/document.xml'))
            assert sum('TOC' in instruction for instruction in document.xpath('.//w:instrText/text()', namespaces=NS)) == 1
            assert document.xpath('.//w:fldChar[@w:fldCharType="begin"]', namespaces=NS)[0].get(f'{{{W}}}dirty') in ('1', 'true')
            assert '业务概览 & 总览' in document.xpath('.//w:t/text()', namespaces=NS)
            assert '区域说明' in document.xpath('.//w:t/text()', namespaces=NS)
            assert document.xpath('.//w:t[text()="正文不要被改写"]', namespaces=NS)
