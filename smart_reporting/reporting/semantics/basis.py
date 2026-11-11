"""计算依据的追加回执契约；数据集文件授权继续由既有trace处理。"""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from ..business_knowledge.retrieval import ReportEvidenceSearchReceipt
from ..contract import ModelTermsResponse
from ..data_source.starrocks import StarRocksSourceConfig
from ..data_sources import DatasetHandle
from ..trace.contracts_v1 import DatasetSnapshotRefV1, TraceFileRefV1, derive_resource_id
from .issue_approval import BasisIssueBusinessApprovalReceipt
from .issue_regression import BasisIssueRegressionReceipt
from .issue_resolution import BasisIssueResolutionReceipt
from .models import (
    DataReadiness,
    Identity,
    MetricDefinition,
    MetricRequest,
    MetricResult,
    MetricSelection,
    ReportBasis,
    RunIdentity,
    SemanticModel,
    StatisticalPolicy,
)
from .policy_adoption import BasisPolicyAdoptionReceipt


@dataclass(frozen=True)
class BasisExecutionContext:
    basis: ReportBasis
    policy: StatisticalPolicy
    metrics: tuple[MetricDefinition, ...]
    sources: dict[str, StarRocksSourceConfig] = field(repr=False)
    metadata: dict[str, ModelTermsResponse] = field(repr=False)


class BasisWorkspaceBinding(SemanticModel):
    workspace_key: RunIdentity
    session_id: RunIdentity
    scope_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class BasisDatasetSnapshot(SemanticModel):
    source_id: Identity
    dataset: DatasetSnapshotRefV1
    file: TraceFileRefV1

    @model_validator(mode="after")
    def matching_file(self):
        if self.dataset.file_resource_id != self.file.resource_id or self.file.media_type != "text/csv":
            raise ValueError("数据集与CSV文件身份不一致")
        return self

    @classmethod
    def from_handle(cls, handle: DatasetHandle):
        resource_id = derive_resource_id(handle.path)
        return cls(source_id=handle.source_id,
            file=TraceFileRefV1(resourceId=resource_id, path=handle.path, mediaType="text/csv",
                size=handle.size, sha256=handle.sha256),
            dataset=DatasetSnapshotRefV1(datasetId=handle.dataset_id, fileResourceId=resource_id,
                sourceType=handle.source_type, requirementId=handle.requirement_id, sqlHash=handle.sql_hash,
                periodRoles=handle.period_roles, queryWindowId=handle.query_window_id, rowCount=handle.row_count,
                materializedAt=handle.materialized_at, filename=handle.filename,
                businessLabel=handle.business_label, querySql=handle.query_sql))

    def to_handle(self):
        return DatasetHandle(dataset_id=self.dataset.dataset_id, source_id=self.source_id,
            path=self.file.path, row_count=self.dataset.row_count, size=self.file.size, sha256=self.file.sha256,
            requirement_id=self.dataset.requirement_id, sql_hash=self.dataset.sql_hash or "",
            source_type=self.dataset.source_type, filename=self.dataset.filename,
            period_roles=self.dataset.period_roles, query_window_id=self.dataset.query_window_id,
            materialized_at=self.dataset.materialized_at, business_label=self.dataset.business_label,
            query_sql=self.dataset.query_sql)


class BasisCalculationReceipt(SemanticModel):
    kind: Literal["metric_calculation"] = "metric_calculation"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    request: MetricRequest
    results: tuple[MetricResult, ...] = Field(min_length=1, max_length=10000)
    readiness: tuple[DataReadiness, ...] = Field(default=(), max_length=200)
    datasets: tuple[BasisDatasetSnapshot, ...] = Field(default=(), max_length=200)
    workspace: BasisWorkspaceBinding | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def same_calculation(self):
        if self.request.basis_id != self.basis_id or any(
            result.basis_id != self.basis_id or result.period != self.request.period
            for result in self.results
        ):
            raise ValueError("计算结果与请求的依据或期间不一致")
        if len({result.calculation_id for result in self.results}) != 1:
            raise ValueError("同一回执只能登记一个计算批次")
        if len({result.fact_id for result in self.results}) != len(self.results):
            raise ValueError("计算事实身份不能重复")
        if self.request.metric_version not in {result.metric_version for result in self.results}:
            raise ValueError("回执须包含所请求的指标结果")
        if any(check.requested_period != self.request.period for check in self.readiness):
            raise ValueError("数据就绪检查与计算期间不一致")
        ids = [item.dataset.dataset_id for item in self.datasets]
        if len(ids) != len(set(ids)) or len({item.file.path for item in self.datasets}) != len(ids):
            raise ValueError("数据集身份或路径不能重复")
        if bool(self.datasets) != (self.workspace is not None):
            raise ValueError("CSV快照必须绑定可信工作区")
        if any(not set(result.dataset_ids).issubset(ids) for result in self.results):
            raise ValueError("计算结果缺少已登记的CSV快照")
        if any(result.status == "computed" and not result.dataset_ids for result in self.results):
            raise ValueError("计算值必须关联实际CSV快照")
        return self


