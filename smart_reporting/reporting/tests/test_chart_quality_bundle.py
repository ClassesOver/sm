"""Chart checks must survive publication and be recomputed from current bytes."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.tests.test_report_editor_trace import _context, _make_editor
from smart_reporting.reporting.trace.chart_subjects import freeze_chart_presentations
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


async def chart_case(tmp_path):
    editor, _, workspace = await _make_editor(tmp_path, with_chart_trace=True, with_fact_file=True)
    context = _context()
    await editor.read_document(context)
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await workspace.read_limited_regular_file(
            context.scope["threadId"], file.path, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
    }
    markdown = sources[index.markdown_file_resource_id].decode()
    index = freeze_chart_presentations(index, markdown)
    files = {file.resource_id: file for file in index.files}
    chart = index.chart_traces[0]
    origin = index.fact_files[0]
    fact = json.loads(sources[origin.file_resource_id])
    metric = fact["metrics"][0]
    plot_id = chart.plot_data_file_resource_ids[0]
    plot = {
        "schema": "chart-input/v1",
        "chartId": chart.chart_id,
        "source": {
            "analysisId": origin.analysis_id,
            "sha256": files[origin.file_resource_id].sha256,
            "dataPath": "metrics[0]",
        },
        "columns": ["field", "total"],
        "rows": [[metric["field"], metric["total"]]],
        "rowCount": 1,
    }
    sources[plot_id] = encoded(plot)
    index = index.model_copy(
        update={
            "files": tuple(
                file.model_copy(
                    update={
                        "size": len(sources[file.resource_id]),
                        "sha256": hashlib.sha256(sources[file.resource_id]).hexdigest(),
                    }
                )
                for file in index.files
            )
        }
    )
    mapping = {}
    for file in index.files:
        await workspace.awrite_bytes(
            context.scope["threadId"], file.path, sources[file.resource_id], overwrite=True
        )
    return editor, workspace, context, index, markdown, sources, mapping


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'image_changed', 'caption_changed'])
async def test_static_chart_keeps_one_honest_review_reason_and_checks_identity(tmp_path, fault):
    _, _, _, index, markdown, sources, _ = await chart_case(tmp_path)
    chart = index.chart_traces[0]
    if fault == 'image_changed':
        sources[chart.image_file_resource_id] += b' changed'
    elif fault == 'caption_changed':
        markdown += '\n\n![another](chart-001.png)'
    quality = evaluate_quality_bundle(index, markdown, sources,
                                     authorization_scope_hash='a' * 64)
    check = quality.chart_checks[chart.chart_id]
    assert check.status == 'unknown'
    assert check.reason == {
        'none': 'static_image_not_evaluated',
        'image_changed': 'chart_source_unavailable',
        'caption_changed': 'chart_presentation_changed',
    }[fault]
    assert quality.semantic_checks[chart.chart_id].status == 'unknown'
    assert quality.all_key_facts_evaluated is False
    issues = [issue for issue in quality.issues if issue.subject_id == chart.chart_id]
    assert [issue.code for issue in issues] == ['chart_support_unknown']


@pytest.mark.anyio
@pytest.mark.parametrize("read_failure", [False, True])
async def test_publication_persists_registered_chart_check_with_source_failure_isolated(
    tmp_path, monkeypatch, read_failure
):
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.tests.test_trace_index_builder import _handle, _lineage
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.trace.quality_bundle import QUALITY_FILENAME, QualityBundle
    from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin

    _, workspace, context, index, markdown, _, mapping = await chart_case(tmp_path)
    files = {file.resource_id: file for file in index.files}
    chart = index.chart_traces[0]
    state = {}
    runtime = SimpleNamespace(
        workspace_service=workspace,
        _scope=lambda _run: context.scope,
        _state=lambda _run: state,
        _profile=lambda _run: SimpleNamespace(effective_profile_hash=index.profile_hash),
        _build_drilldown_metrics=AsyncMock(return_value=()),
        state_repository=SimpleNamespace(get=AsyncMock(return_value=None)),
    )
    if read_failure:
        original = workspace.read_limited_regular_file

        async def read(thread_id, path, **kwargs):
            if path == files[chart.image_file_resource_id].path:
                raise OSError("injected chart image read failure")
            return await original(thread_id, path, **kwargs)

        monkeypatch.setattr(workspace, "read_limited_regular_file", read)
    markdown_file = files[index.markdown_file_resource_id]
    identity = await RuntimePublicationMixin._write_trace_index(
        runtime,
        "reports/revision-1/artifact-manifest.json",
        handles=(_handle("dataset-url-abc0001"),),
        lineage=(_lineage("dataset-url-abc0001"),),
        markdown_artifact=ArtifactFile(
            path=markdown_file.path,
            mediaType=markdown_file.media_type,
            size=markdown_file.size,
            sha256=markdown_file.sha256,
        ),
        fact_files={entry.analysis_id: files[entry.file_resource_id] for entry in index.fact_files},
        chart_trace_files=tuple(
            files[resource]
            for resource in (
                chart.image_file_resource_id,
                *chart.plot_data_file_resource_ids,
            )
        ),
        chart_traces=index.chart_traces,
        markdown=markdown,
        revision=1,
        run_context=SimpleNamespace(run_id="report-1"),
    )
    raw = await workspace.read_limited_regular_file(
        context.scope["threadId"], identity.path, max_bytes=identity.size
    )
    published = RevisionTraceIndexV1.model_validate_json(raw)
    registered = next(
        file for file in published.files if file.path.endswith("/" + QUALITY_FILENAME)
    )
    payload = await workspace.read_limited_regular_file(
        context.scope["threadId"], registered.path, max_bytes=registered.size
    )
    assert hashlib.sha256(payload).hexdigest() == registered.sha256
    quality = QualityBundle.model_validate_json(payload)
    assert quality.chart_checks[chart.chart_id].status == "unknown"
    assert quality.chart_checks[chart.chart_id].reason == (
        "chart_source_unavailable" if read_failure else "static_image_not_evaluated"
    )
    assert state["report_quality_issues"] == []
