from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from agentos_dev.coding.reporting.data_source.period import (
    PeriodWindow,
    build_period_windows,
    unique_period_windows,
)
from agentos_dev.coding.reporting.hospital_operation import (
    DatasetFactInput,
    FactEvidence,
    FactSetBuilder,
    FindingProposal,
    OutlineSectionProposal,
    ReportOutlineProposal,
    ReportRequestContext,
    build_analysis_fact_set,
    build_fact_set_from_datasets,
    build_findings,
    coverage_status,
    detect_duplicate_conflicts,
    display_money,
    evaluate_publication_gate,
    freeze_outline,
    make_outline,
    normalize_money,
    reconcile_series,
    reject_double_counting,
    resolve_domain_mentions,
    ruijin_profile,
)
from agentos_dev.coding.reporting.hospital_operation.metrics import build_metric_facts
from agentos_dev.coding.reporting.models import ReportingError

EVIDENCE = FactEvidence(
    datasetId="dataset-income",
    schemaHash="a" * 64,
    sqlHash="b" * 64,
    fileHash="c" * 64,
    references=("citation-income",),
)


def _builder() -> FactSetBuilder:
    return FactSetBuilder(
        hospital="瑞金医院",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-04T00:00:00Z",
    )


def test_金额统一为元且亿元展示不会产生十倍错误():
    value = normalize_money("11123541503", "元")

    assert value == Decimal("11123541503")
    assert display_money(value, factor=Decimal("100000000"), unit="亿元") == Decimal("111.23541503")
    with pytest.raises(ReportingError, match="展示单位与换算因子不一致"):
        display_money(value, factor=Decimal("10000000"), unit="亿元")


def test_收入总额与药品材料子集禁止重复累计():
    builder = _builder()
    total = builder.add(
        fact_id="income-total",
        domain="income",
        metric="actual_medical_income",
        period="2025-01",
        value="889688594",
        raw_unit="元",
        evidence=EVIDENCE,
    )
    medicine = builder.add(
        fact_id="income-medicine",
        domain="income",
        metric="actual_medicine_income",
        period="2025-01",
        value="272014023",
        raw_unit="元",
        evidence=EVIDENCE,
        parent_metric="actual_medical_income",
        is_subset=True,
    )

    with pytest.raises(ReportingError, match="总额与组成子集不能重复累计"):
        reject_double_counting((total, medicine))


def test_零值占位必须显式声明且低值不能自动推断为partial():
    expected = ("2025-01", "2025-02")

    assert coverage_status(expected, expected) == "complete"
    assert coverage_status(expected, ("2025-01",)) == "missing"
    assert coverage_status(expected, ("2025-01",), confirmed_partial=True) == "partial"
    assert coverage_status(expected, (), explicit_zero_placeholders=expected) == "zero_placeholder"


def test_项目预算无版本字段时只报告重复金额冲突():
    rows = (
        {"project": "A", "year": 2025, "amount": "100"},
        {"project": "A", "year": 2025, "amount": "120"},
        {"project": "B", "year": 2025, "amount": "80"},
        {"project": "B", "year": 2025, "amount": "80"},
    )

    conflicts = detect_duplicate_conflicts(
        rows, identity_fields=("project", "year"), value_field="amount"
    )

    assert len(conflicts) == 1
    assert conflicts[0].identity == ("A", "2025")
    assert conflicts[0].values == (Decimal("100"), Decimal("120"))


def test_瑞金院区别名由服务端确定性归一化():
    profile = ruijin_profile()

    assert profile.canonical_campus("质子中心") == "质子院区"
    assert profile.canonical_campus("转化") == "转化院区"
    assert profile.canonical_campus("北部院区") == "北部院区"


def test_瑞金月度表统一使用iso日期且收入明细可以物化():
    profile = ruijin_profile()
    monthly_tables = (
        "rj.dwd_income_budget_view",
        "rj.dwd_expenditure_budget_view",
        "rj.dwd_hdc_income_summary_view",
        "rj.dwd_hdc_cost_table_view",
        "rj.dm_hdc_gongzuoliang_view",
    )

    assert {profile.period_format(table) for table in monthly_tables} == {"date"}

    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "income-summary-iso-date",
                "rj.dwd_hdc_income_summary_view",
                ({"data_date": "2025-01-01", "indicator_value": "100"},),
            ),
        ),
        profile=profile,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-05T00:00:00Z",
    )

    assert fact_set.facts[0].period == "2025-01"


