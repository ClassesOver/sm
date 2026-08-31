"""Reporting 分阶段执行的持久化 checkpoint 与上下文投影契约。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..contract import SHA256_PATTERN, StrictModel
from ..delivery.draft_v1 import ReportDraftBlock
from ..models import ReportingError


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
    metrics: tuple[str, ...] = Field(default=(), max_length=100)
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
            ("metrics", self.metrics),
            ("chartIds", self.chart_ids),
            ("profileReadReceiptIds", self.profile_read_receipt_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} 不能重复")
        paths = [item.path for item in self.evidence_files]
        if len(paths) != len(set(paths)):
            raise ValueError("evidenceFiles 路径不能重复")
        return self


class ChartVisualInspectionIssue(StrictModel):
    category: Literal[
        "blank",
        "cropping",
        "text_overlap",
        "legend_occlusion",
        "missing_units",
        "misleading",
    ]
    severity: Literal["warning", "critical"]
    description: str = Field(min_length=1, max_length=500)


class ChartVisualInspectionReceipt(StrictModel):
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=1024)
    sha256: str = Field(pattern=SHA256_PATTERN)
    inspection_mode: Literal["vision", "deterministic"] = Field(
        default="vision", alias="inspectionMode"
    )
    visual_review_status: Literal["passed", "not_run"] = Field(
        default="passed", alias="visualReviewStatus"
    )
    inspector_id: str | None = Field(
        default=None, alias="inspectorId", min_length=1, max_length=256
    )
    model_id: str | None = Field(default=None, alias="modelId", min_length=1, max_length=256)
    reviewed: bool
    requires_revision: bool = Field(alias="requiresRevision")
    issues: tuple[ChartVisualInspectionIssue, ...] = Field(default=(), max_length=20)
    summary: str | None = Field(default=None, min_length=1, max_length=2000)
    warnings: tuple[str, ...] = Field(default=(), max_length=20)
    suggestions: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("图表视觉回执路径必须是安全工作区相对路径")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_inspection_mode(self) -> ChartVisualInspectionReceipt:
        if self.inspection_mode == "vision":
            if self.visual_review_status != "passed" or self.model_id is None:
                raise ValueError("vision 回执必须记录已通过的真实视觉模型审查")
            return self
        # 确定性检查只证明文件签名、解码和像素级门禁，不能携带或暗示模型视觉结论。
        # 固定 inspectorId 让下游可以稳定区分两类证据，禁止借用 modelId、issues 或
        # suggestions 把未执行的视觉审查包装成已通过。
        if (
            self.visual_review_status != "not_run"
            or self.inspector_id != "deterministic-raster-inspector-v1"
            or self.model_id is not None
            or self.reviewed is not True
            or self.requires_revision is not False
            or self.issues
            or self.suggestions
        ):
            raise ValueError("deterministic 回执只能记录确定性文件检查且不得声称视觉审查")
        return self


class AnalysisChart(StrictModel):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_file: FileIdentity = Field(alias="sourceFile")
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    source_dataset_id: str = Field(alias="sourceDatasetId", min_length=1, max_length=256)
    aggregation_grain: str = Field(alias="aggregationGrain", min_length=1, max_length=128)
    comparability: Literal["strict", "reference_only"] = "strict"
    visual_inspection_receipt: ChartVisualInspectionReceipt | None = Field(
        default=None, alias="visualInspectionReceipt"
    )

    @field_validator("citation_ids")
    @classmethod
    def validate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("图表 citationIds 不能重复")
        return value

    @model_validator(mode="after")
    def validate_semantics(self) -> AnalysisChart:
        if self.comparison_type != "none" and not self.comparison_period:
            raise ValueError("比较图表必须声明 comparisonPeriod")
        if self.comparability == "reference_only" and self.comparison_type in {"yoy", "mom"}:
            raise ValueError("reference_only 图表不得声明严格同比或环比")
        if self.comparability == "reference_only" and (
            "参考" not in self.title or "参考" not in self.alt_text
        ):
            raise ValueError("reference_only 图表标题和图注必须明确标记为参考")
        receipt = self.visual_inspection_receipt
        if receipt is not None and (
            receipt.source_path != self.source_file.path
            or receipt.sha256 != self.source_file.sha256
        ):
            raise ValueError("图表视觉检查回执与源文件身份不一致")
        return self


class AnalysisDatasetSemantics(StrictModel):
    """冻结影响指标聚合的 Dataset 粒度与确定性去重结论。"""

    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    row_grain: str = Field(alias="rowGrain", min_length=1, max_length=128)
    duplicate_resolution: Literal["not_applicable", "resolved", "unresolved"] = Field(
        alias="duplicateResolution"
    )


class AnalysisEvidenceManifest(StrictModel):
    version: Literal["1", "2"] = "2"
    evidence: tuple[AnalysisEvidence, ...] = Field(min_length=1, max_length=200)
    metric_definitions: tuple[MetricDefinition, ...] = Field(
        default=(), alias="metricDefinitions", max_length=500
    )
    charts: tuple[AnalysisChart, ...] = Field(default=(), max_length=100)
    dataset_semantics: tuple[AnalysisDatasetSemantics, ...] = Field(
        default=(), alias="datasetSemantics", max_length=100
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_manifest(self) -> AnalysisEvidenceManifest:
        analysis_ids = [item.analysis_id for item in self.evidence]
        metric_codes = [item.code for item in self.metric_definitions]
        chart_ids = [item.chart_id for item in self.charts]
        semantic_dataset_ids = [item.dataset_id for item in self.dataset_semantics]
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ValueError("AnalysisEvidenceManifest analysisId 不能重复")
        if len(metric_codes) != len(set(metric_codes)):
            raise ValueError("MetricDefinition code 不能重复")
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("AnalysisChart chartId 不能重复")
        if len(semantic_dataset_ids) != len(set(semantic_dataset_ids)):
            raise ValueError("AnalysisDatasetSemantics datasetId 不能重复")
        known_charts = set(chart_ids)
        known_metrics = set(metric_codes)
        known_datasets = {dataset_id for item in self.evidence for dataset_id in item.dataset_ids}
        if any(set(item.chart_ids) - known_charts for item in self.evidence):
            raise ValueError("analysis evidence 引用了未登记图表")
        if self.version == "2" and not self.dataset_semantics:
            raise ValueError("v2 AnalysisEvidenceManifest 必须冻结 Dataset 语义")
        if self.version == "2" and any(
            item.visual_inspection_receipt is None for item in self.charts
        ):
            raise ValueError("v2 AnalysisEvidenceManifest 每张图表必须绑定视觉检查回执")
        if any(set(item.metric_codes) - known_metrics for item in self.charts):
            raise ValueError("AnalysisChart 引用了未冻结指标")
        if any(item.source_dataset_id not in known_datasets for item in self.charts):
            raise ValueError("AnalysisChart 引用了未冻结 Dataset")
        if self.dataset_semantics and set(semantic_dataset_ids) != known_datasets:
            raise ValueError("AnalysisDatasetSemantics 必须精确覆盖 evidence Dataset")
        return self


class AnalysisArtifact(StrictModel):
    version: Literal["1", "2"] = "2"
    report_brief: ReportBrief = Field(alias="reportBrief")
    evidence_manifest: AnalysisEvidenceManifest = Field(alias="evidenceManifest")
    profile_read_receipts: tuple[ProfileReadReceipt, ...] = Field(
        default=(), alias="profileReadReceipts", max_length=1000
    )
    profile_read_receipt_ids: tuple[str, ...] = Field(
        default=(), alias="profileReadReceiptIds", max_length=1000
    )

    @model_validator(mode="after")
    def validate_nested_version(self) -> AnalysisArtifact:
        if self.version == "2" and self.evidence_manifest.version != "2":
            raise ValueError("v2 AnalysisArtifact 只能包含 v2 EvidenceManifest")
        return self


class SectionCitation(StrictModel):
    citation_id: str = Field(alias="citationId", min_length=1, max_length=128)
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=SHA256_PATTERN)


class SectionManagementQuestion(StrictModel):
    ref: str = Field(pattern=r"^analysis_[0-9]{3,6}$")
    question: str = Field(min_length=1, max_length=4000)


class SectionWorkItem(StrictModel):
    version: Literal["1"] = "1"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    section_number: str = Field(alias="sectionNumber", pattern=r"^[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    report_brief: ReportBrief = Field(alias="reportBrief")
    completion_conditions: tuple[str, ...] = Field(
        alias="completionConditions", min_length=1, max_length=100
    )
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=2000)
    evidence: tuple[AnalysisEvidence, ...] = Field(min_length=1, max_length=200)
    metric_definitions: tuple[MetricDefinition, ...] = Field(
        default=(), alias="metricDefinitions", max_length=500
    )
    management_question_catalog: tuple[SectionManagementQuestion, ...] = Field(
        default=(), alias="managementQuestionCatalog", max_length=200
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
        question_refs = tuple(item.ref for item in self.management_question_catalog)
        if question_refs and question_refs != self.analysis_ids:
            raise ValueError("SectionWorkItem 管理问题目录必须按顺序精确覆盖 analysisIds")
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


class SectionClaim(StrictModel):
    claim_id: str = Field(alias="claimId", min_length=1, max_length=128)
    metric_code: str = Field(alias="metricCode", min_length=1, max_length=128)
    value: Any
    period_basis: str = Field(alias="periodBasis", min_length=1, max_length=200)
    comparison: str | None = Field(default=None, max_length=200)
    management_question: str = Field(alias="managementQuestion", min_length=1, max_length=4000)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    chart_ids: tuple[str, ...] = Field(default=(), alias="chartIds", max_length=100)
    comparability: Literal["strict", "reference_only"] = "strict"
    conclusion_type: Literal["value", "comparison", "profit", "efficiency", "entity_ratio"] = Field(
        default="value", alias="conclusionType"
    )
    aggregation_grain: str | None = Field(
        default=None, alias="aggregationGrain", min_length=1, max_length=128
    )
    entity_grain: str | None = Field(
        default=None, alias="entityGrain", min_length=1, max_length=128
    )

    @model_validator(mode="after")
    def validate_entity_ratio(self) -> SectionClaim:
        if self.comparison_type != "none" and self.comparison_period is None:
            raise ValueError("比较 claim 必须声明 comparisonPeriod")
        if self.conclusion_type == "entity_ratio" and (
            self.aggregation_grain is None or self.entity_grain is None
        ):
            raise ValueError("实体级比例必须同时声明 aggregationGrain 与 entityGrain")
        return self


class SectionClaimSubmission(StrictModel):
    """模型提交的 claim；冻结字段由服务端在写入 SectionArtifact 前补齐。"""

    claim_id: str = Field(alias="claimId", min_length=1, max_length=128)
    metric_code: str = Field(alias="metricCode", min_length=1, max_length=128)
    value: Any
    comparison: str | None = Field(default=None, max_length=200)
    management_question_ref: str = Field(
        alias="managementQuestionRef", pattern=r"^analysis_[0-9]{3,6}$"
    )
    current_period: str | None = Field(
        default=None, alias="currentPeriod", min_length=1, max_length=200
    )
    comparison_period: str | None = Field(
        default=None, alias="comparisonPeriod", min_length=1, max_length=200
    )
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    chart_ids: tuple[str, ...] = Field(default=(), alias="chartIds", max_length=100)
    comparability: Literal["strict", "reference_only"] = "strict"
    conclusion_type: Literal["value", "comparison", "profit", "efficiency", "entity_ratio"] = Field(
        default="value", alias="conclusionType"
    )
    aggregation_grain: str | None = Field(
        default=None, alias="aggregationGrain", min_length=1, max_length=128
    )
    entity_grain: str | None = Field(
        default=None, alias="entityGrain", min_length=1, max_length=128
    )

    @model_validator(mode="after")
    def validate_submission(self) -> SectionClaimSubmission:
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("章节 claim citationIds 不能重复")
        if len(self.chart_ids) != len(set(self.chart_ids)):
            raise ValueError("章节 claim chartIds 不能重复")
        if not self.chart_ids and self.comparison_type != "none" and self.comparison_period is None:
            raise ValueError("无图表的比较 claim 必须声明 comparisonPeriod")
        return self


class SectionArtifact(StrictModel):
    version: Literal["1", "2"] = "2"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)
    claims: tuple[SectionClaim, ...] = Field(default=(), max_length=500)
    warnings: tuple[dict[str, Any], ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_claim_references(self) -> SectionArtifact:
        known = {claim.claim_id for claim in self.claims}
        if self.version == "2" and not self.claims:
            raise ValueError("v2 章节必须提交结构化 claims")
        if len(known) != len(self.claims):
            raise ValueError("章节 claimId 不能重复")
        referenced = {claim_id for block in self.blocks for claim_id in block.claim_ids}
        if referenced - known:
            raise ValueError("正文 block 引用了未声明的 claim")
        if known - referenced:
            raise ValueError("章节 claim 必须由正文 block 引用")
        if self.version == "2" and any(not block.claim_ids for block in self.blocks):
            raise ValueError("v2 章节的每个正文 block 必须引用至少一个 claim")
        return self


def read_analysis_artifact(
    payload: Mapping[str, Any], *, running: bool = False
) -> AnalysisArtifact:
    """读取内部分析产物；运行中的 v1 不得猜测缺失的 v2 语义字段。"""
    version = str(payload.get("version", ""))
    if version == "1" and running:
        raise ReportingError(
            "report_semantic_contract_upgrade_required",
            "运行中的 v1 分析产物缺少 v2 语义契约，必须重新分析。",
        )
    if version == "1":
        legacy = dict(payload)
        legacy.pop("version", None)
        return AnalysisArtifact.model_construct(version="1", **legacy)
    return AnalysisArtifact.model_validate(payload)


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


class CheckpointRetryUsage(StrictModel):
    analysis_fact_queries_used: int = Field(default=0, alias="analysisFactQueriesUsed", ge=0)
    visualization_read_units_used: int = Field(default=0, alias="visualizationReadUnitsUsed", ge=0)
    visualization_fact_queries_used: int = Field(
        default=0, alias="visualizationFactQueriesUsed", ge=0
    )
    visualization_tool_calls: int = Field(default=0, alias="visualizationToolCalls", ge=0)
    visualization_script_failures: int = Field(default=0, alias="visualizationScriptFailures", ge=0)
    visualization_attempt_successful_tool_calls: int = Field(
        default=0, alias="visualizationAttemptSuccessfulToolCalls", ge=0
    )
    visualization_attempt_rejected_tool_calls: int = Field(
        default=0, alias="visualizationAttemptRejectedToolCalls", ge=0
    )


class CheckpointError(StrictModel):
    phase: Literal["analysis", "section", "finalize"]
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    section_code: str | None = Field(default=None, alias="sectionCode", max_length=128)
    retry_reason: str | None = Field(default=None, alias="retryReason", max_length=2000)
    details: dict[str, Any] | None = Field(default=None, max_length=50)
    task_id: str | None = Field(default=None, alias="taskId", max_length=128)
    # visualization_section/visualization_finalize 区分并行章节图表 worker 与汇总 worker。
    work_kind: (
        Literal[
            "analysis_item",
            "visualization_section",
            "visualization_finalize",
            "section",
            "finalize",
        ]
        | None
    ) = Field(default=None, alias="workKind")
    analysis_id: str | None = Field(
        default=None, alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$"
    )
    attempt: int | None = Field(default=None, ge=0, le=100)
    retry_usage: CheckpointRetryUsage | None = Field(default=None, alias="retryUsage")


class ContextTrace(StrictModel):
    phase: Literal["analysis", "section", "finalize"]
    task_id: str | None = Field(default=None, alias="taskId", max_length=128)
    work_kind: (
        Literal[
            "analysis_item",
            "visualization_section",
            "visualization_finalize",
            "section",
            "finalize",
        ]
        | None
    ) = Field(default=None, alias="workKind")
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
    visual_inspection_mode: Literal["vision", "deterministic"] | None = Field(
        default=None, alias="visualInspectionMode"
    )


class ReportingCheckpoint(StrictModel):
    version: Literal["1", "2"] = "2"
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
    # 按章保存 visualization_section 失败与预算账本;并发合并时按键合并,
    # 不复用标量 last_error(后者保留给汇总 worker 的全局终态失败)。
    visualization_section_errors: dict[str, CheckpointError] = Field(
        default_factory=dict, alias="visualizationSectionErrors", max_length=200
    )
    deterministic_fact_files: dict[str, FileIdentity] = Field(
        default_factory=dict,
        alias="deterministicFactFiles",
        max_length=200,
    )
    files: tuple[FileIdentity, ...] = Field(default=(), max_length=500)
    trace: tuple[ContextTrace, ...] = Field(default=(), max_length=2000)

    @model_validator(mode="after")
    def validate_sections(self) -> ReportingCheckpoint:
        if self.version == "1" and self.phase != "completed":
            raise ValueError(
                "report_semantic_contract_upgrade_required: 运行中的 v1 checkpoint 必须重新分析"
            )
        if (
            self.version == "2"
            and self.evidence_manifest is not None
            and self.evidence_manifest.version != "2"
        ):
            raise ValueError("v2 ReportingCheckpoint 只能包含 v2 EvidenceManifest")
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
    task_key: str | None = None,
    task_kind: str | None = None,
    attempt: int = 0,
) -> str:
    # 三种 analysis 身份分支与 taskKind 一一绑定，防止把可视化身份伪装成 analysisId：
    # analysis_id 只属于 analysis_item（历史调用不传 taskKind）；section_code 只属于
    # visualization_section；finalize 只接受固定 task_key "viz-finalize"，不接受任意
    # 字符串。section phase 维持普通章节身份，不允许携带可视化 taskKind。
    if (
        revision < 1
        or attempt < 0
        or (phase == "section" and (not section_code or task_kind is not None))
        or (phase == "section" and (analysis_id is not None or task_key is not None))
        or (
            phase == "analysis"
            and sum(value is not None for value in (analysis_id, section_code, task_key)) != 1
        )
        or (
            analysis_id is not None
            and (
                not re.fullmatch(r"analysis_[0-9]{3,6}", analysis_id)
                or task_kind not in (None, "analysis_item")
            )
        )
        or (
            phase == "analysis"
            and section_code is not None
            and task_kind != "visualization_section"
        )
        or (
            phase == "analysis"
            and (
                task_key is not None
                and (task_key != "viz-finalize" or task_kind != "visualization_finalize")
            )
        )
    ):
        raise ValueError("Reporting phase task identity 无效")
    payload = (
        f"{workflow_run_id}:{revision}:{phase}:{analysis_id or task_key or ''}:{section_code or ''}:{attempt}"
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
