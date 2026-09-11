from pathlib import PurePosixPath

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.workflow.checkpoint import FileIdentity, SectionClaimSubmission
from smart_reporting.reporting.workflow.runtime.phase_models import (
    AnalysisReworkDecision,
    ChartDraft,
    RenderSectionDecision,
    SectionBlockContent,
    SectionDecisionAdapter,
    SectionDecisionOutput,
    SectionPlanOutput,
    VisualizationPlanDraft,
)


def _chart(path: str = "report/charts/chart-001.png") -> ChartDraft:
    return ChartDraft(
        chartId="chart_001",
        sourcePath=path,
        title="收入趋势",
        altText="收入按月趋势",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2026-08",
        sourceDatasetId="dataset_001",
        aggregationGrain="month",
    )


def test_visualization_plan_accepts_bound_chart_metadata_and_warnings() -> None:
    assert VisualizationPlanDraft.__name__ == "VisualizationPlanDraft"
    plan = VisualizationPlanDraft(charts=(_chart(),), warnings=("数据仅供参考",))

    assert plan.charts[0].model_dump(mode="json", by_alias=True) == {
        "chartId": "chart_001",
        "sourcePath": "report/charts/chart-001.png",
        "title": "收入趋势",
        "altText": "收入按月趋势",
        "citationIds": ["citation_001"],
        "metricCodes": ["revenue"],
        "currentPeriod": "2026-08",
        "comparisonPeriod": None,
        "comparisonType": "none",
        "sourceDatasetId": "dataset_001",
        "aggregationGrain": "month",
        "comparability": "strict",
    }
    assert plan.warnings == ("数据仅供参考",)


def test_visualization_plan_accepts_zero_charts() -> None:
    assert VisualizationPlanDraft(charts=()).charts == ()


def test_visualization_plan_requires_charts_field() -> None:
    with pytest.raises(ValidationError):
        VisualizationPlanDraft()


@pytest.mark.parametrize(
    "extra",
    [
        {"scriptPath": ""},
        {"pythonSource": ""},
        {"unexpected": ""},
    ],
)
def test_visualization_plan_rejects_source_and_unknown_fields(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        VisualizationPlanDraft(charts=(_chart(),), **extra)


def test_visualization_plan_rejects_duplicate_chart_identity() -> None:
    with pytest.raises(ValidationError):
        VisualizationPlanDraft(charts=(_chart(), _chart()))


@pytest.mark.parametrize(
    "path", ["/tmp/chart.png", "../chart.png", "charts\\chart.png", "chart.svg"]
)
def test_chart_draft_rejects_unsafe_source_path(path: str) -> None:
    with pytest.raises(ValidationError):
        _chart(path)


def test_section_decision_is_a_render_or_rework_union() -> None:
    rendered = RenderSectionDecision(
        sectionCode="section_001",
        blocks=(
            ReportDraftBlock(
                blockId="block_001",
                markdown="收入保持增长。",
                citationIds=("citation_001",),
                claimIds=("claim_001",),
            ),
        ),
        claims=(
            SectionClaimSubmission(
                claimId="claim_001",
                metricCode="revenue",
                value=100,
                managementQuestionRef="analysis_001",
                citationIds=("citation_001",),
            ),
        ),
    )
    parsed = SectionDecisionAdapter.validate_python(rendered.model_dump(mode="json", by_alias=True))
    assert isinstance(parsed, RenderSectionDecision)
    output = SectionDecisionOutput.model_validate_json(rendered.model_dump_json(by_alias=True))
    assert isinstance(output.root, RenderSectionDecision)

    with pytest.raises(ValidationError):
        AnalysisReworkDecision(
            sectionCode="section_001",
            analysisIds=(),
            reason="缺少证据",
            missingEvidence=("dataset_001",),
        )


def test_section_decision_normalizes_single_render_wrapper() -> None:
    output = SectionDecisionOutput.model_validate(
        {
            "render": {
                "sectionCode": "section_001",
                "blocks": [
                    {
                        "blockId": "block_001",
                        "markdown": "收入保持增长。",
                        "citationIds": ["citation_001"],
                        "claimIds": ["claim_001"],
                    }
                ],
                "claims": [
                    {
                        "claimId": "claim_001",
                        "metricCode": "revenue",
                        "value": 100,
                        "managementQuestionRef": "analysis_001",
                        "citationIds": ["citation_001"],
                    }
                ],
            }
        }
    )

    assert isinstance(output.root, RenderSectionDecision)
    assert output.root.kind == "render"


def test_section_decision_normalizes_numeric_comparison_display_value() -> None:
    output = SectionDecisionOutput.model_validate(
        {
            "kind": "render",
            "sectionCode": "section_001",
            "blocks": [
                {
                    "blockId": "block_001",
                    "markdown": "收入下降。",
                    "citationIds": ["citation_001"],
                    "claimIds": ["claim_001"],
                }
            ],
            "claims": [
                {
                    "claimId": "claim_001",
                    "metricCode": "revenue",
                    "value": 100,
                    "comparison": -40000000,
                    "managementQuestionRef": "analysis_001",
                    "citationIds": ["citation_001"],
                }
            ],
        }
    )

    assert output.root.claims[0].comparison == "-40000000"


@pytest.mark.parametrize("wrapped", [False, True])
def test_section_plan_decodes_object_strings_inside_render(wrapped: bool) -> None:
    render = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": ['{"blockId":"block_001","objective":"说明收入趋势。","claimIds":["claim_001"]}'],
        "claims": [
            '{"claimId":"claim_001","metricCode":"revenue","value":100,'
            '"managementQuestionRef":"analysis_001",'
            '"citationIds":["citation_001"]}'
        ],
    }
    value = (
        {"render": {key: item for key, item in render.items() if key != "kind"}}
        if wrapped
        else render
    )

    output = SectionPlanOutput.model_validate(value)

    assert output.root.kind == "render"
    assert output.root.blocks[0].block_id == "block_001"
    assert output.root.claims[0].claim_id == "claim_001"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blocks", "收入趋势正文。"),
        ("blocks", '"收入趋势正文。"'),
        ("blocks", '[{"blockId":"block_001"}]'),
        ("claims", "not-json"),
        ("claims", "null"),
        ("claims", '[{"claimId":"claim_001"}]'),
    ],
)
def test_section_plan_keeps_non_object_strings_for_strict_validation(
    field: str, value: str
) -> None:
    payload = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [
            {
                "blockId": "block_001",
                "objective": "说明收入趋势。",
                "claimIds": ["claim_001"],
            }
        ],
        "claims": [
            {
                "claimId": "claim_001",
                "metricCode": "revenue",
                "value": 100,
                "managementQuestionRef": "analysis_001",
                "citationIds": ["citation_001"],
            }
        ],
    }
    payload[field] = [value]

    with pytest.raises(ValidationError) as raised:
        SectionPlanOutput.model_validate(payload)

    assert raised.value.errors(include_url=False)[0]["input"] == value


