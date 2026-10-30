"""自动编号不改变语义证据，真实标题及正文改动仍需重新复核。"""

import hashlib

import pytest

from smart_reporting.reporting.delivery.draft_v1 import HeadingNumber
from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.claim_semantics import (
    freeze_interpretation,
    project_semantic_headings,
)
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
from smart_reporting.reporting.trace.index_builder import encode_trace_index


async def _editor_with_numbered_heading(tmp_path, title, *, metric_scope=None, visible_title=None):
    editor, _, context = await _make_editor_with_subject(
        tmp_path, period_table=True, include_table=False, number_reference=True,
        metric_scope={"院区": "北院"} if metric_scope is None else metric_scope,
        number_statement="2025年10月北院收入"
        "{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。",
    )
    index = await editor.trace.require_index(context)
    workspace = editor.trace._workspace
    thread = context.scope["threadId"]
    markdown_file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    original = f"### {title}\n\n" + (
        await editor.trace._read_registered_file(context, markdown_file, max_bytes=1 << 24)
    ).decode()
    binding = index.subject_bindings[0]
    receipt = freeze_interpretation(original, binding.claim_id, {
        "claimId": binding.claim_id,
        "scope": [{"field": "院区", "value": "北院", "status": "resolved", "evidence": ["北院收入"]}],
        "periods": ["2025-10"], "periodEvidence": ["2025年10月北院收入"],
    }, include_section=True)
    assert receipt is not None
    markdown = "[[section:section_002]]\n\n## 1. Report\n\n" + original.replace(
        f"### {title}", f"### 1.1 {title}", 1,
    )
    raw = markdown.encode()
    updated = index.model_copy(update={
        "files": tuple(file.model_copy(update={"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
                       if file.resource_id == markdown_file.resource_id else file for file in index.files),
        "subject_bindings": (binding.model_copy(update={
            "number_reference": binding.number_reference.model_copy(update={"semantic_receipt": receipt}),
        }), *index.subject_bindings[1:]),
    })
    await workspace.awrite_bytes(thread, markdown_file.path, raw, overwrite=True)
    await workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest_file = await register_trace_manifest(workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest_file})
    manifest = await editor.trace.load_manifest(context)
    manifest = manifest.model_copy(update={"heading_numbers": (*manifest.heading_numbers, HeadingNumber(
        level=3, number="1.1", title=title if visible_title is None else visible_title,
        sectionCode="section_002", anchor="report-heading-section_002-1-1",
    ))})
    raw_manifest = canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True))
    await workspace.awrite_bytes(thread, manifest_file.path, raw_manifest, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest_file.model_copy(update={
        "size": len(raw_manifest), "sha256": hashlib.sha256(raw_manifest).hexdigest(),
    })})
    return editor, context, markdown


@pytest.mark.anyio
@pytest.mark.parametrize("title", ["成本总额与同比变化", "床位规模", "月度变化", "1.5 万人次", "3 月收入", "收入概况"])
async def test_registered_heading_numbering_preserves_editor_and_quality_receipts(tmp_path, title):
    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, title)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result["subjects"][0]
    assert subject["semanticCheck"]["status"] == "interpreted"
    assert subject["warnings"] == []
    assert result["quality"]["status"] == "evaluated"
    assert result["quality"]["issues"] == []


