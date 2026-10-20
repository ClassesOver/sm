"""B6 正文 subject 绑定与校验测试（计划 6.1）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    FactRefV1,
    SubjectBindingV1,
    TableCellBindingV1,
    TableTraceV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.subject_builder import (
    build_claim_subject_bindings,
    claim_status,
    evaluate_subject_status,
    extract_comparable_value,
    value_text_variants,
)

# ---------------------------------------------------------------------------
# 值形态与状态判定（纯函数）
# ---------------------------------------------------------------------------


def test_value_text_variants_cover_common_formats() -> None:
    variants = value_text_variants(3600.0)
    assert "3600" in variants and "3,600" in variants
    variants = value_text_variants(66.67)
    assert "66.67" in variants and any(v.startswith("66.67") for v in variants)


def test_evaluate_subject_status_matrix() -> None:
    markdown = "本月收入 3600 万元，环比上升。[[claim:claim-1]]"
    assert evaluate_subject_status(markdown, "claim-1", 3600.0) == "valid"
    # 正文改值：标记还在，生成时值不在附近。
    changed = "本月收入 3800 万元，环比上升。[[claim:claim-1]]"
    assert evaluate_subject_status(changed, "claim-1", 3600.0) == "stale"
    # 标记被删除：unbound。
    deleted = "本月收入 3800 万元，环比上升。"
    assert evaluate_subject_status(deleted, "claim-1", 3600.0) == "unbound"
    # 千分位形态同样命中。
    formatted = "本月收入 3,600 万元。[[claim:claim-1]]"
    assert evaluate_subject_status(formatted, "claim-1", 3600.0) == "valid"


def test_evaluate_subject_status_rejects_duplicate_markers_and_partial_numbers() -> None:
    assert evaluate_subject_status(
        "收入 3600 万元[[claim:claim-1]]\n\n其他收入 3600 万元[[claim:claim-1]]", "claim-1", 3600.0
    ) == "unbound"
    assert evaluate_subject_status("收入 13600 万元[[claim:claim-1]]", "claim-1", 3600.0) == "stale"
    assert evaluate_subject_status("收入 3,600 万元[[claim:claim-1]]", "claim-1", 3600.0) == "valid"
    assert evaluate_subject_status("收入-3600万元[[claim:claim-1]]", "claim-1", 3600.0) == "stale"
    assert evaluate_subject_status("收入3600万元[[claim:claim-1]]", "claim-1", 3600.0) == "valid"
    assert evaluate_subject_status(
        "其他收入 3600 万元\n\n本月收入 3800 万元[[claim:claim-1]]", "claim-1", 3600.0
    ) == "stale"
    assert evaluate_subject_status("收入 3800 万元[[claim:3600]]", "3600", 3600.0) == "stale"


def test_claim_status_scopes_reused_claim_ids_to_registered_section():
    markdown = (
        "[[section:section_001]]\n\n门诊5,393,961[[claim:claim_001]]人次。\n\n"
        "[[section:section_002]]\n\n门诊100[[claim:claim_001]]人次。"
    )
    assert claim_status(markdown, "claim_001", 5393961, section_id="section_001")["status"] == "valid"
    assert claim_status(markdown, "claim_001", 5393961, section_id="section_002")["status"] == "stale"
    assert claim_status(markdown, "claim_001", 5393961, section_id="section_003")["status"] == "unbound"
    duplicate_section = markdown + "\n\n[[section:section_001]]\n\n重复章节。"
    assert claim_status(duplicate_section, "claim_001", 5393961, section_id="section_001")["status"] == "unbound"
    duplicate_claim = markdown.replace("人次。", "人次。[[claim:claim_001]]", 1)
    assert claim_status(duplicate_claim, "claim_001", 5393961, section_id="section_001")["status"] == "unbound"
    assert claim_status("门诊100[[claim:claim_001]]人次。", "claim_001", 100, section_id="section_001")["status"] == "valid"


@pytest.mark.parametrize(
    ("text", "warning_count"),
    [
        ("2025-09收入3600万元", 0),
        ("2025年9月收入3600万元", 0),
        ("2025/09收入3600亿元", 1),
        ("2025-10收入3600万元", 1),
        ("2025-10收入3600元", 2),
        ("本月收入3600万元", 0),
        ("收入3600", 0),
        ("2025-10人数20人。2025-09收入3600万元", 0),
        ("2025-09收入3600万元，人数20人", 0),
        ("2025-09记录核对后，2025-10收入3600万元", 1),
        ("2025-09收入3,600.00亿元", 1),
    ],
)
def test_claim_unit_period_modifications_are_soft_warnings(text: str, warning_count: int) -> None:
    result = claim_status(
        text + "[[claim:claim-1]]", "claim-1", 3600.0,
        expected_unit="万元", expected_periods=("2025-09",),
    )
    assert result["status"] == "valid"
    assert len(result["warnings"]) == warning_count


@pytest.mark.parametrize('relative', ['同比', '环比', '本月', '上月', '去年同期'])
def test_relative_wording_does_not_erase_an_explicit_cumulative_window(relative):
    from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

    warnings = unit_period_warnings(
        f'2025年9—10月累计收入{relative}2,400.00万元',
        expected_unit='万元', fact_value=2400, expected_periods=('2025-10',),
    )
    assert any('期间' in warning for warning in warnings)


@pytest.mark.anyio
@pytest.mark.parametrize('comparison', ['', '同比', '环比', '本月'])
async def test_editor_retains_period_warning_with_relative_comparison(tmp_path, comparison):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement='2025年9—10月累计收入' + comparison
            + '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。',
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result['subjects'][0]
    # 业务期间仍为软告警，数值绑定不因此失效。
    assert subject['status'] == 'valid'
    assert any('期间' in warning for warning in subject['warnings'])


def test_claim_changed_units_do_not_share_substring_identity() -> None:
    result = claim_status(
        "收入3600万元[[claim:claim-1]]", "claim-1", 3600,
        expected_unit="元",
    )
    assert len(result["warnings"]) == 1
    assert "单位" in result["warnings"][0]


def test_extract_comparable_value_requires_unique_value_unit_period_and_scope() -> None:
    result = extract_comparable_value(
        "2025-09华东收入3,780万元",
        expected_unit="万元",
        expected_periods=("2025-09",),
        expected_scope={},
    )
    assert result == {"value": 3780, "unit": "万元", "periods": ["2025-09"]}

    scoped = extract_comparable_value(
        "2025-09华东收入3,780万元",
        expected_unit="万元",
        expected_periods=("2025-09",),
        expected_scope={"region": "华东"},
    )
    assert scoped == result

    assert extract_comparable_value(
        "收入3,780万元",
        expected_unit="万元",
        expected_periods=("2025-09",),
        expected_scope={},
    ) is None
    assert extract_comparable_value(
        "2025-09华东收入3,780万元，2025-08收入3,500万元",
        expected_unit="万元",
        expected_periods=("2025-09",),
        expected_scope={},
    ) is None
    assert extract_comparable_value(
        "2025-09收入3,780万元",
        expected_unit="万元",
        expected_periods=("2025-09",),
        expected_scope={"region": "华东"},
    ) is None


def test_percentage_point_claim_exposes_comparable_edited_value() -> None:
    result = claim_status(
        "2026年10月东院占比提高2个百分点。[[claim:claim-1]]", "claim-1", 1,
        expected_unit="个百分点", expected_periods=("2026-10",),
        expected_scope={"院区": "东院"},
    )
    assert result["status"] == "stale"
    assert result["draftValue"] == 2
    assert result["draftUnit"] == "个百分点"
    assert result["comparable"] is True
    for text in ("东院提高2个百分点。", "2026年10月提高2个百分点。",
                 "2026年10月东院提高2个百分点，另提高3个百分点。"):
        assert extract_comparable_value(
            text, expected_unit="个百分点", expected_periods=("2026-10",),
            expected_scope={"院区": "东院"},
        ) is None


@pytest.mark.parametrize(("written", "expected"), [
    ("2个百分点后趋稳", 2), ("−2个百分点", -2), ("－2个百分点", -2),
    ("1,234.5个百分点", 1234.5), ("-1,234.5个百分点", -1234.5),
    ("1e2个百分点", None), ("metric2个百分点", None), ("1,23个百分点", None),
])
def test_comparable_percentage_points_preserve_whole_number_identity(written, expected):
    result = claim_status(
        f"2026年10月东院变化{written}。[[claim:claim-1]]", "claim-1", -1,
        expected_unit="个百分点", expected_periods=("2026-10",),
        expected_scope={"院区": "东院"},
    )
    assert result["status"] == "stale"
    if expected is None:
        assert "draftValue" not in result
    else:
        assert result["draftValue"] == expected


@pytest.mark.parametrize(("verb", "expected", "direction"), [
    ("下降", -2, "decrease"), ("降低了", -2, "decrease"),
    ("回落约", -2, "decrease"), ("提高", 2, "increase"), ("涨幅为", 2, "increase"),
])
def test_percentage_point_draft_preserves_direction(verb, expected, direction):
    result = claim_status(
        f"2026年10月东院占比{verb}2个百分点。[[claim:claim-1]]", "claim-1", -1,
        expected_unit="个百分点", expected_periods=("2026-10",),
    )
    assert result["draftValue"] == expected
    assert result["draftDirection"] == direction


@pytest.mark.parametrize("verb", ["下降", "上升"])
def test_ambiguous_signed_percentage_point_magnitude_is_not_comparable(verb):
    assert extract_comparable_value(
        f"2026年10月占比{verb}-2个百分点。",
        expected_unit="个百分点", expected_periods=("2026-10",),
    ) is None


@pytest.mark.parametrize("phrase", ["下降了约{n}个百分点", "下降 约{n}个百分点", "下降**{n}个百分点**", "**下降了约{n}个百分点**"])
def test_percentage_point_direction_survives_modifiers_and_emphasis(phrase):
    def validate(n, fact):
        return claim_status(
            "2026年10月占比" + phrase.format(n=n) + "。[[claim:c]]", "c", fact,
            expected_unit="个百分点", expected_periods=("2026-10",),
        )
    edited = validate(2, 1)
    assert edited["status"] == "stale"
    assert edited["draftValue"] == -2
    assert edited["draftDirection"] == "decrease"
    # Matching magnitude must not hide the opposite sign, including after restoration.
    assert validate(1, 1)["status"] == "stale"
    assert validate(1, -1)["status"] == "valid"


@pytest.mark.parametrize("phrase", ["提高了约1个百分点", "上升**1个百分点**"])
def test_percentage_point_increase_cannot_validate_a_negative_fact(phrase):
    result = claim_status(
        "2026年10月占比" + phrase + "。[[claim:c]]", "c", -1,
        expected_unit="个百分点", expected_periods=("2026-10",),
    )
    assert result["status"] == "stale"
    assert result["draftDirection"] == "increase"


def test_claim_status_exposes_only_a_conservative_comparable_draft_value() -> None:
    result = claim_status(
        "2025-09华东收入3,780万元[[claim:claim-1]]",
        "claim-1",
        3600,
        expected_unit="万元",
        expected_periods=("2025-09",),
    )
    assert result["status"] == "stale"
    assert result["comparable"] is True
    assert result["draftValue"] == 3780
    assert "不一致" in result["warnings"][0]

    ambiguous = claim_status(
        "2025-09收入3,780万元，2025-08收入3,500万元[[claim:claim-1]]",
        "claim-1",
        3600,
        expected_unit="万元",
        expected_periods=("2025-09",),
    )
    assert ambiguous["status"] == "stale"
    assert "draftValue" not in ambiguous
    assert "尚未完成数值校验" in ambiguous["warnings"][0]


def test_build_claim_subject_bindings_maps_facts_and_skips_unknown() -> None:
    fact_id = "fact-" + "a" * 16
    fact_path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    claim = SimpleNamespace(
        claim_id="claim-1",
        value=3600.0,
        metric_code="income_total",
        current_period="2025-09",
        fact_ids=(fact_id, "fact-" + "b" * 16),  # 第二个不在目录 → 跳过
    )
    artifact = SimpleNamespace(section_code="section_002", claims=(claim,))
    directory = {fact_id: ("analysis_001", "/metrics/0")}
    resources = {"analysis_001": derive_resource_id(fact_path)}
    bindings = build_claim_subject_bindings((artifact,), directory, resources)
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.claim_id == "claim-1"
    assert binding.locator.section_id == "section_002"
    assert binding.subject_id.startswith("sub-")
    assert len(binding.fact_refs) == 1
    assert binding.fact_refs[0].fact_key == fact_id
    assert binding.fact_refs[0].json_pointer == "/metrics/0"
    # factIds 全未知的 claim 不产生绑定（软降级，不伪造）。
    unknown_claim = SimpleNamespace(
        claim_id="claim-2", value=1, metric_code="m", current_period="p", fact_ids=("fact-x",)
    )
    unknown_artifact = SimpleNamespace(section_code="section_003", claims=(unknown_claim,))
    assert (
        build_claim_subject_bindings((unknown_artifact,), directory, resources) == ()
    )

    from smart_reporting.reporting.trace.contracts_v1 import (
        NumberReferenceV1,
        TableDerivationV1,
        TableOperandV1,
    )

    table_number = NumberReferenceV1(
        claimId="claim-table",
        token="table-value-token",
        statementSha256="0" * 64,
        tableDerivation=TableDerivationV1(
            operands=(TableOperandV1(
                fileResourceId=derive_resource_id("table.json"),
                tablePointer="/tables/0",
                rowIndex=0,
                columnIndex=1,
                coefficient="1",
            ),),
            unit="元",
        ),
    )
    table_block = SimpleNamespace(number_references=(table_number,), review_notices=None)
    table_artifact = SimpleNamespace(
        section_code="section_004", blocks=(table_block,), claims=()
    )
    table_bindings = build_claim_subject_bindings(
        (table_artifact,), {}, {}
    )
    assert len(table_bindings) == 1
    assert table_bindings[0].claim_id == "claim-table"
    assert table_bindings[0].fact_refs == ()


# ---------------------------------------------------------------------------
# Editor validate 端到端（索引 + [[claim:]] 标记）
# ---------------------------------------------------------------------------


async def _make_editor_with_subject(
    tmp_path: Path,
    *, report_id: str = "report-1", period_table: bool = False, comparison_table: bool = False,
    comparison_rate: float | None = 20, correlation_claim: bool = False, large_amounts: bool = False,
    percentage_point_claim: bool = False, window_claim: str | None = None, window_date_labels: bool = False,
    number_reference: bool = False,
    number_statement: str | None = None,
    metric_scope: dict[str, str] | None = None,
    metric_values: tuple[float, float] | None = None,
    metric_unit: str | None = None,
    include_table: bool = True,
) -> tuple:
    # large_amounts：元为单位的大额分期间表，服务端按“收入（万元）”表头写换算后的数字。
    column_key = "收入（万元）" if large_amounts else "income_total"
    period_numbers = (11123541503.0, 2400000.0) if large_amounts else (1200.0, 2400.0)
    period_cells = ["1,112,354.15", "240.00"] if large_amounts else ["1,200", "2,400"]
    if metric_values is not None:
        period_numbers = metric_values
        period_cells = [f'{value:,}' for value in period_numbers]
    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorContext,
        ReportEditorGrantService,
        ReportEditorService,
    )
    from smart_reporting.reporting.data_sources import DatasetHandle
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, DatasetLineage
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.trace.contracts_v1 import SubjectLocatorV1
    from smart_reporting.reporting.trace.index_builder import (
        build_csv_trace_index,
        encode_trace_index,
    )
    from smart_reporting.reporting.workflow.scope import reporting_scope_keys

    keys = reporting_scope_keys(
        database="database-1",
        company_id="company-1",
        user_id="user-1",
        thread_id="caller-thread",
        run_id=report_id,
    )
    from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

    scope = ReportingWorkflowScope(
        run_id=report_id,
        external_run_id="external-1",
        session_id="workflow-session",
        caller_thread_id="caller-thread",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    )
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    table_block = render_table_markdown(
        "tbl-1", (column_key,),
        [["2025-09", period_cells[0]], ["2025-10", period_cells[1]]] if period_table
        else [["本期", "3,600"], ["上期", "3,600"]],
    )
    markdown = f"# 报告\n\n{table_block}\n"
    if not comparison_table:
        await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown)
    csv_bytes = b"period,revenue\n2025-09,3600\n"
    csv_path = f"报表/数据集/{report_id}/dataset-url-abc0001.csv"
    await workspace.awrite_bytes(scope.workspace_key, csv_path, csv_bytes)
    fact_path = f"报表/智能分析/{report_id}/facts/revision-1/analysis_001.json"
    bundle_bytes = json.dumps(
        {
            "version": "1",
            "analysisId": "analysis_001",
            "metrics": [
                {
                    "factId": "fact-" + "a" * 16,
                    "datasetId": "dataset-url-abc0001",
                    "datasetSha256": hashlib.sha256(csv_bytes).hexdigest(),
                    "periodRoles": ["current"],
                    "metricCodes": ["income_total"],
                    "field": "收入",
                    "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
                    "aggregation": "sum",
                    "formula": "sum(revenue)",
                    "scope": metric_scope or {},
                    "total": sum(period_numbers) if large_amounts or metric_values is not None else 3600.0,
                    "unit": metric_unit or ("元" if large_amounts else "万元"),
                    "periodGranularity": "month",
                    "periodValues": ([{"period": "2025-09", "value": period_numbers[0]},
                                      {"period": "2025-10", "value": period_numbers[1]}] if period_table
                                     else [{"period": "2025-09", "value": 3600.0}]),
                    "missingCount": 0,
                    "zeroCount": 0,
                    "negativeCount": 0,
                    "warnings": [],
                }
            ],
            "derivedMetrics": [],
            "comparisons": [],
            "reconciliations": [],
            "correlationDetails": [],
            "correlations": {},
            "warnings": [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if percentage_point_claim:
        document = json.loads(bundle_bytes)
        document["metrics"][0].update(total=-1, unit="个百分点",
                                      periodValues=[{"period": "2025-09", "value": -1}])
        bundle_bytes = json.dumps(document, ensure_ascii=False).encode()
    if correlation_claim:
        document = json.loads(bundle_bytes)
        document["correlationDetails"] = [{
            "factId": "fact-" + "b" * 16, "datasetId": "dataset-url-abc0001",
            "leftField": "收入", "rightField": "人次", "method": "pearson",
            "sampleCount": 12, "value": 0.8,
        }]
        bundle_bytes = json.dumps(document, ensure_ascii=False).encode()
    if comparison_table or window_claim == "comparison":
        document = json.loads(bundle_bytes)
        document["comparisons"] = [{
            "factId": "fact-" + "c" * 16, "currentTotal": 3600,
            "baselineTotal": 3000, "change": 600, "changeRate": comparison_rate,
            "unit": "元", "comparisonType": "yoy",
            "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
            "currentDatasetId": "dataset-url-abc0001",
            "periodStart": "2025-09-01" if window_date_labels else "2025-09",
            "periodEnd": "2025-09-01" if window_date_labels else "2025-09",
        }]
        bundle_bytes = json.dumps(document, ensure_ascii=False).encode()
    if window_claim == "derived":
        document = json.loads(bundle_bytes)
        document["derivedMetrics"] = [{
            "factId": "fact-" + "c" * 16, "code": "revenue_ratio", "kind": "ratio",
            "numeratorMetric": "income_total", "denominatorMetric": "income_total",
            "datasetIds": ["dataset-url-abc0001"], "periodRole": "current",
            "value": 1, "percentage": 100, "unit": "万元",
            "periodStart": "2025-09-01" if window_date_labels else "2025-09",
            "periodEnd": "2025-09-01" if window_date_labels else "2025-09",
        }]
        bundle_bytes = json.dumps(document, ensure_ascii=False).encode()
    if comparison_table:
        rate_text = "—" if comparison_rate is None else f"{comparison_rate}%"
        table_block = render_table_markdown("tbl-1", ("数值",), [["本期", "3,600元"], ["同期", "3,000元"], ["变化", "600元"], ["同比", rate_text]])
        markdown = f"# 报告\n\n{table_block}\n"
        await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown)
    await workspace.awrite_bytes(scope.workspace_key, fact_path, bundle_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    handle = DatasetHandle(
        dataset_id="dataset-url-abc0001",
        source_id="mcp-url",
        source_type="url_csv",
        path=csv_path,
        row_count=1,
        size=len(csv_bytes),
        sha256=csv_sha,
        requirement_id="attachment-001",
        sql_hash=hashlib.sha256(f"url_csv:{csv_sha}".encode()).hexdigest(),
        filename="收入明细.csv",
    )
    lineage = DatasetLineage(
        datasetId="dataset-url-abc0001",
        sourceId="mcp-url",
        sourceType="url_csv",
        requirementId="attachment-001",
        sqlHash=handle.sql_hash,
        rowCount=1,
        size=len(csv_bytes),
        sha256=csv_sha,
    )
    subject = SubjectBindingV1(
        subjectId="sub-" + "0" * 16,
        subjectKind="text_claim",
        locator=SubjectLocatorV1(sectionId="section_002"),
        subjectSha256="b" * 64,
        claimId="claim-1",
        factRefs=(
            FactRefV1(
                analysisId="analysis_001",
                fileResourceId=derive_resource_id(fact_path),
                jsonPointer="/metrics/0",
                factKind="metric",
                factKey="fact-" + "a" * 16,
            ),
        ),
    )
    review_notices = None
    if number_reference:
        from smart_reporting.reporting.trace.semantic_bindings import (
            anchor_bound_numbers,
            render_bound_numbers,
        )

        markdown, references, review_notices = render_bound_numbers(
            number_statement or
            "10月收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。供应商回复待核实。金额999999元。",
            [bundle_bytes.decode()], key="section_002:block",
        )
        markdown = anchor_bound_numbers(markdown, references, review_notices)
        subject = subject.model_copy(update={"claim_id": references[0].claim_id,
                                             "number_reference": references[0]})
        await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown, overwrite=True)
    if window_claim:
        array = "comparisons" if window_claim == "comparison" else "derivedMetrics"
        subject = subject.model_copy(update={"fact_refs": (subject.fact_refs[0].model_copy(update={
            "json_pointer": f"/{array}/0", "fact_kind": window_claim, "fact_key": "fact-" + "c" * 16,
        }),)})
    if correlation_claim:
        fact_id = "fact-" + "b" * 16
        claim = SimpleNamespace(claim_id="claim-1", value=0.8, metric_code="correlation",
                                current_period="2025-09", fact_ids=(fact_id,))
        subject = build_claim_subject_bindings(
            (SimpleNamespace(section_code="section_002", claims=(claim,)),),
            {fact_id: ("analysis_001", "/correlationDetails/0")},
            {"analysis_001": derive_resource_id(fact_path)},
        )[0]
    table_fact_ref = FactRefV1(
        analysisId="analysis_001",
        fileResourceId=derive_resource_id(fact_path),
        jsonPointer="/metrics/0",
        factKind="metric",
        factKey="fact-" + "a" * 16,
    )
    table_trace = TableTraceV1(
        tableId="tbl-1",
        rowKeys=("period:2025-09", "period:2025-10") if period_table else ("row:cur", "row:prev"),
        columnKeys=(column_key,),
        cells=(
            TableCellBindingV1(rowKey="period:2025-09" if period_table else "row:cur", columnKey=column_key, factRefs=(table_fact_ref,)),
            TableCellBindingV1(rowKey="period:2025-10" if period_table else "row:prev", columnKey=column_key, factRefs=(table_fact_ref,)),
        ),
    )
    if comparison_table:
        comparison_ref = table_fact_ref.model_copy(update={
            "json_pointer": "/comparisons/0", "fact_kind": "comparison", "fact_key": "fact-" + "c" * 16,
        })
        row_keys = tuple(f"comparison:0:{field}" for field in ("currentTotal", "baselineTotal", "change", "changeRate"))
        table_trace = TableTraceV1(tableId="tbl-1", rowKeys=row_keys, columnKeys=("数值",), cells=tuple(
            TableCellBindingV1(rowKey=row, columnKey="数值", factRefs=(comparison_ref,)) for row in row_keys
        ))
    index = build_csv_trace_index(
        handles=(handle,),
        lineage=(lineage,),
        report_id=report_id,
        revision=1,
        workflow_run_id=report_id,
        markdown_file=ArtifactFile(
            path="reports/revision-1/report.md",
            mediaType="text/markdown",
            size=len(markdown.encode()),
            sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        ),
        fact_files={
            "analysis_001": ArtifactFile(
                path=fact_path,
                mediaType="application/json",
                size=len(bundle_bytes),
                sha256=hashlib.sha256(bundle_bytes).hexdigest(),
            )
        },
        subject_bindings=(subject,),
        review_notices=review_notices,
        server_table_traces=(table_trace,) if include_table else (),
    )
    await workspace.awrite_bytes(
        scope.workspace_key,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index),
    )
    from .lineage_fixtures.manifest import register_trace_manifest

    manifest_identity = await register_trace_manifest(workspace, scope.workspace_key, index)
    registry.release(scope.workspace_key)
    context = ReportEditorContext(
        artifactManifest=manifest_identity,
        reportId=report_id,
        revision=1,
        jobId="job-1",
        workflowRunId=report_id,
        markdownPath="reports/revision-1/report.md",
        job={"jobId": "job-1", "status": "validated"},
        scope=scope.as_state(),
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )

    async def _get(*_args, **_kwargs):
        return state

    editor = ReportEditorService(
        state_repository=SimpleNamespace(get=_get),
        workspace_registry=registry,
        workspace=workspace,
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    # 编辑器每次请求都会经 _restore 重新注册工作区；测试模拟该恢复。
    registry.resolve(scope)
    return editor, grants, context


async def _make_editor_with_table_derivation(
    tmp_path: Path, *, source_bytes: bytes | None = None, fault: str | None = None,
    fact_ref_fault: str | None = None, claims: int = 1, include_ordinary: bool = False,
):
    from smart_reporting.reporting.trace.contracts_v1 import (
        NumberReferenceV1,
        TableDerivationV1,
        TableOperandV1,
    )
    from smart_reporting.reporting.trace.index_builder import encode_trace_index
    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprints
    from smart_reporting.reporting.trace.table_sources import table_derivation_token

    from .lineage_fixtures.manifest import register_trace_manifest

    editor, _, context = await _make_editor_with_subject(
        tmp_path, include_table=False, number_reference=include_ordinary,
        period_table=include_ordinary,
    )
    index = await editor.trace.require_index(context)
    ordinary = index.subject_bindings[0]
    path = "reports/revision-1/table-source.json"
    resource_id = derive_resource_id(path)
    original = json.dumps({"tables": [{
        "title": "收入", "columns": ["科室", "本期收入", "上期收入"],
        "rows": [["财务科", 3600, 3000]],
        "columnMeta": {"本期收入": {"unit": "万元"}, "上期收入": {"unit": "万元"}},
        "periodStart": "2025-09", "periodEnd": "2025-09",
        "scope": {"科室": "财务科"},
    }]}, ensure_ascii=False).encode()
    derivation = TableDerivationV1(operands=tuple(
        TableOperandV1(fileResourceId=resource_id, tablePointer="/tables/0",
                       rowIndex=0, columnIndex=column, coefficient=coefficient)
        for column, coefficient in ((1, "1"), (2, "-1"))
    ), unit="万元")
    token = table_derivation_token(derivation, {resource_id: original})
    assert token is not None
    if fault == "unsupported_shape":
        derivation = derivation.model_copy(update={"operands": derivation.operands[:1]})
    elif fault == "bad_pointer":
        derivation = derivation.model_copy(update={"operands": tuple(
            operand.model_copy(update={"table_pointer": "/tables/99"})
            for operand in derivation.operands
        )})
    elif fault == "token_mismatch":
        token = "{{tableDerived:" + "0" * 64 + "}}"
    refs = ()
    if fact_ref_fault is not None:
        changes = {
            "valid": {}, "analysis": {"analysis_id": "analysis_001"},
            "pointer": {"json_pointer": "/metrics/99"},
            "kind": {"fact_kind": "comparison"}, "key": {"fact_key": "fact-" + "f" * 16},
        }[fact_ref_fault]
        refs = (ordinary.fact_refs[0].model_copy(update=changes),)
    claim_ids = tuple(f"claim-table-{position}" for position in range(claims))
    markdown = "\n\n".join(
        f"2025年9月财务科收入差额600万元[[claim:{claim_id}]]。" for claim_id in claim_ids
    )
    if include_ordinary:
        markdown += "\n\n" + (await editor.trace._read_registered_file(
            context, next(file for file in index.files
                          if file.resource_id == index.markdown_file_resource_id),
            max_bytes=16 * 1024 * 1024,
        )).decode()
    fingerprints = statement_fingerprints(markdown, claim_ids)
    bindings = tuple(ordinary.model_copy(update={
        "subject_id": "sub-" + f"{position + 1:016x}", "claim_id": claim_id, "fact_refs": refs,
        "number_reference": NumberReferenceV1(
            claimId=claim_id, token=token, statementSha256=fingerprints[claim_id],
            displayText="600万元", tableDerivation=derivation,
        ),
    }) for position, claim_id in enumerate(claim_ids))
    source_bytes = original if source_bytes is None else source_bytes
    await editor.workspace.awrite_bytes(context.scope["threadId"], path, source_bytes)
    await editor.workspace.awrite_text(
        context.scope["threadId"], context.markdown_path, markdown, overwrite=True,
    )
    if fact_ref_fault == "analysis":
        fact_ref = ordinary.fact_refs[0]
        fact_file = next(file for file in index.files if file.resource_id == fact_ref.file_resource_id)
        fact_document = json.loads(await editor.trace._read_registered_file(
            context, fact_file, max_bytes=16 * 1024 * 1024,
        ))
        fact_document["analysisId"] = "other_analysis"
        fact_bytes = json.dumps(fact_document, ensure_ascii=False).encode()
        await editor.workspace.awrite_bytes(context.scope["threadId"], fact_file.path, fact_bytes, overwrite=True)
        index = index.model_copy(update={"files": tuple(
            file.model_copy(update={"size": len(fact_bytes), "sha256": hashlib.sha256(fact_bytes).hexdigest()})
            if file.resource_id == fact_file.resource_id else file for file in index.files
        )})
    files = tuple(file.model_copy(update={
        "size": len(markdown.encode()), "sha256": hashlib.sha256(markdown.encode()).hexdigest(),
    }) if file.resource_id == index.markdown_file_resource_id else file for file in index.files)
    index = index.model_copy(update={
        "files": (*files, TraceFileRefV1(
            resourceId=resource_id, path=path, mediaType="application/json",
            size=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest(),
        )),
        "subject_bindings": (*bindings, ordinary) if include_ordinary else bindings,
    })
    await editor.workspace.awrite_bytes(
        context.scope["threadId"], "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index), overwrite=True,
    )
    manifest = await register_trace_manifest(
        editor.workspace, context.scope["threadId"], index, overwrite=True,
    )
    return editor, context.model_copy(update={"artifact_manifest": manifest}), markdown, path


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_table_only_derivation_uses_frozen_source_metadata(tmp_path):
    editor, context, markdown, _ = await _make_editor_with_table_derivation(tmp_path)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"] == {"valid": 1, "stale": 0, "unbound": 0}
    subject = result["subjects"][0]
    assert subject["factValue"] == 600
    assert subject["restoreText"] == "600万元"
    assert subject["unit"] == "万元"
    assert subject["periods"] == ["2025-09"]
    assert subject["scope"] == {"科室": "财务科"}
    assert subject["formula"] == "(3600) * (1) + (3000) * (-1)"
    assert subject["datasetIds"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(("change", "expected"), [
    ("value", "stale"), ("statement", "stale"),
    ("missing_marker", "unbound"), ("duplicate_marker", "unbound"),
])
async def test_validate_table_derivation_tracks_draft_changes(tmp_path, change, expected):
    editor, context, markdown, _ = await _make_editor_with_table_derivation(tmp_path)
    draft = {
        "value": markdown.replace("600", "700"),
        "statement": markdown.replace("收入差额", "收入差额合计"),
        "missing_marker": markdown.replace("[[claim:claim-table-0]]", ""),
        "duplicate_marker": markdown + "\n\n" + markdown,
    }[change]
    result = await editor.trace.validate(context, draft, hashlib.sha256(draft.encode()).hexdigest())
    assert result["subjects"][0]["status"] == expected
    assert result["subjects"][0]["factValue"] == 600
    assert result["subjects"][0]["restoreText"] == "600万元"
    if change == "statement":
        assert result["subjects"][0]["comparable"] is False
        assert any("陈述已修改" in warning for warning in result["subjects"][0]["warnings"])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [
    "unsupported_shape", "bad_pointer", "token_mismatch", "malformed_json", "resolver_exception",
])
async def test_validate_table_resolution_failures_are_unbound(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.trace import table_sources

    editor, context, markdown, _ = await _make_editor_with_table_derivation(
        tmp_path, fault=fault, source_bytes=b"{broken-json" if fault == "malformed_json" else None,
    )
    if fault == "resolver_exception":
        def fail(*_args):
            raise RuntimeError("resolver unavailable")
        monkeypatch.setattr(table_sources, "resolve_table_derivation", fail)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"] == {"valid": 0, "stale": 0, "unbound": 1}
    assert result["subjects"][0]["factValue"] is None
    assert result["subjects"][0]["restoreText"] is None
    assert result["subjects"][0]["warnings"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["missing", "size", "hash"])
async def test_validate_table_source_integrity_failure_is_not_softened(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.trace import table_sources

    editor, context, markdown, path = await _make_editor_with_table_derivation(tmp_path)
    def unexpected_resolve(*_args):
        pytest.fail("unverified source reached the resolver")
    monkeypatch.setattr(table_sources, "resolve_table_derivation", unexpected_resolve)
    if fault == "missing":
        await editor.workspace.adelete_file(context.scope["threadId"], path)
    else:
        raw = await editor.workspace.read_limited_regular_file(
            context.scope["threadId"], path, max_bytes=16 * 1024 * 1024,
        )
        changed = b"{}" if fault == "size" else raw.replace(b"3600", b"9999")
        await editor.workspace.awrite_bytes(context.scope["threadId"], path, changed, overwrite=True)
    with pytest.raises(ReportingError) as error:
        await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert error.value.code == "snapshot_integrity_failed"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fact_ref_fault", ["valid", "analysis", "pointer", "kind", "key"])
async def test_validate_table_derivation_checks_accompanying_fact_refs(tmp_path, fact_ref_fault):
    editor, context, markdown, _ = await _make_editor_with_table_derivation(
        tmp_path, fact_ref_fault=fact_ref_fault,
    )
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["subjects"][0]["status"] == ("valid" if fact_ref_fault == "valid" else "unbound")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_table_sources_cached_per_request_off_thread_and_not_fact_batched(tmp_path, monkeypatch):
    import threading

    from smart_reporting.reporting.trace import semantic_bindings, table_sources

    editor, context, markdown, path = await _make_editor_with_table_derivation(
        tmp_path, claims=2, include_ordinary=True,
    )
    source_reads = []
    resolver_threads = []
    batches = []
    original_read = editor.workspace.read_limited_regular_file
    original_table_resolve = table_sources.resolve_table_derivation
    original_fact_resolve = semantic_bindings.resolve_number_references
    async def read(*args, **kwargs):
        if args[1] == path:
            source_reads.append(args[1])
        return await original_read(*args, **kwargs)
    def table_resolve(*args):
        resolver_threads.append(threading.get_ident())
        return original_table_resolve(*args)
    def fact_resolve(tokens, sources):
        batches.append(set(tokens))
        return original_fact_resolve(tokens, sources)
    monkeypatch.setattr(editor.workspace, "read_limited_regular_file", read)
    monkeypatch.setattr(table_sources, "resolve_table_derivation", table_resolve)
    monkeypatch.setattr(semantic_bindings, "resolve_number_references", fact_resolve)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"] == {"valid": 3, "stale": 0, "unbound": 0}
    assert source_reads == [path]
    assert len(resolver_threads) == 2
    assert all(thread != threading.get_ident() for thread in resolver_threads)
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert all("tableDerived" not in token for token in batches[0])
    # A new validation must verify the file again, not reuse a previous request's bytes.
    await editor.workspace.awrite_bytes(context.scope["threadId"], path, b"{}", overwrite=True)
    with pytest.raises(ReportingError) as error:
        await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert error.value.code == "snapshot_integrity_failed"
    assert source_reads == [path, path]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_reports_valid_stale_unbound(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    valid_markdown = "收入 3600 万元[[claim:claim-1]]"
    result = await editor.trace_validate(
        context, session, valid_markdown, hashlib.sha256(valid_markdown.encode()).hexdigest()
    )
    assert result["summary"] == {"valid": 1, "stale": 0, "unbound": 0}
    assert result["draftSha256"] == hashlib.sha256(valid_markdown.encode()).hexdigest()
    assert result["subjects"][0]["factValue"] == 3600.0
    # B8 导出附录摘要字段：全部来自冻结事实登记，不从草稿反推。
    assert result["subjects"][0]["unit"] == "万元"
    assert result["subjects"][0]["periods"] == ["2025-09"]
    assert result["subjects"][0]["formula"] == "sum(revenue)"
    # 编辑器核对卡片使用与导出附录相同的中文口径。
    assert result["subjects"][0]["formulaText"] == "revenue 求和"
    assert result["subjects"][0]["datasetIds"] == ["dataset-url-abc0001"]

    stale_markdown = "收入 3800 万元[[claim:claim-1]]"
    stale = await editor.trace_validate(
        context, session, stale_markdown, hashlib.sha256(stale_markdown.encode()).hexdigest()
    )
    assert stale["summary"]["stale"] == 1

    unbound_markdown = "段落已删除"
    unbound = await editor.trace_validate(
        context, session, unbound_markdown, hashlib.sha256(unbound_markdown.encode()).hexdigest()
    )
    assert unbound["summary"]["unbound"] == 1

    with pytest.raises(ReportingError) as error:
        await editor.trace_validate(context, session, valid_markdown, "e" * 64)
    assert error.value.code == "request_invalid"


@pytest.mark.anyio
async def test_validate_content_warnings_survive_missing_claim_anchor(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _, session = await grants.exchange(raw)
    markdown = "收入3800万元。字段未填充有效数值。"
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["summary"]["unbound"] == 1
    assert any("3800万元" in warning for warning in result["warnings"])
    assert any("直接证据" in warning for warning in result["warnings"])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_uses_registered_chart_percentages(tmp_path: Path) -> None:
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    from .lineage_fixtures.manifest import register_trace_manifest

    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    assert index is not None
    image_path = "reports/revision-1/chart.png"
    plot_path = "reports/revision-1/chart.chart-input.json"
    plot = json.dumps({
        "schema": "chart-input/v1", "chartId": "chart_001", "columns": ["name", "share"],
        "rows": [["药品", 27.387028071755648]], "rowCount": 1,
        "columnMeta": {"share": {"unit": "%", "isPercent": True}},
    }).encode()
    files = []
    for path, data, media_type in ((image_path, b"png", "image/png"),
                                   (plot_path, plot, "application/json")):
        await editor.workspace.awrite_bytes(context.scope["threadId"], path, data)
        files.append(TraceFileRefV1(
            resourceId=derive_resource_id(path), path=path, mediaType=media_type,
            size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        ))
    index = index.model_copy(update={
        "files": (*index.files, *files),
        "chart_traces": (ChartTraceV1(
            chartId="chart_001", imageFileResourceId=derive_resource_id(image_path),
            plotDataFileResourceIds=(derive_resource_id(plot_path),),
            datasetIds=("dataset-url-abc0001",),
        ),),
    })
    await editor.workspace.awrite_bytes(
        context.scope["threadId"], "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index), overwrite=True,
    )
    manifest = await register_trace_manifest(
        editor.workspace, context.scope["threadId"], index, overwrite=True,
    )
    context = context.model_copy(update={"artifact_manifest": manifest})
    markdown = "药品占比27.39%。"
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert not any("27.39%" in warning for warning in result["warnings"])



@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_returns_unit_and_period_warnings(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = "2025-10收入3600亿元[[claim:claim-1]]"
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["subjects"][0]["status"] == "valid"
    assert len(result["subjects"][0]["warnings"]) == 2
    assert result["summary"]["valid"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("window_claim", ["comparison", "derived"])
@pytest.mark.parametrize("window_date_labels", [False, True])
@pytest.mark.parametrize(("month", "warns"), [(9, False), (10, True)])
async def test_validate_checks_comparison_and_derived_claim_periods(tmp_path, window_claim, window_date_labels, month, warns):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, window_claim=window_claim, window_date_labels=window_date_labels)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    statement = "收入同比增加600元" if window_claim == "comparison" else "收入比率100%"
    markdown = f"2025年{month}月{statement}[[claim:claim-1]]。"
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result["subjects"][0]
    assert subject["status"] == "valid"
    assert bool([w for w in subject["warnings"] if "期间文本" in w]) is warns
    assert subject["periods"] == ["2025-09"]
    assert result["summary"]["valid"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("percentage_point_claim", [False, True])
async def test_validate_returns_conservative_comparable_draft_value(tmp_path: Path, percentage_point_claim) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path, percentage_point_claim=percentage_point_claim)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = ("2025-09占比下降2个百分点[[claim:claim-1]]" if percentage_point_claim
                else "2025-09收入3780万元[[claim:claim-1]]")
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    subject = result["subjects"][0]
    assert subject["status"] == "stale"
    assert subject["comparable"] is True
    assert subject["draftValue"] == (-2 if percentage_point_claim else 3780)
    assert subject["draftUnit"] == ("个百分点" if percentage_point_claim else "万元")
    assert subject["draftDirection"] == ("decrease" if percentage_point_claim else None)
    assert subject["draftPeriods"] == ["2025-09"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_rejects_modified_fact_file(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    fact_path = "报表/智能分析/report-1/facts/revision-1/analysis_001.json"
    await editor.workspace.adelete_file(context.scope["threadId"], fact_path)
    await editor.workspace.awrite_bytes(context.scope["threadId"], fact_path, b"{}")
    markdown = "收入 3600 万元[[claim:claim-1]]"
    with pytest.raises(ReportingError) as error:
        await editor.trace_validate(
            context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
        )
    assert error.value.code == "snapshot_integrity_failed"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sources_reject_index_for_another_report(tmp_path: Path) -> None:
    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    mismatched = context.model_copy(update={"report_id": "other-report"})
    with pytest.raises(ReportingError) as error:
        await editor.trace.load_index(mismatched)
    assert error.value.code == "snapshot_integrity_failed"


# ---------------------------------------------------------------------------
# 表格身份重判（计划 6.1：排序不失效，改值 stale，插删行/删块 unbound）
# ---------------------------------------------------------------------------


def _table_markdown(rows: list[list[str]]) -> str:
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    return render_table_markdown("tbl-1", ("income_total",), rows)


async def _validate_tables(tmp_path: Path, draft: str) -> dict:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    return await editor.trace_validate(
        context, session, draft, hashlib.sha256(draft.encode()).hexdigest()
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_period_table_sources_and_values_use_frozen_months(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path, period_table=True)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    index = await editor.trace.load_index(context)
    assert index is not None
    cells = [item for item in index.subject_bindings if item.subject_kind == "table_cell"]
    assert len(cells) == 2
    assert {item.locator.row_key for item in cells} == {"period:2025-09", "period:2025-10"}
    from smart_reporting.reporting.trace.subject_builder import bind_table_subjects

    assert bind_table_subjects(index).subject_bindings == index.subject_bindings
    markdown = _table_markdown([["2025-09", "1,200"], ["2025-10", "2,400"]])
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["tableSummary"]["valid"] == 2
    modified = markdown.replace("1,200", "3,600")
    result = await editor.trace_validate(
        context, session, modified, hashlib.sha256(modified.encode()).hexdigest()
    )
    assert result["tableSummary"]["stale"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_scaled_table_cells_are_verified_with_the_header_unit(tmp_path: Path) -> None:
    """大额列以“收入（万元）”表头写换算后的数字，单元格须按表头单位核对，不能全判 stale。"""
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, large_amounts=True
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = _table_markdown_with(
        "收入（万元）", [["2025-09", "1,112,354.15"], ["2025-10", "240.00"]]
    )
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["tableSummary"]["valid"] == 2
    modified = markdown.replace("240.00", "250.00")
    result = await editor.trace_validate(
        context, session, modified, hashlib.sha256(modified.encode()).hexdigest()
    )
    assert result["tableSummary"]["stale"] == 1


def _table_markdown_with(column_key: str, rows: list[list[str]]) -> str:
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    return render_table_markdown("tbl-1", (column_key,), rows)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_keep_binding_when_rows_are_sorted(tmp_path: Path) -> None:
    swapped = _table_markdown([["上期", "3,600"], ["本期", "3,600"]])
    result = await _validate_tables(tmp_path, f"# 报告\n\n{swapped}\n")
    assert result["tableSummary"] == {
        "valid": 2, "stale": 0, "unbound": 0, "insertedRows": 0, "copiedCells": 0,
    }
    assert result["tables"][0] == {
        "tableId": "tbl-1",
        "cells": {"valid": 2, "stale": 0, "unbound": 0},
        "copiedCells": [],
        "insertedRows": 0,
        "datasetIds": ["dataset-url-abc0001"],
        "methods": ["sum(revenue)"],
        "locations": [
            {"rowKey": "row:cur", "columnKey": "income_total", "rowIndex": 1,
             "columnIndex": 1, "rowLabel": "本期", "text": "3,600", "status": "valid"},
            {"rowKey": "row:prev", "columnKey": "income_total", "rowIndex": 0,
             "columnIndex": 1, "rowLabel": "上期", "text": "3,600", "status": "valid"},
        ],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_preserves_binding_after_editor_serialization(tmp_path: Path) -> None:
    draft = (
        "[[table:tbl-1]]\n\n"
        "| <br /> | income\\_total |\n"
        "| ------ | ------------- |\n"
        "| **本期** | **3,600** |\n"
        "| 上期 | 3,600 |\n\n"
        "[[/table:tbl-1]]\n"
    )
    result = await _validate_tables(tmp_path, f"# 报告\n\n{draft}")
    assert result["tableSummary"] == {
        "valid": 2, "stale": 0, "unbound": 0, "insertedRows": 0, "copiedCells": 0,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_tolerate_unreadable_committed_markdown(tmp_path: Path) -> None:
    """已提交正文读取失败时表格重判按保守路径完成（不给定位），不因 None 崩溃。"""
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    original = editor.trace._workspace.read_limited_regular_file

    async def failing_markdown(thread_id, path, *, max_bytes):
        if path == context.markdown_path:
            raise OSError("committed markdown unavailable")
        return await original(thread_id, path, max_bytes=max_bytes)

    editor.trace._workspace.read_limited_regular_file = failing_markdown
    draft = f"# 报告\n\n{_table_markdown([['本期', '3,600'], ['上期', '3,600']])}\n"
    result = await editor.trace_validate(
        context, session, draft, hashlib.sha256(draft.encode()).hexdigest()
    )
    # 没有已提交正文就无法把行标签映射到冻结行键：单元格按 unbound 计，不给定位。
    assert result["tables"][0]["locations"] == []
    assert result["tableSummary"]["unbound"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_flag_edited_value_but_keep_other_cells(tmp_path: Path) -> None:
    edited = _table_markdown([["本期", "3,600"], ["上期", "9,999"]])
    result = await _validate_tables(tmp_path, f"# 报告\n\n{edited}\n")
    assert result["tableSummary"] == {
        "valid": 1, "stale": 1, "unbound": 0, "insertedRows": 0, "copiedCells": 0,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("correct_last", [False, True])
@pytest.mark.parametrize("copies", [2, 3])
async def test_duplicate_table_identity_cannot_hide_modified_values(tmp_path, correct_last, copies):
    correct = _table_markdown([["本期", "3,600"], ["上期", "3,600"]])
    wrong = _table_markdown([["本期", "9,999"], ["上期", "9,999"]])
    blocks = [correct] * (copies - 1)
    blocks.insert(0 if correct_last else len(blocks), wrong)
    result = await _validate_tables(tmp_path, "\n\n".join(blocks))
    assert result["tableSummary"]["valid"] == 0
    assert result["tableSummary"]["unbound"] == 2
    assert result["tables"][0]["locations"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_locations_follow_current_rows_without_guessing_duplicates(tmp_path: Path) -> None:
    sorted_table = _table_markdown([["上期", "9,999"], ["本期", "3,600"]])
    result = await _validate_tables(tmp_path / "sorted", f"# 报告\n\n{sorted_table}\n")
    assert result["tables"][0]["locations"] == [
        {"rowKey": "row:cur", "columnKey": "income_total", "rowIndex": 1,
         "columnIndex": 1, "rowLabel": "本期", "text": "3,600", "status": "valid"},
        {"rowKey": "row:prev", "columnKey": "income_total", "rowIndex": 0,
         "columnIndex": 1, "rowLabel": "上期", "text": "9,999", "status": "stale"},
    ]
    duplicated = _table_markdown([["本期", "3,600"], ["本期", "3,600"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path / "duplicate", f"# 报告\n\n{duplicated}\n")
    assert [item["rowKey"] for item in result["tables"][0]["locations"]] == ["row:prev"]
    result = await _validate_tables(tmp_path / "blocks", f"# 报告\n\n{sorted_table}\n\n{sorted_table}\n")
    assert result["tables"][0]["locations"] == []
    removed = _table_markdown([["本期", "3,600"]])
    result = await _validate_tables(tmp_path / "removed-location", f"# 报告\n\n{removed}\n")
    assert [item["rowKey"] for item in result["tables"][0]["locations"]] == ["row:cur"]
    renamed_column = sorted_table.replace(r"income\_total", "renamed")
    assert renamed_column != sorted_table
    result = await _validate_tables(tmp_path / "renamed-column-location", renamed_column)
    assert result["tables"][0]["locations"] == []
    duplicate_column = sorted_table.replace(r"| income\_total |", r"| income\_total | income\_total |")
    assert duplicate_column != sorted_table
    result = await _validate_tables(tmp_path / "duplicate-column-location", duplicate_column)
    assert result["tables"][0]["locations"] == []
    result = await _validate_tables(tmp_path / "missing-table-location", "# 报告\n")
    assert result["tables"][0]["locations"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_count_inserted_renamed_and_deleted_rows(tmp_path: Path) -> None:
    inserted = _table_markdown([["本期", "3,600"], ["上期", "3,600"], ["新增", "1,234"]])
    result = await _validate_tables(tmp_path / "inserted", f"# 报告\n\n{inserted}\n")
    assert result["tableSummary"]["insertedRows"] == 1
    assert result["tableSummary"]["valid"] == 2
    assert result["tableSummary"]["copiedCells"] == 0

    renamed = _table_markdown([["本期X", "3,600"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path / "renamed", f"# 报告\n\n{renamed}\n")
    assert result["tableSummary"] == {
        "valid": 1, "stale": 0, "unbound": 1, "insertedRows": 1, "copiedCells": 1,
    }

    removed = _table_markdown([["本期", "3,600"]])
    result = await _validate_tables(tmp_path / "removed", f"# 报告\n\n{removed}\n")
    assert result["tableSummary"] == {
        "valid": 1, "stale": 0, "unbound": 1, "insertedRows": 0, "copiedCells": 0,
    }

    result = await _validate_tables(tmp_path / "deleted", "# 报告\n\n表格整体被删除。\n")
    assert result["tableSummary"] == {
        "valid": 0, "stale": 0, "unbound": 2, "insertedRows": 0, "copiedCells": 0,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_flag_edited_header_as_stale(tmp_path: Path) -> None:
    broken = (
        "[[table:tbl-1]]\n"
        "|  | 收入合计 |\n"
        "| --- | --- |\n"
        "| 本期 | 3,600 |\n"
        "| 上期 | 3,600 |\n"
        "[[/table:tbl-1]]"
    )
    result = await _validate_tables(tmp_path, f"# 报告\n\n{broken}\n")
    assert result["tableSummary"] == {
        "valid": 0, "stale": 2, "unbound": 0, "insertedRows": 0, "copiedCells": 0,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_validate_tables_hint_copied_cells_with_frozen_binding_candidates(
    tmp_path: Path,
) -> None:
    duplicated = _table_markdown([["本期", "3,600"], ["本期", "3,600"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path / "duplicated", f"# 报告\n\n{duplicated}\n")
    assert result["tableSummary"] == {
        "valid": 2, "stale": 0, "unbound": 0, "insertedRows": 0, "copiedCells": 1,
    }
    hints = result["tables"][0]["copiedCells"]
    assert len(hints) == 1
    assert hints[0]["rowLabel"] == "本期"
    assert hints[0]["columnKey"] == "income_total"
    assert hints[0]["text"] == "3,600"
    assert {match["rowKey"] for match in hints[0]["matches"]} == {"row:cur", "row:prev"}
    assert {match["factKey"] for match in hints[0]["matches"]} == {"fact-" + "a" * 16}
    assert all(match["columnKey"] == "income_total" for match in hints[0]["matches"])

    # 复制行但值被改：无候选提示，原映射行不受影响。
    edited_copy = _table_markdown([["本期", "3,600"], ["本期", "9,999"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path / "edited-copy", f"# 报告\n\n{edited_copy}\n")
    assert result["tableSummary"] == {
        "valid": 2, "stale": 0, "unbound": 0, "insertedRows": 0, "copiedCells": 0,
    }

    # 新标签行复制了冻结值：计 insertedRows 并给出候选提示。
    inserted_copy = _table_markdown([["本期", "3,600"], ["上期", "3,600"], ["副本", "3,600"]])
    result = await _validate_tables(tmp_path / "inserted-copy", f"# 报告\n\n{inserted_copy}\n")
    assert result["tableSummary"]["insertedRows"] == 1
    assert result["tableSummary"]["copiedCells"] == 1
    assert result["tables"][0]["copiedCells"][0]["rowLabel"] == "副本"


def test_frozen_amount_anchor_survives_long_block_and_checks_unit_conversion() -> None:
    from smart_reporting.reporting.trace.subject_builder import anchor_claims

    body = '收入为111.24亿元。\n\n' + '数据说明。' * 100
    anchored = anchor_claims(body, {'claim_001': (11123541503, '元')})
    assert '111.24亿元[[claim:claim_001]]。' in anchored
    assert claim_status(anchored, 'claim_001', 11123541503, expected_unit='元')['status'] == 'valid'
    assert claim_status(anchored.replace('111.24亿元', '111.25亿元'), 'claim_001', 11123541503, expected_unit='元')['status'] == 'stale'
    missing = anchor_claims('无数值。', {'claim_001': (11123541503, '元')})
    assert claim_status(missing, 'claim_001', 11123541503, expected_unit='元')['status'] == 'stale'


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_comparison_table_validates_each_frozen_field(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path, comparison_table=True)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    markdown = render_table_markdown("tbl-1", ("数值",), [["本期", "3,600元"], ["同期", "3,000元"], ["变化", "600元"], ["同比", "20%"]])
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["tableSummary"]["valid"] == 4
    changed = markdown.replace("3,000元", "3,001元")
    result = await editor.trace_validate(context, session, changed, hashlib.sha256(changed.encode()).hexdigest())
    assert result["tableSummary"]["valid"] == 3
    assert result["tableSummary"]["stale"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(("text", "valid", "stale"), [("—", 4, 0), ("0%", 3, 1), ("20%", 3, 1)])
async def test_comparison_null_rate_placeholder_is_valid_but_numbers_are_stale(
    tmp_path: Path, text: str, valid: int, stale: int,
) -> None:
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, comparison_table=True, comparison_rate=None,
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    markdown = render_table_markdown("tbl-1", ("数值",), [
        ["本期", "3,600元"], ["同期", "3,000元"], ["变化", "600元"], ["同比", text],
    ])
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["tableSummary"]["valid"] == valid
    assert result["tableSummary"]["stale"] == stale


@pytest.mark.parametrize(("entry", "periods", "within", "outside"), [
    ({"periodStart": "2025-09", "periodEnd": "2025-09"}, ("2025-09",), "2025年9月", "2025年10月"),
    ({"periodStart": "2024-11", "periodEnd": "2025-02"},
     ("2024-11", "2024-12", "2025-01", "2025-02"), "2025年1月", "2025年3月"),
    ({"periodStart": "2024-02-28", "periodEnd": "2024-03-01"},
     ("2024-02-28", "2024-02-29", "2024-03-01"), "2024年2月29日", "2024年3月2日"),
    ({"periodGranularity": "month", "periodStart": "2025-01-01", "periodEnd": "2025-03-01"},
     ("2025-01", "2025-02", "2025-03"), "2025年2月", "2025年4月"),
])
def test_fact_period_windows_include_interior_buckets(entry, periods, within, outside):
    from smart_reporting.reporting.trace.subject_builder import fact_periods, unit_period_warnings

    assert fact_periods(entry) == periods
    assert unit_period_warnings(within, expected_periods=fact_periods(entry)) == []
    assert unit_period_warnings(outside, expected_periods=fact_periods(entry))


def test_fact_period_windows_keep_explicit_buckets_and_unknown_periods():
    from smart_reporting.reporting.trace.subject_builder import fact_periods

    assert fact_periods({}) == ()
    assert fact_periods({"periodStart": "2025-09", "periodEnd": None}) == ()
    assert fact_periods({"periodStart": "2025-10", "periodEnd": "2025-09"}) == ()
    assert fact_periods({"periodStart": "2025-13", "periodEnd": "2025-14"}) == ()
    assert fact_periods({"periodStart": "2024", "periodEnd": "2026"}) == ("2024", "2025", "2026")
    assert fact_periods({"periodStart": "2025-01", "periodEnd": "2025-03", "periodValues": [
        {"period": "2025-01", "value": 100}, {"period": "2025-03", "value": 200}]}) == ("2025-01", "2025-03")
    assert fact_periods({"periodStart": "2025-09-01", "periodEnd": "2025-09-01"}) == ("2025-09",)


def test_month_bucket_dates_do_not_warn_on_same_month_prose():
    from smart_reporting.reporting.trace.subject_builder import fact_periods, unit_period_warnings

    entry = {"periodGranularity": "month", "periodValues": [
        {"period": "2025-01-01", "value": 10}, {"period": "2025-09-01", "value": 20}]}
    periods = fact_periods(entry)
    assert periods == ("2025-01", "2025-09")
    assert unit_period_warnings("2025年1–9月成本为30元", expected_periods=periods) == []
    assert unit_period_warnings("2024年1月成本为30元", expected_periods=periods)
    assert fact_periods({**entry, "periodGranularity": "day"}) == ("2025-01-01", "2025-09-01")
    assert unit_period_warnings("2025年1月", expected_periods=fact_periods({**entry, "periodGranularity": "day"}))


def test_numeric_claim_bindings_only_use_values_present_in_the_local_block():
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.trace.subject_builder import bind_local_claim_values
    from smart_reporting.reporting.workflow.checkpoint import SectionArtifact, SectionClaim

    fact_id = "fact-" + "a" * 16
    claim = SectionClaim(claimId="claim_1", metricCode="income", value=3600, periodBasis="本期",
        managementQuestion="收入趋势", currentPeriod="2025-09", citationIds=("citation_001",), factIds=(fact_id,))
    artifact = SectionArtifact(sectionCode="section_001", claims=(claim,), blocks=(
        ReportDraftBlock(blockId="block_1", markdown="各月收入先升后降，原因待核实。", claimIds=("claim_1",), citationIds=("citation_001",)),))
    normalized = bind_local_claim_values((artifact,), {fact_id: (3600, "元")})[0]
    assert normalized.claims[0].fact_ids == ()
    assert normalized.blocks[0].citation_ids == ("citation_001",)
    SectionArtifact.model_validate(normalized.model_dump())
    total_block = artifact.blocks[0].model_copy(update={"markdown": "本期收入为3,600元。"})
    local = bind_local_claim_values((artifact.model_copy(update={"blocks": (total_block,)}),), {fact_id: (3600, "元")})[0]
    assert local.claims[0].fact_ids == (fact_id,)
    assert artifact.claims[0].fact_ids == (fact_id,)


def test_bed_day_claim_unit_is_not_truncated_to_beds():
    from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

    assert unit_period_warnings("累计1,501,876床日。", expected_unit="床日", fact_value=1501876) == []
    assert unit_period_warnings("累计1,501,876床。", expected_unit="床日", fact_value=1501876)
    detail = claim_status("累计1,501,876[[claim:claim_1]]床日。", "claim_1", 1501876, expected_unit="床日")
    assert detail['status'] == 'valid'
    assert detail['warnings'] == []


@pytest.mark.parametrize("markdown", [
    "上期收入3600万元。本期收入3800万元[[claim:claim-1]]。",
    "本期收入3800万元[[claim:claim-1]]。上期收入3600万元。",
    "上期收入3600万元。本期收入3800万元。[[claim:claim-1]]",
])
def test_claim_does_not_borrow_value_from_neighboring_sentence(markdown):
    assert claim_status(markdown, "claim-1", 3600, expected_unit="万元")["status"] == "stale"


@pytest.mark.parametrize("text,warning", [
    ("2025-09华东收入3600万元", False),
    ("2025-09华西收入3600万元", True),
    ("2025-09收入3600万元", True),
    ("华东另有收入。2025-09华西收入3600万元", True),
])
def test_claim_registered_scope_requires_soft_review_when_absent(text, warning):
    result = claim_status(
        text + "[[claim:claim-1]]", "claim-1", 3600,
        expected_unit="万元", expected_periods=("2025-09",),
        expected_scope={"region": "华东"},
    )
    assert result["status"] == "valid"
    assert bool(result["warnings"]) is warning
    if warning:
        assert "范围" in result["warnings"][0] and "华东" in result["warnings"][0]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_correlation_claim_generated_binding_validates(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, correlation_claim=True)
    index = await editor.trace.load_index(context)
    assert index.subject_bindings[0].fact_refs[0].fact_kind == "correlation"
    markdown = "相关系数0.8[[claim:claim-1]]"
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"] == {"valid": 1, "stale": 0, "unbound": 0}
    assert result["subjects"][0]["factValue"] == 0.8


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("current,rate,valid,stale", [
    ("0.36万元", "20%", 4, 0),
    ("0.37万元", "20%", 3, 1),
    ("0.36万元", "0.002万元", 3, 1),
    ("3600万元", "20元", 2, 2),
    ("3600元", "20%", 4, 0),
])
async def test_table_unit_conversion_uses_each_fields_unit(tmp_path, current, rate, valid, stale):
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    editor, _, context = await _make_editor_with_subject(tmp_path, comparison_table=True)
    markdown = render_table_markdown("tbl-1", ("数值",), [
        ["本期", current], ["同期", "0.30万元"], ["变化", "0.06万元"], ["同比", rate],
    ])
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["tableSummary"]["valid"] == valid
    assert result["tableSummary"]["stale"] == stale


@pytest.mark.parametrize("sign", ["−", "－"])
@pytest.mark.parametrize("value,unit,text", [(0.8, None, "0.8"), (3600, "元", "0.36万元")])
def test_unicode_negative_does_not_match_positive_fact(sign, value, unit, text):
    result = claim_status(f"数值{sign}{text}[[claim:c]]", "c", value, expected_unit=unit)
    assert result["status"] == "stale"
    assert result["warnings"]


@pytest.mark.parametrize("sign", ["−", "－"])
@pytest.mark.parametrize("value,unit,text", [(-0.8, None, "0.8"), (-3600, "元", "0.36万元")])
def test_unicode_negative_matches_negative_fact(sign, value, unit, text):
    result = claim_status(f"数值{sign}{text}[[claim:c]]", "c", value, expected_unit=unit)
    assert result["status"] == "valid"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("wrapper", ["```markdown\n{}\n```", "~~~~\n{}\n~~~~", "<!--\n{}\n-->"])
@pytest.mark.parametrize("keep_visible", [False, True])
async def test_trace_ignores_hidden_markers(tmp_path, wrapper, keep_visible):
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    editor, _, context = await _make_editor_with_subject(tmp_path, comparison_table=True)
    body = "收入3600元[[claim:claim-1]]\n\n" + render_table_markdown(
        "tbl-1", ("数值",), [["本期", "3600元"], ["同期", "3000元"], ["变化", "600元"], ["同比", "20%"]],
    )
    markdown = (body + "\n\n" if keep_visible else "") + wrapper.format(body)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"] == {"valid": int(keep_visible), "stale": 0, "unbound": int(not keep_visible)}
    assert result["tableSummary"]["valid"] == (4 if keep_visible else 0)
    assert result["tableSummary"]["unbound"] == (0 if keep_visible else 4)
    assert len(result["tables"][0]["locations"]) == (4 if keep_visible else 0)


@pytest.mark.parametrize("hidden", [
    "`3600[[claim:c]]`", "``3600[[claim:c]]``", "    3600[[claim:c]]",
    "<!-- 3600[[claim:c]] -->", "<!-- 3600[[claim:c]]",
])
def test_claim_ignores_non_body_marker(hidden):
    assert claim_status(hidden, "c", 3600)["status"] == "unbound"
    assert claim_status("收入3600[[claim:c]]\n\n" + hidden, "c", 3600)["status"] == "valid"


def test_inline_comment_literal_does_not_hide_table():
    from smart_reporting.reporting.trace.markdown_body import trace_body

    markdown = "注释语法 `<!--`。\n\n[[table:tbl-1]]\n| 指标 |\n"
    assert trace_body(markdown, mask_inline_code=False) == markdown
    assert "[[table:tbl-1]]" in trace_body(markdown)


@pytest.mark.parametrize(("text", "matched"), [
    ("收入同比下降5.20%。", True),
    ("门诊量减少了1,200人次。", True),
    ("收入下滑5.2%。", True),
    ("收入同比增长5.20%。", False),
    ("收入为5.20%。", False),
    ("收入同比下降-5.20%。", True),
])
def test_negative_frozen_values_match_decline_magnitudes(text, matched):
    from smart_reporting.reporting.trace.subject_builder import (
        anchor_claims,
        formatted_value_matches,
        value_matches,
    )

    # 负的冻结值按“下降/减少… + 正幅度”书写是推荐写法，绑定与锚定都必须识别。
    rate_matched = value_matches(text, -5.2) or formatted_value_matches(text, -5.2, "%")
    count_matched = value_matches(text, -1200)
    assert (rate_matched or count_matched) is matched
    if matched and "%" in text:
        # 锚点紧跟数值（可位于数字与单位之间，渲染不可见）；未命中时才会追加到段尾。
        anchored = anchor_claims(text, {"claim_1": (-5.2, "%")})
        assert "[[claim:claim_1]]" in anchored and not anchored.endswith("[[claim:claim_1]]")


def test_visit_count_claims_bind_when_written_in_wan_visits() -> None:
    """人次事实写成万人次时仍按相同舍入核对并锚定，不能丢失数值绑定。"""
    from smart_reporting.reporting.trace.subject_builder import (
        anchor_claims,
        formatted_value_matches,
    )

    assert formatted_value_matches("门诊量123.46万人次。", 1234567, "人次")
    assert formatted_value_matches("门诊量1,234,567人次。", 1234567, "人次")
    assert not formatted_value_matches("门诊量123.47万人次。", 1234567, "人次")
    assert anchor_claims("门诊量123.46万人次，同比增长。", {"claim-1": (1234567, "人次")}) == (
        "门诊量123.46万人次[[claim:claim-1]]，同比增长。"
    )


def test_claim_anchor_never_lands_inside_a_date() -> None:
    """“2025年12月”中紧跟“月”的数字是日期，不能被当成事实值把锚点插进日期中间。"""
    from smart_reporting.reporting.trace.subject_builder import anchor_claims, value_matches

    assert anchor_claims("2025年12月开放床位数为12。", {"claim-1": (12, "张")}) == (
        "2025年12月开放床位数为12[[claim:claim-1]]。"
    )
    assert not value_matches("2025年12月", 12)
    # 平均住院日、“本月”后的数值仍正常匹配。
    assert value_matches("平均住院日8.5日。", 8.5)
    assert value_matches("本月35.3万人次。", 35.3)


def test_negative_fact_binds_through_decline_synonyms() -> None:
    from smart_reporting.reporting.trace.subject_builder import (
        formatted_value_matches,
        value_matches,
    )

    assert formatted_value_matches("收入跌幅5.03%。", -5.0332, "%")
    assert value_matches("门诊量下跌120人次。", -120)
    assert not formatted_value_matches("收入涨幅5.03%。", -5.0332, "%")


@pytest.mark.anyio
async def test_exact_number_reference_validates_month_and_detects_changed_subject(tmp_path):
    editor, grants, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    from hashlib import sha256

    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint

    claim_id = "number-" + sha256(b"section_002:block:2").hexdigest()[:20]
    # 原文的来源复核先登记，因此数值引用使用序号 2。
    markdown = next(tmp_path.rglob("report.md")).read_text()
    assert statement_fingerprint(markdown, claim_id)
    result = await editor.trace_validate(context, session, markdown, sha256(markdown.encode()).hexdigest())
    assert result['subjects'][0]['factValue'] == 2400
    assert result['subjects'][0]['periods'] == ['2025-10']
    assert result['subjects'][0]['status'] == 'valid'
    assert {item['kind'] for item in result['reviewNotices']} == {'source_review', 'numeric_unverified'}
    assert next(item for item in result['reviewNotices'] if item['kind'] == 'numeric_unverified')['originalText'] == '999999元'
    assert next(item for item in result['reviewNotices'] if item['kind'] == 'source_review')['originalText'] is None
    assert all(item['occurrences'] == 1 and item['bound'] for item in result['reviewNotices'])
    for variant, occurrences, bound in ((markdown + markdown, 2, False), (f'<!--{markdown}-->', 0, False),
                                        (markdown.replace('待核实[[', '**待核实**[['), 1, True)):
        checked = await editor.trace_validate(context, session, variant, sha256(variant.encode()).hexdigest())
        assert all(item['occurrences'] == occurrences and item['bound'] is bound for item in checked['reviewNotices'])
    changed = markdown.replace('收入', '成本')
    result = await editor.trace_validate(context, session, changed, sha256(changed.encode()).hexdigest())
    assert result['subjects'][0]['status'] == 'stale'
    assert result['subjects'][0]['comparable'] is False


@pytest.mark.anyio
@pytest.mark.parametrize(('selector', 'statement', 'warns'), [
    ('periodTotals.0-1:万元', '截至2025年9月累计收入', True),
    ('periodTotals.0-1:万元', '截至2025年10月，含2025年9月的累计收入', False),
    ('periodChanges.1:万元', '2025年9月增加', True),
    ('periodChanges.1:万元', '2025年10月较2025年9月增加', False),
    ('periodChangeRates.1:%', '2025年9月增长', True),
    ('periodChangeRates.1:%', '以2025年9月为基期，2025年10月增长', False),
])
async def test_editor_number_reference_checks_period_roles_without_blocking(tmp_path, selector, statement, warns):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True,
        number_statement=statement + '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}。',
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result['subjects'][0]
    assert subject['periods'] == ['2025-09', '2025-10']
    assert subject['status'] == 'valid'
    assert bool(subject['warnings']) is warns
    if warns:
        assert '期间角色' in subject['warnings'][0]


@pytest.mark.parametrize(('value', 'text', 'supported'), [
    (1.005, '1.00床日', False),
    (1.005, '1.01床日', True),
    (2.675, '2.67床日', False),
    (2.675, '2.68床日', True),
    (-1.005, '-1.00床日', False),
    (-1.005, '-1.01床日', True),
    (-2.675, '减少2.67床日', False),
    (-2.675, '减少2.68床日', True),
])
def test_trace_value_rounding_matches_frozen_decimal_rule(value, text, supported):
    from smart_reporting.reporting.trace.subject_builder import claim_status, value_matches

    assert value_matches(text, value) is supported
    result = claim_status(text + '[[claim:rounding]]。', 'rounding', value, expected_unit='床日')
    assert (result['status'] == 'valid') is supported


@pytest.mark.parametrize(('text', 'value', 'supported'), [
    ('2025年收入尚待核实', 2025, False),
    ('2025-09-12收入尚待核实', 2025, False),
    ('2025/09/12收入尚待核实', 12, False),
    ('2025年9月12日收入尚待核实', 12, False),
    ('9月12日收入尚待核实', 12, False),
    ('平均住院8.5日', 8.5, True),
    ('本月收入2025.09元', 2025.09, True),
    ('2025年床位为2025张', 2025, True),
])
def test_calendar_numbers_are_not_fact_values(text, value, supported):
    from smart_reporting.reporting.trace.subject_builder import claim_status, value_matches

    assert value_matches(text, value) is supported
    assert (claim_status(text + '[[claim:calendar]]。', 'calendar', value)['status'] == 'valid') is supported


def test_claim_anchor_skips_calendar_year_when_value_repeats():
    from smart_reporting.reporting.trace.subject_builder import anchor_claims

    assert anchor_claims('2025年床位为2025张。', {'calendar': (2025, '张')}) == (
        '2025年床位为2025[[claim:calendar]]张。'
    )
