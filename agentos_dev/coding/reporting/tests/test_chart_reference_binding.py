from types import SimpleNamespace

import pytest
from agno.run import RunContext

from agentos_dev import app
from agentos_dev.coding.reporting.delivery.draft_v1 import ReportSectionDefinition
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import (
    REPORT_CHART_STATE_KEY,
    REPORT_DRAFT_STATE_KEY,
    build_report_worker_tools,
)


@pytest.mark.anyio
async def test_finalize前要求正文引用全部已登记图表(monkeypatch, tmp_path):
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 1,
                "charts": {
                    chart_id: {
                        "chartId": chart_id,
                        "sourcePath": f"analysis/charts/{chart_id}.png",
                        "title": chart_id,
                        "altText": chart_id,
                        "citationIds": ["citation_001"],
                        "size": 1024,
                        "sha256": "a" * 64,
                        "extension": ".png",
                    }
                    for chart_id in (
                        "budget_exec_cum",
                        "exp_budget_monthly",
                        "income_outpatient_yoy",
                    )
                },
            }
        },
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def scope(_run_context):
        return SimpleNamespace(
            attempt_no=1,
            thread_id="thread",
            task=SimpleNamespace(mutation_sequence=0),
        )

    async def render_contract(_scope):
        return (
            "运营报告",
            "reports/report.md",
            (
                ReportSectionDefinition(code="budget", title="预算执行"),
                ReportSectionDefinition(code="income", title="收入联动"),
            ),
            ("citation_001",),
            False,
        )

    monkeypatch.setattr(toolkit.kernel, "scope", scope)
    monkeypatch.setattr(toolkit, "_render_contract", render_contract)

    await toolkit.begin_report_draft(context)
    await toolkit.render_report_section(
        "budget",
        [
            {
                "blockId": "budget",
                "markdown": "预算执行分析。",
                "citationIds": ["citation_001"],
            }
        ],
        context,
    )
    completed = await toolkit.render_report_section(
        "income",
        [
            {
                "blockId": "income",
                "markdown": "收入联动分析。",
                "citationIds": ["citation_001"],
            }
        ],
        context,
    )

    assert completed["status"] == "awaiting_chart_references"
    assert completed["unreferencedChartIds"] == [
        "budget_exec_cum",
        "exp_budget_monthly",
        "income_outpatient_yoy",
    ]
    assert completed["requiredActions"] == [
        "计划发布图用同一 sectionCode 重提完整章节并补齐 chartIds；误登记且未被章节引用的"
        "预览图用 discard_report_charts 丢弃；处理完成后再调用 finalize_report_draft。"
    ]

    stored = context.session_state[REPORT_DRAFT_STATE_KEY]

    async def validate_and_store(*, scope, state, draft):
        del scope, state
        stored.update(
            {
                "submitted": True,
                "status": "validated",
                "draft": draft,
                "draftId": "draft-1",
            }
        )
        return None, "reports/report.md", (), (), stored

    async def batch_copy_files(copies, _run_context, *, _scope):
        return {
            "ok": True,
            "status": "completed",
            "files": [{"source": item["source"], "path": item["destination"]} for item in copies],
            "execution_id": "copy-1",
            "mutation_sequence": 1,
        }

    async def write_rendered_draft(**_kwargs):
        return {"ok": True, "execution_id": "write-1", "mutation_sequence": 2}

    monkeypatch.setattr(toolkit, "_validate_and_store_draft", validate_and_store)
    monkeypatch.setattr(toolkit.kernel, "batch_copy_files", batch_copy_files)
    monkeypatch.setattr(toolkit, "_write_rendered_draft", write_rendered_draft)

    needs_repair = await toolkit.finalize_report_draft(context)

    assert needs_repair["status"] == "awaiting_chart_references"
    assert needs_repair["unreferencedChartIds"] == completed["unreferencedChartIds"]
    assert "nextToolCall" not in needs_repair
    assert stored["submitted"] is True
    assert stored["status"] == "rendered"

    repaired = await toolkit.render_report_section(
        "income",
        [
            {
                "blockId": "income",
                "markdown": "收入联动与预算执行分析。",
                "citationIds": ["citation_001"],
                "chartIds": completed["unreferencedChartIds"],
            }
        ],
        context,
    )

    assert repaired["status"] == "replaced"
    assert "unreferencedChartIds" not in repaired
    assert stored["submitted"] is False
    assert stored["status"] == "sections_completed"

    finalized = await toolkit.finalize_report_draft(context)

    assert finalized["ok"] is True
    assert finalized["nextToolCall"]["name"] == "finish_task"


