"""Selected-line markups use pinned annotation/AP writer and immutable page IDs."""
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture

KINDS = {'highlight': ('Highlight', [1, .87, .35]), 'underline': ('Underline', [.17, .4, 1]), 'squiggly': ('Squiggly', [.13, .65, .35]), 'strikeout': ('StrikeOut', [.86, .22, .18])}
QUADS = [[40, 420, 150, 420, 40, 400, 150, 400], [40, 390, 210, 390, 40, 370, 210, 370]]


def markup_source(rotation=0, unit=1):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(size_fixture(rotation))))
    writer.pages[0][NameObject('/UserUnit')] = NumberObject(unit)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def operation(source, kind='underline'):
    model = inspect_pdf(source)
    return {'kind': 'addMarkup', 'pageId': model['pages'][0]['pageId'], 'markupType': kind, 'quads': QUADS, 'color': KINDS[kind][1]}


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('unit', [1, 2])
def test_selection_markup_writes_real_type_quads_color_and_appearance_without_content_changes(kind, rotation, unit):
    source = markup_source(rotation, unit)
    result = patch_pdf(source, [operation(source, kind)])
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(result))
    annotations = [item.get_object() for item in after.pages[0]['/Annots']]
    actual = annotations[-1]
    subtype, color = KINDS[kind]
    assert actual['/Subtype'] == '/' + subtype
    assert list(actual['/QuadPoints']) == [number for quad in QUADS for number in quad]
    assert list(actual['/C']) == pytest.approx(color)
    assert list(actual['/Rect']) == [40, 370, 210, 420]
    appearance = actual['/AP']['/N'].get_data()
    assert b' re f' in appearance if kind == 'highlight' else b' RG' in appearance
    assert b' c' in appearance if kind == 'squiggly' else appearance
    for old, new in zip(before.pages, after.pages, strict=True):
        assert old.get_contents().get_data() == new.get_contents().get_data()
        assert old.extract_text() == new.extract_text()
        assert list(old.cropbox) == list(new.cropbox)
        assert new.get('/Rotate') == old.get('/Rotate')
        assert new.get('/UserUnit', 1) == old.get('/UserUnit', 1)
    assert {name: value.get('/V') for name, value in before.get_fields().items()} == {name: value.get('/V') for name, value in after.get_fields().items()}
    inspected = inspect_pdf(result)
    assert inspected['capabilities']['selectionMarkup'] is True
    assert inspected['pages'][0]['markupReadSafe'] is True
    assert inspected['pages'][0]['markups'][-1]['markupType'] == kind
    assert inspected['pages'][0]['markups'][-1]['quads'] == QUADS
    with pytest.raises(ValueError):
        patch_pdf(result, [operation(source, kind)])


@pytest.mark.parametrize('change', [
    {'quads': []}, {'quads': [QUADS[0]] * 201}, {'quads': [[1, 2, 3]]},
    {'quads': [[0, 420, 150, 420, 0, 400, 150, 400]]},
    {'quads': [[40, 420, 40, 420, 40, 400, 40, 400]]},
    {'quads': [[40, 420, 150, 419, 40, 400, 150, 400]]},
    {'markupType': 'ink'}, {'color': [2, 0, 0]}, {'extra': True}, {'sourceSha256': '0' * 64},
])
def test_bad_selection_markup_fails_before_output(change):
    source = markup_source()
    with pytest.raises(ValueError):
        patch_pdf(source, [{**operation(source), **change}])


def test_unreadable_existing_markup_disables_new_selection_commands_and_forced_requests():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(markup_source())))
    writer.pages[0]['/Annots'].append(writer._add_object(DictionaryObject({NameObject('/Subtype'): NameObject('/Underline'), NameObject('/QuadPoints'): ArrayObject([NumberObject(1), NumberObject(2)])})))
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    assert inspect_pdf(source)['pages'][0]['markupReadSafe'] is False
    with pytest.raises(ValueError):
        patch_pdf(source, [operation(source)])
    assert patch_pdf(source, []) is source


def test_selection_markup_keeps_source_target_under_reorder_and_pending_rotation():
    source = markup_source()
    model = inspect_pdf(source)
    first, second, third = [page['pageId'] for page in model['pages']]
    result = patch_pdf(source, [operation(source), {'kind': 'rotatePage', 'pageId': first, 'delta': 90}, {'kind': 'deletePage', 'pageId': second}, {'kind': 'reorderPages', 'pageIds': [third, first]}])
    reader = PdfReader(BytesIO(result))
    assert len(reader.pages) == 2
    assert reader.pages[1].get('/Rotate') == 90
    assert reader.pages[1]['/Annots'][-1].get_object()['/Subtype'] == '/Underline'
    assert 'PAGE 0' in reader.pages[1].extract_text()
