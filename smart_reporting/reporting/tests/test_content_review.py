from __future__ import annotations

import json

import pytest

from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog


def _metric(field="actual", values=(10, 20, 0)):
    return {"factId": "fact-" + "a" * 16, "datasetId": "current", "datasetSha256": "b" * 64,
            "periodRoles": ["current"], "field": field, "fieldRef": "hospital.budget." + field,
            "aggregation": "sum", "unit": "人次", "formula": "sum(actual)", "total": sum(values),
            "missingCount": 0, "zeroCount": 1, "negativeCount": 0, "periodGranularity": "month",
            "periodValues": [{"period": f"2025-{index:02d}-01", "value": value}
                             for index, value in enumerate(values, 1)]}


def test_monthly_frozen_prefix_does_not_round_before_adding():
    fact = _metric(values=(606259,) * 12)
    catalog = frozen_number_catalog([json.dumps({"analysisId": "analysis_001", "metrics": [fact]})])
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:periodTotals.0-9:人次}}"] == "6,062,590人次"
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:人次}}"] == "606,259人次"
    assert review_content("同期预算6,062,600人次", [json.dumps({"analysisId": "analysis_001", "metrics": [fact]})])
    assert review_content("同期预算6,062,590人次", [json.dumps({"analysisId": "analysis_001", "metrics": [fact]})]) == []


def test_review_keeps_registered_values_and_flags_invented_units():
    content = json.dumps({"analysisId": "analysis_001", "metrics": [_metric()]})
    assert review_content("实际累计{{value:fact-aaaaaaaaaaaaaaaa:total:人次}}", [content]) == []
    assert review_content("实际累计300元", [content])
    assert review_content("实际累计300人次", [content])
    assert review_content("补充科室金额123.45元", [content, '{"departmentAmount":123.45}']) == []


def test_amount_extrema_does_not_apply_to_type_share_extrema():
    fact = {**_metric(values=(100, 70, 80)), 'unit': '元'}
    content = json.dumps({'analysisId': 'analysis_001', 'metrics': [fact]})
    assert review_content('3月卫生材料成本占比最高。', [content]) == []
    assert review_content('3月手术室组织明细为最高单项。', [content]) == []
    assert any('最高月份为1月' in w for w in review_content('3月成本总额最高。', [content]))


def test_multi_metric_extrema_uses_unique_heading_field_definition():
    first = _metric("actual_open_bed", (149301, 134405, 132706))
    second = {**_metric("discharges_bed", (110625, 105655, 104718)), "factId": "fact-" + "c" * 16}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [first, second]})
    labels = {"actual_open_bed": "实际开放床日数", "discharges_bed": "出院者占用床日数"}
    text = "### 实际开放床日数月度走势\n\n低点：2月为134,405人次。\n\n### 出院者占用床日数走势\n\n2月为期间最低值105,655人次。"
    warnings = review_content(text, [content], field_definitions=labels)
    assert sum("冻结月序列的最低月份为3月" in warning for warning in warnings) == 2
    assert review_content("### 两项指标走势\n\n2月最低", [content], field_definitions=labels) == []


def test_multi_metric_extrema_uses_explicit_paragraph_label_and_deduplicates_facts():
    outpatient = _metric("mantime_outpatient", (562826, 527550, 644217, 420422))
    discharges = {**_metric("mantime_discharges", (22000, 18000, 25000, 20000)),
                  "factId": "fact-" + "c" * 16}
    contents = [json.dumps({"analysisId": analysis, "metrics": [outpatient, discharges]})
                for analysis in ("analysis_001", "analysis_002")]
    labels = {"mantime_outpatient": "门诊人次", "mantime_discharges": "出院人次"}
    text = "### 三项指标月度走势与拐点特征\n\n门诊人次在2月录得527,550人次，为期间最低值。"
    warnings = review_content(text, contents, field_definitions=labels)
    assert sum("门诊人次：月度极值" in warning and "最低月份为4月" in warning
               for warning in warnings) == 1
    assert review_content("门诊人次1—2月中2月最低，为527,550人次。", contents,
                          field_definitions=labels) == []
    assert review_content("门诊人次与出院人次在2月最低。", contents,
                          field_definitions=labels) == []