@pytest.mark.anyio
async def test_finalize前拒绝未覆盖服务端citation(monkeypatch, tmp_path):
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def scope(_run_context):
        return SimpleNamespace(
            attempt_no=1,
            thread_id="thread",
            task=SimpleNamespace(mutation_sequence=0),
        )

    async def render_contract(_scope):
        return (
            "运营报告",
            "reports/report.md",
            (
                ReportSectionDefinition(code="budget", title="预算执行"),
                ReportSectionDefinition(code="income", title="收入联动"),
            ),
            ("citation_001", "citation_002"),
            False,
        )

    monkeypatch.setattr(toolkit.kernel, "scope", scope)
    monkeypatch.setattr(toolkit, "_render_contract", render_contract)

    await toolkit.begin_report_draft(context)
    await toolkit.render_report_section(
        "budget",
        [{"blockId": "budget", "markdown": "预算执行分析。", "citationIds": ["citation_001"]}],
        context,
    )
    await toolkit.render_report_section(
        "income",
        [{"blockId": "income", "markdown": "收入联动分析。", "citationIds": ["citation_001"]}],
        context,
    )

    result = await toolkit.finalize_report_draft(context)

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "report_draft_citation_missing"
    assert "citation_002" in result["message"]
    assert context.session_state[REPORT_DRAFT_STATE_KEY]["submitted"] is not True


@pytest.mark.anyio
async def test_finalize将超过单批上限的图表分批归档(monkeypatch, tmp_path):
    chart_ids = [f"chart_{index:03d}" for index in range(21)]
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 1,
                "charts": {
                    chart_id: {
                        "chartId": chart_id,
                        "sourcePath": f"analysis/charts/{chart_id}.png",
                        "title": chart_id,
                        "altText": chart_id,
                        "citationIds": ["citation_001"],
                        "size": 1024,
                        "sha256": "a" * 64,
                        "extension": ".png",
                    }
                    for chart_id in chart_ids
                },
            }
        },
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]
    scope = SimpleNamespace(
        attempt_no=1,
        thread_id="thread",
        task=SimpleNamespace(mutation_sequence=0),
    )

    async def resolve_scope(_run_context):
        return scope

    async def render_contract(_scope):
        return (
            "运营报告",
            "reports/report.md",
            (ReportSectionDefinition(code="summary", title="运营总览"),),
            ("citation_001",),
            False,
        )

    copied_batches = []

    async def batch_copy_files(copies, _run_context, *, _scope):
        copied_batches.append(list(copies))
        return {
            "ok": True,
            "status": "completed",
            "files": [{"source": item["source"], "path": item["destination"]} for item in copies],
            "execution_id": f"copy-{len(copied_batches)}",
            "mutation_sequence": len(copied_batches),
        }

    async def write_rendered_draft(**_kwargs):
        return {"ok": True, "execution_id": "write-1", "mutation_sequence": 3}

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit, "_render_contract", render_contract)
    monkeypatch.setattr(toolkit.kernel, "batch_copy_files", batch_copy_files)
    monkeypatch.setattr(toolkit, "_write_rendered_draft", write_rendered_draft)

    await toolkit.begin_report_draft(context)
    section = await toolkit.render_report_section(
        "summary",
        [
            {
                "blockId": "overview",
                "markdown": "运营总览。",
                "citationIds": ["citation_001"],
                "chartIds": chart_ids,
            }
        ],
        context,
    )
    finalized = await toolkit.finalize_report_draft(context)

    assert section["status"] == "accepted"
    assert [len(batch) for batch in copied_batches] == [20, 1]
    assert len(finalized["archiveReceipts"]) == 21
    assert len(finalized["nextToolCall"]["arguments"]["artifact_paths"]) == 22


