"""按正文明确写出的指标及期间约束冻结数值选择，不按相同金额猜来源。"""
from __future__ import annotations

import re
from collections.abc import Mapping

from .numeric_text import frozen_fact_bundles, frozen_number_catalog

_TOKEN = re.compile(r'\{\{value:([^:{}]+):([^:{}]+):([^:{}]*)\}\}')
_PERIOD = re.compile(r'(?P<year>\d{4})年(?:(?P<start>\d{1,2})月?(?:[—–至到~-](?P<end>\d{1,2}))?月)?')


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
        periods = list(_PERIOD.finditer(sentence))
        written = periods[-1] if periods else None
        candidates = {}
        for fact_id in labels[subject[0]]:
            if fact_id in conflicts:
                continue
            fact = facts[fact_id]
            if fact.scope != original.scope or fact.unit != original.unit:
                continue
            selector = 'total'
            if written:
                year, start, end = written['year'], written['start'], written['end']
                buckets = [(i, item.period[:7]) for i, item in enumerate(fact.period_values)]
                if start:
                    first, last = int(start), int(end or start)
                    expected = [f'{year}-{month:02d}' for month in range(first, last + 1)]
                    selected = [(i, period) for i, period in buckets if period in expected]
                    if not expected or [p for _, p in selected] != expected:
                        continue
                    selector = (f'periodTotals.{selected[0][0]}-{selected[-1][0]}'
                                if end else f'periodValues.{selected[0][0]}')
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
