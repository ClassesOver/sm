"""正常报告的追溯索引超过元数据预算时仍可核验，身份和读取上限继续生效。"""

import hashlib

import pytest

from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError

from .test_report_editor_trace import _context, _make_editor, _scope


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["registered", "changed", "oversized"])
async def test_large_registered_trace_index_preserves_integrity_checks(tmp_path, case):
    editor, _, workspace = await _make_editor(tmp_path)
    workspace.registry.resolve(_scope())
    context = _context()
    manifest = await editor.trace.load_manifest(context)
    identity = manifest.trace_index
    original = await workspace.read_limited_regular_file(
        context.scope["threadId"], identity.path, max_bytes=1024 * 1024,
    )
    # 空白是合法 JSON；只改变文件大小，不改变索引中的报告身份及绑定。
    size = (17 if case == "oversized" else 5) * 1024 * 1024
    content = original + b" " * (size - len(original))
    path = "reports/revision-1/large-trace-index.json"
    await workspace.awrite_bytes(context.scope["threadId"], path, content)
    registered = ArtifactFile(
        path=path, mediaType="application/json", size=len(content),
        sha256=hashlib.sha256(content).hexdigest() if case != "changed" else "0" * 64,
    )
    manifest = manifest.model_copy(update={"trace_index": registered})
    if case != "registered":
        with pytest.raises(ReportingError, match="snapshot_integrity_failed"):
            await editor.trace.index_for_manifest(context, manifest)
        return

    index = await editor.trace.index_for_manifest(context, manifest)
    assert index.report_id == "report-1"
    assert index.revision == 1
    assert index.datasets[0].dataset_id == "dataset-url-abc0001"
