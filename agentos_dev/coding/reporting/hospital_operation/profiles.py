from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .schema import HospitalOperationSchema


class PhysicalFieldBinding(HospitalOperationSchema):
    domain: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=128)
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)
    raw_unit: str = Field(alias="rawUnit", min_length=1, max_length=32)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    parent_metric: str | None = Field(default=None, alias="parentMetric", max_length=128)
    aggregation: Literal["sum"] = "sum"


class PhysicalDimensionBinding(HospitalOperationSchema):
    code: Literal["campus", "department", "first_level_accounting_unit"]
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)


class ReconciliationBinding(HospitalOperationSchema):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    domains: tuple[str, ...] = Field(min_length=1, max_length=6)
    left_metric: str = Field(alias="leftMetric", min_length=1, max_length=128)
    right_metrics: tuple[str, ...] = Field(alias="rightMetrics", min_length=1, max_length=10)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    absolute_tolerance: str = Field(default="0", alias="absoluteTolerance")


class DuplicateConflictBinding(HospitalOperationSchema):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    domain: str = Field(min_length=1, max_length=64)
    table_ref: str = Field(alias="tableRef", min_length=1, max_length=512)
    identity_fields: tuple[str, ...] = Field(alias="identityFields", min_length=1, max_length=20)
    value_fields: tuple[str, ...] = Field(alias="valueFields", min_length=1, max_length=20)