def test_paragraph_extrema_does_not_confuse_subset_or_conflicting_snapshots():
    outpatient = _metric("outpatient", (20, 10, 5))
    subset = {**_metric("outpatient_non", (15, 5, 10)), "factId": "fact-" + "c" * 16}
    labels = {"outpatient": "门诊人次", "outpatient_non": "不含体检和急诊门诊人次"}
    contents = [json.dumps({"analysisId": "analysis_001", "metrics": [outpatient, subset]})]
    assert review_content("不含体检和急诊门诊人次在2月最低，为5人次。", contents,
                          field_definitions=labels) == []
    assert review_content("门诊人次与不含体检和急诊门诊人次在1月最低。", contents,
                          field_definitions=labels) == []
    other = {**_metric("outpatient", (20, 5, 10)), "factId": "fact-" + "d" * 16}
    contents.append(json.dumps({"analysisId": "analysis_002", "metrics": [other, subset]}))
    assert review_content("门诊人次在2月最低。", contents, field_definitions=labels) == []
    warnings = review_content("[[analysis:analysis_001]]门诊人次在2月最低。", contents,
                              field_definitions=labels)
    assert any("最低月份为3月" in warning for warning in warnings)


def test_extrema_range_inside_claim_is_not_mistaken_for_another_month_claim():
    fact = _metric(values=(545329, 527550, 644217, 420422, 0))
    content = json.dumps({'analysisId': 'analysis_001', 'metrics': [fact]})
    warnings = review_content('2月为1—4月期间最低值527,550人次。', [content])
    assert any('2月被写为最低' in w and '最低月份为4月' in w for w in warnings)
    assert review_content('4月为1—4月期间最低值420,422人次。', [content]) == []
    assert review_content('1—3月期间波动；4月为有数据月份中的最低值。', [content]) == []


def test_explicit_year_extrema_checks_comparison_year_without_using_current_year():
    current = _metric(values=(10, 20, 30))
    previous = {**_metric(values=(30, 10, 20)), "factId": "fact-" + "c" * 16,
                "periodRoles": ["comparison"]}
    previous["periodValues"] = [{**item, "period": item["period"].replace("2025", "2024")}
                                for item in previous["periodValues"]]
    contents = [json.dumps({"analysisId": "analysis_001", "metrics": [current, previous]})]
    incorrect = "按2025年1—3月月度原始金额，3月最高；按2024年1—3月月度原始金额，3月最高。"
    warnings = review_content(incorrect, contents)
    assert any("2024年" in warning and "最高月份为1月" in warning for warning in warnings)
    assert not any("2025年" in warning for warning in warnings)
    assert review_content(incorrect.replace("2024年1—3月月度原始金额，3月", "2024年1—3月月度原始金额，1月"), contents) == []


def test_explicit_year_extrema_skips_ambiguous_metrics():
    first = _metric("income", values=(10, 20, 30))
    second = {**_metric("cost", values=(30, 20, 10)), "factId": "fact-" + "c" * 16}
    contents = [json.dumps({"analysisId": "analysis_001", "metrics": [first, second]})]
    assert review_content("2025年两项指标2月最高。", contents) == []
    warnings = review_content("2025年收入2月最高。", contents,
                              field_definitions={"income": "收入", "cost": "成本"})
    assert any("最高月份为3月" in warning for warning in warnings)
    warnings = review_content("2025年2月最高。", contents, fact_ids=[first["factId"]])
    assert any("最高月份为3月" in warning for warning in warnings)
    assert review_content("2025年2月最高。", contents, fact_ids=[]) == []


