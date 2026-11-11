"""Multi-section page setup and section breaks through the native docx bridge."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import re

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml.ns import qn
from docx.shared import Twips

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def two_sections() -> bytes:
    doc = Document()
    doc.add_paragraph('first section')
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('second section')
    doc.add_paragraph('second tail')
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def block(model, text):
    return next(item for item in model['blocks'] if item['text'] == text)


def test_inspect_exposes_every_section_with_block_ranges():
    model = inspect_docx(two_sections())
    sections = model['sections']
    assert len(sections) == 2
    assert sections[0]['firstBlockIndex'] == 0 and sections[0]['lastBlockIndex'] < sections[1]['firstBlockIndex']
    assert all(set(section) >= {'sectionId', 'expectedSectionSha256', 'settings', 'startType'} for section in sections)


@pytest.mark.parametrize('target_index', [0, 1])
def test_different_first_page_changes_only_current_section_and_preserves_all_parts(target_index):
    doc = Document(BytesIO(two_sections()))
    for index, section in enumerate(doc.sections):
        for kind in ('header', 'footer', 'first_page_header', 'first_page_footer'):
            part = getattr(section, kind)
            part.is_linked_to_previous = False
            part.paragraphs[0].text = f'{index}:{kind}'
    stream = BytesIO(); doc.save(stream); source = stream.getvalue()
    for enabled in (True, False):
        model = inspect_docx(source)
        target = model['sections'][target_index]
        assert target['titlePg'] is (not enabled if enabled is False else False)
        patched = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'],
                                    'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'titlePg': enabled}}])
        actual = Document(BytesIO(patched))
        assert [section.different_first_page_header_footer for section in actual.sections] == [enabled if i == target_index else False for i in range(2)]
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
            assert {name for name in before.namelist() if not name.endswith('/')} == {name for name in after.namelist() if not name.endswith('/')}
            mutable = {'word/document.xml'}
            assert {name: before.read(name) for name in before.namelist() if name not in mutable and not name.endswith('/')} == {name: after.read(name) for name in after.namelist() if name not in mutable and not name.endswith('/')}
            without_title = lambda xml: re.sub(rb'<w:titlePg\b[^>]*/>', b'', xml)
            assert without_title(before.read('word/document.xml')) == without_title(after.read('word/document.xml'))
        assert [section['titlePg'] for section in inspect_docx(patched)['sections']] == [enabled if i == target_index else False for i in range(2)]
        source = patched


def test_unknown_title_page_state_is_read_only_and_cannot_be_normalized_by_a_toggle():
    source = two_sections()
    with ZipFile(BytesIO(source)) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    entries['word/document.xml'] = entries['word/document.xml'].replace(b'</w:sectPr>', b'<w:titlePg w:val="unexpected"/></w:sectPr>', 1)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        for name, content in entries.items(): package.writestr(name, content)
    source = output.getvalue()
    target = inspect_docx(source)['sections'][0]
    assert target['titlePg'] is None and target['titlePgReadOnlyReason']
    with pytest.raises(ValueError, match='section_title_page_unsupported'):
        patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'],
                            'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'titlePg': True}}])


def test_even_odd_headers_are_document_wide_and_preserve_all_unrelated_parts():
    doc = Document(BytesIO(two_sections()))
    for index, section in enumerate(doc.sections):
        for kind in ('header', 'footer', 'even_page_header', 'even_page_footer'):
            part = getattr(section, kind); part.is_linked_to_previous = False
            part.paragraphs[0].text = f'{index}:{kind}'
    stream = BytesIO(); doc.save(stream); source = stream.getvalue()
    for enabled in (True, False):
        model = inspect_docx(source); target = model['sections'][-1]
        assert model['headersFooters']['evenAndOddHeaders'] is (not enabled)
        patched = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'],
                                    'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'evenAndOddHeaders': enabled}}])
        assert Document(BytesIO(patched)).settings.odd_and_even_pages_header_footer is enabled
        assert inspect_docx(patched)['headersFooters']['evenAndOddHeaders'] is enabled
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
            assert {name: before.read(name) for name in before.namelist() if name != 'word/settings.xml' and not name.endswith('/')} == {name: after.read(name) for name in after.namelist() if name != 'word/settings.xml' and not name.endswith('/')}
            strip_flag = lambda xml: re.sub(rb'<w:evenAndOddHeaders\b[^>]*/>', b'', xml)
            assert strip_flag(before.read('word/settings.xml')) == strip_flag(after.read('word/settings.xml'))
        source = patched


@pytest.mark.parametrize('marker', [b'<w:evenAndOddHeaders w:val="unknown"/>', b'<w:evenAndOddHeaders/><w:evenAndOddHeaders/>', b'<alt:evenAndOddHeaders xmlns:alt="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'])
def test_even_odd_headers_reject_unknown_source_or_non_document_anchor(marker):
    source = two_sections(); model = inspect_docx(source); first = model['sections'][0]
    with pytest.raises(ValueError, match='document_header_footer_anchor_invalid'):
        patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': first['sectionId'], 'expectedSectionSha256': first['expectedSectionSha256'], 'values': {'evenAndOddHeaders': True}}])
    with ZipFile(BytesIO(source)) as original: entries = {name: original.read(name) for name in original.namelist()}
    entries['word/settings.xml'] = entries['word/settings.xml'].replace(b'</w:settings>', marker + b'</w:settings>')
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as package:
        for name, content in entries.items(): package.writestr(name, content)
    source = stream.getvalue(); model = inspect_docx(source); target = model['sections'][-1]
    assert model['headersFooters']['evenAndOddHeadersReadOnlyReason']
    with pytest.raises(ValueError, match='document_even_odd_unsupported'):
        patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'evenAndOddHeaders': True}}])


@pytest.mark.parametrize('target_index', [0, 1])
def test_page_number_format_and_restart_patch_only_the_selected_section(target_index):
    source = two_sections()
    for values in ({'pageNumberFmt': 'upperRoman', 'pageNumberStart': 0}, {'pageNumberFmt': 'lowerRoman', 'pageNumberStart': 4294967295}, {'pageNumberFmt': None, 'pageNumberStart': None}):
        model = inspect_docx(source); target = model['sections'][target_index]
        assert 'pageNumberFmt' in target and 'pageNumberStart' in target
        patched = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'],
                                    'expectedSectionSha256': target['expectedSectionSha256'], 'values': values}])
        actual = inspect_docx(patched)['sections']
        assert actual[target_index]['pageNumberFmt'] == values['pageNumberFmt']
        assert actual[target_index]['pageNumberStart'] == values['pageNumberStart']
        assert actual[1 - target_index]['pageNumberFmt'] == model['sections'][1 - target_index]['pageNumberFmt']
        assert actual[1 - target_index]['pageNumberStart'] == model['sections'][1 - target_index]['pageNumberStart']
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
            assert {name: before.read(name) for name in before.namelist() if name != 'word/document.xml' and not name.endswith('/')} == {name: after.read(name) for name in after.namelist() if name != 'word/document.xml' and not name.endswith('/')}
            strip_pg = lambda xml: re.sub(rb'<w:pgNumType\b[^>]*/>', b'', xml)
            assert strip_pg(before.read('word/document.xml')) == strip_pg(after.read('word/document.xml'))
        source = patched


@pytest.mark.parametrize('marker', [b'<w:pgNumType w:fmt="unknown"/>', b'<w:pgNumType w:start="-1"/>', b'<w:pgNumType w:chapStyle="1"/>', b'<w:pgNumType/><w:pgNumType/>'])
def test_unknown_page_number_source_is_preserved_and_read_only(marker):
    source = two_sections()
    with ZipFile(BytesIO(source)) as package: entries = {name: package.read(name) for name in package.namelist()}
    entries['word/document.xml'] = entries['word/document.xml'].replace(b'</w:sectPr>', marker + b'</w:sectPr>', 1)
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as package:
        for name, value in entries.items(): package.writestr(name, value)
    source = stream.getvalue(); target = inspect_docx(source)['sections'][0]
    assert target['pageNumberReadOnlyReason']
    with pytest.raises(ValueError, match='section_page_number_unsupported'):
        patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': target['sectionId'], 'expectedSectionSha256': target['expectedSectionSha256'], 'values': {'pageNumberFmt': 'decimal', 'pageNumberStart': None}}])


def test_layout_of_a_middle_section_patches_only_its_break_paragraph():
    source = two_sections()
    first = inspect_docx(source)['sections'][0]
    patched = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': first['sectionId'], 'expectedSectionSha256': first['expectedSectionSha256'],
                                   'values': {'orientation': 'landscape', 'pageWidth': 15840, 'pageHeight': 12240, 'marginLeft': 720}}])
    sections = Document(BytesIO(patched)).sections
    assert sections[0].orientation == WD_ORIENT.LANDSCAPE and sections[0].page_width == Twips(15840) and sections[0].left_margin == Twips(720)
    assert sections[1].orientation == WD_ORIENT.PORTRAIT and sections[1].page_width == Twips(12240)
    assert [p.text for p in Document(BytesIO(patched)).paragraphs if p.text] == ['first section', 'second section', 'second tail']


@pytest.mark.parametrize(('kind', 'start'), [('nextPage', WD_SECTION.NEW_PAGE), ('continuous', WD_SECTION.CONTINUOUS), ('oddPage', WD_SECTION.ODD_PAGE)])
def test_section_break_splits_the_anchor_section_and_sets_the_new_section_start(kind, start):
    source = two_sections()
    anchor = block(inspect_docx(source), 'second section')
    patched = patch_docx(source, [{'kind': 'insertSectionBreak', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'type': kind}])
    doc = Document(BytesIO(patched))
    assert len(doc.sections) == 3
    assert doc.sections[2].start_type == start
    # the inserted break paragraph carries a copy of the section's sectPr right after the anchor
    paragraphs = doc.paragraphs
    index = next(i for i, p in enumerate(paragraphs) if p.text == 'second section')
    assert paragraphs[index + 1]._p.pPr.find(qn('w:sectPr')) is not None
    assert [p.text for p in paragraphs if p.text] == ['first section', 'second section', 'second tail']


def test_section_break_in_a_middle_section_retypes_its_break_paragraph():
    source = two_sections()
    anchor = block(inspect_docx(source), 'first section')
    patched = patch_docx(source, [{'kind': 'insertSectionBreak', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'type': 'continuous'}])
    doc = Document(BytesIO(patched))
    assert len(doc.sections) == 3
    assert doc.sections[1].start_type == WD_SECTION.CONTINUOUS
    assert doc.sections[2].start_type == WD_SECTION.NEW_PAGE


def test_section_operations_reject_conflicts_and_bad_input():
    source = two_sections()
    model = inspect_docx(source)
    second = model['sections'][1]
    anchor = block(model, 'second section')
    tail = block(model, 'second tail')
    brk = lambda target, kind='nextPage': {'kind': 'insertSectionBreak', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'type': kind}
    layout = {'kind': 'setSectionLayout', 'sectionId': second['sectionId'], 'expectedSectionSha256': second['expectedSectionSha256'], 'values': {'columns': 2}}
    for operations in ([brk(anchor), brk(tail)], [brk(anchor), layout], [brk(anchor, 'nextColumn')],
                       [{**brk(anchor), 'expectedObjectSha256': 'stale'}], [{**layout, 'sectionId': 'forged'}]):
        with pytest.raises(ValueError):
            patch_docx(source, operations)
    break_paragraph = next(item for item in model['blocks'] if item['blockId'] not in {anchor['blockId'], tail['blockId']} and item['text'] == '')
    with pytest.raises(ValueError, match='section_break_anchor_invalid'):
        patch_docx(source, [brk(break_paragraph)])


def section_headers() -> bytes:
    doc = Document(BytesIO(two_sections()))
    for index, section in enumerate(doc.sections):
        section.header.is_linked_to_previous = False
        run = section.header.paragraphs[0].add_run(f'header {index}')
        run.bold = True
        section.footer.is_linked_to_previous = False
        section.footer.paragraphs[0].text = f'footer {index}'
    stream = BytesIO(); doc.save(stream)
    return stream.getvalue()


def link_operation(model, index, linked):
    section = model['sections'][index]
    part = section['headersFooters']['parts']['header.default']
    return dict(kind='setHeaderFooterLink', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'],
                part='header', variant='default', linked=linked, expectedOwnRId=part['ownRId'], expectedOwnPartSha256=part['ownPartSha256'],
                expectedOwnerSectionId=part['ownerSectionId'], expectedRId=part['rId'], expectedPartSha256=part['expectedPartSha256'],
                expectedRelationshipsSha256=part['relationshipsSha256'], expectedOwnRelationshipsSha256=part['ownRelationshipsSha256'])


def test_header_link_roundtrip_preserves_raw_part_and_other_package_members():
    source = section_headers()
    model = inspect_docx(source)
    assert model['sections'][0]['headersFooters']['parts']['header.default']['linked'] is None
    linked = patch_docx(source, [link_operation(model, 1, True)])
    linked_model = inspect_docx(linked)
    inherited = linked_model['sections'][1]['headersFooters']['parts']['header.default']
    assert inherited['linked'] is True
    assert inherited['text'] == 'header 0'
    assert inherited['ownerSectionId'] == linked_model['sections'][0]['sectionId']
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(linked)) as new:
        assert [name for name in old.namelist() if not name.endswith('/')] == [name for name in new.namelist() if not name.endswith('/')]
        for name in old.namelist():
            if name != 'word/document.xml': assert old.read(name) == new.read(name), name
    unlinked = patch_docx(linked, [link_operation(linked_model, 1, False)])
    own_model = inspect_docx(unlinked)
    own = own_model['sections'][1]['headersFooters']['parts']['header.default']
    assert own['linked'] is False and own['ownerSectionId'] == own_model['sections'][1]['sectionId']
    assert own['rId'] != inherited['rId']
    with ZipFile(BytesIO(linked)) as old, ZipFile(BytesIO(unlinked)) as new:
        assert new.read(own['path']) == old.read(inherited['path'])
        for name in old.namelist():
            if name not in ('word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'): assert old.read(name) == new.read(name), name
    target = own_model['sections'][1]
    changed = patch_docx(unlinked, [dict(kind='setHeaderFooter', sectionId=target['sectionId'], expectedSectionSha256=target['expectedSectionSha256'],
        part='header', variant='default', expectedPartSha256=own['expectedPartSha256'], text='new own text', pageNumber=False)])
    result = inspect_docx(changed)
    assert result['sections'][0]['headersFooters']['parts']['header.default']['text'] == 'header 0'
    assert result['sections'][1]['headersFooters']['parts']['header.default']['text'] == 'new own text'


def test_header_link_refuses_first_section_and_forged_effective_owner():
    model = inspect_docx(source := section_headers())
    with pytest.raises(Exception, match='hf_link_first_section'):
        patch_docx(source, [link_operation(model, 0, True)])
    forged = link_operation(model, 1, True)
    forged['expectedOwnerSectionId'] = model['sections'][0]['sectionId']
    with pytest.raises(Exception, match='hf_anchor_invalid'):
        patch_docx(source, [forged])


@pytest.mark.parametrize('target_index', [1, 2])
def test_link_close_targets_only_tail_of_identical_section_xml(target_index):
    doc = Document()
    doc.add_paragraph('first')
    doc.sections[0].header.paragraphs[0].text = 'inherited'
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('middle')
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('tail')
    stream = BytesIO(); doc.save(stream)
    source = stream.getvalue()
    with ZipFile(BytesIO(source)) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    entries['word/document.xml'] = re.sub(rb'<w:sectPr\b[^>]*>', b'<w:sectPr>', entries['word/document.xml'])
    rewritten = BytesIO()
    with ZipFile(rewritten, 'w', ZIP_DEFLATED) as package:
        for name, content in entries.items(): package.writestr(name, content)
    source = rewritten.getvalue(); model = inspect_docx(source)
    # 中间/尾节均没有own引用，w:sectPr实际XML完全相同。
    output = patch_docx(source, [link_operation(model, target_index, False)])
    result = inspect_docx(output)
    assert [section['headersFooters']['parts']['header.default']['linked'] for section in result['sections']] == ([None, False, True] if target_index == 1 else [None, True, False])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        from lxml import etree
        old = etree.fromstring(before.read('word/document.xml')).findall('.//' + qn('w:sectPr'))
        new = etree.fromstring(after.read('word/document.xml')).findall('.//' + qn('w:sectPr'))
        assert etree.tostring(old[1]) == etree.tostring(old[2])
        for index in range(3):
            if index != target_index: assert etree.tostring(old[index]) == etree.tostring(new[index])


def test_header_link_requires_section_breaks_to_be_saved_first():
    source = section_headers(); model = inspect_docx(source)
    first = block(model, 'first section')
    operation = dict(kind='insertSectionBreak', blockId=first['blockId'], expectedObjectSha256=first['expectedObjectSha256'], type='nextPage')
    with pytest.raises(Exception, match='hf_link_pending_save'):
        patch_docx(source, [operation, link_operation(model, 1, True)])


def test_unlink_rejects_unverifiable_dynamic_inheritance_after_earlier_link_changes():
    from docx.oxml import OxmlElement
    from docx.opc.constants import RELATIONSHIP_TYPE
    doc = Document(BytesIO(section_headers()))
    first = doc.sections[0].header
    rid = first.part.relate_to('https://example.com', RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement('w:hyperlink'); hyperlink.set(qn('r:id'), rid)
    run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'linked'; run.append(text); hyperlink.append(run)
    first.paragraphs[0]._p.append(hyperlink)
    doc.add_section(WD_SECTION.NEW_PAGE); doc.add_paragraph('third')
    stream = BytesIO(); doc.save(stream)
    source = rewrite_hf_package(stream.getvalue(), lambda entries: entries.__setitem__('word/header1.xml', entries['word/header1.xml'].replace(b'r:id="rId1"', b'r:id="missing"')))
    model = inspect_docx(source)
    assert model['sections'][0]['headersFooters']['parts']['header.default']['editable'] is False
    assert model['sections'][2]['headersFooters']['parts']['header.default']['editable'] is True
    with pytest.raises(Exception, match='hf_link_unsupported'):
        patch_docx(source, [link_operation(model, 1, True), link_operation(model, 2, False)])


def test_unlink_clones_pending_inherited_content_written_to_original_owner():
    source = section_headers(); source = patch_docx(source, [link_operation(inspect_docx(source), 1, True)])
    model = inspect_docx(source); owner = model['sections'][0]; part = owner['headersFooters']['parts']['header.default']
    operation = dict(kind='setHeaderFooter', sectionId=owner['sectionId'], expectedSectionSha256=owner['expectedSectionSha256'], part='header', variant='default',
        expectedPartSha256=part['expectedPartSha256'], text='pending inherited text', pageNumber=False)
    output = patch_docx(source, [operation, link_operation(model, 1, False)])
    result = inspect_docx(output)
    assert [section['headersFooters']['parts']['header.default']['text'] for section in result['sections']] == ['pending inherited text', 'pending inherited text']
    own = result['sections'][1]['headersFooters']['parts']['header.default']
    assert own['ownRId'] != result['sections'][0]['headersFooters']['parts']['header.default']['ownRId']


def picture_hyperlink_headers() -> bytes:
    from docx.oxml import OxmlElement
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches
    from PIL import Image
    picture = BytesIO(); Image.new('RGB', (12, 8), '#3483ab').save(picture, format='PNG'); picture.seek(0)
    doc = Document(BytesIO(section_headers()))
    first = doc.sections[0].header
    first.paragraphs[0].add_run().add_picture(picture, width=Inches(.5))
    rid = first.part.relate_to('https://example.com/a?b=1&c=2', RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement('w:hyperlink'); hyperlink.set(qn('r:id'), rid)
    run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'example link'; run.append(text); hyperlink.append(run)
    first.paragraphs[0]._p.append(hyperlink)
    doc.sections[1].header.is_linked_to_previous = True
    stream = BytesIO(); doc.save(stream)
    return stream.getvalue()


def test_unlink_copies_picture_and_external_link_relationships_and_keeps_edit_independent():
    source = rewrite_hf_package(picture_hyperlink_headers(), lambda entries: entries.__setitem__('word/header1.xml', re.sub(rb'mc:Ignorable="[^"]*"', b'mc:Ignorable="w14"', entries['word/header1.xml'])))
    model = inspect_docx(source)
    first, second = model['sections']
    effective = second['headersFooters']['parts']['header.default']
    assert effective['editable'], effective.get('readOnlyReason')
    assert effective['relationshipsSha256']
    output = patch_docx(source, [link_operation(model, 1, False)])
    result = inspect_docx(output); own = result['sections'][1]['headersFooters']['parts']['header.default']
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(output)) as new:
        assert new.read(own['path']) == old.read(effective['path'])
        old_rels = effective['path'].replace('word/', 'word/_rels/') + '.rels'
        new_rels = own['path'].replace('word/', 'word/_rels/') + '.rels'
        assert new.read(new_rels) == old.read(old_rels)
        assert b'TargetMode="External"' in new.read(new_rels)
        for name in old.namelist():
            if name not in ('word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'): assert old.read(name) == new.read(name), name
    section = result['sections'][1]
    changed = patch_docx(output, [dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'],
        part='header', variant='default', expectedPartSha256=own['expectedPartSha256'], text='changed independent header with image and link', pageNumber=False)])
    changed_model = inspect_docx(changed)
    assert changed_model['sections'][0]['headersFooters']['parts']['header.default']['expectedPartSha256'] == first['headersFooters']['parts']['header.default']['expectedPartSha256']
    with ZipFile(BytesIO(changed)) as edited, ZipFile(BytesIO(output)) as before:
        assert edited.read(new_rels) == before.read(new_rels)
        from lxml import etree
        xml = etree.fromstring(edited.read(own['path']))
        original_xml = etree.fromstring(before.read(effective['path']))
        assert all(xml.nsmap.get(prefix) == uri for prefix, uri in original_xml.nsmap.items())
        assert xml.get('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable') == 'w14'
        from PIL import Image
        with Image.open(BytesIO(edited.read('word/media/image1.png'))) as image: assert image.size == (12, 8)
        assert len(xml.findall('.//' + qn('w:drawing'))) == 1
        assert len(xml.findall('.//' + qn('w:hyperlink'))) == 1


def rewrite_hf_package(source: bytes, change) -> bytes:
    with ZipFile(BytesIO(source)) as package: entries = {name: package.read(name) for name in package.namelist() if not name.endswith('/')}
    change(entries)
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as package:
        for name, content in entries.items(): package.writestr(name, content)
    return stream.getvalue()


def test_unlink_verifies_nested_dependencies_and_copies_relationships_without_rewriting_shared_parts():
    def add_chart(entries):
        entries['word/_rels/header1.xml.rels'] = entries['word/_rels/header1.xml.rels'].replace(b'</Relationships>', b'<Relationship Id="rChart" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="./charts/../charts/chart1.xml"/></Relationships>')
        entries['word/charts/chart1.xml'] = b'<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><c:externalData r:id="rPackage"/></c:chartSpace>'
        entries['word/charts/_rels/chart1.xml.rels'] = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rPackage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/data.xlsx"/></Relationships>'
        from openpyxl import Workbook
        stream = BytesIO(); Workbook().save(stream); entries['word/embeddings/data.xlsx'] = stream.getvalue()
        entries['[Content_Types].xml'] = entries['[Content_Types].xml'].replace(b'</Types>', b'<Override PartName="/word/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/><Override PartName="/word/embeddings/data.xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/></Types>')
    source = rewrite_hf_package(picture_hyperlink_headers(), add_chart); model = inspect_docx(source)
    part = model['sections'][1]['headersFooters']['parts']['header.default']
    assert part['editable'], part.get('readOnlyReason')
    output = patch_docx(source, [link_operation(model, 1, False)])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        for name in ('word/charts/chart1.xml', 'word/charts/_rels/chart1.xml.rels', 'word/embeddings/data.xlsx', 'word/media/image1.png'):
            assert before.read(name) == after.read(name)
    broken = rewrite_hf_package(source, lambda entries: entries.pop('word/embeddings/data.xlsx'))
    broken_part = inspect_docx(broken)['sections'][1]['headersFooters']['parts']['header.default']
    assert broken_part['editable'] is False
    assert '缺失' in broken_part['readOnlyReason']


@pytest.mark.parametrize('fault', ['missing-media', 'missing-content-type', 'duplicate-id', 'unknown-type', 'dangling-id', 'cycle'])
def test_unverifiable_header_relationships_are_read_only_with_specific_reasons(fault):
    def corrupt(entries):
        if fault == 'missing-media': entries.pop('word/media/image1.png')
        elif fault == 'missing-content-type': entries['[Content_Types].xml'] = re.sub(rb'<Default Extension="png"[^>]*/>', b'', entries['[Content_Types].xml'])
        elif fault == 'duplicate-id': entries['word/_rels/header1.xml.rels'] = entries['word/_rels/header1.xml.rels'].replace(b'</Relationships>', b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>')
        elif fault == 'unknown-type': entries['word/_rels/header1.xml.rels'] = entries['word/_rels/header1.xml.rels'].replace(b'/relationships/image', b'/relationships/unknown')
        elif fault == 'dangling-id': entries['word/header1.xml'] = entries['word/header1.xml'].replace(b'r:embed="rId1"', b'r:embed="rMissing"')
        else: entries['word/_rels/header1.xml.rels'] = entries['word/_rels/header1.xml.rels'].replace(b'media/image1.png', b'header1.xml')
    source = rewrite_hf_package(picture_hyperlink_headers(), corrupt)
    model = inspect_docx(source); part = model['sections'][1]['headersFooters']['parts']['header.default']
    assert part['editable'] is False
    assert part['readOnlyReason']
    assert part['relationshipsSha256'] is None
    with pytest.raises(Exception, match='hf_link_unsupported'):
        patch_docx(source, [link_operation(model, 1, False)])


def test_header_link_relationship_identity_cannot_be_forged():
    source = picture_hyperlink_headers(); model = inspect_docx(source)
    operation = link_operation(model, 1, False); operation['expectedRelationshipsSha256'] = 'forged'
    with pytest.raises(Exception, match='hf_anchor_invalid'): patch_docx(source, [operation])


def test_unlink_copies_supported_media_from_dynamic_owner_changed_by_earlier_link():
    doc = Document(BytesIO(picture_hyperlink_headers()))
    doc.sections[1].header.is_linked_to_previous = False
    doc.sections[1].header.paragraphs[0].text = 'temporary own'
    doc.add_section(WD_SECTION.NEW_PAGE); doc.add_paragraph('third')
    stream = BytesIO(); doc.save(stream)
    source = stream.getvalue(); model = inspect_docx(source)
    output = patch_docx(source, [link_operation(model, 1, True), link_operation(model, 2, False)])
    result = inspect_docx(output)
    first = result['sections'][0]['headersFooters']['parts']['header.default']
    third = result['sections'][2]['headersFooters']['parts']['header.default']
    assert third['editable'] and not third['linked']
    with ZipFile(BytesIO(output)) as package:
        assert package.read(first['path']) == package.read(third['path'])
        assert package.read(first['path'].replace('word/', 'word/_rels/') + '.rels') == package.read(third['path'].replace('word/', 'word/_rels/') + '.rels')


def test_header_edit_restores_source_namespaces_when_the_original_root_is_self_closing():
    source = rewrite_hf_package(section_headers(), lambda entries: entries.__setitem__('word/header1.xml', b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
    model = inspect_docx(source); section = model['sections'][0]; part = section['headersFooters']['parts']['header.default']
    assert part['editable'], part.get('readOnlyReason')
    output = patch_docx(source, [dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'],
        part='header', variant='default', expectedPartSha256=part['expectedPartSha256'], text='new text', pageNumber=False)])
    with ZipFile(BytesIO(output)) as package:
        from lxml import etree
        xml = etree.fromstring(package.read(part['path']))
        assert ''.join(xml.itertext()) == 'new text'


@pytest.mark.parametrize('directory', ['word/headers', 'other/headers', 'word/header assets/nested'])
def test_unlink_keeps_nonstandard_header_directory_and_resolves_all_original_dependencies(directory):
    from posixpath import dirname, join, normpath, relpath
    from urllib.parse import quote, unquote
    from lxml import etree
    def relocate(entries):
        path = f'{directory}/header1.xml'; rel_path = f'{directory}/_rels/header1.xml.rels'
        entries[path] = entries.pop('word/header1.xml')
        rels = etree.fromstring(entries.pop('word/_rels/header1.xml.rels'))
        for relationship in rels:
            if relationship.get('TargetMode') != 'External': relationship.set('Target', quote(relpath('word/media/image1.png', directory)))
        entries[rel_path] = etree.tostring(rels)
        document_rels = etree.fromstring(entries['word/_rels/document.xml.rels'])
        for relationship in document_rels:
            if relationship.get('Target') == 'header1.xml': relationship.set('Target', quote(relpath(path, 'word')))
        entries['word/_rels/document.xml.rels'] = etree.tostring(document_rels)
        entries['[Content_Types].xml'] = entries['[Content_Types].xml'].replace(b'PartName="/word/header1.xml"', f'PartName="/{quote(path)}"'.encode())
    source = rewrite_hf_package(picture_hyperlink_headers(), relocate); model = inspect_docx(source)
    part = model['sections'][1]['headersFooters']['parts']['header.default']
    assert part['editable'], part.get('readOnlyReason')
    output = patch_docx(source, [link_operation(model, 1, False)])
    output_model = inspect_docx(output)
    own = output_model['sections'][1]['headersFooters']['parts']['header.default']
    assert own['editable'], own.get('readOnlyReason')
    assert dirname(own['path']) == directory
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        assert after.read(own['path']) == before.read(part['path'])
        own_rels = join(dirname(own['path']), '_rels', own['path'].rsplit('/', 1)[-1] + '.rels')
        old_rels = join(directory, '_rels', 'header1.xml.rels')
        assert after.read(own_rels) == before.read(old_rels)
        relationships = etree.fromstring(after.read(own_rels))
        for relationship in relationships:
            if relationship.get('TargetMode') == 'External':
                assert relationship.get('Target') == 'https://example.com/a?b=1&c=2'
            else:
                target = normpath(join(dirname(own['path']), unquote(relationship.get('Target'))))
                assert target == 'word/media/image1.png'
                assert after.read(target) == before.read(target)
        for name in before.namelist():
            if name not in ('word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'): assert before.read(name) == after.read(name), name

    section = output_model['sections'][1]
    edited = patch_docx(output, [dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'],
        part='header', variant='default', expectedPartSha256=own['expectedPartSha256'], text='edited independent nonstandard header', pageNumber=False)])
    edited_model = inspect_docx(edited)
    assert edited_model['sections'][1]['headersFooters']['parts']['header.default']['editable']
    with ZipFile(BytesIO(edited)) as after, ZipFile(BytesIO(output)) as before:
        assert after.read(part['path']) == before.read(part['path'])
        assert after.read(own_rels) == before.read(own_rels)
        assert after.read('word/media/image1.png') == before.read('word/media/image1.png')
        xml = etree.fromstring(after.read(own['path']))
        assert len(xml.findall('.//' + qn('w:drawing'))) == 1
        assert len(xml.findall('.//' + qn('w:hyperlink'))) == 1


@pytest.mark.parametrize('media', [False, True])
def test_unlink_and_edit_new_own_header_in_one_save_preserves_original_part(media):
    source = picture_hyperlink_headers() if media else section_headers()
    if not media: source = patch_docx(source, [link_operation(inspect_docx(source), 1, True)])
    model = inspect_docx(source); section = model['sections'][1]; inherited = section['headersFooters']['parts']['header.default']
    operation = dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'], part='header', variant='default',
        expectedPartSha256=inherited['expectedPartSha256'], text='same-save new own text', pageNumber=False, afterLink=True)
    output = patch_docx(source, [link_operation(model, 1, False), operation])
    result = inspect_docx(output); own = result['sections'][1]['headersFooters']['parts']['header.default']
    assert len(result['sections']) == len(model['sections'])
    assert own['linked'] is False and own['editable']
    assert own['text'] == 'same-save new own text'
    assert result['sections'][0]['headersFooters']['parts']['header.default']['expectedPartSha256'] == model['sections'][0]['headersFooters']['parts']['header.default']['expectedPartSha256']
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(output)) as new:
        assert old.read(inherited['path']) == new.read(inherited['path'])
        strip_refs = lambda xml: re.sub(rb'<w:headerReference\b[^>]*/>', b'', xml)
        assert strip_refs(old.read('word/document.xml')) == strip_refs(new.read('word/document.xml'))
        for name in old.namelist():
            if name not in ('word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'): assert old.read(name) == new.read(name), name
        if media:
            from lxml import etree
            xml = etree.fromstring(new.read(own['path']))
            assert len(xml.findall('.//' + qn('w:drawing'))) == 1
            assert len(xml.findall('.//' + qn('w:hyperlink'))) == 1
            assert new.read(own['path'].replace('word/', 'word/_rels/') + '.rels') == old.read(inherited['path'].replace('word/', 'word/_rels/') + '.rels')
            assert new.read('word/media/image1.png') == old.read('word/media/image1.png')


def test_after_link_content_requires_matching_unlink_and_original_source_identity():
    source = picture_hyperlink_headers(); model = inspect_docx(source); section = model['sections'][1]
    operation = dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'], part='header', variant='default',
        expectedPartSha256=section['headersFooters']['parts']['header.default']['expectedPartSha256'], text='unsafe', pageNumber=False, afterLink=True)
    with pytest.raises(Exception, match='hf_after_link_invalid'): patch_docx(source, [operation])
    with pytest.raises(Exception, match='hf_anchor_invalid'): patch_docx(source, [link_operation(model, 1, False), {**operation, 'expectedPartSha256': 'forged'}])


def test_link_on_and_edit_inherited_owner_in_one_save_keeps_discarded_own_part_unchanged():
    source = section_headers(); model = inspect_docx(source); owner = model['sections'][0]; part = owner['headersFooters']['parts']['header.default']
    operation = dict(kind='setHeaderFooter', sectionId=owner['sectionId'], expectedSectionSha256=owner['expectedSectionSha256'], part='header', variant='default',
        expectedPartSha256=part['expectedPartSha256'], text='shared owner edited after linking', pageNumber=False)
    output = patch_docx(source, [link_operation(model, 1, True), operation]); result = inspect_docx(output)
    assert [section['headersFooters']['parts']['header.default']['text'] for section in result['sections']] == ['shared owner edited after linking', 'shared owner edited after linking']
    discarded = model['sections'][1]['headersFooters']['parts']['header.default']['ownPath']
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after: assert before.read(discarded) == after.read(discarded)


def test_cascaded_unlinks_keep_the_edited_intermediate_owner_and_media_in_one_save():
    doc = Document(BytesIO(picture_hyperlink_headers())); doc.add_section(WD_SECTION.NEW_PAGE); doc.add_paragraph('third')
    stream = BytesIO(); doc.save(stream); source = stream.getvalue(); model = inspect_docx(source)
    operations = []
    for index in (1, 2):
        section = model['sections'][index]; part = section['headersFooters']['parts']['header.default']
        operations.extend([link_operation(model, index, False), dict(kind='setHeaderFooter', sectionId=section['sectionId'], expectedSectionSha256=section['expectedSectionSha256'],
            part='header', variant='default', expectedPartSha256=part['expectedPartSha256'], text='intermediate X', pageNumber=False, afterLink=True)])
    output = patch_docx(source, operations); result = inspect_docx(output)
    assert [section['headersFooters']['parts']['header.default']['text'] for section in result['sections']] == ['header 0example link', 'intermediate X', 'intermediate X']
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        from lxml import etree
        assert before.read('word/header1.xml') == after.read('word/header1.xml')
        assert before.read('word/media/image1.png') == after.read('word/media/image1.png')
        for section in result['sections'][1:]:
            path = section['headersFooters']['parts']['header.default']['path']; xml = etree.fromstring(after.read(path))
            assert len(xml.findall('.//' + qn('w:drawing'))) == 1
            assert len(xml.findall('.//' + qn('w:hyperlink'))) == 1
