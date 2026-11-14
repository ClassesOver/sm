"""独立 pypdf 回读静态填写下载：内容图像、透明度、metadata 与原生表单隔离。"""
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream


root = Path(sys.argv[1])
source = PdfReader(root / 'source.pdf')
results = []
for filename, expected_text, expected_count in [
    ('downloaded.pdf', '中文填写\nStatic form', 3),
    ('downloaded-edited.pdf', '保存后重新编辑', 2),
]:
    raw = (root / filename).read_bytes()
    reader = PdfReader(root / filename)
    records = json.loads(str(reader.trailer['/Root']['/GenOfficeStaticFormFills']))
    assert len(reader.pages) == len(source.pages) == 3
    assert len(records) == expected_count
    text = next(record for record in records if record['kind'] == 'text')
    assert text['text'] == expected_text
    assert text['pageIndex'] == 0
    assert set(reader.get_fields()) == set(source.get_fields()) == {'RequiredCustomer', 'NativeCheck'}
    assert reader.get_fields()['NativeCheck']['/V'] == '/Yes'
    assert reader.get_fields()['RequiredCustomer'].get('/V', '') == ''
    image_count = 0
    mask_count = 0
    for index, page in enumerate(reader.pages):
        assert page.extract_text().strip() == source.pages[index].extract_text().strip()
        assert list(page.mediabox) == list(source.pages[index].mediabox)
        xobjects = page['/Resources'].get('/XObject')
        xobjects = xobjects.get_object() if xobjects else {}
        used = {args[0] for args, operator in ContentStream(page.get_contents(), reader).operations if operator == b'Do'}
        for name, reference in xobjects.items():
            if name not in used:
                continue
            image = reference.get_object()
            if image.get('/Subtype') != '/Image':
                continue
            image_count += 1
            assert image['/Width'] > 1 and image['/Height'] > 1
            assert len(image.get_data()) == image['/Width'] * image['/Height'] * 3
            mask = image.get('/SMask')
            assert mask is not None, '静态透明图片必须保留 alpha mask'
            alpha = mask.get_object()
            assert alpha['/Width'] == image['/Width'] and alpha['/Height'] == image['/Height']
            assert 0 in alpha.get_data() and max(alpha.get_data()) > 0
            mask_count += 1
        assert all(annot.get_object().get('/Subtype') != '/Stamp' for annot in page.get('/Annots', []))
    assert image_count == mask_count == expected_count
    if filename.endswith('-edited.pdf'):
        check = next(record for record in records if record['kind'] == 'check')
        assert check['rect'] == [75, 340, 95, 362]
    results.append({'path': filename, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                    'records': records, 'images': image_count, 'alphaMasks': mask_count,
                    'nativeFieldsUnchanged': True, 'originalTextUnchanged': True})
result = {'ok': True, 'reader': 'pypdf', 'results': results}
(root / 'independent-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