def _project_execution_evidence():
    return {'findings': [{'name': '预算类型执行',
        'columns': ['budget_type', 'budget_project_amount', 'contract_amount', 'payment_amount'],
        'rows': [['专用设备', 100000, 51900, 41390], ['信息化建设', 100000, 84010, 19650]],
        'columnMeta': {field: {'unit': '元', 'periodRole': 'current'} for field in
                       ('budget_project_amount', 'contract_amount', 'payment_amount')}}]}


def test_project_execution_ranking_checks_each_named_ratio_against_same_evidence():
    contents = [json.dumps(_project_execution_evidence())]
    warnings = review_content('专用设备签约率和付款率在各类型中相对最高。', contents)
    assert len(warnings) == 1
    assert '签约率排名需复核' in warnings[0] and '信息化建设' in warnings[0]
    assert review_content('专用设备付款率最高。信息化建设签约率最高。', contents) == []
    assert review_content('专用设备签约率不是最高。', contents) == []
    assert review_content('专用设备与信息化建设签约率最高。', contents) == []


def test_project_execution_ranking_skips_untyped_mixed_scope_and_conflicting_evidence():
    evidence = _project_execution_evidence()
    evidence['findings'][0]['columnMeta']['contract_amount']['unit'] = '万元'
    assert review_content('专用设备签约率最高。', [json.dumps(evidence)]) == []
    evidence = _project_execution_evidence()
    evidence['findings'][0]['columnMeta']['contract_amount']['periodRole'] = 'yoy'
    assert review_content('专用设备签约率最高。', [json.dumps(evidence)]) == []
    other = _project_execution_evidence()
    other['findings'][0]['rows'][0][2] = 99000
    assert review_content('专用设备签约率最高。', [json.dumps(_project_execution_evidence()),
                       json.dumps(other)]) == []
    assert review_content('1月专用设备签约率最高。', [json.dumps(_project_execution_evidence())]) == []


def test_project_execution_ranking_never_compares_groups_from_separate_tables():
    evidence = _project_execution_evidence()
    first = evidence['findings'][0]
    second = {**first, 'rows': [['其他类型', 100000, 99000, 90000], ['另一类型', 100000, 98000, 80000]]}
    first['rows'] = [['专用设备', 100000, 51900, 41390], ['信息化建设', 100000, 30000, 19650]]
    evidence['findings'].append(second)
    assert review_content('专用设备签约率最高。', [json.dumps(evidence)]) == []


@pytest.mark.parametrize("text", [
    "负值可能源于冲销或调整分录。", "低点系该月自然天数较少所致。",
    "金山院区尚未启动采购流程。", "字段未填充有效数值。", "11月无实际支出记录。",
])
def test_review_requests_evidence_for_inference_instead_of_accepting_zero_as_status(text):
    assert any("直接证据" in warning for warning in review_content(text, []))


def test_review_field_level_keeps_metadata_definition():
    definitions = {"rdlevel_analytic_unit": "三级科室"}
    assert review_content("rdlevel_analytic_unit（一级科室）存在缺失值。", [], field_definitions=definitions)
    assert review_content("rdlevel_analytic_unit（三级科室）存在缺失值。", [], field_definitions=definitions) == []


def test_review_continuous_trend_checks_each_frozen_month_and_skips_gaps():
    fact = _metric(values=(385662470, 385318383, 392628849))
    fact["periodValues"] = [{**item, "period": f"2025-{index:02d}-01"}
                            for index, item in enumerate(fact["periodValues"], 7)]
    content = json.dumps({"analysisId": "analysis_001", "metrics": [fact]})
    assert any("7月→8月" in warning for warning in review_content("7—9月连续上升。", [content]))
    assert review_content("8月至9月连续增加。", [content]) == []
    assert review_content("6—9月连续上升。", [content]) == []


