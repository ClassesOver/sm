"""Independent replacement-data cases and expected plotted values, not model outputs."""
import copy
import random


def parameters(form='line', **options):
    return {'chart_id': 'stress', 'renderer': 'matplotlib', 'interactive_path': None,
            'visual_form': form, 'source_path': 'standard.png', 'title': '扩展数据回放', **options}


def case(name, documents, params, expected='render', **assertions):
    return {'id': 'extended-' + name, 'group': name.split('-')[0], 'variant': name,
            'synthetic': True, 'parameters': params, 'documents': documents,
            'expected': expected, 'assertions': assertions}


def extended_cases():
    # Independently shuffled sources must align to the first frozen source order.
    for count in [2, 3, 8]:
        for seed in [3, 17, 51]:
            rng = random.Random(seed)
            documents, selections, expected = [], [], []
            for index in range(count):
                name, field = f'业务（{index}） · 本期', f'数值_{index}'
                rows = [[f'2026-{month:02}', 100 * (index + 1) + month] for month in range(1, 7)]
                if index:
                    rng.shuffle(rows)
                documents.append({'columns': ['期间', field], 'rows': rows, 'columnMeta': {field: {'unit': '元'}}})
                selections.append({'sourceIndex': index, 'labelField': '期间', 'valueField': field, 'seriesName': name})
                expected.append({'name': name, 'kind': 'line', 'values': [100 * (index + 1) + month for month in range(1, 7)]})
            yield case(f'multisource-{count}-{seed}', documents, parameters(standard_sources=selections), series=expected)
    documents = [
        {'columns': ['period', 'value'], 'rows': [['2026-01', 10], ['2026-02', 20]], 'columnMeta': {'value': {'unit': '元'}}},
        {'columns': ['period', 'value'], 'rows': [['2026-02', 40], ['2026-01', 30]], 'columnMeta': {'value': {'unit': '元'}}},
    ]
    selections = [{'sourceIndex': index, 'labelField': 'period', 'valueField': 'value', 'seriesName': name}
                  for index, name in enumerate(['甲', '乙'])]
    for fault in ['missing_label', 'duplicate_label', 'missing_unit', 'null_meta', 'bool_value',
                  'unused_source', 'duplicate_name', 'window_mismatch', 'percent_scale', 'tamper_primary', 'tamper_secondary']:
        docs, selected = copy.deepcopy(documents), copy.deepcopy(selections)
        assertion = {}
        expected = 'fallback'
        if fault == 'missing_label':
            docs[1]['rows'].pop()
        elif fault == 'duplicate_label':
            docs[1]['rows'][0][0] = '2026-01'
        elif fault == 'missing_unit':
            docs[1].pop('columnMeta')
        elif fault == 'null_meta':
            docs[1]['columnMeta']['value'] = None
        elif fault == 'bool_value':
            docs[1]['rows'][0][1] = True
        elif fault == 'unused_source':
            selected.pop()
        elif fault == 'duplicate_name':
            selected[1]['seriesName'] = '甲'
        elif fault == 'window_mismatch':
            docs[0]['columnMeta']['value']['periods'] = ['2026-01']
        elif fault == 'percent_scale':
            docs[0]['columnMeta']['value'] = {'unit': '%', 'isPercent': False}
            docs[1]['columnMeta']['value'] = {'unit': '%', 'isPercent': True}
        else:
            expected = 'identity'
            assertion['tamperSource'] = 0 if fault == 'tamper_primary' else 1
        yield case('multisource-' + fault, docs, parameters(standard_sources=selected), expected, **assertion)
    for form in ['bar', 'barh', 'line']:
        for fraction in [True, False]:
            values = [.125, 0, -.05]
            doc = {'columns': ['label', 'actual'], 'rows': [[label, value] for label, value in zip(['甲', '乙', '丙'], values)],
                   'columnMeta': {'actual': {'unit': '%', 'isPercent': not fraction}}}
            params = parameters(form, standard_value_fields=['actual'], standard_annotations=[{'kind': 'values', 'series': 'actual'}])
            yield case(f'percentage-{form}-{fraction}', [doc], params,
                       series=[{'name': 'actual', 'kind': 'line' if form == 'line' else 'bar',
                                'values': [value * (100 if fraction else 1) for value in values]}])
    for target, divisor in [('元', 1), ('万元', 1e4), ('亿元', 1e8)]:
        for form in ['line', 'barh']:
            doc = {'columns': ['label', 'actual'], 'rows': [['甲', 123456789], ['乙', 987654321]], 'columnMeta': {'actual': {'unit': '元'}}}
            yield case(f'conversion-{target}-{form}', [doc], parameters(form, standard_display_unit=target),
                       series=[{'name': 'actual', 'kind': 'line' if form == 'line' else 'bar', 'values': [123456789 / divisor, 987654321 / divisor]}])
    for labels, month_mode, expected in [
        (['2024-02-29', '2024-03-31'], True, 'render'),
        (['2025-12', '2026-01'], True, 'fallback'),
        (['2025-12', '2026-01'], False, 'render'),
        (['2026-01-01', '2026-01-31'], True, 'fallback'),
        (['2026-02-30', '2026-03-01'], True, 'fallback'),
        (['2026-01-01T00:00:00', '2026-02-01T00:00:00'], True, 'fallback'),
        (['甲 / 院区', '乙（非病区）'], False, 'render'),
    ]:
        document = {'columns': ['label', 'actual'], 'rows': [[label, (i + 1) * 10] for i, label in enumerate(labels)], 'columnMeta': {'actual': {'unit': '元'}}}
        yield case(f'dates-{labels[0]}-{month_mode}'.replace('/', '_').replace(':', '_'), [document],
                   parameters(standard_presentation={'labelMode': 'month' if month_mode else 'source'}), expected)
    for mode in ['dual', 'panels', 'zoom', 'log']:
        for count in [2, 4]:
            for distribution in ['positive', 'zero', 'negative', 'mixed_units']:
                names = [f'指标{i}' for i in range(count)]
                values = [10 ** (i * 4) for i in range(count)]
                if distribution == 'zero':
                    values[0] = 0
                elif distribution == 'negative':
                    values[0] *= -1
                metadata = {name: {'unit': '%' if distribution == 'mixed_units' and i % 2 else '元'} for i, name in enumerate(names)}
                rows = [['2026-01', *values], ['2026-02', *[value * 2 for value in values]]]
                doc = {'columns': ['period', *names], 'rows': rows, 'columnMeta': metadata}
                axes = {'scale': 'log'} if mode == 'log' else {'mode': mode}
                if mode == 'dual':
                    axes['rightFields'] = names[1::2]
                elif mode == 'zoom':
                    axes.update(zoomStart='2026-01', zoomEnd='2026-02')
                declined = mode == 'log' and distribution in ['zero', 'negative', 'mixed_units'] or mode == 'zoom' and distribution == 'mixed_units'
                expected = []
                for index, name in enumerate(names):
                    caption = name + (' · 右轴' if index % 2 else ' · 左轴') if mode == 'dual' else name
                    expected.append({'name': caption, 'kind': 'line', 'values': [values[index], 2 * values[index]]})
                yield case(f'axes-{mode}-{count}-{distribution}', [doc], parameters(standard_axes=axes),
                           'fallback' if declined else 'render', series=expected)
    for direction in [False, True]:
        for fraction in [False, True]:
            doc = {'columns': ['label', 'actual', 'budget'], 'rows': [['甲', 12, 20], ['乙', 5, 10], ['丙', 25, 40]],
                   'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
            order = sorted(doc['rows'], key=lambda row: row[1], reverse=direction)
            p = parameters('barh', standard_value_fields=['actual'],
                standard_style={'points': [{'series': 'actual', 'label': '乙', 'color': '#bd4f4f'}]},
                standard_annotations=[{'kind': 'values', 'series': 'actual'}],
                standard_presentation={'order': {'mode': 'value', 'field': 'actual', 'descending': direction},
                    'labelFormats': [{'numerator': 'actual', 'denominator': 'budget', 'caption': '执行率'}]})
            if fraction:
                p['standard_presentation']['summaries'] = [{'field': 'actual', 'label': '乙', 'caption': '重点值'}]
            yield case(f'order-color-summary-{direction}-{fraction}', [doc], p,
                       series=[{'name': 'actual', 'kind': 'bar', 'values': [row[1] for row in order],
                                'colors': ['#bd4f4f' if row[0] == '乙' else '#3066a3' for row in order]}],
                       texts=['执行率 50.00%', '执行率 60.00%', '执行率 62.50%'] + (['重点值 5.00元'] if fraction else []))
    for form in ['line', 'stacked-bar', 'barh']:
        rows = [['2026-01', '甲', 10], ['2026-01', '乙', 20], ['2026-02', '甲', 15]]
        doc = {'columns': ['period', 'category', 'value'], 'rows': rows, 'columnMeta': {'value': {'unit': '元'}}}
        yield case('long-gap-' + form, [doc], parameters(form, standard_value_fields=['value']),
                   'render' if form == 'line' else 'fallback',
                   **({'series': [{'name': '甲', 'kind': 'line', 'values': [10, 15]}, {'name': '乙', 'kind': 'line', 'values': [20, None]}]} if form == 'line' else {}))
    for layout in ['tight', 'constrained', 'manual']:
        for legend in ['inside', 'outside']:
            names = [f'系列{i}' for i in range(8)]
            doc = {'columns': ['label', *names], 'rows': [['甲', *range(1, 9)], ['乙', *range(2, 10)]], 'columnMeta': {name: {'unit': '元'} for name in names}}
            yield case(f'canvas-{layout}-{legend}', [doc], parameters(standard_canvas={'layout': layout, 'legendPosition': legend}),
                       'repair' if layout == 'manual' and legend == 'outside' else 'render')
    for fault in ['bool_auxiliary', 'null_auxiliary_meta', 'ratio_units', 'zero_denominator', 'missing_point', 'invalid_palette']:
        doc = {'columns': ['label', 'actual', 'budget'], 'rows': [['甲', 10, 20]], 'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
        p = parameters('barh', standard_value_fields=['actual'], standard_annotations=[{'kind': 'values', 'series': 'actual'}],
                       standard_presentation={'labelFormats': [{'field': 'budget'}]})
        if fault == 'bool_auxiliary':
            doc['rows'][0][2] = True
        elif fault == 'null_auxiliary_meta':
            doc['columnMeta']['budget'] = None
        elif fault == 'ratio_units':
            doc['columnMeta']['budget']['unit'] = '人次'
            p['standard_presentation']['labelFormats'] = [{'numerator': 'actual', 'denominator': 'budget'}]
        elif fault == 'zero_denominator':
            doc['rows'][0][2] = 0
            p['standard_presentation']['labelFormats'] = [{'numerator': 'actual', 'denominator': 'budget'}]
        elif fault == 'missing_point':
            p['standard_style'] = {'points': [{'series': 'actual', 'label': 'foreign', 'color': '#ff0000'}]}
        else:
            p['standard_style'] = {'palette': 'invented'}
        yield case('metadata-' + fault, [doc], p, 'schema' if fault == 'invalid_palette' else 'fallback')
    for count in [20, 30, 60]:
        doc = {'columns': ['label', 'actual'], 'rows': [[f'分类{i:02}', 100] for i in range(count)], 'columnMeta': {'actual': {'unit': '元'}}}
        yield case(f'annotations-flat-{count}', [doc], parameters(standard_annotations=[{'kind': 'values', 'series': 'actual'}]),
                   series=[{'name': 'actual', 'kind': 'line', 'values': [100] * count}])
    doc = {'columns': ['label', 'actual', 'budget'], 'rows': [[f'分类{i:02}', 100, 100] for i in range(60)],
           'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
    yield case('annotations-budget-exceeded', [doc], parameters(standard_annotations=[{'kind': 'values', 'series': name} for name in ['actual', 'budget']]), 'fallback')
    yield case('annotations-small-canvas', [doc], parameters(standard_value_fields=['actual'],
        standard_canvas={'sizeMode': 'fixed', 'width': 4, 'height': 3}, standard_style={'annotationFontSize': 16},
        standard_annotations=[{'kind': 'values', 'series': 'actual'}]), 'repair')
    unicode_docs = copy.deepcopy(documents)
    unicode_docs[0]['rows'] = [['院区é', 10]]
    unicode_docs[1]['rows'] = [['院区e\u0301', 20]]
    yield case('multisource-unicode-not-identical', unicode_docs, parameters(standard_sources=selections), 'fallback')
    for display in [None, '元']:
        doc = {'columns': ['label', 'actual'], 'rows': [['甲', 10], ['乙', 20]], 'columnMeta': {'actual': {'unit': '元/人次'}}}
        yield case('compound-unit-' + str(display), [doc], parameters(standard_display_unit=display), 'render' if display is None else 'fallback')
    for invalid_scale in [0, 'false']:
        doc = {'columns': ['label', 'actual'], 'rows': [['甲', .25]], 'columnMeta': {'actual': {'unit': '%', 'isPercent': invalid_scale}}}
        yield case(f'percentage-invalid-scale-{type(invalid_scale).__name__}', [doc], parameters(), 'fallback')
