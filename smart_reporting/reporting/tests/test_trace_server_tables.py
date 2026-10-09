"""B2 服务端表格正文装配集成测试（计划 B2-3：表格进入草稿渲染协议）。"""

from __future__ import annotations

import json

import pytest

from smart_reporting.reporting.delivery.draft_v1 import (
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    ReportServerTable,
    assemble_report_markdown,
)
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.table_builder import build_analysis_table

from .test_deterministic_analysis import analysis, context

SHA = "b" * 64
FACT_RESOURCE = "trf-" + "0" * 20

CSV = b"month,department,revenue\n2025-09,A,1200\n2025-09,B,2400\n"


def _bundle():
    return build_deterministic_analysis_bundle(
        analysis(fields=("revenue",)),
        (
            (
                "current",
                CSV,
                context(
                    "current",
                    fields=("month", "department", "revenue"),
                    semantics=(
                        {
                            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
                            "aggregation": "sum",
                            "additiveAcross": ["month", "department"],
                            "exclusiveScope": {},
                            "unit": "元",
                        },
                    ),
                ),
                ("current",),
            ),
        ),
        profile_metrics=(
            {
                "code": "income_total",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
            },
        ),
        profile_hash="c" * 64,
    )


def _outline_sections():
    return (
        ReportSectionDefinition(
            code="section_002",
            sectionNumber="1",
            title="收入分析",
            protocolMarker=True,
            analysisIds=("analysis_001",),
        ),
    )


def _draft():
    return ReportDraft(
        sections=(
            ReportDraftSection(
                sectionCode="section_002",
                blocks=(
                    ReportDraftBlock(
                        blockId="b1",
                        markdown="收入保持增长。",
                        citationIds=(),
                    ),
                ),
            ),
        )
    )


# ---------------------------------------------------------------------------
# build_analysis_table 规则
# ---------------------------------------------------------------------------


def test_build_analysis_table_generates_period_rows_from_bundle() -> None:
    bundle = _bundle()
    built = build_analysis_table(bundle, fact_file_resource_id=FACT_RESOURCE)
    assert built is not None
    trace, markdown = built
    assert trace.table_id == "table-analysis_001"
    # 行 = bundle 指标 periodValues 的期间（2025-09）。
    assert trace.row_keys == ("period:2025-09",)
    assert trace.column_keys == ("收入（元）",)
    assert f"[[table:table-analysis_001]]" in markdown
    assert "| 2025年9月 | 3,600 |" in markdown


def test_build_analysis_table_binds_unique_current_fact_with_same_code_yoy() -> None:
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import PeriodValue

    bundle = _bundle()
    current = bundle.metrics[0].model_copy(update={"fact_id": "fact-" + "a" * 16})
    baseline = current.model_copy(update={
        "fact_id": "fact-" + "b" * 16, "dataset_id": "previous", "period_roles": ("yoy",),
        "period_values": (PeriodValue(period="2024-09", value=3000),),
    })
    bundle = bundle.model_copy(update={"metrics": (baseline, current)})
    built = build_analysis_table(bundle, fact_file_resource_id=FACT_RESOURCE)
    assert built is not None
    trace, markdown = built
    assert trace.row_keys == ("period:2025-09",)
    assert trace.cells[0].fact_refs[0].json_pointer == "/metrics/1"
    assert trace.cells[0].fact_refs[0].fact_key == current.fact_id
    assert "3,600" in markdown and "2024-09" not in markdown
    ambiguous = bundle.model_copy(update={"metrics": (current, current)})
    assert build_analysis_table(ambiguous, fact_file_resource_id=FACT_RESOURCE) is None


def test_build_analysis_table_uses_frozen_total_without_periods() -> None:
    bundle = _bundle()
    # 构造无分期间值的 bundle：清空 periodValues。
    stripped = bundle.model_copy(
        update={
            "metrics": tuple(
                fact.model_copy(update={"period_values": ()})
                for fact in bundle.metrics
            )
        }
    )
    trace, markdown = build_analysis_table(stripped, fact_file_resource_id=FACT_RESOURCE)
    assert trace.row_keys == ("total",)
    assert "| 合计 | 3,600 |" in markdown
    assert trace.cells[0].fact_refs[0].json_pointer == "/metrics/0"


def test_build_analysis_table_skips_bundle_without_metric_codes() -> None:
    document = json.loads(
        json.dumps(_bundle().model_dump(mode="json", by_alias=True))
    )
    for metric in document["metrics"]:
        metric["metricCodes"] = []
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )

    stripped = DeterministicAnalysisBundle.model_validate(document)
    assert build_analysis_table(
        stripped, fact_file_resource_id=FACT_RESOURCE
    ) is None


