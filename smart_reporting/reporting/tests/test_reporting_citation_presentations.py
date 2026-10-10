from __future__ import annotations

import pytest

from smart_reporting.reporting.delivery.report_runtime.pdf import _pdf_markdown
from smart_reporting.reporting.delivery.report_runtime.validation import ReportFailure


def presentation(citation_id: str) -> dict[str, object]:
    return {
        "citationId": citation_id,
        "label": f"来源 {citation_id}",
        "coverageItems": [],
    }


def test_pdf_markdown_numbers_by_first_appearance_and_reuses_alias() -> None:
    markdown = (
        "# 报告\n\n"
        "收入结论[[citation:citation_003]]\n\n"
        "成本结论[[citation:citation_001]][[citation:citation_003]]\n"
    )
    presentations = [
        presentation("citation_001"),
        presentation("citation_002"),
        presentation("citation_003"),
    ]

    visible, normalized, _trace = _pdf_markdown(markdown, presentations)

    assert visible.count("[来源 001]") == 2
    assert visible.count("[来源 002]") == 1
    assert "[[citation:" not in visible
    assert [item["citationId"] for item in normalized] == [
        "citation_003",
        "citation_001",
        "citation_002",
    ]
    assert [item["alias"] for item in normalized] == [
        "[来源 001]",
        "[来源 002]",
        "[来源 003]",
    ]


def test_pdf_markdown_rejects_unknown_markdown_citation() -> None:
    with pytest.raises(ReportFailure, match="Markdown 引用不一致"):
        _pdf_markdown(
            "结论[[citation:citation_999]]",
            [presentation("citation_001")],
        )


def test_pdf_markdown_can_hide_display_without_dropping_registered_identity() -> None:
    visible, normalized, _trace = _pdf_markdown(
        "# 报告\n\n收入结论[[citation:citation_001]]\n",
        [presentation("citation_001")],
        include_sources=False,
    )

    assert "[来源" not in visible
    assert "[[citation:" not in visible
    assert normalized[0]["citationId"] == "citation_001"
    assert normalized[0]["alias"] == "[来源 001]"


def test_source_link_is_bound_to_subject_and_rejects_session_tokens() -> None:
    item = presentation("citation_001")
    item["links"] = [
        {
            "subjectId": "sub-cccccccccccccccc",
            "label": "正文结论",
            "url": (
                "https://reports.test/reports/v1/editor/report-1/1"
                "?subject=sub-cccccccccccccccc"
            ),
        }
    ]

    _visible, normalized, _trace = _pdf_markdown(
        "结论[[citation:citation_001]]", [item]
    )
    assert normalized[0]["links"][0]["subjectId"] == "sub-cccccccccccccccc"

    item["links"][0]["url"] += "&session=secret"
    with pytest.raises(ReportFailure, match="在线定位信息无效"):
        _pdf_markdown("结论[[citation:citation_001]]", [item])


# ---------------------------------------------------------------------------
# B8 数据来源附录：载荷校验、首次出现顺序编号与状态展示
# ---------------------------------------------------------------------------

_BASE_URL = "https://reports.test/reports/v1/editor/report-1/2"


def _trace_links(subject_id: str) -> list[dict[str, str]]:
    return [{"subjectId": subject_id, "url": f"{_BASE_URL}?subject={subject_id}"}]


def _trace_claim(claim_id: str, **overrides: object) -> dict[str, object]:
    subject_id = f"sub-{claim_id[-1] * 16}"
    entry: dict[str, object] = {
        "claimId": claim_id,
        "subjectIds": [subject_id],
        "status": "valid",
        "factValue": 3600.0,
        "unit": "万元",
        "periods": ["2025-09"],
        "formula": "sum(revenue)",
        "scope": {"院区": "全部院区"},
        "datasetIds": ["dataset-overview"],
        "links": _trace_links(subject_id),
    }
    entry.update(overrides)
    return entry


def _trace_table(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "tableId": "tbl-1",
        "subjectIds": [],
        "status": "stale",
        "datasetIds": ["dataset-overview"],
        "methods": ["环比聚合"],
        "links": [],
    }
    entry.update(overrides)
    return entry


