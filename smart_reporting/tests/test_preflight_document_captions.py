"""图注独立回读覆盖全部语义图注，不能凭第一图批准编号。"""
import pytest

from smart_reporting.management import preference_preflight_readback as module


@pytest.mark.parametrize('numbered', [True, False])
def test_document_caption_expectations_ignore_unpaired_prose_and_preserve_inline_text(numbered):
    markdown = ('*图表：独立说明*\n\n![alt](one.png)\n\n*图表：第一 **趋势***\n\n'
        '![alt](two.png)\n\n无图注\n\n![alt](three.png)\n\n*图表：第二趋势*')
    assert module._document_captions(markdown, numbered) == ([
        '图 1：第一 趋势', '图 2：第二趋势'] if numbered else ['图表：第一 趋势', '图表：第二趋势'])


@pytest.mark.parametrize('numbered', [True, False])
def test_pdf_caption_readback_detects_missing_second_and_duplicate_first(numbered):
    markdown = '![a](one.png)\n\n*图表：第一*\n\n![b](two.png)\n\n*图表：第二*'
    expected = (['图 1：第一', '图 2：第二'] if numbered else ['图表：第一', '图表：第二'])
    for text, passed in [('正文\n' + '\n'.join(expected), True), (expected[0] + expected[0], False)]:
        checks = []
        def check(path, actual, wanted, **kwargs):
            assert kwargs['coverage'] == 'sample'
            checks.append((path, actual == wanted))
        module._check_pdf_captions(text, markdown, numbered, check)
        assert checks and all(item[0] == 'charts.captionNumbering' for item in checks)
        assert all(item[1] for item in checks) is passed


def test_unresolved_caption_citations_cannot_be_falsely_verified():
    assert module._document_captions('![a](a.png)\n\n*图表：趋势[[citation:x]]*', True) == []


def test_pdf_caption_substring_evidence_cannot_approve_extra_suffix():
    from smart_reporting.management.preference_preflight import _capabilities

    checks = []
    def check(path, actual, expected, **kwargs):
        checks.append({'path': 'pdf.' + path, 'passed': actual == expected, **kwargs})
    module._check_pdf_captions('图 1：趋势伪造后缀', '![a](a.png)\n\n*图表：趋势*', True, check)
    capabilities = _capabilities('pdf', {'charts': {'captionNumbering': True}}, {'checks': checks}, {})
    assert capabilities[0]['status'] == 'not_verified'
