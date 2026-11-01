"""语义解释仅用于当前断言的软复核，不授权数据也不替代数值核验。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from pydantic import ValidationError

from .contracts_v1 import ClaimInterpretationV1, ClaimSemanticReceiptV1

if TYPE_CHECKING:
    from ..delivery.draft_v1 import HeadingNumber


def project_semantic_headings(markdown: str, headings: Sequence[HeadingNumber]) -> str:
    """仅移除权威清单中真实标题的自动编号；数量标题、正文和代码不变。"""
    from markdown_it import MarkdownIt

    from ..delivery.draft_v1 import _inline_heading_text
    from ..delivery.report_runtime.markdown import format_heading_label

    registered = {
        (heading.level, format_heading_label(level=heading.level, number=heading.number, title=heading.title)): heading
        for heading in headings if heading.level in {3, 4}
    }
    if not registered:
        return markdown
    lines = markdown.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark').parse(markdown)
    for position, token in enumerate(tokens):
        if token.type != 'heading_open' or token.tag not in {'h3', 'h4'} or not token.map:
            continue
        title = _inline_heading_text(re.sub(r'\[\[[^\]\r\n]+\]\]', '', tokens[position + 1].content))
        heading = registered.get((int(token.tag[1:]), title))
        if heading is None:
            continue
        line = token.map[0]
        prefix = re.match(r'^( {0,3}#{3,4}[ \t]+)' + re.escape(heading.number) + r'[ \t]+', lines[line])
        if prefix is not None:
            lines[line] = prefix[1] + lines[line][prefix.end():]
    return ''.join(lines)


def _section_narrative(markdown: str) -> str:
    """投影叙述正文；图表、表格及自动标题编号不作为断言的共同主语。"""
    from markdown_it import MarkdownIt

    from ..delivery.report_runtime.markdown import _HEADING_NUMBER_PREFIX

    lines = markdown.splitlines()
    tokens = MarkdownIt('commonmark').enable('table').parse(markdown)
    pieces = []
    image_end = None
    for index, token in enumerate(tokens):
        if token.type == 'table_open' and token.map:
            table = '\n'.join(lines[token.map[0]:token.map[1]])
            if '【当前数值引用】' in table:
                pieces.append(table)
            continue
        if token.type != 'inline' or not token.map or tokens[index - 1].type not in {'paragraph_open', 'heading_open'}:
            continue
        start, end = token.map
        children = token.children or []
        if any(child.type == 'image' for child in children) and all(
            child.type == 'image' or (child.type == 'text' and not child.content.strip()) for child in children
        ):
            image_end = end
            continue
        # 装配图注是紧随独立图片的斜体段落，按结构识别，不依赖图注措辞。
        if (image_end is not None and not any(line.strip() for line in lines[image_end:start])
                and children and children[0].type == 'em_open' and children[-1].type == 'em_close'):
            image_end = None
            continue
        image_end = None
        text = '\n'.join(lines[start:end])
        if tokens[index - 1].type == 'heading_open':
            text = _HEADING_NUMBER_PREFIX.sub(lambda match: match.group().split()[0] + ' ', text)
        pieces.append(text)
    return '\n\n'.join(pieces)


_CLAIM_CONTEXT_CACHE: ContextVar[dict[tuple[str, str, bool, bool], str | None] | None] = ContextVar(
    'claim_context_cache', default=None,
)


@contextmanager
def claim_context_cache_scope() -> Iterator[None]:
    """一次章节语义复核内复用 claim_context 结果；正文为不可变字符串，结果按参数记忆。"""
    if _CLAIM_CONTEXT_CACHE.get() is not None:
        yield
        return
    token = _CLAIM_CONTEXT_CACHE.set({})
    try:
        yield
    finally:
        _CLAIM_CONTEXT_CACHE.reset(token)


def claim_context(
    markdown: str, claim_id: str, *, include_previous: bool = False, include_section: bool = False,
) -> str | None:
    """章节或前段仅是候选背景，是否承接口径仍由语义解释判断。"""
    cache = _CLAIM_CONTEXT_CACHE.get()
    if cache is None:
        return _claim_context(markdown, claim_id, include_previous=include_previous,
                              include_section=include_section)
    key = (markdown, claim_id, include_previous, include_section)
    if key not in cache:
        cache[key] = _claim_context(markdown, claim_id, include_previous=include_previous,
                                    include_section=include_section)
    return cache[key]


def _claim_context(
    markdown: str, claim_id: str, *, include_previous: bool, include_section: bool,
) -> str | None:
    from ..delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording
    from .markdown_body import SERVER_TABLE_BLOCK, trace_body

    markdown = trace_body(markdown)
    marker = f'[[claim:{claim_id}]]'
    if markdown.count(marker) != 1:
        return None
    position = markdown.index(marker)
    start = markdown.rfind('\n\n', 0, position)
    end = markdown.find('\n\n', position)
    paragraph = markdown[start + 2 if start >= 0 else 0:end if end >= 0 else len(markdown)]
    if include_section:
        # 报告装配增加的章标题/锚点不进入指纹；章内小标题保留，不裁掉共同主语。
        boundaries = list(re.finditer(
            r'(?m)^ {0,3}(?:#{1,2}(?:[ \t]+[^\n]*|[ \t]*)|\[\[section:[^\]\r\n]+\]\])[ \t]*(?:\n|$)',
            markdown,
        ))
        left = max((match.end() for match in boundaries if match.end() <= position), default=0)
        right = min((match.start() for match in boundaries if match.start() > position), default=len(markdown))
        paragraph = markdown[left:right]
    elif include_previous and start >= 0:
        previous = markdown[:start].rsplit('\n\n', 1)[-1].strip()
        if (previous and not re.search(r'^\s*#{1,6}\s|\[\[section:', previous, re.MULTILINE)
                and not re.search(r'^\s*#{1,6}\s|\[\[section:', paragraph, re.MULTILINE)):
            paragraph = previous + '\n\n' + paragraph
    paragraph = paragraph.replace(marker, '【当前数值引用】')
    if include_section:
        paragraph = SERVER_TABLE_BLOCK.sub(
            lambda match: match[0] if '【当前数值引用】' in match[0] else '', paragraph,
        )
    paragraph = re.sub(r'\[\[[^\]\r\n]+\]\]', '', paragraph)
    if include_section:
        paragraph = _section_narrative(paragraph)
    if paragraph.count('【当前数值引用】') != 1:
        return None
    return normalize_cjk_punctuation(normalize_cjk_wording(paragraph)).strip()


def _fingerprint(context: str) -> str:
    return hashlib.sha256(re.sub(r'[\s*]', '', context).encode()).hexdigest()


def quantity_binding_fingerprint(reference: Mapping) -> str:
    """保留数量角色、操作数及统计窗口，不用金额相同认定引用身份相同。"""
    from .contracts_v1 import canonical_sha256

    return canonical_sha256({
        'selector': reference.get('selector'), 'operation': reference.get('operation'),
        'expressionTree': reference.get('expressionTree'), 'operands': reference.get('operandViews'),
        'factId': reference.get('entry', {}).get('factId'), 'scope': reference.get('scope'),
        'periods': reference.get('periods'), 'unit': reference.get('unit'),
        'formula': reference.get('formula'),
        'denominatorFact': {key: value for key, value in (reference.get('denominatorFact') or {}).items()
                            if key != 'fileResourceId'},
        'populationProof': reference.get('populationProof'),
        'topSelection': reference.get('topSelection'), 'topLimit': reference.get('topLimit'),
    })


def semantic_receipt_status(markdown: str, claim_id: str, receipt: ClaimSemanticReceiptV1 | None) -> str:
    if receipt is None:
        return 'unavailable'
    context = claim_context(markdown, claim_id, include_previous=receipt.includes_previous,
                            include_section=receipt.includes_section)
    return _receipt_status(context, claim_id, receipt)


def _receipt_status(context: str | None, claim_id: str, receipt: ClaimSemanticReceiptV1) -> str:
    return ('interpreted' if context is not None and receipt.interpretation.claim_id == claim_id
            and _fingerprint(context) == receipt.context_sha256 else 'invalidated')


def freeze_interpretation(
    markdown: str, claim_id: str, interpretation, *, reviewed_markdown: str | None = None,
    include_previous: bool = False, include_section: bool = False,
) -> ClaimSemanticReceiptV1 | None:
    try:
        item = ClaimInterpretationV1.model_validate(interpretation)
    except ValidationError:
        return None
    context = claim_context(markdown, claim_id, include_previous=include_previous, include_section=include_section)
    if item.claim_id != claim_id or context is None:
        return None
    reviewed = claim_context(reviewed_markdown, claim_id, include_previous=include_previous,
                             include_section=include_section) if reviewed_markdown is not None else None
    return ClaimSemanticReceiptV1(contextSha256=_fingerprint(context), interpretation=item,
                                  reviewedContext=reviewed, includesPrevious=include_previous, includesSection=include_section)


def semantic_period_token(markdown, claim_id, token, selected, interpretation, contents, *, include_previous=False, include_section=False) -> str | None:
    """只在同一冻结事实内按有原文依据的期间及统计方式选择，不搜索同值事实。"""
    from .semantic_bindings import resolve_number_reference

    item = ClaimInterpretationV1.model_validate(interpretation)
    context = claim_context(markdown, claim_id, include_previous=include_previous, include_section=include_section)
    match = re.fullmatch(r'\{\{value:(fact-[0-9a-f]{16}):([^:{}]+):([^{}]*)\}\}', token)
    evidence = (*item.period_evidence, *item.statistic_evidence)
    if (not context or item.claim_id != claim_id or not match
            or not item.periods or not item.period_evidence or not item.statistic_evidence
            or not all(text.strip() and text in context for text in evidence)
            or item.statistic not in {'single_period', 'period_total', 'period_average'}):
        return None
    if any(scope.status == 'conflicting' or (scope.status == 'resolved'
           and scope.field in selected['scope'] and scope.value != selected['scope'][scope.field])
           for scope in item.scope):
        return None
    # 金额改写比软告警消歧更严格：全部登记范围必须有唯一、可核对的正文归属。
    for field, expected in selected['scope'].items():
        matches = [scope for scope in item.scope if scope.field == field]
        if len(matches) != 1:
            return None
        scope = matches[0]
        if (scope.status != 'resolved' or scope.value != expected or not scope.evidence
                or not all(text.strip() and text in context for text in scope.evidence)):
            return None
    if (match[2] not in {'total', 'monthlyAverage'}
            and not match[2].startswith(('periodValues.', 'periodTotals.', 'periodAverages.'))):
        return None
    same_periods = tuple(selected['periods']) == tuple(item.periods)
    average = match[2] == 'monthlyAverage' or match[2].startswith('periodAverages.')
    if same_periods and average == (item.statistic == 'period_average'):
        return None
    entry = selected['entry']
    if (entry.get('aggregation') not in {'sum', 'count'} or entry.get('periodGranularity') != 'month'
            or entry.get('periodAggregation') == 'last' or entry.get('periodMissingCount', 0)):
        return None
    periods = [row.get('period', '')[:7] for row in entry.get('periodValues', ())]
    if len(set(periods)) != len(periods) or any(period not in periods for period in item.periods):
        return None
    indices = [periods.index(period) for period in item.periods]
    if indices != list(range(indices[0], indices[-1] + 1)):
        return None
    if not all(re.fullmatch(r'\d{4}-\d{2}', period) for period in item.periods):
        return None
    calendar = [int(period[:4]) * 12 + int(period[5:]) for period in item.periods]
    if calendar != list(range(calendar[0], calendar[-1] + 1)):
        return None
    if item.statistic == 'single_period':
        if len(indices) != 1:
            return None
        selector = f'periodValues.{indices[0]}'
    elif item.statistic == 'period_average' and indices == list(range(len(periods))):
        selector = 'monthlyAverage'
    else:
        selector = ('periodAverages.' if item.statistic == 'period_average' else 'periodTotals.') + f'{indices[0]}-{indices[-1]}'
    candidate = '{{value:' + match[1] + ':' + selector + ':' + match[3] + '}}'
    resolved = resolve_number_reference(candidate, contents)
    if (resolved is None or tuple(resolved['periods']) != tuple(item.periods)
            or resolved['scope'] != selected['scope'] or resolved['unit'] != selected['unit']):
        return None
    return candidate if candidate != token else None


def semantic_warnings(
    markdown: str, claim_id: str, receipt: ClaimSemanticReceiptV1 | None,
    expected_scope: Mapping[str, str], expected_periods: tuple[str, ...], warnings: list[str],
    *, reference: Mapping | None = None,
) -> list[str]:
    if receipt is None:
        return warnings
    context = claim_context(markdown, claim_id, include_previous=receipt.includes_previous,
                            include_section=receipt.includes_section)
    if context is None or _receipt_status(context, claim_id, receipt) != 'interpreted':
        return [*warnings, '语义归属需复核：正文上下文已改变，原语义判断失效。']
    result = list(warnings)
    evidence_context = (receipt.reviewed_context or context).replace('【当前数值引用】', '')
    item = receipt.interpretation
    if item.quantity is not None:
        if receipt.quantity_binding_sha256 is None:
            result.append('数量关系需复核：正文数量关系尚未唯一绑定到可核验来源。')
        elif reference is None or quantity_binding_fingerprint(reference) != receipt.quantity_binding_sha256:
            result.append('数量关系需复核：当前引用与正文确认的操作数、分母或统计角色不一致。')
    for field, expected in expected_scope.items():
        matches = [scope for scope in item.scope if scope.field == field]
        if len(matches) != 1:
            continue
        scope = matches[0]
        grounded = bool(scope.evidence) and all(text.strip() and text in evidence_context for text in scope.evidence)
        if scope.status == 'resolved' and scope.value == expected and grounded:
            missing = f'业务范围需复核：当前引用句未体现登记范围 {field}={expected}。'
            result = [warning for warning in result if warning != missing]
        elif scope.status == 'conflicting' or (scope.status == 'resolved' and scope.value != expected):
            result.append(f'语义范围需复核：正文对 {field} 的归属与登记范围 {expected} 存在冲突。')
        elif scope.status == 'unknown':
            result.append(f'语义范围需复核：无法确定当前数值的 {field} 归属。')
        elif not grounded:
            result.append(f'语义范围需复核：{field} 的判断缺少可核对的原文依据。')
    if item.periods and item.period_evidence and all(text.strip() and text in evidence_context for text in item.period_evidence):
        allowed_periods = [tuple(expected_periods)]
        if reference and reference.get('selector') in {'monthlyMinimum', 'monthlyMaximum'}:
            rows = reference['entry'].get('periodValues') or ()
            if rows:
                extreme = (min if reference['selector'] == 'monthlyMinimum' else max)(row['value'] for row in rows)
                allowed_periods.extend((row['period'][:7],) for row in rows if row['value'] == extreme)
        if not any(sorted(item.periods) == sorted(periods) for periods in allowed_periods):
            result.append('语义期间需复核：正文所述期间与当前数值引用覆盖期间不一致。')
        elif sorted(item.periods) == sorted(expected_periods):
            from .comparison_proofs import period_list_text
            from .subject_builder import written_period_mentions

            # 同句可同时陈述本期与基期；有逐字依据的当前引用期间与冻结期间
            # 完全一致时，替代邻近背景日期产生的文本告警，不覆盖角色等其他校验。
            period_label = period_list_text(expected_periods)
            frozen_keys = tuple(key for period in expected_periods for key in written_period_mentions(period))
            # 语义解释已从完整上下文确定期间。局部证据可能省略年份或只写年份，
            # 不再要求每段证据重复完整日期；明确写出的相反年月仍不能覆盖。
            if frozen_keys and all(
                all(any(frozen[:len(key)] == key for frozen in frozen_keys)
                    for key in written_period_mentions(text))
                for text in item.period_evidence
            ):
                background_warning = f'期间文本与生成时不一致（生成时 {period_label}）'
                result = [warning for warning in result if warning != background_warning]
    if (reference and item.statistic_evidence
            and all(text.strip() and text in evidence_context for text in item.statistic_evidence)):
        selector = reference.get('selector', '')
        average = selector == 'monthlyAverage' or selector.startswith('periodAverages.')
        total = selector == 'total' or selector.startswith('periodTotals.')
        if (average and item.statistic in {'single_period', 'period_total'}
                or total and item.statistic == 'period_average'):
            result.append('语义统计方式需复核：正文所述统计方式与当前数值引用的合计或平均方式不一致。')
    return list(dict.fromkeys(result))
