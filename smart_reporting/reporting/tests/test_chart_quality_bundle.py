"""Chart checks must survive publication and be recomputed from current bytes."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.tests.test_report_editor_trace import _context, _make_editor
from smart_reporting.reporting.trace.chart_subjects import freeze_chart_presentations
from smart_reporting.reporting.trace.contracts_v1 import TraceFileRefV1, derive_resource_id
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
    spec_path = "reports/revision-1/chart-001.plotly.json"
    spec_id = derive_resource_id(spec_path)
    sources[spec_id] = encoded(
        {"data": [{"type": "bar", "x": [metric["field"]], "y": [metric["total"]]}]}
    )
    spec = TraceFileRefV1(
        resourceId=spec_id,
        path=spec_path,
        mediaType="application/json",
        size=len(sources[spec_id]),
        sha256=hashlib.sha256(sources[spec_id]).hexdigest(),
    )
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
            + (spec,)
        }
    )
    mapping = {files[chart.image_file_resource_id].path: spec_path}
    for file in index.files:
        await workspace.awrite_bytes(
            context.scope["threadId"], file.path, sources[file.resource_id], overwrite=True
        )
    return editor, workspace, context, index, markdown, sources, mapping


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "spec_changed",
        "source_missing",
        "input_missing",
        "caption",
        "coordinated",
        "unregistered",
    ],
)
async def test_chart_quality_rechecks_both_identity_and_frozen_projection(tmp_path, fault):
    _, _, _, index, markdown, sources, mapping = await chart_case(tmp_path)
    chart = index.chart_traces[0]
    spec_id = derive_resource_id(next(iter(mapping.values())))
    if fault == "spec_changed":
        sources[spec_id] += b" "
    elif fault == "source_missing":
        sources.pop(index.fact_files[0].file_resource_id)
    elif fault == "input_missing":
        sources.pop(chart.plot_data_file_resource_ids[0])
    elif fault == "caption":
        markdown += "\n\n![another](chart-001.png)"
    elif fault == "coordinated":
        plot_id = chart.plot_data_file_resource_ids[0]
        plot = json.loads(sources[plot_id])
        plot["rows"][0][1] += 100
        sources[plot_id] = encoded(plot)
        figure = json.loads(sources[spec_id])
        figure["data"][0]["y"][0] += 100
        sources[spec_id] = encoded(figure)
        # Even registering both modified outputs cannot change their frozen origin.
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
    elif fault == "unregistered":
        mapping = {key: "unregistered.plotly.json" for key in mapping}
    quality = evaluate_quality_bundle(
        index, markdown, sources, authorization_scope_hash="a" * 64, interactive_charts=mapping
    )
    check = quality.chart_checks[chart.chart_id]
    assert quality.all_key_facts_evaluated is False
    assert check.scope == "registered_arrays"
    assert check.status == ("verified" if fault == "none" else "unknown")
    if fault == "coordinated":
        assert check.reason == "chart_input_projection_mismatch"


@pytest.mark.anyio
async def test_live_editor_does_not_reuse_previous_array_pass(tmp_path, monkeypatch):
    editor, workspace, context, index, markdown, sources, mapping = await chart_case(tmp_path)
    monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=index))
    monkeypatch.setattr(
        editor.trace,
        "load_manifest",
        AsyncMock(
            return_value=SimpleNamespace(
                charts=[
                    SimpleNamespace(
                        **next(file for file in index.files if file.path == key).model_dump(),
                        interactive_spec=next(file for file in index.files if file.path == value),
                    )
                    for key, value in mapping.items()
                ]
            )
        ),
    )
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["charts"][0]["dataCheck"]["status"] == "verified"
    first_hash = result["quality"]["inputSha256"]
    spec_id = derive_resource_id(next(iter(mapping.values())))
    await workspace.awrite_bytes(
        context.scope["threadId"],
        next(iter(mapping.values())),
        sources[spec_id] + b" ",
        overwrite=True,
    )
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["charts"][0]["dataCheck"]["status"] == "unknown"
    assert result["quality"]["inputSha256"] != first_hash


@pytest.mark.anyio
async def test_editor_does_not_trust_a_manifest_spec_with_a_different_identity(
    tmp_path, monkeypatch
):
    editor, _, context, index, markdown, _, mapping = await chart_case(tmp_path)
    image = next(file for file in index.files if file.path in mapping)
    spec = next(file for file in index.files if file.path in mapping.values())
    monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=index))
    monkeypatch.setattr(
        editor.trace,
        "load_manifest",
        AsyncMock(
            return_value=SimpleNamespace(
                charts=[
                    SimpleNamespace(
                        **image.model_dump(),
                        interactive_spec=spec.model_copy(update={"sha256": "f" * 64}),
                    ),
                ]
            )
        ),
    )
    result = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert result["charts"][0]["dataCheck"]["status"] == "unknown"
    assert result["quality"]["status"] == "evaluated"


@pytest.mark.anyio
async def test_copied_revision_rebinds_spec_identity_and_rechecks_frozen_projection(tmp_path):
    from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
    from smart_reporting.reporting.delivery.artifacts_v1 import (
        ArtifactFile,
        ChartArtifact,
        ReportArtifactManifest,
    )

    editor, workspace, context, index, markdown, sources, mapping = await chart_case(tmp_path)
    manifest = await editor.trace.load_manifest(context)
    chart = index.chart_traces[0]
    image = next(file for file in index.files if file.resource_id == chart.image_file_resource_id)
    spec_path = next(iter(mapping.values()))
    raw = sources[derive_resource_id(spec_path)]
    spec = ArtifactFile(
        path=spec_path,
        mediaType="application/vnd.plotly.v1+json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    manifest = ReportArtifactManifest.model_validate(
        manifest.model_copy(
            update={
                "charts": (
                    ChartArtifact(
                        path=image.path,
                        mediaType=image.media_type,
                        size=image.size,
                        sha256=image.sha256,
                        chartId=chart.chart_id,
                        datasetIds=chart.dataset_ids,
                        renderer="plotly",
                        interactiveSpec=spec,
                    ),
                ),
            }
        ).model_dump(mode="json", by_alias=True)
    )
    path_map = {
        file.path: file.path.replace("/revision-1/", "/revision-2/") for file in index.files
    }
    target = path_map[context.markdown_path]
    await workspace.awrite_text(context.scope["threadId"], target, markdown)
    md = ArtifactFile(
        path=target,
        mediaType="text/markdown",
        size=len(markdown.encode()),
        sha256=hashlib.sha256(markdown.encode()).hexdigest(),
    )
    _, identity = await snapshot_revision_lineage(
        workspace,
        context.scope["threadId"],
        manifest=manifest,
        index=index,
        markdown_file=md,
        target_revision=2,
        path_map=path_map,
        manifest_path="reports/revision-2/artifact-manifest.json",
    )
    current = context.model_copy(
        update={"revision": 2, "markdown_path": target, "artifact_manifest": identity}
    )
    result = await editor.trace.validate(current, markdown, md.sha256)
    assert result["charts"][0]["dataCheck"]["status"] == "verified"
    await workspace.awrite_bytes(
        context.scope["threadId"], path_map[spec_path], raw + b" ", overwrite=True
    )
    result = await editor.trace.validate(current, markdown, md.sha256)
    assert result["charts"][0]["dataCheck"]["status"] == "unknown"


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
            if path in mapping.values():
                raise OSError("injected chart spec read failure")
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
                derive_resource_id(next(iter(mapping.values()))),
            )
        ),
        chart_traces=index.chart_traces,
        markdown=markdown,
        interactive_charts=mapping,
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
    assert quality.chart_checks[chart.chart_id].status == (
        "unknown" if read_failure else "verified"
    )
    assert state["report_quality_issues"] == []
