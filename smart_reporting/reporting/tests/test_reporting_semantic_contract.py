import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisArtifact,
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    ChartVisualInspectionReceipt,
    FileIdentity,
    MetricDefinition,
    ReportBrief,
    ReportingCheckpoint,
    SectionArtifact,
    SectionCitation,
    SectionClaim,
    read_analysis_artifact,
)
from smart_reporting.reporting.workflow.runtime.publication import evaluate_publication_semantics


def test_running_v1_artifact_fails_closed() -> None:
    with pytest.raises(ReportingError, match="report_semantic_contract_upgrade_required"):
        read_analysis_artifact({"version": "1"}, running=True)


def test_v2_artifact_rejects_nested_v1_manifest() -> None:
    with pytest.raises(ValueError, match="v2 EvidenceManifest"):
        AnalysisArtifact(
            reportBrief=ReportBrief(
                objective="目标",
                executiveSummary="摘要",
                managementQuestions=("收入如何？",),
            ),
            evidenceManifest=AnalysisEvidenceManifest.model_construct(
                version="1",
                evidence=(),
                metric_definitions=(),
                charts=(),
                dataset_semantics=(),
                warnings=(),
            ),
        )


def test_completed_v1_artifact_is_read_only_compatible() -> None:
    artifact = read_analysis_artifact({"version": "1"}, running=False)
    assert artifact.version == "1"


def test_running_v1_checkpoint_fails_closed() -> None:
    with pytest.raises(ValueError, match="report_semantic_contract_upgrade_required"):
        ReportingCheckpoint.model_validate(
            {
                "version": "1",
                "revision": 1,
                "phase": "analysis",
                "outlineHash": "0" * 64,
                "profileCoverage": {
                    "authorizedDatasetCount": 1,
                    "coveredDatasetCount": 1,
                    "datasets": [
                        {
                            "datasetId": "d1",
                            "datasetPath": "d.csv",
                            "datasetSize": 1,
                            "datasetSnapshotHash": "1" * 64,
                            "profileFile": {"path": "p.json", "size": 1, "sha256": "2" * 64},
                            "rowCount": 1,
                            "fieldCount": 1,
                            "fields": ["x"],
                        }
                    ],
                },
            }
        )


def test_chart_requires_structured_comparability_fields() -> None:
    with pytest.raises(ValueError):
        AnalysisChart(
            chartId="chart_1",
            sourceFile={"path": "x.png", "size": 1, "sha256": "0" * 64},
            title="x",
            altText="x",
            citationIds=("c1",),
        )


def test_chart_visual_inspection_receipt_rejects_unknown_issue_and_invalid_hash() -> None:
    with pytest.raises(ValueError):
        ChartVisualInspectionReceipt(
            sourcePath="analysis/charts/x.png",
            sha256="invalid",
            modelId="vision-model",
            reviewed=True,
            requiresRevision=False,
            issues=(
                {
                    "category": "unknown",
                    "severity": "warning",
                    "description": "未知问题",
                },
            ),
            summary="检查完成",
        )


def test_v2_manifest_requires_every_chart_visual_inspection_receipt() -> None:
    with pytest.raises(ValueError, match="视觉检查回执"):
        AnalysisEvidenceManifest(
            evidence=(
                AnalysisEvidence(
                    analysisId="analysis_001",
                    summary="冻结证据",
                    datasetIds=("dataset-1",),
                    evidenceFiles=(_identity("analysis/evidence.json"),),
                    citationIds=("c1",),
                    chartIds=("chart-1",),
                ),
            ),
            metricDefinitions=(
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2026-01",
                ),
            ),
            charts=(
                AnalysisChart(
                    chartId="chart-1",
                    sourceFile={"path": "analysis/charts/x.png", "size": 1, "sha256": "0" * 64},
                    title="收入",
                    altText="收入",
                    citationIds=("c1",),
                    metricCodes=("revenue",),
                    currentPeriod="2026-01",
                    comparisonType="none",
                    sourceDatasetId="dataset-1",
                    aggregationGrain="month",
                ),
            ),
            datasetSemantics=(
                AnalysisDatasetSemantics(
                    datasetId="dataset-1",
                    rowGrain="record",
                    duplicateResolution="not_applicable",
                ),
            ),
        )


def test_section_block_claim_reference_must_exist() -> None:
    with pytest.raises(ValueError, match="claim"):
        SectionArtifact(
            sectionCode="s1",
            blocks=(ReportDraftBlock(blockId="b1", markdown="正文", claimIds=("missing",)),),
            claims=(),
        )


