"""独立读取下载的 PDF，核对链接目标/区域及非目标内容；不调用写入桥。"""
import hashlib
import json
import sys
from pathlib import Path

import pymupdf
from pypdf import PdfReader


def canonical(value):
    if hasattr(value, 'get_object') and value.get_object() is not value:
        return canonical(value.get_object())
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items() if k not in ['/P', '/Parent']}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return str(value)


def verify(directory: Path, content: bytes | None = None):
    source_bytes = (directory / 'source.pdf').read_bytes()
    output_bytes = (directory / 'downloaded.pdf').read_bytes() if content is None else content
    saved = json.loads((directory / 'save.json').read_text())
    request, result = saved['request'], saved['result']
    # 故障注入校验语义，正常对照还须匹配已签发文件身份。
    if content is None:
        assert hashlib.sha256(output_bytes).hexdigest() == result['artifacts']['pdf']['sha256']
        assert len(output_bytes) == result['artifacts']['pdf']['size']
    assert hashlib.sha256(source_bytes).hexdigest() == request['expectedSha256']
    operations = request['operations']
    assert len(operations) == 3
    assert [op['shape'] for op in operations] == ['link'] * 3
    assert [op.get('url') for op in operations[:2]] == [
        'https://www.example.com/report?year=2026&kind=office',
        'mailto:review@example.com?subject=Report',
    ]
    assert operations[2]['destPage'] == 3
    source = pymupdf.open(stream=source_bytes, filetype='pdf')
    output = pymupdf.open(stream=output_bytes, filetype='pdf')
    before = PdfReader(directory / 'source.pdf')
    from io import BytesIO
    after = PdfReader(BytesIO(output_bytes), strict=True)
    assert len(source) == len(output) == len(after.pages) == 3
    assert source.metadata['format'] == 'PDF 1.3'
    assert output.metadata['format'] == 'PDF 1.7', 'serializer PDF version'
    assert {k: v for k, v in source.metadata.items() if k != 'format'} == {k: v for k, v in output.metadata.items() if k != 'format'}, 'document metadata'
    assert source.get_toc() == output.get_toc(), 'document outline'
    links = output[0].get_links()
    assert len(links) == 3
    targets = []
    for link, operation in zip(links, operations, strict=True):
        if 'url' in operation:
            assert link['kind'] == pymupdf.LINK_URI
            assert link['uri'] == operation['url'], 'link URI'
            targets.append(link['uri'])
        else:
            assert link['kind'] == pymupdf.LINK_GOTO
            assert link['page'] == operation['destPage'] - 1, 'link destination'
            targets.append({'page': link['page'] + 1})
        rect = operation['rect']
        expected = [rect[0], 400 - rect[3], rect[2], 400 - rect[1]]
        assert max(abs(a-b) for a, b in zip(link['from'], expected, strict=True)) < .001, 'link rectangle'
    renders = []
    for index in range(3):
        a, b = source[index], output[index]
        assert a.get_text() == b.get_text(), 'page text'
        assert tuple(a.mediabox) == tuple(b.mediabox)
        assert tuple(a.cropbox) == tuple(b.cropbox), 'page crop'
        assert a.rotation == b.rotation
        assert before.pages[index].get_contents().get_data() == after.pages[index].get_contents().get_data(), 'page content stream'
        assert canonical(before.pages[index].get('/Resources')) == canonical(after.pages[index].get('/Resources')), 'page resources'
        original_annots = [canonical(n) for n in before.pages[index].get('/Annots', [])]
        actual_annots = [canonical(n) for n in after.pages[index].get('/Annots', [])]
        if index == 0:
            assert not original_annots
            assert len(actual_annots) == 3
        else:
            assert original_annots == actual_annots, 'original annotations'
            assert [{k: str(v) for k,v in n.items() if k not in ['xref','id']} for n in a.get_links()] == [{k: str(v) for k,v in n.items() if k not in ['xref','id']} for n in b.get_links()]
        aa, bb = a.get_pixmap(alpha=False), b.get_pixmap(alpha=False)
        assert (aa.width, aa.height, aa.n, aa.samples) == (bb.width, bb.height, bb.n, bb.samples)
        renders.append(hashlib.sha256(bb.samples).hexdigest())
    assert canonical(before.get_fields()) == canonical(after.get_fields())
    source.close(); output.close()
    return {'ok': True, 'sourceSha256': hashlib.sha256(source_bytes).hexdigest(),
            'outputSha256': hashlib.sha256(output_bytes).hexdigest(), 'targets': targets,
            'allPageRendersEqual': True, 'pagePixelSha256': renders, 'pdfHeaderVersion': {'source': '1.3', 'saved': '1.7'},
            'preserved': ['text', 'content streams', 'page geometry', 'resources and image', 'original link and note', 'metadata', 'outline', 'form census']}


if __name__ == '__main__':
    directory = Path(sys.argv[1])
    result = verify(directory)
    (directory / 'independent-check.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
