"""同一完整原生组和独立留存XLSX才可产生最多13项字段证据。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.header_footer import HeaderFooter

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)
from smart_reporting.reporting.tests.test_workbook_header_footer_style import _preferences
from smart_reporting.reporting.tests.test_workbook_header_footer_style import (
    styled_workbook as styled_workbook,
)

FIELDS = ('enabled', 'header.left', 'header.center', 'header.right', 'footer.left', 'footer.center',
    'footer.right', 'style.font', 'style.size', 'style.color', 'style.bold', 'headerDistance', 'footerDistance')
PREFIX = 'xlsx.print.headerFooter.'


def material(styled_workbook):
    source, frozen = styled_workbook
    content = source.read_bytes()
    artifact = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64, 'contractHash': approval_contract_hash(contract),
        'executorManifestHash': 'b' * 64}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'xlsx': {'artifact': artifact, 'readback': readback(content, 'xlsx', _preferences(), frozen)}}}
    return result, contract, binding, {'formats': {'xlsx': {'artifact': deepcopy(artifact)}}, 'issues': []}


def mapped(inputs):
    from smart_reporting.management.preference_workbook_header_footer_evidence import (
        map_workbook_header_footer_evidence,
    )

    return map_workbook_header_footer_evidence(*inputs)


def test_maps_only_thirteen_complete_native_fields_without_approving_full_contract(styled_workbook):
    inputs = material(styled_workbook)
    before = deepcopy(inputs)
    rows = mapped(inputs)
    assert inputs == before
    assert len(rows) == 13 and {row['path'] for row in rows} == {PREFIX + field for field in FIELDS}
    assert all(row['format'] == 'xlsx' and row['role'] == 'print' and row['dimension'] == 'native'
        and row['scenario'] == 'configured_field' and row['status'] == 'passed'
        and row['objectScope'] == 'complete' for row in rows)
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    assert not any(gap.get('path') in {row['path'] for row in rows}
        and gap.get('scenario') == 'configured_field' for gap in gaps)


@pytest.mark.parametrize('fault', ['authority', 'binding', 'draft', 'contract', 'retained_size', 'retained_hash',
    'retention_issue', 'preview_only', 'pdf_only'])
def test_requires_current_binding_and_same_independently_retained_xlsx(styled_workbook, fault):
    inputs = material(styled_workbook)
    result, _, binding, retained = inputs
    if fault == 'authority':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'binding':
        result['binding']['valid'] = False
    elif fault == 'draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'contract':
        binding['contractHash'] = 'c' * 64
    elif fault == 'retained_size':
        retained['formats']['xlsx']['artifact']['size'] += 1
    elif fault == 'retained_hash':
        retained['formats']['xlsx']['artifact']['sha256'] = 'c' * 64
    elif fault == 'retention_issue':
        retained['issues'] = [{'format': 'xlsx', 'role': 'artifact'}]
    elif fault == 'preview_only':
        retained['formats']['xlsx']['pdf'] = retained['formats']['xlsx'].pop('artifact')
    else:
        result['formats']['pdf'] = result['formats'].pop('xlsx')
    assert mapped(inputs) == []


@pytest.mark.parametrize('fault', ['missing_guard', 'duplicate_guard', 'group_sample', 'unverified_source',
    'zero_sheets', 'boolean_count', 'missing_sheet', 'duplicate_variant', 'missing_variant', 'aliased_part'])
def test_incomplete_or_ambiguous_group_cannot_grant_passed_fields(styled_workbook, fault):
    inputs = material(styled_workbook)
    read = inputs[0]['formats']['xlsx']['readback']
    checks = read['checks']
    guard = next(item for item in checks if item['path'] == PREFIX + 'nativeStructure')
    summary = read['headerFooterReadback']
    if fault == 'missing_guard':
        checks.remove(guard)
    elif fault == 'duplicate_guard':
        checks.append(deepcopy(guard))
    elif fault == 'group_sample':
        guard['coverage'] = 'sample'
    else:
        if fault == 'unverified_source':
            summary['sourceStatus'] = 'unverified'
        elif fault == 'zero_sheets':
            summary['expectedSheets'] = summary['nativeSheets'] = summary['checkedSheets'] = 0
        elif fault == 'boolean_count':
            summary['checkedSheets'] = True
        elif fault == 'missing_sheet':
            summary['sheetNames'].pop()
        elif fault == 'duplicate_variant':
            summary['variants'].append(deepcopy(summary['variants'][0]))
        elif fault == 'missing_variant':
            summary['variants'].pop()
        else:
            summary['worksheetParts'][1] = summary['worksheetParts'][0]
        guard['evidenceObjects'] = deepcopy(summary)
    assert not any(row['status'] == 'passed' for row in mapped(inputs))


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'sample', 'unmarked', 'wrong_location', 'wrong_count'])
def test_partial_field_cannot_hide_behind_other_complete_fields(styled_workbook, fault):
    inputs = material(styled_workbook)
    checks = inputs[0]['formats']['xlsx']['readback']['checks']
    path = PREFIX + 'footer.right'
    item = next(item for item in checks if item['path'] == path)
    if fault == 'missing':
        checks.remove(item)
    elif fault == 'duplicate':
        checks.append(deepcopy(item))
    elif fault == 'sample':
        item['coverage'] = 'sample'
    elif fault == 'unmarked':
        item.pop('evidenceKind')
    elif fault == 'wrong_location':
        item['evidenceObjects']['sheet'] = '未核验工作表'
    else:
        item['evidenceObjects']['part'] = 'xl/worksheets/sheet999.xml'
    rows = mapped(inputs)
    assert len(rows) == 12 and all(row['path'] != path and row['status'] == 'passed' for row in rows)


def test_any_same_path_failure_survives_later_passing_checks(styled_workbook):
    inputs = material(styled_workbook)
    checks = inputs[0]['formats']['xlsx']['readback']['checks']
    item = deepcopy(next(item for item in checks if item['path'] == PREFIX + 'footer.right'))
    item['passed'], item['actual'] = False, '错误的页脚'
    checks.append(item)
    rows = mapped(inputs)
    assert len(rows) == 13
    assert [row['path'] for row in rows if row['status'] == 'failed'] == [PREFIX + 'footer.right']


@pytest.mark.parametrize('fault', ['unhashable_sheet', 'unhashable_part', 'unhashable_variant'])
def test_malformed_variant_identity_is_unverified_without_crashing(styled_workbook, fault):
    inputs = material(styled_workbook)
    read = inputs[0]['formats']['xlsx']['readback']
    summary = read['headerFooterReadback']
    summary['variants'][0][fault.removeprefix('unhashable_')] = []
    guard = next(item for item in read['checks'] if item['path'] == PREFIX + 'nativeStructure')
    guard['evidenceObjects'] = deepcopy(summary)
    assert mapped(inputs) == []


@pytest.mark.parametrize('profile', ['disabled', 'empty'])
def test_no_native_style_objects_never_fabricate_four_style_evidence_rows(styled_workbook, profile):
    inputs = material(styled_workbook)
    prefs = _preferences()
    if profile == 'disabled':
        prefs['print']['headerFooter']['enabled'] = False
    else:
        for kind in ('header', 'footer'):
            prefs['print']['headerFooter'][kind] = dict.fromkeys(('left', 'center', 'right'), '')
    book = load_workbook(styled_workbook[0])
    for sheet in book:
        sheet.HeaderFooter = HeaderFooter()
    content = BytesIO()
    book.save(content)
    data = content.getvalue()
    artifact = {'size': len(data), 'sha256': sha256(data).hexdigest()}
    inputs[0]['formats']['xlsx'] = {'artifact': artifact,
        'readback': readback(data, 'xlsx', prefs, styled_workbook[1])}
    inputs[3]['formats']['xlsx']['artifact'] = deepcopy(artifact)
    rows = mapped(inputs)
    assert len(rows) == 9 and all(row['status'] == 'passed' for row in rows)
    assert not any(row['path'].startswith(PREFIX + 'style.') for row in rows)


@pytest.mark.parametrize('missing', [False, True])
def test_every_activated_first_and_even_variant_requires_its_own_checks(styled_workbook, missing):
    inputs = material(styled_workbook)
    book = load_workbook(styled_workbook[0])
    for sheet in book:
        sheet.HeaderFooter.differentFirst = True
        sheet.HeaderFooter.differentOddEven = True
        for variant in ('first', 'even'):
            for kind in ('Header', 'Footer'):
                setattr(sheet, variant + kind, deepcopy(getattr(sheet, 'odd' + kind)))
    content = BytesIO()
    book.save(content)
    data = content.getvalue()
    artifact = {'size': len(data), 'sha256': sha256(data).hexdigest()}
    read = readback(data, 'xlsx', _preferences(), styled_workbook[1])
    assert len(read['headerFooterReadback']['variants']) == 6
    inputs[0]['formats']['xlsx'] = {'artifact': artifact, 'readback': read}
    inputs[3]['formats']['xlsx']['artifact'] = deepcopy(artifact)
    if missing:
        read['checks'] = [item for item in read['checks'] if not (
            item['path'] == PREFIX + 'footer.right' and item.get('evidenceObjects', {}).get('variant') == 'even')]
    rows = mapped(inputs)
    assert len(rows) == (12 if missing else 13)
    assert all(row['status'] == 'passed' for row in rows)
    assert any(row['path'] == PREFIX + 'footer.right' for row in rows) is (not missing)