# ---------------------------------------------------------------------------
# 装配器：服务端表格渲染
# ---------------------------------------------------------------------------


def _server_table(markdown: str, section_code: str = "section_002"):
    return ReportServerTable(sectionCode=section_code, markdown=markdown)


def test_assembler_appends_server_table_to_section() -> None:
    _trace, table_markdown = build_analysis_table(
        _bundle(), fact_file_resource_id=FACT_RESOURCE
    )
    rendered = assemble_report_markdown(
        _draft(),
        expected_title="运营报告",
        markdown_path="报表/智能分析/run-1/revision-1/report.md",
        sections=_outline_sections(),
        citation_ids=(),
        server_tables=(_server_table(table_markdown),),
    )
    # 协议块进入最终 Markdown，且位于章节标题之后。
    assert "[[table:table-analysis_001]]" in rendered.markdown
    assert rendered.markdown.index("## 1. 收入分析") < rendered.markdown.index(
        "[[table:table-analysis_001]]"
    )
    assert "3,600" in rendered.markdown


def test_assembler_rejects_unknown_section_and_duplicate_table_id() -> None:
    _trace, table_markdown = build_analysis_table(
        _bundle(), fact_file_resource_id=FACT_RESOURCE
    )
    with pytest.raises(ReportingError, match="未注册章节"):
        assemble_report_markdown(
            _draft(),
            expected_title="运营报告",
            markdown_path="报表/智能分析/run-1/revision-1/report.md",
            sections=_outline_sections(),
            citation_ids=(),
            server_tables=(
                _server_table(table_markdown, section_code="section_999"),
            ),
        )
    with pytest.raises(ReportingError, match="tableId 重复"):
        assemble_report_markdown(
            _draft(),
            expected_title="运营报告",
            markdown_path="报表/智能分析/run-1/revision-1/report.md",
            sections=_outline_sections(),
            citation_ids=(),
            server_tables=(
                _server_table(table_markdown),
                _server_table(table_markdown),
            ),
        )


def test_server_table_contract_rejects_extra_markers_and_images() -> None:
    _trace, table_markdown = build_analysis_table(
        _bundle(), fact_file_resource_id=FACT_RESOURCE
    )
    with pytest.raises(ValueError, match="协议标记"):
        ReportServerTable(
            sectionCode="section_002",
            markdown=table_markdown + "\n[[citation:citation_000]]",
        )
    with pytest.raises(ValueError, match="图片语法"):
        ReportServerTable(
            sectionCode="section_002",
            markdown=table_markdown + "\n![图](chart-001.png)",
        )
    with pytest.raises(ValueError, match="成对"):
        ReportServerTable(
            sectionCode="section_002",
            markdown=table_markdown.replace("[[/table:table-analysis_001]]", ""),
        )


def test_model_body_still_rejected_for_table_marker() -> None:
    """模型提交路径保持不变：正文含 table 协议标记仍被拒绝。"""

    from smart_reporting.reporting.delivery.draft_v1 import validate_report_body_markdown
    from smart_reporting.reporting.models import ReportingError

    with pytest.raises(ReportingError, match="协议标记"):
        validate_report_body_markdown("正文\n[[table:x]]\n| a | b |\n[[/table:x]]")


# ---------------------------------------------------------------------------
# finalize 集成：_build_server_tables（bundle 读取 → 章节分配）
# ---------------------------------------------------------------------------


