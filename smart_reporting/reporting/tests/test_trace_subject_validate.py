"""B6 正文 subject 绑定与校验测试（计划 6.1）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import (
    FactRefV1,
    SubjectBindingV1,
    TableCellBindingV1,
    TableTraceV1,
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

    ambiguous = claim_status(
        "2025-09收入3,780万元，2025-08收入3,500万元[[claim:claim-1]]",
        "claim-1",
        3600,
        expected_unit="万元",
        expected_periods=("2025-09",),
    )
    assert ambiguous["status"] == "stale"
    assert "draftValue" not in ambiguous


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


# ---------------------------------------------------------------------------
# Editor validate 端到端（索引 + [[claim:]] 标记）
# ---------------------------------------------------------------------------


async def _make_editor_with_subject(
    tmp_path: Path,
    *, report_id: str = "report-1",
) -> tuple:
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
        "tbl-1", ("income_total",), [["本期", "3,600"], ["上期", "3,600"]]
    )
    markdown = f"# 报告\n\n{table_block}\n"
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
                    "scope": {},
                    "total": 3600.0,
                    "unit": "万元",
                    "periodValues": [{"period": "2025-09", "value": 3600.0}],
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
    table_fact_ref = FactRefV1(
        analysisId="analysis_001",
        fileResourceId=derive_resource_id(fact_path),
        jsonPointer="/metrics/0",
        factKind="metric",
        factKey="fact-" + "a" * 16,
    )
    table_trace = TableTraceV1(
        tableId="tbl-1",
        rowKeys=("row:cur", "row:prev"),
        columnKeys=("income_total",),
        cells=(
            TableCellBindingV1(rowKey="row:cur", columnKey="income_total", factRefs=(table_fact_ref,)),
            TableCellBindingV1(rowKey="row:prev", columnKey="income_total", factRefs=(table_fact_ref,)),
        ),
    )
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
        server_table_traces=(table_trace,),
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
async def test_validate_returns_conservative_comparable_draft_value(tmp_path: Path) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = "2025-09收入3780万元[[claim:claim-1]]"
    result = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    subject = result["subjects"][0]
    assert subject["status"] == "stale"
    assert subject["comparable"] is True
    assert subject["draftValue"] == 3780
    assert subject["draftUnit"] == "万元"
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
             "columnIndex": 1, "rowLabel": "本期", "text": "3,600"},
            {"rowKey": "row:prev", "columnKey": "income_total", "rowIndex": 0,
             "columnIndex": 1, "rowLabel": "上期", "text": "3,600"},
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
async def test_table_locations_follow_current_rows_without_guessing_duplicates(tmp_path: Path) -> None:
    sorted_table = _table_markdown([["上期", "9,999"], ["本期", "3,600"]])
    result = await _validate_tables(tmp_path / "sorted", f"# 报告\n\n{sorted_table}\n")
    assert result["tables"][0]["locations"] == [
        {"rowKey": "row:cur", "columnKey": "income_total", "rowIndex": 1,
         "columnIndex": 1, "rowLabel": "本期", "text": "3,600"},
        {"rowKey": "row:prev", "columnKey": "income_total", "rowIndex": 0,
         "columnIndex": 1, "rowLabel": "上期", "text": "9,999"},
    ]
    duplicated = _table_markdown([["本期", "3,600"], ["本期", "3,600"], ["上期", "3,600"]])
    result = await _validate_tables(tmp_path / "duplicate", f"# 报告\n\n{duplicated}\n")
    assert [item["rowKey"] for item in result["tables"][0]["locations"]] == ["row:prev"]
    result = await _validate_tables(tmp_path / "blocks", f"# 报告\n\n{sorted_table}\n\n{sorted_table}\n")
    assert result["tables"][0]["locations"] == []
    removed = _table_markdown([["本期", "3,600"]])
    result = await _validate_tables(tmp_path / "removed-location", f"# 报告\n\n{removed}\n")
    assert [item["rowKey"] for item in result["tables"][0]["locations"]] == ["row:cur"]
    renamed_column = sorted_table.replace("income_total", "renamed")
    result = await _validate_tables(tmp_path / "renamed-column-location", renamed_column)
    assert result["tables"][0]["locations"] == []
    duplicate_column = sorted_table.replace("| income_total |", "| income_total | income_total |")
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
