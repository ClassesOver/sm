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
    VisualizationScriptDraft,
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


def test_visualization_script_draft_accepts_bound_chart_paths() -> None:
    draft = VisualizationScriptDraft(
        scriptPath="report/charts/charts.py",
        pythonSource=(
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2], [3, 4])\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
        charts=(_chart(),),
    )
    assert draft.charts[0].chart_id == "chart_001"


def test_visualization_script_draft_reports_python_syntax_location() -> None:
    with pytest.raises(ValidationError) as caught:
        VisualizationScriptDraft(
            scriptPath="report/charts/charts.py",
            pythonSource="if True print('broken')",
            charts=(_chart(),),
        )

    issue = caught.value.errors(include_url=False, include_input=False)[0]
    assert issue["loc"] == ("pythonSource",)
    assert (
        issue["msg"]
        == "Value error, pythonSource Python 语法错误：invalid syntax（第 1 行，第 9 列）"
    )


@pytest.mark.parametrize(
    "python_source",
    [
        "submit_visualization_charts([])",
        "print(__file__)",
        "comparison_period = null",
    ],
)
def test_visualization_script_draft_rejects_workflow_or_runtime_placeholders(
    python_source: str,
) -> None:
    with pytest.raises(ValidationError):
        VisualizationScriptDraft(
            scriptPath="report/charts/charts.py",
            pythonSource=python_source,
            charts=(_chart(),),
        )


@pytest.mark.parametrize(
    "python_source",
    [
        "import plotly.express as px\npx.bar(x=[1], y=[2])",
        (
            "import matplotlib\n"
            "import matplotlib.pyplot as plt\n"
            "matplotlib.use('Agg')\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "figure = plt.figure()\n"
            "figure.write_image('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2], [3, 4])\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "obj.savefig('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "def configure_backend():\n"
            "    matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "import importlib\n"
            "importlib.import_module('seaborn')\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "__import__('plotly')\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
        (
            "import matplotlib\n"
            "if True:\n"
            "    import matplotlib.pyplot as early_plt\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.savefig('report/charts/chart-001.png')\n"
        ),
    ],
)
def test_visualization_script_draft_enforces_matplotlib_rendering_contract(
    python_source: str,
) -> None:
    with pytest.raises(ValidationError):
        VisualizationScriptDraft(
            scriptPath="report/charts/charts.py",
            pythonSource=python_source,
            charts=(_chart(),),
        )


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


def test_section_block_content_rejects_disallowed_heading_level() -> None:
    with pytest.raises(ValidationError, match="report_draft_heading_level_invalid"):
        SectionBlockContent(markdown="## 非法章节标题\n\n正文")


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
