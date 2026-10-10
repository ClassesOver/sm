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


def test_review_flags_internal_ids_and_raw_field_names_in_visible_prose():
    content = json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(10, 20, 0))]})
    fields = {"actual": "实际门诊人次", "indicator_value": "指标值"}
    # 协议标记里的内部 ID 不可见，不告警；正文里直接写出的 ID 和英文字段名须改为业务名称。
    clean = "[[analysis:analysis_001]]实际门诊人次保持稳定[[citation:cite_001]]。"
    assert not [w for w in review_content(clean, [content], field_definitions=fields) if "内部" in w]
    leaked = "根据 analysis_001 的 indicator_value，fact-" + "a" * 16 + " 显示 actual 上升。"
    warnings = [w for w in review_content(leaked, [content], field_definitions=fields) if "内部" in w]
    assert any("analysis_001" in w for w in warnings)
    assert any("fact-" + "a" * 16 in w for w in warnings)
    assert any("indicator_value" in w and "指标值" in w for w in warnings)
    assert any("actual" in w and "实际门诊人次" in w for w in warnings)
    # 英文单词的一部分不算字段名泄漏。
    assert not [w for w in review_content("actually 稳定。", [content], field_definitions=fields) if "内部" in w]


@pytest.mark.parametrize(("text", "kind"), [
    ("收入同比下降-5.20%。", "重复"),
    ("门诊量减少了 -1,200人次。", "重复"),
    ("收入同比增长-5.20%。", "矛盾"),
    ("收入同比下降5.20%。", None),
    ("收入变化率为-5.20%。", None),
    ("收入同比增长5.20%。", None),
])
def test_review_flags_sign_and_direction_wording(text, kind):
    # 负值占位渲染后带负号：“下降-5.20%”双重否定，“增长-5.20%”方向矛盾；读者易误读。
    warnings = [w for w in review_content(text, []) if "符号" in w or "方向" in w]
    if kind is None:
        assert warnings == []
    else:
        assert len(warnings) == 1 and kind in warnings[0]


def test_repeated_sentences_across_blocks_are_flagged_for_correction():
    from smart_reporting.reporting.trace.content_review import repeated_sentence_warnings

    earlier = ["本期门诊收入保持稳定增长，结构持续优化[[citation:cite_001]]。\n\n其他内容。"]
    # 标记、加粗与标点差异不影响判定；短句（如“其他内容”）不算重复。
    current = "**本期门诊收入保持稳定增长，结构持续优化**。其他内容。新增住院分析结论较为明确。"
    warnings = repeated_sentence_warnings(current, earlier)
    assert len(warnings) == 1 and "本期门诊收入保持稳定增长" in warnings[0]
    assert repeated_sentence_warnings("新增住院分析结论较为明确。", earlier) == []


def test_readability_warnings_ask_to_split_long_or_number_dense_sentences():
    from smart_reporting.reporting.trace.content_review import readability_warnings

    dense = "1月收入100元、2月120元、3月130元、4月90元、5月80元、6月70元[[citation:cite_001]]。"
    long_sentence = "本期" + "门诊收入保持稳定增长并且结构持续优化" * 9 + "。"
    table = "| 月份 | 1月 | 2月 | 3月 | 4月 | 5月 | 6月 |\n| --- | 1元 | 2元 | 3元 | 4元 | 5元 | 6元 |"
    warnings = readability_warnings("\n\n".join([dense, long_sentence, table, "## 收入" + "很长" * 80]))
    assert len(warnings) == 2
    assert any("数值过多" in w for w in warnings) and any("句子过长" in w for w in warnings)
    assert readability_warnings("1月收入100元，2月120元。本期结构稳定。") == []
    token = "{{value:fact-" + "a" * 16 + ":total:元}}"
    # 占位按显示值度量：6 个占位即 6 个数值。
    assert any("数值过多" in w for w in readability_warnings("、".join([token] * 6) + "。", {token: "100元"}))


def test_prose_checks_skip_server_tables_behind_protocol_markers():
    from smart_reporting.reporting.trace.content_review import (
        readability_warnings,
        repeated_sentence_warnings,
    )

    # 服务端表格格式：[[table:id]] 紧贴表头，不隔空行；表格行不是正文句子。
    table = (
        "收入分月汇总\n\n[[table:table-analysis_001]]\n| | 1月 | 2月 | 3月 | 4月 | 5月 | 6月 |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 门诊收入（元） | 100元 | 120元 | 130元 | 90元 | 80元 | 70元 |\n\n[[/table:table-analysis_001]]"
    )
    assert readability_warnings(table) == []
    assert repeated_sentence_warnings(table, [table]) == []


