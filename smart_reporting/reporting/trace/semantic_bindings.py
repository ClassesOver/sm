"""把冻结数值选择器及提示类型保留到编辑器；不根据业务名称猜事实。"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .contracts_v1 import NumberReferenceV1, ReviewNoticeV1
from .numeric_text import (
    _frozen_number_entries,
    align_placeholder_direction,
    correct_period_extrema,
    frozen_number_catalog,
    normalize_signed_wording,
    render_frozen_numbers,
    replace_unregistered_numbers,
)


def reference_fact_ids(token: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"fact-[0-9a-f]{16}", token)))


def statement_fingerprint(markdown: str, claim_id: str) -> str | None:
    from ..delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording

    markdown = normalize_cjk_punctuation(normalize_cjk_wording(markdown))
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


def resolve_number_reference(token: str, contents) -> dict[str, Any] | None:
    """仅从调用者已经核验文件身份的内容重算完整 token；缺失或冲突不回退 total。"""
    contents = tuple(contents)
    matches = [(value, unit, target) for candidate, value, unit, target in _frozen_number_entries(contents)
               if candidate == token]
    if not matches or len({(str(value), unit, target) for value, unit, target in matches}) != 1:
        return None
    ids = reference_fact_ids(token)
    entries = {}
    for content in contents:
        document = json.loads(content)
        for array in ('metrics', 'comparisons', 'derivedMetrics', 'reconciliations', 'correlationDetails'):
            for fact in document.get(array, ()):
                if fact.get('factId') in ids:
                    if fact['factId'] in entries and entries[fact['factId']] != fact:
                        return None
                    entries[fact['factId']] = fact
    if not ids or set(ids) != entries.keys():
        return None
    primary = entries[ids[0]]
    value, unit, target = matches[0]
    selector = token[2:-2].split(':')[2]
    from .subject_builder import fact_periods
    periods = fact_periods(primary)
    if selector.startswith('periodValues.'):
        periods = (primary['periodValues'][int(selector.split('.')[1])]['period'],)
    elif selector.startswith(('periodTotals.', 'periodAverages.')):
        start, end = (int(index) for index in selector.split('.')[1].split('-'))
        selected_periods = primary['periodValues'][start:end + 1]
        periods = tuple(dict.fromkeys((selected_periods[0]['period'], selected_periods[-1]['period'])))
    elif selector.startswith(('periodChanges.', 'periodChangeRates.')):
        periods = (primary['periodValues'][int(selector.split('.')[1])]['period'],)
    elif selector.startswith('budgetComparison.'):
        period = selector[len('budgetComparison.' + ids[1] + '.'):].rsplit('.', 1)[0]
        periods = tuple(dict.fromkeys(period.split('..')))
    scope = dict(primary.get('scope') or {})
    if selector.startswith(('topGroups.', 'bottomGroups.')):
        group, index = selector.split('.')
        scope['group'] = primary[group][int(index)]['group']
    formula = primary.get('formula')
    if selector.startswith(('budgetComparison.', 'projectRatio.')):
        operation = '/' if selector.endswith('.percentage') else '-'
        formula = f"({primary.get('formula')}) {operation} ({entries[ids[1]].get('formula')})"
        if operation == '/':
            formula += ' * 100'
    return {'value': float(value), 'unit': target if target == '个百分点' else unit,
            'periods': periods, 'scope': scope, 'formula': formula, 'entry': primary}
