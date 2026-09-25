from smart_reporting.reporting.workflow.benchmark_variants import (
    BenchmarkProjection,
    BenchmarkVariant,
)
from smart_reporting.reporting.workflow.runtime.analysis import (
    visualization_coding_facts,
    visualization_coding_plan,
    visualization_read_paths,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    VisualizationPlanDraft,
)


def test_visualization_authorizes_supplemental_sources_without_unrelated_evidence():
    fact = {"path": "facts/item.json", "sha256": "a" * 64, "size": 10}
    supplement = {"path": "evidence/item.json", "sha256": "b" * 64, "size": 20}
    projection = [
        {
            "factFile": fact,
            "supplementalEvidenceSources": [{"sourceFile": supplement}, {"sourceFile": fact}],
            "evidenceFiles": [{"path": "unprojected.json"}],
        }
    ]
    assert visualization_read_paths(projection) == ("evidence/item.json", "facts/item.json")


def test_visualization_coding_facts_drop_planning_narrative_and_keep_descriptors():
    projection = [{
        "analysisId": "analysis_001",
        "factFile": {"path": "facts/item.json", "sha256": "a" * 64, "size": 10},
        "dataPathBase": "fileRoot",
        "summary": "面向章节撰写的长篇业务总结",
        "metrics": [{"metricIndex": 0, "unit": "元", "dataPaths": {"metric": "metrics[0]"}}],
        "dataDescriptors": [
            {"dataPath": "metrics[0]", "fields": ["field", "total"]}
        ],
        "derivedMetrics": [],
        "comparisons": [{"comparisonIndex": 0, "dataPath": "comparisons[0]"}],
        "evidenceFiles": [{"path": "evidence/item.json"}],
        "citationIds": ["citation_001"],
        "supplementalEvidenceSources": [{
            "sourceFile": {"path": "evidence/item.json", "sha256": "b" * 64, "size": 20},
            "findings": [{
                "findingIndex": 0,
                "rowEncoding": "columns_rows",
                "nullableFields": ["同比"],
            }],
        }],
    }]

    coding_facts = visualization_coding_facts(projection)

    assert coding_facts == [{
        "analysisId": "analysis_001",
        "factFile": projection[0]["factFile"],
        "dataPathBase": "fileRoot",
        "metrics": projection[0]["metrics"],
        "dataDescriptors": projection[0]["dataDescriptors"],
        "comparisons": projection[0]["comparisons"],
        "supplementalEvidenceSources": projection[0]["supplementalEvidenceSources"],
    }]
    assert projection[0]["summary"] == "面向章节撰写的长篇业务总结"


def test_visualization_coding_facts_keep_only_plan_bound_descriptors():
    fact_file = {"path": "facts/analysis.json", "sha256": "a" * 64, "size": 10}
    supplement_file = {
        "path": "evidence/analysis.json",
        "sha256": "b" * 64,
        "size": 20,
    }
    facts = [
        {
            "analysisId": "analysis_001",
            "factFile": fact_file,
            "dataPathBase": "fileRoot",
            "metrics": [
                {"metricIndex": 0, "dataPath": "metrics[0]"},
                {"metricIndex": 1, "dataPath": "metrics[1]"},
            ],
            "dataDescriptors": [
                {"dataPath": "metrics[0]", "fields": ["name", "value"]},
                {"dataPath": "metrics[1]", "fields": ["name", "value"]},
            ],
            "supplementalEvidenceSources": [
                {
                    "sourceFile": supplement_file,
                    "dataPathBase": "fileRoot",
                    "findings": [
                        {"findingIndex": 0, "dataPath": "findings[0]"},
                        {"findingIndex": 1, "dataPath": "findings[1]"},
                    ],
                    "dataDescriptors": [
                        {"dataPath": "findings[0]", "fields": ["name", "rows"]},
                        {"dataPath": "findings[1]", "fields": ["name", "rows"]},
                    ],
                }
            ],
        },
        {
            "analysisId": "analysis_002",
            "factFile": {"path": "facts/unbound.json", "sha256": "c" * 64, "size": 5},
            "dataDescriptors": [
                {"dataPath": "metrics[0]", "fields": ["name", "value"]}
            ],
        },
    ]
    plan = VisualizationPlanDraft(
        charts=(
            ChartDraft(
                chartId="chart_001",
                sourcePath="charts/one.png",
                title="收入指标",
                altText="收入指标图",
                citationIds=("citation_001",),
                metricCodes=("revenue",),
                currentPeriod="2025",
                sourceDatasetId="dataset_001",
                aggregationGrain="year",
                visualForm="柱状图",
                dataBindings=(
                    {
                        "analysisId": "analysis_001",
                        "factPath": fact_file["path"],
                        "dataPath": "metrics[0]",
                        "fields": ["name", "value"],
                        "role": "收入",
                    },
                    {
                        "analysisId": "analysis_001",
                        "factPath": supplement_file["path"],
                        "dataPath": "findings[1]",
                        "fields": ["name", "rows"],
                        "role": "明细",
                    },
                ),
            ),
        )
    )

    coding_facts = visualization_coding_facts(facts, plan=plan)

    assert len(coding_facts) == 1
    assert coding_facts[0]["dataDescriptors"] == [
        {"dataPath": "metrics[0]", "fields": ["name", "value"]}
    ]
    assert coding_facts[0]["metrics"] == [
        {"metricIndex": 0, "dataPath": "metrics[0]"}
    ]
    assert coding_facts[0]["supplementalEvidenceSources"][0]["dataDescriptors"] == [
        {"dataPath": "findings[1]", "fields": ["name", "rows"]}
    ]
    assert coding_facts[0]["supplementalEvidenceSources"][0]["findings"] == [
        {"findingIndex": 1, "dataPath": "findings[1]"}
    ]