def test_真实sql投影字段生成收入工作量和全成本事实():
    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "income-summary-real-header",
                "rj.dwd_hdc_income_summary_view",
                ({"data_date": "2025-01-01", "indicator_value": "100"},),
            ),
            _dataset(
                "workload-real-header",
                "rj.dm_hdc_gongzuoliang_view",
                (
                    {
                        "data_date": "2025-01-01",
                        "mantime_outpatient": "80",
                        "mantime_discharges": "20",
                    },
                ),
            ),
            _dataset(
                "cost-real-header",
                "rj.dwd_hdc_cost_table_view",
                ({"data_date": "2025-01-01", "indicator_value": "90"},),
            ),
        ),
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-05T00:00:00Z",
    )

    assert {fact.metric for fact in fact_set.facts} >= {
        "income_summary_total",
        "outpatient_visits",
        "discharges",
        "total_cost",
    }


def test_profile表已有绑定但物化投影零匹配时失败关闭():
    with pytest.raises(ReportingError) as captured:
        build_fact_set_from_datasets(
            (
                _dataset(
                    "cost-wrong-header",
                    "rj.dwd_hdc_cost_table_view",
                    ({"data_date": "2025-01-01", "total_cost": "90"},),
                ),
            ),
            profile=ruijin_profile(),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            generated_at="2026-08-05T00:00:00Z",
        )

    assert captured.value.code == "hospital_operation_fact_binding_unresolved"


def test_十月收入和工作量勾稽差异被标记为冲突():
    income = reconcile_series(
        "income",
        {"2025-10": "926393868"},
        {"2025-10": "1072269548"},
        absolute_tolerance=Decimal("100"),
    )
    workload = reconcile_series(
        "workload",
        {"2025-10": "518335"},
        {"2025-10": "434914"},
        absolute_tolerance=Decimal("100"),
    )

    assert income.status == "conflict"
    assert income.points[0].difference == Decimal("-145875680")
    assert workload.status == "conflict"
    assert workload.points[0].difference == Decimal("83421")


def test_综合报告固定十章且专题报告只能使用十章有序子集():
    comprehensive = make_outline("comprehensive", title="2025年综合运营报告")
    topic = make_outline(
        "topic",
        title="2025年收入专题报告",
        selected_codes=("income", "cross_domain"),
    )

    assert len(comprehensive.sections) == 10
    assert [item.code for item in comprehensive.sections][:2] == ["operation_overview", "income"]
    assert [item.code for item in topic.sections] == [
        "operation_overview",
        "income",
        "cross_domain",
        "risk_and_data_quality",
        "management_actions",
    ]


def test_请求语境按顺序保存反馈且身份变化要求重启():
    context = ReportRequestContext(
        originalGoal="生成报告",
        reportType="comprehensive",
        periodStart=date(2025, 1, 1),
        periodEnd=date(2025, 12, 31),
        hospital="瑞金医院",
        sourceIds=("rj",),
    )
    updated = context.append_feedback("关注十月差异", stage="request_supplement").append_feedback(
        "调整收入章节标题", stage="outline_feedback"
    )

    assert [item.content for item in updated.feedback] == ["关注十月差异", "调整收入章节标题"]
    with pytest.raises(ReportingError, match="必须取消当前运行并重新发起"):
        updated.assert_same_identity(
            report_type="topic",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            hospital="瑞金医院",
            source_ids=("rj",),
        )


def test_综合报告缺少费控资金且预算冲突时仅允许内部草稿():
    builder = _builder()
    for domain, metric in (
        ("income", "actual_medical_income"),
        ("workload", "outpatient_visits"),
        ("full_cost", "total_cost"),
    ):
        builder.add(
            fact_id=f"{domain}-2025-01",
            domain=domain,
            metric=metric,
            period="2025-01",
            value="100",
            raw_unit="元" if domain != "workload" else "人次",
            evidence=EVIDENCE,
            grain=("month", "campus"),
        )
    builder.add(
        fact_id="budget-2025-01",
        domain="budget",
        metric="project_budget",
        period="2025-01",
        value="100",
        raw_unit="元",
        evidence=EVIDENCE,
        grain=("month", "campus"),
        coverage="conflict",
        conflicts=("同一项目存在不同金额且没有版本字段",),
    )
    fact_set = builder.build()

    gate = evaluate_publication_gate(fact_set, report_type="comprehensive")

    assert gate.internal_draft_allowed is True
    assert gate.formal_release_allowed is False
    assert {item.code for item in gate.issues} >= {
        "domain_coverage_blocked",
        "domain_unavailable",
    }