@pytest.mark.anyio
@pytest.mark.parametrize(("title", "visible_title"), [
    ("成本**总额**与同比变化", "成本总额与同比变化"),
    ("月度`收入`变化", "月度收入变化"),
    ("床位[规模](https://example.com)", "床位规模"),
    ("成本 &amp; 收入", "成本 & 收入"),
])
async def test_styled_heading_numbering_uses_manifest_visible_title(tmp_path, title, visible_title):
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportSectionDefinition,
        _number_block_headings,
    )

    _, _, _, headings = _number_block_headings(
        f"### {title}", definition=ReportSectionDefinition(code="section_002", sectionNumber="1", title="Report"),
        h3_count=0, h4_count=0,
    )
    assert headings[0].title == visible_title
    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, title, visible_title=visible_title)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["subjects"][0]["semanticCheck"]["status"] == "interpreted"
    assert result["subjects"][0]["warnings"] == []
    assert result["quality"]["issues"] == []
    edited = markdown.replace(title, title + "（不含北院）", 1)
    changed = await editor.trace.validate(context, edited, hashlib.sha256(edited.encode()).hexdigest())
    assert changed["subjects"][0]["semanticCheck"]["status"] == "invalidated"
    assert changed["quality"]["issues"]


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["quantity_heading", "scope", "period", "number", "duplicate_claim"])
async def test_numbering_projection_never_accepts_real_semantic_edits(tmp_path, change):
    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, "1.5 万人次")
    claim = (await editor.trace.require_index(context)).subject_bindings[0].claim_id
    edited = {
        "quantity_heading": markdown.replace("1.5 万人次", "2.5 万人次"),
        "scope": markdown.replace("北院", "南院"),
        "period": markdown.replace("2025年10月", "2025年9月"),
        "number": markdown.replace("2,400", "2,500"),
        "duplicate_claim": markdown + f"\n\n北院收入2,400万元[[claim:{claim}]]。",
    }[change]
    assert edited != markdown
    result = await editor.trace.validate(context, edited, hashlib.sha256(edited.encode()).hexdigest())
    assert result["subjects"][0]["semanticCheck"]["status"] == "invalidated"
    assert result["quality"]["issues"]


@pytest.mark.anyio
async def test_numbering_projection_retains_unknown_statistical_scope(tmp_path):
    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, "成本", metric_scope={})
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["subjects"][0]["semanticCheck"]["status"] == "interpreted"
    assert any("scope_unknown" in issue["reasons"] for issue in result["quality"]["issues"])


def test_projection_only_removes_registered_number_from_real_headings():
    heading = HeadingNumber(level=3, number="1.1", title="1.5 万人次", sectionCode="section_002",
                            anchor="report-heading-section_002-1-1")
    markdown = ("### 1.1 1.5 万人次[[claim:c]]\n\n"
                "### 1.2 成本\n\n正文1.1 1.5 万人次。\n\n"
                "```markdown\n### 1.1 1.5 万人次\n```\n")
    projected = project_semantic_headings(markdown, (heading,))
    assert projected == ("### 1.5 万人次[[claim:c]]\n\n"
                         "### 1.2 成本\n\n正文1.1 1.5 万人次。\n\n"
                         "```markdown\n### 1.1 1.5 万人次\n```\n")
    assert project_semantic_headings(markdown, ()) == markdown


@pytest.mark.anyio
async def test_quality_projection_identity_includes_registered_heading_mapping(tmp_path):
    from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, "成本")
    manifest, index = await editor.trace.load_manifest_and_index(context)
    sources = {file.resource_id: await editor.trace._read_registered_file(context, file, max_bytes=1 << 24)
               for file in index.files if file.media_type == "application/json"}
    without_mapping = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    with_mapping = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64,
                                         heading_numbers=manifest.heading_numbers)
    assert without_mapping.input_sha256 != with_mapping.input_sha256
    assert any("statement_not_supported" in issue.reasons for issue in without_mapping.issues)
    assert not with_mapping.issues


@pytest.mark.anyio
async def test_publisher_persists_quality_with_authoritative_heading_projection(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.trace.quality_bundle import QualityBundle
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime, publication

    editor, context, markdown = await _editor_with_numbered_heading(tmp_path, "成本")
    manifest, index = await editor.trace.load_manifest_and_index(context)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = editor.trace._workspace
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=None))
    runtime._scope = lambda _context: context.scope
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash=index.profile_hash)
    state = {}
    runtime._state = lambda _context: state
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication, "build_csv_trace_index", lambda **_kwargs: index)
    identity = await runtime._write_trace_index(
        "reports/revision-1/report.manifest.json", handles=(), lineage=(), markdown_artifact=manifest.markdown,
        revision=1, run_context=SimpleNamespace(run_id=index.report_id), markdown=markdown,
        heading_numbers=manifest.heading_numbers,
    )
    registered = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        context.scope["threadId"], identity.path, max_bytes=identity.size,
    ))
    quality_file = next(file for file in registered.files if file.path.endswith("/quality-bundle-v1.json"))
    raw = await runtime.workspace_service.read_limited_regular_file(
        context.scope["threadId"], quality_file.path, max_bytes=quality_file.size,
    )
    assert hashlib.sha256(raw).hexdigest() == quality_file.sha256
    quality = QualityBundle.model_validate_json(raw)
    assert not quality.issues
    assert state["report_quality_issues"] == []
