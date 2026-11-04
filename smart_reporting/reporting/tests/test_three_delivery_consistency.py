"""同一离线冻结输入经实际导出器交付，核对指标、单位、期间与结论。"""
from __future__ import annotations

import csv
from io import BytesIO

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.delivery.report_runtime import ReportRuntime
from smart_reporting.reporting.delivery.xlsx import build_workbook
from smart_reporting.reporting.tests.test_report_runtime_full_render import (
    _DEPENDENCIES_OK,
    _SKIP_REASON,
    _build_workspace,
)


@pytest.mark.skipif(not _DEPENDENCIES_OK, reason=_SKIP_REASON)
def test_three_delivery_exporters_preserve_one_frozen_input(tmp_path):
    root = tmp_path / "frozen"
    state = _build_workspace(root)
    with (root / "data/overview.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    revenue = rows[0]
    period = state["_documentContext"]["periodLabel"]
    conclusion = "核心指标保持平稳"
    text = f"{period} 营业收入 {revenue['value']} {revenue['unit']}，{conclusion}。"
    markdown = root / "report.md"
    markdown.write_text(markdown.read_text(encoding="utf-8") + f"\n\n{text}\n", encoding="utf-8")
    document = ReportRuntime(root).render_markdown(
        state, "report.md", "out/report.pdf", ".reporting-tmp/workspace-report-consistency-render/render.pdf",
    )
    deck_path = root / "out/report.pptx"
    build_editable_pptx(output_path=deck_path, title="经营概览", period=period,
        theme="executive", slides=({"title": "营业收入", "bullets": [text],
                                     "evidenceIds": ["analysis_001"]},))
    workbook_path = root / "out/report.xlsx"
    build_workbook(output_path=workbook_path, title="经营概览", period=period,
        sheets=(
            {"name": "汇总", "rows": [["指标", "数值", "单位", "期间", "结论"],
                [revenue['metric'], {"value": float(revenue['value']), "formula": "='经营报表'!B2"},
                 revenue['unit'], period, conclusion]]},
            {"name": "经营报表", "rows": [["指标", "数值", "单位", "期间"],
                [revenue['metric'], float(revenue['value']), revenue['unit'], period]]},
            {"name": "明细", "rows": [list(revenue), *[list(row.values()) for row in rows]]},
        ), source_mapping={"datasetPath": "data/overview.csv", "sha256": state['sources'][0]['sha256']})
    pdf_text = ''.join(page.extract_text() for page in PdfReader(root / document['pdfPath']).pages)
    word = Document(root / document['wordPath'])
    word_text = ''.join(p.text for p in word.paragraphs) + ''.join(
        p.text for section in word.sections for part in (section.header, section.footer)
        for p in part.paragraphs
    )
    slide_text = ''.join(shape.text for slide in Presentation(deck_path).slides
                         for shape in slide.shapes if shape.has_text_frame)
    for rendered in (pdf_text, word_text, slide_text):
        normalized = ''.join(rendered.split())
        assert f"{revenue['value']}{revenue['unit']}" in normalized
        assert conclusion in normalized
        assert ''.join(period.split()) in normalized
    workbook = load_workbook(workbook_path, data_only=True)
    assert workbook.sheetnames == ['汇总', '经营报表', '明细']
    assert workbook['汇总']['B2'].value == float(revenue['value'])
    assert workbook['汇总']['C2'].value == revenue['unit']
    assert workbook['汇总']['D2'].value == period
    assert workbook['汇总']['E2'].value == conclusion
    assert load_workbook(BytesIO(workbook_path.read_bytes()), data_only=False)['汇总']['B2'].value == "='经营报表'!B2"