def test_repeated_sentences_compare_displayed_numbers_not_placeholders():
    from smart_reporting.reporting.trace.content_review import repeated_sentence_warnings

    token = "{{value:fact-" + "a" * 16 + ":total:元}}"
    # 已采纳 block 中数值已渲染；当前 block 仍是占位，须按显示值比较。
    earlier = ["本期门诊收入合计为1,234元，较上期保持稳定。"]
    current = f"本期门诊收入合计为{token}，较上期保持稳定。"
    assert len(repeated_sentence_warnings(current, earlier, {token: "1,234元"})) == 1


def test_percentage_point_differences_must_come_from_two_registered_percentages():
    supplement = json.dumps({"findings": [{"columns": ["year", "share"], "rows": [["2024", 41.7], ["2025", 45.24]],
                                           "columnMeta": {"share": {"unit": "%", "isPercent": True}}}]})

    def pp_warnings(text):
        return [w for w in review_content(text, [supplement]) if "百分点" in w]

    # 45.24 − 41.7 = 3.54，按书写精度舍入后 3.5 或 3.54 均有依据。
    assert pp_warnings("占比由41.7%提高到45.24%，提高3.5个百分点。") == []
    assert pp_warnings("占比提高3.54个百分点。") == []
    assert len(pp_warnings("占比提高4.1个百分点。")) == 1


@pytest.mark.parametrize(("text", "flagged"), [
    ("收入同比增长5.2%。", False),
    ("收入环比下降3.1%。", False),
    ("收入环比增长5.2%。", True),
    ("收入同比下降3.10%。", True),
    ("收入同比增长7.7%。", False),  # 无对应变化率：由数值依据告警负责，不判为口径混淆
])
def test_review_flags_yoy_mom_mixups(text, flagged):
    def comparison(kind, rate):
        return {"comparisonType": kind, "changeRate": rate, "currentTotal": 1, "baselineTotal": 1, "change": 0}

    content = json.dumps({"analysisId": "analysis_001",
                          "comparisons": [comparison("yoy", 5.2), comparison("mom", -3.1)]})
    warnings = [w for w in review_content(text, [content]) if "口径混淆" in w]
    assert bool(warnings) is flagged


@pytest.mark.parametrize(("text", "flagged"), [
    ("收入同比下降5.2%。", True),
    ("收入环比增长3.1%。", True),
    ("收入同比增长5.2%。", False),
    ("收入环比下降3.1%。", False),
    ("收入同比变化5.2%。", False),
    ("门诊量环比下降0.0%。", False),  # 零变化率没有方向
])
def test_review_flags_direction_opposite_to_registered_change_rate(text, flagged):
    def comparison(kind, rate):
        return {"comparisonType": kind, "changeRate": rate, "currentTotal": 1, "baselineTotal": 1, "change": 0}

    content = json.dumps({"analysisId": "analysis_001",
                          "comparisons": [comparison("yoy", 5.2), comparison("mom", -3.1),
                                          comparison("mom", 0.0)]})
    warnings = [w for w in review_content(text, [content]) if "方向与登记" in w]
    assert bool(warnings) is flagged


def test_review_reports_each_extrema_issue_once_preferring_the_labelled_form():
    content = json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(10, 30, 20))]})
    warnings = review_content("实际门诊人次在3月最高。", [content], field_definitions={"actual": "实际门诊人次"})
    extrema = [w for w in warnings if "3月被写为最高" in w]
    # 同一极值问题不应以“带指标名”和“不带指标名”两种形式重复进入纠错 issues。
    assert len(extrema) == 1 and extrema[0].startswith("实际门诊人次：")