def _dataset(
    dataset_id: str,
    table: str,
    rows: tuple[dict[str, object], ...],
    *,
    period_column: str = "data_date",
    row_preserving: bool = False,
) -> DatasetFactInput:
    return DatasetFactInput(
        dataset_id=dataset_id,
        requirement_id=f"requirement-{dataset_id}",
        source_id="rj",
        table=table,
        period_column=period_column,
        grain=("month", "campus", "accounting_unit"),
        rows=rows,
        schema_hash="a" * 64,
        sql_hash="b" * 64,
        file_hash="c" * 64,
        reference=f"citation-{dataset_id}",
        row_preserving=row_preserving,
    )


def test_已物化csv生成事实时保留负成本院区映射和完整证据():
    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "cost",
                "rj.dwd_hdc_cost_table_view",
                (
                    {
                        "data_date": "2025-01-01",
                        "area": "质子中心",
                        "detail_analytic_unit": "核算单元A",
                        "indicator_value": "-123.45",
                    },
                ),
            ),
        ),
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-04T00:00:00Z",
    )

    cost = next(fact for fact in fact_set.facts if fact.metric == "total_cost")
    assert cost.raw_value == Decimal("-123.45")
    assert cost.normalized_value == Decimal("-123.45")
    assert cost.campus == "质子院区"
    assert cost.accounting_unit == "核算单元A"
    assert cost.evidence.schema_hash == "a" * 64
    assert cost.evidence.sql_hash == "b" * 64
    assert cost.evidence.file_hash == "c" * 64
    assert cost.evidence.references == ("citation-cost",)


def test_项目预算重复和两项月度勾稽冲突进入factset门禁():
    datasets = (
        _dataset(
            "income",
            "rj.dwd_income_budget_view",
            ({"data_date": "2025-10-01", "actual_medical_income": "926393868"},),
        ),
        _dataset(
            "income-summary",
            "rj.dwd_hdc_income_summary_view",
            ({"data_date": "2025-10-01", "indicator_value": "1072269548"},),
        ),
        _dataset(
            "workload-main",
            "rj.dwd_income_budget_view",
            ({"data_date": "2025-10-01", "actual_person_time": "518335"},),
        ),
        _dataset(
            "workload-detail",
            "rj.dm_hdc_gongzuoliang_view",
            (
                {
                    "data_date": "2025-10-01",
                    "mantime_outpatient": "420422",
                    "mantime_discharges": "14492",
                },
            ),
        ),
        _dataset(
            "project-budget",
            "rj.dwd_project_budget_view",
            (
                {
                    "period_year": "2025",
                    "area": "全院",
                    "stlevel_analytic_unit": "设备处",
                    "project_code": "P1",
                    "project_name": "项目一",
                    "budget_type": "设备",
                    "budget_project_amount": "100",
                    "contract_amount": "80",
                    "payment_amount": "50",
                },
                {
                    "period_year": "2025",
                    "area": "全院",
                    "stlevel_analytic_unit": "设备处",
                    "project_code": "P1",
                    "project_name": "项目一",
                    "budget_type": "设备",
                    "budget_project_amount": "100",
                    "contract_amount": "80",
                    "payment_amount": "60",
                },
            ),
            period_column="period_year",
            row_preserving=True,
        ),
    )
    fact_set = build_fact_set_from_datasets(
        datasets,
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-04T00:00:00Z",
    )

    issues = {issue.code: issue for issue in fact_set.issues}
    assert issues["income_monthly_reconciliation"].periods == ("2025-10",)
    assert issues["workload_monthly_reconciliation"].periods == ("2025-10",)
    assert issues["project_budget_duplicate_rows_conflict"].status == "conflict"
    assert issues["project_budget_duplicate_rows_conflict"].fact_ids

    gate = evaluate_publication_gate(fact_set, report_type="comprehensive")
    assert gate.formal_release_allowed is False
    assert {issue.code for issue in gate.issues} >= set(issues)


