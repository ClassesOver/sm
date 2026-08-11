from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agentos_dev.coding.reporting.delivery.acceptance import (
    build_report_phase_acceptance_contract,
)
from agentos_dev.coding.reporting.workflow.checkpoint import (
    AnalysisChart,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageManifest,
    ProfileReadReceipt,
    ReportBrief,
    ReportingCheckpoint,
    SectionCitation,
    SectionWorkItem,
    build_profile_coverage_manifest,
    reporting_phase_task_key,
)
from agentos_dev.coding.reporting.workflow.execution import _worker_session_id
from agentos_dev.task_execution import TaskScope
from agentos_dev.task_execution.acceptance import normalize_acceptance_contract


def _file(path: str, marker: str = "a") -> FileIdentity:
    return FileIdentity(path=path, size=128, sha256=marker * 64)


def test_profile_coverage_manifest精确覆盖全部授权dataset和字段() -> None:
    manifest = build_profile_coverage_manifest(
        dataset_handles=(
            {
                "datasetId": "dataset-1",
                "path": "data/one.csv",
                "size": 10,
                "sha256": "1" * 64,
                "rowCount": 2,
            },
            {
                "datasetId": "dataset-2",
                "path": "data/two.csv",
                "size": 20,
                "sha256": "2" * 64,
                "rowCount": 3,
            },
        ),
        dataset_contexts=(
            {
                "datasetId": "dataset-1",
                "fields": ["period", "amount"],
                "rowCount": 2,
                "profileFile": {
                    "path": "profiles/one.json",
                    "size": 100,
                    "sha256": "a" * 64,
                },
            },
            {
                "datasetId": "dataset-2",
                "fields": ["period", "department", "cost"],
                "rowCount": 3,
                "profileFile": {
                    "path": "profiles/two.json",
                    "size": 200,
                    "sha256": "b" * 64,
                },
            },
        ),
    )

    assert manifest.authorized_dataset_count == 2
    assert manifest.covered_dataset_count == 2
    assert manifest.dataset_ids == ("dataset-1", "dataset-2")
    assert manifest.datasets[1].fields == ("period", "department", "cost")
    assert manifest.datasets[1].field_count == 3


def test_profile_coverage_manifest拒绝缺失dataset或字段() -> None:
    with pytest.raises(ValueError, match="精确覆盖"):
        build_profile_coverage_manifest(
            dataset_handles=(
                {
                    "datasetId": "dataset-1",
                    "path": "data/one.csv",
                    "size": 10,
                    "sha256": "1" * 64,
                    "rowCount": 2,
                },
            ),
            dataset_contexts=(),
        )

    with pytest.raises(ValidationError, match="字段"):
        ProfileCoverageManifest.model_validate(
            {
                "authorizedDatasetCount": 1,
                "coveredDatasetCount": 1,
                "datasets": [
                    {
                        "datasetId": "dataset-1",
                        "datasetPath": "data/one.csv",
                        "datasetSize": 10,
                        "datasetSnapshotHash": "1" * 64,
                        "profileFile": _file("profiles/one.json").model_dump(
                            mode="json", by_alias=True
                        ),
                        "rowCount": 2,
                        "fieldCount": 2,
                        "fields": ["period"],
                    }
                ],
            }
        )


def test_analysis与章节task使用互不复用的agno_session() -> None:
    analysis_task = reporting_phase_task_key("workflow-run", 1, "analysis")
    income_task = reporting_phase_task_key("workflow-run", 1, "section", section_code="income")
    cost_task = reporting_phase_task_key("workflow-run", 1, "section", section_code="cost")
    scopes = [
        TaskScope(task_id, "user", "thread", "sandbox", "report-worker")
        for task_id in (analysis_task, income_task, cost_task)
    ]

    assert len({item.external_run_id for item in scopes}) == 3
    assert len({_worker_session_id(item) for item in scopes}) == 3
    assert all(item.external_run_id.startswith("report-coding-") for item in scopes)


def test_phase_acceptance首个requirement携带受信阶段参数() -> None:
    contract = build_report_phase_acceptance_contract(
        phase="section",
        validation_context_file=_file("contexts/validation.json").model_dump(
            mode="json", by_alias=True
        ),
        phase_contract={
            "sectionWorkItemFile": _file("contexts/income-work-item.json").model_dump(
                mode="json", by_alias=True
            )
        },
        section_output_path="sections/income.json",
        rework_request_path="sections/income.rework.json",
    )

    normalized = normalize_acceptance_contract(contract)
    requirement = normalized["requirements"][0]
    assert requirement["parameters"]["phase"] == "section"
    assert requirement["parameters"]["phaseContract"]["sectionWorkItemFile"]["sha256"] == "a" * 64
    assert requirement["artifactPatterns"] == [
        "sections/income.json",
        "sections/income.rework.json",
    ]


