"""验收摘要绑定表题的共享来源规则及实际下发运行时包。"""
from hashlib import sha256

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.preference_executor import executor_manifest
from smart_reporting.reporting.workspace import _report_runtime_package


def test_manifest_includes_current_caption_source_snapshot_and_runtime_entrypoints():
    result = executor_manifest()
    paths = {item['path'].removeprefix('smart_reporting/') for item in result['files']}
    assert {
        'reporting/trace/contracts_v1.py', 'reporting/trace/markdown_body.py',
        'reporting/workspace.py', 'report_editor/render_preparation.py',
        'report_editor/trace_revisions.py', 'report_editor/trace_sources.py',
        'management/preference_document_table_readback.py',
        'management/preference_word_caption_evidence.py', 'management/preference_evidence.py',
    } <= paths
    raw, digest = _report_runtime_package()
    assert result['reportRuntimePackage'] == {'size': len(raw), 'sha256': digest}


def test_manifest_changes_when_actual_caption_runtime_package_changes(monkeypatch):
    from smart_reporting.reporting import workspace

    before = configuration_hash(executor_manifest())
    raw = b'new-actual-runtime-package'
    monkeypatch.setattr(workspace, '_report_runtime_package', lambda: (raw, sha256(raw).hexdigest()))
    after = executor_manifest()
    assert configuration_hash(after) != before
    assert after['reportRuntimePackage'] == {'size': len(raw), 'sha256': sha256(raw).hexdigest()}