def test_瑞金月份格式统一且十一十二月工作量零值显式标记占位():
    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "workload-placeholder",
                "rj.dm_hdc_gongzuoliang_view",
                (
                    {
                        "data_date": "2025-11-01",
                        "mantime_outpatient": "0",
                        "mantime_discharges": "0",
                    },
                ),
            ),
        ),
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-04T00:00:00Z",
    )

    workload = [fact for fact in fact_set.facts if fact.domain == "workload"]
    assert {fact.period for fact in workload} == {"2025-11"}
    assert {fact.coverage for fact in workload} == {"zero_placeholder"}


def test_服务端冻结月度累计和共同期间运营指标():
    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "income-main",
                "rj.dwd_income_budget_view",
                (
                    {"data_date": "2025-01-01", "actual_medical_income": "5000000000"},
                    {"data_date": "2025-02-01", "actual_medical_income": "4514000000"},
                ),
            ),
            _dataset(
                "cost-detail",
                "rj.dwd_hdc_cost_table_view",
                (
                    {"data_date": "2025-01-01", "indicator_value": "5200000000"},
                    {"data_date": "2025-02-01", "indicator_value": "4712000000"},
                ),
            ),
        ),
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-05T00:00:00Z",
    )

    metrics = {fact.metric: fact for fact in fact_set.metric_facts if fact.scope == "common_period"}
    assert metrics["operating_result"].normalized_value == Decimal("-398000000")
    assert metrics["operating_result"].display_text == "-3.98亿元"
    assert metrics["cost_income_ratio"].normalized_value.quantize(Decimal("0.01")) == Decimal(
        "104.18"
    )
    assert metrics["cost_income_ratio"].display_text == "104.18%"
    for fact in metrics.values():
        assert fact.input_fact_ids
        assert fact.citation_ids

    operating_id = metrics["operating_result"].fact_id
    ratio_id = metrics["cost_income_ratio"].fact_id
    mismatched = evaluate_publication_gate(
        fact_set,
        report_type="topic",
        selected_domains=("income", "full_cost"),
        referenced_fact_ids=(operating_id,),
        chart_fact_ids=(ratio_id,),
    )
    assert "fact_reference_mismatch" in {issue.code for issue in mismatched.issues}

    bound = evaluate_publication_gate(
        fact_set,
        report_type="topic",
        selected_domains=("income", "full_cost"),
        referenced_fact_ids=(operating_id, ratio_id),
        chart_fact_ids=(ratio_id,),
    )
    assert not {
        "fact_reference_unknown",
        "fact_reference_mismatch",
        "fact_reference_missing",
        "fact_reference_not_publishable",
    }.intersection(issue.code for issue in bound.issues)


def test_单月明细超过公式输入上限时使用不可发布分块事实():
    builder = _builder()
    for index in range(100_001):
        builder.add(
            fact_id=f"large-income-{index:06d}",
            domain="income",
            metric="actual_medical_income",
            period="2025-01",
            value="1",
            raw_unit="元",
            evidence=EVIDENCE,
        )

    base = builder.build()
    metric_facts = build_metric_facts(base)
    completed = builder.build(metric_facts=metric_facts)

    support = [item for item in completed.metric_facts if not item.publishable]
    monthly = [
        item for item in completed.metric_facts if item.publishable and item.scope == "month"
    ]
    assert support
    assert monthly
    assert max(len(item.input_fact_ids) for item in completed.metric_facts) <= 10_000
    assert all(item.scope == "support" for item in support)
    assert all(item.fact_id not in {metric.fact_id for metric in monthly} for item in support)
    analysis = build_analysis_fact_set(completed)
    assert {item.fact_id for item in analysis.facts} == {
        item.fact_id for item in completed.metric_facts if item.publishable
    }
    assert all(item.input_fact_count == 100_001 for item in analysis.facts)


def test_分析目录继承事实集期间角色且不混合对比期():
    builder = FactSetBuilder(
        hospital="瑞金医院",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-04T00:00:00Z",
        period_roles=("current", "yoy"),
    )
    for period_role, period, value in (
        ("current", "2025-01", "120"),
        ("yoy", "2024-01", "100"),
    ):
        builder.add(
            fact_id=f"income-{period_role}",
            domain="income",
            metric="actual_medical_income",
            period=period,
            period_role=period_role,
            value=value,
            raw_unit="元",
            evidence=EVIDENCE,
        )

    base = builder.build()
    completed = builder.build(metric_facts=build_metric_facts(base))
    analysis = build_analysis_fact_set(completed)

    assert analysis.period_roles == ("current", "yoy")
    assert {item.period_role for item in analysis.facts} == {"current", "yoy"}