def _trace_chart(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "chartId": "chart_001",
        "subjectIds": [],
        "status": "valid",
        "imagePath": "reports/r1/chart.png",
        "datasetIds": ["dataset-overview"],
        "methods": [],
        "transformNotes": ["按期间升序排序"],
        "unit": "元",
        "links": [],
    }
    entry.update(overrides)
    return entry


def _trace_datasets() -> dict[str, dict[str, object]]:
    return {
        "dataset-overview": {
            "filename": "收入明细.csv",
            "businessLabel": "集团医院营业收入按月汇总冻结数据长中文业务名称",
            "periodRoles": ["current", "mom"],
        }
    }


def test_trace_sources_are_numbered_by_first_appearance_and_reused() -> None:
    markdown = (
        "# 报告\n\n"
        "本期营业收入 3,600 万元[[claim:claim-1]]，口径一致[[claim:claim-1]]。\n\n"
        "![核心指标趋势](chart.png)\n\n"
        "*图表：核心指标趋势示意*\n\n"
        "次均收入 120 元[[claim:claim-2]]。\n\n"
        "[[table:tbl-1]]\n"
        "| 指标 | 本期 |\n"
        "| --- | ---: |\n"
        "| 营业收入 | 3,600 万元 |\n"
        "[[/table:tbl-1]]\n"
    )
    trace_sources = {
        "claims": [
            _trace_claim("claim-1"),
            _trace_claim("claim-2", status="stale"),
            _trace_claim("claim-unbound", status="unbound", factValue=None),
        ],
        "tables": [_trace_table()],
        "charts": [_trace_chart()],
        "datasets": _trace_datasets(),
    }

    visible, _citations, trace = _pdf_markdown(markdown, [], trace_sources=trace_sources)

    # claim 复用同一编号；图表、claim-2、表格按首次出现顺序递增；
    # 正文未出现的 claim-unbound 排在全部锚点之后。
    assert visible.count("[数据来源 001]") == 2
    assert "图表：核心指标趋势示意 [数据来源 002]" in visible
    assert "[数据来源 003]" in visible
    assert visible.count("[数据来源 004]") == 1
    assert "[[claim:" not in visible and "[[table:" not in visible
    assert [(item["kind"], item["alias"]) for item in trace["entries"]] == [
        ("claim", "[数据来源 001]"),
        ("chart", "[数据来源 002]"),
        ("claim", "[数据来源 003]"),
        ("table", "[数据来源 004]"),
        ("claim", "[数据来源 005]"),
    ]
    assert [
        item["claimId"] for item in trace["entries"] if item["kind"] == "claim"
    ] == ["claim-1", "claim-2", "claim-unbound"]


@pytest.mark.parametrize("include_sources", [True, False])
def test_chart_inline_citations_preserve_figure_and_caption_number(include_sources: bool) -> None:
    from markdown_it import MarkdownIt

    from smart_reporting.reporting.delivery.report_runtime.markdown import _prepare_figure_layout

    markdown = (
        "![收入](chart.png) [[citation:citation_001]] [[citation:citation_002]]\n\n"
        "*图表：收入快照*\n"
    )
    visible, _, _ = _pdf_markdown(
        markdown,
        [presentation("citation_001"), presentation("citation_002")],
        include_sources=include_sources,
        trace_sources={"claims": [], "tables": [], "charts": [_trace_chart()], "datasets": _trace_datasets()},
    )
    rendered = _prepare_figure_layout(MarkdownIt("commonmark").render(visible))
    assert rendered.count('<figure class="report-figure">') == 1
    assert '<p class="report-figure-image"><img' in rendered
    assert '<figcaption class="report-figure-caption">图表：收入快照' in rendered
    if include_sources:
        assert "[来源 001] [来源 002]" in rendered
        assert "图表：收入快照 [数据来源 001]" in rendered
    else:
        assert "[来源" not in rendered and "[数据来源" not in rendered


def test_figure_layout_does_not_capture_explanatory_paragraph() -> None:
    from smart_reporting.reporting.delivery.report_runtime.markdown import _prepare_figure_layout

    body = '<p><img src="chart.png" alt="收入"> 这是正文解释</p>'
    assert _prepare_figure_layout(body) == body


