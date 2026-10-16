import pytest


@pytest.mark.parametrize('missing', [False, True])
def test_toc_matches_wrapped_titles_but_still_requires_every_heading(missing):
    from smart_reporting.reporting.delivery.report_runtime.runtime import _toc_headings_present

    headings = [{'level': 2, 'number': '1', 'title': '收入趋势与预算执行分析'},
                {'level': 3, 'number': '1.1', 'title': '本期变化'}]
    text = '目录\n1. 收入趋势与\n预算执行分析 1\n'
    if not missing:
        text += '1.1 本期变化 2\n'
    assert _toc_headings_present(text, headings) is not missing


def test_wide_pdf_table_stays_inside_printable_area():
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from weasyprint import HTML

    from smart_reporting.reporting.delivery.report_runtime.markdown import _semantic_documents

    from .test_report_runtime_full_render import _build_workspace

    with TemporaryDirectory() as directory:
        state = _build_workspace(Path(directory))
        cells = ''.join('<td>109,771.85</td>' for _ in range(13))
        body = '<h2 id="report-section-overview">1. 经营概览</h2><table><tr>' + cells + '</tr></table>'
        pdf, _ = _semantic_documents(body, context=state['_documentContext'], layout={},
                                     include_cover=False, include_toc=False)
        document = HTML(string=pdf).render()
        tables = [box for page in document.pages for box in page._page_box.descendants()
                  if box.element_tag == 'table' and box.__class__.__name__ == 'TableBox']
        assert tables
        for table in tables:
            assert table.position_x + table.width <= document.pages[0].width - 35
