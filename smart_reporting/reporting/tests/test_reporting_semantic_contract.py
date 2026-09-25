from types import SimpleNamespace

import pytest

from smart_reporting.quality_warnings import QualityAuditCollector
from smart_reporting.reporting.delivery.artifacts_v1 import Citation
from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
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
from smart_reporting.reporting.workflow.runtime.analysis import _finalize_semantic_catalog
from smart_reporting.reporting.workflow.runtime.publication import (
    _publication_warning_notice,
    evaluate_publication_semantics,
)
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin


def test_non_v1_artifact_fails_closed() -> None:
    with pytest.raises(ReportingError, match="report_semantic_contract_upgrade_required"):
        read_analysis_artifact({"version": "2"})


def test_v1_artifact_rejects_incomplete_nested_manifest() -> None:
    with pytest.raises(ValueError, match="AnalysisEvidenceManifest 必须冻结 Dataset 语义"):
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


def test_v1_artifact_uses_unified_schema() -> None:
    payload = {
        "version": "1",
        "reportBrief": {
            "objective": "目标",
            "executiveSummary": "摘要",
            "managementQuestions": ["收入如何？"],
        },
        "evidenceManifest": {
            "version": "1",
            "evidence": [{"analysisId": "analysis_001", "datasetIds": ["d1"]}],
            "datasetSemantics": [
                {"datasetId": "d1", "rowGrain": "row", "duplicateResolution": "resolved"}
            ],
        },
    }
    with pytest.raises(ValueError):
        read_analysis_artifact(payload)


def test_v1_checkpoint_is_valid() -> None:
    checkpoint = ReportingCheckpoint.model_validate(
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
    assert checkpoint.version == "1"


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


def test_legacy_chart_visual_inspection_receipt_defaults_to_vision_passed() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="analysis/charts/x.png",
        sha256="0" * 64,
        modelId="vision-model",
        reviewed=True,
        requiresRevision=False,
    )

    assert receipt.inspection_mode == "vision"
    assert receipt.visual_review_status == "passed"
    assert receipt.inspector_id is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"inspectionMode": "vision", "visualReviewStatus": "not_run"},
        {
            "inspectionMode": "deterministic",
            "visualReviewStatus": "passed",
            "modelId": None,
            "inspectorId": "deterministic-raster-inspector-v1",
        },
        {
            "inspectionMode": "deterministic",
            "visualReviewStatus": "not_run",
            "modelId": None,
            "inspectorId": "deterministic-raster-inspector-v1",
            "issues": (
                {
                    "category": "cropping",
                    "severity": "warning",
                    "description": "视觉问题",
                },
            ),
        },
        {
            "inspectionMode": "deterministic",
            "visualReviewStatus": "not_run",
            "modelId": None,
            "inspectorId": "deterministic-raster-inspector-v1",
            "suggestions": ("调整布局",),
        },
        {"inspectionMode": "vision", "visualReviewStatus": "passed", "modelId": None},
    ],
)
def test_chart_visual_inspection_receipt_rejects_inconsistent_mode(
    overrides: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "sourcePath": "analysis/charts/x.png",
        "sha256": "0" * 64,
        "modelId": "vision-model",
        "reviewed": True,
        "requiresRevision": False,
    }
    payload.update(overrides)

    with pytest.raises(ValueError):
        ChartVisualInspectionReceipt.model_validate(payload)


def test_deterministic_chart_visual_inspection_receipt_is_honest() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="analysis/charts/x.png",
        sha256="0" * 64,
        inspectionMode="deterministic",
        visualReviewStatus="not_run",
        inspectorId="deterministic-raster-inspector-v1",
        modelId=None,
        reviewed=True,
        requiresRevision=False,
        warnings=("未运行模型视觉审查。",),
    )

    assert receipt.model_id is None
    assert receipt.visual_review_status == "not_run"


def test_v1_manifest_requires_every_chart_visual_inspection_receipt() -> None:
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


