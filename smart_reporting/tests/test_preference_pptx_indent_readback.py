"""逐对象首行缩进回读；后页/末格篡改不能由首对象掩盖。"""

import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences


def _case():
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    prefs = resolve_format_preferences(FormatPreferences(common={'signer': '冻结署名'}), 'pptx')
    prefs['footer'] = {'left': '页脚 {slide}', 'center': '', 'right': ''}
    prefs['hideTitleSlideFooter'] = False
    prefs['signature']['description'] = '落款说明'
    prefs['common']['signer'] = '冻结署名'
    prefs['common']['dateFormat'] = 'iso'
    for index, role in enumerate(['h1', 'body', 'table', 'caption'], 1):
        prefs['typography'][role]['indent'] = index
    prefs['signature']['indent'], prefs['footerStyle']['indent'] = 5, 6
    frozen = {'state': {'_documentContext': {'title': '冻结报告', 'periodLabel': '冻结期间',
        'generatedDate': '2026-11-13'}}, 'slides': [
            {'title': '图源一', 'bullets': ['正文第一段', '正文第二段'], 'chartPath': 'chart1.png'},
            {'title': '图源二', 'bullets': ['正文末段'], 'chartPath': 'chart2.png'}]}
    roles = {role: [] for role in ['h1', 'body', 'table', 'caption', 'signature', 'footer']}

    def text(slide, value, role, y, x=1, width=11):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(.4))
        shape.text = value
        style = prefs['typography'][role] if role in prefs['typography'] else prefs[
            'footerStyle' if role == 'footer' else role]
        for paragraph in shape.text_frame.paragraphs:
            paragraph._p.get_or_add_pPr().set('indent', str(style['indent'] * 12700))
        roles[role].append(shape)
        return shape

    for index, title in enumerate(['冻结报告', '图源一', '图源二', '报告落款']):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        text(slide, title, 'h1', .8)
        text(slide, f'页脚 {index + 1}', 'footer', 6.9, width=3)
        if index == 0:
            text(slide, '冻结期间', 'body', 2)
            text(slide, '管理分析报告', 'body', 3)
        elif index < 3:
            source = frozen['slides'][index - 1]
            for offset, value in enumerate(source['bullets']):
                text(slide, value, 'body', 2 + offset * .6)
            text(slide, f'图 {index} {title}', 'caption', 5, x=7, width=4)
        else:
            text(slide, '冻结署名\n2026-11-13', 'signature', 2)
            text(slide, '落款说明', 'signature', 3)
    table = deck.slides[2].shapes.add_table(2, 2, Inches(1), Inches(4), Inches(5), Inches(.8))
    for row in table.table.rows:
        for cell in row.cells:
            cell.text = '原值'
            cell.text_frame.paragraphs[0]._p.get_or_add_pPr().set('indent', '38100')
    roles['table'].append(table)
    guards = [{'path': 'pptx.tables.' + key, 'passed': True, 'coverage': 'complete'} for key in
        ['content', 'visibility', 'structure', 'bounds', 'nativeRuns', 'objectCoverage']]
    guards += [{'path': 'pptx.' + key, 'passed': True, 'coverage': 'complete'} for key in
        ['common.signer', 'common.dateFormat', 'signature.description']]
    return SimpleNamespace(deck=deck, prefs=prefs, frozen=frozen, roles=roles, guards=guards)


def _read(case):
    from smart_reporting.management.preference_pptx_indent_readback import read_pptx_indents

    checks = []

    def check(path, actual, expected, message='', **kwargs):
        checks.append({'path': 'pptx.' + path, 'passed': actual == expected,
            'actual': actual, 'expected': expected, **kwargs})

    read_pptx_indents(case.deck, case.prefs, case.frozen, check, case.guards)
    return checks


def _path(role):
    return 'pptx.' + ('typography.' + role if role in ['h1', 'body', 'table', 'caption'] else
        'footerStyle' if role == 'footer' else role) + '.indent'