@pytest.mark.parametrize(("text", "flagged"), [
    ("2024年门诊收入合计1,234.56万元。", True),
    ("2025年门诊收入合计1,234.56万元。", False),
    ("2024年同期门诊收入为1,173.54万元。", False),  # 基期合计没有登记期间，不判定
    ("2025年1—9月门诊收入合计1,234.56万元，较2024年同期增长5.20%。", False),  # 两个年份，不判定
    ("2024年9月门诊收入为145.56万元。", True),
    ("2025年9月门诊收入为145.56万元。", False),
])
def test_review_flags_values_labelled_with_a_year_outside_their_registered_period(text, flagged):
    metric = {**_metric(values=(1200000, 1300000, 1400000, 1350000, 1380000, 1420000, 1390000, 1450000, 1455600)),
              "unit": "元", "periodStart": "2025-01", "periodEnd": "2025-09"}
    comparison = {"factId": "fact-" + "b" * 16, "comparisonType": "yoy", "field": "actual",
                  "fieldRef": metric["fieldRef"], "currentDatasetId": "current", "baselineDatasetId": "yoy",
                  "currentDatasetSha256": "b" * 64, "baselineDatasetSha256": "c" * 64,
                  "currentTotal": metric["total"], "baselineTotal": 11735360,
                  "change": metric["total"] - 11735360, "changeRate": 5.2, "formula": "x", "unit": "元",
                  "periodStart": "2025-01", "periodEnd": "2025-09"}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [metric], "comparisons": [comparison]})
    warnings = [w for w in review_content(text, [content]) if "年份" in w]
    assert bool(warnings) is flagged


@pytest.mark.parametrize(("text", "flagged"), [
    ("门诊收入11,123,541,503元。", True),
    ("门诊收入1,234,567元。", True),
    ("门诊收入111.24亿元（11,123,541,503元）。", False),  # 括号内保留原始元值是规范写法
    ("人均费用356.20元。", False),
    ("门诊收入123.46万元。", False),
])
def test_readability_suggests_wan_or_yi_for_long_yuan_amounts(text, flagged):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    warnings = [w for w in readability_warnings(text) if "金额位数" in w]
    assert bool(warnings) is flagged


@pytest.mark.parametrize("text", [
    "门诊收入整体呈",
    "收入为1,234万元，同比增长5%，",
    "收入增长较快，成本增长与",
    "主要原因包括：",
    "上半年收入平稳。\n\n下半年收入分别为",
])
def test_readability_flags_paragraphs_that_end_mid_sentence(text):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    warnings = readability_warnings(text)
    assert len(warnings) == 1 and warnings[0].startswith("段落未写完")


@pytest.mark.parametrize("text", [
    "收入同比下降5%。原因待核实。",
    "收入为1,234万元",
    "主要原因包括：\n\n- 价格调整\n- 人次增加",
    "各科室收入如下：\n\n[[table:t1]]\n| 科室 | 收入 |\n|---|---|\n| 内科 | 2 |",
    "如图所示：\n\n![收入趋势](chart.png)",
    "### 收入分析：\n\n收入增长。",
    "- 门诊：\n- 住院：",
    "收入较上年增长。[[claim:c1]]",
    "全年收入达到**1,234万元**。",
    "```text\n收入整体呈\n```",
])
def test_readability_accepts_complete_paragraphs_and_lead_ins(text):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    assert readability_warnings(text) == []


@pytest.mark.parametrize(("text", "flagged"), [
    ("门诊量1,234,567人次。", True),
    ("门诊量123.46万人次（1,234,567人次）。", False),
    ("门诊量123,456人次。", False),
])
def test_readability_suggests_wan_visits_for_long_visit_counts(text, flagged):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    warnings = readability_warnings(text)
    assert bool(warnings) is flagged
    assert all("万人次" in item for item in warnings)


def test_review_flags_decline_wording_on_positive_registered_change_once():
    from .test_numeric_text import _comparison_document

    document = _comparison_document(6543211, 5.0332)
    amount = review_content('收入较上年减少{{value:fact-cccccccccccccccc:change:万元}}。', [document])
    assert [item for item in amount if item.startswith('方向与登记变化相反')] == [
        '方向与登记变化相反：减少654.32万元。该变化已登记为正值（增加），请改写为增长/增加，并同步修正前后文的方向判断。'
    ]
    # “同比下降{变化率}”已有变化率方向检查，不重复提示。
    rate = review_content('收入同比下降{{value:fact-cccccccccccccccc:changeRate:%}}。', [document])
    assert sum(item.startswith('方向与登记变化') for item in rate) == 1
    assert review_content('收入较上年增加{{value:fact-cccccccccccccccc:change:万元}}。', [document]) == []


