"""五类静态图的冻结数据政策与有界 Matplotlib 几何。"""
from __future__ import annotations

import json
import math
from collections import deque

from ...units import unit_conversion_scale
from .standard_chart_encoding import fail, scaled_column
from .standard_chart_presentation import order_standard_rows, prepare_standard_presentation, valid_standard_metadata

FAMILY_FORMS = frozenset({'pie', 'donut', 'radar', 'funnel', 'sankey'})


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _registered_dimensions(container, key):
    dimensions = container.get(key, ())
    if (not isinstance(dimensions, (list, tuple))
            or any(not isinstance(field, str) or not field for field in dimensions)
            or len(set(dimensions)) != len(dimensions)):
        fail('standard_family_metadata_invalid', 'columnMeta.' + key, '冻结维度登记必须是唯一非空字段字符串数组。')
    return dimensions


def _table(document):
    columns, rows = document.get('columns'), document.get('rows')
    if (not isinstance(columns, list) or not columns or any(not isinstance(c, str) or not c for c in columns)
            or len(set(columns)) != len(columns) or not isinstance(rows, list) or not rows
            or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
        fail('standard_family_input_invalid', 'chartInputs', '冻结表格列或行结构无效。')
    metadata = document.get('columnMeta')
    if metadata is not None and (not isinstance(metadata, dict)
            or any(not isinstance(meta, dict) for meta in metadata.values())):
        fail('standard_family_metadata_invalid', 'columnMeta', '冻结列元数据必须为字段到登记对象的映射。')
    return columns, rows


def family_scalar_refs(chart, documents=()):
    """显式标量及冻结元数据中的共同分母均定位原始有序输入。"""
    refs = []
    composition = getattr(chart, 'standard_composition', None)
    if composition and composition.denominator.ref:
        refs.append(composition.denominator.ref)
    radar = getattr(chart, 'standard_radar', None)
    if radar:
        refs.extend(ref for scale in radar.scales for ref in (scale.minimum, scale.maximum))
    from .phase_models import StandardChartScalarRef
    selections = getattr(chart, 'standard_sources', ())
    sources = [(selection.source_index, selection.value_field) for selection in selections]
    if not sources and documents:
        selected = getattr(chart, 'standard_value_fields', ())
        encoding = getattr(chart, 'standard_encoding', None)
        if encoding and encoding.value_field:
            selected = (encoding.value_field,)
        if not selected:
            columns, rows = _table(documents[0])
            selected = [field for field in columns if all(_finite(row[columns.index(field)]) for row in rows)]
        sources = [(0, field) for field in selected]
    for index, field in sources:
        if index >= len(documents):
            continue
        document = documents[index]
        metadata = document.get('columnMeta') or {}
        if isinstance(metadata, dict):
            meta = metadata.get(field) or {}
            if isinstance(meta, dict) and meta.get('commonDenominator') is not None:
                refs.append(StandardChartScalarRef.model_validate(meta['commonDenominator']))
    return refs


def family_input_roles(chart, entries, files):
    """主辅来源分工只看显式引用，绝不按字段相似度重选主表。"""
    documents, identities = [], []
    for entry in entries:
        source = next((item for item in files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            fail('standard_input_identity_mismatch', 'chartInputs.sha256', '输入身份与登记不一致。')
        document = json.loads(source.content)
        if not isinstance(document, dict):
            fail('standard_family_input_invalid', 'chartInputs', '冻结来源必须为表格对象。')
        _table(document)
        documents.append(document)
        identities.append((source.path, source.sha256))
    selections = getattr(chart, 'standard_sources', ())
    main = {item.source_index for item in selections} if selections else {0}
    auxiliary = {ref.source_index for ref in family_scalar_refs(chart, documents)}
    sankey = getattr(chart, 'standard_sankey', None)
    if sankey and sankey.nodes:
        auxiliary.add(sankey.nodes.source_index)
    if any(index >= len(entries) for index in main | auxiliary):
        fail('standard_source_index_invalid', 'sourceIndex', '来源索引不在本图原始有序绑定内。')
    if main | auxiliary != set(range(len(entries))):
        fail('standard_source_unused', 'chartInputs', '本图有未被主表、标量或节点引用使用的冻结来源。')
    main_indices = sorted(main)
    remapped = tuple(item.model_copy(update={'source_index': main_indices.index(item.source_index)}) for item in selections)
    return documents, identities, [entries[i] for i in main_indices], remapped


def family_aligned_semantics(document, selections):
    """对齐仅映射明确来源标签维度；同名未登记维度不借壳授权。"""
    metadata = dict(document.get('columnMeta') or {})
    for selection in selections:
        meta = dict(metadata.get(selection.series_name) or {})
        semantic = dict(meta.get('measureSemantic', meta))
        registered = _registered_dimensions(semantic, 'additiveAcross')
        semantic['additiveAcross'] = ['period'] if selection.label_field in registered else []
        meta['measureSemantic'] = semantic
        if 'exclusiveAcross' in meta:
            meta['exclusiveAcross'] = ['period'] if selection.label_field in _registered_dimensions(meta, 'exclusiveAcross') else []
        metadata[selection.series_name] = meta
    return {**document, 'columnMeta': metadata}


def resolve_scalar(ref, documents):
    if ref.source_index >= len(documents):
        fail('standard_scalar_source_invalid', 'sourceIndex', '标量来源不在本图原始绑定中。')
    document = documents[ref.source_index]
    columns, rows = _table(document)
    if ref.field not in columns or ref.label_field is not None and ref.label_field not in columns:
        fail('standard_scalar_field_missing', 'standardScalarRef', '冻结标量字段或选择标签不存在。')
    if ref.label_field is not None:
        rows = [row for row in rows if row[columns.index(ref.label_field)] == ref.label]
    if len(rows) != 1:
        fail('standard_scalar_ambiguous', 'standardScalarRef', '冻结标量选择必须恰好命中一行，不按同值去重或取首行。')
    value = rows[0][columns.index(ref.field)]
    meta = (document.get('columnMeta') or {}).get(ref.field, {})
    if not _finite(value) or not valid_standard_metadata(meta) or not meta.get('unit'):
        fail('standard_scalar_invalid', 'standardScalarRef', '标量必须为有限非布尔数值且有登记单位。')
    return value, meta


def _convert(value, meta, unit):
    factor = unit_conversion_scale(meta['unit'], unit)
    if factor is None:
        fail('standard_family_unit_incompatible', 'columnMeta.unit', '冻结端点、分母或度量单位不兼容。')
    result = value * float(factor)
    if meta['unit'] == '%' and meta.get('isPercent') is False:
        result *= 100
    if not _finite(result) or value != 0 and result == 0:
        fail('standard_family_scale_unrepresentable', 'columnMeta.unit', '单位换算溢出或非零下溢，不能改变原值。')
    return result


def _additive(meta, dimensions, documents):
    semantic = meta.get('measureSemantic', meta)
    if not isinstance(semantic, dict):
        semantic = {}
    axes = _registered_dimensions(semantic, 'additiveAcross')
    if (semantic.get('aggregation') in {'sum', 'count'} and isinstance(axes, (list, tuple))
            and all(field in axes for field in dimensions) and meta.get('unit') != '%'):
        return
    # 百分比只有冻结共同基数、互斥维度和明确比例尺度时才可加。
    if (meta.get('unit') == '%' and isinstance(meta.get('isPercent'), bool)
            and meta.get('commonDenominator') is not None
            and isinstance(meta.get('exclusiveAcross'), (list, tuple))
            and all(field in meta['exclusiveAcross'] for field in dimensions)):
        from .phase_models import StandardChartScalarRef
        base, base_meta = resolve_scalar(StandardChartScalarRef.model_validate(meta['commonDenominator']), documents)
        if base > 0 and base_meta['unit'] != '%':
            return
    fail('standard_family_additivity_unproven', 'columnMeta.measureSemantic',
         '未登记本图维度的可加度量或同一冻结基数的互斥份额；同单位和百分号不能证明可加。')


def _warning(code, message, **details):
    return dict(code=code, message=message, **details)


def validate_family_parameters(chart):
    """规划和绘图共用无数据依赖的参数校验，便于在昂贵绘图前纠错。"""
    form = chart.standard_form
    if form not in FAMILY_FORMS:
        return
    _common_policy(chart, form, chart.standard_canvas, chart.standard_style,
                   chart.standard_presentation, chart.standard_axes)
    # 规划可省略整组并继承上一轮；完整来源必需性仍在绘图前检查。
    if form == 'sankey' and chart.standard_encoding is not None:
        _sankey_encoding(chart)


def _common_policy(chart, form, canvas, style, presentation, axes):
    if (axes.mode != 'single' or axes.scale != 'linear' or axes.right_fields
            or axes.right_display_unit or axes.zoom_start or axes.zoom_end or axes.panel_limit
            or axes.zero_baseline or axes.allow_nulls
            or getattr(chart, 'standard_domains', None) or getattr(chart, 'standard_break', None)
            or getattr(chart, 'standard_pagination', None) or getattr(chart, 'standard_bands', ())
            or getattr(chart, 'standard_total_field', None) or getattr(chart, 'standard_label_fields', ())
            or presentation.label_formats or presentation.summaries):
        fail('standard_family_combination_unsupported', 'standardChart', '此图族不支持笛卡尔多轴、断轴、域、分页、范围带或辅助摘要组合。')
    supported_axes = {'left_display_unit'}
    defaults = type(axes)().model_dump()
    if any(value != defaults[key] for key,value in axes.model_dump().items() if key not in supported_axes):
        fail('standard_family_axes_unsupported', 'standardAxes', '此图族不支持非默认笛卡尔坐标参数。')
    for field, forms in [('standard_composition', {'pie','donut'}), ('standard_radar', {'radar'}),
                         ('standard_funnel', {'funnel'}), ('standard_sankey', {'sankey'})]:
        if getattr(chart, field, None) is not None and form not in forms:
            fail('standard_family_form_conflict', field, '图族专用参数与机器类型不匹配。')
    if form != 'sankey' and getattr(chart, 'standard_encoding', None):
        fail('standard_family_encoding_conflict', 'standardEncoding', '该图族不使用散点/热力字段编码。')
    if any(item.geometry != 'auto' for item in style.series):
        fail('standard_family_style_unsupported', 'standardStyle.series.geometry', '不能用柱线样式替换本图族几何。')
    # 每项非默认外观必须有真实消费方，不能因共享schema接受而承诺无效参数。
    supported_style = {'palette','theme','series','points','background','title_font_size','annotation_font_size'}
    if form != 'sankey':
        supported_style.add('decimals')
    if form in {'pie','donut','radar'}:
        supported_style.update({'legend_columns','legend_font_size','legend_location'})
    if form == 'radar':
        supported_style.update({'grid','grid_alpha'})
    defaults = type(style)().model_dump()
    ignored = [key for key,value in style.model_dump().items()
               if key not in supported_style and value != defaults[key]
               and not (key == 'grid' and value == 'none')]
    if ignored:
        fail('standard_family_style_unsupported', 'standardStyle.' + ignored[0], '该图族未实现此非默认外观参数，不能静默忽略。')
    canvas_defaults = type(canvas)().model_dump()
    if canvas.max_category_ticks != canvas_defaults['max_category_ticks']:
        fail('standard_family_canvas_unsupported', 'standardCanvas.maxCategoryTicks', '该图族不使用笛卡尔类别刻度抽稀。')
    if form in {'funnel','sankey'} and canvas.legend_position != 'auto':
        fail('standard_family_canvas_unsupported', 'standardCanvas.legendPosition', '该图族没有图例，不能指定图例位置。')
    for item in style.series:
        if form != 'radar' and (item.line_style != '-' or item.line_width != 2 or item.marker != 'o' or item.marker_size != 5):
            fail('standard_family_style_unsupported', 'standardStyle.series', '非雷达图不支持线型或点型参数，不能静默忽略。')
        if item.label is not None:
            fail('standard_family_style_unsupported', 'standardStyle.series.label', '该图族保留原始实体/阶段/节点名称，不能用系列别名替换。')
        if form == 'radar' and item.hatch:
            fail('standard_family_style_unsupported', 'standardStyle.series.hatch', '雷达线不支持柱纹理参数。')
    if form in {'pie','donut','sankey'} and style.grid not in {'none','y'}:
        fail('standard_family_style_unsupported', 'standardStyle.grid', '非坐标图不支持显式笛卡尔网格方向。')
    annotations = getattr(chart, 'standard_annotations', ())
    if any(item.kind != 'values' or item.label or item.end_label or item.row_label or item.end_row_label for item in annotations):
        fail('standard_family_annotation_unsupported', 'standardAnnotations', '此图族目前只支持绑定原值标注，其他标注不可忽略。')
    for item in annotations:
        if item.caption is not None or item.color is not None or item.highlight or item.position != 'auto':
            fail('standard_family_annotation_unsupported', 'standardAnnotations', '图族值标注暂不支持自定义标题、颜色、重点或位置。')
    if any(point.marker_size != 8 for point in style.points):
        fail('standard_family_style_unsupported', 'standardStyle.points.markerSize', '扇区/阶段不是点标记，不支持markerSize。')
    policy = canvas.model_dump()
    policy.update(style=style.model_dump(), special_form=form, total_field=None, zero_baseline=False,
                  annotation_specs=[], categorical_x=False, categorical_y=form == 'funnel')
    return policy


def _display_rows(chart, document, label, presentation, form):
    columns, rows = _table(document)
    if label not in columns:
        fail('standard_family_label_missing', 'standardLabelField', '图族需要明确冻结类别/阶段/实体字段。')
    labels = [row[columns.index(label)] for row in rows]
    if any(not isinstance(value, str) or not value for value in labels) or len(set(labels)) != len(labels):
        fail('standard_family_labels_invalid', 'standardLabelField', '类别必须为唯一非空冻结字符串。')
    order = presentation.order
    selected = getattr(chart, 'standard_labels', ())
    # 完整唯一实体清单不构成筛选，仍按冻结输入顺序显示；子集不能借此删行。
    filters_rows = bool(selected) and (len(selected) != len(labels) or set(selected) != set(labels))
    if form == 'funnel' and (filters_rows or order.mode not in {'source','explicit'} or order.limit is not None or order.exclude_missing):
        fail('standard_funnel_order_invalid', 'standardPresentation.order', '漏斗只支持原序或完整explicit阶段顺序，不能排序/TopN/删阶段。')
    if form == 'radar' and (filters_rows or order.limit is not None or order.exclude_missing or order.mode in {'value','max_abs'}):
        fail('standard_radar_selection_unsupported', 'standardPresentation.order', '雷达不能隐式截断实体，超容量应整图诊断。')
    if selected:
        if len(set(selected)) != len(selected) or not set(selected).issubset(labels):
            fail('standard_family_selection_invalid', 'standardLabels', '展示类别必须唯一且存在于完整绑定中。')
        document = {**document, 'rows': [row for row in rows if row[columns.index(label)] in selected]}
    ordered = order_standard_rows(document, label, order)
    if ordered is None:
        fail('standard_family_order_invalid', 'standardPresentation.order', '展示排序声明无效。')
    return ordered


def _measure_fields(chart, document, label):
    columns, rows = _table(document)
    selected = list(getattr(chart, 'standard_value_fields', ()))
    if not selected:
        selected = [field for field in columns if field != label and all(_finite(row[columns.index(field)]) for row in rows)]
    if not selected or len(set(selected)) != len(selected) or not set(selected).issubset(columns):
        fail('standard_family_fields_invalid', 'standardValueFields', '度量选择必须唯一且引用现有冻结字段。')
    return selected


def prepare_family_chart(chart, document, original, form, canvas, style, presentation, axes, documents):
    policy = _common_policy(chart, form, canvas, style, presentation, axes)
    if form in {'pie','donut','sankey'}:
        views = [getattr(chart, 'standard_view', None)]
        views.extend(getattr(step, 'view', None) for step in getattr(chart, 'standard_steps', ()))
        derivations = list(getattr(chart, 'standard_derivations', ()))
        derivations.extend(getattr(step, 'derivation', None) for step in getattr(chart, 'standard_steps', ()))
        if any(view and view.kind == 'group' and view.aggregation != 'sum' for view in views) or any(derivations):
            fail('standard_family_additivity_unproven', 'standardSteps/standardView',
                 '均值/派生结果不能沿用原列可加登记；须有该结果本身的共同基数或可加事实依据。')
    if form == 'sankey':
        return _prepare_sankey(chart, document, original, policy, presentation, axes, documents)
    label = getattr(chart, 'standard_label_field', None)
    columns, rows = _table(document)
    if label is None:
        candidates = [c for c in columns if all(isinstance(r[columns.index(c)], str) for r in rows)]
        label = candidates[0] if len(candidates) == 1 else None
    fields = _measure_fields(chart, document, label)
    # 单行宽表按显式字段顺序重排，沿用 summary-bars 的确定性投影。
    if form == 'funnel' and label is None and len(rows) == 1 and len(fields) >= 2:
        meta = document.get('columnMeta') or {}
        first = meta.get(fields[0], {})
        values = []
        for field in fields:
            raw = rows[0][columns.index(field)]
            current = meta.get(field, {})
            if not _finite(raw) or not valid_standard_metadata(current) or not current.get('unit'):
                fail('standard_funnel_values_invalid', 'standardValueFields', '宽表阶段须为有单位的有限原值。')
            values.append([field, _convert(raw, current, first.get('unit'))])
        # _convert 已输出百分数坐标，投影元数据必须同步，避免下游重复乘100。
        projected_meta = {**first, **({'isPercent': True} if first.get('unit') == '%' else {})}
        document = {'columns': ['label','value'], 'rows': values, 'columnMeta': {'value': projected_meta}}
        label, fields = 'label', ['value']
    full = document
    document = _display_rows(chart, document, label, presentation, form)
    labels = [row[document['columns'].index(label)] for row in document['rows']]
    if len(labels) > (8 if form == 'radar' else 60):
        fail('standard_family_capacity_exceeded', 'standardLabelField', '实体/类别超过图族预算，不能截断。')
    display = getattr(chart, 'standard_display_unit', None) or axes.left_display_unit
    if axes.left_display_unit and getattr(chart, 'standard_display_unit', None) not in (None, axes.left_display_unit):
        fail('standard_family_unit_conflict', 'standardDisplayUnit', '重复显示单位不一致。')
    warnings, notes = [], []
    family = {}
    if form in {'pie','donut','funnel'}:
        if len(fields) != 1:
            fail('standard_family_single_value_required', 'standardValueFields', '构成/长表漏斗必须且只能选择一个冻结度量。')
        field = fields[0]
        values, value_meta = scaled_column(document, field, display, False)
        full_values, _ = scaled_column(full, field, display, False)
        if any(value < 0 for value in full_values):
            fail('standard_family_negative_value', field, '该图族不接受负值，不取绝对值或截零。')
        unit = value_meta['unit']
        meta = (full.get('columnMeta') or {}).get(field, {})
        family.update(values=values, unit=unit, field=field)
        if form in {'pie','donut'}:
            _additive(meta, [label], documents)
            composition = getattr(chart, 'standard_composition', None)
            denominator_spec = composition.denominator if composition else None
            if denominator_spec is None or denominator_spec.mode == 'bound_sum':
                denominator = math.fsum(full_values)
                notes.append('占绑定范围合计（展示筛选前）')
            else:
                denominator, denominator_meta = resolve_scalar(denominator_spec.ref, documents)
                denominator = _convert(denominator, denominator_meta, unit)
                for key in ('periods', 'scope'):
                    if meta.get(key) is not None and denominator_meta.get(key) is not None and meta[key] != denominator_meta[key]:
                        warnings.append(_warning('standard_composition_denominator_scope_mismatch',
                            '分项与冻结分母登记期间/作用域不一致，保留原值但不能据此证明业务构成关系。', metadataField=key))
                if not all(meta.get(key) is not None and denominator_meta.get(key) is not None for key in ('periods','scope')):
                    warnings.append(_warning('standard_composition_coverage_unproven', '独立冻结分母与分项的完整业务覆盖关系尚未证明。'))
                notes.append('占独立冻结分母；业务覆盖关系以登记依据为准')
            visible_sum = math.fsum(values)
            if not _finite(denominator) or denominator <= 0 or visible_sum > denominator and not math.isclose(visible_sum, denominator, rel_tol=1e-12):
                fail('standard_composition_denominator_invalid', 'standardComposition.denominator', '分母必须为正且不小于可见类别合计，不能重新归一化。')
            family.update(denominator=denominator)
            angle = 90.0
            for value in values:
                stop = angle + value / denominator * 360
                if value > 0 and (stop == angle or abs(stop-angle) < math.ulp(360.0)):
                    fail('standard_composition_angle_unrepresentable', 'standardComposition',
                         '非零类别角度小于浮点几何可表达范围，不能当零扇区。')
                angle = stop
            if visible_sum < denominator:
                notes.append(f'可见覆盖 {visible_sum / denominator * 100:.2f}%；留空为未展示范围，不称其他')
        else:
            spec = getattr(chart, 'standard_funnel', None)
            family['ratio_base'] = spec.ratio_base if spec else 'none'
            if any(right > left for left, right in zip(values, values[1:])):
                warnings.append(_warning('standard_funnel_nonmonotonic', '阶段值非单调，不据此断言转化损耗。'))
            notes.append('按冻结阶段原值显示；阶段值比不代表已证明的同队列转化率')
    else:
        if not 3 <= len(fields) <= 8:
            fail('standard_radar_axis_capacity', 'standardValueFields', '雷达必须显式保留3–8个轴，不能截轴。')
        metas = (document.get('columnMeta') or {})
        units = [metas.get(field, {}).get('unit') for field in fields]
        if not all(units):
            fail('standard_radar_unit_missing', 'columnMeta', '雷达每轴必须有登记单位。')
        spec = getattr(chart, 'standard_radar', None)
        scales = spec.scales if spec else ()
        if scales and (len(scales) != len(fields) or len({s.field for s in scales}) != len(scales) or {s.field for s in scales} != set(fields)):
            fail('standard_radar_scale_axes_invalid', 'standardRadar.scales', '显式尺度必须逐轴恰好绑定一次。')
        raw_columns, coordinates, axis_units, endpoints = [], [], [], []
        base_unit = display or units[0]
        if not scales and any(unit_conversion_scale(unit, base_unit) is None for unit in units):
            fail('standard_radar_scales_required', 'standardRadar.scales', '异量纲雷达必须提供全部轴的冻结min/max。')
        for field, unit in zip(fields, units):
            shown_unit = display or (unit if scales else base_unit)
            values, _ = scaled_column(document, field, shown_unit, False)
            raw_columns.append(values)
            axis_units.append(shown_unit)
            if scales:
                scale = next(s for s in scales if s.field == field)
                lo, lo_meta = resolve_scalar(scale.minimum, documents)
                hi, hi_meta = resolve_scalar(scale.maximum, documents)
                lo, hi = _convert(lo, lo_meta, shown_unit), _convert(hi, hi_meta, shown_unit)
                if lo >= hi or not math.isfinite(hi-lo):
                    fail('standard_radar_scale_invalid', 'standardRadar.scales', '冻结尺度须min<max且可表达。')
                if any(value < lo or value > hi for value in values):
                    fail('standard_radar_out_of_range', 'standardRadar.scales', '原值超出冻结尺度，不能裁切或夹值。')
                coordinates.append([(v-lo)/(hi-lo) for v in values])
                endpoints.append((lo, hi))
            else:
                if any(v < 0 for v in values):
                    fail('standard_radar_negative_radius', 'standardRadar.scales', '负径向原值必须通过冻结min/max显式映射，不能abs或默移原点。')
                coordinates.append(values)
        family.update(fields=fields, raw=[list(row) for row in zip(*raw_columns)],
                      coordinates=[list(row) for row in zip(*coordinates)], units=axis_units, endpoints=endpoints)
        if scales:
            notes.append('径向为冻结min/max线性映射坐标，非原值/综合评分；' + '；'.join(f'{f} [{lo:g}, {hi:g}]{u}' for f,(lo,hi),u in zip(fields,endpoints,axis_units)))
        else:
            notes.append('共享登记原值径向尺度，不据此宣称综合优劣')
    names = labels if form == 'radar' else fields
    for item in style.series:
        if item.series not in names:
            fail('standard_family_style_unknown', 'standardStyle.series', '系列样式必须引用实际绑定系列/雷达实体。')
    for point in style.points:
        if form == 'radar' or point.series not in names or point.label not in labels:
            fail('standard_family_point_unsupported', 'standardStyle.points', '逐点样式必须绑定当前可见的冻结类别；雷达不支持逐点颜色。')
    for annotation in getattr(chart, 'standard_annotations', ()):
        if annotation.series not in (None, *fields):
            fail('standard_family_annotation_field_invalid', 'standardAnnotations', '标注必须引用当前冻结度量。')
    prepared = prepare_standard_presentation(presentation, document, original, label, names, labels)
    if prepared is None:
        fail('standard_family_presentation_invalid', 'standardPresentation', '该图族标签展示参数无效。')
    prepared['source_note'] = '\n'.join([*([prepared['source_note']] if prepared['source_note'] else []), *notes])
    policy.update(family=family, labels=labels, series_names=names, presentation=prepared)
    return policy, warnings


FAMILY_DISPATCH = '''    if form in {"pie", "donut", "radar", "funnel", "sankey"}:
        render_family_chart(payload, canvas, form, title, output_path)
        continue
'''


FAMILY_SCRIPT = '''def finish_family_layout(fig, ax, policy, title):
    style = policy["style"]
    fig.set_facecolor(style["background"])
    ax.set_facecolor(style["background"])
    ax.set_title(title)
    finish_standard_presentation(fig, policy)
    for text in ax.texts:
        text.set_fontsize(style["annotation_font_size"])
    for tick in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        tick.set_fontsize(policy["tick_font_size"])
    legend = ax.get_legend()
    if legend is not None:
        for text in legend.get_texts():
            text.set_fontsize(style["legend_font_size"])
            text.set_text(standard_wrap(text.get_text(), policy["label_wrap"]))
        if policy["legend_position"] == "outside":
            legend.set_bbox_to_anchor((1.01, 1))
            legend.set_loc("upper left")
    if policy["layout"] == "manual":
        fig.subplots_adjust(left=policy["left"],right=policy["right"],bottom=policy["bottom"],top=policy["top"])
    elif policy["layout"] == "tight":
        fig.tight_layout(pad=max(.7,policy["padding"]),rect=(.02,policy["presentation"]["footer_top"],.98,policy["presentation"]["header_bottom"]))
    else:
        fig.get_layout_engine().set(rect=(.02,policy["presentation"]["footer_top"],.96,policy["presentation"]["header_bottom"]-policy["presentation"]["footer_top"]))
    fig.canvas.draw()
    if legend is not None and policy["crop"] == "canvas":
        bounds=legend.get_window_extent(fig.canvas.get_renderer())
        if bounds.x0<0 or bounds.y0<0 or bounds.x1>fig.bbox.width or bounds.y1>fig.bbox.height:
            raise ValueError("standard_chart_layout_unresolved: 图族图例超出画布")
    if policy["crop"] == "canvas":
        renderer=fig.canvas.get_renderer()
        for text in [*fig.texts, *[text for axis in fig.axes for text in axis.texts]]:
            bounds=text.get_window_extent(renderer)
            if bounds.x0<0 or bounds.y0<0 or bounds.x1>fig.bbox.width or bounds.y1>fig.bbox.height:
                raise ValueError("standard_chart_layout_unresolved: 图族说明/原值文字超出画布，请扩大画布或保留来源诊断")

def family_point_color(policy, field, label, index):
    import matplotlib.pyplot as plt
    for point in policy["style"]["points"]:
        if point["series"] == field and point["label"] == label:
            return point["color"]
    for item in policy["style"]["series"]:
        if item["series"] == field and item["color"]:
            return item["color"]
    palette=policy["style"]["palette"]
    if palette=="report":
        return ["#3066a3","#dc884d","#36856b","#b55d68","#8573a6","#58a3ae","#b49b53","#718096"][index%8]
    cmap=plt.get_cmap(palette)
    return cmap(index/max(1,len(policy["labels"])-1) if cmap.N>20 else index)

def render_family_chart(payload, policy, form, title, output_path):
    import math
    import matplotlib.pyplot as plt
    from matplotlib.patches import Wedge, Rectangle, PathPatch
    from matplotlib.path import Path
    data=policy["family"]
    style=policy["style"]
    precision=style["decimals"]
    options=create_standard_canvas(policy, policy["labels"], form)
    fig=plt.figure(**options)
    ax=fig.add_subplot(111,projection="polar" if form=="radar" else None)
    labels=policy["presentation"]["display_labels"]
    if form in {"pie","donut"}:
        start=90.0
        wedges=[]
        for index,(label,value) in enumerate(zip(policy["labels"],data["values"])):
            angle=value/data["denominator"]*360
            color=family_point_color(policy,data["field"],label,index)
            override=next((item for item in style["series"] if item["series"]==data["field"]),{})
            wedge=Wedge((0,0),1,start,start+angle,width=.35 if form=="donut" else None,facecolor=color,edgecolor=style["background"],linewidth=1,alpha=override.get("alpha",1),hatch=override.get("hatch",""))
            wedge.set_gid("category:"+label)
            ax.add_patch(wedge)
            wedges.append(wedge)
            start+=angle
        ax.set_aspect("equal")
        ax.set_xlim(-1.15,1.15)
        ax.set_ylim(-1.15,1.15)
        ax.axis("off")
        location=style["legend_location"] if style["legend_location"]!="auto" else "upper left"
        texts=[f"{label} · {format_standard_number(value,precision)}{data['unit']} · {value/data['denominator']*100:.2f}%" for label,value in zip(labels,data["values"])]
        legend_options={} if policy["legend_position"]=="inside" else dict(bbox_to_anchor=(1.0,1.0))
        ax.legend(wedges,texts,loc=location,frameon=False,ncols=style["legend_columns"],**legend_options)
    elif form=="radar":
        count=len(data["fields"])
        angles=[i*2*math.pi/count for i in range(count)]
        for index,(label,values,raw) in enumerate(zip(labels,data["coordinates"],data["raw"])):
            color=family_point_color(policy,policy["labels"][index],policy["labels"][index],index)
            override=next((item for item in style["series"] if item["series"]==policy["labels"][index]),{})
            ax.plot([*angles,angles[0]],[*values,values[0]],label=override.get("label") or label,color=color,linewidth=override.get("line_width",2),linestyle=override.get("line_style","-"),marker=override.get("marker","o"),markersize=override.get("marker_size",5),alpha=override.get("alpha",1))
            ax.fill([*angles,angles[0]],[*values,values[0]],color=color,alpha=.08)
            for angle,radius,value,unit in zip(angles,values,raw,data["units"]):
                ax.text(angle,radius,format_standard_number(value,precision)+unit,color=color,ha="center",va="bottom")
        ax.set_xticks(angles,[standard_wrap(f"{field}（{unit}）",policy["label_wrap"]) for field,unit in zip(data["fields"],data["units"])])
        ax.set_ylim(0,1 if data["endpoints"] else max(1,max(v for row in data["coordinates"] for v in row))*1.1)
        ax.grid(False)
        if style["grid"] in {"x","both"}:
            ax.xaxis.grid(True,alpha=style["grid_alpha"])
        if style["grid"] in {"y","both"}:
            ax.yaxis.grid(True,alpha=style["grid_alpha"])
        ax.legend(loc=style["legend_location"] if style["legend_location"]!="auto" else "upper right",frameon=False,ncols=style["legend_columns"])
    elif form=="funnel":
        maximum=max(data["values"],default=0)
        for index,(label,value) in enumerate(zip(policy["labels"],data["values"])):
            color=family_point_color(policy,data["field"],label,index)
            override=next((item for item in style["series"] if item["series"]==data["field"]),{})
            bar=Rectangle((-value/2,index-.32),value,.64,facecolor=color,alpha=override.get("alpha",1),hatch=override.get("hatch",""))
            bar.set_gid("stage:"+label)
            ax.add_patch(bar)
            text=format_standard_number(value,precision)+data["unit"]
            base=(data["values"][0] if data["ratio_base"]=="first" else data["values"][index-1] if index else None)
            if data["ratio_base"]!="none":
                text+=" · 阶段值比 "+("未定义（无前阶段）" if base is None else "未定义（分母为零）" if base==0 else f"{value/base*100:.2f}%")
            ax.text(maximum*.55 if maximum else .1,index,text,va="center",ha="left",color="#334155")
        ax.set_yticks(range(len(labels)),[standard_wrap(label,policy["label_wrap"]) for label in labels])
        ax.set_ylim(len(labels)-.5,-.5)
        ax.set_xlim(-maximum*.65 if maximum else -1,maximum*1.5 if maximum else 1)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        nodes=data["nodes"]
        edges=data["edges"]
        levels=data["stages"]
        heights={node:max(data["inflows"][node],data["outflows"][node]) for node in nodes}
        layer_totals=[sum(heights[n] for n in nodes if levels[n]==stage) for stage in sorted(set(levels.values()))]
        gap=max(max(layer_totals,default=0)*.12,1)
        cursor={stage:0.0 for stage in set(levels.values())}
        positions={}
        for node in nodes:
            stage=levels[node]
            positions[node]=(stage*3.0,cursor[stage])
            cursor[stage]+=heights[node]+gap
        top=max(cursor.values(),default=gap)
        if not data["positive"]:
            ax.text(.02,.96,"无正流量：全部冻结边为零",transform=ax.transAxes,ha="left",va="top",fontsize=12)
            lines=[data["node_labels"][s]+" → "+data["node_labels"][t]+"：0"+data["unit"] for s,t,_ in edges]
            ax.text(.02,.85,standard_wrap("；".join(lines),max(30,int(policy["width"]*6))),transform=ax.transAxes,ha="left",va="top")
        else:
            source_slots={node:positions[node][1] for node in nodes}
            target_slots=source_slots.copy()
            zero=[]
            for index,(source,target,value) in enumerate(edges):
                if value==0:
                    zero.append(data["node_labels"][source]+" → "+data["node_labels"][target]+"：0"+data["unit"])
                    continue
                sx=positions[source][0]+.25
                tx=positions[target][0]
                sy,ty=source_slots[source],target_slots[target]
                if sy+value==sy or ty+value==ty:
                    raise ValueError("standard_sankey_slot_unrepresentable: 非零流宽下溢，不能补正宽")
                source_slots[source]+=value
                target_slots[target]+=value
                if levels[target]-levels[source]>1:
                    # x(t)严格单调；由最靠近两端的中间节点反解t，保证整段下边界高于全部节点。
                    middle=[node for node in nodes if levels[source]<levels[node]<levels[target]]
                    def parameter_at(x):
                        left,right=0.0,1.0
                        for _ in range(64):
                            t=(left+right)/2
                            u=1-t
                            current=u*u*u*sx+3*u*u*t*(sx+.15)+3*u*t*t*(tx-.15)+t*t*t*tx
                            if current<x:
                                left=t
                            else:
                                right=t
                        return (left+right)/2
                    first=parameter_at(min(positions[node][0] for node in middle))
                    last=parameter_at(max(positions[node][0]+.25 for node in middle))
                    coefficient=3*min(first*(1-first),last*(1-last))
                    floor=min(sy,ty)
                    control=floor+(top+gap-floor)/coefficient
                    c1,c2=(sx+.15,control),(tx-.15,control)
                else:
                    c1,c2=((sx+tx)/2,sy),((sx+tx)/2,ty)
                vertices=[(sx,sy),c1,c2,(tx,ty),(tx,ty+value),(c2[0],c2[1]+value),(c1[0],c1[1]+value),(sx,sy+value),(sx,sy)]
                codes=[Path.MOVETO,Path.CURVE4,Path.CURVE4,Path.CURVE4,Path.LINETO,Path.CURVE4,Path.CURVE4,Path.CURVE4,Path.CLOSEPOLY]
                override=next((item for item in style["series"] if item["series"]==policy["series_names"][0]),{})
                patch=PathPatch(Path(vertices,codes),facecolor=family_point_color(policy,policy["series_names"][0],source,index),edgecolor="none",alpha=.55*override.get("alpha",1),hatch=override.get("hatch",""))
                if levels[target]-levels[source]>1:
                    from matplotlib.transforms import Bbox
                    if any(heights[node]>0 and patch.get_path().intersects_bbox(Bbox.from_bounds(*positions[node],.25,heights[node]),filled=True) for node in middle):
                        raise ValueError("standard_sankey_route_unrepresentable: 跨层路径无法避让中间节点，保留原边诊断")
                patch.set_gid("edge:"+str(index))
                ax.add_patch(patch)
            for index,node in enumerate(nodes):
                x,y=positions[node]
                height=heights[node]
                label=standard_wrap(data["node_labels"][node],policy["label_wrap"])
                if height>0:
                    rectangle=Rectangle((x,y),.25,height,facecolor=family_point_color(policy,policy["series_names"][0],node,index),edgecolor="white",linewidth=.5)
                    rectangle.set_gid("node:"+node)
                    ax.add_patch(rectangle)
                    ax.text(x+.125,y+height/2,label,ha="center",va="center",zorder=5,bbox=dict(fc="white",ec="none",alpha=.8,pad=1))
                else:
                    ax.text(x,y,label+"（零流量）",ha="left",va="center")
            if zero:
                ax.text(.01,.01,standard_wrap("零边："+"；".join(zero),max(30,int(policy["width"]*6))),transform=ax.transAxes,ha="left",va="bottom")
            ax.autoscale_view()
            ax.margins(x=.08,y=.1)
        ax.axis("off")
    finish_family_layout(fig,ax,policy,title)
    save_standard_canvas(fig,output_path,policy)
    plt.close(fig)
'''


def _sankey_encoding(chart):
    encoding = getattr(chart, 'standard_encoding', None)
    if encoding is None or not encoding.value_field:
        fail('standard_sankey_encoding_required', 'standardEncoding', '桑基必须显式绑定source/target/value。')
    allowed = {'x_field','y_field','value_field'}
    defaults = type(encoding).model_construct(x_field=encoding.x_field, y_field=encoding.y_field, value_field=encoding.value_field)
    if any(v != defaults.model_dump()[k] for k,v in encoding.model_dump().items() if k not in allowed):
        fail('standard_sankey_encoding_unsupported', 'standardEncoding', '桑基不使用颜色/大小/热力或坐标变换编码。')
    return encoding


def _prepare_sankey(chart, document, original, policy, presentation, axes, documents):
    encoding = _sankey_encoding(chart)
    if (getattr(chart, 'standard_labels', ()) or presentation.order.mode != 'source'
            or presentation.order.limit is not None or presentation.order.exclude_missing or presentation.label_mode != 'source'):
        fail('standard_sankey_order_unsupported', 'standardPresentation.order', '桑基必须保留全部冻结边及首次出现顺序。')
    columns, rows = _table(document)
    fields = [encoding.x_field, encoding.y_field, encoding.value_field]
    if len(set(fields)) != 3 or not set(fields).issubset(columns):
        fail('standard_sankey_fields_invalid', 'standardEncoding', 'source/target/value必须绑定三个不同冻结字段。')
    selected = getattr(chart, 'standard_value_fields', ())
    if selected and tuple(selected) != (encoding.value_field,):
        fail('standard_sankey_selection_conflict', 'standardValueFields', '桑基只选择显式weight字段。')
    display = getattr(chart, 'standard_display_unit', None) or axes.left_display_unit
    values, value_meta = scaled_column(document, encoding.value_field, display, False)
    if any(value < 0 for value in values):
        fail('standard_sankey_negative_weight', 'standardEncoding.valueField', '负流量不能自动反转方向。')
    _additive((document.get('columnMeta') or {}).get(encoding.value_field, {}), fields[:2], documents)
    edges = []
    order = []
    for row, value in zip(rows, values):
        source, target = row[columns.index(fields[0])], row[columns.index(fields[1])]
        if any(not isinstance(node, str) or not node for node in (source,target)):
            fail('standard_sankey_node_invalid', 'standardEncoding', '节点ID必须为冻结非空字符串。')
        if source == target:
            fail('standard_sankey_cycle', 'standardEncoding', '自环不属于DAG模板，保留原边并给诊断。')
        for node in (source,target):
            if node not in order:
                order.append(node)
        edges.append((source,target,value))
    if len(order) > 60 or len(edges) > 480:
        fail('standard_sankey_capacity', 'standardEncoding', '桑基最多60节点/480边，不能截边。')
    incoming = {node: [] for node in order}
    outgoing = {node: [] for node in order}
    for index,(source,target,value) in enumerate(edges):
        outgoing[source].append(index)
        incoming[target].append(index)
    degrees = {node:len(incoming[node]) for node in order}
    queue = deque(node for node in order if not degrees[node])
    stages = {node:0 for node in order}
    visited = []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for index in outgoing[node]:
            target = edges[index][1]
            stages[target] = max(stages[target],stages[node]+1)
            degrees[target] -= 1
            if not degrees[target]:
                queue.append(target)
    if len(visited) != len(order):
        fail('standard_sankey_cycle', 'standardEncoding', '全部边（含零权边）存在环，不能删边修复。')
    labels = {node:node for node in order}
    spec = getattr(chart, 'standard_sankey', None)
    if spec and spec.nodes:
        nodes = spec.nodes
        nc,nr = _table(documents[nodes.source_index])
        required = [nodes.id_field, *([nodes.label_field] if nodes.label_field else []), *([nodes.stage_field] if nodes.stage_field else [])]
        if not set(required).issubset(nc):
            fail('standard_sankey_node_fields_missing', 'standardSankey.nodes', '辅助节点字段不存在。')
        identifiers = [row[nc.index(nodes.id_field)] for row in nr]
        if any(not isinstance(i,str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers) or set(identifiers) != set(order):
            fail('standard_sankey_node_coverage_invalid', 'standardSankey.nodes', '节点ID必须唯一且恰好覆盖全部原始端点。')
        for node,row in zip(identifiers,nr):
            if nodes.label_field:
                name = row[nc.index(nodes.label_field)]
                if not isinstance(name,str) or not name:
                    fail('standard_sankey_label_invalid', 'standardSankey.nodes.labelField', '节点显示名须为冻结非空文本。')
                labels[node] = name
            if nodes.stage_field:
                stage = row[nc.index(nodes.stage_field)]
                if not isinstance(stage,int) or isinstance(stage,bool) or stage < 0:
                    fail('standard_sankey_stage_invalid', 'standardSankey.nodes.stageField', 'stage必须为非布尔非负整数。')
                stages[node] = stage
        if nodes.stage_field and any(stages[s] >= stages[t] for s,t,_ in edges):
            fail('standard_sankey_stage_order_invalid', 'standardSankey.nodes.stageField', '每条边必须从较小stage流向较大stage。')
    # 稀疏层号压为等距展示层，不冒充时间距离。
    levels = {stage:i for i,stage in enumerate(sorted(set(stages.values())))}
    stages = {node:levels[stage] for node,stage in stages.items()}
    ins = {n:math.fsum(edges[i][2] for i in incoming[n]) for n in order}
    outs = {n:math.fsum(edges[i][2] for i in outgoing[n]) for n in order}
    if any(not math.isfinite(v) for v in [*ins.values(),*outs.values()]):
        fail('standard_sankey_overflow', 'standardEncoding.valueField', '汇合/分叉总流量溢出。')
    warnings = [_warning('standard_sankey_imbalance', '中间节点流入流出不相等；留白不补虚拟流。', nodeId=n, inflow=ins[n], outflow=outs[n], delta=ins[n]-outs[n])
                for n in order if incoming[n] and outgoing[n] and not math.isclose(ins[n],outs[n],rel_tol=1e-12,abs_tol=1e-12)]
    positive = any(v > 0 for v in values)
    if not positive:
        warnings.append(_warning('standard_sankey_no_positive_flow', '全部冻结边为零；保留节点和零边文字，不画伪正流量。'))
    for item in policy['style']['series']:
        if item['series'] != encoding.value_field:
            fail('standard_sankey_style_invalid', 'standardStyle.series', '桑基系列样式只能引用冻结权重字段。')
    if policy['style']['points'] or getattr(chart, 'standard_annotations', ()):
        fail('standard_sankey_annotation_unsupported', 'standardAnnotations/standardStyle.points', '桑基暂不支持逐类别点样式或笛卡尔值标注。')
    prepared = prepare_standard_presentation(presentation, document, original, None, [encoding.value_field], order)
    if prepared is None:
        fail('standard_sankey_presentation_invalid', 'standardPresentation', '桑基展示参数无效。')
    notes = ['所有原始边独立保留；统一流宽；节点高度=max(流入,流出)，空白非损耗/外部流']
    notes.extend(w['message'] for w in warnings)
    prepared['source_note'] = '\n'.join([*([prepared['source_note']] if prepared['source_note'] else []), *notes])
    policy.update(family=dict(edges=edges, nodes=order, node_labels=labels, stages=stages,
                              inflows=ins, outflows=outs, positive=positive, unit=value_meta['unit']),
                  labels=order, series_names=[encoding.value_field], presentation=prepared)
    return policy, warnings