def test_manifest_warns_chart_metric_without_definition() -> None:
    manifest = AnalysisEvidenceManifest(
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
        metricDefinitions=(),
        charts=(
            AnalysisChart(
                chartId="chart-1",
                sourceFile={"path": "analysis/charts/x.png", "size": 1, "sha256": "0" * 64},
                title="收入",
                altText="收入",
                citationIds=("c1",),
                metricCodes=("income_total",),
                currentPeriod="2026-01",
                comparisonType="none",
                sourceDatasetId="dataset-1",
                aggregationGrain="month",
                visualInspectionReceipt=ChartVisualInspectionReceipt(
                    sourcePath="analysis/charts/x.png",
                    sha256="0" * 64,
                    inspectionMode="deterministic",
                    visualReviewStatus="not_run",
                    inspectorId="deterministic-raster-inspector-v1",
                    modelId=None,
                    reviewed=True,
                    requiresRevision=False,
                ),
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
    gate = evaluate_publication_semantics(
        evidence_manifest=manifest,
        section_artifacts=(),
        citations=(
            SectionCitation(
                citationId="c1", datasetId="dataset-1", requirementId="r1", snapshotHash="0" * 64
            ),
        ),
    )
    assert any(item["code"] == "report_chart_metric_unfrozen" for item in gate["warnings"])


def test_manifest_warns_chart_dataset_without_frozen_evidence() -> None:
    manifest = AnalysisEvidenceManifest(
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
        metricDefinitions=(),
        charts=(
            AnalysisChart(
                chartId="chart-1",
                sourceFile={"path": "analysis/charts/x.png", "size": 1, "sha256": "0" * 64},
                title="收入",
                altText="收入",
                citationIds=("c1",),
                metricCodes=("income_total",),
                currentPeriod="2026-01",
                comparisonType="none",
                sourceDatasetId="dataset-2",
                aggregationGrain="month",
                visualInspectionReceipt=ChartVisualInspectionReceipt(
                    sourcePath="analysis/charts/x.png",
                    sha256="0" * 64,
                    inspectionMode="deterministic",
                    visualReviewStatus="not_run",
                    inspectorId="deterministic-raster-inspector-v1",
                    modelId=None,
                    reviewed=True,
                    requiresRevision=False,
                ),
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

    gate = evaluate_publication_semantics(
        evidence_manifest=manifest,
        section_artifacts=(),
        citations=(
            SectionCitation(
                citationId="c1", datasetId="dataset-1", requirementId="r1", snapshotHash="0" * 64
            ),
        ),
    )

    assert gate["formalReleaseAllowed"] is True
    assert gate["issues"] == []
    assert {
        (item["code"], item["details"]["chartId"], item["details"]["datasetId"])
        for item in gate["warnings"]
        if item["code"] == "report_chart_dataset_unfrozen"
    } == {("report_chart_dataset_unfrozen", "chart-1", "dataset-2")}
    # 发布门禁把每条 warning 送入质量审计；未登记的规则码会把软告警升级为发布阻断。
    audit = QualityAuditCollector(report_run_id="run-1", revision=1)
    for item in gate["warnings"]:
        audit.add(_publication_warning_notice(item, run_id="run-1", source_phase="publication"))
    assert "report_chart_dataset_unfrozen" in {
        finding.rule_code for finding in audit.build().findings
    }


def test_semantic_catalog_registers_metric_field_alias() -> None:
    _dataset_semantics, metric_definitions, findings = _finalize_semantic_catalog(
        analysis_plans={
            "analysis_001": {
                "datasetIds": ["dataset-1"],
                "organizationGrain": ["month"],
            }
        },
        fact_bundles={
            "analysis_001": {
                "metrics": [
                    {
                        "field": "budget_medical_income",
                        "metricCodes": ["budget_income"],
                        "formula": "sum(budget_medical_income)",
                        "unit": "元",
                        "periodStart": "2025-01-01",
                        "periodEnd": "2025-10-01",
                    }
                ]
            }
        },
        dataset_ids=("dataset-1",),
    )

    assert [item["code"] for item in metric_definitions] == [
        "budget_income",
        "budget_medical_income",
    ]
    assert findings == []


def test_section_block_claim_reference_must_exist() -> None:
    with pytest.raises(ValueError, match="claim"):
        SectionArtifact(
            sectionCode="s1",
            blocks=(ReportDraftBlock(blockId="b1", markdown="正文", claimIds=("missing",)),),
            claims=(),
        )


def _identity(path: str) -> FileIdentity:
    return FileIdentity(path=path, size=1, sha256="0" * 64)


def test_section_work_item_uses_charts_from_section_scoped_artifact() -> None:
    chart = AnalysisChart(
        chartId="chart-1",
        sourceFile=_identity("analysis/charts/income.png"),
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("c1",),
        metricCodes=("income_total",),
        currentPeriod="2026-01",
        comparisonType="none",
        sourceDatasetId="dataset-1",
        aggregationGrain="month",
        visualInspectionReceipt=ChartVisualInspectionReceipt(
            sourcePath="analysis/charts/income.png",
            sha256="0" * 64,
            inspectionMode="deterministic",
            visualReviewStatus="not_run",
            inspectorId="deterministic-raster-inspector-v1",
            modelId=None,
            reviewed=True,
            requiresRevision=False,
        ),
    )
    artifact = AnalysisArtifact(
        reportBrief=ReportBrief(
            objective="分析收入",
            executiveSummary="收入摘要",
            managementQuestions=("收入如何？",),
        ),
        evidenceManifest=AnalysisEvidenceManifest(
            evidence=(
                AnalysisEvidence(
                    analysisId="analysis_001",
                    summary="冻结证据",
                    datasetIds=("dataset-1",),
                    evidenceFiles=(_identity("analysis/evidence.json"),),
                    citationIds=("c1",),
                    metrics=("indicator_value",),
                    chartIds=(),
                ),
            ),
            metricDefinitions=(
                MetricDefinition(
                    code="income_total",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2026-01",
                ),
            ),
            charts=(chart,),
            datasetSemantics=(
                AnalysisDatasetSemantics(
                    datasetId="dataset-1",
                    rowGrain="record",
                    duplicateResolution="not_applicable",
                ),
            ),
        ),
    )
    plan = DetailedAnalysisPlan.model_validate(
        {
            "analyses": [
                {
                    "analysisId": "analysis_001",
                    "domain": "hospital_operation",
                    "managementQuestion": "收入如何？",
                    "primaryMetricFamily": "income",
                    "datasetIds": ["dataset-1"],
                    "fields": ["indicator_value"],
                    "metrics": ["indicator_value"],
                    "periods": ["2026-01"],
                    "actions": ["sum"],
                    "evidenceSummary": "收入证据",
                    "suggestedSection": "section_001",
                    "completionConditions": ["给出收入结论"],
                }
            ],
            "datasetIds": ["dataset-1"],
        }
    )

    work_item = RuntimeSectionsMixin._build_section_work_item(
        SimpleNamespace(
            code="section_001",
            section_number="1",
            title="收入分析",
            focus=(),
            analysis_ids=("analysis_001",),
        ),
        detailed_plan=plan,
        analysis_artifact=artifact,
        citation_bindings=(
            Citation(
                citationId="c1",
                datasetId="dataset-1",
                requirementId="r1",
                snapshotHash="1" * 64,
            ),
        ),
    )

    assert [item.chart_id for item in work_item.charts] == ["chart-1"]
    assert [item.code for item in work_item.metric_definitions] == ["income_total"]


def test_unused_chart_warning_uses_report_audit_subject() -> None:
    notice = _publication_warning_notice(
        {
            "code": "unused_chart_excluded",
            "message": "未被正文引用的图表已从发布包排除。",
            "chartIds": ["chart-1"],
        },
        run_id="report-1",
        source_phase="publication",
    )
    audit = QualityAuditCollector(report_run_id="report-1", revision=1)
    audit.add(notice)

    result = audit.build()

    assert notice.subject_type == "report"
    assert result.total == 1
    assert result.by_disposition == {"quality_warning": 1}


@pytest.mark.parametrize(
    ("warning", "expected_subject_type", "expected_subject_id"),
    [
        (
            {
                "code": "report_section_chart_auto_bound",
                "message": "图表已自动绑定正文 block。",
                "details": {"blockId": "block-1", "chartId": "chart-1"},
            },
            "section_block",
            "block-1",
        ),
        (
            {
                "code": "report_section_chart_unbound",
                "message": "图表未绑定正文 block。",
                "details": {"chartId": "chart-1"},
            },
            "analysis_chart",
            "chart-1",
        ),
        (
            {
                "code": "report_section_chart_citation_unknown",
                "message": "图表引用了未知 citation。",
                "details": {"blockId": "block-1", "chartId": "chart-1"},
            },
            "section_block",
            "block-1",
        ),
        (
            {
                "code": "report_section_chart_duplicate_binding",
                "message": "同一图表重复绑定。",
                "details": {
                    "chartId": "chart-1",
                    "firstBlockId": "block-1",
                    "duplicateBlockId": "block-2",
                },
            },
            "analysis_chart",
            "chart-1",
        ),
    ],
)
def test_section_chart_warning_uses_registered_production_subject(
    warning: dict[str, object], expected_subject_type: str, expected_subject_id: str
) -> None:
    notice = _publication_warning_notice(
        warning,
        run_id="report-1",
        source_phase="publication",
    )

    assert notice.subject_type == expected_subject_type
    assert notice.subject_id == expected_subject_id


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
def test_semantic_publication_claim_issues_are_warnings(
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
    assert gate["formalReleaseAllowed"] is True
    assert gate["issues"] == []
    assert code in {item["code"] for item in gate["warnings"]}


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
