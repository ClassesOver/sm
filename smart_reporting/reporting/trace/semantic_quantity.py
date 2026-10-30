"""按已核验来源身份编译数量语义，不根据数值相等搜索事实。"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact
from .contracts_v1 import (
    ClaimQuantityV1,
    FactRefV1,
    TableDerivationV1,
    TableOperandV1,
    canonical_sha256,
)
from .fact_index import merge_frozen_fact
from .numeric_text import format_fact_value
from .semantic_bindings import NumberReferenceResolver, reference_fact_ids
from .table_sources import (
    _TOTAL,
    _column_unit,
    _number,
    _structured_periods,
    resolve_table_derivation,
    table_derivation_token,
    table_semantics,
)


@dataclass(frozen=True)
class QuantityBinding:
    token: str
    view: dict[str, Any]
    display_text: str
    table_derivation: TableDerivationV1 | None = None


class QuantityCatalog:
    def __init__(self, contents: Sequence[str], table_sources: Mapping[str, bytes], *, table_contexts=None,
                 field_definitions: Mapping[str, str] | None = None):
        self.resolver = NumberReferenceResolver(contents)
        self.sources = dict(table_sources)
        self.prompt: list[dict[str, Any]] = []
        self._sources: dict[str, dict[str, Any]] = {}
        self._table_contexts = table_contexts or {}
        seen = set()
        for token in self.resolver.numbers:
            parts = token[2:-2].split(':', 3)
            if len(parts) != 4 or parts[0] != 'value':
                continue
            _, fact, selector, _unit = parts
            if selector not in {'total', 'currentTotal', 'baselineTotal', 'change', 'changeRate',
                                'value', 'percentage', 'numerator', 'denominator', 'difference',
                                'monthlyAverage', 'monthlyMinimum', 'monthlyMaximum'} and not selector.startswith(
                                    ('periodValues.', 'periodAverages.', 'periodTotals.',
                                     'periodChanges.', 'periodChangeRates.',
                                     'groupMissingShares.', 'seriesGroupMissingShares.')):
                continue
            if (fact, selector) in seen:
                continue
            seen.add((fact, selector))
            registered = self.resolver.registered_token(fact, selector)
            view = self.resolver.resolve(registered) if registered else None
            if view is None:
                continue
            source_id = _identity('fact', fact, selector)
            entry = view['entry']
            descriptor = {'sourceId': source_id, 'kind': 'fact', 'factId': fact, 'selector': selector,
                          'label': entry.get('displayName') or entry.get('field'),
                          'scope': view['scope'], 'periods': list(view['periods']), 'unit': view['unit']}
            descriptor['periodRoles'] = view['period_roles']
            if selector in {'change', 'changeRate', 'difference'} or selector.startswith(
                    ('periodChanges.', 'periodChangeRates.')):
                descriptor.update(
                    quantityRole='registered_change_rate' if selector == 'changeRate'
                    or selector.startswith('periodChangeRates.') else 'registered_change',
                    periodMeaning=('已登记左右操作数在共同期间的差额，不代表跨期变化'
                                   if selector == 'difference' else
                                   '已登记比较的基期和当期窗口；必须与正文所述两期一致'),
                    operationMeaning='已登记完整比较结果，直接使用operation=value，不再用两期总量重复计算',
                )
            if selector.startswith(('groupMissingShares.', 'seriesGroupMissingShares.')):
                group = selector.split('.', 1)[1]
                descriptor.update(quantityRole='group_missing_absolute_share',
                                  groupingField=group,
                                  windowBasis='series' if selector.startswith('seriesGroupMissingShares.') else 'value',
                                  meaning='该维度归属缺失行的指标绝对值合计占同范围全部行指标绝对值合计的比例')
                descriptor['periodMeaning'] = (
                    '全部已登记期间的原始行，覆盖上述periods；不是最新单月'
                    if selector.startswith('seriesGroupMissingShares.') else
                    '登记指标取值窗口内的原始行，覆盖上述periods；时点指标仅最新单月'
                )
                descriptor['operationMeaning'] = '已登记完整比例，直接使用operation=value，不再另除分母'
                if label := (field_definitions or {}).get(group):
                    descriptor['groupingLabel'] = label
            self.prompt.append(descriptor)
            self._sources[source_id] = {'kind': 'fact', 'token': registered, 'view': view}
        allowed = {content.encode() for content in contents}
        seen_bytes = set()
        for resource, raw in sorted(table_sources.items()):
            if not isinstance(raw, bytes) or raw not in allowed or raw in seen_bytes:
                continue
            seen_bytes.add(raw)
            try:
                document = json.loads(raw)
            except (ValueError, TypeError):
                continue
            self._tables(resource, raw, document, document, '')

    def prompt_for(self, views: Sequence[Mapping[str, Any]], *,
                   tokens: Sequence[str] = (),
                   table_derivations: Sequence[TableDerivationV1] = ()) -> list[dict[str, Any]]:
        """只投影本批登记身份及其业务家族；宿主的完整解析目录不变。"""
        fact_ids: set[str] = set()
        tables: set[tuple[str, str]] = set()

        def collect(entry):
            if not isinstance(entry, Mapping):
                return
            if fact_id := entry.get('factId'):
                fact_ids.add(fact_id)
            fact_ids.update(entry.get('inputFactIds') or ())
            if parent := entry.get('parentFactId'):
                fact_ids.add(parent)

        for view in views:
            collect(view.get('entry'))
            for entry in (*view.get('operandEntries', ()), *view.get('operandViews', ())):
                collect(entry)
        # budgetComparison/metricShare/derived 等既有视图未必展开操作数；
        # 从已核验 token 读取原登记身份，不能靠字段家族猜分母。
        for token in tokens:
            if self.resolver.resolve(token) is not None:
                fact_ids.update(reference_fact_ids(token))
        for derivation in table_derivations:
            tables.update((operand.file_resource_id, operand.table_pointer) for operand in derivation.operands)
            for fact in (derivation.population_fact, derivation.denominator_fact):
                if fact is not None and fact.fact_key:
                    fact_ids.add(fact.fact_key)
        for source in self._sources.values():
            if source['kind'] == 'table_column' and (source['resource'], source['pointer']) in tables:
                if parent := source['population'].get('populationFactId'):
                    fact_ids.add(parent)

        # 同物理列还可能承载不同业务指标或不同主体，不能只按 fieldRef 扩大候选。
        entries = self.resolver.entries
        family_keys = ('fieldRef', 'scope', 'metricCodes', 'unit', 'aggregation', 'periodAggregation')
        seeds = [entries[key] for key in fact_ids if key in entries]
        for key, entry in entries.items():
            if any(seed.get('fieldRef') and all(entry.get(name) == seed.get(name) for name in family_keys)
                   for seed in seeds):
                fact_ids.add(key)
        # 比较结果只在全部操作数已属于本批家族时加入，不沿共享分母串联无关指标。
        for key, entry in entries.items():
            operands = set(entry.get('inputFactIds') or ())
            if entry.get('comparisonType') and operands and operands <= fact_ids:
                fact_ids.add(key)
        pending = list(fact_ids)
        while pending:
            entry = entries.get(pending.pop(), {})
            parents = [*(entry.get('inputFactIds') or ())]
            if parent := entry.get('parentFactId'):
                parents.append(parent)
            for parent in parents:
                if parent not in fact_ids:
                    fact_ids.add(parent)
                    pending.append(parent)

        result = []
        for descriptor in self.prompt:
            if descriptor['kind'] == 'fact':
                if descriptor['factId'] in fact_ids:
                    result.append(descriptor)
            else:
                source = self._sources[descriptor['sourceId']]
                if ((source['resource'], source['pointer']) in tables
                        or source['population'].get('populationFactId') in fact_ids):
                    result.append(descriptor)
        return result

    def _tables(self, resource, raw, document, node, pointer):
        if isinstance(node, list):
            for index, value in enumerate(node):
                self._tables(resource, raw, document, value, f'{pointer}/{index}')
            return
        if not isinstance(node, dict):
            return
        columns, rows = node.get('columns'), node.get('rows')
        if (isinstance(columns, list) and columns and len(set(map(str, columns))) == len(columns)
                and all(isinstance(column, str) for column in columns)
                and isinstance(rows, list) and rows
                and all(isinstance(row, list) and len(row) == len(columns) for row in rows)):
            text_columns = [index for index in range(len(columns))
                            if all(isinstance(row[index], str) and row[index].strip() for row in rows)]
            labels = [' / '.join(row[index] for index in text_columns) for row in rows]
            complete = (bool(text_columns) and len(set(labels)) == len(rows)
                        and not any(_TOTAL.fullmatch(label.strip()) for label in labels))
            semantics = table_semantics(document, node)
            resource_context = self._table_contexts.get(resource, {})
            trusted = resource_context.get(pointer, resource_context)
            if trusted:
                scope = trusted.get('scope')
                periods = _structured_periods({**trusted, 'periodGranularity':
                    node.get('periodGranularity', document.get('periodGranularity'))})
                if (not isinstance(scope, Mapping) or not isinstance(periods, (list, tuple))
                        or semantics['scope'] and semantics['scope'] != scope
                        or semantics['periods'] and tuple(semantics['periods']) != tuple(periods)):
                    trusted = {}
                else:
                    semantics = {**semantics, 'scope': dict(scope), 'periods': tuple(periods)}
            for column, name in enumerate(columns):
                unit = _column_unit(node, name)
                if unit is None:
                    continue
                meta = node.get('columnMeta', {}).get(name, {})
                column_semantics = (table_semantics(document, node, name)
                                    if isinstance(meta, Mapping) and any(key in meta for key in
                                        ('periods', 'periodStart', 'periodEnd', 'scope', 'periodRoles'))
                                    else semantics)
                source_id = _identity('table', hashlib.sha256(raw).hexdigest(), pointer, str(column))
                descriptor = {'sourceId': source_id, 'kind': 'table_column', 'tablePointer': pointer,
                              'column': name, 'label': node.get('name') or node.get('title'),
                              'rowLabels': labels, 'unit': unit, 'scope': column_semantics['scope'],
                              'periods': list(column_semantics['periods'])}
                if trusted.get('completePopulation') is True:
                    descriptor['completePopulation'] = True
                    descriptor['populationFactSourceId'] = _identity('fact', trusted.get('populationFactId'), 'total')
                self.prompt.append(descriptor)
                self._sources[source_id] = {'kind': 'table_column', 'resource': resource, 'pointer': pointer,
                    'column': column, 'unit': unit, 'rows': rows, 'labels': labels,
                    'semantics': column_semantics,
                    'population': trusted,
                    'complete': complete and all(_number(row[column]) is not None for row in rows)}
        for key, value in node.items():
            self._tables(resource, raw, document, value, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))

    def resolve(self, quantity, context: str, *, display_unit: str | None = None) -> QuantityBinding | None:
        try:
            item = ClaimQuantityV1.model_validate(quantity)
            # 定位符不属于原文；逐字依据和歧义次数均按真实可见上下文核对。
            marker = '【当前数值引用】'
            offset = context.index(marker) if context.count(marker) == 1 else None
            context = context.replace(marker, '')
            def grounded(text):
                if not text.strip():
                    return False
                if context.count(text) == 1:
                    return True
                return offset is not None and any(
                    match.end() == offset
                    for match in re.finditer(re.escape(text), context)
                )
            if (item.operation == 'unknown' or not item.left or not item.evidence
                    or any(not grounded(text) for text in item.evidence)
                    or len(set(item.left)) != len(item.left) or len(set(item.right)) != len(item.right)):
                return None
            left = [self._sources[source] for source in item.left]
            right = [self._sources[source] for source in item.right]
            if any(source['kind'] == 'table_column' for source in (*left, *right)):
                return self._table(item, left, right, display_unit)
            return self._facts(item, left, right, display_unit)
        except (KeyError, ValueError, TypeError, ArithmeticError, ValidationError):
            return None

    def _facts(self, item, left, right, display_unit):
        def expression(sources):
            operands = [source['token'][len('{{value:'):-2].rsplit(':', 1)[0] for source in sources]
            return operands[0] if len(operands) == 1 else 'sum(' + ','.join(operands) + ')'

        if item.row_label or item.limit is not None or item.order_by_source_id is not None:
            return None
        if item.operation == 'value' and len(left) == 1 and not right:
            view = left[0]['view']
            unit = display_unit or view['unit']
            token = left[0]['token'].rsplit(':', 1)[0] + ':' + unit + '}}'
        elif item.operation == 'sum' and len(left) >= 2 and not right:
            unit = display_unit or left[0]['view']['unit']
            token = '{{calc:' + expression(left) + ':' + unit + '}}'
        elif item.operation in {'difference', 'share'} and right:
            unit = display_unit or ('%' if item.operation == 'share' else left[0]['view']['unit'])
            op = 'ratio' if item.operation == 'share' else 'diff'
            token = '{{calc:' + op + '(' + expression(left) + ',' + expression(right) + '):' + unit + '}}'
        else:
            return None
        view = self.resolver.resolve(token)
        if view is None:
            return None
        return QuantityBinding(token, view, format_fact_value(view['value'], view['unit'], unit))

    def _table(self, item, left, right, display_unit):
        if len(left) != 1 or left[0]['kind'] != 'table_column':
            return None
        source = left[0]
        if not source['complete']:
            return None
        denominator = None
        if right:
            if (item.operation not in {'share', 'top_share'} or len(right) != 1 or right[0]['kind'] != 'fact'
                    or right[0]['view']['selector'] != 'total' or display_unit not in {None, '%'}):
                return None
            denominator = self._fact_ref(right[0]['view']['entry'])
            if denominator is None:
                return None
        if item.operation in {'value', 'share'}:
            if item.operation == 'share' and denominator is None:
                return None
            if (not item.row_label or item.row_label not in source['labels']
                    or not any(item.row_label in evidence for evidence in item.evidence)
                    or item.limit is not None or item.order_by_source_id is not None):
                return None
            indices = [source['labels'].index(item.row_label)]
        elif item.operation in {'top_sum', 'top_share'}:
            if (item.limit is None or item.limit > len(source['rows']) or item.row_label
                    or item.selection not in {'rank', 'items'}):
                return None
            order = self._sources[item.order_by_source_id] if item.order_by_source_id else source
            if (order['kind'] != 'table_column' or not order['complete']
                    or (source['resource'], source['pointer']) != (order['resource'], order['pointer'])
                    or item.operation == 'top_share' and denominator is None
                    and (not item.order_by_source_id or source['unit'] != '%')):
                return None
            population = self._population(order)
            if population is None:
                return None
            if item.operation == 'top_share' and denominator is None:
                total = population['value']
                if not total or any(abs(float(_number(row[source['column']])) -
                    float(_number(row[order['column']])) / total * 100) > 0.000001
                    for row in source['rows']):
                    return None
            ordered = sorted(range(len(source['rows'])),
                             key=lambda index: (-_number(order['rows'][index][order['column']]), source['labels'][index]))
            indices = ordered[:item.limit]
            if item.selection == 'rank':
                threshold = _number(order['rows'][indices[-1]][order['column']])
                indices = [index for index in ordered if _number(order['rows'][index][order['column']]) >= threshold]
        else:
            return None
        from ..units import unit_conversion_scale

        unit = '%' if denominator else display_unit or source['unit']
        scale = unit_conversion_scale(source['unit'], right[0]['view']['unit'] if denominator else unit)
        if scale is None:
            return None
        derivation = TableDerivationV1(operands=tuple(TableOperandV1(
            fileResourceId=source['resource'], tablePointer=source['pointer'], rowIndex=index,
            columnIndex=source['column'], coefficient=str(scale),
        ) for index in indices), unit=unit, denominatorFact=denominator)
        if item.operation in {'top_sum', 'top_share'} and source['population'].get('version') == 'standard-population-v1':
            population_ref = self._fact_ref(population['entry'])
            if population_ref is None or source['unit'] in {'%', '‰'}:
                return None
            if denominator is not None and denominator != population_ref:
                return None
            derivation = derivation.model_copy(update={'population_fact': population_ref,
                'population_proof_sha256': canonical_sha256(source['population']),
                'top_selection': item.selection, 'top_limit': item.limit})
        token = table_derivation_token(derivation, self.sources)
        view = resolve_table_derivation(token, derivation, self.sources) if token else None
        if view is None:
            return None
        return QuantityBinding(token, view, format_fact_value(view['value'], unit, unit), derivation)

    def _fact_ref(self, entry):
        """核对全部同身份副本；等价分析描述以稳定来源顺序选引用。"""
        candidates = []
        merged = entry
        for resource, raw in self.sources.items():
            try:
                document = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(document, dict):
                continue
            for index, fact in enumerate(document.get('metrics', [])):
                if isinstance(fact, dict) and fact.get('factId') == entry.get('factId'):
                    normalized = DeterministicMetricFact.model_validate(fact).model_dump(mode='json', by_alias=True)
                    merged = merge_frozen_fact(merged, normalized)
                    if merged is None:
                        return None
                    ref = FactRefV1(analysisId=document['analysisId'],
                        fileResourceId=resource, jsonPointer=f'/metrics/{index}',
                        factKind='metric', factKey=fact['factId'])
                    candidates.append((ref, normalized))
        # 与合并事实的期间粒度一致，避免旧day副本让月序列退化为离散日。
        compatible = [ref for ref, fact in candidates
                      if fact.get('periodGranularity') == merged.get('periodGranularity')]
        return min(compatible, key=lambda ref: (ref.file_resource_id, ref.json_pointer,
                                              ref.analysis_id)) if compatible else None

    def _population(self, source):
        semantics = source['semantics']
        population = source['population']
        if (not semantics['periods'] or source['unit'] in {'%', '‰'}
                or population.get('completePopulation') is not True):
            return None
        candidates = [item['view'] for item in self._sources.values() if item['kind'] == 'fact'
                      and item['view']['selector'] == 'total'
                      and item['view']['entry'].get('factId') == population.get('populationFactId')
                      and item['view']['entry'].get('aggregation') == 'sum'
                      and item['view']['entry'].get('periodAggregation') in {None, 'sum'}
                      and item['view']['entry'].get('cumulativePolicy') is None
                      and item['view']['scope'] == semantics['scope']
                      and tuple(item['view']['periods']) == tuple(semantics['periods'])
                      and item['view']['unit'] == source['unit']]
        identities = {item.get('entry', {}).get('factId') for item in candidates}
        if len(candidates) != 1 or len(identities) != 1:
            return None
        total = sum(_number(row[source['column']]) for row in source['rows'])
        expected = candidates[0]['value']
        return candidates[0] if abs(float(total) - expected) <= max(1e-9, abs(expected) * 1e-12) else None


def _identity(*parts: str) -> str:
    return 'quantity-' + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def build_quantity_catalog(contents: Sequence[str], table_sources: Mapping[str, bytes], *, table_contexts=None,
                           field_definitions: Mapping[str, str] | None = None) -> QuantityCatalog:
    return QuantityCatalog(contents, table_sources, table_contexts=table_contexts,
                           field_definitions=field_definitions)
