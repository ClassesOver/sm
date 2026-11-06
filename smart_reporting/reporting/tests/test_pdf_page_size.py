"""Pinned paper sizing, actual content transforms and conservative source gates."""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, RectangleObject

from smart_reporting.reporting.delivery.pdf_native import (
    inspect_pdf,
    patch_pdf,
    patch_pdf_with_receipt,
)
from smart_reporting.reporting.tests.test_pdf_crop import crop_fixture

PAPERS = {'A3': (842, 1191), 'A4': (595, 842), 'A5': (420, 595), 'Letter': (612, 792), 'Legal': (612, 1008)}


def size_fixture(rotation=0):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(crop_fixture(rotation=rotation))))
    writer._root_object.pop(NameObject('/Outlines'), None)
    for page in writer.pages:
        page.mediabox = RectangleObject([10, 20, 410, 520])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('preset', PAPERS)
@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_pinned_paper_sizes_scale_contents_widgets_notes_and_frames(preset, rotation):
    source = size_fixture(rotation)
    assert inspect_pdf(source)['capabilities']['pageSize'] is True
    result = patch_pdf(source, [{'kind': 'setPageSize', 'preset': preset}])
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(result))
    target_w, target_h = PAPERS[preset]
    for old, new in zip(before.pages, after.pages, strict=True):
        angle = old.get('/Rotate', 0)
        w, h = (target_h, target_w) if angle in [90, 270] else (target_w, target_h)
        k = min(w / 400, h / 500)
        expected = [10 * k - (w - 400 * k) / 2, 20 * k - (h - 500 * k) / 2]
        assert list(new.mediabox) == pytest.approx([*expected, expected[0] + w, expected[1] + h])
        assert list(new.cropbox) == pytest.approx(list(new.mediabox))
        assert new.get('/Rotate') == angle
        assert new.extract_text() == old.extract_text()
        matrices = [operands for operands, operator in new.get_contents().operations if operator == b'cm']
        assert any([float(v) for v in matrix] == pytest.approx([k, 0, 0, k, 0, 0]) for matrix in matrices)
        old_annots = [item.get_object() for item in old.get('/Annots', [])]
        new_annots = [item.get_object() for item in new.get('/Annots', [])]
        assert len(old_annots) == len(new_annots)
        for previous, current in zip(old_annots, new_annots, strict=True):
            assert current['/Subtype'] == previous['/Subtype']
            assert list(current['/Rect']) == pytest.approx([float(value) * k for value in previous['/Rect']])
            assert current.get('/Contents') == previous.get('/Contents')
    assert {key: field.get('/V') for key, field in after.get_fields().items()} == {key: field.get('/V') for key, field in before.get_fields().items()}
    assert hashlib.sha256(source).hexdigest() == inspect_pdf(source)['sourceSha256']


def test_paper_size_composes_with_source_order_rotation_deletion_and_form_values():
    source = size_fixture()
    model = inspect_pdf(source)
    first, second, third = [page['pageId'] for page in model['pages']]
    field = next(item for item in model['formFields'] if item['name'] == 'contact')
    operations = [
        {'kind': 'setPageSize', 'preset': 'A4'},
        {'kind': 'rotatePage', 'pageId': first, 'delta': 90},
        {'kind': 'deletePage', 'pageId': second},
        {'kind': 'reorderPages', 'pageIds': [third, first]},
        {'kind': 'setFormValue', 'name': field['name'], 'fieldId': field['fieldId'], 'expectedFieldSha256': field['expectedFieldSha256'], 'fieldKind': 'text', 'value': 'Ada'},
    ]
    receipt = patch_pdf_with_receipt(source, operations)
    reader = PdfReader(BytesIO(receipt['content']))
    assert len(reader.pages) == 2
    assert [page.get('/Rotate') for page in reader.pages] == [180, 90]
    assert [(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages] == pytest.approx([(595, 842), (842, 595)])
    assert 'PAGE 2' in reader.pages[0].extract_text()
    assert reader.get_fields()['contact']['/V'] == 'Ada'
    assert receipt['appliedOperationIndices'] == list(range(5))
    assert receipt['previewDigest'] == patch_pdf_with_receipt(source, operations)['previewDigest']
    changed = [{**operations[0], 'preset': 'A5'}, *operations[1:]]
    assert receipt['previewDigest'] != patch_pdf_with_receipt(source, changed)['previewDigest']


@pytest.mark.parametrize('case', ['unit', 'outline', 'names', 'print_box', 'unknown_annotation', 'signature'])
def test_unmodeled_paper_size_sources_remain_readonly_and_forced_write_rejects(case):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(size_fixture())))
    page = writer.pages[0]
    if case == 'unit':
        page[NameObject('/UserUnit')] = NumberObject(2)
    elif case == 'outline':
        writer.add_outline_item('Original point', 0)
    elif case == 'names':
        writer._root_object[NameObject('/Names')] = DictionaryObject()
    elif case == 'print_box':
        page[NameObject('/TrimBox')] = RectangleObject([10, 20, 400, 500])
    elif case == 'unknown_annotation':
        page['/Annots'][0].get_object()[NameObject('/Subtype')] = NameObject('/Link')
    else:
        writer.get_fields()['contact'].indirect_reference.get_object()[NameObject('/FT')] = NameObject('/Sig')
    output = BytesIO()
    writer.write(output)
    source = output.getvalue()
    assert inspect_pdf(source)['capabilities']['pageSize'] is False
    with pytest.raises(ValueError):
        patch_pdf(source, [{'kind': 'setPageSize', 'preset': 'A4'}])
    assert patch_pdf(source, []) is source


@pytest.mark.parametrize('operations', [
    [{'kind': 'setPageSize', 'preset': 'A6'}],
    [{'kind': 'setPageSize', 'preset': 'A4', 'width': 595}],
    [{'kind': 'setPageSize', 'preset': 'A4', 'sourceSha256': '0' * 64}],
    [{'kind': 'setPageSize', 'preset': 'A4'}] * 2,
    [{'kind': 'setPageSize'}],
])
def test_paper_size_rejects_invalid_records(operations):
    with pytest.raises(ValueError):
        patch_pdf(size_fixture(), operations)


@pytest.mark.parametrize('kind', ['cropPage', 'replaceText'])
def test_paper_size_rejects_incompatible_coordinate_operations(kind):
    source = size_fixture()
    first = inspect_pdf(source)['pages'][0]['pageId']
    other = {'kind': kind, 'pageId': first, **({'rect': [20, 30, 380, 470]} if kind == 'cropPage' else {'objectId': 'x', 'expectedTextSha256': '0' * 64, 'newText': 'x'})}
    with pytest.raises(ValueError):
        patch_pdf(source, [{'kind': 'setPageSize', 'preset': 'A4'}, other])


def test_already_matching_source_paper_keeps_its_crop_and_content_exact():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(size_fixture())))
    for page in writer.pages:
        w, h = (842, 595) if page.get('/Rotate') in [90, 270] else (595, 842)
        page.mediabox = RectangleObject([0, 0, w, h])
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    result = patch_pdf(source, [{'kind': 'setPageSize', 'preset': 'A4'}])
    for old, new in zip(PdfReader(BytesIO(source)).pages, PdfReader(BytesIO(result)).pages, strict=True):
        assert list(new.cropbox) == list(old.cropbox)
        assert new.get_contents().get_data() == old.get_contents().get_data()