def test_section_plan_does_not_infer_missing_claims() -> None:
    with pytest.raises(ValidationError) as raised:
        SectionPlanOutput.model_validate(
            {
                "render": {
                    "sectionCode": "section_001",
                    "blocks": [
                        '{"blockId":"block_001","objective":"说明收入趋势。",'
                        '"claimIds":["claim_001"]}'
                    ],
                }
            }
        )

    assert raised.value.errors(include_url=False)[0]["loc"] == ("render", "claims")


def test_section_block_content_rejects_disallowed_heading_level() -> None:
    with pytest.raises(ValidationError, match="report_draft_heading_level_invalid"):
        SectionBlockContent(markdown="## 非法章节标题\n\n正文")


def test_section_block_content_rejects_heading_with_301_visible_characters() -> None:
    with pytest.raises(ValidationError, match="report_draft_heading_title_too_long") as raised:
        SectionBlockContent(markdown=f"### {'甲' * 301}\n\n正文")

    assert raised.value.errors(include_url=False)[0]["loc"] == ("markdown",)


def test_section_block_content_splits_runon_heading_into_title_and_body() -> None:
    body = (
        "本季度收入预算执行率达到95.2%，门诊收入完成预算的98%，"
        "住院收入完成预算的93%，需持续关注后续走势。" * 6
    )

    content = SectionBlockContent(markdown=f"### 收入预算执行情况分析：{body}")

    assert content.markdown == f"### 收入预算执行情况分析\n\n{body}"


def test_section_block_content_rejects_runon_heading_with_inline_markdown() -> None:
    body = "本季度收入增长。" * 50

    with pytest.raises(ValidationError, match="report_draft_heading_title_too_long"):
        SectionBlockContent(markdown=f"### **收入分析：{body}**")


