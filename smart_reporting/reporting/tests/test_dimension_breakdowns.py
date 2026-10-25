"""维度分组事实：按已确认可加的业务维度拆分求和指标，各组合计闭合、可引用、可核对。"""

import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.hospital_operation.finding_projection import (
    project_analysis_findings,
)
from smart_reporting.reporting.trace.fact_index import fact_entry_from_pointer, fact_pointer
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog, frozen_number_guide
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_references
from smart_reporting.reporting.trace.statement_review import statement_review_warnings

from .test_deterministic_analysis import analysis, context, semantic

FIELDS = ("month", "department", "income_type", "amount")
CSV = (
    "month,department,income_type,amount\n"
    "2025-01,A,住院,60\n2025-01,A,门诊,40\n"
    "2025-02,A,住院,90\n2025-02,B,门诊,-10\n2025-02,B,门诊,70\n"
)


def dimension(code, field, description):
    return {"code": code, "description": description,
            "fieldRefs": [f"dynamic_source.dynamic_db.dynamic_table.{field}"]}


DIMENSIONS = (
    dimension("income_type", "income_type", "收入业务类型；枚举由运行时画像确定。"),
    dimension("department", "department", "科室"),
    dimension("month", "month", "月份"),
)


def _bundle(csv=CSV, *, additive=("month", "department", "income_type"), fields=FIELDS, dimensions=DIMENSIONS,
            measures=None):
    measures = measures or ({**semantic("amount", unit="元"), "additiveAcross": list(additive)},)
    dataset = context("current", fields=fields, semantics=measures).model_copy(
        update={"period_granularities": {"month": "month"}})
    item = analysis(fields=tuple(str(measure["fieldRef"]).rsplit(".", 1)[-1] for measure in measures))
    return build_deterministic_analysis_bundle(
        item.model_copy(update={"series_granularity": "month"}),
        (("current", csv.encode(), dataset, ("current",)),), profile_dimensions=dimensions,
    )


def _groups(bundle, field):
    return {item.scope[field]: item for item in bundle.breakdowns if item.breakdown_field == field}


def test_breakdowns_partition_the_registered_total_by_confirmed_dimensions():
    bundle = _bundle()
    [parent] = bundle.metrics
    by_type, by_department = _groups(bundle, "income_type"), _groups(bundle, "department")
    # 期间字段不作为分组维度；分组只拆 Profile 维度且 additiveAcross 已确认的字段。
    assert {item.breakdown_field for item in bundle.breakdowns} == {"income_type", "department"}
    assert {name: item.total for name, item in by_type.items()} == {"住院": 150, "门诊": 100}
    assert sum(item.total for item in by_department.values()) == parent.total == 250
    inpatient = by_type["住院"]
    assert inpatient.parent_fact_id == parent.fact_id
    assert inpatient.scope == {"income_type": "住院"} and inpatient.breakdown_label == "收入业务类型"
    assert inpatient.display_name.endswith("（住院）")
    assert [(item.period, item.value) for item in inpatient.period_values] == [("2025-01", 60), ("2025-02", 90)]
    # 分组事实有独立 ID 与指针，父指标、同比、比率与对账输入不受影响。
    assert len({item.fact_id for item in bundle.breakdowns} | {parent.fact_id}) == len(bundle.breakdowns) + 1
    document = bundle.model_dump(mode="json", by_alias=True)
    pointer = fact_pointer(bundle, inpatient.fact_id)
    assert pointer.startswith("/breakdowns/")
    assert fact_entry_from_pointer(document, pointer) == ("metric", document["breakdowns"][int(pointer.rsplit("/", 1)[1])])
    without = _bundle(dimensions=())
    assert without.breakdowns == () and without.metrics == bundle.metrics
    assert "breakdowns" not in without.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize(("case", "expected"), [
    # 未确认可加的维度不拆：跨该字段汇总可能重复计数。
    ("unconfirmed", {"department"}),
    # 归属缺失的维度不拆：缺失行无法分配到任何一组。
    ("missing", {"income_type"}),
    # 只有一个非零取值的维度没有构成可言；全零分组不列出、不影响闭合。
    ("zero_groups", {"department"}),
])
def test_breakdowns_skip_unconfirmed_missing_or_degenerate_dimensions(case, expected):
    if case == "unconfirmed":
        bundle = _bundle(additive=("month", "department"))
    elif case == "missing":
        bundle = _bundle(CSV.replace("2025-02,B,门诊,70", "2025-02,,门诊,70"))
    else:
        bundle = _bundle("month,department,income_type,amount\n2025-01,A,住院,60\n2025-01,B,门诊,0\n"
                         "2025-02,B,住院,40\n")
    assert {item.breakdown_field for item in bundle.breakdowns} == expected
    if case == "zero_groups":
        assert set(_groups(bundle, "department")) == {"A", "B"}