@pytest.mark.anyio
async def test_已登记图表允许校正元数据但保持文件身份不可变(monkeypatch, tmp_path):
    original_path = "analysis/charts/income.png"
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 1,
                "charts": {
                    "income": {
                        "chartId": "income",
                        "sourcePath": original_path,
                        "title": "收入趋势",
                        "altText": "收入趋势",
                        "citationIds": ["citation_001"],
                        "size": 1024,
                        "sha256": "a" * 64,
                        "format": "PNG",
                        "mediaType": "image/png",
                        "extension": ".png",
                        "width": 1200,
                        "height": 675,
                    }
                },
            }
        },
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def resolve_scope(_run_context):
        return SimpleNamespace(
            attempt_no=1,
            thread_id="thread",
            task=SimpleNamespace(mutation_sequence=0),
        )

    async def render_contract(_scope):
        return (
            "运营报告",
            "reports/report.md",
            (ReportSectionDefinition(code="summary", title="运营总览"),),
            ("citation_001", "citation_002"),
            False,
        )

    async def inspect_chart(*, thread_id, registration):
        del thread_id
        return (
            {
                **registration.model_dump(mode="json", by_alias=True),
                "size": 1024,
                "sha256": "a" * 64,
                "format": "PNG",
                "mediaType": "image/png",
                "extension": ".png",
                "width": 1200,
                "height": 675,
            },
            [],
        )

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    monkeypatch.setattr(toolkit, "_render_contract", render_contract)
    monkeypatch.setattr(toolkit, "_inspect_chart", inspect_chart)

    corrected = await toolkit.register_report_charts(
        [
            {
                "chartId": "income",
                "sourcePath": original_path,
                "title": "收入月度趋势",
                "altText": "医疗收入月度趋势",
                "citationIds": ["citation_002"],
            }
        ],
        context,
    )
    changed_source = await toolkit.register_report_charts(
        [
            {
                "chartId": "income",
                "sourcePath": "analysis/charts/other.png",
                "title": "收入月度趋势",
                "altText": "医疗收入月度趋势",
                "citationIds": ["citation_002"],
            }
        ],
        context,
    )

    registry = context.session_state[REPORT_CHART_STATE_KEY]["charts"]
    assert corrected["ok"] is True
    assert registry["income"]["title"] == "收入月度趋势"
    assert registry["income"]["citationIds"] == ["citation_002"]
    assert len(registry) == 1
    assert changed_source["code"] == "report_chart_registration_conflict"


@pytest.mark.anyio
async def test_finalize前可丢弃未被章节引用的误登记图表(monkeypatch, tmp_path):
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 1,
                "charts": {
                    chart_id: {
                        "chartId": chart_id,
                        "sourcePath": f"analysis/charts/{chart_id}.png",
                        "title": chart_id,
                        "altText": chart_id,
                        "citationIds": ["citation_001"],
                        "size": 1024,
                        "sha256": "a" * 64,
                        "extension": ".png",
                    }
                    for chart_id in ("preview", "final")
                },
            },
            REPORT_DRAFT_STATE_KEY: {
                "attemptNo": 1,
                "started": True,
                "status": "collecting",
                "submitted": False,
                "sections": [
                    {
                        "sectionCode": "summary",
                        "blocks": [
                            {
                                "blockId": "overview",
                                "markdown": "运营总览。",
                                "chartIds": ["final"],
                            }
                        ],
                    }
                ],
            },
        },
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def resolve_scope(_run_context):
        return SimpleNamespace(
            attempt_no=1,
            thread_id="thread",
            task=SimpleNamespace(mutation_sequence=0),
        )

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)

    discarded = await toolkit.discard_report_charts(["preview"], context)

    assert discarded == {
        "ok": True,
        "status": "discarded",
        "chartIds": ["preview"],
    }
    assert set(context.session_state[REPORT_CHART_STATE_KEY]["charts"]) == {"final"}

    rejected = await toolkit.discard_report_charts(["final"], context)
    assert rejected["code"] == "report_chart_discard_referenced"
    assert set(context.session_state[REPORT_CHART_STATE_KEY]["charts"]) == {"final"}


@pytest.mark.anyio
async def test_discard_report_charts在草稿冻结后拒绝(monkeypatch, tmp_path):
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            REPORT_CHART_STATE_KEY: {
                "attemptNo": 1,
                "charts": {
                    "preview": {
                        "chartId": "preview",
                        "sourcePath": "analysis/charts/preview.png",
                        "title": "preview",
                        "altText": "preview",
                        "citationIds": ["citation_001"],
                        "size": 1024,
                        "sha256": "a" * 64,
                        "extension": ".png",
                    }
                },
            },
            REPORT_DRAFT_STATE_KEY: {
                "attemptNo": 1,
                "started": True,
                "submitted": True,
                "status": "rendered",
                "sections": [],
            },
        },
    )
    toolkit = build_report_worker_tools(
        service(tmp_path),
        app.coding_repository,
        run_context=context,
    )[0]

    async def resolve_scope(_run_context):
        return SimpleNamespace(
            attempt_no=1,
            thread_id="thread",
            task=SimpleNamespace(mutation_sequence=0),
        )

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)

    rejected = await toolkit.discard_report_charts(["preview"], context)

    assert rejected["code"] == "report_chart_discard_after_finalize"
    assert rejected["retryable"] is False
