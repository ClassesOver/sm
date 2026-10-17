"""按正文明确写出的指标及期间约束冻结数值选择，不按相同金额猜来源。"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta

from ..hospital_operation.deterministic_analysis import _parse_fact_period
from .numeric_text import frozen_fact_bundles, frozen_number_catalog

_TOKEN = re.compile(r'\{\{value:([^:{}]+):([^:{}]+):([^:{}]*)\}\}')
_PERIOD = re.compile(r'(?P<year>\d{4})年(?:(?P<start>\d{1,2})月?(?:[—–至到~～-](?:(?P<end_year>\d{4})年)?(?P<end>\d{1,2}))?月)?')
_DAY_PERIOD = re.compile(
    r'(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})'
    r'(?:[日号]?[—–至到~～-](?:(?P<end_year>\d{4})年)?'
    r'(?:(?P<end_month>\d{1,2})月)?(?P<end_day>\d{1,2}))?[日号]'
)


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
        return None
    if fact.period_aggregation == 'last':
        return f'periodValues.{selected[-1][0]}'
    if length == 1:
        return f'periodValues.{selected[0][0]}'
    if (len(selected) == len(fact.period_values) and fact.period_missing_count == 0
            and fact.aggregation in {'sum', 'count'}):
        return 'total'
    return None


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
                if fact.fact_id in facts and facts[fact.fact_id] != fact:
                    conflicts.add(fact.fact_id)
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
    if not labels:
        return markdown, []
    names = re.compile('|'.join(re.escape(name) for name in sorted(labels, key=len, reverse=True)))
    catalog = frozen_number_catalog(contents)
    warnings = []

    def replace(match):
        original = facts.get(match[1])
        if original is None:
            return match[0]
        if match[1] in conflicts:
            warnings.append('数值引用身份冲突：同一事实身份存在不同记录，需复核。')
            return '{{value:' + match[1] + ':unverified:' + match[3] + '}}'
        sentence = re.split(r'[。！？；;\n]', markdown[:match.start()])[-1]
        clause = re.split(r'[，,]', sentence)[-1]
        named = list(names.finditer(clause))
        if not named:
            return match[0]
        subject = named[-1]
        tail = clause[subject.end():]
        # 比率、变化、排名及算式需要各自的选择器，不能套用指标总额。
        if ('{{value:' in tail or re.search(r'同比|环比|增|减|差|缺口|率|占比|比重|最高|最低|均|每月|单笔|单行|排名|第', tail)):
            return match[0]
        if not re.fullmatch(r'[\s（(]*(?:合计|累计|全年|总额|总量|规模|为|约|达到|是|的|：|:|=|登记值|登记|对应)*[\s）)]*', tail):
            return match[0]
        periods = [*_PERIOD.finditer(sentence), *_DAY_PERIOD.finditer(sentence)]
        written = max(periods, key=lambda period: period.end()) if periods else None
        candidates = {}
        for fact_id in labels[subject[0]]:
            if fact_id in conflicts:
                continue
            fact = facts[fact_id]
            if fact.scope != original.scope or fact.unit != original.unit:
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
        if len(candidates) == 1:
            replacement = next(iter(candidates))
        else:
            replacement = '{{value:' + match[1] + ':unverified:' + match[3] + '}}'
        warnings.append(f'数值引用口径不匹配：{subject[0]}的指标、期间或统计方式与所选引用不同。'
                        + ('已匹配唯一冻结依据。' if candidates and len(candidates) == 1 else '缺少唯一匹配依据，需复核。'))
        return replacement

    return _TOKEN.sub(replace, markdown), list(dict.fromkeys(warnings))
