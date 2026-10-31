"""标准静态图只按精确来源选择器建立业务归属，不以名称或数值相同配对。"""

from __future__ import annotations

from collections.abc import Mapping

from ..hospital_operation.deterministic_analysis import metric_period_key
from ..units import unit_conversion_scale
from ..workflow.runtime.chart_inputs import parse_data_path
from ..workflow.runtime.phase_models import VisualizationPlanDraft
from ..workflow.runtime.standard_supplemental import StandardSupplementalRequest
from .fact_index import FACT_ARRAYS, fact_entry_from_pointer


def evaluate_standard_chart_alignment(index, chart, document):
    """前提为标准渲染已核验（重编译一致或签发签名）；转换、系列及轴由证明中的计划确定。"""
    from .semantic_alignment import SemanticAlignmentCheck

    fact_ids = set()
    try:
        plan = VisualizationPlanDraft.model_validate(chart.standard_render_proof.plan)
        draft = next(item for item in plan.charts if item.chart_id == chart.chart_id)
        files = {file.resource_id: file for file in index.files}
        all_metrics = []
        for origin in index.fact_files:
            if origin.content_kind != "deterministic_bundle":
                continue
            source = document(origin.file_resource_id)
            if source.get('analysisId') != origin.analysis_id:
                raise ValueError('chart_input_identity_mismatch')
            for _, array in FACT_ARRAYS:
                all_metrics.extend(item for item in source.get(array, ()) if isinstance(item, Mapping))
        codes = set()
        scopes = {}
        matched_bindings = set()
        for resource_id in chart.plot_data_file_resource_ids:
            plot = document(resource_id)
            source = plot['source']
            matches = [origin for origin in index.fact_files
                       if origin.analysis_id == source['analysisId']
                       and files[origin.file_resource_id].sha256 == source['sha256']]
            if len(matches) != 1:
                raise ValueError('chart_input_fact_source_ambiguous')
            origin = matches[0]
            bindings = [position for position, binding in enumerate(draft.data_bindings)
                        if binding.analysis_id == origin.analysis_id and binding.data_path == source['dataPath']
                        and binding.fact_path == source.get('path')
                        and (tuple(plot['columns']) == binding.fields or not binding.data_path.endswith('.rows')
                             and parse_data_path(binding.data_path)[0] == 'findings')]
            if len(bindings) != 1 or bindings[0] in matched_bindings:
                raise ValueError('chart_plan_binding_mismatch')
            matched_bindings.add(bindings[0])
            tokens = parse_data_path(source['dataPath'])
            source_document = document(origin.file_resource_id)
            proof_inputs = [item for item in chart.standard_render_proof.inputs if item['chartId'] == chart.chart_id]
            source_positions = [position for position, item in enumerate(proof_inputs)
                                if item['sha256'] == files[resource_id].sha256]
            if len(source_positions) != 1:
                raise ValueError('chart_plan_binding_mismatch')
            selected_fields = _selected_measure_fields(draft, plot, source_positions[0])
            if not selected_fields:
                continue
            metadata = plot.get('columnMeta') or {}
            if any(not isinstance(metadata.get(field), Mapping)
                                          or not metadata[field].get('unit') for field in selected_fields):
                raise ValueError('chart_axis_unit_unregistered')
            if tokens[0] == 'findings':
                ownership = _standard_finding_parents(index, origin, tokens, all_metrics)
                entries = []
                for field in selected_fields:
                    if not ownership.get(field):
                        raise ValueError('chart_metric_ownership_unregistered')
                    entries.extend(ownership[field])
            else:
                if len(tokens) < 2 or not isinstance(tokens[1], int):
                    raise ValueError('chart_projection_fact_unregistered')
                kind, entry = fact_entry_from_pointer(source_document, f'/{tokens[0]}/{tokens[1]}')
                from .semantic_alignment import _projection_semantics

                for field in selected_fields:
                    unit, _ = _projection_semantics(kind, entry, tokens, [
                        column for column in plot['columns'] if column == field
                        or column in {'field', 'period', 'group'}
                    ])
                    if not unit or metadata[field].get('unit') != unit:
                        raise ValueError('chart_axis_unit_mismatch')
                entries = [entry]
            for entry in entries:
                if not entry.get('factId') or not entry.get('scope'):
                    raise ValueError('chart_projection_scope_unregistered')
                if entry.get('profileHash') not in {None, index.profile_hash}:
                    raise ValueError('chart_fact_profile_mismatch')
                for key, value in entry['scope'].items():
                    if key in scopes and scopes[key] != value:
                        raise ValueError('chart_scope_mismatch')
                    scopes[key] = value
                codes.update(entry.get('metricCodes', ()))
                if entry.get('code'):
                    codes.add(entry['code'])
                fact_ids.add(entry['factId'])
        if matched_bindings != set(range(len(draft.data_bindings))):
            raise ValueError('chart_plan_binding_mismatch')
        if not set(draft.metric_codes).issubset(codes):
            raise ValueError('chart_metric_ownership_mismatch')
        return SemanticAlignmentCheck(scope='registered_fact_projection', status='verified',
                                      factIds=tuple(sorted(fact_ids)))
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) and str(error).startswith('chart_') else 'chart_plan_semantics_unavailable'
        return SemanticAlignmentCheck(scope='registered_fact_projection', reasons=(reason,),
                                      factIds=tuple(sorted(fact_ids)))