def test_breakdown_values_are_citable_with_net_shares_and_monthly_series():
    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    parent = bundle.metrics[0].fact_id
    inpatient = _groups(bundle, "income_type")["住院"].fact_id
    tokens = [f"{{{{value:{inpatient}:{selector}}}}}" for selector in (
        "total:元", f"metricShare.{parent}:%", f"metricShare.{parent}.2025-02:%", "periodChangeRates.1:%")]
    catalog = frozen_number_catalog([content])
    assert [catalog.get(token) for token in tokens] == ["150元", "60.00%", "60.00%", "50.00%"]
    # 含冲销负值记录的指标按净额计算构成占比；分组级 groupShares 仍按原规则不登记。
    assert bundle.metrics[0].negative_count == 1
    assert not any(":groupShares." in token for token in catalog)
    resolved = resolve_number_references(tokens, [content])
    assert resolved[tokens[0]]["scope"] == {"income_type": "住院"}
    assert resolved[tokens[1]]["explanation"] == (
        "amount（住院）（2025年1—2月）150元 ÷ amount（2025年1—2月）250元 × 100% = 60%")
    # 任一分组净额为负时，占比之和不再是有意义的构成，不登记占比。
    negative = _bundle(CSV.replace("2025-02,B,门诊,70", "2025-02,B,门诊,-70")).model_dump_json(by_alias=True)
    assert not any(":metricShare." in token for token in frozen_number_catalog([negative]))


def test_breakdown_sentences_must_name_the_registered_group():
    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    token = f"{{{{value:{_groups(bundle, 'income_type')['住院'].fact_id}:total:元}}}}"
    assert statement_review_warnings(f"2025年1—2月住院收入{token}。", [content]) == []
    [warning] = statement_review_warnings(f"2025年1—2月门诊收入{token}。", [content])
    assert "income_type=住院" in warning


def test_number_guide_summarizes_groups_on_the_parent_and_keeps_group_items_compact():
    from smart_reporting.reporting.workflow.runtime.sections import _section_number_context

    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    catalog = frozen_number_catalog([content])
    guide = {item["factId"]: item for item in frozen_number_guide([content], catalog)}
    parent = guide[bundle.metrics[0].fact_id]
    by_type = next(entry for entry in parent["breakdowns"] if entry["field"] == "income_type")
    assert by_type["dimension"] == "income_type"
    assert [(group["group"], catalog[group["share"]]) for group in by_type["groups"]] == [("住院", "60.00%"), ("门诊", "40.00%")]
    inpatient = guide[by_type["groups"][0]["factId"]]
    assert inpatient["breakdownOf"] == parent["factId"] and "monthOverMonth" not in json.dumps(inpatient)
    assert [row[0] for row in inpatient["monthly"]["rows"]] == ["2025-01", "2025-02"]
    # 规划只看父指标概览；章节只在分组被选中时展开分组条目，父指标列出的分组引用仍可用。
    _, planning = _section_number_context([content], {})
    assert all("breakdownField" not in item for item in planning)
    visible, items = _section_number_context([content], {}, allowed_fact_ids={parent["factId"]})
    assert [item["factId"] for item in items] == [parent["factId"]]
    assert by_type["groups"][0]["total"] in visible
    _, selected = _section_number_context([content], {}, allowed_fact_ids={inpatient["factId"]})
    assert inpatient["factId"] in {item["factId"] for item in selected}


def test_breakdowns_project_one_composition_finding_per_dimension():
    bundle = _bundle()
    cards = project_analysis_findings("analysis_001", bundle, None, snapshot_hash="0" * 64,
                                      citation_ids=("citation_001",))
    composition = [card for card in cards if card.evidence_level == "direct_decomposition"]
    assert sorted(card.title for card in composition) == ["amount按收入业务类型构成", "amount按科室构成"]
    by_type = next(card for card in composition if "收入业务类型" in card.title)
    assert by_type.kind == "attribution" and by_type.grain == ("income_type",)
    assert "住院、门诊" in by_type.summary and "不证明业务因果" in by_type.summary
    assert [ref.pointer for ref in by_type.source_refs][0] == "/metrics/0"
    assert all(ref.pointer.startswith("/breakdowns/") for ref in by_type.source_refs[1:])


