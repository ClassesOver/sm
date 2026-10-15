"""把冻结数值选择器及提示类型保留到编辑器；不根据业务名称猜事实。"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Any

from .contracts_v1 import NumberReferenceV1, ReviewNoticeV1
from .numeric_text import (
    _frozen_number_entries,
    align_placeholder_direction,
    correct_period_extrema,
    frozen_fact_bundles,
    frozen_number_catalog,
    normalize_signed_wording,
    render_frozen_numbers,
    replace_unregistered_numbers,
)


def reference_fact_ids(token: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"fact-[0-9a-f]{16}", token)))


def statement_fingerprint(markdown: str, claim_id: str) -> str | None:
    return statement_fingerprints(markdown, (claim_id,))[claim_id]


def statement_fingerprints(markdown: str, claim_ids) -> dict[str, str | None]:
    """同一草稿只做一次显示规范化，不跨请求缓存可编辑正文。"""
    from ..delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording

    markdown = normalize_cjk_punctuation(normalize_cjk_wording(markdown))
    return {claim_id: _statement_fingerprint(markdown, claim_id) for claim_id in claim_ids}


def _statement_fingerprint(markdown: str, claim_id: str) -> str | None:
    marker = f"[[claim:{claim_id}]]"
    if markdown.count(marker) != 1:
        return None
    before, after = markdown.split(marker)
    statement = re.split(r"[。！？；;\n]", before)[-1] + re.split(r"[。！？；;\n]", after)[0]
    statement = re.sub(r"\[\[[^\]\n]+\]\]", "", statement)
    return hashlib.sha256(re.sub(r"[\s*]", "", statement).encode()).hexdigest()


def render_bound_numbers(markdown: str, contents, *, key: str):
    contents = tuple(contents)
    catalog = frozen_number_catalog(contents)
    references: list[tuple[str, str]] = []
    notices: list[ReviewNoticeV1] = []
    counter = 0

    def identity(kind: str) -> str:
        nonlocal counter
        counter += 1
        return kind + '-' + hashlib.sha256(f'{key}:{counter}'.encode()).hexdigest()[:20]

    def notice(kind: str, text: str = '待核实') -> str:
        claim_id = identity('review')
        notices.append(ReviewNoticeV1(claimId=claim_id, kind=kind))
        return text + f'[[claim:{claim_id}]]'

    def annotate(token: str, text: str) -> str:
        if token not in catalog or text == '数值待核实':
            return notice('numeric_unverified', text)
        claim_id = identity('number')
        references.append((claim_id, token))
        return text + f'[[claim:{claim_id}]]'

    # 模型不能自行签发数字锚点。原正文的复核表述独立记为来源复核，不能拿来恢复数字。
    markdown = re.sub(r'\[\[claim:[^\]\n]+\]\]', '', markdown)
    markdown = re.sub('待核实', lambda _: notice('source_review'), markdown)
    markdown = render_frozen_numbers(align_placeholder_direction(markdown, contents), catalog, annotate=annotate)
    markdown = replace_unregistered_numbers(
        normalize_signed_wording(correct_period_extrema(markdown, contents)), contents,
        missing=lambda: notice('numeric_unverified'),
    )
    references = tuple(NumberReferenceV1(
        claimId=claim_id, token=token, statementSha256=statement_fingerprint(markdown, claim_id),
    ) for claim_id, token in references)
    return strip_bound_anchors(markdown, references, notices)


def strip_bound_anchors(markdown: str, references, notices):
    """把服务端临时锚点收为装配偏移，正文仍遵守禁止协议注入的原有契约。"""
    offsets = {}
    removed = 0
    for match in re.finditer(r"\[\[claim:([^\]\n]+)\]\]", markdown):
        offsets[match[1]] = match.start() - removed
        removed += len(match[0])
    plain = re.sub(r"\[\[claim:[^\]\n]+\]\]", "", markdown)
    return (plain,
            tuple(item.model_copy(update={"offset": offsets[item.claim_id]}) for item in references if item.claim_id in offsets),
            tuple(item.model_copy(update={"offset": offsets[item.claim_id]}) for item in notices if item.claim_id in offsets))


def anchor_bound_numbers(markdown: str, references, notices=()) -> str:
    """只在首次装配中按服务端记录的偏移插入锚点，此后编辑仅使用锚点定位。"""
    for item in sorted((*references, *(notices or ())), key=lambda item: item.offset, reverse=True):
        if item.offset <= len(markdown):
            markdown = markdown[:item.offset] + f"[[claim:{item.claim_id}]]" + markdown[item.offset:]
    return markdown


class NumberReferenceResolver:
    """仅在一次校验请求内复用同组已核验文件的数值目录。"""

    def __init__(self, contents):
        contents = tuple(contents)
        self.numbers = {}
        for token, value, unit, target in _frozen_number_entries(contents):
            self.numbers.setdefault(token, []).append((value, unit, target))
        self.entries = {}
        self.conflicts = set()
        for bundle in frozen_fact_bundles(contents):
            document = bundle.model_dump(mode="json", by_alias=True)
            for array in ('metrics', 'comparisons', 'derivedMetrics', 'reconciliations', 'correlationDetails'):
                for fact in document.get(array, ()):
                    key = fact.get('factId')
                    if key in self.entries and self.entries[key] != fact:
                        self.conflicts.add(key)
                    self.entries[key] = fact

    def resolve(self, token: str) -> dict[str, Any] | None:
        matches = self.numbers.get(token, ())
        if not matches or len({(str(value), unit, target) for value, unit, target in matches}) != 1:
            return None
        ids = reference_fact_ids(token)
        if not ids or any(key not in self.entries or key in self.conflicts for key in ids):
            return None
        return _resolved_number_reference(token, ids, self.entries, matches[0])


def resolve_number_reference(token: str, contents) -> dict[str, Any] | None:
    """仅从调用者已经核验文件身份的内容重算完整 token；缺失或冲突不回退 total。"""
    return NumberReferenceResolver(contents).resolve(token)


def _resolved_number_reference(token, ids, entries, selected_value):
    primary = entries[ids[0]]
    value, unit, target = selected_value
    selector = token[2:-2].split(':')[2]
    from .subject_builder import fact_periods
    periods = fact_periods(primary)
    selected_periods = None
    if selector.startswith('periodValues.'):
        selected_periods = [primary['periodValues'][int(selector.split('.')[1])]]
    elif selector.startswith(('periodTotals.', 'periodAverages.')):
        start, end = (int(index) for index in selector.split('.')[1].split('-'))
        selected_periods = primary['periodValues'][start:end + 1]
    elif selector.startswith(('periodChanges.', 'periodChangeRates.')):
        index = int(selector.split('.')[1])
        selected_periods = primary['periodValues'][index - 1:index + 1]
    elif selector.startswith('budgetComparison.'):
        period = selector[len('budgetComparison.' + ids[1] + '.'):].rsplit('.', 1)[0]
        window = period.split('..')
        periods = fact_periods({'periodStart': window[0], 'periodEnd': window[-1],
                                'periodGranularity': 'month'})
    if selected_periods is not None:
        # 复用事实粒度规范化，保留累计窗口的所有桶及环比的基期与本期。
        periods = fact_periods({**primary, 'periodValues': selected_periods})
    scope = dict(primary.get('scope') or {})
    if selector.startswith(('topGroups.', 'bottomGroups.')):
        group, index = selector.split('.')
        scope['group'] = primary[group][int(index)]['group']

    def operand(value) -> str:
        return format(Decimal(str(value)).normalize(), 'f')

    formula = primary.get('formula')
    if selector in {'monthlyAverage', 'monthlyMinimum', 'monthlyMaximum'}:
        amounts = [operand(item['value']) for item in primary['periodValues']]
        if selector == 'monthlyAverage':
            formula = '(' + ' + '.join(f'({amount})' for amount in amounts) + f') / {len(amounts)}'
        else:
            operation = 'min' if selector == 'monthlyMinimum' else 'max'
            formula = operation + '(' + ', '.join(amounts) + ')'
    elif selector.startswith(('periodTotals.', 'periodAverages.')):
        formula = ' + '.join(f"({operand(item['value'])})" for item in selected_periods)
        if selector.startswith('periodAverages.'):
            formula = f'({formula}) / {len(selected_periods)}'
    elif selector.startswith(('periodChanges.', 'periodChangeRates.')):
        baseline, current = (operand(item['value']) for item in selected_periods)
        formula = f'({current}) - ({baseline})'
        if selector.startswith('periodChangeRates.'):
            formula = f'({formula}) / ({baseline}) * 100'
    elif selector.startswith('groupShares.'):
        _, group, index = selector.split('.')
        numerator = primary[group][int(index)]
        scope['group'] = numerator['group']
        formula = f"({operand(numerator['value'])}) / ({operand(primary['total'])}) * 100"
    elif selector.startswith('groupGaps.'):
        left, right = (int(index) for index in selector.split('.')[1].split('-'))
        left_group, right_group = primary['topGroups'][left], primary['topGroups'][right]
        scope.update(leftGroup=left_group['group'], rightGroup=right_group['group'])
        formula = f"abs(({operand(left_group['value'])}) - ({operand(right_group['value'])}))"
    elif selector.startswith('budgetComparison.'):
        operands = [sum((Decimal(str(item['value'])) for item in entry['periodValues']
                         if window[0] <= item['period'][:7] <= window[-1]), Decimal(0))
                    for entry in (primary, entries[ids[1]])]
        operation = '/' if selector.endswith('.percentage') else '-'
        formula = f'({operand(operands[0])}) {operation} ({operand(operands[1])})'
        if operation == '/':
            formula += ' * 100'
    elif selector.startswith('projectRatio.'):
        operation = '/' if selector.endswith('.percentage') else '-'
        formula = f"({primary.get('formula')}) {operation} ({entries[ids[1]].get('formula')})"
        if operation == '/':
            formula += ' * 100'
    return {'value': float(value), 'unit': target if target == '个百分点' else unit,
            'periods': periods, 'scope': scope, 'formula': formula, 'entry': primary}
