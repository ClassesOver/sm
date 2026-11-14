"""落款前间距必须体现在每张原生幻灯片的坐标及续页预算中。"""
from copy import deepcopy

import pytest
from pptx import Presentation
from pptx.util import Pt

from smart_reporting.management.preference_preflight_readback import _slide_signature
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


def _build(tmp_path, gap=18, aspect='16:9', description='', **style):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'SpacingSigner', 'dateFormat': 'iso'}, 'pptx': {
            'aspectRatio': aspect, 'footer': {'right': 'PAGE {slide}/{slides}'},
            'signature': {'spaceBefore': gap, 'description': description, **style}}}), 'pptx')
    frozen = deepcopy(prefs)
    path = tmp_path / 'leading-space.pptx'
    result = build_editable_pptx(output_path=path, title='间距验证', period='2026', theme='executive',
        slides=({'title': '正文', 'bullets': ['BODY preserved 1234.5600']},),
        preferences=prefs, generated_date='2026-11-12')
    assert prefs == frozen
    return path, prefs, result


def _signature_pages(deck):
    for slide in deck.slides:
        headings = [shape for shape in slide.shapes if shape.has_text_frame
            and shape.text in {'报告落款', '报告落款（附加说明续页）'}]
        if headings:
            heading = headings[0]
            body = sorted((shape for shape in slide.shapes if shape.has_text_frame and shape != heading
                and not shape.text.startswith('PAGE ')), key=lambda shape: (shape.top, shape.left))
            yield heading, body


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
@pytest.mark.parametrize('gap', [0, 18, 144])
def test_signature_leading_space_is_actual_native_distance(tmp_path, gap, aspect):
    path, _, _ = _build(tmp_path, gap, aspect)
    pages = list(_signature_pages(Presentation(path)))
    assert len(pages) == 1
    heading, body = pages[0]
    assert (body[0].top - heading.top - heading.height) / 12700 == pytest.approx(gap, abs=.002)


def test_all_signature_continuations_preserve_gap_content_and_footer_budget(tmp_path):
    lines = [f'DESC{index:02} 完整说明 ' + '长文本内容' * 3 for index in range(16)]
    path, _, result = _build(tmp_path, 144, '4:3', '\n'.join(lines), size=24)
    deck = Presentation(path)
    pages = list(_signature_pages(deck))
    assert len(pages) > 2
    text = []
    for heading, body in pages:
        assert (body[0].top - heading.top - heading.height) / 12700 == pytest.approx(144, abs=.002)
        text.extend(shape.text for shape in body)
        for shape in body:
            assert shape.top + shape.height < deck.slide_height - Pt(40)
    actual = ''.join(text)
    assert actual.count('SpacingSigner') == 1
    for line in lines:
        assert actual.count(line) == 1
    assert not any('unfit' in issue.get('code', '') for issue in result.issues)


def test_reader_checks_later_continuation_native_gap(tmp_path):
    path, prefs, _ = _build(tmp_path, 144, description='\n'.join('DESC%02d ' % i + 'x' * 30 for i in range(12)), size=24)
    deck = Presentation(path)
    pages = list(_signature_pages(deck))
    assert len(pages) > 2
    frozen = {'state': {'_documentContext': {'title': '间距验证', 'periodLabel': '2026', 'generatedDate': '2026-11-12'}}}
    checks = []
    def check(path, actual, expected, *args, **kwargs):
        checks.append((path, actual, expected, kwargs))
    _slide_signature(deck, prefs, frozen, check)
    spacing = [item for item in checks if item[0] == 'signature.spaceBefore']
    assert spacing and all(actual == expected for _, actual, expected, _ in spacing)
    pages[1][1][0].top += Pt(5)
    checks.clear()
    _slide_signature(deck, prefs, frozen, check)
    assert any(actual != expected for path, actual, expected, _ in checks if path == 'signature.spaceBefore')


def test_maximum_signature_gap_and_spacing_finish_with_content_and_soft_warning(tmp_path, monkeypatch):
    from functools import partial
    from smart_reporting.reporting.delivery import pptx as delivery
    from smart_reporting.reporting.delivery.office_engine import run_bridge

    monkeypatch.setattr(delivery, 'run_bridge', partial(run_bridge, timeout=10))
    path, _, result = _build(tmp_path, 144, description='DESC impossible spacing preserved',
        size=72, lineHeight=3, dateGap=72, spaceAfter=72)
    deck = Presentation(path)
    assert len(deck.slides) < 10
    text = ''.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    assert 'SpacingSigner' in text and 'DESC impossible spacing preserved' in text
    assert any(issue.get('code') == 'pptx_signature_identity_spacing_unfit' for issue in result.issues)
    for heading, body in _signature_pages(deck):
        assert (body[0].top - heading.top - heading.height) / 12700 == pytest.approx(144, abs=.002)
    assert result.size == path.stat().st_size > 0 and result.sha256


def test_signature_gap_uses_actual_fitted_heading_height_on_each_page(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'HeadingSigner'}, 'pptx': {'aspectRatio': '4:3',
            'typography': {'h1': {'size': 72, 'lineHeight': 3, 'spaceBefore': 72, 'spaceAfter': 72}},
            'signature': {'spaceBefore': 144, 'size': 24,
                'description': '\n'.join(f'DESC{i:02} 逐页标题预算验证' for i in range(12))}}}), 'pptx')
    path = tmp_path / 'heading-budget.pptx'
    build_editable_pptx(output_path=path, title='标题预算', period='2026', theme='executive',
        slides=({'title': '正文', 'bullets': ['BODY preserved']},), preferences=prefs, generated_date='2026-11-12')
    pages = list(_signature_pages(Presentation(path)))
    assert len(pages) > 1
    for heading, body in pages:
        assert (body[0].top - heading.top - heading.height) / 12700 == pytest.approx(144, abs=.002)