class BasisSelectionReceipt(SemanticModel):
    kind: Literal["metric_selection"] = "metric_selection"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    selections: tuple[MetricSelection, ...] = Field(min_length=1, max_length=50)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def unique_questions(self):
        if len({item.question_id for item in self.selections}) != len(self.selections):
            raise ValueError("每个问题只能有一个当前选择")
        return self


class BasisKnowledgeReceipt(SemanticModel):
    kind: Literal["knowledge_retrieval"] = "knowledge_retrieval"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    section_code: Identity
    query: str = Field(min_length=1, max_length=4000)
    evidence: ReportEvidenceSearchReceipt
    created_at: AwareDatetime

    @model_validator(mode="after")
    def matching_evidence(self):
        if self.evidence.basis_id != self.basis_id or (
            self.evidence.search is not None and self.evidence.search.request.query != self.query
        ):
            raise ValueError("知识回执与依据或检索请求不一致")
        return self


class BasisAdoptionCalculationIntent(SemanticModel):
    """新依据初始取数意图；没有结果回执时保持未知，不自动重查。"""

    kind: Literal["policy_adoption_calculation_intent"] = "policy_adoption_calculation_intent"
    receipt_id: Identity
    basis_id: Identity
    report_revision: Literal["initial"] = "initial"
    target_receipt_id: Identity
    adoption_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace: BasisWorkspaceBinding
    request: MetricRequest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def calculation_identity(self):
        target = "initial-" + sha256(self.request.model_dump_json().encode()).hexdigest()
        if (self.request.basis_id != self.basis_id or self.target_receipt_id != target
                or self.receipt_id != "adoption-intent-" + sha256(target.encode()).hexdigest()):
            raise ValueError("新口径计算意图必须绑定新依据与精确请求")
        return self


class BasisRefreshIntent(SemanticModel):
    """业务查询前持久登记；缺少目标回执时不得自动再次取数。"""

    kind: Literal["metric_refresh_intent"] = "metric_refresh_intent"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    target_receipt_id: Identity
    parent_receipt_id: Identity
    parent_report_revision: RunIdentity
    request: MetricRequest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def distinct_target(self):
        if (self.target_receipt_id == self.parent_receipt_id or self.report_revision == self.parent_report_revision
                or self.request.basis_id != self.basis_id):
            raise ValueError("刷新必须固定原依据并使用新的回执和修订身份")
        return self


class BasisRefreshRevisionIntent(SemanticModel):
    """第一条业务SQL前固定整个父分析及新修订所需计算。"""

    kind: Literal["metric_refresh_revision_intent"] = "metric_refresh_revision_intent"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    parent_report_revision: RunIdentity
    parent_calculation_receipt_ids: tuple[Identity, ...] = Field(min_length=1, max_length=100)
    calculation_receipt_ids: tuple[Identity, ...] = Field(min_length=1, max_length=100)
    parent_planning_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime

    @model_validator(mode="after")
    def revision_identity(self):
        if (self.report_revision == self.parent_report_revision
                or self.receipt_id != "refresh-revision-intent-" + sha256(self.report_revision.encode()).hexdigest()
                or len(self.parent_calculation_receipt_ids) != len(self.calculation_receipt_ids)
                or len(set(self.parent_calculation_receipt_ids)) != len(self.parent_calculation_receipt_ids)
                or len(set(self.calculation_receipt_ids)) != len(self.calculation_receipt_ids)
                or set(self.parent_calculation_receipt_ids) & set(self.calculation_receipt_ids)):
            raise ValueError("整批刷新须固定完整父计算并使用独立目标身份")
        return self


class BasisRefreshRevisionReceipt(SemanticModel):
    """新分析修订选用的计算清单；不表示正文、图表或导出已经生成。"""

    kind: Literal["metric_refresh_revision"] = "metric_refresh_revision"
    receipt_id: Identity
    basis_id: Identity
    report_revision: RunIdentity
    parent_report_revision: RunIdentity
    calculation_receipt_ids: tuple[Identity, ...] = Field(max_length=100)
    planning_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime

    @model_validator(mode="after")
    def revision_identity(self):
        if (self.report_revision == self.parent_report_revision
                or self.receipt_id != "refresh-revision-" + sha256(self.report_revision.encode()).hexdigest()
                or len(set(self.calculation_receipt_ids)) != len(self.calculation_receipt_ids)):
            raise ValueError("刷新修订必须有独立身份和唯一计算清单")
        return self


BasisReceipt = Annotated[BasisCalculationReceipt | BasisSelectionReceipt | BasisKnowledgeReceipt | BasisAdoptionCalculationIntent | BasisRefreshIntent | BasisRefreshRevisionReceipt | BasisRefreshRevisionIntent | BasisPolicyAdoptionReceipt | BasisIssueRegressionReceipt | BasisIssueBusinessApprovalReceipt | BasisIssueResolutionReceipt, Field(discriminator="kind")]
