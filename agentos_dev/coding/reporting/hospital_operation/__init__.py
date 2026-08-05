"""医院运营管理业务核心。

该包只提供确定性的业务事实、领域装配和发布门禁；不连接数据库，也不依赖
Report Worker。Workflow 通过这里冻结的 FactSet 向下游传递事实。
"""

from .domains import (
    DOMAIN_CODES,
    DomainDefinition,
    DomainResolution,
    HospitalOperationCore,
    build_domain_stage_guidance,
    domain_definitions,
    domain_guidance,
    normalize_domain_code,
    resolve_domain_mentions,
)
from .factset import (
    AnalysisFactSetHandle,
    FactEvidence,
    FactSetBuilder,
    FactSetHandle,
    FactSetIssue,
    HospitalOperationAnalysisFact,
    HospitalOperationAnalysisFactSet,
    HospitalOperationFact,
    HospitalOperationFactSet,
    HospitalOperationMetricFact,
    MetricFormula,
    build_analysis_fact_set,
    display_money,
    normalize_money,
)
from .findings import (
    EvidenceKind,
    FindingProposal,
    FindingsResult,
    FindingType,
    HospitalOperationFinding,
    build_findings,
)
from .gate import PublicationGateResult, evaluate_publication_gate
from .materialization import DatasetFactInput, build_fact_set_from_datasets
from .outline import (
    COMPREHENSIVE_SECTIONS,
    OutlineSectionProposal,
    ReportOutline,
    ReportOutlineProposal,
    ReportOutlineSection,
    freeze_outline,
    make_outline,
)
from .profiles import HospitalOperationProfile, ruijin_profile
from .reconciliation import (
    ReconciliationResult,
    coverage_status,
    detect_duplicate_conflicts,
    reconcile_series,
    reject_double_counting,
)
from .request import (
    ClarificationRequired,
    CorrectionFeedback,
    ReportRequestContext,
    normalize_report_request,
)

__all__ = [
    "AnalysisFactSetHandle",
    "ClarificationRequired",
    "CorrectionFeedback",
    "COMPREHENSIVE_SECTIONS",
    "OutlineSectionProposal",
    "FactEvidence",
    "FactSetIssue",
    "FactSetBuilder",
    "FactSetHandle",
    "DatasetFactInput",
    "HospitalOperationCore",
    "HospitalOperationAnalysisFact",
    "HospitalOperationAnalysisFactSet",
    "DOMAIN_CODES",
    "DomainDefinition",
    "DomainResolution",
    "HospitalOperationFact",
    "HospitalOperationFactSet",
    "HospitalOperationMetricFact",
    "EvidenceKind",
    "FindingProposal",
    "FindingType",
    "FindingsResult",
    "HospitalOperationFinding",
    "HospitalOperationProfile",
    "MetricFormula",
    "PublicationGateResult",
    "ReconciliationResult",
    "ReportOutline",
    "ReportOutlineProposal",
    "ReportOutlineSection",
    "ReportRequestContext",
    "coverage_status",
    "build_fact_set_from_datasets",
    "build_analysis_fact_set",
    "build_findings",
    "build_domain_stage_guidance",
    "detect_duplicate_conflicts",
    "display_money",
    "domain_definitions",
    "domain_guidance",
    "evaluate_publication_gate",
    "make_outline",
    "freeze_outline",
    "normalize_money",
    "normalize_domain_code",
    "normalize_report_request",
    "reconcile_series",
    "reject_double_counting",
    "ruijin_profile",
    "resolve_domain_mentions",
]