def test_review_asks_for_units_on_bare_wan_and_yi_numbers():
    warnings = review_content('收入约9.99亿，门诊量88万。约2万多名患者。', [])
    assert [item.split('。')[0] for item in warnings if item.startswith('数值缺少单位')] == [
        '数值缺少单位：9.99亿', '数值缺少单位：88万',
    ]


@pytest.mark.parametrize(("text", "fields"), [
    ("收入yoy增长。", ["yoy"]),
    ("门诊量MoM回落，total为合计。", ["MoM", "total"]),
    ("periodTotals显示累计增长，changeRate较高。", ["periodTotals", "changeRate"]),
    # 数值占位、协议标记、链接地址、行内代码、业务缩写与英文单词不告警。
    ("收入{{value:fact-" + "a" * 16 + ":total:人次}}，CMI与DRG组数增加[[analysis:analysis_001]]，"
     "见[附表](https://x.com/total)，代码`total`，Totally fine。", []),
])
def test_contract_field_names_in_prose_are_flagged(text, fields):
    content = json.dumps({"analysisId": "analysis_001", "metrics": [_metric()]})
    warnings = [w for w in review_content(text, [content]) if "数据字段名" in w]
    assert [w.split("：", 1)[1].split("。", 1)[0] for w in warnings] == fields


@pytest.mark.parametrize(("text", "references"), [
    ("如图1所示，门诊收入增长。", ["图1"]),
    ("收入增长（见表2），图3显示回落，详见图4。", ["表2", "图3", "图4"]),
    # 模型自拟编号标题时引用一致；词内数字、标题主题词指代不告警。
    ("表1：科室收入\n\n| 科室 | 收入 |\n| --- | --- |\n\n见表1。", []),
    ("**图2 收入趋势**\n\n如图2所示。", []),
    ("代表1名医生，试图1次完成，门诊收入趋势图显示增长。", []),
])
def test_unnumbered_figure_references_are_flagged(text, references):
    warnings = [w for w in review_content(text, []) if "图表编号" in w]
    assert [w.split("：", 1)[1].split("。", 1)[0] for w in warnings] == references


def _grouped_metric_document():
    groups = [{"group": "心内科", "value": 300}, {"group": "外科", "value": 200}, {"group": "内科", "value": 100}]
    return json.dumps({"analysisId": "analysis_001", "metrics": [{
        **_metric(), "unit": "元", "topGroups": groups, "bottomGroups": list(reversed(groups)),
    }]})


@pytest.mark.parametrize(("text", "expected"), [
    ("外科收入最高。", ["分组排名需复核：外科被写为最高，冻结分组结果的最高为心内科。"]),
    ("内科收入居首。", ["分组排名需复核：内科被写为最高，冻结分组结果的最高为心内科。"]),
    ("外科收入最低。", ["分组排名需复核：外科被写为最低，冻结分组结果的最低为内科。"]),
    # 排名正确（“心内科”不误认为“内科”）、月度极值、占比排名与否定表述不告警。
    ("心内科收入最高，内科最低。", []),
    ("外科9月收入最高，外科收入占比最高，外科并非最高。", []),
])
def test_group_ranking_claims_are_checked_against_frozen_groups(text, expected):
    warnings = [w for w in review_content(text, [_grouped_metric_document()]) if "分组排名" in w]
    assert warnings == expected


def test_group_ranking_is_skipped_when_several_metrics_have_groups():
    document = json.loads(_grouped_metric_document())
    document["metrics"].append({**document["metrics"][0], "factId": "fact-" + "e" * 16, "field": "visits"})
    assert not [w for w in review_content("外科收入最高。", [json.dumps(document)]) if "分组排名" in w]


@pytest.mark.parametrize(("text", "expected"), [
    ("月均收入200.00万元。", []),
    ("月均收入150.00万元。",
     ["月均值需复核：月均收入150.00万元使用的是原始行平均值，不是月均值；冻结月均值为200.00万元。"]),
    ("平均每月收入600万元。",
     ["月均值需复核：平均每月收入600万元对应的是合计、单月或累计登记值，不是月均值；冻结月均值为200.00万元。"]),
    # 对不上任何登记值的数字交给无依据数值检查；未写“月均”的合计不受影响。
    ("月均收入999万元，收入合计600万元。", []),
])
def test_monthly_average_claims_use_the_monthly_statistic(text, expected):
    metric = {**_metric(values=(1200000, 1800000, 3000000)), "unit": "元", "average": 1500000}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [metric]})
    assert [w for w in review_content(text, [content]) if "月均值" in w] == expected


