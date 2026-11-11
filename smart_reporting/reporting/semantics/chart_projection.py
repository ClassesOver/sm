"""正式结果到标准静态图的有限投影；原始Decimal及事实身份不改写。"""

import math

from .planning_contracts import MetricPlanningContext


def registered_chart_results(document, tokens):
    """返回精确位置及结果；整组选择必须属于同一指标版本，不按相等数值配对。"""
    context = MetricPlanningContext.model_validate(document['metricContext'])
    return _registered_chart_results(context, tokens)


def _registered_chart_results(context, tokens):
    if (len(tokens) not in (4, 5) or tokens[:2] != ('metricContext', 'calculations')
            or not isinstance(tokens[2], int) or tokens[2] < 0 or tokens[3] != 'results'
            or len(tokens) == 5 and (not isinstance(tokens[4], int) or tokens[4] < 0)):
        raise ValueError('chart_fact_selector_unregistered')
    calculation = context.calculations[tokens[2]]
    positions = range(len(calculation.results)) if len(tokens) == 4 else (tokens[4],)
    definitions = {metric.version_ref(): metric for metric in context.metrics}
    results = tuple((position, calculation.results[position]) for position in positions)
    if not results or len({result.metric_version for _, result in results}) != 1:
        raise ValueError('chart_metric_ownership_unregistered')
    # 依赖按精确版本遍历；只有原请求可达的结果才能进入图表。
    reachable, pending = set(), [calculation.request.metric_version]
    while pending:
        version = pending.pop()
        if version in reachable:
            continue
        reachable.add(version)
        metric = definitions[version]
        pending.extend(ref for ref in (metric.numerator_version, metric.denominator_version) if ref is not None)
    if results[0][1].metric_version not in reachable:
        raise ValueError('chart_metric_ownership_unregistered')
    definition = definitions[results[0][1].metric_version]
    if (definition.scope_id != context.request.organization or context.policy.scope_id != context.request.organization
            or calculation.request.basis_id != context.basis_id
            or len({result.fact_id for _, result in results}) != len(results)):
        raise ValueError('chart_fact_identity_mismatch')
    for _, result in results:
        if (result.basis_id != context.basis_id or result.calculation_id != calculation.receipt_id
                or result.unit != definition.unit or result.period != calculation.request.period
                or tuple(item.dimension_id for item in result.dimensions) != calculation.request.dimensions):
            raise ValueError('chart_fact_identity_mismatch')
    return context, definition, results


def registered_chart_table(document, tokens, fields):
    if not fields or len(set(fields)) != len(fields) or not set(fields).issubset({'label', 'value'}):
        raise ValueError('chart_projection_selector_unregistered')
    _, definition, results = registered_chart_results(document, tokens)
    rows, labels = [], set()
    for _, result in results:
        label = f'{definition.name} · [{result.period.start.isoformat()}, {result.period.end.isoformat()})'
        if result.dimensions:
            label += ' · ' + '、'.join(f'{item.dimension_id}={"（空值）" if item.value is None else item.value}'
                for item in result.dimensions)
        if label in labels:
            raise ValueError('chart_projection_category_ambiguous')
        labels.add(label)
        value = None if result.value is None else float(result.value)
        if value is not None and (not math.isfinite(value) or value == 0 and result.value != 0):
            raise ValueError('chart_render_numeric_range_unavailable')
        row = {'label': label, 'value': value}
        rows.append([row[field] for field in fields])
    metadata = {'value': {'unit': definition.unit}} if 'value' in fields else {}
    if definition.unit == '%' and metadata:
        metadata['value']['isPercent'] = True
    return list(fields), rows, metadata


def registered_chart_descriptors(document):
    descriptors = []
    context = MetricPlanningContext.model_validate(document['metricContext'])
    for calculation_index, calculation in enumerate(context.calculations):
        selectors = [(result_index,) for result_index in range(len(calculation.results))]
        if len(calculation.results) > 1:
            selectors.insert(0, ())
        for suffix in selectors:
            tokens = ('metricContext', 'calculations', calculation_index, 'results', *suffix)
            try:
                _registered_chart_results(context, tokens)
            except (ValueError, KeyError, IndexError):
                continue
            path = f'metricContext.calculations[{calculation_index}].results' + (f'[{suffix[0]}]' if suffix else '')
            descriptors.append({'dataPath': path, 'fields': ['label', 'value'],
                'dataScope': '已登记指标结果；期间含起日、不含止日；不重新聚合或补零。',
                'standardHints': {'standardLabelField': 'label', 'standardValueFields': ['value']}})
    return descriptors