def _selected_measure_fields(chart, plot, source_index):
    """沿已证明的标准流水线反查实际绘制列，不借整张输入表的归属。"""
    available = {column for position, column in enumerate(plot['columns'])
                 if column != chart.standard_label_field and any(
                     isinstance(row[position], (int, float)) and not isinstance(row[position], bool)
                     for row in plot['rows'])}
    if chart.standard_sources:
        available = {item.series_name for item in chart.standard_sources}
    operations = ([(step.view, step.derivation) for step in chart.standard_steps]
                  if chart.standard_steps else
                  [(chart.standard_view, None), *((None, item) for item in chart.standard_derivations)])
    for view, derivation in operations:
        if view is not None:
            available = set(view.series_values if view.kind == 'pivot' else view.value_fields)
        if derivation is not None:
            available.add(derivation.name)
    active = set(chart.standard_value_fields) or available
    if chart.standard_encoding is not None:
        encoding = chart.standard_encoding
        active = {field for field in (encoding.x_field, encoding.y_field, encoding.value_field,
                                     encoding.size_field, encoding.color_field) if field in available}
    if chart.standard_waterfall is not None:
        active = {chart.standard_waterfall.value_field}
    if not active.issubset(available):
        raise ValueError('chart_metric_ownership_unregistered')
    for view, derivation in reversed(operations):
        if derivation is not None and derivation.name in active:
            # 二元派生需独立的已登记指标关系；不能把分子代码冒充为比率身份。
            if derivation.denominator is not None:
                raise ValueError('chart_derived_metric_ownership_unregistered')
            active.remove(derivation.name)
            active.add(derivation.numerator)
        if view is not None and active:
            output = set(view.series_values if view.kind == 'pivot' else view.value_fields)
            if not active.issubset(output):
                raise ValueError('chart_metric_ownership_unregistered')
            if view.kind == 'pivot':
                active = set(view.value_fields)
            if view.weight_field:
                active.add(view.weight_field)
    if chart.standard_sources:
        return tuple(item.value_field for item in chart.standard_sources
                     if item.source_index == source_index and item.series_name in active)
    if not active.issubset(plot['columns']):
        raise ValueError('chart_metric_ownership_unregistered')
    return tuple(column for column in plot['columns'] if column in active)


