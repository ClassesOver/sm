"""Source-bound saved markup removal: exact identity, preservation and composition."""
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, IndirectObject, NameObject

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
from smart_reporting.reporting.tests.test_pdf_native_text_edits import source_pdf, text_operation
from smart_reporting.reporting.tests.test_pdf_selection_markup import (
    KINDS,
    markup_source,
    operation,
)


def marked_source(kind='underline', source=None):
    source = source or markup_source()
    return patch_pdf(source, [operation(source, kind)])


def removal(source, index=0):
    page = inspect_pdf(source)['pages'][0]
    mark = page['markups'][index]
    return {'kind': 'removeMarkup', 'pageId': page['pageId'], 'annotationId': mark['annotationId'], 'expectedAnnotationSha256': mark['expectedAnnotationSha256']}


@pytest.mark.parametrize('kind', KINDS)
def test_removes_only_target_preserves_content_forms_note_and_other_markup_appearance(kind):
    source = marked_source(kind)
    other = 'highlight' if kind != 'highlight' else 'underline'
    source = patch_pdf(source, [operation(source, other)])
    result = patch_pdf(source, [removal(source)])
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(result))
    assert [mark['markupType'] for mark in inspect_pdf(result)['pages'][0]['markups']] == [other]
    for old, new in zip(before.pages, after.pages, strict=True):
        assert old.get_contents().get_data() == new.get_contents().get_data()
        assert old.extract_text() == new.extract_text()
        assert list(old.cropbox) == list(new.cropbox)
    def canonical(value):
        if isinstance(value, IndirectObject):
            return (value.idnum, value.generation)
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return value
    assert canonical(before.get_fields()) == canonical(after.get_fields())
    old_annots = [item.get_object() for item in before.pages[0]['/Annots']]
    new_annots = [item.get_object() for item in after.pages[0]['/Annots']]
    assert len(old_annots) == len(new_annots) + 1
    assert [item.get('/Subtype') for item in new_annots] == [item.get('/Subtype') for item in old_annots[:-2] + old_annots[-1:]]
    assert new_annots[-1]['/AP']['/N'].get_data() == old_annots[-1]['/AP']['/N'].get_data()
    assert patch_pdf(source, []) is source


def test_duplicate_geometry_is_not_a_delete_key_and_ids_are_revision_bound():
    source = marked_source()
    source = patch_pdf(source, [operation(source)])
    marks = inspect_pdf(source)['pages'][0]['markups']
    assert marks[0]['annotationId'] != marks[1]['annotationId']
    result = patch_pdf(source, [removal(source, 1)])
    assert len(inspect_pdf(result)['pages'][0]['markups']) == 1
    with pytest.raises(ValueError):
        patch_pdf(result, [removal(source)])


@pytest.mark.parametrize('change', [{'annotationId': '0' * 64}, {'expectedAnnotationSha256': '0' * 64}, {'sourceSha256': '0' * 64}, {'rect': [1, 2, 3, 4]}])
def test_forged_or_geometry_only_identity_is_refused(change):
    source = marked_source()
    with pytest.raises(ValueError):
        patch_pdf(source, [{**removal(source), **change}])
    assert len(inspect_pdf(source)['pages'][0]['markups']) == 1


def test_batch_duplicate_and_late_failure_never_return_partial_output():
    source = marked_source()
    op = removal(source)
    for operations in [[op, op], [op, {**op, 'annotationId': '0' * 64}], [op, {'kind': 'deletePage', 'pageId': op['pageId']}]]:
        with pytest.raises(ValueError):
            patch_pdf(source, operations)
    assert len(inspect_pdf(source)['pages'][0]['markups']) == 1


def rewrite(source, mutate):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    mutate(writer)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.mark.parametrize('protection', ['popup', 'reply', 'direct', 'perms', 'struct'])
def test_linked_direct_and_protected_annotations_stay_readonly(protection):
    def mutate(writer):
        annots = writer.pages[0]['/Annots']
        ref = annots[-1]
        if protection == 'direct':
            annots[-1] = ref.get_object()
        elif protection == 'perms':
            writer.root_object[NameObject('/Perms')] = DictionaryObject()
        elif protection == 'reply':
            annots.append(writer._add_object(DictionaryObject({NameObject('/Subtype'): NameObject('/Text'), NameObject('/IRT'): ref})))
        else:
            ref.get_object()[NameObject('/Popup' if protection == 'popup' else '/StructParent')] = ref
    source = rewrite(marked_source(), mutate)
    mark = inspect_pdf(source)['pages'][0]['markups'][0]
    assert not mark['removable'] and mark['removalReason']
    with pytest.raises(ValueError):
        patch_pdf(source, [removal(source)])


def test_shared_annotation_array_is_copied_for_one_page_only():
    def share(writer):
        writer.pages[1][NameObject('/Annots')] = writer.pages[0].raw_get('/Annots')
    source = rewrite(marked_source(), share)
    result = patch_pdf(source, [removal(source)])
    pages = inspect_pdf(result)['pages']
    assert not pages[0]['markups'] and len(pages[1]['markups']) == 1


def test_removal_composes_with_rotation_reorder_delete_and_page_size():
    source = marked_source()
    model = inspect_pdf(source)
    first, second, third = [page['pageId'] for page in model['pages']]
    result = patch_pdf(source, [removal(source), {'kind': 'rotatePage', 'pageId': first, 'delta': 90}, {'kind': 'deletePage', 'pageId': second}, {'kind': 'reorderPages', 'pageIds': [third, first]}, {'kind': 'setPageSize', 'preset': 'A4'}])
    reader = PdfReader(BytesIO(result))
    assert len(reader.pages) == 2
    assert reader.pages[1].get('/Rotate') == 90
    assert not inspect_pdf(result)['pages'][1]['markups']
    assert 'PAGE 0' in reader.pages[1].extract_text()


def test_removal_before_text_rewrite_keeps_exact_text_target():
    source = source_pdf()
    add = {'kind': 'addMarkup', 'pageId': inspect_pdf(source)['pages'][0]['pageId'], 'markupType': 'underline', 'quads': [[30, 240, 140, 240, 30, 225, 140, 225]], 'color': [.17, .4, 1]}
    source = patch_pdf(source, [add])
    result = patch_pdf(source, [removal(source), text_operation(source, 'Amount due 750')])
    text = PdfReader(BytesIO(result)).pages[0].extract_text()
    assert 'Amount due 750' in text and 'UNCHANGED CONTROL' in text
    assert not inspect_pdf(result)['pages'][0]['markups']