def test_visualization_coding_facts_keep_full_item_for_unresolved_binding():
    facts = [
        {
            "analysisId": "analysis_001",
            "factFile": {"path": "facts/analysis.json", "sha256": "a" * 64, "size": 10},
            "dataDescriptors": [{"dataPath": "metrics[0]", "fields": ["name", "value"]}],
        },
        {
            "analysisId": "analysis_002",
            "factFile": {"path": "facts/other.json", "sha256": "c" * 64, "size": 5},
            "dataDescriptors": [{"dataPath": "metrics[0]", "fields": ["name", "value"]}],
        },
    ]
    plan = VisualizationPlanDraft(
        charts=(
            ChartDraft(
                chartId="chart_001",
                sourcePath="charts/one.png",
                title="收入指标",
                altText="收入指标图",
                citationIds=("citation_001",),
                metricCodes=("revenue",),
                currentPeriod="2025",
                sourceDatasetId="dataset_001",
                aggregationGrain="year",
                visualForm="柱状图",
                dataBindings=(
                    {
                        # 错配绑定按软告警继续执行：factPath 不在签发目录中。
                        "analysisId": "analysis_001",
                        "factPath": "evidence/unsigned.json",
                        "dataPath": "findings[0].rows",
                        "fields": ["name", "value"],
                        "role": "收入",
                    },
                ),
            ),
        )
    )

    coding_facts = visualization_coding_facts(facts, plan=plan)

    # 无法定位的绑定保留该分析项完整描述，未绑定的分析项仍被裁掉。
    assert coding_facts == [facts[0]]
    assert visualization_read_paths(coding_facts) == ("facts/analysis.json",)


def test_visualization_legacy_projection_hides_r7_plan_fields() -> None:
    plan = VisualizationPlanDraft(
        charts=(
            ChartDraft(
                chartId="chart_001",
                sourcePath="report/chart.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
                metricCodes=("revenue",),
                currentPeriod="2026-08",
                sourceDatasetId="dataset_001",
                aggregationGrain="month",
                visualForm="折线图",
                dataBindings=(
                    {
                        "analysisId": "analysis_001",
                        "factPath": "facts/analysis.json",
                        "dataPath": "metrics[0]",
                        "fields": ["period", "value"],
                        "role": "趋势",
                    },
                ),
            ),
        )
    )

    projected = visualization_coding_plan(
        plan,
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY),
    )

    assert "visualForm" not in projected["charts"][0]
    assert "dataBindings" not in projected["charts"][0]


def test_section_scoped_chart_ids_prevent_cross_section_collisions() -> None:
    from smart_reporting.reporting.workflow.runtime.analysis import _section_scoped_chart_ids

    def plan(chart_id: str) -> VisualizationPlanDraft:
        return VisualizationPlanDraft(
            charts=(
                ChartDraft(
                    chartId=chart_id,
                    sourcePath="charts/one.png",
                    title="收入指标",
                    altText="收入指标图",
                    citationIds=("citation_001",),
                    metricCodes=("revenue",),
                    currentPeriod="2025",
                    sourceDatasetId="dataset_001",
                    aggregationGrain="year",
                    visualForm="柱状图",
                    dataBindings=(
                        {
                            "analysisId": "analysis_001",
                            "factPath": "facts/analysis.json",
                            "dataPath": "metrics[0]",
                            "fields": ["name", "value"],
                            "role": "收入",
                        },
                    ),
                ),
            )
        )

    first = _section_scoped_chart_ids(plan("chart_001"), "section_001")
    second = _section_scoped_chart_ids(plan("chart_001"), "section_002")

    # durable 状态要求 chartId 跨章节唯一；各章 planner 常各自生成 chart_001。
    assert first.charts[0].chart_id == "section_001__chart_001"
    assert second.charts[0].chart_id == "section_002__chart_001"
    assert _section_scoped_chart_ids(first, "section_001") == first
    long_ids = {
        _section_scoped_chart_ids(plan("x" * 127 + suffix), "section_001").charts[0].chart_id
        for suffix in "ab"
    }
    assert len(long_ids) == 2
    assert all(len(item) <= 128 for item in long_ids)