class HospitalOperationProfile(HospitalOperationSchema):
    profile_id: str = Field(alias="profileId", min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=128)
    hospital: str = Field(min_length=1, max_length=200)
    bindings: tuple[PhysicalFieldBinding, ...] = Field(max_length=500)
    dimension_bindings: tuple[PhysicalDimensionBinding, ...] = Field(
        default=(), alias="dimensionBindings", max_length=500
    )
    publish_grains: tuple[tuple[str, ...], ...] = Field(
        default=(("month",),), alias="publishGrains", min_length=1, max_length=20
    )
    additive_overlap_metrics: tuple[str, ...] = Field(
        default=(), alias="additiveOverlapMetrics", max_length=500
    )
    campus_aliases: dict[str, tuple[str, ...]] = Field(alias="campusAliases", max_length=100)
    reconciliations: tuple[ReconciliationBinding, ...] = Field(default=(), max_length=100)
    duplicate_conflicts: tuple[DuplicateConflictBinding, ...] = Field(
        default=(), alias="duplicateConflicts", max_length=100
    )
    period_formats: dict[str, Literal["year", "year_month", "date", "day_month_year"]] = Field(
        default_factory=dict, alias="periodFormats", max_length=100
    )
    zero_placeholder_periods: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, alias="zeroPlaceholderPeriods", max_length=100
    )
    unconfirmed_metrics: dict[str, str] = Field(
        default_factory=dict, alias="unconfirmedMetrics", max_length=100
    )
    unconfirmed_domains: tuple[str, ...] = Field(default=(), alias="unconfirmedDomains")
    pending_confirmations: tuple[str, ...] = Field(default=(), alias="pendingConfirmations")

    @field_validator("campus_aliases")
    @classmethod
    def validate_aliases(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        reverse: dict[str, str] = {}
        for canonical, aliases in value.items():
            candidates = (canonical, *aliases)
            for candidate in candidates:
                normalized = candidate.strip()
                if not normalized or reverse.get(normalized) not in {None, canonical}:
                    raise ValueError("院区别名为空或映射到多个规范名称")
                reverse[normalized] = canonical
        return value

    @model_validator(mode="after")
    def validate_bindings(self) -> HospitalOperationProfile:
        keys = [(item.domain, item.metric, item.field_ref.lower()) for item in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("Profile 物理字段绑定不能重复")
        dimension_refs = [item.field_ref.lower() for item in self.dimension_bindings]
        if len(dimension_refs) != len(set(dimension_refs)):
            raise ValueError("Profile 维度字段绑定不能重复")
        allowed = {"month", "year", "campus", "department", "first_level_accounting_unit"}
        if any(not grain or set(grain) - allowed for grain in self.publish_grains):
            raise ValueError("Profile publishGrains 包含未知或空粒度")
        return self

    def canonical_campus(self, value: str) -> str:
        normalized = value.strip()
        for canonical, aliases in self.campus_aliases.items():
            if normalized == canonical or normalized in aliases:
                return canonical
        return normalized

    def period_format(self, table: str) -> Literal["year", "year_month", "date", "day_month_year"]:
        normalized = table.rsplit(".", 1)[-1].lower()
        for table_ref, period_format in self.period_formats.items():
            if table_ref.rsplit(".", 1)[-1].lower() == normalized:
                return period_format
        raise ValueError(f"医院运营 Profile 未声明期间格式: {table}")


def ruijin_profile() -> HospitalOperationProfile:
    """瑞金首批已确认映射；不完整业务口径显式保持未确认。"""
    bindings = (
        PhysicalFieldBinding(
            domain="income",
            metric="actual_medical_income",
            fieldRef="rj.rj.dwd_income_budget_view.actual_medical_income",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="income",
            metric="actual_medicine_income",
            fieldRef="rj.rj.dwd_income_budget_view.actual_medicine_income",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit"),
            parentMetric="actual_medical_income",
        ),
        PhysicalFieldBinding(
            domain="income",
            metric="actual_material_income",
            fieldRef="rj.rj.dwd_income_budget_view.actual_material_income",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit"),
            parentMetric="actual_medical_income",
        ),
        PhysicalFieldBinding(
            domain="workload",
            metric="actual_person_time",
            fieldRef="rj.rj.dwd_income_budget_view.actual_person_time",
            rawUnit="人次",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="workload",
            metric="outpatient_visits",
            fieldRef="rj.rj.dm_hdc_gongzuoliang_view.mantime_outpatient",
            rawUnit="人次",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="workload",
            metric="discharges",
            fieldRef="rj.rj.dm_hdc_gongzuoliang_view.mantime_discharges",
            rawUnit="人次",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="income",
            metric="income_summary_total",
            fieldRef="rj.rj.dwd_hdc_income_summary_view.indicator_value",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit", "income_indicator"),
        ),
        PhysicalFieldBinding(
            domain="budget",
            metric="budget_income",
            fieldRef="rj.rj.dwd_income_budget_view.budget_medical_income",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="full_cost",
            metric="total_cost",
            fieldRef="rj.rj.dwd_hdc_cost_table_view.indicator_value",
            rawUnit="元",
            grain=("month", "campus", "accounting_unit"),
        ),
        PhysicalFieldBinding(
            domain="budget",
            metric="project_budget",
            fieldRef="rj.rj.dwd_project_budget_view.budget_project_amount",
            rawUnit="元",
            grain=("year", "campus", "accounting_unit", "project"),
        ),
        PhysicalFieldBinding(
            domain="budget",
            metric="project_contract_amount",
            fieldRef="rj.rj.dwd_project_budget_view.contract_amount",
            rawUnit="元",
            grain=("year", "campus", "accounting_unit", "project"),
        ),
        PhysicalFieldBinding(
            domain="budget",
            metric="project_payment_amount",
            fieldRef="rj.rj.dwd_project_budget_view.payment_amount",
            rawUnit="元",
            grain=("year", "campus", "accounting_unit", "project"),
        ),
    )
    dimension_specs: tuple[
        tuple[Literal["campus", "department", "first_level_accounting_unit"], str], ...
    ] = (
        ("campus", "area"),
        ("first_level_accounting_unit", "stlevel_analytic_unit"),
    )
    return HospitalOperationProfile(
        profileId="ruijin-hospital-operation",
        revision="2025-acceptance-2",
        hospital="瑞金医院",
        bindings=bindings,
        dimensionBindings=tuple(
            PhysicalDimensionBinding(code=code, fieldRef=f"rj.rj.{table}.{column}")
            for table in (
                "dwd_income_budget_view",
                "dm_hdc_gongzuoliang_view",
                "dwd_hdc_income_summary_view",
                "dwd_hdc_cost_table_view",
                "dwd_project_budget_view",
            )
            for code, column in dimension_specs
        ),
        publishGrains=(
            ("month",),
            ("month", "campus"),
            ("month", "first_level_accounting_unit"),
            ("year",),
            ("year", "campus"),
            ("year", "first_level_accounting_unit"),
        ),
        campusAliases={
            "质子院区": ("质子中心",),
            "转化院区": ("转化",),
            "远洋院区": ("远洋",),
            "总部院区": (),
            "北部院区": (),
        },
        reconciliations=(
            ReconciliationBinding(
                code="income_monthly_reconciliation",
                domains=("income",),
                leftMetric="actual_medical_income",
                rightMetrics=("income_summary_total",),
                grain=("month",),
                absoluteTolerance="100",
            ),
            ReconciliationBinding(
                code="workload_monthly_reconciliation",
                domains=("workload",),
                leftMetric="actual_person_time",
                rightMetrics=("outpatient_visits", "discharges"),
                grain=("month",),
                absoluteTolerance="100",
            ),
        ),
        duplicateConflicts=(
            DuplicateConflictBinding(
                code="project_budget_duplicate_rows",
                domain="budget",
                tableRef="rj.rj.dwd_project_budget_view",
                identityFields=(
                    "period_year",
                    "area",
                    "stlevel_analytic_unit",
                    "project_code",
                    "project_name",
                    "budget_type",
                ),
                valueFields=("budget_project_amount", "contract_amount", "payment_amount"),
            ),
        ),
        periodFormats={
            # 真实物化 CSV 会把五张月度表的 DATE 字段统一序列化为 ISO 日期；
            # Profile 必须描述物理值，不能因业务按月汇总而改写成其他输入格式。
            "rj.rj.dwd_income_budget_view": "date",
            "rj.rj.dwd_expenditure_budget_view": "date",
            "rj.rj.dwd_project_budget_view": "year",
            "rj.rj.dwd_hdc_income_summary_view": "date",
            "rj.rj.dwd_hdc_cost_table_view": "date",
            "rj.rj.dm_hdc_gongzuoliang_view": "date",
        },
        # 2025 验收探测确认工作量两表的 11–12 月均为全零占位。该规则只属于当前
        # Profile revision；物化阶段仍校验值必须为零，非零时升级为冲突，禁止按数值大小推断。
        zeroPlaceholderPeriods={
            "actual_person_time": ("2025-11", "2025-12"),
            "outpatient_visits": ("2025-11", "2025-12"),
            "discharges": ("2025-11", "2025-12"),
        },
        # 项目表没有版本字段。即使 SQL 暂时只返回一行，也不能证明该行是唯一版本；
        # 因此确认前所有项目金额都只能作为冲突核验材料，不能进入可累计指标层。
        unconfirmedMetrics={
            "project_budget": "项目预算缺少版本字段，禁止自动去重或累计。",
            "project_contract_amount": "项目预算缺少版本字段，合同金额口径未确认。",
            "project_payment_amount": "项目预算缺少版本字段，付款金额口径未确认。",
        },
        unconfirmedDomains=("cost_control", "funds"),
        pendingConfirmations=(
            "项目预算缺少版本字段，禁止自动去重或累计。",
            "支出预算包含收入类项目且一月口径异常。",
            "生产正式发布前需由财务数据负责人确认货币原始单位为人民币元。",
        ),
    )
