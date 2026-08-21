"""Reporting 分阶段执行的持久化 checkpoint 与上下文投影契约。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..delivery.draft_v1 import ReportDraftBlock


class FileIdentity(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(gt=0, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("文件路径必须是安全的工作区相对路径")
        return path.as_posix()


class ProfileCoverageDataset(StrictModel):
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    dataset_path: str = Field(alias="datasetPath", min_length=1, max_length=1024)
    dataset_size: int = Field(alias="datasetSize", gt=0)
    dataset_snapshot_hash: str = Field(alias="datasetSnapshotHash", pattern=SHA256_PATTERN)
    profile_file: FileIdentity = Field(alias="profileFile")
    row_count: int = Field(alias="rowCount", ge=0)
    field_count: int = Field(alias="fieldCount", ge=1, le=500)
    fields: tuple[str, ...] = Field(min_length=1, max_length=500)
    period_coverage: tuple[str, ...] = Field(default=(), alias="periodCoverage", max_length=1200)
    source_warnings: tuple[str, ...] = Field(default=(), alias="sourceWarnings", max_length=100)
    quality_warnings: tuple[str, ...] = Field(default=(), alias="qualityWarnings", max_length=100)

    @model_validator(mode="after")
    def validate_fields(self) -> ProfileCoverageDataset:
        if (
            self.field_count != len(self.fields)
            or len(self.fields) != len(set(self.fields))
            or any(not item for item in self.fields)
        ):
            raise ValueError("Profile coverage 字段必须完整、不重复且与 fieldCount 一致")
        if len(self.period_coverage) != len(set(self.period_coverage)) or any(
            not item for item in self.period_coverage
        ):
            raise ValueError("Profile periodCoverage 不能为空或重复")
        return self


class ProfileCoverageManifest(StrictModel):
    version: Literal["1"] = "1"
    authorized_dataset_count: int = Field(alias="authorizedDatasetCount", ge=1, le=100)
    covered_dataset_count: int = Field(alias="coveredDatasetCount", ge=1, le=100)
    datasets: tuple[ProfileCoverageDataset, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_coverage(self) -> ProfileCoverageManifest:
        dataset_ids = [item.dataset_id for item in self.datasets]
        if (
            self.authorized_dataset_count != len(self.datasets)
            or self.covered_dataset_count != len(self.datasets)
            or len(dataset_ids) != len(set(dataset_ids))
        ):
            raise ValueError("ProfileCoverageManifest 必须精确覆盖全部授权 Dataset")
        return self


class ProfileReadReceipt(StrictModel):
    receipt_id: str = Field(alias="receiptId", pattern=r"^profile-read-[0-9a-f]{24}$")
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    profile_pointer: str | None = Field(
        default=None, alias="profilePointer", min_length=1, max_length=1024
    )
    query: str | None = Field(default=None, min_length=1, max_length=1024)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=SHA256_PATTERN)
    purpose: str = Field(min_length=1, max_length=1000)

    @field_validator("profile_pointer")
    @classmethod
    def validate_pointer(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("Profile Pointer 必须是 RFC 6901 绝对指针")
        return value

    @model_validator(mode="after")
    def validate_locator(self) -> ProfileReadReceipt:
        if (self.profile_pointer is None) == (self.query is None):
            raise ValueError("ProfileReadReceipt 必须且只能包含 profilePointer 或 query")
        return self

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        profile_pointer: str,
        snapshot_hash: str,
        purpose: str,
    ) -> ProfileReadReceipt:
        payload = json.dumps(
            [dataset_id, profile_pointer, snapshot_hash],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            receiptId=f"profile-read-{hashlib.sha256(payload).hexdigest()[:24]}",
            datasetId=dataset_id,
            profilePointer=profile_pointer,
            snapshotHash=snapshot_hash,
            purpose=purpose,
        )

    @classmethod
    def create_query(
        cls,
        *,
        dataset_id: str,
        query: str,
        snapshot_hash: str,
        purpose: str,
    ) -> ProfileReadReceipt:
        payload = json.dumps(
            [dataset_id, "jmespath", query, snapshot_hash],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            receiptId=f"profile-read-{hashlib.sha256(payload).hexdigest()[:24]}",
            datasetId=dataset_id,
            query=query,
            snapshotHash=snapshot_hash,
            purpose=purpose,
        )


class MetricDefinition(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    period_basis: str = Field(alias="periodBasis", min_length=1, max_length=500)


class ReportBrief(StrictModel):
    objective: str = Field(min_length=1, max_length=4000)
    executive_summary: str = Field(alias="executiveSummary", min_length=1, max_length=8000)
    management_questions: tuple[str, ...] = Field(
        alias="managementQuestions", min_length=1, max_length=100
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=500)


class AnalysisEvidence(StrictModel):
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    summary: str = Field(min_length=1, max_length=8000)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=100)
    evidence_files: tuple[FileIdentity, ...] = Field(
        alias="evidenceFiles", min_length=1, max_length=50
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    chart_ids: tuple[str, ...] = Field(default=(), alias="chartIds", max_length=100)
    profile_read_receipt_ids: tuple[str, ...] = Field(
        default=(), alias="profileReadReceiptIds", max_length=500
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_references(self) -> AnalysisEvidence:
        for name, values in (
            ("datasetIds", self.dataset_ids),
            ("citationIds", self.citation_ids),
            ("chartIds", self.chart_ids),
            ("profileReadReceiptIds", self.profile_read_receipt_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} 不能重复")
        paths = [item.path for item in self.evidence_files]
        if len(paths) != len(set(paths)):
            raise ValueError("evidenceFiles 路径不能重复")
        return self


class AnalysisChart(StrictModel):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_file: FileIdentity = Field(alias="sourceFile")
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)

    @field_validator("citation_ids")
    @classmethod
    def validate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("图表 citationIds 不能重复")
        return value


class AnalysisEvidenceManifest(StrictModel):
    version: Literal["1"] = "1"
    evidence: tuple[AnalysisEvidence, ...] = Field(min_length=1, max_length=200)
    metric_definitions: tuple[MetricDefinition, ...] = Field(
        default=(), alias="metricDefinitions", max_length=500
    )
    charts: tuple[AnalysisChart, ...] = Field(default=(), max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_manifest(self) -> AnalysisEvidenceManifest:
        analysis_ids = [item.analysis_id for item in self.evidence]
        metric_codes = [item.code for item in self.metric_definitions]
        chart_ids = [item.chart_id for item in self.charts]
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ValueError("AnalysisEvidenceManifest analysisId 不能重复")
        if len(metric_codes) != len(set(metric_codes)):
            raise ValueError("MetricDefinition code 不能重复")
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("AnalysisChart chartId 不能重复")
        known_charts = set(chart_ids)
        if any(set(item.chart_ids) - known_charts for item in self.evidence):
            raise ValueError("analysis evidence 引用了未登记图表")
        return self


class AnalysisArtifact(StrictModel):
    version: Literal["1"] = "1"
    report_brief: ReportBrief = Field(alias="reportBrief")
    evidence_manifest: AnalysisEvidenceManifest = Field(alias="evidenceManifest")
    profile_read_receipts: tuple[ProfileReadReceipt, ...] = Field(
        default=(), alias="profileReadReceipts", max_length=1000
    )
    profile_read_receipt_ids: tuple[str, ...] = Field(
        default=(), alias="profileReadReceiptIds", max_length=1000
    )


class SectionCitation(StrictModel):
    citation_id: str = Field(alias="citationId", min_length=1, max_length=128)
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=SHA256_PATTERN)


class SectionWorkItem(StrictModel):
    version: Literal["1"] = "1"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    completion_conditions: tuple[str, ...] = Field(
        alias="completionConditions", min_length=1, max_length=100
    )
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=2000)
    evidence: tuple[AnalysisEvidence, ...] = Field(min_length=1, max_length=200)
    metric_definitions: tuple[MetricDefinition, ...] = Field(
        default=(), alias="metricDefinitions", max_length=500
    )
    profile_read_receipts: tuple[ProfileReadReceipt, ...] = Field(
        default=(), alias="profileReadReceipts", max_length=1000
    )
    profile_read_receipt_ids: tuple[str, ...] = Field(
        default=(), alias="profileReadReceiptIds", max_length=1000
    )
    charts: tuple[AnalysisChart, ...] = Field(default=(), max_length=100)
    citations: tuple[SectionCitation, ...] = Field(min_length=1, max_length=2000)
    fact_files: tuple[FileIdentity, ...] = Field(default=(), alias="factFiles", max_length=200)
    fact_summaries: tuple[str, ...] = Field(default=(), alias="factSummaries", max_length=200)
    markdown_requirements: tuple[str, ...] = Field(
        alias="markdownRequirements", min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def validate_projection(self) -> SectionWorkItem:
        evidence_ids = tuple(item.analysis_id for item in self.evidence)
        if evidence_ids != self.analysis_ids or len(self.analysis_ids) != len(
            set(self.analysis_ids)
        ):
            raise ValueError("SectionWorkItem evidence 必须按顺序精确覆盖 analysisIds")
        known_receipts = {
            *self.profile_read_receipt_ids,
            *(item.receipt_id for item in self.profile_read_receipts),
        }
        if len(known_receipts) != (
            len(self.profile_read_receipt_ids) + len(self.profile_read_receipts)
        ):
            raise ValueError("SectionWorkItem ProfileReadReceipt 不能重复")
        known_charts = {item.chart_id for item in self.charts}
        known_citations = {item.citation_id for item in self.citations}
        for item in self.evidence:
            if set(item.profile_read_receipt_ids) - known_receipts:
                raise ValueError("SectionWorkItem 缺少 evidence 引用的 ProfileReadReceipt")
            if set(item.chart_ids) - known_charts:
                raise ValueError("SectionWorkItem 缺少 evidence 引用的 chart")
            if set(item.citation_ids) - known_citations:
                raise ValueError("SectionWorkItem 缺少 evidence 引用的 citation")
        return self

    def serialized_bytes(self) -> int:
        return len(
            json.dumps(
                self.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )


class SectionArtifact(StrictModel):
    version: Literal["1"] = "1"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)


class AnalysisReworkRequest(StrictModel):
    version: Literal["1"] = "1"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    missing_evidence: tuple[str, ...] = Field(alias="missingEvidence", min_length=1, max_length=100)


class CompletedSection(StrictModel):
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    work_item_hash: str = Field(alias="workItemHash", pattern=SHA256_PATTERN)
    artifact_file: FileIdentity = Field(alias="artifactFile")
    retry_count: int = Field(default=0, alias="retryCount", ge=0, le=10)


class CheckpointError(StrictModel):
    phase: Literal["analysis", "section", "finalize"]
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    section_code: str | None = Field(default=None, alias="sectionCode", max_length=128)
    retry_reason: str | None = Field(default=None, alias="retryReason", max_length=2000)


class ContextTrace(StrictModel):
    phase: Literal["analysis", "section", "finalize"]
    task_id: str | None = Field(default=None, alias="taskId", max_length=128)
    work_kind: Literal["analysis_item", "visualization", "section", "finalize"] | None = Field(
        default=None, alias="workKind"
    )
    analysis_id: str | None = Field(
        default=None, alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$"
    )
    section_code: str | None = Field(default=None, alias="sectionCode", max_length=128)
    attempt: int = Field(default=0, ge=0, le=100)
    status: Literal["started", "completed", "rework", "failed"] = "started"
    artifact_file: FileIdentity | None = Field(default=None, alias="artifactFile")
    instruction_bytes: int = Field(default=0, alias="instructionBytes", ge=0)
    projected_context_bytes: int = Field(default=0, alias="projectedContextBytes", ge=0)
    model_input_tokens: int | None = Field(default=None, alias="modelInputTokens", ge=0)
    model_request_count: int = Field(default=0, alias="modelRequestCount", ge=0)
    max_canonical_tokens: int = Field(default=0, alias="maxCanonicalTokens", ge=0)
    max_projected_tokens: int = Field(default=0, alias="maxProjectedTokens", ge=0)
    rebase_count: int = Field(default=0, alias="rebaseCount", ge=0)
    input_token_hard_cap: int = Field(default=0, alias="inputTokenHardCap", ge=0)
    completed_analysis_count: int = Field(default=0, alias="completedAnalysisCount", ge=0)
    tool_event_count: int = Field(default=0, alias="toolEventCount", ge=0)
    duration_seconds: float = Field(default=0.0, alias="durationSeconds", ge=0)
    pointer_receipt_ids: tuple[str, ...] = Field(
        default=(), alias="pointerReceiptIds", max_length=1000
    )
    retry_reason: str | None = Field(default=None, alias="retryReason", max_length=2000)


class ReportingCheckpoint(StrictModel):
    version: Literal["1"] = "1"
    revision: int = Field(ge=1)
    phase: Literal["analysis", "sections", "finalize", "completed"]
    outline_hash: str = Field(alias="outlineHash", pattern=SHA256_PATTERN)
    profile_coverage: ProfileCoverageManifest = Field(alias="profileCoverage")
    profile_read_receipts: tuple[ProfileReadReceipt, ...] = Field(
        default=(), alias="profileReadReceipts", max_length=1000
    )
    report_brief: ReportBrief | None = Field(default=None, alias="reportBrief")
    evidence_manifest: AnalysisEvidenceManifest | None = Field(
        default=None, alias="evidenceManifest"
    )
    analysis_manifest_file: FileIdentity | None = Field(default=None, alias="analysisManifestFile")
    completed_sections: tuple[CompletedSection, ...] = Field(
        default=(), alias="completedSections", max_length=100
    )
    pending_sections: tuple[str, ...] = Field(default=(), alias="pendingSections", max_length=100)
    warnings: tuple[dict[str, Any], ...] = Field(default=(), max_length=500)
    last_error: CheckpointError | None = Field(default=None, alias="lastError")
    files: tuple[FileIdentity, ...] = Field(default=(), max_length=500)
    trace: tuple[ContextTrace, ...] = Field(default=(), max_length=2000)

    @model_validator(mode="after")
    def validate_sections(self) -> ReportingCheckpoint:
        completed = [item.section_code for item in self.completed_sections]
        if len(completed) != len(set(completed)):
            raise ValueError("checkpoint completedSections 不能重复")
        if len(self.pending_sections) != len(set(self.pending_sections)):
            raise ValueError("checkpoint pendingSections 不能重复")
        if set(completed) & set(self.pending_sections):
            raise ValueError("checkpoint 章节不能同时处于完成和待生成状态")
        if self.phase != "analysis" and (
            self.report_brief is None
            or self.evidence_manifest is None
            or self.analysis_manifest_file is None
        ):
            raise ValueError("分析阶段完成后 checkpoint 必须包含冻结分析产物")
        return self


def build_profile_coverage_manifest(
    *,
    dataset_handles: Sequence[Mapping[str, Any]],
    dataset_contexts: Sequence[Mapping[str, Any]],
) -> ProfileCoverageManifest:
    """从同一批授权 Dataset 与 Profile 上下文生成精确 coverage，缺一即拒绝。"""

    handle_by_id = {
        str(item.get("datasetId")): item
        for item in dataset_handles
        if isinstance(item.get("datasetId"), str)
    }
    context_by_id = {
        str(item.get("datasetId")): item
        for item in dataset_contexts
        if isinstance(item.get("datasetId"), str)
    }
    if (
        not handle_by_id
        or len(handle_by_id) != len(dataset_handles)
        or len(context_by_id) != len(dataset_contexts)
        or set(handle_by_id) != set(context_by_id)
    ):
        raise ValueError("Profile coverage 没有精确覆盖全部授权 Dataset")

    datasets: list[ProfileCoverageDataset] = []
    for handle in dataset_handles:
        dataset_id = str(handle["datasetId"])
        context = context_by_id[dataset_id]
        fields = context.get("fields")
        if not isinstance(fields, (list, tuple)) or not fields:
            raise ValueError(f"Dataset {dataset_id} 的 Profile coverage 缺少字段")
        datasets.append(
            ProfileCoverageDataset.model_validate(
                {
                    "datasetId": dataset_id,
                    "datasetPath": handle.get("path"),
                    "datasetSize": handle.get("size"),
                    "datasetSnapshotHash": handle.get("sha256"),
                    "profileFile": context.get("profileFile"),
                    "rowCount": context.get("rowCount"),
                    "fieldCount": len(fields),
                    "fields": tuple(fields),
                    "periodCoverage": context.get("periodCoverage", ()),
                    "sourceWarnings": context.get("sourceWarnings", ()),
                    "qualityWarnings": context.get("qualityWarnings", ()),
                }
            )
        )
    return ProfileCoverageManifest(
        authorizedDatasetCount=len(dataset_handles),
        coveredDatasetCount=len(datasets),
        datasets=tuple(datasets),
    )


def reporting_phase_task_key(
    workflow_run_id: str,
    revision: int,
    phase: Literal["analysis", "section"],
    *,
    analysis_id: str | None = None,
    section_code: str | None = None,
    attempt: int = 0,
) -> str:
    if (
        revision < 1
        or attempt < 0
        or (phase == "section") != bool(section_code)
        or (phase == "section" and analysis_id is not None)
        or (phase == "analysis" and (not analysis_id or section_code is not None))
    ):
        raise ValueError("Reporting phase task identity 无效")
    payload = (
        f"{workflow_run_id}:{revision}:{phase}:{analysis_id or ''}:{section_code or ''}:{attempt}"
    ).encode()
    return f"report-coding-{hashlib.sha256(payload).hexdigest()[:40]}"


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
