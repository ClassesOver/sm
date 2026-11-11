"""计算限制的中文展示；不改变问题代码、事实身份或核验结论。"""

import re

_ISSUE_MESSAGES = {
    'data_readiness_unknown': '数据完整性与更新状态尚未核实，暂不据此判断经营变化',
    'missing_data': '未取得对应范围的数据，暂不可计算；不按零值处理',
    'null_observations': '部分记录的指标值为空，暂不可计算；不按零值处理',
    'zero_denominator': '分母为零，比例暂不可计算；不按零比例处理',
    'join_fanout': '关联键不唯一，可能重复计入金额，暂不可计算',
    'unmatched_dimension_keys': '部分记录未匹配到维度，需核对其范围后再比较',
    'unmatched_groups': '参与计算的指标分组不一致，暂不可计算；不将缺失分组补零',
    'grain_not_supported': '尚未登记所需统计粒度或分摊规则，暂不可计算',
    'period_observations_unknown': '缺少期间覆盖记录，尚无法确认所需期间是否完整',
    'missing_period_observations': '所需期间存在无观测记录的区间，需核对是否未同步或无交易',
    'missing_group_observations': '所需对象存在无观测记录的分组，需核对是否遗漏',
    'source_watermark_unknown': '缺少源数据更新时间，尚无法确认数据是否及时',
    'source_watermark_stale': '源数据更新时间超过口径允许延迟，需补齐更新后再比较',
    'source_watermark_in_future': '源数据更新时间晚于取数时间，需核对时钟或更新时间记录',
    'metric_query_failed': '指标取数未成功，暂不可计算；需核查数据源及查询回执',
    'fact_citation_unavailable': '计算结果的来源未完整核实，暂不能作为已核实结论',
    'metric_no_match': '尚未找到对应的已登记指标，此问题仍未解决',
    'metric_ambiguous': '存在不同计算定义的候选指标，需确认选用依据',
    'metric_selection_unresolved': '尚未确认对应指标，此问题仍未解决',
    'question_analysis_pending': '已有计算结果，问题的分析与解释仍待完成',
    'xlsx_numeric_precision_preserved': '超出Excel数值精度或范围，保留精确文本，不作数值汇总',
    'question_completion_mapping_unavailable': '完成条件尚未确认',
    'question_completion_evidence_unverified': '完成条件的证据尚未核实',
    'question_completion_conditions_unavailable': '问题缺少完成条件',
    'registered_question_sources_unavailable': '原始问题或计算来源不可用',
    'registered_question_identity_mismatch': '问题与冻结请求不一致',
    'registered_question_results_unavailable': '缺少对应指标计算结果',
    'registered_question_period_unavailable': '本期或比较期结果不完整',
    'question_support_unverified': '正文事实尚未通过核验',
    'metric_selection_unavailable': '尚未确认对应指标',
}


def semantic_issue_message(value: str) -> str:
    """识别代码用于展示；自由文本原样保留，未知代码明确待核查而非推断通过。"""
    if value in _ISSUE_MESSAGES:
        return _ISSUE_MESSAGES[value]
    if re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+', value):
        return '存在尚未识别的计算限制，请在本报告计算依据中进一步核查'
    return value