def test_项目预算未确认时不得生成可展示业务指标():
    fact_set = build_fact_set_from_datasets(
        (
            _dataset(
                "project-budget-aggregated",
                "rj.dwd_project_budget_view",
                (
                    {
                        "period_year": "2025",
                        "area": "全院",
                        "stlevel_analytic_unit": "设备处",
                        "project_code": "P1",
                        "project_name": "项目一",
                        "budget_type": "设备",
                        "budget_project_amount": "100",
                        "contract_amount": "80",
                        "payment_amount": "50",
                    },
                ),
                period_column="period_year",
                row_preserving=True,
            ),
        ),
        profile=ruijin_profile(),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        generated_at="2026-08-05T00:00:00Z",
    )

    project_facts = [fact for fact in fact_set.facts if fact.metric.startswith("project_")]
    assert project_facts
    assert {fact.coverage for fact in project_facts} == {"unconfirmed"}
    assert not {
        "project_budget",
        "project_contract_amount",
        "project_payment_amount",
    }.intersection(fact.metric for fact in fact_set.metric_facts)


def test_项目预算物化拒绝缺少原始行审核身份():
    dataset = _dataset(
        "project-budget-summed",
        "rj.dwd_project_budget_view",
        (
            {
                "period_year": "2025",
                "project_code": "P1",
                "budget_project_amount": "200",
            },
        ),
        period_column="period_year",
    )

    with pytest.raises(ReportingError) as captured:
        build_fact_set_from_datasets(
            (dataset,),
            profile=ruijin_profile(),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            generated_at="2026-08-05T00:00:00Z",
        )
    assert captured.value.code == "hospital_operation_duplicate_probe_not_row_preserving"


@pytest.mark.parametrize(
    ("start", "end", "expected_yoy", "expected_mom"),
    (
        (
            date(2025, 5, 10),
            date(2025, 5, 20),
            (date(2024, 5, 10), date(2024, 5, 20)),
            (date(2025, 4, 29), date(2025, 5, 9)),
        ),
        (
            date(2024, 2, 29),
            date(2024, 2, 29),
            (date(2023, 2, 28), date(2023, 2, 28)),
            (date(2024, 2, 28), date(2024, 2, 28)),
        ),
    ),
)
def test_同比保持月日且环比使用相同闭区间天数(start, end, expected_yoy, expected_mom):
    windows = build_period_windows(start, end)

    yoy = windows.for_role("yoy")
    mom = windows.for_role("mom")
    assert (yoy.start, yoy.end) == expected_yoy
    assert (mom.start, mom.end) == expected_mom
    assert mom.inclusive_days == (end - start).days + 1


def test_相同期间窗口只保留一次查询且保留全部角色():
    grouped = unique_period_windows(
        (
            PeriodWindow("current", date(2025, 1, 1), date(2025, 1, 31)),
            PeriodWindow("yoy", date(2024, 1, 1), date(2024, 1, 31)),
            PeriodWindow("mom", date(2024, 1, 1), date(2024, 1, 31)),
        )
    )

    assert len(grouped) == 2
    assert grouped[1].roles == ("yoy", "mom")


def test_领域别名识别子集且成本短词保持歧义():
    selected = resolve_domain_mentions("分析收入、预算和资金")
    ambiguous = resolve_domain_mentions("分析成本")

    assert selected.selected == ("income", "budget", "funds")
    assert ambiguous.is_ambiguous is True


