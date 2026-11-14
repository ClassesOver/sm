"""可视签名放入已有签名字段（固定源 placeSignatureInField）：真实 PDF 服务预览、保存签发与 pypdf 独立回读。"""
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_existing_image_replace import _fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _source(signed=False):
    writer = PdfWriter()
    page = writer.add_blank_page(400, 500)
    field = DictionaryObject({
        NameObject('/FT'): NameObject('/Sig'), NameObject('/T'): TextStringObject('甲方签字'),
        NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'), NameObject('/F'): NumberObject(4),
        NameObject('/Rect'): ArrayObject([FloatObject(40), FloatObject(60), FloatObject(240), FloatObject(120)]),
        NameObject('/P'): page.indirect_reference,
    })
    if signed:
        field[NameObject('/V')] = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Sig'), NameObject('/Filter'): NameObject('/Adobe.PPKLite')}))
    ref = writer._add_object(field)
    page[NameObject('/Annots')] = ArrayObject([ref])
    writer._root_object[NameObject('/AcroForm')] = writer._add_object(DictionaryObject({NameObject('/Fields'): ArrayObject([ref]), NameObject('/SigFlags'): NumberObject(1)}))
    stream = BytesIO(); writer.write(stream)
    return stream.getvalue()


async def _model(editor, context):
    return (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']


def _ink(model, field, paths):
    return [{'kind': 'addDrawing', 'sourceSha256': model['sourceSha256'], 'pageId': model['pages'][0]['pageId'], 'shape': 'ink', 'paths': paths,
             'color': [0.15, 0.15, 0.15], 'width': 1.6, 'signatureField': {'fieldId': field['fieldId'], 'expectedFieldSha256': field['expectedFieldSha256']}}]


@pytest.mark.anyio
async def test_signature_into_field_saves_associated_ink_and_reopens_as_signed(tmp_path):
    content = _source()
    editor, context, downloads = await _fixture(tmp_path, content)
    model = await _model(editor, context)
    field = model['signatureFields'][0]
    assert field['name'] == '甲方签字' and field['bindable'] and field['widgets'] == [{'pageIndex': 0, 'rect': [40, 60, 240, 120]}]
    operations = _ink(model, field, [[64.4, 115.2, 140, 80, 215.6, 64.8]])
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
    assert preview['model']['signatureFields'][0]['visuallySigned'] is True
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id='signature-field')
    assert result['revisionRegistered']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    saved = b''.join([part async for part in chunks])
    reader = PdfReader(BytesIO(saved))
    annotations = [item.get_object() for item in reader.pages[0]['/Annots']]
    ink = next(item for item in annotations if item['/Subtype'] == '/Ink')
    assert ink['/GenOfficeFormField'] == '甲方签字' and str(ink['/Contents']).endswith('甲方签字')
    widget = next(item for item in annotations if item['/Subtype'] == '/Widget')
    assert '/V' not in widget, '可视签名不写入证书签名值'
    assert PdfReader(BytesIO(content)).pages[0]['/Annots'][0].get_object()['/T'] == '甲方签字'


@pytest.mark.anyio
async def test_signed_field_outside_rect_and_stale_identity_are_rejected(tmp_path):
    editor, context, _ = await _fixture(tmp_path, _source(signed=True))
    model = await _model(editor, context)
    field = model['signatureFields'][0]
    assert field['signed'] is True and field['bindable'] is False and '证书签名' in field['reason']
    with pytest.raises(ReportingError):
        await editor.preview(context, expected_sha256=context.source_file.sha256, operations=_ink(model, field, [[64, 80, 200, 100]]))
    editor, context, _ = await _fixture(tmp_path / 'open', _source())
    model = await _model(editor, context)
    field = model['signatureFields'][0]
    for operations in (_ink(model, field, [[10, 80, 200, 100]]), _ink(model, {**field, 'expectedFieldSha256': 'f' * 64}, [[64, 80, 200, 100]])):
        with pytest.raises(ReportingError):
            await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