@pytest.mark.parametrize("counts", [{"links": True}, {"methods": -1}, {"secret": 1}, {"links": 100001}, []])
def test_trace_summary_rejects_invalid_omission_counts(counts) -> None:
    with pytest.raises(ReportFailure, match="省略数量"):
        _pdf_markdown("", [], trace_sources={
            "claims": [], "tables": [], "charts": [_trace_chart(omittedCounts=counts)],
            "datasets": _trace_datasets(),
        })


def test_trace_source_display_can_be_disabled_without_dropping_registry() -> None:
    markdown = (
        "结论[[claim:claim-1]]\n\n"
        "[[table:tbl-1]]\n| a |\n| --- |\n| 1 |\n[[/table:tbl-1]]\n"
    )
    trace_sources = {
        "claims": [_trace_claim("claim-1")],
        "tables": [_trace_table()],
        "charts": [],
        "datasets": _trace_datasets(),
    }

    visible, _citations, trace = _pdf_markdown(
        markdown, [], include_sources=False, trace_sources=trace_sources
    )

    assert "[数据来源" not in visible
    assert "[[claim:" not in visible and "[[table:" not in visible
    assert [item["alias"] for item in trace["entries"]] == [
        "[数据来源 001]",
        "[数据来源 002]",
    ]


def test_trace_source_payload_is_strictly_validated() -> None:
    good = {
        "claims": [_trace_claim("claim-1")],
        "tables": [],
        "charts": [],
        "datasets": _trace_datasets(),
    }
    # 未知字段 / 未知状态 / 非法 URL / 非法图表路径都必须拒绝。
    bad_payloads = [
        {**good, "claims": [{**_trace_claim("claim-1"), "extra": 1}]},
        {**good, "claims": [_trace_claim("claim-1", status="unknown")]},
        {
            **good,
            "claims": [
                _trace_claim(
                    "claim-1",
                    links=[{"subjectId": "s" * 16, "url": f"{_BASE_URL}?subject=other"}],
                )
            ],
        },
        {**good, "charts": [_trace_chart(imagePath="../escape.png")]},
        {**good, "charts": [_trace_chart(imagePath="")]},
    ]
    for payload in bad_payloads:
        with pytest.raises(ReportFailure):
            _pdf_markdown("结论[[claim:claim-1]]", [], trace_sources=payload)
    # 重复 claim 身份同样拒绝。
    with pytest.raises(ReportFailure):
        _pdf_markdown(
            "结论[[claim:claim-1]]",
            [],
            trace_sources={
                **good,
                "claims": [_trace_claim("claim-1"), _trace_claim("claim-1")],
            },
        )


def test_trace_source_appendix_renders_status_and_summary_fields() -> None:
    from smart_reporting.reporting.delivery.report_runtime.markdown import (
        _trace_source_appendix_html,
    )

    trace_sources = {
        "entries": [
            {
                "kind": "claim",
                "alias": "[数据来源 001]",
                "status": "stale",
                "factValue": 3600.0,
                "unit": "万元",
                "periods": ["2025-09", "2025-08"],
                "formula": "sum(revenue)",
                "scope": {"院区": "全部院区"},
                "datasetIds": ["dataset-overview"],
                "links": _trace_links("sub-" + "0" * 16),
            },
            {
                "kind": "chart",
                "alias": "[数据来源 002]",
                "status": "valid",
                "datasetIds": ["dataset-overview"],
                "methods": [],
                "transformNotes": ["按期间升序排序"],
                "links": [],
            },
        ],
        "datasets": _trace_datasets(),
    }

    html = _trace_source_appendix_html(trace_sources)

    assert "数据来源附录" in html
    assert "[数据来源 001] 正文事实" in html
    assert "[数据来源 002] 静态图表" in html
    assert "状态：待复核" in html and "状态：有效" in html
    # 事实值不在数字与单位间留空格；期间写中文日期；计算口径写中文说明。
    assert "事实值：3,600万元" in html
    assert "期间：2025年9月、2025年8月" in html
    assert "范围：院区=全部院区" in html
    assert "方法：revenue 求和" in html
    assert "方法：转换：按期间升序排序" in html
    assert "源文件：收入明细.csv" in html
    assert 'href="https://reports.test/reports/v1/editor/report-1/2?subject=' in html
    assert "未提供在线定位" in html
    assert _trace_source_appendix_html({}) == ""
    assert _trace_source_appendix_html({"entries": [], "datasets": {}}) == ""


