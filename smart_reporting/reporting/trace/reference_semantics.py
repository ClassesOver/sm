"""依据具体数值选择器复核业务表述，只给软告警，不猜测替代事实。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact, _parse_fact_period
from .number_selection import (
    _DAY_PERIOD,
    _PERIOD,
    _SHORT_DAY_PERIOD,
    _SHORT_PERIOD,
    _written_period,
)
from .review_common import _CLAUSE_BREAK

_WORDING = re.compile(r'月均|月平均|平均每月|平均值|均值|单月|累计|合计|总额|总量|总计|汇总')
_NEGATED_WORDING = re.compile(r'(?:并非|不是|而非|不同于|非|不属于|不代表|不作为|不能称为|不能视为)\s*(?:按|以)?\s*$')
_SCOPE_EXCLUSION_BEFORE = re.compile(
    r'(?:并非|不是|而非|非|不含|不包括|不包含|不属于|不来自|未纳入|未计入|剔除|排除|除去)\s*(?:了\s*)?$'
)
_SCOPE_EXCLUSION_AFTER = re.compile(r'^\s*(?:以外|之外|除外)')
_SCOPE_EXCLUSION_CANCELLED = re.compile(r'(?:并非|不是|并不是|没有|未曾|未|不|不能|无法|不应|不宜|不得)\s*$')
_DEPARTMENT = re.compile(r'[\u3400-\u9fff]{1,12}科(?:室)?')
_DEPARTMENT_PREFIX = re.compile(r'^(?:(?:其中|本期|本月|本年|本院|该院|全院|预计|目前|科室|一级科室|二级科室)(?:的)?)+')
_DEPARTMENT_CONTEXT = re.compile(r'显示|表明|反映|可见|可知|发现|统计|观察|关注|比较|相比|相较|登记')
_INCLUDED_MONTH = re.compile(
    r'(?:包含|包括|含|例如|覆盖)\s*(?:\d{4}年)?\d{1,2}月?'
    r'(?:[—–至到~～-](?:\d{4}年)?\d{1,2})?月'
)


def _postfix_qualifier(suffix: str) -> str:
    """只读取当前值紧邻的括注或归属表述，不读后续引用或新分句。"""
    suffix = suffix.replace('**', '').strip()
    # 当前值的来源入口不是新断言；生成期和编辑期须以同样方式读取其后括注。
    suffix = re.sub(r'^(?:\s*\[\[citation:[^\]\r\n]+\]\])*\s*', '', suffix)
    suffix = re.split(r'\{\{value:|\[\[(?:claim|citation):', suffix, maxsplit=1)[0]
    notes: list[str] = []
    offset = 0
    while offset < len(suffix) and suffix[offset] in '（(':
        closing = []
        for index in range(offset, len(suffix)):
            char = suffix[index]
            if char in '（(':
                closing.append('）' if char == '（' else ')')
            elif char in '）)':
                if not closing or closing.pop() != char:
                    return ' '.join(notes)
                if not closing:
                    # 括注内部的逗号不建立下一条正文断言。
                    notes.append(re.sub(r'[，,;；]', ' ', suffix[offset:index + 1]))
                    offset = index + 1
                    while offset < len(suffix) and suffix[offset].isspace():
                        offset += 1
                    break
        else:
            break  # 不完整括注（包括包含下一引用的括注）不能替当前值说明口径。
    if notes:
        return ' '.join(notes)
    suffix = re.split(r'[。！？;；，,\n]', suffix, maxsplit=1)[0]
    attribution = re.match(r'(?:为|是|属于|系|对应|即|表示|作为)\s*(.+)', suffix)
    return attribution[1] if attribution else ''


def _department_name(raw: str, registered: set[str], identity: str) -> str:
    """先保留登记的完整科名，只有科名前的叙述语法可以被裁掉。"""
    name = _DEPARTMENT_PREFIX.sub('', raw)
    candidates = registered | {match[0] for match in _DEPARTMENT.finditer(identity)}
    for candidate in sorted(candidates, key=len, reverse=True):
        if name == candidate:
            return candidate
        if name.endswith(candidate):
            before = name[:-len(candidate)]
            context = list(_DEPARTMENT_CONTEXT.finditer(before))
            if context and not _DEPARTMENT_PREFIX.sub('', before[context[-1].end():]):
                return candidate
    return _DEPARTMENT_PREFIX.sub('', _DEPARTMENT_CONTEXT.split(name)[-1])


def _affirmative_wording(clause: str) -> list[str]:
    return [match[0] for match in _WORDING.finditer(clause)
            if not _NEGATED_WORDING.search(clause[:match.start()])]


def scope_exclusion_warnings(clause: str, scope: Mapping[str, Any]) -> list[str]:
    """Recognize finite explicit exclusions, without inferring substitute scopes.

    Callers supply only this reference's clause and attached qualifiers. A scope
    name occurring inside a denial cannot establish affirmative attribution.
    This does not claim to understand arbitrary negation or approve missing scope.
    """
    clause = clause.replace('**', '')
    warnings = []
    for key, value in scope.items():
        if not isinstance(value, str) or not value.strip():
            continue
        for match in re.finditer(re.escape(value), clause):
            before = clause[:match.start()]
            preceding = _SCOPE_EXCLUSION_BEFORE.search(before)
            following = _SCOPE_EXCLUSION_AFTER.search(clause[match.end():])
            # “未排除北院” and “不含北院以外” do not explicitly exclude
            # 北院. This finite guard is not proof of affirmative inclusion.
            if preceding and (following or _SCOPE_EXCLUSION_CANCELLED.search(before[:preceding.start()])):
                continue
            if preceding or following:
                warnings.append(f'业务范围需复核：当前引用否定或排除了登记范围 {key}={value}。')
                break
    return warnings


def _monthly_window_warnings(prefix: str, clause: str, reference: Mapping[str, Any]) -> list[str]:
    """多月合计/均值必须对应完整窗口；累计截止月与背景月份另行处理。"""
    selector = reference['selector']
    periods: tuple[str, ...] = tuple(reference.get('periods') or ())
    if (selector not in {'total', 'monthlyAverage', 'monthlyTrend'} and not selector.startswith(('periodTotals.', 'periodAverages.'))
            or len(periods) < 2 or any(not re.fullmatch(r'\d{4}-\d{2}', period) for period in periods)):
        return []
    # 沿用数值选择阶段的日期继承和范围解析，避免两套规则解释同一句话。
    fact = DeterministicMetricFact.model_validate(reference['entry'])
    # “含一月调整额”说明组成，不能替代正文已经限定的二月统计窗口。
    period_prefix = _INCLUDED_MONTH.sub(' ', prefix)
    period_clause = _INCLUDED_MONTH.sub(' ', clause)
    written = _written_period(period_prefix, fact)
    if not written or written.re is not _PERIOD or not written['start']:
        return []
    first = int(written['year']) * 12 + int(written['start']) - 1
    last = int(written['end_year'] or written['year']) * 12 + int(written['end'] or written['start']) - 1
    if not (1 <= int(written['start']) <= 12 and 1 <= int(written['end'] or written['start']) <= 12
            and 0 <= last - first < 1200):
        return []
    written_periods: tuple[str, ...] = tuple(f'{month // 12:04d}-{month % 12 + 1:02d}' for month in range(first, last + 1))
    cutoff_pattern = r'(?:截至|截止)(?:到)?\s*(?:\d{4}年)?\d{1,2}月'
    cutoff = re.search(cutoff_pattern, period_clause)
    if not cutoff and _written_period(period_clause, fact) is None:
        cutoff = re.search(cutoff_pattern, period_prefix)
    if first == last and written_periods[-1] == periods[-1] and (cutoff or '累计' in _affirmative_wording(clause)):
        return []
    # “区间为2月…至7月…，9个月月均…”：月份是极值说明，紧邻数值写明的月数与完整窗口一致。
    months = re.search(r'(\d{1,3})个(?:自然)?月(?:的)?(?:月均|平均|均值|合计|累计|总计)', clause)
    if months and int(months[1]) == len(periods):
        return []
    if written_periods != tuple(periods):
        return [f"统计期间需复核：当前引用覆盖 {'、'.join(periods)}，与正文限定的统计窗口不一致。"]
    return []


def _uniform_month_warnings(clause: str, reference: Mapping[str, Any]) -> list[str]:
    from .monthly_trends import has_monthly_trend_wording

    if has_monthly_trend_wording(clause):
        return []  # A changing series is not a claim that every month has this amount.
    # “1—2月平均每月”中的日历“月”不能吞掉“平均每月”的前半部分。
    wording = re.sub(r'(?<![各每])月均|月平均', '', clause.replace('平均每月', ''))
    if re.search(r'(?:各月|每月|逐月)[^，。；,;]{0,12}?(?:平均|均值)', wording):
        return []  # “各月成本平均为11.01亿元”说的是平均水平，不是各月相同。
    assertions = [match for match in re.finditer(r'各月|每月|逐月', wording)
                  if not _NEGATED_WORDING.search(wording[:match.start()])]
    if (not assertions or re.search(r'(?:并非|不是|并不|未必)\s*(?:均|都|相同|一样)', wording)
            or any(word in {'累计', '合计', '总额', '总量', '总计', '汇总'} for word in _affirmative_wording(clause))
            or reference['entry'].get('periodGranularity') != 'month'):
        return []
    periods = set(reference.get('periods') or ())
    values = set()
    for item in reference['entry'].get('periodValues') or ():
        parsed = _parse_fact_period(item['period'], 'month')
        if parsed and f'{parsed.value.year:04d}-{parsed.value.month:02d}' in periods:
            values.add(item['value'])
    if len(values) > 1:
        return ['逐月数值需复核：登记月份的数值并不相同，不能表述为各月均为同一数值。']
    return []


def number_reference_warnings(prefix: str, reference: Mapping[str, Any], suffix: str = '') -> list[str]:
    """复核当前引用前的断言及紧邻后置限定，不跨入下一分句或引用。"""
    boundaries = list(re.finditer(r'\{\{value:[^{}\r\n]+\}\}|\[\[claim:[^\]\r\n]+\]\]', prefix))
    rank_prefix = prefix[boundaries[-1].end():] if boundaries else prefix
    next_metric_clause = prefix[boundaries[-1].end():] if boundaries else ''
    prefix = re.sub(r"\[\[[^\]\n]+\]\]", "", prefix).replace('**', '')
    prefix_clause = _CLAUSE_BREAK.split(prefix)[-1]
    scope_clause = prefix_clause
    next_metric_clause = _CLAUSE_BREAK.split(re.sub(r'\[\[[^\]\n]+\]\]', '', next_metric_clause))[-1]
    if re.search(r'收入|支出|预算|门诊|出院|工作量', next_metric_clause):
        prefix_clause = next_metric_clause
        # 省略主语的“及收入”仍继承原科室；只有明确新主语才能重置范围。
        if re.search(r'全院|总体|全部|本院|该院|' + _DEPARTMENT.pattern, next_metric_clause):
            scope_clause = next_metric_clause
    qualifier = _postfix_qualifier(suffix)
    if qualifier:
        prefix += ' ' + qualifier
    clause = prefix_clause + ' ' + qualifier
    entry = reference['entry']
    selector = reference['selector']
    warnings = scope_exclusion_warnings(rank_prefix + ' ' + qualifier, reference.get('scope') or {})
    warnings.extend(_monthly_window_warnings(prefix, clause, reference))
    from .top_sets import top_set_wording_warnings

    warnings.extend(top_set_wording_warnings(rank_prefix + " " + qualifier, reference))
    cumulative_warnings, rank_prefix = _cumulative_wording_warnings(rank_prefix + " " + qualifier, reference)
    warnings.extend(cumulative_warnings)
    from .ratio_proofs import ratio_wording_warnings

    ratio_warnings, rank_prefix = ratio_wording_warnings(rank_prefix + " " + qualifier, reference)
    warnings.extend(ratio_warnings)
    from .group_contributions import contribution_wording_warnings

    contribution_warnings, rank_prefix = contribution_wording_warnings(rank_prefix + " " + qualifier, reference)
    warnings.extend(contribution_warnings)
    from .business_semantics import mask_registered_display_data

    rank_prefix = mask_registered_display_data(rank_prefix, reference)
    warnings.extend(_uniform_month_warnings(clause, reference))
    from .group_ranking import group_rank_wording_warnings

    rank_prefix = re.sub(r"\[\[[^\]\n]+\]\]", "", rank_prefix).replace('**', '')
    warnings.extend(group_rank_wording_warnings(rank_prefix + ' ' + qualifier, reference))
    from .monthly_trends import monthly_trend_wording_warnings

    warnings.extend(monthly_trend_wording_warnings(rank_prefix + ' ' + qualifier, reference))
    from .business_semantics import unsupported_business_warnings

    warnings.extend(unsupported_business_warnings(rank_prefix + ' ' + qualifier))
    from .comparison_proofs import comparison_wording_warnings

    warnings.extend(comparison_wording_warnings(rank_prefix + ' ' + qualifier, reference))
    # 只有当前引用前最近的统计口径词生效：“累计…（月均…）”不是均值冒充累计。
    wording = _affirmative_wording(prefix_clause)
    # 前后都明确归属同一个值时，后置口径不能抹去前置的矛盾断言。
    written = ([wording[-1]] if wording else []) + _affirmative_wording(qualifier)
    meaning = None
    if selector == 'monthlyAverage' or selector.startswith('periodAverages.'):
        meaning = '月均值'
    elif selector in {'average', 'minimum', 'maximum', 'monthlyMinimum', 'monthlyMaximum'}:
        meaning = {'average': '原始行平均值', 'minimum': '最小值', 'maximum': '最大值',
                   'monthlyMinimum': '月度最小值', 'monthlyMaximum': '月度最大值'}[selector]
    elif selector == 'total' and entry.get('aggregation') in {'average', 'min', 'max'}:
        meaning = {'average': '平均值', 'min': '最小值', 'max': '最大值'}[entry['aggregation']]
    cumulative = next((word for word in written if word in {'累计', '合计', '总额', '总量', '总计', '汇总'}), None)
    if meaning and cumulative:
        warnings.append(f'统计口径需复核：当前引用为{meaning}，不能称为{cumulative}。')
    elif (any(word in {'月均', '月平均', '平均每月'} for word in written)
          and (selector in {'total', 'average'} or selector.startswith('periodTotals.'))):
        warnings.append('统计口径需复核：当前引用不是月均选择器，请核对月均口径。')

    scope = reference.get('scope') or {}
    # Nullable hierarchy/group keys denote missing mapping, not a text identity.
    # Keep registered strings usable without inventing a department for nulls.
    identity = ' '.join((str(entry.get('displayName') or ''), *(entry.get('aliases') or ()),
                         *(value for value in scope.values() if isinstance(value, str))))
    # 空范围不等于“全院”。正文明确限定科室而引用没有相应登记时，只提示范围未获证实。
    department_clause = scope_clause + ' ' + qualifier
    for calendar in (_DAY_PERIOD, _PERIOD, _SHORT_DAY_PERIOD, _SHORT_PERIOD):
        department_clause = calendar.sub(' ', department_clause)
    departments = list(re.finditer(r'(?P<department>' + _DEPARTMENT.pattern + r')(?:的)?\s*(?=收入|支出|预算|门诊|出院|工作量|[）)])', department_clause))
    department = departments[-1] if departments else None
    if department:
        # “普通外科收入占全院收入”紧邻引用的是分母；“位居全院第一”仍属于科室。
        denominator = re.search(r'占\s*(?:全院|总体|全部)(?:的)?\s*(?:收入|支出|预算|门诊|出院|工作量)',
                                department_clause[department.end():])
        if denominator:
            return warnings
        registered = {word for value in scope.values() for word in re.split(r'[/／|，,、\s]+', str(value))
                      if _DEPARTMENT.fullmatch(word)}
        name = _department_name(department['department'], registered, identity)
        if registered and name not in registered:
            warnings.append(f"业务范围需复核：当前科室表述与登记科室 {'、'.join(sorted(registered))} 不一致。")
        elif not registered and name not in identity:
            warnings.append('业务范围需复核：正文限定了科室，当前数值引用未登记对应科室范围。')
    return warnings


def _cumulative_wording_warnings(text: str, reference: Mapping[str, Any]) -> tuple[list[str], str]:
    """Snapshot arithmetic never establishes operating flow or a different reset."""
    from .assertions import _label
    from .business_semantics import _NEGATION
    from .cumulative_changes import cumulative_change_template

    if not reference['selector'].startswith('cumulativeChanges.'):
        entry = reference['entry']
        if entry.get('cumulativePolicy') is None:
            return [], text
        wording = text
        for key, value in reference.get('scope', {}).items():
            wording = wording.replace(f'{_label(key)}={_label(str(value))}', ' ')
        label = _label(str(entry.get('displayName') or entry.get('field') or '指标'))
        for suffix in ('登记值为', '记录值为'):
            wording = wording.replace(label + suffix, ' ')
        for match in re.finditer(
            r'业务流量|(?:当|本)(?:期|月)(?:业务)?(?:新增|增量|流量|发生额)'
            r'|(?:当|本)(?:期|月)(?:实现|发生|取得)?(?:收入|支出|营收|成本|费用|利润|人次|出院人数)',
            wording,
        ):
            prefix = wording[:match.start()]
            if re.match(r'(?:的)?[（(]?(?:累计|快照|期末)', wording[match.end():]):
                continue
            if not (_NEGATION.search(prefix)
                    or re.search(r'(?:不等同|不等于|不能视为)(?:(?:当|本)(?:期|月))?$', prefix)):
                return ['累计口径需复核：累计快照原值不能证明当期业务流量或新增发生额。'], text
        return [], text
    proof = reference.get('_cumulative_change_proof')
    if proof is None:
        return ['累计口径需复核：累计快照、重置策略或基线尚未核验。'], text
    scope = '、'.join(f'{_label(key)}={_label(value)}'
                     for key, value in sorted(reference['entry']['scope'].items()))
    entry = reference['entry']
    subject = str(entry.get('displayName') or entry.get('field') or '指标')
    before, after = cumulative_change_template(proof, f'{scope}，{_label(subject)}', '__VALUE__').split('__VALUE__')

    def normalized(value: str) -> str:
        # Editor normalization and postfix extraction can replace punctuation.
        return re.sub(r'[\s，,、（）()。；;*]', '', value)

    remaining = normalized(text)
    expected, caveat = normalized(before), normalized(after)
    if expected not in remaining or caveat not in remaining:
        return ['累计口径需复核：期间、零基线、快照差额或追溯调整限制与冻结证据不一致。'], text
    remaining = remaining.replace(expected, ' ', 1).replace(caveat, ' ', 1)
    for match in re.finditer(r'当期|当月|本月|业务流量|业务增量|新增|同比|环比|增长率|累计|重置|基线', remaining):
        if not _NEGATION.search(remaining[:match.start()]):
            return ['累计口径需复核：快照差额不能替代当期业务流量或其他累计比较政策。'], remaining
    return [], remaining