def _identity(path: str) -> FileIdentity:
    return FileIdentity(path=path, size=1, sha256="0" * 64)


def _semantic_inputs(*, claim: SectionClaim, duplicate_resolution: str = "not_applicable"):
    manifest = AnalysisEvidenceManifest(
        evidence=(
            AnalysisEvidence(
                analysisId="analysis_001",
                summary="冻结证据",
                datasetIds=("dataset-1", "dataset-2"),
                evidenceFiles=(_identity("analysis/evidence.json"),),
                citationIds=("c1", "c2"),
            ),
        ),
        metricDefinitions=(
            MetricDefinition(
                code="revenue",
                name="收入",
                definition="收入合计",
                unit="元",
                periodBasis="2026-01",
            ),
        ),
        datasetSemantics=(
            AnalysisDatasetSemantics(
                datasetId="dataset-1",
                rowGrain="record",
                duplicateResolution=duplicate_resolution,
            ),
            AnalysisDatasetSemantics(
                datasetId="dataset-2",
                rowGrain="record",
                duplicateResolution="not_applicable",
            ),
        ),
    )
    artifact = SectionArtifact(
        sectionCode="s1",
        blocks=(
            ReportDraftBlock(
                blockId="b1",
                markdown="收入结论。",
                citationIds=claim.citation_ids,
                claimIds=(claim.claim_id,),
            ),
        ),
        claims=(claim,),
    )
    citations = (
        SectionCitation(
            citationId="c1", datasetId="dataset-1", requirementId="r1", snapshotHash="1" * 64
        ),
        SectionCitation(
            citationId="c2", datasetId="dataset-2", requirementId="r2", snapshotHash="2" * 64
        ),
    )
    return manifest, (artifact,), citations


@pytest.mark.parametrize(
    "claim,duplicate_resolution,code",
    [
        (
            SectionClaim(
                claimId="claim-period",
                metricCode="revenue",
                value=1,
                periodBasis="2026累计",
                managementQuestion="收入如何？",
                currentPeriod="2026-01",
                citationIds=("c1",),
            ),
            "not_applicable",
            "report_period_basis_conflict",
        ),
        (
            SectionClaim(
                claimId="claim-duplicate",
                metricCode="revenue",
                value=1,
                periodBasis="2026-01",
                managementQuestion="收入如何？",
                currentPeriod="2026-01",
                citationIds=("c1",),
            ),
            "unresolved",
            "report_aggregation_duplicate_unresolved",
        ),
        (
            SectionClaim(
                claimId="claim-grain",
                metricCode="revenue",
                value="50%",
                periodBasis="2026-01",
                managementQuestion="收入如何？",
                currentPeriod="2026-01",
                citationIds=("c1",),
                conclusionType="entity_ratio",
                aggregationGrain="record",
                entityGrain="project",
            ),
            "not_applicable",
            "report_entity_grain_unproven",
        ),
        (
            SectionClaim(
                claimId="claim-cross-source",
                metricCode="revenue",
                value="10%",
                periodBasis="2026-01",
                managementQuestion="收入如何？",
                currentPeriod="2026-01",
                citationIds=("c1", "c2"),
                conclusionType="profit",
                comparability="reference_only",
            ),
            "not_applicable",
            "report_cross_source_inference_unsupported",
        ),
    ],
)
def test_semantic_publication_issues_block_release(
    claim: SectionClaim, duplicate_resolution: str, code: str
) -> None:
    manifest, artifacts, citations = _semantic_inputs(
        claim=claim,
        duplicate_resolution=duplicate_resolution,
    )
    gate = evaluate_publication_semantics(
        evidence_manifest=manifest,
        section_artifacts=artifacts,
        citations=citations,
    )
    assert gate["formalReleaseAllowed"] is False
    assert code in {item["code"] for item in gate["issues"]}


def test_unreferenced_quality_warning_does_not_block_release() -> None:
    claim = SectionClaim(
        claimId="claim-ok",
        metricCode="revenue",
        value=1,
        periodBasis="2026-01",
        managementQuestion="收入如何？",
        currentPeriod="2026-01",
        citationIds=("c2",),
    )
    manifest, artifacts, citations = _semantic_inputs(
        claim=claim,
        duplicate_resolution="unresolved",
    )
    gate = evaluate_publication_semantics(
        evidence_manifest=manifest,
        section_artifacts=artifacts,
        citations=citations,
    )
    assert gate["formalReleaseAllowed"] is True