@pytest.mark.parametrize("text", ["7-9月连续回升。", "7月至9月连续三个月回升。"])
def test_review_continuous_recovery_uses_frozen_months(text):
    fact = _metric(values=(385662470, 385318383, 392628849))
    fact["periodValues"] = [{**item, "period": f"2025-{index:02d}-01"}
                            for index, item in enumerate(fact["periodValues"], 7)]
    content = json.dumps({"analysisId": "analysis_001", "metrics": [fact]})
    assert any("7月→8月" in warning for warning in review_content(text, [content]))


def test_review_unknown_number_reference_requests_correction():
    assert any("未登记" in warning for warning in review_content("总量{{value:fact-unknown:total:人次}}", []))


def test_frozen_group_values_keep_exact_amount_and_unit_conversion():
    fact = {**_metric(values=(2616255731,)), "unit": "元",
            "topGroups": [{"group": "2025-09 / 门诊血液", "value": 21135987}],
            "bottomGroups": [{"group": "2025-09 / 药剂科公共", "value": -1037}],
            "minimum": -1037, "maximum": 21135987}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [fact]})
    catalog = frozen_number_catalog([content])
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:topGroups.0:元}}"] == "21,135,987元"
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:topGroups.0:万元}}"] == "2,113.60万元"
    assert review_content("门诊血液21,135,987元，药剂科公共-1,037元。", [content]) == []
    assert review_content("门诊血液21,140,000元。", [content])


def test_review_prefix_period_does_not_accept_full_year_total():
    fact = _metric(values=(606259,) * 12)
    content = json.dumps({"analysisId": "analysis_001", "metrics": [fact]})
    warnings = review_content("2025年1—10月，全院预算人次合计7,275,108人次。", [content])
    assert any("6,062,590人次" in warning and "累计期间" in warning for warning in warnings)
    assert review_content("2025年1—10月，全院预算人次合计6,062,590人次。", [content]) == []
    assert review_content("2025年1—12月，全院预算人次合计7,275,108人次。", [content]) == []
    assert any("累计期间" in warning for warning in review_content(
        "2025年1—10月，全院预算人次合计7,275,108[[claim:claim_001]]人次。", [content]))


def test_review_natural_days_cause_needs_direct_evidence():
    assert any('直接证据' in warning for warning in review_content('2月因自然天数较少，两项指标均为年内低谷。', []))


def test_review_annual_budget_allocation_is_not_a_subperiod_total():
    content = json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})
    text = "2025年1—9月各月预算诊疗人次均为606,259人次，系年度预算总量7,275,108[[claim:claim_006]]人次按月均摊形成。"
    assert review_content(text, [content]) == []
    wrong = "2025年1—9月预算人次累计7,275,108人次。年度预算总量7,275,108人次按月均摊。"
    assert any("累计期间" in warning for warning in review_content(wrong, [content]))


@pytest.mark.parametrize('text', [
    '零值不能直接证明尚未启动采购。',
    '不能认定字段未填充有效数值。',
    '不足以证明11月无实际支出记录。',
    '不可因零值推断疑似未入账。',
])
def test_negated_business_inference_does_not_warn(text):
    assert review_content(text, []) == []


def test_negation_does_not_hide_an_assertion_in_another_clause():
    text = '零值不能证明未入账，但院区尚未启动采购。负值可能源于冲销，原因待核实。'
    warnings = review_content(text, [])
    assert any('尚未启动采购' in warning for warning in warnings)
    assert any('可能源于' in warning for warning in warnings)


def test_repeated_unknown_numeric_value_warns_once_across_formats():
    warnings = review_content('合计1234元，表格1,234 元，图注1,234.00元；其他1235元。', [])
    assert len(warnings) == 2


def test_explicit_subperiod_extrema_keeps_zero_months_outside_that_window():
    content = json.dumps({'analysisId': 'analysis_001', 'metrics': [_metric(values=(20, 10, 0))]})
    assert review_content('1—2月，2月最低，为10人次。', [content]) == []
    assert any('最低月份为2月' in warning for warning in review_content('1—2月，1月最低，为20人次。', [content]))
    assert any('最低月份为3月' in warning for warning in review_content('全年2月最低。', [content]))