def test_发现只能引用已注册事实且相关性不得写成因果():
    builder = _builder()
    builder.add(
        fact_id="income-current",
        domain="income",
        metric="actual_medical_income",
        period="2025-01",
        value="100",
        raw_unit="元",
        evidence=EVIDENCE,
    )
    base = builder.build()
    fact_set = builder.build(metric_facts=build_metric_facts(base))
    metric_id = fact_set.metric_facts[0].fact_id

    result = build_findings(
        (
            FindingProposal(
                type="trend",
                domain="income",
                title="收入规模保持稳定",
                claim="本期收入规模为已注册事实。",
                factIds=(metric_id,),
                evidenceKind="derived_fact",
            ),
        ),
        fact_set,
        selected_domains=("income",),
    )
    assert result.findings[0].finding_id == "finding_001"

    with pytest.raises(ReportingError) as unbound_value:
        build_findings(
            (
                FindingProposal(
                    type="trend",
                    domain="income",
                    title="收入规模",
                    claim="本期收入为999元。",
                    factIds=(metric_id,),
                    evidenceKind="derived_fact",
                ),
            ),
            fact_set,
            selected_domains=("income",),
        )
    assert unbound_value.value.code == "report_findings_invalid"
    assert unbound_value.value.details["issues"][0]["path"] == "findings[0].claim"

    with pytest.raises(ReportingError) as base_fact:
        build_findings(
            (
                FindingProposal(
                    type="trend",
                    domain="income",
                    title="收入基础事实",
                    claim="基础事实不得直接用于发现。",
                    factIds=("income-current",),
                    evidenceKind="direct_fact",
                ),
            ),
            fact_set,
            selected_domains=("income",),
        )
    assert base_fact.value.details["issues"][0]["path"] == "findings[0].factIds"

    with pytest.raises(ValueError, match="相关性发现不得使用确定因果措辞"):
        FindingProposal(
            type="attribution",
            domain="income",
            title="收入与工作量相关",
            claim="工作量下降导致收入下降。",
            factIds=(metric_id,),
            evidenceKind="correlation",
        )


def test_动态提纲由服务端生成连续code且不接受重复发现归属():
    findings = (
        {"findingId": "finding_001", "domain": "income", "title": "收入趋势"},
        {"findingId": "finding_002", "domain": "income", "title": "收入异常"},
    )
    proposal = ReportOutlineProposal(
        reportType="topic",
        title="收入运营专题",
        sections=(
            OutlineSectionProposal(
                title="收入趋势与拐点",
                focus=("核对规模、趋势和关键月份",),
                findingIds=("finding_001",),
            ),
            OutlineSectionProposal(
                title="异常贡献与行动",
                focus=("定位异常贡献并形成管理行动",),
                findingIds=("finding_002",),
            ),
        ),
    )

    outline = freeze_outline(proposal, findings=findings)
    assert [section.code for section in outline.sections] == ["section_001", "section_002"]

    with pytest.raises(ValueError, match="未知 findingId"):
        freeze_outline(
            ReportOutlineProposal(
                reportType="topic",
                title="收入运营专题",
                sections=(
                    OutlineSectionProposal(
                        title="未知发现",
                        findingIds=("finding_999",),
                    ),
                ),
            ),
            findings=findings,
        )

    with pytest.raises(ValueError, match="extra_forbidden"):
        ReportOutlineProposal.model_validate(
            {
                "reportType": "topic",
                "title": "收入运营专题",
                "sections": [
                    {
                        "code": "section_001",
                        "title": "收入趋势",
                        "findingIds": ["finding_001"],
                    }
                ],
            }
        )

    with pytest.raises(ValueError, match="同一 findingId 只能归属一个动态章节"):
        ReportOutlineProposal(
            reportType="topic",
            title="收入运营专题",
            sections=(
                OutlineSectionProposal(title="趋势分析", findingIds=("finding_001",)),
                OutlineSectionProposal(title="异常分析", findingIds=("finding_001",)),
            ),
        )


def test_主领域本期事实完整时缺少对比期只形成非阻断披露():
    builder = _builder()
    builder.add(
        fact_id="income-current",
        domain="income",
        metric="actual_medical_income",
        period="2025-01",
        value="100",
        raw_unit="元",
        evidence=EVIDENCE,
    )
    base = builder.build()
    fact_set = builder.build(metric_facts=build_metric_facts(base))
    metric_id = next(item.fact_id for item in fact_set.metric_facts if item.publishable)

    gate = evaluate_publication_gate(
        fact_set,
        report_type="topic",
        selected_domains=("income",),
        referenced_fact_ids=(metric_id,),
    )

    comparison_issue = next(
        item for item in gate.issues if item.code == "comparison_period_unavailable"
    )
    assert comparison_issue.blocking is False
    assert gate.formal_release_allowed is True
