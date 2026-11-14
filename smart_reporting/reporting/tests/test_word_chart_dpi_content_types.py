"""图片派生必须维持DOCX包的媒体类型登记，允许独立Office读取。"""

from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.shared import Inches
from lxml import etree
from PIL import Image

from smart_reporting.reporting.delivery.report_runtime.word_image_dpi import (
    apply_word_chart_image_dpi,
)


@pytest.mark.parametrize('image_format,extension', [('PNG', 'png'), ('JPEG', 'jpg')])
def test_derived_chart_keeps_explicit_media_content_type_and_reopens(tmp_path, image_format, extension):
    chart = tmp_path / ('chart.' + extension)
    Image.new('RGB', (1200, 600), '#345678').save(chart, format=image_format)
    doc = Document()
    doc.add_picture(str(chart), width=Inches(2))
    stream = BytesIO()
    doc.save(stream)
    with ZipFile(BytesIO(stream.getvalue())) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    # Pandoc等转换器允许仅对每个原图片登记Override，无扩展名Default。
    content_types = etree.fromstring(entries['[Content_Types].xml'])
    namespace = '{http://schemas.openxmlformats.org/package/2006/content-types}'
    media_extensions = {name.rsplit('.', 1)[-1] for name in entries if name.startswith('word/media/')}
    for node in list(content_types):
        if node.tag == namespace + 'Default' and node.get('Extension') in media_extensions:
            content_types.remove(node)
    for name in entries:
        if name.startswith('word/media/'):
            etree.SubElement(content_types, namespace + 'Override', PartName='/' + name,
                ContentType='image/png' if image_format == 'PNG' else 'image/jpeg')
    entries['[Content_Types].xml'] = etree.tostring(content_types)
    path = tmp_path / 'chart.docx'
    with ZipFile(path, 'w') as package:
        for name, content in entries.items():
            package.writestr(name, content)
    assert len(Document(path).inline_shapes) == 1
    receipt = apply_word_chart_image_dpi(path, target_dpi=96,
        chart_source_sha256s={sha256(chart.read_bytes()).hexdigest()})
    assert receipt['status'] == 'applied'
    assert len(Document(path).inline_shapes) == 1
    with ZipFile(path) as package:
        after = {name: package.read(name) for name in package.namelist()}
    assert all(after[name] == content for name, content in entries.items()
        if name not in {'word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'})
    added = set(after) - set(entries)
    assert len(added) == 1
    types = etree.fromstring(after['[Content_Types].xml'])
    assert types.xpath('count(ct:Override[@PartName=$part and @ContentType=$type])',
        namespaces={'ct': namespace[1:-1]}, part='/' + added.pop(),
        type='image/png' if image_format == 'PNG' else 'image/jpeg') == 1