def test_all_six_roles_read_every_native_paragraph():
    case = _case()
    checks = _read(case)
    assert len(checks) == 6
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks), checks
    assert all(item['evidence_kind'] == 'pptx_native_indent_fields_v1' for item in checks)
    assert next(item for item in checks if item['path'] == _path('table'))['actual'] == [38100] * 4
    assert next(item for item in checks if item['path'] == _path('signature'))['actual'] == [63500] * 3


@pytest.mark.parametrize('role', ['h1', 'body', 'table', 'caption', 'signature', 'footer'])
def test_late_object_indent_tampering_fails_its_field(role):
    case = _case()
    shape = case.roles[role][-1]
    paragraph = (shape.table.cell(1, 1).text_frame.paragraphs[-1] if role == 'table'
        else shape.text_frame.paragraphs[-1])
    paragraph._p.get_or_add_pPr().set('indent', '123')
    checks = _read(case)
    assert {item['path'] for item in checks if not item['passed']} == {_path(role)}


@pytest.mark.parametrize('fault', ['missing_caption', 'unknown_body', 'hidden_footer', 'offpage_title',
    'table_guard', 'signature_guard', 'missing_indent', 'invalid_indent'])
def test_unknown_missing_invisible_and_unbound_roles_never_gain_complete_proof(fault):
    case = _case()
    role = {'missing_caption': 'caption', 'unknown_body': 'body', 'hidden_footer': 'footer',
        'offpage_title': 'h1', 'table_guard': 'table', 'signature_guard': 'signature',
        'missing_indent': 'body', 'invalid_indent': 'body'}[fault]
    shape = case.roles[role][-1]
    if fault == 'missing_caption':
        shape._element.getparent().remove(shape._element)
    elif fault == 'unknown_body':
        shape.text = '未绑定的额外正文'
    elif fault == 'hidden_footer':
        shape._element.xpath('.//p:cNvPr')[0].set('hidden', '1')
    elif fault == 'offpage_title':
        shape.left = -1000
    elif fault in {'table_guard', 'signature_guard'}:
        case.guards = deepcopy(case.guards)
        case.guards[0 if role == 'table' else -1]['passed'] = False
    elif fault == 'missing_indent':
        shape.text_frame.paragraphs[-1]._p.get_or_add_pPr().attrib.pop('indent')
    else:
        shape.text_frame.paragraphs[-1]._p.get_or_add_pPr().set('indent', 'not-an-integer')
    item = next(item for item in _read(case) if item['path'] == _path(role))
    assert item['passed'] is False


def test_legitimate_no_chart_table_or_footer_produces_no_vacuous_role_proof():
    case = _case()
    for source in case.frozen['slides']:
        source.pop('chartPath')
    case.prefs['footer'] = dict.fromkeys(case.prefs['footer'], '')
    for role in ['caption', 'table', 'footer']:
        for shape in case.roles[role]:
            shape._element.getparent().remove(shape._element)
    checks = _read(case)
    assert {item['path'] for item in checks} == {_path(role) for role in ['h1', 'body', 'signature']}
    assert all(item['passed'] for item in checks)


@pytest.mark.parametrize('role', ['caption', 'table'])
def test_declared_role_with_all_native_objects_removed_fails(role):
    case = _case()
    case.frozen['slides'][0]['tables'] = [{'caption': '声明表格'}]
    for shape in case.roles[role]:
        shape._element.getparent().remove(shape._element)
    item = next(item for item in _read(case) if item['path'] == _path(role))
    assert not item['passed'] and item['coverage'] != 'complete'


def test_zero_without_explicit_native_indent_cannot_hide_an_inherited_nonzero_value():
    from pptx.oxml.xmlchemy import OxmlElement

    case = _case()
    case.prefs['typography']['body']['indent'] = 0
    for shape in case.roles['body']:
        shape.text_frame.paragraphs[0]._p.get_or_add_pPr().set('indent', '0')
    shape = case.roles['body'][-1]
    shape.text_frame.paragraphs[-1]._p.get_or_add_pPr().attrib.pop('indent')
    style = OxmlElement('a:lvl1pPr')
    style.set('indent', '12700')
    shape.text_frame._txBody.find('{http://schemas.openxmlformats.org/drawingml/2006/main}lstStyle').append(style)
    item = next(item for item in _read(case) if item['path'] == _path('body'))
    assert not item['passed'] and item['coverage'] != 'complete'