def test_trace_source_visibility_gate_matches_export_settings() -> None:
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    runtime = ReportRuntime("/tmp/report-visibility-gate")
    entries = [{"alias": "[数据来源 001]"}, {"alias": "[数据来源 002]"}]
    render = {
        "traceSourcePresentations": {"entries": entries, "datasets": {}},
        "traceSourceAppendixPresent": True,
        "exportSettings": {"sources": True},
    }
    text = "正文 [数据来源 001]\n数据来源附录\n[数据来源 002]"
    runtime._validate_trace_source_visibility(render, text)

    with pytest.raises(ReportFailure, match="编号不完整"):
        runtime._validate_trace_source_visibility(render, "数据来源附录\n[数据来源 002]")
    with pytest.raises(ReportFailure, match="附录不完整"):
        runtime._validate_trace_source_visibility(
            render, "正文 [数据来源 001] [数据来源 002]"
        )
    with pytest.raises(ReportFailure, match="协议标记"):
        runtime._validate_trace_source_visibility(render, f"{text} [[claim:claim-1]]")

    hidden = {
        "traceSourcePresentations": {"entries": entries, "datasets": {}},
        "traceSourceAppendixPresent": False,
        "exportSettings": {"sources": False},
    }
    runtime._validate_trace_source_visibility(hidden, "只有正文")
    with pytest.raises(ReportFailure, match="关闭来源展示"):
        runtime._validate_trace_source_visibility(hidden, "[数据来源 001]")


def test_citation_appendix_shows_readable_scope_and_periods() -> None:
    from smart_reporting.reporting.delivery.report_runtime.markdown import _source_appendix_html

    def presentation(scope: str, periods: list[str]) -> dict:
        return {
            "alias": "[来源 001]", "label": "门诊收入明细", "status": "valid",
            "coverageItems": [{"label": "门诊收入表", "periods": periods}],
            "scope": scope, "method": "CSV 文件冻结快照", "summary": "12 行", "links": [],
        }

    # 期间角色代码换成中文名称，ISO 期间与区间按正文同一规则写成中文日期（含旧任务保存的数据）。
    html = _source_appendix_html([presentation("current、yoy", ["2025-01-01至2025-12-31"])])
    assert "范围：本期、同比基期" in html
    assert "门诊收入表（2025年1月1日至12月31日）" in html
    html = _source_appendix_html([presentation("院区=全部院区", ["2025-01", "2025-03"])])
    assert "范围：院区=全部院区" in html
    assert "门诊收入表（2025年1月、2025年3月）" in html


@pytest.mark.parametrize(("formula", "expected"), [
    ("sum(revenue)", "revenue 求和"),
    ("average(床位使用率) WHERE 院区='东院' AND 科室='内科'", "床位使用率 平均（筛选：院区=东院、科室=内科）"),
    ("(currentTotal-baselineTotal)/abs(baselineTotal)*100%", "变化率 =（本期合计 − 基期合计）÷ 基期合计绝对值 × 100%"),
    ("actual/budget; difference=actual-budget", "比率 = actual ÷ budget；差额 = actual − budget"),
    # 未登记的写法原样保留。
    ("自定义口径", "自定义口径"),
])
def test_trace_appendix_methods_are_written_for_readers(formula, expected):
    from smart_reporting.reporting.delivery.report_runtime.markdown import _readable_formula

    assert _readable_formula(formula) == expected


@pytest.mark.parametrize(("value", "unit", "expected"), [
    (1112354150.0, "元", "1,112,354,150元"),
    (5.033219, "%", "5.03%"),
    (2.1, "个百分点", "2.10个百分点"),
    # 非零小值不显示成 0.00。
    (0.0042, "%", "0.0042%"),
])
def test_trace_appendix_fact_values_use_display_precision(value, unit, expected):
    from smart_reporting.reporting.delivery.report_runtime.markdown import _readable_fact_value

    assert _readable_fact_value(value, unit) == expected
