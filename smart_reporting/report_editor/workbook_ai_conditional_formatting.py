"""Translate GenOffice conditional-format rules to the native Univer wire shape."""
from __future__ import annotations

import math
import re
from typing import Any

_INVALID = 'workbook_ai_conditional_format_invalid'
_NUMBER_COMPARISONS = {
    'greaterThan', 'greaterThanOrEqual', 'lessThan', 'lessThanOrEqual',
    'equal', 'notEqual', 'between', 'notBetween',
}
_TEXT_COMPARISONS = {
    'contains': 'containsText', 'notContains': 'notContainsText',
    'beginsWith': 'beginsWith', 'endsWith': 'endsWith',
}
_ILLEGAL_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def _color(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        raise ValueError(_INVALID)
    return value


def _format(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value or set(value) - {'fillColor', 'fontColor', 'bold', 'italic'}:
        raise ValueError(_INVALID)
    result = {}
    for key, target in [('fillColor', 'bg'), ('fontColor', 'cl')]:
        if key in value:
            result[target] = {'rgb': _color(value[key])}
    for key, target in [('bold', 'bl'), ('italic', 'it')]:
        if key in value:
            if type(value[key]) is not bool:
                raise ValueError(_INVALID)
            if value[key]:
                result[target] = 1
    return result


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= limit or _ILLEGAL_XML.search(value):
        raise ValueError(_INVALID)
    return value


def source_conditional_rule(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, dict) or not isinstance(kind := rule.get('kind'), str):
        raise ValueError(_INVALID)
    required, optional = {
        'number': ({'operator', 'value', 'format'}, {'value2'}),
        'text': ({'operator', 'text', 'format'}, set()),
        'blank': ({'blank', 'format'}, set()),
        'duplicate': ({'format'}, {'unique'}),
        'top10': ({'rank', 'format'}, {'percent', 'bottom'}),
        'formula': ({'formula', 'format'}, set()),
        'colorScale': ({'minColor', 'maxColor'}, {'midColor'}),
        'dataBar': (set(), {'color'}),
    }.get(kind, (set(), set()))
    if set(rule) - optional != required | {'kind'}:
        raise ValueError(_INVALID)
    if kind == 'colorScale':
        keys = ['minColor', 'midColor', 'maxColor'] if 'midColor' in rule else ['minColor', 'maxColor']
        thresholds = {'minColor': {'type': 'min'}, 'midColor': {'type': 'percentile', 'value': 50},
                      'maxColor': {'type': 'max'}}
        return {'type': 'colorScale', 'config': [
            {'index': index, 'color': _color(rule[key]), 'value': thresholds[key]}
            for index, key in enumerate(keys)
        ]}
    if kind == 'dataBar':
        return {'type': 'dataBar', 'isShowValue': True, 'config': {
            'min': {'type': 'min'}, 'max': {'type': 'max'},
            'positiveColor': _color(rule.get('color', '#638EC6')),
        }}
    if kind not in {'number', 'text', 'blank', 'duplicate', 'top10', 'formula'}:
        raise ValueError(_INVALID)
    style = _format(rule['format'])
    if kind == 'number':
        operator, first = rule['operator'], rule['value']
        second = rule.get('value2', first)
        if (not isinstance(operator, str) or operator not in _NUMBER_COMPARISONS
                or any(type(value) not in (int, float) or abs(value) > 1.7976931348623157e308
                       or not math.isfinite(value) for value in (first, second))):
            raise ValueError(_INVALID)
        value = [first, second] if operator in {'between', 'notBetween'} else first
        condition = {'subType': 'number', 'operator': operator, 'value': value}
    elif kind == 'text':
        operator = rule['operator']
        if not isinstance(operator, str) or operator not in _TEXT_COMPARISONS:
            raise ValueError(_INVALID)
        condition = {'subType': 'text', 'operator': _TEXT_COMPARISONS[operator], 'value': _text(rule['text'], 255)}
    elif kind == 'blank':
        if type(rule['blank']) is not bool:
            raise ValueError(_INVALID)
        condition = {'subType': 'text', 'operator': 'containsBlanks' if rule['blank'] else 'notContainsBlanks'}
    elif kind == 'duplicate':
        if type(rule.get('unique', False)) is not bool:
            raise ValueError(_INVALID)
        condition = {'subType': 'uniqueValues' if rule.get('unique') else 'duplicateValues'}
    elif kind == 'top10':
        if (type(rule['rank']) is not int or not 1 <= rule['rank'] <= 1000
                or any(type(rule.get(key, False)) is not bool for key in ('percent', 'bottom'))):
            raise ValueError(_INVALID)
        condition = {'subType': 'rank', 'value': rule['rank'],
                     'isPercent': rule.get('percent', False), 'isBottom': rule.get('bottom', False)}
    else:
        formula = _text(rule['formula'], 8192)
        if not formula.startswith('=') or not formula[1:].strip():
            raise ValueError(_INVALID)
        condition = {'subType': 'formula', 'value': formula}
    return {'type': 'highlightCell', 'style': style, **condition}