class _Harness:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self._scope_value = {"threadId": "thread-1"}

    def _scope(self, _run_context):
        return self._scope_value

    def _state(self, _run_context):
        return {}

    def _profile(self, _run_context):
        # 与生产一致：状态中没有有效 Profile 时报错，表格仍照常生成。
        from smart_reporting.reporting.models import ReportingError

        raise ReportingError("report_profile_state_invalid", "有效 Profile 状态无效。")

    async def _read_identity_bytes(self, thread_id, identity, *, max_bytes):
        return self._files[identity.path]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_finalize_build_server_tables_assigns_to_first_section() -> None:
    import hashlib
    from types import SimpleNamespace

    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

    bundle_bytes = json.dumps(
        _bundle().model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    fact_path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    identity = FileIdentity(
        path=fact_path,
        size=len(bundle_bytes),
        sha256=hashlib.sha256(bundle_bytes).hexdigest(),
    )
    checkpoint = SimpleNamespace(deterministic_fact_files={"analysis_001": identity})
    outline = SimpleNamespace(
        sections=(SimpleNamespace(code="section_002", analysis_ids=("analysis_001",)),)
    )
    harness = _Harness({fact_path: bundle_bytes})
    tables, traces, fact_directory, fact_values = await RuntimeSectionsMixin._build_server_tables(
        harness, SimpleNamespace(), checkpoint=checkpoint, outline=outline
    )
    assert len(tables) == len(traces) == 1
    assert tables[0].section_code == "section_002"
    assert traces[0].table_id == "table-analysis_001"
    assert traces[0].cells[0].fact_refs[0].file_resource_id == derive_resource_id(fact_path)
    # B6：factId 目录随表构建产出，供 subject 绑定复用。
    assert fact_directory, "factId 目录应包含 bundle 内的事实定位"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_finalize_skips_table_when_analysis_unassigned() -> None:
    import hashlib
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

    fact_path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    bundle_bytes = json.dumps(
        _bundle().model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    identity = FileIdentity(
        path=fact_path,
        size=len(bundle_bytes),
        sha256=hashlib.sha256(bundle_bytes).hexdigest(),
    )
    checkpoint = SimpleNamespace(deterministic_fact_files={"analysis_001": identity})
    outline = SimpleNamespace(sections=())  # 无章节引用该 analysis
    # B6 起 factId 目录无条件构建（读 bundle），但表格仍只生成给被引用的分析。
    harness = _Harness({fact_path: bundle_bytes})
    tables, traces, fact_directory, fact_values = await RuntimeSectionsMixin._build_server_tables(
        harness, SimpleNamespace(), checkpoint=checkpoint, outline=outline
    )
    assert tables == () and traces == ()
    assert fact_directory, "目录仍应产出（subject 绑定不依赖章节引用）"


def test_comparison_table_uses_aligned_totals_and_readable_labels() -> None:
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import DeterministicComparison

    bundle = _bundle()
    comparison = DeterministicComparison(
        factId='fact-' + 'c' * 16, comparisonType='yoy', field='revenue',
        fieldRef=bundle.metrics[0].field_ref,
        currentDatasetId='current', baselineDatasetId='baseline',
        currentDatasetSha256=SHA, baselineDatasetSha256=SHA,
        currentTotal=3600, baselineTotal=3000, change=600, changeRate=20,
        formula='(currentTotal-baselineTotal)/abs(baselineTotal)*100%', unit='元',
    )
    bundle = bundle.model_copy(update={'analysis_name': '收入同比分析', 'comparisons': (comparison,)})
    trace, markdown = build_analysis_table(bundle, fact_file_resource_id=FACT_RESOURCE)
    assert trace.column_keys == ('数值',)
    assert len(trace.cells) == 4
    assert '本期收入 | 3,600元' in markdown
    assert '同期收入 | 3,000元' in markdown
    assert '收入变化额 | 600元' in markdown
    assert '同比增幅 | 20%' in markdown
    assert 'income_total' not in markdown and '服务端冻结' not in markdown
    assert trace.cells[1].row_key == 'comparison:0:baselineTotal'
    assert all(cell.fact_refs[0].fact_kind == 'comparison' for cell in trace.cells)


def test_multiple_comparisons_keep_unique_rows_and_source_identity() -> None:
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import DeterministicComparison

    bundle = _bundle()
    fact = DeterministicComparison(
        factId='fact-' + 'c' * 16, comparisonType='yoy', field='revenue', fieldRef=bundle.metrics[0].field_ref,
        currentDatasetId='current', baselineDatasetId='baseline', currentDatasetSha256=SHA, baselineDatasetSha256=SHA,
        currentTotal=3600, baselineTotal=3000, change=600, changeRate=20,
        formula='(currentTotal-baselineTotal)/abs(baselineTotal)*100%', unit='元',
    )
    other = fact.model_copy(update={'fact_id': 'fact-' + 'd' * 16, 'current_dataset_id': 'other'})
    trace, markdown = build_analysis_table(bundle.model_copy(update={'comparisons': (fact, other)}), fact_file_resource_id=FACT_RESOURCE)
    assert len(trace.row_keys) == 4 and len(trace.cells) == 8
    assert trace.column_keys == ('对比 1', '对比 2')
    assert markdown.count('| 本期收入 |') == 1
    assert trace.cells[0].fact_refs[0].json_pointer == '/comparisons/0'
    assert trace.cells[1].fact_refs[0].json_pointer == '/comparisons/1'


@pytest.mark.parametrize(("field", "label", "unit"), (
    ("indicator_value", "成本金额", "元"),
    ("mantime_outpatient", "门诊人次", "人次"),
    ("budget_service_income", "预算医疗服务收入", "元"),
))
def test_analysis_table_uses_frozen_schema_business_label(field, label, unit) -> None:
    bundle = _bundle()
    original = bundle.metrics[0]
    ref = "dynamic_source.dynamic_db.dynamic_table." + field
    fact = original.model_copy(update={"field": field, "field_ref": ref, "unit": unit})
    bundle = bundle.model_copy(update={"metrics": (fact,)})
    contexts = ({"datasetId": fact.dataset_id, "sha256": fact.dataset_sha256,
                 "schema": {"tables": [{"sourceId": "dynamic_source", "database": "dynamic_db",
                 "name": "dynamic_table", "columns": [{"name": field, "description": label}]}]}},)
    trace, markdown = build_analysis_table(bundle, fact_file_resource_id=FACT_RESOURCE, dataset_contexts=contexts)
    assert trace.column_keys == (f"{label}（{unit}）",)
    assert trace.cells[0].fact_refs[0].fact_key == fact.fact_id
    assert "3,600" in markdown
    stale = ({**contexts[0], "sha256": "a" * 64},)
    stale_trace, _ = build_analysis_table(bundle, fact_file_resource_id=FACT_RESOURCE, dataset_contexts=stale)
    assert stale_trace.column_keys != trace.column_keys


def test_analysis_table_keeps_union_of_periods_without_filling_missing_values():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import PeriodValue

    bundle = _bundle()
    budget = bundle.metrics[0].model_copy(update={"metric_codes": ("budget",),
        "field": "budget_person_time", "unit": "人次", "fact_id": "fact-" + "a" * 16,
        "period_values": (PeriodValue(period="2025-09", value=1200), PeriodValue(period="2025-10", value=1200))})
    actual = budget.model_copy(update={"metric_codes": ("actual",), "field": "actual_person_time",
        "fact_id": "fact-" + "b" * 16, "period_values": (PeriodValue(period="2025-09", value=1100),)})
    trace, markdown = build_analysis_table(bundle.model_copy(update={"metrics": (budget, actual)}), fact_file_resource_id=FACT_RESOURCE)
    assert trace.row_keys == ("period:2025-09", "period:2025-10")
    assert "| 2025年10月 | 1,200 | — |" in markdown
    assert trace.cells[-1].fact_refs == ()
    assert trace.cells[-2].fact_refs[0].fact_key == budget.fact_id


def test_analysis_table_uses_readable_period_labels_and_profile_metric_names():
    """行标签按读者习惯显示期间（行键不变）；字段无说明时用 Profile 中唯一的简短指标说明。"""
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import PeriodValue

    bundle = _bundle()
    budget = bundle.metrics[0].model_copy(update={"metric_codes": ("budget",),
        "field": "budget_person_time", "unit": "人次", "fact_id": "fact-" + "a" * 16,
        "period_granularity": "month",
        "period_values": (PeriodValue(period="2025-09-01", value=1200), PeriodValue(period="2025-10-01", value=1200))})
    actual = budget.model_copy(update={"metric_codes": ("actual",), "field": "actual_person_time",
        "fact_id": "fact-" + "b" * 16})
    descriptions = {"budget": "预算门诊人次", "actual": "实际门诊人次" * 10}
    trace, markdown = build_analysis_table(
        bundle.model_copy(update={"metrics": (budget, actual)}),
        fact_file_resource_id=FACT_RESOURCE,
        metric_descriptions=descriptions,
    )
    assert trace.row_keys == ("period:2025-09-01", "period:2025-10-01")
    assert "| 2025年9月 | 1,200 | 1,200 |" in markdown
    # 过长的 Profile 说明不适合作表头，仍退回字段名。
    assert trace.column_keys == ("预算门诊人次（人次）", "actual_person_time（人次）")


def test_analysis_table_keeps_raw_periods_when_readable_labels_collide():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import PeriodValue

    bundle = _bundle()
    fact = bundle.metrics[0].model_copy(update={"period_granularity": "month", "period_values": (
        PeriodValue(period="2025-09", value=1), PeriodValue(period="2025-09-01", value=2))})
    _trace, markdown = build_analysis_table(
        bundle.model_copy(update={"metrics": (fact,)}), fact_file_resource_id=FACT_RESOURCE
    )
    assert "| 2025-09 |" in markdown and "| 2025-09-01 |" in markdown
