"""动态发现图谱与章节提纲的 checkpoint 身份契约。"""

import pytest

from smart_reporting.reporting.workflow.checkpoint import (
    FileIdentity,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
    ReportingCheckpoint,
)


def _coverage() -> ProfileCoverageManifest:
    dataset = ProfileCoverageDataset(
        datasetId="dataset-url-abc0001",
        datasetPath="报表/数据集/run1/dataset-url-abc0001.csv",
        datasetSize=100,
        datasetSnapshotHash="b" * 64,
        profileFile=FileIdentity(path="profiles/x.json", size=1, sha256="c" * 64),
        rowCount=4,
        fieldCount=1,
        fields=("amount",),
    )
    return ProfileCoverageManifest(
        authorizedDatasetCount=1,
        coveredDatasetCount=1,
        datasets=(dataset,),
    )


def test_checkpoint_preserves_finding_graph_and_narrative_identity():
    graph_file = FileIdentity(path="facts/finding-graph.json", size=10, sha256="d" * 64)
    outline_file = FileIdentity(path="outline/narrative.json", size=11, sha256="e" * 64)
    checkpoint = ReportingCheckpoint(
        revision=1,
        phase="analysis",
        outlineHash="a" * 64,
        profileCoverage=_coverage(),
        findingGraphFile=graph_file,
        findingGraphHash="f" * 64,
        narrativeOutlineFile=outline_file,
        narrativeOutlineHash="1" * 64,
    )

    assert checkpoint.finding_graph_file == graph_file
    assert checkpoint.finding_graph_hash == "f" * 64
    assert checkpoint.narrative_outline_file == outline_file
    assert checkpoint.narrative_outline_hash == "1" * 64


def test_checkpoint_rejects_invalid_finding_graph_hash():
    try:
        ReportingCheckpoint(
            revision=1,
            phase="analysis",
            outlineHash="a" * 64,
            profileCoverage=_coverage(),
            findingGraphHash="not-a-sha256",
        )
    except ValueError as error:
        assert "findingGraphHash" in str(error)
    else:
        raise AssertionError("invalid finding graph hash was accepted")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_restore_rejects_graph_from_another_fact_snapshot(anyio_backend):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.hospital_operation.finding_projection import build_finding_graph
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    graph = build_finding_graph(
        [{"analysisId": "analysis_001"}], None, (), snapshot_hash="f" * 64
    )
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(),
        findingGraphFile=FileIdentity(path="findings/graph.json", size=10, sha256="d" * 64),
        findingGraphHash=graph.snapshot_hash,
    )
    runtime = SimpleNamespace(_read_identity_model=AsyncMock(return_value=graph))
    with pytest.raises(ReportingError, match="快照"):
        await RuntimeAnalysisMixin._restore_or_create_finding_graph(
            runtime, run_context=None, checkpoint=checkpoint, thread_id="thread-1",
            report_run_id="run-1", revision=1,
            fact_files={"analysis_001": FileIdentity(path="facts/001.json", size=10, sha256="e" * 64)},
        )
