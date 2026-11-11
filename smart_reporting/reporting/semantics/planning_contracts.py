"""可序列化的正式分析上下文；不依赖管理服务或工作流初始化。"""

from pydantic import Field

from .models import (
    DataReadiness,
    Identity,
    MetricDefinition,
    MetricRequest,
    MetricResult,
    MetricSelection,
    ReportRequestSummary,
    SemanticModel,
    StatisticalPolicy,
)
from .request_types import RunIdentity


class PlanningCalculation(SemanticModel):
    receipt_id: Identity
    request: MetricRequest
    results: tuple[MetricResult, ...] = Field(min_length=1)
    readiness: tuple[DataReadiness, ...] = ()


class MetricPlanningContext(SemanticModel):
    basis_id: Identity
    report_revision: RunIdentity
    request: ReportRequestSummary
    policy: StatisticalPolicy
    metrics: tuple[MetricDefinition, ...]
    selections: tuple[MetricSelection, ...]
    calculations: tuple[PlanningCalculation, ...]