def test_deleted_frozen_title_only_source_cannot_gain_h1_complete_coverage():
    case = _case()
    case.frozen['slides'].append({'title': '冻结空正文标题页', 'bullets': []})
    item = next(item for item in _read(case) if item['path'] == _path('h1'))
    assert not item['passed'] and item['coverage'] != 'complete'


def test_cover_title_cannot_replace_a_missing_identically_named_source_page():
    case = _case()
    case.frozen['slides'].append({'title': '冻结报告', 'bullets': []})
    item = next(item for item in _read(case) if item['path'] == _path('h1'))
    assert not item['passed'] and item['coverage'] != 'complete'


@pytest.fixture(scope='module', params=['16:9', '4:3'])
def real_indents(tmp_path_factory, request):
    from PIL import Image

    from smart_reporting.reporting.delivery.pptx import build_editable_pptx
    from smart_reporting.reporting.tests.test_pptx_native_tables import table_input

    root = tmp_path_factory.mktemp('indent-native-' + request.param.replace(':', '-'))
    chart = root / 'chart.png'
    Image.new('RGB', (320, 160), '#abcdef').save(chart)
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {
        'signer': '冻结独立署名', 'dateFormat': 'iso'}, 'pptx': {
            'aspectRatio': request.param, 'footer': {'left': '独立页脚', 'right': '{slide}/{slides}'},
            'footerStyle': {'indent': 43}, 'signature': {'indent': 48, 'size': 24,
                'description': '\n'.join(f'说明{index:02} ' + '完整说明段落 ' * 4 for index in range(14))},
            'typography': {role: {'indent': indent} for role, indent in
                [('h1', 7), ('body', 19), ('table', 29), ('caption', 37)]}}}), 'pptx')
    table = table_input(18)
    table['headers'] = ['期间\n原值', *[f'字段{index}' for index in range(7)]]
    table['rows'] = [[f'期间{row}', *[f'{row}.{column:04}\n原值' for column in range(7)]]
        for row in range(18)]
    slides = [{'title': '正文分页', 'bullets': ['短正文入口', *[
        f'正文{index:02} ' + '冻结内容 1234.5600 ' * 45 for index in range(3)]]},
        {'title': '首图原值', 'bullets': [], 'chartPath': str(chart)},
        {'title': '末图完整图注 ' * 42, 'bullets': [], 'chartPath': str(chart), 'tables': [table]}]
    frozen = {'slides': slides, 'state': {'_documentContext': {'title': '独立回读报告',
        'periodLabel': '2026年', 'generatedDate': '2026-11-13'}}}
    path = root / 'native.pptx'
    build_editable_pptx(output_path=path, title='独立回读报告', period='2026年', theme='executive',
        slides=slides, preferences=prefs, generated_date='2026-11-13')
    return SimpleNamespace(content=path.read_bytes(), prefs=prefs, frozen=frozen,
        aspect=request.param.replace(':', '-'))


@pytest.mark.parametrize('fault', ['valid', 'late_title', 'late_body', 'last_cell', 'late_caption',
    'late_signature', 'late_footer'])
