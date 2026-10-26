from __future__ import annotations

from types import SimpleNamespace

from smart_reporting.report_editor.chart_templates import TEMPLATE_IDS, template_availability
from smart_reporting.report_editor.table_ai import _review_payload, _template_availability, _template_spec
from smart_reporting.reporting.hospital_operation.deterministic_analysis import DeterministicAnalysisBundle


def _fact_ref(fact_id: str) -> SimpleNamespace:
    return SimpleNamespace(analysis_id="analysis_001", fact_key=fact_id)


def test_review_payload_carries_per_cell_fact_sources() -> None:
    """逐格来源（§14.1 第 4 步）：数据格携带 FactRef，行标签格不携带。"""
    trace = SimpleNamespace(
        row_keys=("period:2025-09", "total"),
        column_keys=("收入（万元）",),
        cells=(
            SimpleNamespace(
                row_key="period:2025-09", column_key="收入（万元）",
                value_selector="periodValues.0", fact_refs=(_fact_ref("fact-aaaaaaaaaaaaaaaa"),),
            ),
            SimpleNamespace(
                row_key="total", column_key="收入（万元）",
                value_selector="total", fact_refs=(_fact_ref("fact-aaaaaaaaaaaaaaaa"),),
            ),
        ),
    )
    markdown = (
        "[[table:t1]]\n"
        "| | 收入（万元） |\n"
        "| --- | ---: |\n"
        "| 2025年9月 | 3,600 |\n"
        "| 合计 | 3,600 |\n\n"
        "[[/table:t1]]"
    )
    payload = _review_payload("", markdown, trace)
    period_cell = payload["rows"][0]["cells"][1]
    assert period_cell["source"] == {
        "analysisId": "analysis_001",
        "factIds": ["fact-aaaaaaaaaaaaaaaa"],
        "selector": "periodValues.0",
    }
    total_cell = payload["rows"][1]["cells"][1]
    assert total_cell["source"]["selector"] == "total"
    # 行标签列（第 0 列）不携带来源。
    assert "source" not in payload["rows"][0]["cells"][0]
    # 未提供 trace 时来源缺省，审阅仍可用。
    assert "source" not in _review_payload("", markdown)["rows"][0]["cells"][1]


def test_all_chart_templates_are_deterministic_and_disable_without_facts() -> None:
    bundle = DeterministicAnalysisBundle(analysisId="analysis_001")
    assert TEMPLATE_IDS == ("composition-bars", "monthly-trend", "yoy-comparison", "budget-progress")
    for template_id in TEMPLATE_IDS:
        available, reason = template_availability(template_id, bundle)
        assert available is False
        assert reason


def test_all_table_templates_disable_without_registered_facts() -> None:
    bundle = DeterministicAnalysisBundle(analysisId="analysis_001")
    for template_id in ("composition", "yoy-comparison", "budget-execution", "monthly-detail"):
        available, reason = _template_availability(template_id, bundle)
        assert available is False
        assert reason
        spec, skipped = _template_spec(template_id, bundle)
        assert spec is None
        if template_id != "budget-execution":
            assert skipped
