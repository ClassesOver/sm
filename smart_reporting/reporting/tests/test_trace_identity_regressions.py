"""事实身份、派生导出权限与文件身份回归。"""
import hashlib
from pathlib import Path

import pytest

from smart_reporting.report_editor.trace_revisions import write_registered_json
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1, canonical_json_bytes
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from .test_report_editor_trace import _make_editor, _context, DATASET_ID
from .test_trace_subject_validate import _make_editor_with_subject

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
