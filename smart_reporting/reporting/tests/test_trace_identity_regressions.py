"""事实身份、派生导出权限与文件身份回归。"""
import hashlib
import json
from pathlib import Path

import pytest

from smart_reporting.report_editor.trace_revisions import write_registered_json
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1, canonical_json_bytes
from smart_reporting.reporting.trace.index_builder import encode_trace_index

from .test_report_editor_trace import DATASET_ID, _context, _make_editor
from .test_trace_subject_validate import _make_editor_with_subject, _table_markdown

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.mark.parametrize("field,value", [("factKey", "fact-" + "f" * 16), ("factKind", "derived")])
async def test_invalid_fact_identity_is_not_valid(tmp_path, field, value):
    editor, _, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    manifest = await editor.trace.load_manifest(context)
    payload = index.model_dump(mode="json", by_alias=True)
    payload["subjectBindings"][0]["factRefs"][0][field] = value
    index = RevisionTraceIndexV1.model_validate(payload)
    thread = context.scope["threadId"]
    identity = await write_registered_json(editor.workspace, thread, "reports/revision-1/invalid-index.json", encode_trace_index(index))
    manifest = manifest.model_copy(update={"trace_index": identity})
    identity = await write_registered_json(editor.workspace, thread, "reports/revision-1/invalid-manifest.json", canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True)))
    context = context.model_copy(update={"artifact_manifest": identity})
    markdown = "收入3600万元[[claim:claim-1]]"
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result["summary"]["valid"] == 0
    assert result["summary"]["stale"] == 1


async def test_existing_export_must_cover_downloading_sessions_blocked_columns(tmp_path):
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _, owner = await grants.exchange(raw)
    raw, _ = await grants.issue(_context(), capabilities={"blocked_columns": ["revenue"], "download_derived": True})
    _, restricted = await grants.exchange(raw)
    for columns in (["visits"], ["visits", "revenue"]):
        started = await editor.trace_create_derived_export(_context(), owner, DATASET_ID, policy="masked_columns", params={"columns": columns})
        job = editor.trace.exports._jobs[started["exportId"]]
        await job.task
        if "revenue" not in columns:
            with pytest.raises(ReportingError) as error:
                await editor.trace_derived_export_download(_context(), restricted, job.export_id)
            assert error.value.code == "dataset_access_denied"
        else:
            path, _, _ = await editor.trace_derived_export_download(_context(), restricted, job.export_id)
            assert all(row.split(",")[2] == "***" for row in Path(path).read_text().splitlines()[1:])


async def test_modified_export_is_rejected_even_when_size_is_unchanged(tmp_path):
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _, session = await grants.exchange(raw)
    started = await editor.trace_create_derived_export(_context(), session, DATASET_ID, policy="masked_columns", params={"columns": ["visits"]})
    job = editor.trace.exports._jobs[started["exportId"]]
    await job.task
    path, _, _ = await editor.trace_derived_export_download(_context(), session, job.export_id)
    original = Path(path).read_bytes()
    Path(path).write_bytes(original.replace(b"1000", b"9999"))
    assert Path(path).stat().st_size == job.size
    with pytest.raises(ReportingError) as error:
        await editor.trace_derived_export_download(_context(), session, job.export_id)
    assert error.value.code == "snapshot_integrity_failed"


async def test_overview_rejects_fact_file_registered_for_another_analysis(tmp_path):
    editor, _, _ = await _make_editor(tmp_path, with_fact_file=True)
    try:
        context = await editor._source_context(_context())
        index = await editor.trace.load_index(context)
        manifest = await editor.trace.load_manifest(context)
        payload = index.model_dump(mode="json", by_alias=True)
        payload["factFiles"][0]["analysisId"] = "analysis_002"
        index = RevisionTraceIndexV1.model_validate(payload)
        thread = context.scope["threadId"]
        identity = await write_registered_json(
            editor.workspace, thread, "reports/revision-1/foreign-analysis-index.json", encode_trace_index(index),
        )
        manifest = manifest.model_copy(update={"trace_index": identity})
        identity = await write_registered_json(
            editor.workspace, thread, "reports/revision-1/foreign-analysis-manifest.json",
            canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True)),
        )
        context = context.model_copy(update={"artifact_manifest": identity})
        with pytest.raises(ReportingError) as error:
            await editor.trace.fact_detail(context, "analysis_002", "fact-" + "a" * 16)
        assert error.value.code == "fact_binding_unavailable"
        overview = await editor.trace.sources(context)
        assert overview["available"] is True
        assert overview["datasets"]
        assert overview["facts"] == []
    finally:
        await editor.aclose()


async def test_duplicate_fact_ids_are_unavailable_without_blocking_editor_validation(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path)
    try:
        index = await editor.trace.load_index(context)
        manifest = await editor.trace.load_manifest(context)
        fact_ref = next(item for item in index.files if item.resource_id == index.fact_files[0].file_resource_id)
        thread = context.scope["threadId"]
        content = await editor.workspace.read_limited_regular_file(thread, fact_ref.path, max_bytes=16 * 1024 * 1024)
        document = json.loads(content)
        document["metrics"].append({**document["metrics"][0], "total": 9999})
        # 构造已登记但内容身份有歧义的输入快照；生产写入路径本身保持不可覆盖。
        await editor.workspace.awrite_bytes(thread, fact_ref.path, canonical_json_bytes(document), overwrite=True)
        identity = await write_registered_json(editor.workspace, thread, fact_ref.path, canonical_json_bytes(document))
        changed_ref = fact_ref.model_copy(update={"size": identity.size, "sha256": identity.sha256})
        index = index.model_copy(update={"files": tuple(
            changed_ref if item.resource_id == fact_ref.resource_id else item for item in index.files
        )})
        identity = await write_registered_json(
            editor.workspace, thread, "reports/revision-1/duplicate-facts-index.json", encode_trace_index(index),
        )
        manifest = manifest.model_copy(update={"trace_index": identity})
        identity = await write_registered_json(
            editor.workspace, thread, "reports/revision-1/duplicate-facts-manifest.json",
            canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True)),
        )
        context = context.model_copy(update={"artifact_manifest": identity})
        markdown = "收入3600万元[[claim:claim-1]]\n\n" + _table_markdown([["本期", "3,600"], ["上期", "3,600"]])
        result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
        assert result["summary"]["valid"] == 0
        assert result["summary"]["stale"] == 1
        assert result["tableSummary"]["valid"] == 0
        assert result["tableSummary"]["stale"] == 2
        overview = await editor.trace.sources(context)
        assert overview["available"] is True
        assert overview["datasets"]
        assert overview["facts"] == []
    finally:
        await editor.aclose()
