"""按正文明确写出的指标及期间约束冻结数值选择，不按相同金额猜来源。"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta

from ..hospital_operation.deterministic_analysis import _parse_fact_period
from .fact_index import merge_frozen_fact
from .numeric_text import _frozen_number_entries, frozen_fact_bundles, frozen_number_catalog

_TOKEN = re.compile(r'\{\{value:([^:{}]+):([^:{}]+):([^:{}]*)\}\}')
_PERIOD = re.compile(r'(?P<year>\d{4})年(?:(?P<start>\d{1,2})月?(?:[—–至到~～-](?:(?P<end_year>\d{4})年)?(?P<end>\d{1,2}))?月)?')
_DAY_PERIOD = re.compile(
    r'(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})'
    r'(?:[日号]?[—–至到~～-](?:(?P<end_year>\d{4})年)?'
    r'(?:(?P<end_month>\d{1,2})月)?(?P<end_day>\d{1,2}))?[日号]'
)
_SHORT_PERIOD = re.compile(
    r'(?<!\d)\d{1,2}月?(?:[—–至到~～-](?:\d{4}年)?\d{1,2})?月'
)
_SHORT_DAY_PERIOD = re.compile(
    r'(?<![\d.])(?:(?P<month>\d{1,2})月)?\d{1,2}'
    r'(?:[日号]?[—–至到~～-](?:\d{4}年)?(?:\d{1,2}月)?\d{1,2})?[日号]'
)
_RELATIVE_PERIOD = re.compile(r'(次年|翌年|来年|上年|去年|同年|当年|次月|翌月|下月|上月|当月|本月)\s*$')
_YEAR_OFFSETS = {"次年": 1, "翌年": 1, "来年": 1, "上年": -1, "去年": -1, "同年": 0, "当年": 0}
_MONTH_OFFSETS = {"次月": 1, "翌月": 1, "下月": 1, "上月": -1, "当月": 0, "本月": 0}
_MONTHLY_WORDING = re.compile(r'月均|月平均|平均每月|各月|每月|逐月')


def _monthly_selector(fact, sentence, *, uniform):
    """仅从完整月桶选择已登记均值；每月相同还须逐桶验证相等。"""
    if (fact.aggregation != 'sum' or fact.period_aggregation == 'last'
            or fact.period_granularity != 'month' or fact.period_missing_count not in (None, 0)
            or fact.unit in {'%', '‰'} or re.search(r'[/／]', fact.unit or '')):
        return None
    buckets = []
    for index, item in enumerate(fact.period_values):
        period = _parse_fact_period(item.period, fact.period_granularity)
        if period is None or period.granularity != 'month':
            return None
        buckets.append((index, period.value.year * 12 + period.value.month - 1))
    if not buckets or len({month for _, month in buckets}) != len(buckets):
        return None
    written = _written_period(sentence, fact)
    if written is False or (written and written.re is not _PERIOD):
        return None
    if written:
        year = int(written['year'])
        first = year * 12 + int(written['start'] or 1) - 1
        last = int(written['end_year'] or year) * 12 + int(written['end'] or written['start'] or 12) - 1
        if (written['start'] and not 1 <= int(written['start']) <= 12
                or written['end'] and not 1 <= int(written['end']) <= 12
                or not 0 <= last - first < 1200):
            return None
        expected = list(range(first, last + 1))
    elif uniform:
        expected = list(range(buckets[0][1], buckets[-1][1] + 1))
    else:
        return None  # “月均”本身不授权改变原引用的统计期间。
    selected = [(index, month) for index, month in buckets if month in expected]
    if not selected or [month for _, month in selected] != expected:
        return None
    if uniform and len({fact.period_values[index].value for index, _ in selected}) != 1:
        return None
    if len(selected) == len(buckets):
        return 'monthlyAverage'
    return f'periodAverages.{selected[0][0]}-{selected[-1][0]}'


_VALUE_INTERVAL = re.compile(
    r'(?:介于|区间为|范围为)\s*' + _TOKEN.pattern
    + r'\s*(?:至|到|[—–~～-])\s*' + _TOKEN.pattern
)
_ISO_PERIOD = re.compile(r'(?<![\d/.-])\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?(?![\d/.-])')


def _has_period_context(sentence, fact, position, catalog):
    prose = _TOKEN.sub('', sentence[:position])
    written = _written_period(prose, fact)
    if written is None:
        # 允许引用后括注期间，但不能让后续分句的日期改变当前引用的期间。
        prose += re.split(r'[，,]', _TOKEN.sub('', sentence[position:]), maxsplit=1)[0]
        written = _written_period(prose, fact)
    if written:
        try:
            if written.re is _DAY_PERIOD:
                start = date(int(written['year']), int(written['month']), int(written['day']))
                end = date(int(written['end_year'] or written['year']),
                           int(written['end_month'] or written['month']),
                           int(written['end_day'] or written['day']))
            else:
                start = date(int(written['year']), int(written['start'] or 1), 1)
                end = date(int(written['end_year'] or written['year']),
                           int(written['end'] or written['start'] or 1), 1)
            if start <= end:
                return True
        except ValueError:
            pass
    if any(_parse_fact_period(item[0], None) is not None for item in _ISO_PERIOD.finditer(prose)):
        return True
    # “介于…至…”必须是同一事实的两个有效单期引用，且确实覆盖冻结序列的最小/最大值。
    for interval in _VALUE_INTERVAL.finditer(sentence):
        endpoints = list(_TOKEN.finditer(interval[0]))
        if not any(interval.start() + item.start() == position for item in endpoints):
            continue
        if any(item[1] != fact.fact_id or not re.fullmatch(r'periodValues\.\d+', item[2])
               or catalog.get(item[0], '数值待核实') == '数值待核实' for item in endpoints):
            continue
        indices = [int(item[2].split('.')[1]) for item in endpoints]
        if (indices[0] == indices[1] or endpoints[0][3] != endpoints[1][3]
                or any(index >= len(fact.period_values) for index in indices)):
            continue
        if any(_parse_fact_period(item.period, fact.period_granularity) is None
               for item in fact.period_values):
            continue
        values = [item.value for item in fact.period_values]
        if [values[index] for index in indices] == [min(values), max(values)]:
            return True
    return False


def _written_period(sentence, fact):
    """按出现顺序继承省略的年/月，后一个简写期间覆盖前一个完整期间。"""
    mentions = [(match, pattern) for pattern in (_DAY_PERIOD, _PERIOD, _SHORT_DAY_PERIOD, _SHORT_PERIOD)
                for match in pattern.finditer(sentence)]
    mentions.sort(key=lambda item: (item[0].start(), -item[0].end()))
    parsed = [_parse_fact_period(item.period, fact.period_granularity) for item in fact.period_values]
    years = {item.value.year for item in parsed if item is not None}
    months = {item.value.month for item in parsed if item is not None}
    year = month = None
    covered = -1
    written = None
    for mention, pattern in mentions:
        if mention.start() < covered:
            continue  # 完整日历表达式中的年月/日不是独立的新期间。
        covered = mention.end()
        if pattern in (_DAY_PERIOD, _PERIOD):
            written = mention
        else:
            inherited_year = year if year is not None else next(iter(years)) if len(years) == 1 else None
            inherited_month = month if month is not None else next(iter(months)) if len(months) == 1 else None
            relative = _RELATIVE_PERIOD.search(sentence[:mention.start()])
            relative_month = None
            if relative:
                modifier = relative[1]
                # 相对期间必须有正文给出的基准，不能把唯一快照年份当作“次年”的上年。
                if (written is False or year is None or not 1 <= year <= 9999
                        or (modifier in _MONTH_OFFSETS and (month is None or not 1 <= month <= 12))):
                    written = False
                    continue
                if modifier in _YEAR_OFFSETS:
                    inherited_year = year + _YEAR_OFFSETS[modifier]
                else:
                    absolute_month = year * 12 + month - 1 + _MONTH_OFFSETS[modifier]
                    inherited_year, zero_based_month = divmod(absolute_month, 12)
                    inherited_month = relative_month = zero_based_month + 1
            if inherited_year is None:
                written = False
                continue
            prefix = f'{inherited_year}年'
            if pattern is _SHORT_DAY_PERIOD and not mention['month']:
                if inherited_month is None:
                    written = False
                    continue
                prefix += f'{inherited_month}月'
            written = (_DAY_PERIOD if pattern is _SHORT_DAY_PERIOD else _PERIOD).fullmatch(prefix + mention[0])
            if written is None:
                written = False
                continue
            if relative_month is not None:
                explicit_month = int(written['month'] if written.re is _DAY_PERIOD else written['start'])
                if explicit_month != relative_month:
                    written = False
                    continue
        year = int(written['end_year'] or written['year'])
        if written.re is _DAY_PERIOD:
            month = int(written['end_month'] or written['month'])
        else:
            month = int(written['end'] or written['start']) if written['start'] else None
    return written


def _daily_selector(fact, written):
    try:
        start = date(int(written['year']), int(written['month']), int(written['day']))
        end = date(int(written['end_year'] or written['year']),
                   int(written['end_month'] or written['month']), int(written['end_day'] or written['day']))
    except ValueError:
        return None
    length = (end - start).days + 1
    if not 0 < length <= 1200:
        return None
    selected = [(i, period.value) for i, item in enumerate(fact.period_values)
                if (period := _parse_fact_period(item.period, fact.period_granularity)) is not None
                and period.granularity == 'day' and start <= period.value <= end]
    if [period for _, period in selected] != [start + timedelta(days=i) for i in range(length)]:
        return _labelled_window_selector(fact, start, end)
    if fact.period_aggregation == 'last':
        return f'periodValues.{selected[-1][0]}'
    if length == 1:
        return f'periodValues.{selected[0][0]}'
    if (len(selected) == len(fact.period_values) and fact.period_missing_count == 0
            and fact.aggregation in {'sum', 'count'}):
        return 'total'
    return None


def _labelled_window_selector(fact, start, end):
    """月度桶以月初标注：“2025年1月1日至12月1日”正好写出事实首末桶标签时即其完整统计窗口。"""
    labels = [_parse_fact_period(label, fact.period_granularity) if label else None
              for label in (fact.period_start, fact.period_end)]
    if (start >= end or len(fact.period_values) < 2 or None in labels
            or (labels[0].value, labels[1].value) != (start, end) or fact.period_aggregation == 'last'
            or fact.aggregation not in {'sum', 'count'} or fact.period_missing_count):
        return None
    return 'total'


def align_number_selections(markdown: str, contents, field_definitions: Mapping[str, str] | None = None):
    """只在主语和统计窗口明确、候选身份唯一时纠正；冲突且无法消歧时撤销引用。"""
    if not _TOKEN.search(markdown):
        return markdown, []
    contents = tuple(contents)
    facts = {}
    owners = {}
    conflicts = set()
    for bundle in frozen_fact_bundles(contents):
        for fact in bundle.metrics:
            if fact.fact_id:
                if fact.fact_id in facts:
                    existing = facts[fact.fact_id]
                    merged = merge_frozen_fact(existing.model_dump(mode='json', by_alias=True),
                                               fact.model_dump(mode='json', by_alias=True))
                    if merged is None:
                        conflicts.add(fact.fact_id)
                    elif merged['periodGranularity'] == existing.period_granularity:
                        fact = existing
                facts[fact.fact_id] = fact
                owners.setdefault(fact.fact_id, set()).add(bundle.analysis_id)
    labels = {}
    for fact_id, fact in facts.items():
        names = [fact.display_name or '', *fact.aliases,
                 (field_definitions or {}).get(fact.field, ''),
                 (field_definitions or {}).get(fact.field_ref, '')]
        for name in names:
            for label in re.split(r'[，,、；;]', name):
                if len(label.strip()) >= 2:
                    labels.setdefault(label.strip(), set()).add(fact_id)
    names = (re.compile('|'.join(re.escape(name) for name in sorted(labels, key=len, reverse=True)))
             if labels else None)
    catalog = frozen_number_catalog(contents)
    raw_values = {token: (value, unit) for token, value, unit, _target in _frozen_number_entries(contents)}
    warnings = []

    def replace(match):
        original = facts.get(match[1])
        if original is None:
            return match[0]
        if match[1] in conflicts:
            warnings.append('数值引用身份冲突：同一事实身份存在不同记录，需复核。')
            return '{{value:' + match[1] + ':unverified:' + match[3] + '}}'
        sentence = re.split(r'[。！？；;\n]', markdown[:match.start()])[-1]
        # 只读本句，防止下一句的日期替当前单期引用提供虚假的期间依据。
        suffix = re.split(r'[。！？；;\n]', markdown[match.end():], maxsplit=1)[0]
        if (match[2].startswith('periodValues.') and len(original.period_values) > 1
                and not _has_period_context(sentence + match[0] + suffix, original, len(sentence), catalog)):
            warnings.append('数值引用期间缺失：单期数值所在句未写出期间，已撤销引用，需复核。')
            return '{{value:' + match[1] + ':unverified:' + match[3] + '}}'
        clause = re.split(r'[，,]', sentence)[-1]
        named = list(names.finditer(clause)) if names else []
        monthly = list(_MONTHLY_WORDING.finditer(clause))
        if monthly:
            # 先确定统计方式，不能因“月均”位于指标名前就把正确均值改成合计。
            if (_TOKEN.search(clause)
                    or any(re.search(r'(?:不是|并非|而非|非|不属于|不代表)\s*$', clause[:word.start()])
                           for word in monthly)):
                return match[0]
            subject = named[-1] if named else None
            wording = clause[:subject.start()] + clause[subject.end():] if subject else clause
            if re.search(r'同比|环比|增|减|差|缺口|率|占比|比重|最高|最低|单笔|单行|排名|第|累计|合计|总额|总量|总计|汇总', wording):
                return match[0]
            tail = clause[subject.end():] if subject else ''
            if subject and not re.fullmatch(
                r'[\s（(]*(?:月均|月平均|平均每月|各月|每月|逐月|均|为|约|达到|是|的|：|:|=|登记值|登记|对应)*[\s）)]*', tail,
            ):
                return match[0]
            uniform = not any(word[0] in {'月均', '月平均', '平均每月'} for word in monthly)
            candidates = set()
            for fact_id in labels[subject[0]] if subject else (match[1],):
                if fact_id in conflicts:
                    continue
                fact = facts[fact_id]
                if fact.scope != original.scope or fact.unit != original.unit:
                    continue
                selector = _monthly_selector(fact, sentence, uniform=uniform)
                token = '{{value:' + fact_id + ':' + str(selector) + ':' + match[3] + '}}'
                if selector and token in catalog and catalog[token] != '数值待核实':
                    candidates.add(token)
            if match[0] in candidates or len(candidates) != 1:
                return match[0]
            warnings.append('数值引用口径不匹配：正文明确限定月度口径，已匹配唯一冻结月均依据。')
            return next(iter(candidates))
        if not named:
            return match[0]
        subject = named[-1]
        tail = clause[subject.end():]
        # 比率、变化、排名及算式需要各自的选择器，不能套用指标总额。
        if ('{{value:' in tail or re.search(r'同比|环比|增|减|差|缺口|率|占比|比重|最高|最低|均|每月|单笔|单行|排名|第', tail)):
            return match[0]
        if not re.fullmatch(r'[\s（(]*(?:合计|累计|全年|总额|总量|规模|为|约|达到|是|的|：|:|=|登记值|登记|对应)*[\s）)]*', tail):
            return match[0]
        candidates = {}
        for fact_id in labels[subject[0]]:
            if fact_id in conflicts:
                continue
            fact = facts[fact_id]
            if fact.scope != original.scope or fact.unit != original.unit:
                continue
            written = _written_period(sentence, fact)
            if written is False:
                continue
            selector = 'total'
            if written and written.re is _DAY_PERIOD:
                selector = _daily_selector(fact, written)
                if selector is None:
                    continue
            elif written:
                year, start, end = written['year'], written['start'], written['end']
                # 事实允许不补零及斜线年月；不能截取原始标签猜月桶，也不能把日桶当作月桶。
                buckets = [(i, f'{period.value.year:04d}-{period.value.month:02d}')
                           for i, item in enumerate(fact.period_values)
                           if (period := _parse_fact_period(item.period, fact.period_granularity)) is not None
                           and period.granularity == 'month']
                if start:
                    first, last = int(start), int(end or start)
                    end_year = int(written['end_year'] or year)
                    first_month, last_month = int(year) * 12 + first - 1, end_year * 12 + last - 1
                    if not (1 <= first <= 12 and 1 <= last <= 12 and 0 <= last_month - first_month < 1200):
                        continue
                    expected = [f'{month // 12:04d}-{month % 12 + 1:02d}'
                                for month in range(first_month, last_month + 1)]
                    selected = [(i, period) for i, period in buckets if period in expected]
                    if not expected or [p for _, p in selected] != expected:
                        continue
                    selector = (f'periodValues.{selected[-1][0]}' if fact.period_aggregation == 'last'
                                else f'periodTotals.{selected[0][0]}-{selected[-1][0]}'
                                if end else f'periodValues.{selected[0][0]}')
                    if (end and fact.period_aggregation != 'last' and fact.aggregation in {'sum', 'count'}
                            and len(selected) == len(fact.period_values) and fact.period_missing_count == 0):
                        selector = 'total'
                elif not fact.period_start or fact.period_start[:4] != year or not fact.period_end or fact.period_end[:4] != year:
                    continue
            elif fact_id == match[1] and not match[2].startswith(('budgetComparison.', 'projectRatio.')):
                # 没有明确期间时保留原引用的统计窗口。
                selector = match[2]
            token = '{{value:' + fact_id + ':' + selector + ':' + match[3] + '}}'
            if token in catalog and catalog[token] != '数值待核实':
                candidates[token] = fact_id
        if match[0] in candidates:
            return match[0]
        local = {token: fact_id for token, fact_id in candidates.items()
                 if owners[fact_id] & owners[match[1]]}
        if local:
            candidates = local
        # 回放：同一字段在多个分析中各自登记（成本金额 1—9 月合计在三个事实中完全相同），
        # 候选原值一致时并无歧义，取其一而不撤销引用。
        if len(candidates) > 1 and len({raw_values.get(token) for token in candidates}) == 1:
            candidates = {min(candidates): candidates[min(candidates)]}
        if len(candidates) == 1:
            replacement = next(iter(candidates))
        else:
            replacement = '{{value:' + match[1] + ':unverified:' + match[3] + '}}'
        warnings.append(f'数值引用口径不匹配：{subject[0]}的指标、期间或统计方式与所选引用不同。'
                        + ('已匹配唯一冻结依据。' if candidates and len(candidates) == 1 else '缺少唯一匹配依据，需复核。'))
        return replacement

    return _TOKEN.sub(replace, markdown), list(dict.fromkeys(warnings))