def test_real_generated_all_objects_and_last_native_paragraph_faults(real_indents, fault):
    from smart_reporting.management.preference_preflight_readback import readback

    case = real_indents
    deck = Presentation(BytesIO(case.content))
    texts = [shape for slide in deck.slides for shape in slide.shapes if shape.has_text_frame]
    if fault == 'last_cell':
        tables = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
        assert len(tables) > 2
        paragraph = list(list(tables[-1].rows)[-1].cells)[-1].text_frame.paragraphs[-1]
    elif fault != 'valid':
        selected = {'late_title': lambda shape: shape.text == '报告落款（附加说明续页）',
            'late_body': lambda shape: '正文02' in shape.text or '冻结内容 1234.5600' in shape.text,
            'late_caption': lambda shape: shape.text.startswith('图 2 ') and shape.top > 150 * 9525,
            'late_signature': lambda shape: shape.text.startswith('说明13'),
            'late_footer': lambda shape: shape.text == '独立页脚'}[fault]
        matches = [shape for shape in texts if selected(shape)]
        assert matches
        paragraph = matches[-1].text_frame.paragraphs[-1]
    if fault != 'valid':
        paragraph._p.get_or_add_pPr().set('indent', '17')
        stream = BytesIO()
        deck.save(stream)
        content = stream.getvalue()
    else:
        content = case.content
    actual = readback(content, 'pptx', case.prefs, case.frozen)
    checks = [item for item in actual['checks'] if item.get('evidenceKind') == 'pptx_native_indent_fields_v1']
    root = Path('output/system-config-preferences/pptx-indent/readback') / case.aspect / fault
    if root.exists():
        root = root.with_name(root.name + '-' + uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    (root / 'actual.pptx').write_bytes(content)
    (root / 'proof.json').write_text(json.dumps({'size': len(content), 'sha256': sha256(content).hexdigest(),
        'checks': checks, 'source': case.frozen, 'preferences': case.prefs,
        'realGenerator': True, 'realReader': True, 'fixtureOnly': True,
        'visualVerified': False}, ensure_ascii=False, indent=2))
    assert len(checks) == 6
    expected = {'late_title': 'h1', 'late_body': 'body', 'last_cell': 'table', 'late_caption': 'caption',
        'late_signature': 'signature', 'late_footer': 'footer'}
    failed = {item['path'] for item in checks if not item['passed']}
    assert failed == (set() if fault == 'valid' else {_path(expected[fault])}), checks
    assert all(item['coverage'] == 'complete' for item in checks), checks


def test_real_paginated_first_bullet_uses_full_chunk_reader_instead_of_throwing(tmp_path):
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.reporting.delivery.pptx import build_editable_pptx

    prefs = resolve_format_preferences(FormatPreferences(common={'signer': '独立署名'}), 'pptx')
    prefs['typography']['body']['indent'] = 48
    source = [{'title': '完整长首段', 'bullets': ['LONGFIRST ' + '冻结原值 1234.5600 ' * 200]}]
    frozen = {'slides': source, 'state': {'_documentContext': {'title': '长首段报告',
        'periodLabel': '2026年', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'long-first.pptx'
    build_editable_pptx(output_path=output, title='长首段报告', period='2026年', theme='executive',
        slides=source, preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    deck = Presentation(BytesIO(content))
    assert not any(shape.text == source[0]['bullets'][0] for slide in deck.slides
        for shape in slide.shapes if shape.has_text_frame)
    root = Path('output/system-config-preferences/pptx-indent/readback/long-first-body')
    if root.exists():
        root = root.with_name(root.name + '-' + uuid4().hex[:8])
    root.mkdir()
    (root / 'actual.pptx').write_bytes(content)
    actual = readback(content, 'pptx', prefs, frozen)
    checks = [item for item in actual['checks'] if item.get('evidenceKind') == 'pptx_native_indent_fields_v1']
    (root / 'proof.json').write_text(json.dumps({'checks': checks, 'source': frozen, 'preferences': prefs,
        'sha256': sha256(content).hexdigest(), 'size': len(content), 'fixtureOnly': True,
        'realGenerator': True, 'realReader': True, 'visualVerified': False}, ensure_ascii=False, indent=2))
    assert checks and all(item['passed'] and item['coverage'] == 'complete' for item in checks), checks
    assert next(item for item in checks if item['path'] == _path('body'))['actual'] == [609600] * (
        len(deck.slides) - 2 + 2)