def test_section_block_content_splits_single_line_runon_document() -> None:
    body = (
        "门诊收入增长且结构占比提升，住院收入下降主要受DRG支付改革影响，"
        "需持续关注成本控制压力与月度执行走势。" * 6
    )
    content = SectionBlockContent(markdown=f"### 收入总览。{body}")

    assert content.markdown == f"### 收入总览\n\n{body}"


def test_section_block_content_keeps_body_lines_after_runon_heading_split() -> None:
    content = SectionBlockContent(markdown=f"### 收入预算执行分析。{'甲' * 350}。\n\n正文段落。")

    assert content.markdown == f"### 收入预算执行分析\n\n{'甲' * 350}。\n\n正文段落。"


def test_section_block_content_normalizes_runon_subordinate_heading() -> None:
    content = SectionBlockContent(markdown=f"##### 明细说明：{'甲' * 350}。")

    assert content.markdown == f"#### 明细说明\n\n{'甲' * 350}。"


def test_section_block_content_keeps_short_heading_with_punctuation() -> None:
    content = SectionBlockContent(markdown="### 收入分析：门诊与住院\n\n正文。")

    assert content.markdown == "### 收入分析：门诊与住院\n\n正文。"


def test_section_block_content_rejects_runon_heading_without_short_prefix() -> None:
    # 首个句末标点之前的可见文本仍超上限：不猜测拆分点，失败关闭。
    with pytest.raises(ValidationError, match="report_draft_heading_title_too_long"):
        SectionBlockContent(markdown=f"### {'甲' * 301}。正文内容。")


def test_section_block_content_heading_feedback_reports_line_and_length() -> None:
    with pytest.raises(ValidationError) as raised:
        SectionBlockContent(markdown=f"### 正常标题\n\n正文。\n\n### {'甲' * 301}\n\n正文。")

    message = str(raised.value)
    assert "report_draft_heading_title_too_long" in message
    assert "第 5 行" in message
    assert "301 个字符" in message
    assert "上限 300" in message
    assert "甲" in message
    assert "短标题" in message


def test_section_block_content_heading_feedback_truncates_preview() -> None:
    with pytest.raises(ValidationError) as raised:
        SectionBlockContent(markdown=f"### {'乙' * 400}")

    message = str(raised.value)
    assert f"{'乙' * 50}…" in message
    assert "乙" * 51 not in message


def test_section_block_content_allows_h4_parented_by_previous_block() -> None:
    content = SectionBlockContent(markdown="#### 同比变化\n\n正文")

    assert content.markdown == "#### 同比变化\n\n正文"


def test_section_block_content_normalizes_h5_h6_as_business_style() -> None:
    content = SectionBlockContent(
        markdown=(
            "### 收入结构\n\n"
            "##### 大额项目\n\n正文\n\n"
            "###### 补充说明\n\n补充\n\n"
            "```markdown\n##### 代码示例\n```"
        )
    )

    assert content.markdown == (
        "### 收入结构\n\n"
        "#### 大额项目\n\n正文\n\n"
        "#### 补充说明\n\n补充\n\n"
        "```markdown\n##### 代码示例\n```"
    )


def test_section_block_content_removes_model_protocol_syntax() -> None:
    content = SectionBlockContent(
        markdown=(
            "### 月度同比趋势\n\n"
            "收入保持增长[[citation:citation_001]]。"
            '![趋势图](chart-001.png "趋势")\n'
            "<!-- repair-warning: retry -->"
        )
    )

    assert content.markdown == "### 月度同比趋势\n\n收入保持增长。趋势图"


def test_section_block_content_preserves_text_after_model_image() -> None:
    content = SectionBlockContent(
        markdown="### 月度同比趋势\n\n![趋势图](chart-001.png) 后续分析 (必须保留)"
    )

    assert content.markdown == "### 月度同比趋势\n\n趋势图 后续分析 (必须保留)"


def test_section_block_content_does_not_clean_protocol_syntax_inside_inline_code() -> None:
    with pytest.raises(ValidationError, match="report_draft_protocol_injection"):
        SectionBlockContent(markdown="### 语法示例\n\n`![趋势图](chart-001.png)`")


def test_section_block_content_keeps_malformed_protocol_marker_strict() -> None:
    with pytest.raises(ValidationError, match="report_draft_protocol_injection"):
        SectionBlockContent(markdown="### 月度同比趋势\n\n[[citation:未闭合")


def test_file_identity_keeps_existing_safe_path_contract() -> None:
    identity = FileIdentity(path="report/evidence.json", size=1, sha256="a" * 64)
    assert PurePosixPath(identity.path).is_absolute() is False
