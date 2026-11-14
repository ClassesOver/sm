"""PDF目录链接中的同名文字不能冒充实际正文标题的排版证据。"""

import shutil
from copy import deepcopy

import pytest

from smart_reporting.management.preference_preflight import _generate, _verify_materials
from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

from .test_preference_preflight import _inputs


@pytest.fixture(scope='module')
def toc_pdf(tmp_path_factory):
    root = tmp_path_factory.mktemp('pdf-heading-readback')
    source = root / 'source'
    source.mkdir()
    draft, materials = _inputs(source)
    draft['document']['pdf'].update(cover=True, toc=True, bookmarks=False)
    preferences = FormatPreferences.model_validate(draft['document'])
    _, frozen, _ = _verify_materials(materials, formats=('pdf',))
    for identity in materials.state['sources']:
        target = root / 'inputs' / identity['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / identity['path'], target)
    _generate(root, preferences, frozen)
    content = (root / 'inputs/revision/report.pdf').read_bytes()
    return content, resolve_format_preferences(preferences, 'pdf'), frozen


def test_pdf_heading_sample_uses_body_heading_instead_of_linked_toc(toc_pdf):
    content, preferences, frozen = toc_pdf
    result = readback(content, 'pdf', preferences, frozen)
    checks = [item for item in result['checks'] if item['path']
        and item['path'].startswith(('pdf.typography.h1.', 'pdf.typography.h2.', 'pdf.typography.h3.'))]
    assert len(checks) == 12
    assert all(item['passed'] and item['coverage'] == 'sample' for item in checks), checks


def test_pdf_matching_toc_style_cannot_hide_wrong_body_heading(toc_pdf):
    content, preferences, frozen = toc_pdf
    expected = deepcopy(preferences)
    # 目录恰好符合期望时，仍必须报告正文标题实际16磅与期望10.5磅不一致。
    expected['typography']['h1'].update(size=10.5, color='#1B2A41', bold=False)
    result = readback(content, 'pdf', expected, frozen)
    size = next(item for item in result['checks'] if item['path'] == 'pdf.typography.h1.size')
    assert not size['passed'] and abs(size['actual'] - preferences['typography']['h1']['size']) < .05, size
