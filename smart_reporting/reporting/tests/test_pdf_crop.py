"""Actual PDF crop boxes, unchanged content/widgets and source-index composition."""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import NameObject, NumberObject, RectangleObject
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf


def object_bytes(value):
    output = BytesIO()
    value.write_to_stream(output)
    return output.getvalue()


def crop_fixture(rotation=0, unit=1, page_count=3):
    output = BytesIO()
    canvas = Canvas(output, pagesize=(400, 500))
    canvas.setTitle('Native crop acceptance')
    for index in range(page_count):
        canvas.drawString(25, 450, f'UNCHANGED PAGE {index}')
        canvas.drawString(1, 2, 'HIDDEN CONTENT STILL EXISTS')
        if index == 0:
            canvas.acroForm.textfield(name='contact', x=40, y=320, width=120, height=20, value='original')
            canvas.acroForm.checkbox(name='consent', x=40, y=280, checked=True)
            for value, x in [('basic', 40), ('pro', 80)]:
                canvas.acroForm.radio(name='plan', value=value, x=x, y=250, selected=value == 'basic')
        canvas.bookmarkPage(f'page-{index}')
        canvas.addOutlineEntry(f'Page {index}', f'page-{index}', 0)
        canvas.showPage()
    canvas.save()
    reader = PdfReader(BytesIO(output.getvalue()))
    writer = PdfWriter(clone_from=reader)
    for index, page in enumerate(writer.pages):
        page.cropbox = RectangleObject([10, 20, 390, 480])
        page[NameObject('/Rotate')] = NumberObject((rotation + index * 90) % 360)
        page[NameObject('/UserUnit')] = NumberObject(unit)
    writer.add_annotation(0, Text(rect=(50, 60, 70, 78), text='keep note'))
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('unit', [1, 2])
def test_crop_preserves_content_media_rotation_userunit_forms_and_annotations(rotation, unit):
    source = crop_fixture(rotation, unit)
    digest = hashlib.sha256(source).hexdigest()
    model = inspect_pdf(source)
    assert model['capabilities']['cropPage'] is True
    first = model['pages'][0]['pageId']
    result = patch_pdf(source, [{'kind': 'cropPage', 'pageId': first, 'rect': [35, 55, 355, 435]}])
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(result))
    assert list(after.pages[0].cropbox) == [35, 55, 355, 435]
    assert len(after.pages) == len(before.pages)
    for index, (old, new) in enumerate(zip(before.pages, after.pages, strict=True)):
        assert list(new.mediabox) == list(old.mediabox)
        assert new.get('/Rotate') == old.get('/Rotate')
        assert new.get('/UserUnit') == old.get('/UserUnit')
        assert new.get_contents().get_data() == old.get_contents().get_data()
        assert new.extract_text() == old.extract_text()
        assert 'HIDDEN CONTENT STILL EXISTS' in new.extract_text()
        assert [object_bytes(a.get_object()) for a in new.get('/Annots', [])] == [object_bytes(a.get_object()) for a in old.get('/Annots', [])]
        if index:
            assert list(new.cropbox) == list(old.cropbox)
    assert {name: object_bytes(field) for name, field in after.get_fields().items()} == {name: object_bytes(field) for name, field in before.get_fields().items()}
    assert [item.title for item in after.outline] == [item.title for item in before.outline]
    assert hashlib.sha256(source).hexdigest() == digest
    assert patch_pdf(source, []) is source
    with pytest.raises(ValueError):
        patch_pdf(result, [{'kind': 'cropPage', 'pageId': first, 'rect': [40, 60, 350, 430]}])


def test_crops_compose_in_source_space_with_rotation_reorder_delete_and_form_write():
    source = crop_fixture()
    model = inspect_pdf(source)
    first, second, third = [page['pageId'] for page in model['pages']]
    field = next(field for field in model['formFields'] if field['name'] == 'contact')
    result = patch_pdf(source, [
        {'kind': 'cropPage', 'pageId': first, 'rect': [20, 30, 380, 470]},
        {'kind': 'rotatePage', 'pageId': first, 'delta': 90},
        {'kind': 'cropPage', 'pageId': first, 'rect': [30, 40, 370, 460]},
        {'kind': 'cropPage', 'pageId': third, 'rect': [50, 60, 350, 440]},
        {'kind': 'deletePage', 'pageId': second},
        {'kind': 'reorderPages', 'pageIds': [third, first]},
        {'kind': 'setFormValue', 'name': field['name'], 'fieldId': field['fieldId'], 'expectedFieldSha256': field['expectedFieldSha256'], 'fieldKind': 'text', 'value': 'Ada'},
    ])
    reader = PdfReader(BytesIO(result))
    assert [list(page.cropbox) for page in reader.pages] == [[50, 60, 350, 440], [30, 40, 370, 460]]
    assert [page.get('/Rotate') for page in reader.pages] == [180, 90]
    assert ['PAGE 2' in reader.pages[0].extract_text(), 'PAGE 0' in reader.pages[1].extract_text()] == [True, True]
    assert reader.get_fields()['contact']['/V'] == 'Ada'
    assert reader.get_fields()['plan']['/V'] == '/basic'
    saved = inspect_pdf(result)
    assert next(field for field in saved['formFields'] if field['name'] == 'contact')['value'] == 'Ada'


@pytest.mark.parametrize('rect', [
    [0, 20, 390, 480], [10, 19, 390, 480], [10, 20, 391, 480], [10, 20, 390, 481],
    [30, 40, 30, 80], [30, 40, 29, 80], [30, 40, 30.1, 80], [30, 40, 80, 40.1],
    [10, 20, 30], [10, 20, 30, 40, 50], ['10', 20, 30, 40], None,
])
def test_invalid_crop_is_rejected(rect):
    source = crop_fixture()
    first = inspect_pdf(source)['pages'][0]['pageId']
    with pytest.raises(ValueError):
        patch_pdf(source, [{'kind': 'cropPage', 'pageId': first, 'rect': rect}])


@pytest.mark.parametrize('case', ['growth', 'delete_before', 'delete_after', 'stale', 'extra', 'digest'])
def test_crop_rejects_conflicts_and_identity_failures(case):
    source = crop_fixture()
    first = inspect_pdf(source)['pages'][0]['pageId']
    crop = {'kind': 'cropPage', 'pageId': first, 'rect': [20, 30, 380, 470]}
    operations = [crop]
    if case == 'growth':
        operations.append({**crop, 'rect': [10, 20, 390, 480]})
    elif case == 'delete_before':
        operations.insert(0, {'kind': 'deletePage', 'pageId': first})
    elif case == 'delete_after':
        operations.append({'kind': 'deletePage', 'pageId': first})
    elif case == 'stale':
        crop['pageId'] = 'foreign'
    elif case == 'extra':
        crop['injected'] = True
    elif case == 'digest':
        crop['sourceSha256'] = '0' * 64
    with pytest.raises(ValueError):
        patch_pdf(source, operations)