def test_budget_execution_pairs_groups_of_the_same_dimension_value():
    csv = ("month,budget_type,actual_amount,budget_amount\n"
           "2025-01,门诊业务,80,100\n2025-01,住院业务,150,200\n"
           "2025-02,门诊业务,90,100\n2025-02,住院业务,210,200\n")
    measures = tuple({**semantic(field, unit="元"), "additiveAcross": ["month", "budget_type"]}
                     for field in ("actual_amount", "budget_amount"))
    bundle = _bundle(csv, fields=("month", "budget_type", "actual_amount", "budget_amount"),
                     dimensions=(dimension("budget_type", "budget_type", "预算业务类型。"),), measures=measures)
    actual = next(item for item in bundle.breakdowns
                  if item.field == "actual_amount" and item.scope == {"budget_type": "住院业务"})
    budget = next(item for item in bundle.breakdowns
                  if item.field == "budget_amount" and item.scope == {"budget_type": "住院业务"})
    catalog = frozen_number_catalog([bundle.model_dump_json(by_alias=True)])
    token = f"{{{{value:{actual.fact_id}:budgetComparison.{budget.fact_id}.2025-01..2025-02.percentage:%}}}}"
    assert catalog[token] == "90.00%"


def test_model_facing_facts_list_breakdowns_by_parent_and_dimension():
    from smart_reporting.reporting.workflow.runtime.analysis import (
        _model_facing_deterministic_facts,
    )

    bundle = _bundle()
    projected = _model_facing_deterministic_facts(bundle)
    by_type = next(item for item in projected["breakdowns"] if item["field"] == "income_type")
    assert by_type["parentFactId"] == bundle.metrics[0].fact_id
    assert by_type["dimension"] == "收入业务类型"
    assert by_type["groups"][0] == {"value": "住院", "factId": _groups(bundle, "income_type")["住院"].fact_id,
                                    "total": 150, "periodValues": [["2025-01", 60], ["2025-02", 90]]}


def test_a_group_value_written_under_another_group_is_flagged():
    from smart_reporting.reporting.trace.review_attribution import _group_value_attribution_warnings

    # 住院合计 153 元不与其他登记值相同；写在门诊名下时只可能是住院的分组值。
    csv = ("month,department,income_type,amount\n2025-01,A,住院,61\n2025-01,A,门诊,40\n"
           "2025-02,A,住院,92\n2025-02,B,门诊,57\n")
    documents = [_bundle(csv).model_dump(mode="json", by_alias=True)]
    [warning] = _group_value_attribution_warnings("2025年1—2月门诊收入153元。", documents)
    assert "门诊名下的153元是住院的登记值" in warning
    assert _group_value_attribution_warnings("2025年1—2月住院收入153元。", documents) == []


def test_every_breakdown_formula_recomputes_to_the_result_it_shows():
    from decimal import Decimal

    from .test_reader_formulas import _amounts, _recomputed

    content = _bundle().model_dump_json(by_alias=True)
    checked = 0
    for token, selected in resolve_number_references(list(frozen_number_catalog([content])), [content]).items():
        explanation = (selected or {}).get("explanation") or ""
        if "（" not in token and " = " in explanation and "fact-" in token:
            [shown] = _amounts(explanation.rsplit(" = ", 1)[1])[:1]
            assert abs(_recomputed(explanation) - shown) <= Decimal("0.01"), (token, explanation)
            checked += 1
    assert checked > 20


def test_breakdowns_respect_the_bundle_budget_with_a_soft_warning(monkeypatch):
    from smart_reporting.reporting.hospital_operation import deterministic_analysis

    # 超出分组条数上限只跳过其余维度并软告警，父指标与已登记分组照常保留。
    monkeypatch.setattr(deterministic_analysis, "BREAKDOWN_BUDGET", 2)
    bundle = _bundle()
    assert len(bundle.breakdowns) == 2 and len(bundle.metrics) == 1
    assert any("维度分组达到 2 条上限" in warning for warning in bundle.warnings)


def test_overflowing_group_sum_skips_only_that_dimension(monkeypatch):
    from smart_reporting.reporting.hospital_operation import deterministic_analysis

    original = deterministic_analysis._breakdown_fact

    def overflow(fact, field, *args, **kwargs):
        if field == "income_type":
            raise deterministic_analysis._NonFiniteMetricError("溢出")
        return original(fact, field, *args, **kwargs)

    # 某维度的分组求和溢出只跳过该维度，父指标与其他维度照常登记，不让整个分析项失败。
    monkeypatch.setattr(deterministic_analysis, "_breakdown_fact", overflow)
    bundle = _bundle()
    assert len(bundle.metrics) == 1
    assert {item.breakdown_field for item in bundle.breakdowns} == {"department"}


def test_two_profile_dimensions_on_one_column_are_split_once():
    twin = (*DIMENSIONS, dimension("income_kind", "income_type", "收入类别"))
    bundle = _bundle(dimensions=twin)
    assert sorted(item.scope["income_type"] for item in bundle.breakdowns
                  if item.breakdown_field == "income_type") == ["住院", "门诊"]
    # 分组只带数据集级说明，不复制父指标的整体序列告警。
    assert all(len(item.warnings) <= len(bundle.metrics[0].warnings) for item in bundle.breakdowns)


