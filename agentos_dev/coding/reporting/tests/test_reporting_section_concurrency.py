from __future__ import annotations

import asyncio

import pytest

from agentos_dev.coding.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    CompletedSection,
    FileIdentity,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
    ReportBrief,
    ReportingCheckpoint,
)
from agentos_dev.coding.reporting.workflow.runtime import ReportWorkflowRuntime, _run_bounded


@pytest.mark.anyio
async def test_run_bounded_limits_concurrency_and_preserves_input_order() -> None:
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def worker(value: int) -> int:
        nonlocal active, maximum
        async with lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep((5 - value) * 0.005)
        async with lock:
            active -= 1
        return value * 10

    result = await _run_bounded((1, 2, 3, 4), concurrency=2, worker=worker)

    assert maximum == 2
    assert result == [10, 20, 30, 40]


def test_merge_reporting_checkpoints_keeps_out_of_order_section_results() -> None:
    base = checkpoint(
        completed=(completed("section_002", "b"),),
        pending=("section_001", "section_003"),
    )
    incoming = checkpoint(
        completed=(completed("section_001", "a"),),
        pending=("section_002", "section_003"),
    )

    merged = ReportWorkflowRuntime._merge_reporting_checkpoints(base, incoming)

    assert {item.section_code for item in merged.completed_sections} == {
        "section_001",
        "section_002",
    }
    assert merged.pending_sections == ("section_003",)


def checkpoint(
    *, completed: tuple[CompletedSection, ...], pending: tuple[str, ...]
) -> ReportingCheckpoint:
    profile = ProfileCoverageManifest(
        authorizedDatasetCount=1,
        coveredDatasetCount=1,
        datasets=(
            ProfileCoverageDataset(
                datasetId="dataset-1",
                datasetPath="datasets/a.csv",
                datasetSize=1,
                datasetSnapshotHash="a" * 64,
                profileFile=FileIdentity(path="profiles/a.json", size=1, sha256="b" * 64),
                rowCount=1,
                fieldCount=1,
                fields=("amount",),
            ),
        ),
    )
    return ReportingCheckpoint(
        revision=1,
        phase="sections",
        outlineHash="c" * 64,
        profileCoverage=profile,
        reportBrief=ReportBrief(
            objective="目标",
            executiveSummary="摘要",
            managementQuestions=("问题",),
        ),
        evidenceManifest=AnalysisEvidenceManifest(
            evidence=(
                AnalysisEvidence(
                    analysisId="analysis_001",
                    summary="摘要",
                    datasetIds=("dataset-1",),
                    evidenceFiles=(
                        FileIdentity(path="analysis/evidence.json", size=1, sha256="e" * 64),
                    ),
                    citationIds=("citation_001",),
                ),
            )
        ),
        analysisManifestFile=FileIdentity(path="analysis/final.json", size=1, sha256="d" * 64),
        completedSections=completed,
        pendingSections=pending,
    )


def completed(section_code: str, digest: str) -> CompletedSection:
    return CompletedSection(
        sectionCode=section_code,
        workItemHash=digest * 64,
        artifactFile=FileIdentity(path=f"sections/{section_code}.json", size=1, sha256=digest * 64),
    )
