from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.table_ai import (
    TableAIEditRequest,
    TableAIEditService,
    TableEditMetricsColumn,
    TableEditMetricsSpec,
    TableEditPeriodRow,
    _fact_catalog,
    _table_body_for_id,
    _table_caption,
    _validate_and_render,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.table_builder import build_group_edit_table

from .test_dimension_breakdowns import _bundle, _groups


def test_metrics_edit_renders_registered_fact_without_dataset_context() -> None:
    bundle = _bundle()
    fact = bundle.metrics[0]
    period = fact.period_values[0].period
    rendered = _validate_and_render(
        bundle,
        TableEditMetricsSpec(
            columns=(TableEditMetricsColumn(factId=fact.fact_id),),
            rows=(TableEditPeriodRow(key=f"period:{period}", label=period, period=period),),
        ),
        table_id="table-edited",
        fact_file_resource_id="trf-11111111111111111111",
    )

    assert "[[table:table-edited]]" in rendered.markdown
    assert rendered.trace.cells[0].fact_refs[0].fact_key == fact.fact_id
    assert _fact_catalog(bundle, rendered.trace)["metrics"][0]["label"]


def test_group_edit_caption_uses_dimension_label_instead_of_first_group_value() -> None:
    bundle = _bundle()
    parent = bundle.metrics[0]
    groups = tuple(_groups(bundle, "department").values())

    _trace, markdown = build_group_edit_table(
        bundle,
        parent,
        groups,
        table_id="table-groups",
        caption=None,
        share=True,
        fact_file_resource_id="trf-11111111111111111111",
    )

    assert "按科室构成\n\n[[table:table-groups]]" in markdown
    assert "按A构成" not in markdown


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_multi_analysis_table_is_rejected_deterministically(
    anyio_backend: str,
) -> None:
    refs = (
        SimpleNamespace(analysis_id="analysis-a"),
        SimpleNamespace(analysis_id="analysis-b"),
    )
    table = SimpleNamespace(
        table_id="table-multi", cells=(SimpleNamespace(fact_refs=refs),)
    )
    editor = SimpleNamespace(
        trace=SimpleNamespace(
            load_manifest_and_index=lambda _context: _async_result(
                (SimpleNamespace(), SimpleNamespace(tables=(table,), fact_files=(), files=()))
            )
        )
    )
    service = TableAIEditService(editor=editor, planner=None)

    assert await service._resolve_table(SimpleNamespace(), "table-multi") == {
        "reason": "facts_ambiguous"
    }


def test_current_table_body_lookup_is_exact_across_multiple_blocks() -> None:
    markdown = (
        "[[table:first]]\n| A |\n| --- |\n| 1 |\n\n[[/table:first]]\n\n"
        "[[table:second]]\n| B |\n| --- |\n| 2 |\n\n[[/table:second]]"
    )

    assert _table_body_for_id(markdown, "second") == "| B |\n| --- |\n| 2 |"
    assert _table_body_for_id(markdown, "missing") is None


@pytest.mark.parametrize("prefix", [
    "[[/table:previous]]\n\n",
    "需要保留的正文第一行\n需要保留的正文第二行\n\n",
    "",
])
def test_table_without_caption_does_not_claim_previous_content(prefix: str) -> None:
    assert _table_caption(prefix + "[[table:target]]\n| A |", "target") is None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_edit_compares_expected_body_with_current_server_draft() -> None:
    current_body = "| A |\n| --- |\n| current |"
    submitted_body = "| A |\n| --- |\n| stale |"
    context = SimpleNamespace(
        report_id="report-1",
        revision=1,
        scope={"threadId": "thread-1", "userId": "user-1"},
    )

    class Editor:
        @asynccontextmanager
        async def _draft_lock(self, _context):
            yield

        async def _read_revision_markdown(self, _context):
            markdown = f"[[table:table-1]]\n{current_body}\n\n[[/table:table-1]]"
            return "draft/report.md", markdown, "0" * 64

    service = TableAIEditService(editor=Editor(), planner=lambda _request: None)

    async def resolved(_expected, _session, _table_id):
        return None, SimpleNamespace(
            context=context,
            original_table_id="table-1",
        )

    service._check = resolved  # type: ignore[method-assign]
    with pytest.raises(ReportingError) as failure:
        await service.start_edit(
            context,
            SimpleNamespace(capabilities=None),
            "table-1",
            TableAIEditRequest(
                instruction="更新",
                baseBody=submitted_body,
                expectedSha256=hashlib.sha256(submitted_body.encode()).hexdigest(),
            ),
        )
    assert failure.value.code == "report_editor_table_ai_base_changed"


async def _async_result(value: object) -> object:
    return value


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_table_edit_returns_current_target_caption_without_caption_in_trace(monkeypatch):
    bundle = _bundle()
    fact = bundle.metrics[0]
    period = fact.period_values[0].period
    rendered = _validate_and_render(
        bundle,
        TableEditMetricsSpec(
            columns=(TableEditMetricsColumn(factId=fact.fact_id),),
            rows=(TableEditPeriodRow(key=f"period:{period}", label=period, period=period),),
        ),
        table_id="table-current",
        fact_file_resource_id="trf-11111111111111111111",
    )
    body = _table_body_for_id(rendered.markdown, "table-current")
    context = SimpleNamespace(
        scope={"threadId": "thread-1", "userId": "user-1"}, markdown_path="draft/report.md",
    )
    # 旧报告冻结的 origin_markdown 只有协议表块，没有标题；当前草稿另含其他表。
    trace = rendered.trace.model_copy(update={"origin_markdown": f"[[table:table-current]]\n{body}\n\n[[/table:table-current]]"})

    class Editor:
        workspace = SimpleNamespace()

        @asynccontextmanager
        async def _draft_lock(self, _context):
            yield

        async def _read_revision_markdown(self, _context):
            markdown = (
                "其他表题\n\n[[table:other]]\n| A |\n| --- |\n| 1 |\n\n[[/table:other]]\n\n"
                f"当前收入表题\n\n[[table:table-current]]\n{body}\n\n[[/table:table-current]]"
            )
            return "draft/report.md", markdown, "0" * 64

    async def append_record(*_args):
        return None

    monkeypatch.setattr("smart_reporting.report_editor.table_ai.append_table_edit_record", append_record)
    service = TableAIEditService(editor=Editor(), planner=None)
    service._jobs["tedit-1234567890abcdef"] = SimpleNamespace(stage="queued")
    result = await service._run_edit(
        SimpleNamespace(context=context, bundle=bundle, trace=trace, analysis_id=bundle.analysis_id),
        "table-current", "tedit-1234567890abcdef",
        instruction="", template_id="composition", base_body=body, previous_edit_id=None,
        current_table_id="table-current", expected_body_sha256=hashlib.sha256(body.encode()).hexdigest(),
    )
    assert result["baseCaption"] == "当前收入表题"