def test_parent_dependency_adds_only_group_totals_and_shares_to_the_prompt_catalog():
    from smart_reporting.reporting.workflow.runtime.sections import _section_number_context

    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    parent = bundle.metrics[0].fact_id
    visible, _ = _section_number_context([content], {}, allowed_fact_ids={parent})
    group_tokens = [token for token in visible if token.split(":", 2)[1] != parent]
    assert group_tokens
    assert all(token.split(":")[2] in {"total", f"metricShare.{parent}"} for token in group_tokens)


def test_evidence_view_adds_the_budget_group_for_a_selected_actual_group():
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view

    csv = ("month,budget_type,actual_amount,budget_amount\n2025-01,门诊业务,80,100\n2025-01,住院业务,150,200\n"
           "2025-02,门诊业务,90,100\n2025-02,住院业务,210,200\n")
    measures = tuple({**semantic(field, unit="元"), "additiveAcross": ["month", "budget_type"]}
                     for field in ("actual_amount", "budget_amount"))
    bundle = _bundle(csv, fields=("month", "budget_type", "actual_amount", "budget_amount"),
                     dimensions=(dimension("budget_type", "budget_type", "预算业务类型。"),), measures=measures)
    content = bundle.model_dump_json(by_alias=True)
    index = next(i for i, item in enumerate(bundle.breakdowns)
                 if item.field == "actual_amount" and item.scope == {"budget_type": "住院业务"})
    budget = next(item for item in bundle.breakdowns
                  if item.field == "budget_amount" and item.scope == {"budget_type": "住院业务"})
    import hashlib
    from types import SimpleNamespace

    identity = SimpleNamespace(path="facts/analysis_001.json", sha256=hashlib.sha256(content.encode()).hexdigest())
    source = SimpleNamespace(identity=identity, content=content, model_copy=lambda update: SimpleNamespace(**update))
    work_item = SimpleNamespace(finding_ids=("finding_x",), analysis_ids=("analysis_001",), section_code="s1",
                                finding_summaries=({"findingId": "finding_x", "sourceRefs": [
                                    {"path": identity.path, "fileSha256": identity.sha256,
                                     "analysisId": "analysis_001", "pointer": f"/breakdowns/{index}"}]},))
    _, fact_ids, _ = finding_evidence_view((source,), work_item)
    assert budget.fact_id in fact_ids


def test_calc_mixing_a_group_with_its_parent_is_not_flagged_as_mixed_aggregation():
    from smart_reporting.reporting.trace.content_review import review_content

    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    parent = bundle.metrics[0].fact_id
    group = _groups(bundle, "income_type")["住院"].fact_id
    text = f"门诊收入为{{{{calc:diff({parent}:total,{group}:total):元}}}}。"
    assert not any("口径需确认" in warning for warning in review_content(text, [content]))


def test_group_values_belong_to_their_parent_in_metric_attribution():
    from smart_reporting.reporting.trace.review_attribution import (
        _metric_value_attribution_warnings,
    )

    bundle = _bundle()
    content = bundle.model_dump_json(by_alias=True)
    documents = [json.loads(content)]
    labels = {"amount": "收入金额"}
    # 只有一个指标时无从判定归属；这里只验证分组值不再是“中性”登记值而豁免检查。
    assert _metric_value_attribution_warnings("收入金额150元。", [content], documents, labels) == []


def test_oversized_instruction_drops_breakdown_detail_before_failing():
    from smart_reporting.reporting.workflow.runtime.analysis import (
        _model_facing_deterministic_facts,
    )

    bundle = _bundle()
    full = _model_facing_deterministic_facts(bundle)
    totals = _model_facing_deterministic_facts(bundle, breakdown_detail="totals")
    none = _model_facing_deterministic_facts(bundle, breakdown_detail="none")
    assert "periodValues" in full["breakdowns"][0]["groups"][0]
    assert "periodValues" not in totals["breakdowns"][0]["groups"][0]
    assert "breakdowns" not in none and none["metrics"] == full["metrics"]


def test_chart_descriptors_never_bind_rows_from_different_dimensions():
    from smart_reporting.reporting.workflow.runtime.analysis import _breakdown_descriptors

    rows = [item.model_dump(mode="json", by_alias=True) for item in _bundle().breakdowns]
    paths = [item["dataPath"] for item in _breakdown_descriptors(rows)]
    # 两个维度并存：整表按行绑定会把两套分组相加，只能逐组选取。
    assert "breakdowns" not in paths
    assert {f"breakdowns[{index}]" for index in range(len(rows))} <= set(paths)
    single = [row for row in rows if row["breakdownField"] == "income_type"]
    assert "breakdowns" in [item["dataPath"] for item in _breakdown_descriptors(single)]