def test_number_guide_distinguishes_row_month_prefix_and_group():
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    fact = {**_metric(values=(20, 10, 0)), 'average': 2, 'minimum': -1, 'maximum': 5,
            'topGroups': [{'group': '2025-01 / 总部院区 / 血液内科', 'value': 5}]}
    content = json.dumps({'analysisId': 'analysis_001', 'metrics': [fact]})
    catalog = frozen_number_catalog([content])
    guide = frozen_number_guide([content], catalog, field_definitions={'actual': '实际人次'})[0]
    assert guide['metric'] == '实际人次'
    assert guide['total']['periods'][-1] == '2025-03-01'
    assert guide['rowStatistics']['minimum'] == '{{value:fact-aaaaaaaaaaaaaaaa:minimum:人次}}'
    assert guide['monthlyStatistics']['minimumPeriods'] == ['2025-03-01']
    assert guide['monthlyStatistics']['zeroPeriods'] == ['2025-03-01']
    prefix = guide['monthlyStatistics']['prefixTotals'][1]
    assert prefix['end'] == '2025-02-01'
    assert catalog[prefix['reference']] == '30人次'
    assert guide['groups'][0]['group'] == '2025-01 / 总部院区 / 血液内科'
    assert catalog[guide['groups'][0]['reference']] == '5人次'


def _budget_pair_contents(actual_values=(562826, 542558, 0), budget_values=(606259, 606259, 606259), **budget_updates):
    actual = {**_metric('actual_person_time', actual_values), 'metricCodes': ['actual_person_time']}
    budget = {**_metric('budget_person_time', budget_values), 'factId': 'fact-' + 'b' * 16,
              'metricCodes': ['budget_person_time'], **budget_updates}
    return json.dumps({'analysisId': 'analysis_001', 'metrics': [budget, actual]})


def test_budget_comparison_calculates_registered_months_and_zero_numerator():
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    content = _budget_pair_contents()
    catalog = frozen_number_catalog([content])
    guide = frozen_number_guide([content], catalog)[1]['budgetComparisons']
    month = next(item for item in guide if item['period'] == '2025-01')
    assert catalog[month['references']['difference']] == '-43,433人次'
    assert catalog[month['references']['percentage']] == '92.84%'
    prefix = next(item for item in guide if item['period'] == '2025-01..2025-02')
    assert catalog[prefix['references']['difference']] == '-107,134人次'
    zero = next(item for item in guide if item['period'] == '2025-03')
    assert catalog[zero['references']['percentage']] == '0.00%'
    assert review_content('1月92.8%，3月0%。', [content]) == []
    assert any('93.8%' in warning for warning in review_content('1月93.8%。', [content]))


def test_budget_comparison_zero_denominator_has_no_percentage_reference():
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    content = _budget_pair_contents(budget_values=(0, 606259, 606259))
    catalog = frozen_number_catalog([content])
    guide = frozen_number_guide([content], catalog)[1]['budgetComparisons']
    month = next(item for item in guide if item['period'] == '2025-01')
    assert month['references']['percentage'] is None
    assert catalog[month['references']['difference']] == '562,826人次'


@pytest.mark.parametrize('updates', [
    {'datasetId': 'another'}, {'datasetSha256': 'c' * 64}, {'scope': {'area': '总部'}},
    {'unit': '元'}, {'periodRoles': ['yoy']}, {'fieldRef': 'hospital.other.budget_person_time'},
])
def test_budget_comparison_rejects_different_identity_scope_or_unit(updates):
    catalog = frozen_number_catalog([_budget_pair_contents(**updates)])
    assert not any('budgetComparison' in token for token in catalog)


