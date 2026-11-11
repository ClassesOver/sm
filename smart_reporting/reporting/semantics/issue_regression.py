"""问题回归核验契约；真实快照复算与管理员预期分开保存。"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ..trace.contracts_v1 import TraceFileRefV1, canonical_sha256
from .models import (
    BuildIdentity,
    CorrectedVersionRef,
    FiniteDecimal,
    Identity,
    MetricResult,
    MetricVersionRef,
    RunIdentity,
    SemanticModel,
)


def _rounded(value, places):
    try:
        with localcontext() as context:
            # 与既有Decimal数学一样覆盖SQL Decimal及完整有限float范围。
            context.prec = max(700, len(value.as_tuple().digits) + places + 1)
            return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError('数值无法按声明精度核对') from None


class RegressionAssertion(SemanticModel):
    fact_id: Identity
    expected_status: Literal['computed', 'unavailable']
    expected_value: FiniteDecimal | None = None
    unit: str = Field(min_length=1, max_length=32)
    decimal_places: int | None = Field(default=None, ge=0, le=12, strict=True)
    expected_issue_codes: tuple[Identity, ...] = Field(default=(), max_length=50)

    @model_validator(mode='after')
    def explicit_expectation(self):
        if self.expected_status == 'computed':
            if self.expected_value is None:
                raise ValueError('预期可计算时必须明确预期数值')
            if self.decimal_places is not None and self.expected_value != _rounded(self.expected_value, self.decimal_places):
                raise ValueError('预期数值不得超过明确声明的比较精度')
        elif self.expected_value is not None or self.decimal_places is not None or not self.expected_issue_codes:
            raise ValueError('预期不可计算时须给出原因，不得附加数值或比较精度')
        return self

    def matches(self, actual):
        if (actual.fact_id != self.fact_id or actual.status != self.expected_status or actual.unit != self.unit
                or not set(self.expected_issue_codes) <= set(actual.issue_codes)):
            return False
        if self.expected_status == 'unavailable':
            return actual.value is None
        value = actual.value
        if value is not None and self.decimal_places is not None:
            value = _rounded(value, self.decimal_places)
        return value == self.expected_value


class IssueRegressionRequest(SemanticModel):
    request_id: Identity
    expected_issue_version: int = Field(ge=1, strict=True)
    case_id: Identity
    target_run_id: RunIdentity
    target_report_revision: RunIdentity
    calculation_receipt_id: Identity
    expectation_reason: str = Field(min_length=1, max_length=10000)
    assertions: tuple[RegressionAssertion, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def concrete_case(self):
        if not self.expectation_reason.strip() or len({item.fact_id for item in self.assertions}) != len(self.assertions):
            raise ValueError('回归须有独立预期依据且事实断言不能重复')
        return self


class RegressionComparison(SemanticModel):
    assertion: RegressionAssertion
    actual: MetricResult
    matches: bool

    @model_validator(mode='after')
    def consistent(self):
        if self.matches != self.assertion.matches(self.actual):
            raise ValueError('回归比较与实际值不一致')
        return self


def regression_receipt_id(basis_id, issue_id, request_id):
    return 'issue-regression-' + canonical_sha256({'basisId': basis_id, 'issueId': issue_id, 'requestId': request_id})


class BasisIssueRegressionReceipt(SemanticModel):
    kind: Literal['issue_regression'] = 'issue_regression'
    receipt_id: Identity
    basis_id: Identity
    report_revision: Literal['issue-regression-verification'] = 'issue-regression-verification'
    issue_id: Identity
    request: IssueRegressionRequest
    corrected_versions: tuple[CorrectedVersionRef, ...] = Field(min_length=1, max_length=50)
    target_basis_id: Identity
    target_basis_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    calculation_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    covered_metric_versions: tuple[MetricVersionRef, ...]
    snapshot_files: tuple[TraceFileRefV1, ...] = Field(min_length=1, max_length=200)
    comparisons: tuple[RegressionComparison, ...] = Field(min_length=1, max_length=200)
    status: Literal['passed', 'failed']
    verification_level: Literal['snapshot_recomputed'] = 'snapshot_recomputed'
    business_approval: Literal['not_performed'] = 'not_performed'
    verifier_build: BuildIdentity
    created_at: AwareDatetime

    @model_validator(mode='after')
    def verified_identity(self):
        if (self.receipt_id != regression_receipt_id(self.basis_id, self.issue_id, self.request.request_id)
                or self.status != ('passed' if all(item.matches for item in self.comparisons) else 'failed')
                or tuple(item.assertion for item in self.comparisons) != self.request.assertions
                or any(item.actual.basis_id != self.target_basis_id for item in self.comparisons)):
            raise ValueError('回归结果必须绑定原问题、完整预期和实际计算依据')
        return self
