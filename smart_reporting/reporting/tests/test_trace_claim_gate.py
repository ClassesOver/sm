"""B2 发布门禁 claim factIds 核对测试（计划 B2 第 5 项）。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.checkpoint import (
    FileIdentity,
    ReportingCheckpoint,
    SectionClaim,
    SectionArtifact,
)
from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin

# 直接测试核对逻辑：通过未绑定方法调用（避免拉起整个 workflow facade）。


def _claim(claim_id: str, value, fact_ids: tuple[str, ...] = ()) -> SectionClaim:
    return SectionClaim(
        claimId=claim_id,
        metricCode="income_total",
        value=value,
        periodBasis="2025-09",
        managementQuestion="收入规模如何",
        currentPeriod="2025-09",
        citationIds=("citation_000",),
        factIds=fact_ids,
    )


def _artifact(claims: tuple[SectionClaim, ...]) -> SectionArtifact:
    return SectionArtifact(
        sectionCode="section_002",
        blocks=(
            ReportDraftBlock(
                blockId="b1",
                markdown="收入 3600 万元",
                claimIds=(claims[0].claim_id,),
            ),
        ),
        claims=claims,
    )


def _checkpoint(fact_files: dict) -> ReportingCheckpoint:
    from smart_reporting.reporting.workflow.checkpoint import (
        ProfileCoverageDataset,
        ProfileCoverageManifest,
    )

    coverage = ProfileCoverageDataset(
        datasetId="dataset-url-abc0001",
        datasetPath="报表/数据集/run1/dataset-url-abc0001.csv",
        datasetSize=100,
        datasetSnapshotHash="b" * 64,
        profileFile=FileIdentity(path="profiles/x.json", size=1, sha256="c" * 64),
        rowCount=4,
        fieldCount=1,
        fields=("amount",),
    )
    return ReportingCheckpoint(
        revision=1,
        phase="analysis",  # 核对逻辑不依赖 phase；非 analysis 阶段要求完整 evidence 产物
        outlineHash="0" * 64,
        profileCoverage=ProfileCoverageManifest(
            authorizedDatasetCount=1,
            coveredDatasetCount=1,
            datasets=(coverage,),
        ),
        deterministicFactFiles=fact_files,
    )


def _fact_file_bytes(fact_id: str, total: float = 3600.0) -> bytes:
    document = {
        "version": "1",
        "analysisId": "analysis_001",
        "metrics": [
            {
                "factId": fact_id,
                "datasetId": "dataset-url-abc0001",
                "datasetSha256": "b" * 64,
                "periodRoles": ["current"],
                "metricCodes": ["income_total"],
                "field": "收入",
                "fieldRef": "dynamic_source.dynamic_db.dynamic_table.amount",
                "aggregation": "sum",
                "formula": "sum(amount)",
                "scope": {},
                "total": total,
                "missingCount": 0,
                "zeroCount": 0,
                "negativeCount": 0,
                "warnings": [],
            }
        ],
        "derivedMetrics": [],
        "comparisons": [],
        "reconciliations": [],
        "correlations": {},
        "warnings": [],
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


class _GateHarness:
    """最小化暴露 _verify_claim_fact_bindings 所需的协作对象。"""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = files or {}

    async def _read_identity_bytes(self, thread_id, identity, *, max_bytes):
        return self.files[identity.path]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_unknown_fact_id_blocks_publication() -> None:
    good_id = "fact-" + "1" * 16
    harness = _GateHarness(
        {"facts/analysis_001.json": _fact_file_bytes(good_id, total=3600.0)}
    )
    fact_file = FileIdentity(path="facts/analysis_001.json", size=1, sha256="a" * 64)
    checkpoint = _checkpoint({"analysis_001": fact_file})
    artifact = _artifact(
        (_claim("claim-1", 3600.0, fact_ids=("fact-" + "9" * 16,),),)
    )
    issues, warnings = await RuntimePublicationMixin._verify_claim_fact_bindings(
        harness, "thread", checkpoint, (artifact,)
    )
    assert [item["code"] for item in issues] == ["report_claim_fact_unknown"]
    assert warnings == []


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_matching_value_passes_and_mismatch_warns() -> None:
    good_id = "fact-" + "1" * 16
    harness = _GateHarness(
        {"facts/analysis_001.json": _fact_file_bytes(good_id, total=3600.0)}
    )
    fact_file = FileIdentity(path="facts/analysis_001.json", size=1, sha256="a" * 64)
    checkpoint = _checkpoint({"analysis_001": fact_file})
    matched = _artifact((_claim("claim-1", 3600.0, fact_ids=(good_id,),),))
    issues, warnings = await RuntimePublicationMixin._verify_claim_fact_bindings(
        harness, "thread", checkpoint, (matched,)
    )
    assert issues == [] and warnings == []

    drifted = _artifact((_claim("claim-1", 9999.0, fact_ids=(good_id,),),))
    issues, warnings = await RuntimePublicationMixin._verify_claim_fact_bindings(
        harness, "thread", checkpoint, (drifted,)
    )
    assert issues == []
    assert [item["code"] for item in warnings] == ["report_claim_fact_value_mismatch"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_claims_without_fact_ids_skip_verification() -> None:
    harness = _GateHarness()
    checkpoint = _checkpoint({})  # 无 fact 文件
    artifact = _artifact((_claim("claim-1", 3600.0),))
    issues, warnings = await RuntimePublicationMixin._verify_claim_fact_bindings(
        harness, "thread", checkpoint, (artifact,)
    )
    assert issues == [] and warnings == []
