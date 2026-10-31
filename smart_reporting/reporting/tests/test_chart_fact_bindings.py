"""缺失图表 factRefs 的精确回溯，不以名称或数值猜配。"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_trace_index_builder import _build, _handle, _lineage
from smart_reporting.reporting.trace.chart_facts import recover_chart_fact_refs
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    ComputationRecordV1,
    FactRefV1,
    RevisionTraceIndexV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime


def _case(*, supplemental=False, snapshot=False, register=True, standard=False):
    handle = _handle("dataset-url-abc0001")
    metrics = [{"factId": "fact-aaaaaaaaaaaaaaaa", "datasetId": handle.dataset_id,
        "datasetSha256": handle.sha256, "field": "revenue", "periodField": "period",
        "periodGranularity": "month", "unit": "元", "scope": {},
        "periodValues": [{"period": "2025-09", "value": 1200}]}]
    payload = {"analysisId": "analysis_001", "metrics": metrics,
        "comparisons": [{"factId": "fact-bbbbbbbbbbbbbbbb",
            "inputFactIds": [metrics[0]["factId"]]}]}
    documents = {}

    def file(path, value):
        raw = json.dumps(value).encode()
        documents[path] = raw
        return TraceFileRefV1(resourceId=derive_resource_id(path), path=path,
            mediaType="application/json", size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    source_path = "报表/智能分析/run1/facts/current.json"
    actual_path = source_path.replace("run1/", "run1/revision-2/") if snapshot else source_path
    facts = file(actual_path, payload)
    source = facts
    origin_path = source_path
    tokens = "metrics[0].periodValues"
    columns, rows = ["period", "value"], [["2025-09", 1200]]
    computations = ()
    supplemental_files = ()
    if supplemental:
        origin_path = "报表/智能分析/run1/evidence/supplement.json"
        path = origin_path.replace("run1/", "run1/revision-2/") if snapshot else origin_path
        columns, rows = ["area", "value"], [["总部院区", 1200]]
        source = file(path, {"findings": [{"columns": columns, "rows": rows,
            "columnMeta": {"value": {"unit": "元"}}}]})
        tokens = "findings[0].rows"
        supplemental_files = (source,)
        parameters = {"operation": "group_summary", "datasetId": handle.dataset_id,
            "outputName": "院区收入", "measureField": "revenue", "measureUnit": "元",
            "dimensionField": "area", "periodField": "period", "periodGranularity": "month",
            "currentPeriods": ["2025-09"], "parentTotal": 1200}
        computations = (ComputationRecordV1(computationId="comp-" + "1" * 16,
            method="supplemental_standard_batch" if standard else "supplemental_free",
            methodVersion="standard-supplemental-v1" if standard else None,
            parameters={"computations": [parameters], "inputFiles": [
                {"path": handle.path, "size": handle.size, "sha256": handle.sha256}]},
            inputDatasetIds=(handle.dataset_id,), outputFactRefs=(FactRefV1(
                analysisId="analysis_001", fileResourceId=source.resource_id,
                jsonPointer="/findings/0/rows/0", factKind="supplemental_finding"),)),)
    plot = file("报表/智能分析/run1/plot.json", {"schema": "chart-input/v1", "chartId": "chart_001",
        "role": "measure", "source": {"analysisId": "analysis_001", "path": origin_path,
            "sha256": source.sha256, "dataPath": tokens}, "columns": columns,
        "rows": rows, "rowCount": len(rows), "columnMeta": {"value": {"unit": "元"}}})
    chart = ChartTraceV1(chartId="chart_001", imageFileResourceId=derive_resource_id("chart.png"),
        plotDataFileResourceIds=(plot.resource_id,), datasetIds=(handle.dataset_id,))
    image = SimpleNamespace(path="chart.png", size=10, sha256="c" * 64)
    index = _build((handle,), (_lineage(handle.dataset_id),),
        fact_files={"analysis_001": ArtifactFile(path=facts.path, mediaType="application/json",
            size=facts.size, sha256=facts.sha256)}, chart_trace_files=(image, plot),
        chart_traces=(chart,), computations=computations, computation_files=supplemental_files)
    if snapshot:
        markdown = next(f for f in index.files if f.resource_id == index.markdown_file_resource_id)
        path = "报表/智能分析/run1/revision-2/report.md"
        moved = markdown.model_copy(update={"path": path, "resource_id": derive_resource_id(path)})
        index = index.model_copy(update={"files": tuple(moved if f == markdown else f for f in index.files),
            "markdown_file_resource_id": moved.resource_id})
    if supplemental and not register:
        index = index.model_copy(update={"computations": ()})
    return index, chart, documents


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("snapshot", [False, True])
@pytest.mark.parametrize("supplemental,standard", [(False, False), (True, False), (True, True)])
async def test_chart_fact_recovery_keeps_exact_ownership(snapshot, supplemental, standard):
    index, chart, documents = _case(supplemental=supplemental, standard=standard, snapshot=snapshot)
    async def read(file):
        return documents[file.path]
    refs = await recover_chart_fact_refs(index, chart, read)
    assert {r.fact_kind for r in refs} == ({"supplemental_finding", "metric", "comparison"} if standard
        else {"supplemental_finding"} if supplemental else {"metric", "comparison"})
    assert refs[0].json_pointer == ("/findings/0" if supplemental else "/metrics/0")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["file_changed", "missing", "unregistered_finding", "ambiguous", "wrong_unit"])
async def test_chart_fact_recovery_rejects_unregistered_or_changed_sources(fault):
    index, chart, documents = _case(supplemental=True, register=fault != "unregistered_finding", standard=True)
    if fault == "ambiguous":
        entry = next(e for e in index.fact_files if e.content_kind == "supplemental_evidence")
        index = index.model_copy(update={"fact_files": (*index.fact_files, entry)})
    if fault == "wrong_unit":
        record = index.computations[0]
        parameters = {**record.parameters, "computations": [{**record.parameters["computations"][0], "measureUnit": "人"}]}
        index = index.model_copy(update={"computations": (record.model_copy(update={"parameters": parameters}),)})
    async def read(file):
        if fault == "missing":
            raise FileNotFoundError(file.path)
        return documents[file.path] + (b" " if fault == "file_changed" else b"")
    if fault == "wrong_unit":
        refs = await recover_chart_fact_refs(index, chart, read)
        assert {r.fact_kind for r in refs} == {"supplemental_finding"}
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            await recover_chart_fact_refs(index, chart, read)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_new_report_archive_persists_recovered_chart_facts(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import publication

    index, chart, documents = _case()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _: {"threadId": "thread-1"}
    runtime._profile = lambda _: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._state = lambda _: {}
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    async def read(_thread, path, **_kwargs):
        return documents[path]
    async def write(_thread, path, raw, **_kwargs):
        documents[path] = raw
    runtime.workspace_service = SimpleNamespace(read_limited_regular_file=read, awrite_bytes=write,
        validate_content=lambda _: None)
    monkeypatch.setattr(publication, "build_csv_trace_index", lambda **_: index)
    markdown = next(f for f in index.files if f.resource_id == index.markdown_file_resource_id)
    identity = await runtime._write_trace_index("report/manifest.json", handles=(), lineage=(),
        markdown_artifact=markdown, revision=1, run_context=SimpleNamespace(run_id="run1"))
    saved = RevisionTraceIndexV1.model_validate_json(documents[identity.path])
    assert {r.fact_kind for r in saved.chart_traces[0].fact_refs} == {"metric", "comparison"}