def test_section_work_item保留当前章完整证据口径profile回执和引用() -> None:
    receipt = ProfileReadReceipt.create(
        dataset_id="dataset-1",
        profile_pointer="/variables/amount/histogram",
        snapshot_hash="a" * 64,
        purpose="核验收入分布与异常值",
    )
    metric = MetricDefinition(
        code="income_amount",
        name="医疗收入",
        definition="本期医疗收入求和",
        unit="元",
        periodBasis="自然月",
    )
    evidence = AnalysisEvidence(
        analysisId="analysis_001",
        summary="收入规模、同比与异常科室均已复算。",
        datasetIds=("dataset-1",),
        evidenceFiles=(_file("evidence/income.json"),),
        citationIds=("citation_001",),
        chartIds=("income_trend",),
        profileReadReceiptIds=(receipt.receipt_id,),
    )
    chart = AnalysisChart(
        chartId="income_trend",
        sourceFile=_file("charts/income.png", "c"),
        title="医疗收入月度趋势",
        altText="医疗收入按月变化",
        citationIds=("citation_001",),
    )
    work_item = SectionWorkItem(
        sectionCode="income",
        title="收入规模与趋势",
        objective="解释收入变化及主要贡献对象。",
        completionConditions=("给出规模、趋势、同比和异常",),
        analysisIds=("analysis_001",),
        evidence=(evidence,),
        metricDefinitions=(metric,),
        profileReadReceipts=(receipt,),
        charts=(chart,),
        citations=(
            SectionCitation(
                citationId="citation_001",
                datasetId="dataset-1",
                requirementId="income-monthly",
                snapshotHash="d" * 64,
            ),
        ),
        markdownRequirements=("章节内部标题从三级标题开始",),
    )

    serialized = work_item.model_dump(mode="json", by_alias=True)
    assert serialized["evidence"][0]["summary"] == evidence.summary
    assert serialized["metricDefinitions"][0]["definition"] == metric.definition
    assert serialized["profileReadReceipts"][0]["purpose"] == receipt.purpose
    assert serialized["citations"][0]["snapshotHash"] == "d" * 64


def test_reporting_checkpoint可从任意章节状态严格恢复() -> None:
    coverage = ProfileCoverageManifest.model_validate(
        {
            "authorizedDatasetCount": 1,
            "coveredDatasetCount": 1,
            "datasets": [
                {
                    "datasetId": "dataset-1",
                    "datasetPath": "data/one.csv",
                    "datasetSize": 10,
                    "datasetSnapshotHash": "1" * 64,
                    "profileFile": _file("profiles/one.json").model_dump(
                        mode="json", by_alias=True
                    ),
                    "rowCount": 2,
                    "fieldCount": 2,
                    "fields": ["period", "amount"],
                }
            ],
        }
    )
    brief = ReportBrief(
        objective="形成年度运营管理报告。",
        executiveSummary="分析层已完成全局规模、结构和趋势判断。",
        managementQuestions=("收入增长来自哪里？",),
    )
    evidence_manifest = AnalysisEvidenceManifest(
        evidence=(
            AnalysisEvidence(
                analysisId="analysis_001",
                summary="已完成收入分析。",
                datasetIds=("dataset-1",),
                evidenceFiles=(_file("evidence/income.json"),),
                citationIds=("citation_001",),
            ),
        ),
    )
    checkpoint = ReportingCheckpoint(
        revision=1,
        phase="sections",
        outlineHash=hashlib.sha256(b"outline").hexdigest(),
        profileCoverage=coverage,
        reportBrief=brief,
        evidenceManifest=evidence_manifest,
        analysisManifestFile=_file("analysis/manifest.json"),
        completedSections=(
            {
                "sectionCode": "summary",
                "workItemHash": "e" * 64,
                "artifactFile": _file("sections/summary.json"),
                "retryCount": 0,
            },
        ),
        pendingSections=("income", "cost"),
    )

    restored = ReportingCheckpoint.model_validate(checkpoint.model_dump(mode="json", by_alias=True))

    assert restored == checkpoint
    assert restored.completed_sections[0].section_code == "summary"
    assert restored.pending_sections == ("income", "cost")