def test_budget_comparison_does_not_bridge_missing_month_or_ambiguous_budget():
    document = json.loads(_budget_pair_contents())
    document['metrics'][0]['periodValues'][1]['period'] = '2025-04-01'
    assert not any('budgetComparison' in token for token in frozen_number_catalog([json.dumps(document)]))
    document = json.loads(_budget_pair_contents())
    document['metrics'].append({**document['metrics'][0], 'factId': 'fact-' + 'c' * 16})
    assert not any('budgetComparison' in token for token in frozen_number_catalog([json.dumps(document)]))


def test_budget_currency_difference_keeps_exact_yuan_and_converted_wanyuan():
    document = json.loads(_budget_pair_contents())
    for fact in document['metrics']:
        fact['unit'] = '元'
    catalog = frozen_number_catalog([json.dumps(document)])
    prefix = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01.difference:'
    assert catalog[prefix + '元}}'] == '-43,433元'
    assert catalog[prefix + '万元}}'] == '-4.34万元'


def test_budget_percentage_review_rounds_once_from_exact_calculation():
    content = _budget_pair_contents(actual_values=(10049,), budget_values=(100000,))
    assert review_content('完成率10.0%。', [content]) == []
    assert review_content('完成率10.05%。', [content]) == []
    assert any('10.1%' in warning for warning in review_content('完成率10.1%。', [content]))


@pytest.mark.parametrize(('rate', 'denominator', 'warns'), [
    ('95.14', '全年预算总额', True),
    ('79.28', '全年预算总额', False),
    ('95.14', '同期间预算总额', False),
])
def test_review_budget_rate_checks_explicit_annual_denominator(rate, denominator, warns):
    document = json.loads(_budget_pair_contents(actual_values=(1044347374.7,) * 10, budget_values=(1097718506,) * 12))
    for entry in document['metrics']:
        entry['unit'] = '元'
    text = (f'2025年1—10月实际医疗收入累计10,443,473,747元，{denominator}为13,172,622,072元。'
            f'按1—10月累计实际收入与{denominator}之比计算，执行率为{rate}%。')
    issues = review_content(text, [json.dumps(document)])
    found = [issue for issue in issues if '预算分母口径' in issue]
    assert bool(found) is warns
    if warns:
        assert '79.28%' in found[0]


def test_review_budget_denominator_does_not_join_different_snapshots():
    document = json.loads(_budget_pair_contents(actual_values=(1044347374.7,) * 10, budget_values=(1097718506,) * 12, datasetSha256='c' * 64))
    for entry in document['metrics']:
        entry['unit'] = '元'
    text = '2025年1—10月实际医疗收入累计10,443,473,747元，全年预算总额为13,172,622,072元。执行率为95.14%。'
    assert not any('预算分母口径' in issue for issue in review_content(text, [json.dumps(document)]))


def test_review_budget_annual_context_does_not_override_explicit_same_period_formula():
    document = json.loads(_budget_pair_contents(actual_values=(1044347374.7,) * 10, budget_values=(1097718506,) * 12))
    for entry in document['metrics']:
        entry['unit'] = '元'
    text = ('2025年1—10月实际医疗收入累计10,443,473,747元，全年预算总额为13,172,622,072元。'
            '同期间预算为10,977,185,060元，按实际收入与同期间预算之比计算，执行率为95.14%。')
    assert not any('预算分母口径' in issue for issue in review_content(text, [json.dumps(document)]))


def test_rounded_text_is_checked_against_raw_frozen_values_not_display_text():
    # 原值 12,450元 = 1.245万元，显示值舍入为 1.25万元；正文写一位小数时应从原值舍入（1.2），
    # 不能把显示值再舍入一次（1.3），否则正确数字被误报、错误数字被放过。
    content = json.dumps({"analysisId": "analysis_001", "metrics": [{**_metric(values=(12450,)), "unit": "元"}]})
    assert not [warning for warning in review_content("收入1.2万元。", [content]) if "冻结依据" in warning]
    assert [warning for warning in review_content("收入1.3万元。", [content]) if "冻结依据" in warning]
    assert not [warning for warning in review_content("收入1.25万元。", [content]) if "冻结依据" in warning]