def _comparison_content(change=6543211):
    return json.dumps({
        "analysisId": "analysis_001",
        "metrics": [{**_metric(), "unit": "元", "total": 136543211}],
        "comparisons": [{
            "factId": "fact-" + "c" * 16, "comparisonType": "yoy", "field": "revenue",
            "fieldRef": "hospital.revenue", "currentDatasetId": "current", "baselineDatasetId": "base",
            "currentDatasetSha256": "b" * 64, "baselineDatasetSha256": "c" * 64,
            "currentTotal": 130000000 + change, "baselineTotal": 130000000, "change": change,
            "changeRate": change / 130000000 * 100, "formula": "x", "unit": "元",
        }],
    })


@pytest.mark.parametrize(("text", "expected"), [
    ("收入同比增加654.32万元，较上年增加0.07亿元。", []),
    ("收入环比增加654.32万元。",
     ["同比/环比口径混淆：环比增加654.32万元。该变化额对应已登记的同比比较，请核对比较口径。"]),
    ("收入较上月增加654.32万元。",
     ["同比/环比口径混淆：较上月增加654.32万元。该变化额对应已登记的同比比较，请核对比较口径。"]),
    ("收入同比减少654.32万元。", ["方向与登记变化额相反：同比减少654.32万元。请核对增减方向。"]),
])
def test_comparison_amount_claims_check_type_and_direction(text, expected):
    warnings = [w for w in review_content(text, [_comparison_content()])
                if "变化额" in w and ("口径混淆" in w or "方向" in w)]
    assert warnings == expected


@pytest.mark.parametrize("item", ["（1）门诊收入增长。", "一是门诊收入增长。", "第一，门诊收入增长。", "1、门诊收入增长。"])
def test_colon_intro_followed_by_cjk_enumeration_is_complete(item):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    assert not [w for w in readability_warnings(f"主要发现如下：\n\n{item}") if "段落未写完" in w]
    # 冒号后接普通句子仍是半句话。
    assert [w for w in readability_warnings("主要发现如下：\n\n收入增长。") if "段落未写完" in w]


@pytest.mark.parametrize(("text", "flagged"), [
    ("### 2025年门诊收入同比增长5.03%主要由于门诊量增加且人均费用上升\n\n正文。", True),
    ("### 收入增长。成本下降\n\n正文。", True),
    # 主题短语、末尾句号（装配时清理）、括号内单位说明、加粗与标记、代码块不告警。
    ("### 门诊收入趋势\n\n正文。", False),
    ("### 收入分析。\n\n正文。", False),
    ("### 成本结构（单位：万元，统计口径为全院不含科研项目）\n\n正文。", False),
    ("#### **重点科室收入变化**\n\n正文。", False),
    ("```\n### 这是代码里的一行很长很长很长很长很长很长很长很长的文字\n```", False),
])
def test_sentence_like_headings_are_flagged(text, flagged):
    from smart_reporting.reporting.trace.content_review import readability_warnings

    assert bool([w for w in readability_warnings(text) if "小标题" in w]) is flagged


def test_model_table_cells_without_basis_are_flagged():
    table = (
        "| 项目 | 金额（万元） | 同比（%） |\n| --- | ---: | ---: |\n"
        "| 本期收入 | 13,654.32 | 5.03 |\n| 编造项目 | 9,999.99 | 7.77 |"
    )
    warnings = [w for w in review_content(table, [_comparison_content()]) if "表格数值" in w]
    assert warnings == [
        "表格数值缺少可核对的冻结依据：9,999.99（万元列）。请使用对应数值引用，或删去未登记的计算结果。",
        "表格数值缺少可核对的冻结依据：7.77（%列）。请使用对应数值引用，或删去未登记的计算结果。",
    ]


def test_unregistered_multiples_are_flagged():
    warnings = [w for w in review_content("本期收入是上年同期的3.2倍，较上年为1.05倍。", [_comparison_content()])
                if "倍数" in w]
    assert warnings == [
        "倍数缺少可核对的冻结依据：3.2倍。须由已登记的本期与基期合计或比率得出，请改用变化率表述或删去该倍数。"
    ]
