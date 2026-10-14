"""动态发现图谱与章节提纲的 checkpoint 身份契约。"""

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