def _standard_finding_parents(index, origin, tokens, metrics):
    if len(tokens) < 2 or not isinstance(tokens[1], int):
        raise ValueError('chart_projection_fact_unregistered')
    finding_index = tokens[1]
    prefix = f'/findings/{finding_index}'
    records = [record for record in index.computations
               if record.method_version == 'standard-supplemental-v1'
               and record.method.startswith('supplemental_standard_')
               and any(ref.file_resource_id == origin.file_resource_id
                       and (ref.json_pointer == prefix or ref.json_pointer.startswith(prefix + '/'))
                       for ref in record.output_fact_refs)]
    if len(records) != 1:
        # 自由补证没有服务端结构化计算关系，不能借标准绘图洗白其指标归属。
        raise ValueError('chart_projection_fact_unregistered')
    record = records[0]
    parameters = record.parameters
    input_files = parameters.get('inputFiles', ())
    if record.method == 'supplemental_standard_batch':
        parameters = parameters['computations'][finding_index]
    elif finding_index != 0:
        raise ValueError('chart_projection_fact_unregistered')
    aliases = {field.alias or name for name, field in StandardSupplementalRequest.model_fields.items()}
    request = StandardSupplementalRequest.model_validate({key: value for key, value in parameters.items() if key in aliases})
    parents = {}
    for role, dataset_id, field, periods in (
        ('primary', request.dataset_id, request.measure_field, request.current_periods),
        ('denominator', request.dataset_id, request.denominator_field, request.current_periods),
        ('baseline', request.baseline_dataset_id, request.measure_field, request.baseline_periods),
    ):
        if dataset_id is None or field is None:
            continue
        snapshot = next((item for item in index.datasets if item.dataset_id == dataset_id), None)
        if snapshot is None or dataset_id not in record.input_dataset_ids:
            raise ValueError('chart_dataset_binding_mismatch')
        file = next(item for item in index.files if item.resource_id == snapshot.file_resource_id)
        if not any(item.get('path') == file.path and item.get('size') == file.size
                   and item.get('sha256') == file.sha256 for item in input_files):
            raise ValueError('chart_dataset_binding_mismatch')
        candidates = {entry.get('factId'): entry for entry in metrics
                      if entry.get('datasetId') == dataset_id and entry.get('field') == field
                      and entry.get('datasetSha256') == file.sha256 and entry.get('scope') == request.scope}
        if len(candidates) != 1 or None in candidates:
            raise ValueError('chart_metric_ownership_ambiguous')
        parent = next(iter(candidates.values()))
        scale = unit_conversion_scale(parent.get('unit'), request.measure_unit)
        if not request.measure_unit or (role == 'denominator' and (
            scale is None or float(scale) != request.denominator_scale
        ) or role != 'denominator' and request.measure_unit != parent.get('unit')):
            raise ValueError('chart_axis_unit_mismatch')
        keys = {metric_period_key(item.get('period'), parent.get('periodGranularity'))
                for item in parent.get('periodValues', ())}
        required = {metric_period_key(period, request.period_granularity) for period in periods}
        if parent.get('periodField') != request.period_field or None in required or not required.issubset(keys):
            raise ValueError('chart_period_binding_mismatch')
        parents[role] = [parent]
    if request.baseline_periods and request.baseline_dataset_id is None:
        baseline = parents.get('primary', ())
        keys = {metric_period_key(item.get('period'), parent.get('periodGranularity'))
                for parent in baseline for item in parent.get('periodValues', ())}
        required = {metric_period_key(period, request.period_granularity) for period in request.baseline_periods}
        if None in required or not required.issubset(keys):
            raise ValueError('chart_period_binding_mismatch')
        parents['baseline'] = baseline
    if request.ratio_fact_id:
        candidates = {entry.get('factId'): entry for entry in metrics if entry.get('factId') == request.ratio_fact_id}
        if len(candidates) != 1:
            raise ValueError('chart_metric_ownership_ambiguous')
        ratio = next(iter(candidates.values()))
        expected_parents = {parent['factId'] for role in ('primary', 'denominator')
                            for parent in parents.get(role, ())}
        if (ratio.get('scope') != request.scope or set(ratio.get('inputFactIds', ())) != expected_parents
                or ratio.get('denominatorScale') != request.denominator_scale):
            raise ValueError('chart_metric_ownership_mismatch')
        parents['ratio'] = list(candidates.values())
    primary = parents.get('primary', [])
    baseline = parents.get('baseline', primary)
    denominator = parents.get('denominator', [])
    if request.operation == 'group_ratio':
        return {'numerator': primary, 'denominator': denominator,
                'difference': primary + denominator, 'ratio': parents.get('ratio', [])}
    if request.operation in {'period_comparison', 'group_period_comparison'}:
        return {**{field: primary for field in ('current',)},
                **{field: baseline for field in ('baseline', 'baselineTotal')},
                **{field: primary + baseline for field in ('change', 'changeRate', 'contribution', 'totalChange')}}
    return {field: primary for field in ('value', 'share', 'previous', 'change', 'changeRate',
                                         'primaryTotal', 'primaryShare', 'secondaryTotal', 'secondaryShare')}
