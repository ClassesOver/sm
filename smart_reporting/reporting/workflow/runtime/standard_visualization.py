"""Conservative static templates over identity-checked chart inputs."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, NoReturn

from loguru import logger

from ...units import unit_conversion_scale
from .chart_inputs import ChartInputMaterialization
from .phase_models import (
    StandardChartAxes,
    StandardChartCanvas,
    StandardChartPresentation,
    StandardChartStyle,
    VisualizationPlanDraft,
)
from .standard_chart_alignment import align_chart_sources
from .standard_chart_box_summary import prepare_box_summary, summary_statistics_script
from .standard_chart_breaks import BREAK_DISPATCH, BREAK_SCRIPT, prepare_standard_break
from .standard_chart_contract import StandardChartConfig, resolve_standard_form
from .standard_chart_domains import DOMAIN_SCRIPT, prepare_standard_domains
from .standard_chart_dual_stack import DUAL_STACK_DISPATCH, DUAL_STACK_SCRIPT, prepare_dual_stack
from .standard_chart_encoding import (
    ENCODING_SCRIPT,
    StandardChartEncodingError,
    prepare_bands,
    prepare_encoded_chart,
)
from .standard_chart_families import (
    FAMILY_DISPATCH,
    FAMILY_FORMS,
    FAMILY_SCRIPT,
    family_aligned_semantics,
    family_input_roles,
    prepare_family_chart,
)
from .standard_chart_horizontal_breaks import HORIZONTAL_BREAK_SCRIPT
from .standard_chart_presentation import (
    PRESENTATION_SCRIPT,
    order_standard_rows,
    prepare_standard_presentation,
    valid_standard_metadata,
)
from .standard_chart_statistics import (
    STATISTICS_DISPATCH,
    STATISTICS_SCRIPT,
    prepare_statistical_chart,
)
from .standard_chart_transform import (
    StandardChartTransformationError,
    apply_standard_chart_steps,
    month_label,
    transform_chart_document,
)


@dataclass(frozen=True)
class StandardVisualizationPreflight:
    source: str | None
    diagnostic: dict | None = None
    warnings: tuple[dict, ...] = ()


class _Unsupported(ValueError):
    def __init__(self, code, parameter, message, suggestion, *, details=None):
        self.diagnostic = dict(code=code, parameter=parameter, message=message, suggestion=suggestion)
        if details:
            self.diagnostic['details'] = details
        super().__init__(message)


def _reject(code, parameter, message, suggestion, *, details=None) -> NoReturn:
    raise _Unsupported(code, parameter, message, suggestion, details=details)


def _patch_once(source: str, anchor: str, replacement: str) -> str:
    """模板拼接锚点必须唯一命中；锚点漂移时转Coding并告警，不静默丢失绘制能力。"""
    if source.count(anchor) != 1:
        logger.error('report_standard_visualization_template_anchor_drift anchor={!r} count={}',
                     anchor[:60], source.count(anchor))
        _reject('standard_template_anchor_drift', 'standardTemplate', '标准模板拼接锚点未唯一命中。',
                '属于模板实现缺陷；本图交由Coding生成，并修复模板锚点。')
    return source.replace(anchor, replacement)


def standard_visualization_preflight(
    plan: VisualizationPlanDraft, inputs: ChartInputMaterialization,
) -> StandardVisualizationPreflight:
    try:
        warnings = []
        source = _standard_visualization_script(plan, inputs, warnings=warnings)
        return StandardVisualizationPreflight(source, None if source else dict(
            code='standard_parameter_combination_unsupported', parameter='standardChart',
            message='当前数据或参数组合无法由标准模板表达。',
            suggestion='保留冻结输入与业务目标，交由Coding生成该图；其他图独立选择路线。'), tuple(warnings))
    except StandardChartEncodingError as error:
        return StandardVisualizationPreflight(None, dict(code=error.code, parameter=error.parameter,
            message=str(error), suggestion='保留冻结值及来源，修正显式图族参数；不补造几何或业务数据。'))
    except _Unsupported as error:
        return StandardVisualizationPreflight(None, error.diagnostic)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        logger.warning('report_standard_visualization_preflight_fallback error={}', type(error).__name__)
        return StandardVisualizationPreflight(None, dict(
            code='standard_input_or_transformation_invalid', parameter='chartInputs/standardView/standardDerivations',
            message='冻结输入结构或声明的数据转换未通过预检。',
            suggestion='检查列名、转换操作、月份连续性、重复单元及登记单位；不要补造数据。',
            errorType=type(error).__name__))


def standard_visualization_script(plan: VisualizationPlanDraft, inputs: ChartInputMaterialization) -> str | None:
    """Compatibility API; production routing uses the structured preflight result."""
    return standard_visualization_preflight(plan, inputs).source


def standard_plan_diagnostics(plan: VisualizationPlanDraft, inputs: ChartInputMaterialization) -> list[dict]:
    """逐图反馈机器契约问题；自选Coding及不可用输入不触发无意义重规划。"""
    diagnostics = []
    for chart in plan.charts:
        if (getattr(chart, 'standard_form', None) == 'custom'
                or chart.chart_id in inputs.fallback_chart_ids):
            continue
        entries = tuple(entry for entry in inputs.entries if entry['chartId'] == chart.chart_id)
        if not entries:
            continue
        paths = {entry['path'] for entry in entries}
        bound = ChartInputMaterialization(files=tuple(file for file in inputs.files if file.path in paths),
                                         entries=entries)
        result = standard_visualization_preflight(plan.model_copy(update={'charts': (chart,)}), bound)
        if result.diagnostic is not None:
            issue = {'chartId': chart.chart_id, **result.diagnostic}
            issue['sources'] = []
            for index, entry in enumerate(entries):
                file = next((file for file in bound.files if file.path == entry['path']), None)
                if file is None or file.sha256 != entry['sha256']:
                    continue
                try:
                    document = json.loads(file.content)
                except (ValueError, UnicodeDecodeError):
                    continue  # 输入错误保留原诊断，元数据提示不能使预检异常退出。
                if isinstance(document, dict):
                    issue['sources'].append({
                        'sourceIndex': index, 'source': document.get('source'),
                        'columns': document.get('columns'), 'columnMeta': document.get('columnMeta', {}),
                    })
            if result.diagnostic['code'] in {'standard_series_empty', 'standard_source_alignment_failed',
                                              'standard_period_alignment_invalid'}:
                issue['bindingCorrectionAllowed'] = True
            diagnostics.append(issue)
    return diagnostics


def _compatible_periods(chart, metas, form):
    windows = [meta.get('periods') for meta in metas]
    if all(window == windows[0] for window in windows):
        return True
    if (form not in {'bar', 'barh', 'line'}
            or getattr(chart, 'comparison_type', None) != 'yoy'
            or getattr(chart, 'comparability', None) != 'strict'
            or any(not isinstance(window, (list, tuple)) or not window for window in windows)):
        return False
    try:
        periods = [sorted(month_label(value) for value in window) for window in windows]
    except ValueError:
        return False
    if any(len(set(window)) != len(window) for window in periods):
        return False
    # 一个年度窗口可对应多项指标；按两个唯一窗口校验同比，不限制为两条系列。
    periods = list(dict.fromkeys(tuple(window) for window in periods))
    if len(periods) != 2:
        return False
    years = [{int(value[:4]) for value in window} for window in periods]
    return (all(len(year) == 1 for year in years)
            and abs(next(iter(years[0])) - next(iter(years[1]))) == 1
            and [value[5:] for value in periods[0]] == [value[5:] for value in periods[1]])


def _encoded_configuration(chart, document, original_document, form, label, source, canvas, style, presentation, axes, selected):
    encoding = getattr(chart, 'standard_encoding', None)
    if encoding is None:
        _reject('standard_encoding_required', 'standardEncoding', '散点/气泡/热力图须显式声明编码字段。', '绑定X/Y、大小或热力值的冻结字段，不自动猜测坐标。')
    expected = encoding.value_field if form == 'heatmap' and encoding else encoding.y_field if encoding else None
    if selected and tuple(selected) != (expected,):
        _reject('standard_encoding_selection_conflict', 'standardValueFields', '编码只允许选定主Y或热力值字段。', 'X/颜色/大小及上下界通过显式编码参数绑定。')
    try:
        policy = prepare_encoded_chart(chart, document, original_document, form, label, canvas, style, presentation, axes)
    except StandardChartEncodingError as error:
        _reject(error.code, error.parameter, str(error), '检查显式编码、登记单位、标签及缺失策略，不能填零或改变冻结值。')
    return StandardChartConfig(source.path, source.sha256, chart.source_path, chart.title, form, label,
            [], None, None, None, [], axes.model_dump(), [], None, policy)


def _statistical_configuration(chart, document, original, form, label, source, canvas, style, presentation, axes, selected):
    try:
        policy = prepare_statistical_chart(chart, document, original, form, label, canvas, style, presentation, axes, selected)
    except StandardChartEncodingError as error:
        _reject(error.code, error.parameter, str(error), '保留贡献链或组内原始样本，检查登记单位、绝对值对账及缺失策略。')
    return StandardChartConfig(source.path, source.sha256, chart.source_path, chart.title, form, label,
            [], None, None, None, [], axes.model_dump(), [], None, policy)


def _standard_visualization_script(
    plan: VisualizationPlanDraft, inputs: ChartInputMaterialization,
    *, warnings: list[dict] | None = None,
) -> str | None:
    if inputs.fallback_chart_ids or not plan.charts:
        _reject('standard_input_unavailable', 'chartInputs', '图表缺少可用的物化输入或计划为空。', '为对应图补齐数据绑定，或只将该图交由Coding。')
    configs: list[StandardChartConfig] = []
    summary_profiles: dict[str, Any] = {}
    aligned = {}
    auxiliary = {}
    displays = {}
    for chart in plan.charts:
        if getattr(chart, 'standard_pagination', None) is not None:
            _reject('standard_pagination_not_expanded', 'standardPagination', '分页计划须先在宿主展开为独立图表。', '先物化并展开全部分页，再逐图执行标准模板。')
        canvas = getattr(chart, 'standard_canvas', StandardChartCanvas())
        style = getattr(chart, 'standard_style', StandardChartStyle())
        presentation = getattr(chart, 'standard_presentation', StandardChartPresentation())
        axes = getattr(chart, 'standard_axes', StandardChartAxes())
        form = resolve_standard_form(chart)
        if getattr(chart, 'standard_form', None) == 'custom':
            _reject('standard_custom_requested', 'standardForm', '规划显式选择自定义Coding图。', '保留冻结输入与业务意图，由Coding执行；不视为标准能力命中失败。')
        if ((getattr(chart, 'standard_waterfall', None) is not None and form != 'waterfall')
                or (getattr(chart, 'standard_distribution', None) is not None and form != 'boxplot')
                or (getattr(chart, 'standard_box_summary', None) is not None and form != 'boxplot')):
            _reject('standard_statistics_form_conflict', 'standardWaterfall/standardDistribution', '统计参数与图形不匹配。', '瀑布用waterfall，原始样本分布用boxplot；不能忽略统计参数。')
        entries = [entry for entry in inputs.entries if entry['chartId'] == chart.chart_id]
        if form is None:
            _reject('standard_form_unsupported', 'standardForm', '缺少可执行的标准图机器类型。', '按能力契约显式选择standardForm，业务描述保留在visualForm；确需Coding时选custom。')
        if not entries:
            _reject('standard_input_missing', 'chartInputs', '未找到本图绑定的物化数据。', '补齐本图chart-input绑定。')
        if form not in FAMILY_FORMS and any(getattr(chart, field, None) is not None for field in (
                'standard_composition', 'standard_radar', 'standard_funnel', 'standard_sankey')):
            _reject('standard_family_form_conflict', 'standardChart', '图族专用参数与机器类型不匹配。', '选择匹配机器类型，不能忽略图族参数。')
        entry = entries[0]
        source = next((item for item in inputs.files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            _reject('standard_input_identity_mismatch', 'chartInputs.sha256', '输入身份与登记不一致。', '重新物化并核验原始来源，禁止绕过身份核验。')
        # Multiple charts/pages may intentionally share one immutable full
        # cohort. Their display windows, transforms and units are per output.
        scope = (source.path, chart.source_path)
        document = json.loads(source.content)
        if not isinstance(document, dict):
            _reject('standard_input_not_object', 'chartInputs', '冻结输入不是表格对象。', '重新物化该图chart-input，不手工改写来源。')
        original_document = document
        selected = tuple(getattr(chart, 'standard_value_fields', ()))
        summary_spec = getattr(chart, 'standard_box_summary', None)
        if summary_spec is not None:
            try:
                policy, summary_profiles[chart.chart_id] = prepare_box_summary(
                    chart, document, entries, inputs.files, canvas, style, presentation, axes, selected)
            except StandardChartEncodingError as error:
                _reject(error.code, error.parameter, str(error), '绑定冻结分位数/须和可选样本量/异常点来源，不补造原始样本。')
            configs.append(StandardChartConfig(source.path, source.sha256, chart.source_path, chart.title, form,
                            summary_spec.group_field, [], None, None, None, [], axes.model_dump(), [], None, policy))
            continue
        if form == 'summary-bars':
            original_columns = document.get('columns', [])
            original_rows = document.get('rows', [])
            original_meta = document.get('columnMeta', {})
            if not isinstance(original_meta, dict):
                _reject('standard_metadata_invalid', 'columnMeta', '列元数据结构无效。', '从对应冻结事实重新物化元数据，不从标题猜测单位。')
            if (len(original_rows) != 1 or len(selected) < 2
                    or len(set(selected)) != len(selected) or not set(selected).issubset(original_columns)):
                _reject('standard_summary_bars_selection_invalid', 'standardValueFields', '单行总览需要恰好一行数据，并显式选择至少两个不重复的现有数值列。', '用standardValueFields选择同一行内的度量列；多行数据改用bar/barh。')
            selected_meta = [original_meta.get(column, {}) for column in selected]
            if (any(not valid_standard_metadata(meta) or not meta.get('unit') for meta in selected_meta)
                    or any(meta != selected_meta[0] for meta in selected_meta)):
                _reject('standard_summary_bars_units_incompatible', 'standardValueFields/columnMeta', '单行总览所选列的单位或百分比尺度缺失或不一致。', '只选择登记单位相同的度量列；不同量纲拆图或改用双轴。')
            document = {'columns': ['label', 'value'],
                        'rows': [[column, original_rows[0][original_columns.index(column)]] for column in selected],
                        'columnMeta': {'value': selected_meta[0]}}
            aligned[scope] = (document, [(source.path, source.sha256)])
            selected = ('value',)
            form = 'bar'
        selections = getattr(chart, 'standard_sources', ())
        view = getattr(chart, 'standard_view', None)
        derivations = getattr(chart, 'standard_derivations', ())
        steps = getattr(chart, 'standard_steps', ())
        has_transform = view is not None or bool(derivations) or bool(steps)
        source_labels = getattr(chart, 'standard_source_labels', ())
        if source_labels and not selections:
            _reject('standard_source_window_without_selection', 'standardSourceLabels', '输入窗口需要显式来源列选择。', '声明standardSources，或仅使用standardLabels选择最终展示窗口。')
        family_documents = None
        alignment_entries, alignment_selections = entries, selections
        family_identities = None
        if form in FAMILY_FORMS:
            family_documents, family_identities, alignment_entries, alignment_selections = family_input_roles(chart, entries, inputs.files)
            aligned[scope] = (document, family_identities)
        if alignment_selections or len(alignment_entries) > 1:
            alignment_diagnostics = []
            alignment = align_chart_sources(alignment_entries, inputs.files, alignment_selections,
                                            selected_labels=source_labels or (() if has_transform or form in FAMILY_FORMS else getattr(chart, 'standard_labels', ())),
                                            allow_nulls=axes.allow_nulls, max_labels=480 if form in {'scatter', 'bubble'} else 60,
                                            diagnostics=alignment_diagnostics)
            if alignment is None:
                _reject('standard_source_alignment_failed', 'standardSources', '来源标签、单位、身份或来源使用范围不满足对齐要求。',
                        '按details.reason修正来源选择、分类过滤、月份规范化或共同窗口；单位只用登记值，不补零或静默去重。',
                        details=alignment_diagnostics[0] if alignment_diagnostics else None)
            document, identities = alignment
            if form in FAMILY_FORMS:
                document = family_aligned_semantics(document, selections)
            aligned[scope] = (document, family_identities if form in FAMILY_FORMS else identities)
        if steps and (view is not None or derivations):
            _reject('standard_pipeline_order_ambiguous', 'standardSteps', '不能混用新流水线和旧视图/计算参数。', '将所有view/derivation按执行顺序放入standardSteps。')
        if view is not None or derivations or steps:
            try:
                document = (apply_standard_chart_steps(document, steps) if steps else
                            transform_chart_document(document, view, derivations))
            except StandardChartTransformationError as error:
                _reject('standard_transformation_failed', f'standardSteps[{error.step_index}]',
                        error.reason, '检查该步的输入列、登记单位、分组维度及月份；按声明顺序修正，禁止补零或覆盖原字段。')
            dependencies = aligned.get(scope, (None, [(source.path, source.sha256)]))[1]
            aligned[scope] = (document, dependencies)
        if form in FAMILY_FORMS:
            policy, family_warnings = prepare_family_chart(chart, document, original_document, form,
                canvas, style, presentation, axes, family_documents)
            if warnings is not None:
                warnings.extend({'chartId': chart.chart_id, **item} for item in family_warnings)
            configs.append(StandardChartConfig(source.path, source.sha256, chart.source_path, chart.title, form,
                            None, [], None, None, None, [], axes.model_dump(), [], None, policy))
            continue
        columns, rows = document['columns'], document['rows']
        if (not isinstance(columns, list) or not columns
                or any(not isinstance(column, str) or not column for column in columns)
                or len(set(columns)) != len(columns)
                or not 1 <= len(rows) <= 480
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
            _reject('standard_table_shape_invalid', 'chartInputs', '转换后的表格列名、行宽或行数（1—480）不满足标准模板要求。', '检查视图转换输出的列与行；超量数据先显式汇总或选窗口。')
        explicit_label = getattr(chart, 'standard_label_field', None)
        encoding = getattr(chart, 'standard_encoding', None)
        distribution = getattr(chart, 'standard_distribution', None)
        if form == 'boxplot' and distribution is not None and explicit_label is None:
            explicit_label = distribution.group_field
        if form == 'heatmap' and encoding is not None and explicit_label is None:
            explicit_label = encoding.x_field
        label = explicit_label or ('period' if 'period' in columns else 'label' if 'label' in columns else None)
        if label is not None and label not in columns:
            _reject('standard_label_missing', 'standardLabelField', '显式标签列不在转换后的数据中。', '使用转换后存在的冻结标签列。')
        if label is None:
            text_columns = [column for column in columns
                            if all(isinstance(row[columns.index(column)], str) for row in rows)
                            and not (form in {'scatter', 'bubble'} and encoding is not None and column == encoding.group_field)]
            if len(text_columns) == 1:
                label = text_columns[0]
        if label is None and form in {'scatter', 'bubble'}:
            if (getattr(chart, 'standard_labels', ()) or presentation.order.mode != 'source'
                    or presentation.order.limit is not None):
                _reject('standard_scatter_label_required', 'standardLabelField', '匿名观测不能按虚构标签选择、排序或截取。', '提供冻结标签列后再声明显示窗口/排序。')
            configs.append(_encoded_configuration(chart, document, original_document, form, None,
                            source, canvas, style, presentation, axes, selected))
            continue
        if label is None:
            _reject('standard_label_ambiguous', 'standardLabelField', '无法唯一确定标签列。', '显式指定冻结标签列standardLabelField。')
        label_index = columns.index(label)
        selected_labels = tuple(getattr(chart, 'standard_labels', ()))
        if selected_labels:
            if (len(set(selected_labels)) != len(selected_labels)
                    or not set(selected_labels).issubset(row[label_index] for row in rows)):
                _reject('standard_labels_selection_invalid', 'standardLabels', '显示窗口标签重复或不存在于冻结数据。', '逐字使用冻结标签，不补齐缺失期间。')
            rows = [row for row in rows if row[label_index] in selected_labels]
            document = {**document, 'rows': rows}
            dependencies = aligned.get(scope, (None, [(source.path, source.sha256)]))[1]
            aligned[scope] = (document, dependencies)
        ordered = order_standard_rows(document, label, presentation.order)
        if ordered is None:
            _reject('standard_order_invalid', 'standardPresentation.order', '排序或截取参数无法绑定到冻结数据。', '排序字段须为已选数值列；limit不得丢失必要分组。')
        if ordered['rows'] != rows:
            document, rows = ordered, ordered['rows']
            dependencies = aligned.get(scope, (None, [(source.path, source.sha256)]))[1]
            aligned[scope] = (document, dependencies)
        labels = [row[label_index] for row in rows]
        if any(not isinstance(value, str) or not value for value in labels):
            _reject('standard_labels_invalid', 'standardLabelField', '标签列含空值或非文本值。', '选择全部为非空文本的冻结标签列，或先用month等转换规范化。')
        if form in {'waterfall', 'boxplot'}:
            configs.append(_statistical_configuration(chart, document, original_document, form, label,
                            source, canvas, style, presentation, axes, selected))
            continue
        if form in {'scatter', 'bubble', 'heatmap'}:
            configs.append(_encoded_configuration(chart, document, original_document, form, label,
                            source, canvas, style, presentation, axes, selected))
            continue
        if encoding is not None:
            _reject('standard_encoding_form_conflict', 'standardEncoding', '字段编码仅用于scatter/bubble/heatmap。', '折线范围使用standardBands；其他图继续用standardValueFields。')
        if any(item.row_label or item.end_row_label for item in getattr(chart, 'standard_annotations', ())):
            _reject('standard_annotation_row_coordinate_invalid', 'standardAnnotations', '矩阵行标签仅适用于热力图。', '普通图使用series/label绑定标注。')
        other_columns = [column for column in columns if column != label]
        category_columns = [column for column in other_columns
                            if all(isinstance(row[columns.index(column)], str) for row in rows)]
        category = category_columns[0] if len(category_columns) == 1 else None
        if explicit_label:
            category = None
        values = [column for column in other_columns if column != category]
        if selected:
            if len(set(selected)) != len(selected) or not set(selected).issubset(values):
                _reject('standard_field_selection_invalid', 'standardValueFields', '选定字段重复或不在可用度量中。', '检查视图转换后的列名与新衍生列名称。')
            values = list(selected)
        if not 1 <= len(values) <= 8 or (category and (label != 'period' or len(values) != 1)):
            _reject('standard_series_shape_unsupported', 'standardValueFields/standardView', '系列数量或长表结构超出标准范围。', '显式选取最多8个度量；用pivot转为宽表或group汇总后展示。')
        dual_stack = axes.mode == 'dual' and form in {'stacked-bar', 'stacked-total'}
        nullable = axes.allow_nulls and (form in {'line', 'bar', 'barh'} or dual_stack) and not category
        if any(not (nullable and row[columns.index(column)] is None) and (
               not isinstance(row[columns.index(column)], (int, float))
               or isinstance(row[columns.index(column)], bool)
               or not math.isfinite(row[columns.index(column)])) for row in rows for column in values):
            _reject('standard_values_invalid', 'standardAxes.allowNulls/standardValueFields', '选定系列含缺失、非有限或非数值数据。', '普通柱线图可显式allowNulls=true保留缺失；NaN/Inf/布尔值必须修复来源。')
        if any(all(row[columns.index(column)] is None for row in rows) for column in values):
            _reject('standard_series_empty', 'standardValueFields', '选定系列全部缺失。', '提供有依据的数据或移除空系列，不补零。')
        metadata = document.get('columnMeta') or {}
        if not isinstance(metadata, dict):
            _reject('standard_metadata_invalid', 'columnMeta', '列元数据结构无效。', '从对应冻结事实重新物化元数据，不从标题猜测单位。')
        metas = [metadata.get(column, {}) for column in values]
        if any(not valid_standard_metadata(meta) for meta in metas):
            _reject('standard_metadata_invalid', 'columnMeta', '度量单位或百分比尺度元数据类型无效。', '从对应冻结事实重新物化元数据，不从标题猜测单位。')
        if any(getattr(item, 'label_mode', None) == 'month_of_year' for item in selections) and not _compatible_periods(chart, metas, form):
            _reject('standard_period_alignment_invalid', 'standardSources.periodYear/comparisonType', '同月映射的期间不满足显式比较关系。', '严格同比须为相邻两年的相同月份集合，不修改冻结日期或补齐缺失月份。')
        mixed = any(item.geometry != 'auto' for item in style.series)
        advanced = axes.mode != 'single' or axes.scale != 'linear' or mixed
        if mixed and form not in {'line', 'bar'} and not dual_stack:
            _reject('standard_series_geometry_unsupported', 'standardStyle.series.geometry', '逐系列柱/线混合仅支持line、bar或堆叠双轴。', '改用line/bar，或移除geometry设置。')
        if axes.panel_limit is not None and (axes.mode != 'panels' or form != 'barh'):
            _reject('standard_panel_limit_invalid', 'standardAxes.panelLimit', 'panelLimit仅适用于横向条形分面。', '与mode=panels和barh同时使用，或移除panelLimit。')
        if axes.right_display_unit and axes.mode != 'dual':
            _reject('standard_right_display_unit_invalid', 'standardAxes.rightDisplayUnit', '右轴显示单位仅适用于双轴。', '设置mode=dual，或移除rightDisplayUnit。')
        axis_units = []
        axis_factors = []
        for field, meta in zip(values, metas, strict=True):
            requested = axes.right_display_unit if field in axes.right_fields else axes.left_display_unit
            requested = requested or (getattr(chart, 'standard_display_unit', None) if advanced else None)
            factor = unit_conversion_scale(meta.get('unit'), requested) if requested else 1
            if factor is None:
                _reject('standard_unit_conversion_invalid', 'standardDisplayUnit/standardAxes', '请求的显示单位无法由登记单位换算。', '仅使用同维度的登记单位，复合单位不可降维。')
            axis_factors.append(float(factor))
            axis_units.append(requested or meta.get('unit'))
        display_unit = getattr(chart, 'standard_display_unit', None)
        if display_unit:
            scales = [unit_conversion_scale(meta.get('unit'), display_unit) for meta in metas]
            if not advanced and (None in scales or len(set(scales)) != 1):
                _reject('standard_unit_conversion_invalid', 'standardDisplayUnit', '所选系列无法统一换算到显示单位。',
                        '按sources.columnMeta选择同量纲度量；单位未知时保留原值且不声明换算单位。')
            if not advanced:
                scale = scales[0]
                assert scale is not None
                displays[scope] = (float(scale), display_unit)
        if not advanced and axes.left_display_unit:
            if display_unit:
                _reject('standard_display_unit_conflict', 'standardDisplayUnit/standardAxes.leftDisplayUnit', '单轴图同时声明了两种显示单位。', '仅保留standardDisplayUnit或leftDisplayUnit之一。')
            if len(set(axis_factors)) != 1 or len(set(axis_units)) != 1:
                _reject('standard_unit_conversion_invalid', 'standardAxes.leftDisplayUnit', '所选系列无法统一换算到左轴显示单位。', '仅选择同量纲度量；单位未知时保留原值。')
            displays[scope] = (axis_factors[0], axes.left_display_unit)
        auxiliary_fields = tuple(getattr(chart, 'standard_label_fields', ()))
        if auxiliary_fields:
            if (advanced and not dual_stack or len(auxiliary_fields) != len(set(auxiliary_fields))
                    or not set(auxiliary_fields).issubset(columns)):
                _reject('standard_label_fields_invalid', 'standardLabelFields', '辅助标注列重复、不存在，或与高级轴组合。', '最多3个不重复的同表数值列；高级轴（堆叠双轴除外）暂不支持辅助列。')
            for field in auxiliary_fields:
                meta = metadata.get(field, {})
                if not valid_standard_metadata(meta) or not meta.get('unit') or any(
                    not isinstance(row[columns.index(field)], (int, float))
                    or isinstance(row[columns.index(field)], bool)
                    or not math.isfinite(row[columns.index(field)]) for row in rows
                ):
                    _reject('standard_label_fields_invalid', 'standardLabelFields', '辅助标注列缺少登记单位或含非有限数值。', '选择单位明确且数值完整的冻结列，不补造。')
            auxiliary[scope] = auxiliary_fields
        right = tuple(axes.right_fields)
        if (axes.mode != 'dual' and right) or (axes.mode != 'zoom' and (axes.zoom_start or axes.zoom_end)):
            _reject('standard_axes_mode_conflict', 'standardAxes', 'rightFields仅用于dual，zoomStart/zoomEnd仅用于zoom。', '设置匹配的mode，或移除不适用的轴参数。')
        if advanced:
            if axes.zero_baseline and axes.scale == 'log':
                _reject('standard_axes_mode_conflict', 'standardAxes.zeroBaseline/scale', '对数轴不能强制零基线。', '对数轴移除zeroBaseline，或改用线性轴。')
            if (category or form not in {'line', 'bar', 'barh'} and not dual_stack
                    or form == 'barh' and axes.mode != 'panels'
                    or any(not meta.get('unit') for meta in metas)):
                _reject('standard_advanced_axes_unsupported', 'standardAxes', '高级轴仅支持单位明确的单来源宽表line/bar（barh仅分面）。', '长表先pivot为宽表；补齐登记单位；其他组合交由Coding。')
            if axes.mode == 'dual' and (
                not right or len(right) != len(set(right))
                or not set(right) < set(values)
            ):
                _reject('standard_dual_axis_fields_invalid', 'standardAxes.rightFields', '双轴右侧字段为空、重复，或未给左轴留下系列。', 'rightFields选择已选度量的非空真子集。')
            groups = ([list(range(len(values)))] if axes.mode in {'single', 'zoom'} else
                      [[index for index, value in enumerate(values) if value not in right],
                       [values.index(value) for value in right]] if axes.mode == 'dual' else
                      [[index] for index in range(len(values))])
            if any(len({(axis_units[index], metas[index].get('isPercent'))
                        for index in group}) != 1 for group in groups):
                _reject('standard_axis_units_incompatible', 'standardAxes', '同轴度量单位或百分比尺度不一致。', '显式统一显示单位，或将不同量纲放到双轴/分面。')
            if not _compatible_periods(chart, metas, form):
                _reject('standard_period_alignment_invalid', 'columnMeta.periods/comparisonType', '系列期间不满足显式比较关系。', '同窗口比较保留一致期间；严格同比允许相邻两年相同月份，不得丢失来源期间。')
            if axes.scale == 'log' and (form != 'line' or any(
                row[columns.index(column)] is not None and row[columns.index(column)] <= 0 for row in rows for column in values
            )):
                _reject('standard_log_domain_invalid', 'standardAxes.scale', '普通对数轴要求严格正数折线。', '含零或负值时使用symlog并明确linearThreshold，或采用分面/局部放大。')
            if axes.mode == 'zoom' and (
                axes.zoom_start not in labels or axes.zoom_end not in labels
                or labels.index(axes.zoom_start) > labels.index(axes.zoom_end)
            ):
                _reject('standard_zoom_range_invalid', 'standardAxes.zoomStart/zoomEnd', '局部放大区间不存在于冻结标签或顺序倒置。', '逐字引用冻结标签，起点不晚于终点。')
        # 同轴系列必须有明确且完全一致的单位、比例显示尺度；不推断换算。
        if not advanced and len(values) > 1 and (
            any(not meta.get('unit') for meta in metas)
            or len({(meta.get('unit'), meta.get('isPercent')) for meta in metas}) != 1
        ):
            _reject('standard_axis_units_incompatible', 'standardValueFields/columnMeta',
                    '同轴系列包含未知单位或不同量纲、百分比尺度。',
                    '显式选择同量纲的业务度量；排名和占比不要作为金额系列；不同量纲使用双轴或分面，未知单位不得猜测。')
        if form in {'line', 'stacked-bar', 'stacked-area', 'stacked-total'} and len(values) > 1:
            if not _compatible_periods(chart, metas, form):
                _reject('standard_period_alignment_invalid', 'columnMeta.periods/comparisonType', '系列期间不满足显式比较关系。', '仅普通柱线图允许显式严格同比；堆叠图须使用同一期间。')
        if category:
            category_index = columns.index(category)
            keys = [(row[label_index], row[category_index]) for row in rows]
            categories = list(dict.fromkeys(row[category_index] for row in rows))
            if (any(not value for value in categories) or len(categories) > 8
                    or len(set(keys)) != len(keys)):
                _reject('standard_long_table_categories_invalid', 'standardView', '长表分类为空、超过8类，或期间×分类重复。', '显式group汇总或筛选分类，不静默去重。')
            # 长表缺失组合只允许折线断点；构成图和柱图不补零。
            if form != 'line' and len(keys) != len(set(labels)) * len(categories):
                _reject('standard_long_table_incomplete', 'standardView', '长表缺少期间×分类组合，仅折线允许断点。', '改用line，或补齐有依据的数据；不补零。')
        elif len(set(labels)) != len(labels):
            _reject('standard_labels_duplicate', 'standardLabelField/standardView', '标签重复且没有可用的长表分类。', '显式用group汇总或pivot透视；不要任意丢弃重复行。')
        if len(set(labels)) > 60:
            _reject('standard_label_capacity_exceeded', 'standardLabels/standardPresentation.order', '单图超过60个标签。', '显式选择业务窗口、TopN或汇总视图；不得静默丢弃数据。')
        if form in {'stacked-bar', 'stacked-area', 'stacked-total'} and not dual_stack and any(
            row[columns.index(column)] < 0 for row in rows for column in values
        ):
            _reject('standard_negative_stack_unsupported', 'visualForm', '标准堆叠图暂不支持负数构成。', '采用分组柱图展示正负值，或用Coding实现发散堆叠。')
        total_field = getattr(chart, 'standard_total_field', None)
        if form in {'stacked-bar', 'stacked-area', 'stacked-total'} and not dual_stack:
            try:
                totals_to_check = (
                    [math.fsum(row[columns.index(values[0])] for row in rows if row[label_index] == name)
                     for name in set(labels)] if category else
                    [math.fsum(row[columns.index(column)] for column in values if column != total_field) for row in rows]
                )
            except OverflowError:
                _reject('standard_stack_total_invalid', 'standardValueFields', '堆叠合计溢出。', '检查数值量级与单位，必要时显式换算显示单位。')
            if any(not math.isfinite(value) for value in totals_to_check):
                _reject('standard_stack_total_invalid', 'standardValueFields', '堆叠合计不是有限值。', '检查数值量级与单位，必要时显式换算显示单位。')
        if total_field is not None and not dual_stack:
            if form != 'stacked-total' or category or total_field not in values or len(values) < 2:
                _reject('standard_total_field_invalid', 'standardTotalField', '独立总额仅用于宽表stacked-total，且须为已选列并至少有一个分项。', '将总额列加入standardValueFields并选择stacked-total。')
            if any(not math.isclose(
                math.fsum(row[columns.index(column)] for column in values if column != total_field),
                row[columns.index(total_field)], rel_tol=1e-12, abs_tol=1e-9,
            ) for row in rows):
                _reject('standard_total_reconciliation_failed', 'standardTotalField', '独立总额与分项之和不闭合。', '检查分项是否完整；不闭合时移除standardTotalField改用服务端求和。')
        annotation_names = categories if category else values
        annotation_labels = list(dict.fromkeys(labels))
        annotations: list[tuple[str, int | None, int | None, int | None]] = []
        first: int | None
        for specification in getattr(chart, 'standard_annotations', ()):
            kind = specification.kind
            if kind == 'range':
                if axes.mode == 'panels' and form == 'barh':
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '横向分面不支持区间高亮。', '移除range标注或改用其他轴模式。')
                if (specification.series is not None or specification.label not in annotation_labels
                        or specification.end_label not in annotation_labels):
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '区间标注不能指定series，且起止标签须存在于冻结标签。', '逐字引用冻结标签。')
                first = annotation_labels.index(specification.label)
                last = annotation_labels.index(specification.end_label)
                if first > last:
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '区间标注起点晚于终点。', '按标签顺序声明label与endLabel。')
                annotations.append((kind, None, first, last))
                continue
            name = specification.series
            if name is None and len(annotation_names) == 1:
                name = annotation_names[0]
            if name not in annotation_names or specification.end_label is not None:
                _reject('standard_annotation_binding_invalid', 'standardAnnotations', '标注系列不存在，或非区间标注声明了endLabel。', 'series引用已选度量或长表分类；仅range使用endLabel。')
            if kind in {'point', 'reference'}:
                if specification.label not in annotation_labels:
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '重点/参考标注的标签不存在于冻结标签。', '逐字引用冻结标签。')
                first = annotation_labels.index(specification.label)
                if not category and rows[first][columns.index(name)] is None:
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '重点/参考标注所在点为缺失值。', '选择有冻结数值的点，不补零。')
                if axes.mode == 'panels' and form == 'barh' and axes.panel_limit is not None:
                    visible = sorted((i for i in range(len(rows)) if rows[i][columns.index(name)] is not None),
                                     key=lambda i: rows[i][columns.index(name)],
                                     reverse=axes.panel_descending)[:axes.panel_limit]
                    if first not in visible:
                        _reject('standard_annotation_binding_invalid', 'standardAnnotations', '重点/参考标注不在分面TopN可见范围内。', '调整panelLimit或改选可见标签。')
                if category and (specification.label, name) not in keys:
                    _reject('standard_annotation_binding_invalid', 'standardAnnotations', '重点/参考标注的期间×分类组合不存在。', '选择存在的长表组合。')
            elif kind in {'values', 'peak', 'trough'} and specification.label is None:
                first = None
            else:
                _reject('standard_annotation_binding_invalid', 'standardAnnotations', '该标注类型与label组合不受支持。', 'values/peak/trough不带label；point/reference需要label；range需要label和endLabel。')
            annotations.append((kind, annotation_names.index(name), first, None))
        annotation_count = (min(len(annotation_labels), axes.panel_limit)
                            if axes.mode == 'panels' and form == 'barh' and axes.panel_limit else len(annotation_labels))
        if sum(annotation_count if item[0] in {'values', 'peak', 'trough'} else 1
               for item in annotations) > 60:
            _reject('standard_annotation_capacity_exceeded', 'standardAnnotations', '可见标注超过60项预算。', '保留重点/峰谷标注，或显式选择TopN、窗口、分图。')
        if any(item.series not in annotation_names for item in style.series):
            _reject('standard_style_series_unknown', 'standardStyle.series', '样式引用了不存在的系列。', 'series名称须与已选度量或长表分类一致。')
        if any(item.series not in annotation_names or item.label not in annotation_labels for item in style.points):
            _reject('standard_style_points_invalid', 'standardStyle.points', '点样式引用的系列或标签不存在。', '逐字引用已选系列与冻结标签。')
        if category and any((item.label, item.series) not in keys for item in style.points):
            _reject('standard_style_points_invalid', 'standardStyle.points', '点样式的期间×分类组合不存在。', '选择存在的长表组合。')
        prepared = prepare_standard_presentation(presentation, document, original_document,
                                                 label, annotation_names, annotation_labels, category)
        if prepared is None:
            _reject('standard_presentation_binding_invalid', 'standardPresentation', '摘要或展示标签未绑定可用的冻结数据。', '摘要用row绑定唯一行，或显式sum汇总可加冻结字段；月份显示方式须与来源对齐方式一致。')
        canvas_policy = canvas.model_dump()
        canvas_policy['style'] = style.model_dump()
        canvas_policy['presentation'] = prepared
        canvas_policy['annotation_specs'] = [item.model_dump() for item in getattr(chart, 'standard_annotations', ())]
        canvas_policy['series_names'] = annotation_names
        canvas_policy['labels'] = annotation_labels
        canvas_policy['zero_baseline'] = axes.zero_baseline
        canvas_policy['total_field'] = total_field
        canvas_policy['advanced'] = advanced
        canvas_policy['axis_factors'] = axis_factors
        canvas_policy['axis_units'] = axis_units
        try:
            factors = [axis_factors[i] if advanced or axes.left_display_unit else displays.get(scope, (1, None))[0]
                       for i in range(len(values))]
            factors = [factor * (100 if meta.get('unit') == '%' and meta.get('isPercent') is False else 1)
                       for factor, meta in zip(factors, metas, strict=True)]
            canvas_policy['band_specs'] = prepare_bands(chart, document, values, form, category, factors, axes)
            notes = [(item['label'] or item['series'])+f"：{item['missing_count']}行范围缺失，未补零"
                     for item in canvas_policy['band_specs'] if item['missing_count']]
            if notes:
                prepared['source_note'] = '\n'.join([*([prepared['source_note']] if prepared['source_note'] else []), *notes])
        except StandardChartEncodingError as error:
            _reject(error.code, error.parameter, str(error), '仅绑定同单位、同期间的冻结上下界；不自动估计范围。')
        config = StandardChartConfig(source.path, source.sha256, chart.source_path, chart.title,
                        form, label, values, category, metas[0].get('unit'),
                        metas[0].get('isPercent'), annotations,
                        axes.model_dump(), metas, total_field, canvas_policy)
        try:
            prepare_dual_stack(chart, config, document)
        except StandardChartEncodingError as error:
            _reject(error.code, error.parameter, str(error), '左侧仅用可加且完整的分项；右侧字段独立换算并排除于左侧总额。')
        configs.append(config)
    for chart, config in zip(plan.charts, configs, strict=True):
        if getattr(chart, 'standard_domains', None) is None and getattr(chart, 'standard_break', None) is None:
            continue
        path = config.input_path
        scope = (path, config.output_path)
        document = (aligned[scope][0] if scope in aligned else
                    json.loads(next(source.content for source in inputs.files if source.path == path)))
        try:
            prepare_standard_break(chart, config, document, displays.get(scope, (1, None)))
            prepare_standard_domains(chart, config, document, displays.get(scope, (1, None)),
                                     profiles_override=summary_profiles.get(chart.chart_id))
        except StandardChartEncodingError as error:
            _reject(error.code, error.parameter, str(error), '范围与刻度使用显示单位；保留所有数据或明确声明并说明显示裁切。')
    has_statistics = any(config.form in {'waterfall', 'boxplot'} for config in configs)
    has_families = any(config.form in FAMILY_FORMS for config in configs)
    if has_families and all(config.form in FAMILY_FORMS for config in configs):
        # 纯图族只拼接实际消费的原有helper；读取/SHA循环复用_BODY原文，身份策略不变。
        return ('CONFIGS = ' + repr([tuple(config) for config in configs]) + '\nALIGNED = ' + repr(aligned) + '\n'
                + PRESENTATION_SCRIPT + _CANVAS_SCRIPT + FAMILY_SCRIPT + _FAMILY_BODY)
    statistics_script = summary_statistics_script(STATISTICS_SCRIPT) if summary_profiles else STATISTICS_SCRIPT
    has_domains = any('domains' in config.policy for config in configs)
    has_breaks = any('broken_axis' in config.policy for config in configs)
    has_dual_stacks = any('dual_stack' in config.policy for config in configs)
    has_horizontal_breaks = any('broken_axis' in config.policy and config.form == 'barh' for config in configs)
    break_script = BREAK_SCRIPT
    break_dispatch = BREAK_DISPATCH
    if has_horizontal_breaks:
        break_script = _patch_once(break_script, '    spec=policy["broken_axis"]\n',
            '    if policy["horizontal"]:\n        return layout_horizontal_standard_break(fig,policy)\n    spec=policy["broken_axis"]\n')
        break_script += HORIZONTAL_BREAK_SCRIPT
        break_dispatch = _patch_once(break_dispatch, '        render_broken_chart(',
            '        (render_horizontal_broken_chart if form == "barh" else render_broken_chart)(')
    layout = _LAYOUT
    if has_domains or has_breaks:
        layout = _patch_once(layout, 'if isinstance(text, Annotation)]', 'if isinstance(text, Annotation) and text.get_visible()]')
    if has_domains:
        layout = _patch_once(layout, '    finish_standard_presentation(fig, policy)',
                                '    apply_standard_domains(fig, policy)\n    finish_standard_presentation(fig, policy)')
    if has_breaks:
        layout = _patch_once(layout, '    if policy["layout"] == "tight":',
                                '    if policy.get("broken_axis"):\n        layout_standard_break(fig, policy)\n    elif policy["layout"] == "tight":')
    body = _patch_once(_BODY, '__STATISTICAL_DISPATCH__', STATISTICS_DISPATCH if has_statistics else '')
    if has_families:
        body = _patch_once(body, '    columns = payload["columns"]\n', '    columns = payload["columns"]\n' + FAMILY_DISPATCH)
    if has_dual_stacks:
        boundary = '    canvas["band_data"] = standard_band_data(payload, canvas)\n'
        body = _patch_once(body, boundary, DUAL_STACK_DISPATCH + boundary)
    if has_breaks:
        boundary = '    canvas["band_data"] = standard_band_data(payload, canvas)\n'
        body = _patch_once(body, boundary, break_dispatch + boundary)
    return ('CONFIGS = ' + repr([tuple(config) for config in configs]) + '\nALIGNED = ' + repr(aligned)
            + '\nAUXILIARY = ' + repr(auxiliary) + '\nDISPLAYS = ' + repr(displays)
            + '\n' + PRESENTATION_SCRIPT + layout + ENCODING_SCRIPT + _ADVANCED
            + (FAMILY_SCRIPT if has_families else '')
            + (statistics_script if has_statistics else '')
            + (DUAL_STACK_SCRIPT if has_dual_stacks else '')
            + (break_script if has_breaks else '')
            + (DOMAIN_SCRIPT if has_domains else '')
            + body)


_LAYOUT = '''def standard_series_name(artist, policy):
    label = artist.get_label()
    for name in policy["series_names"]:
        if label in (name, name + " · 左轴", name + " · 右轴", name + "（独立冻结总额，已对账）"):
            return name
    return "分项合计" if label == "分项合计（服务端求和）" else None

def standard_series_color(name, policy):
    import matplotlib.pyplot as plt
    overrides = {item["series"]: item for item in policy["style"]["series"]}
    if overrides.get(name, {}).get("color"):
        return overrides[name]["color"]
    if name == policy["total_field"] or name == "分项合计":
        return "#1f2937"
    index = policy["series_names"].index(name)
    if policy["style"]["palette"] == "report":
        return ["#3066a3", "#dc884d", "#36856b", "#b55d68", "#8573a6", "#58a3ae", "#b49b53", "#718096"][index % 8]
    palette = plt.get_cmap(policy["style"]["palette"])
    return palette(index / max(1, len(policy["series_names"]) - 1) if palette.N > 20 else index)

def apply_standard_style(fig, policy):
    from matplotlib.container import BarContainer
    from matplotlib.text import Annotation
    import matplotlib.pyplot as plt
    style = policy["style"]
    overrides = {item["series"]: item for item in style["series"]}
    all_axes = list(fig.axes)
    for ax in fig.axes:
        all_axes.extend(ax.child_axes)
    fig.set_facecolor(style["background"])
    for ax in all_axes:
        ax.set_facecolor(style["background"])
        if getattr(ax, "_standard_colorbar", False):
            ax.tick_params(labelsize=policy["tick_font_size"])
            ax.yaxis.label.set_fontsize(style["axis_font_size"])
            continue
        for artist in [*ax.lines, *ax.containers, *ax.collections]:
            if getattr(artist, "_standard_band", False):
                continue
            name = standard_series_name(artist, policy)
            if name is None:
                continue
            item = overrides.get(name, {})
            color = standard_series_color(name, policy)
            targets = artist.patches if isinstance(artist, BarContainer) else [artist]
            for target in targets:
                if not getattr(artist, "_standard_keep_colors", False):
                    target.set_color(color)
                target.set_alpha(item.get("alpha", 1))
                if isinstance(artist, BarContainer):
                    target.set_hatch(item.get("hatch", ""))
                    target.set_edgecolor(color)
                elif artist in ax.lines:
                    target.set_linewidth(item.get("line_width", 2))
                    target.set_linestyle(item.get("line_style", "-"))
                    target.set_marker(item.get("marker", "o"))
                    target.set_markersize(item.get("marker_size", 5))
                    if style["theme"] == "report":
                        target.set_markeredgecolor("white")
                        target.set_markeredgewidth(.8)
            for point in style["points"]:
                if point["series"] != name:
                    continue
                drawn_labels = getattr(artist, "_standard_labels", policy["labels"])
                if point["label"] not in drawn_labels:
                    continue
                index = drawn_labels.index(point["label"])
                if isinstance(artist, BarContainer):
                    artist.patches[index].set_facecolor(point["color"])
                    artist.patches[index].set_edgecolor(point["color"])
                elif artist in ax.lines:
                    ax.scatter([artist.get_xdata()[index]], [artist.get_ydata()[index]],
                               s=point["marker_size"] ** 2, color=point["color"],
                               edgecolors="white", linewidths=1, zorder=6)
                elif getattr(artist, "_standard_scatter", False):
                    from matplotlib.colors import to_rgba
                    import numpy as np
                    count = len(artist.get_offsets())
                    colors = artist.get_facecolors()
                    colors = np.tile(colors, (count, 1)) if len(colors) == 1 else colors.copy()
                    colors[index] = to_rgba(point["color"])
                    artist.set_facecolors(colors)
                    if policy.get("special_form") != "bubble":
                        sizes = artist.get_sizes()
                        sizes = np.full(count, sizes[0]) if len(sizes) == 1 else sizes.copy()
                        sizes[index] = point["marker_size"] ** 2
                        artist.set_sizes(sizes)
        ax.grid(False)
        if style["grid"] != "none":
            ax.grid(axis=style["grid"], which="minor" if policy.get("special_form") == "heatmap" else "major",
                    alpha=style["grid_alpha"], linestyle="--", color="#94a3b8", linewidth=.7)
        ax.set_axisbelow(True)
        ax.title.set_fontsize(style["title_font_size"])
        if style["theme"] == "report":
            ax.title.set_fontweight("bold")
            ax.title.set_color("#1e293b")
            ax.tick_params(axis="both", length=0, pad=8, colors="#475569")
            for key, spine in ax.spines.items():
                spine.set_color("#cbd5e1")
                spine.set_linewidth(.7)
                if key == "top" or key == "right" and len(fig.axes) == 1:
                    spine.set_visible(False)
        ax.xaxis.label.set_fontsize(style["axis_font_size"])
        ax.yaxis.label.set_fontsize(style["axis_font_size"])
        for tick in ax.get_xticklabels():
            tick.set_rotation(style["label_rotation"])
            tick.set_ha("right" if style["label_rotation"] > 0 else "left" if style["label_rotation"] < 0 else "center")
        ax.margins(**({"x": style["value_margin"]} if policy["horizontal"] else {"y": style["value_margin"]}))
        if policy["zero_baseline"]:
            low, high = ax.get_xlim() if policy["horizontal"] else ax.get_ylim()
            (ax.set_xlim if policy["horizontal"] else ax.set_ylim)(min(low, 0), max(high, 0))
        if ax.get_legend() is not None:
            location = style["legend_location"]
            if location == "auto":
                location = ("upper left" if ax is fig.axes[0] else "upper right") if len(fig.axes) > 1 else "best"
            legend_options = {}
            if policy.get("special_form") in {"scatter", "bubble"}:
                legend_options = dict(handles=ax.get_legend().legend_handles,
                                      labels=[text.get_text() for text in ax.get_legend().get_texts()])
            ax.legend(frameon=False, loc=location,
                      ncols=style["legend_columns"], fontsize=style["legend_font_size"], **legend_options)
            for text in ax.get_legend().get_texts():
                for name, item in overrides.items():
                    if item.get("label") and text.get_text() in (name, name + " · 左轴", name + " · 右轴"):
                        text.set_text(text.get_text().replace(name, item["label"], 1))
                        break
        for text in ax.texts:
            text.set_fontsize(style["annotation_font_size"])
            if isinstance(text, Annotation) and not getattr(text, "_standard_custom_position", False):
                text.set_position((style["annotation_offset_x"], style["annotation_offset_y"]))
    if fig._suptitle is not None:
        fig._suptitle.set_fontsize(style["title_font_size"])

'''

_CANVAS_SCRIPT = '''def create_standard_canvas(policy, labels, form, panels=1):
    policy["horizontal"] = form == "barh"
    width, height = policy["width"], policy["height"]
    if policy["size_mode"] == "auto":
        if form == "barh":
            height = min(24, max(height, len(labels) * .42))
        else:
            width = min(20, max(width, len(labels) * .45))
        height = min(24, max(height, panels * 2.5))
    if width * height * policy["dpi"] ** 2 > 24000000:
        raise ValueError("standard_canvas_pixel_budget_exceeded")
    return {"figsize": (width, height), "dpi": policy["dpi"],
            "layout": "constrained" if policy["layout"] == "constrained" else None}

def save_standard_canvas(fig, output_path, policy):
    fig.savefig(output_path, dpi=policy["dpi"],
                bbox_inches="tight" if policy["crop"] == "tight" else None,
                pad_inches=policy["padding"])

'''

_LAYOUT += _CANVAS_SCRIPT + '''def place_standard_legends(fig, policy):
    if policy["style"]["legend_location"] != "auto" or policy["legend_position"] == "outside":
        return
    import math
    from matplotlib.transforms import Bbox
    for ax in fig.axes:
        legend = ax.get_legend()
        if legend is None or policy["legend_position"] == "auto" and len(legend.get_texts()) > 3:
            continue
        points, bars = [], []
        for line in ax.lines:
            if standard_series_name(line, policy) is None:
                continue
            points.extend(ax.transData.transform((x, y)) for x, y in zip(line.get_xdata(), line.get_ydata())
                          if math.isfinite(x) and math.isfinite(y))
        for container in ax.containers:
            if standard_series_name(container, policy) is not None:
                bars.extend(patch.get_window_extent() for patch in container.patches
                            if math.isfinite(patch.get_width()) and math.isfinite(patch.get_height()))
        for collection in ax.collections:
            if not getattr(collection, "_standard_scatter", False):
                continue
            import numpy as np
            offsets = np.ma.filled(collection.get_offsets(), np.nan)
            sizes = collection.get_sizes()
            for index, (x, y) in enumerate(offsets):
                if math.isfinite(x) and math.isfinite(y):
                    px, py = ax.transData.transform((x,y))
                    radius = math.sqrt(sizes[index if len(sizes) > 1 else 0])/2*fig.dpi/72
                    bars.append(Bbox.from_bounds(px-radius,py-radius,2*radius,2*radius))
        best = None
        for location in ("upper right", "upper left", "lower right", "lower left", "upper center", "lower center"):
            legend.set_loc(location)
            fig.canvas.draw()
            bounds = legend.get_window_extent(fig.canvas.get_renderer())
            if not fig.bbox.contains(bounds.x0, bounds.y0) or not fig.bbox.contains(bounds.x1, bounds.y1):
                continue
            score = sum(bounds.contains(x, y) for x, y in points)
            score += sum(Bbox.intersection(bounds, bar) is not None for bar in bars)
            score += 10 * sum(bounds.overlaps(other.get_legend().get_window_extent(fig.canvas.get_renderer()))
                              for other in fig.axes if other is not ax and other.get_legend() is not None)
            if best is None or score < best[0]:
                best = (score, location)
        if best is not None:
            legend.set_loc(best[1])

def finish_standard_layout(fig, policy):
    import textwrap
    from matplotlib.text import Annotation
    apply_standard_style(fig, policy)
    finish_standard_presentation(fig, policy)
    for ax in fig.axes:
        if getattr(ax, "_standard_colorbar", False):
            continue
        if policy.get("categorical_x", not policy["horizontal"]):
            ticks, texts = ax.get_xticks(), ax.get_xticklabels()
            if len(texts) > policy["max_category_ticks"]:
                import math
                stride = math.ceil((len(texts) - 1) / (policy["max_category_ticks"] - 1))
                indexes = list(range(0, len(texts) - 1, stride)) + [len(texts) - 1]
                ax.set_xticks([ticks[index] for index in indexes], [texts[index].get_text() for index in indexes])
        for axis, ticks, setter in ((ax.xaxis, ax.get_xticks(), ax.set_xticks),
                                    (ax.yaxis, ax.get_yticks(), ax.set_yticks)):
            texts = [tick.get_text() for tick in axis.get_ticklabels()]
            is_category_axis = ((axis is ax.xaxis and policy.get("categorical_x", not policy["horizontal"])) or
                                (axis is ax.yaxis and policy.get("categorical_y", policy["horizontal"])))
            if is_category_axis and any(len(text) > policy["label_wrap"] for text in texts):
                setter(ticks, [textwrap.fill(text, width=policy["label_wrap"], break_long_words=True) for text in texts])
            for tick in axis.get_ticklabels():
                tick.set_fontsize(policy["tick_font_size"])
        legend = ax.get_legend()
        if legend is not None and (policy["legend_position"] == "outside" or
                                  policy["legend_position"] == "auto" and len(legend.get_texts()) > 3):
            legend.set_bbox_to_anchor((1.01, 1))
            legend.set_loc("upper left")
    if policy["layout"] == "tight":
        reserved = policy["presentation"]
        top, bottom = reserved["header_bottom"], reserved["footer_top"]
        fig.tight_layout(pad=max(.7, policy["padding"]), rect=(.02, bottom, .98, top))
    elif policy["layout"] == "manual":
        fig.subplots_adjust(left=policy["left"], right=policy["right"],
                            bottom=policy["bottom"], top=policy["top"])
    elif policy["layout"] == "constrained":
        reserved = policy["presentation"]
        fig.get_layout_engine().set(rect=(.02, reserved["footer_top"], .96,
            reserved["header_bottom"] - reserved["footer_top"]))
    fig.canvas.draw()
    place_standard_legends(fig, policy)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    if policy["crop"] == "canvas":
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is not None:
                bounds = legend.get_window_extent(renderer)
                if bounds.x0 < 0 or bounds.y0 < 0 or bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height:
                    raise ValueError("standard_chart_layout_unresolved: 图例超出画布，请增加右侧留白或使用自适应布局")
    annotations = [text for ax in fig.axes for text in ax.texts if isinstance(text, Annotation)]
    obstacles = [ax.get_legend().get_window_extent(renderer).expanded(1.02, 1.05)
                 for ax in fig.axes if ax.get_legend() is not None]
    obstacles.extend(ax.title.get_window_extent(renderer) for ax in fig.axes if ax.title.get_text())
    placed = []
    for annotation in annotations:
        for attempt in range(16):
            # Exclude the leader line: only text glyph bounds define collisions.
            from matplotlib.text import Text
            bounds = Text.get_window_extent(annotation, renderer).expanded(1.04, 1.12)
            if not any(bounds.overlaps(previous) for previous in [*placed, *obstacles]):
                if policy["crop"] == "canvas" and (bounds.x0 < 0 or bounds.y0 < 0 or
                        bounds.x1 > fig.bbox.width or bounds.y1 > fig.bbox.height):
                    raise ValueError("standard_chart_layout_unresolved: 标注超出画布，请扩大尺寸或调整位置")
                placed.append(bounds)
                break
            x, y = annotation.get_position()
            annotation.set_position((x, y + 12))
            annotation.update_positions(renderer)
        else:
            raise ValueError("standard_chart_layout_unresolved: 标注重叠，请减少密度或调整布局")
    for ax in fig.axes:
        if getattr(ax, "_standard_colorbar", False):
            continue
        for axis, categorical in ((ax.xaxis, policy.get("categorical_x", not policy["horizontal"])),
                                  (ax.yaxis, policy.get("categorical_y", policy["horizontal"]))):
            if not categorical:
                continue
            boxes = [text.get_window_extent(renderer) for text in axis.get_ticklabels() if text.get_visible()]
            if any(left.overlaps(right) for index, left in enumerate(boxes) for right in boxes[index + 1:]):
                raise ValueError("standard_chart_layout_unresolved: 分类标签重叠，请扩大画布或减少标签密度")

'''


_ADVANCED = '''def render_advanced(labels, names, raw_series, metadata, policy, form, title, output_path, annotations, canvas):
    import math
    import matplotlib.pyplot as plt
    mode = policy["mode"]
    precision = canvas["style"]["decimals"]
    series = [[value * (100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1) * factor
               for value in values] for values, meta, factor in zip(raw_series, metadata, canvas["axis_factors"], strict=True)]
    metadata = [{**meta, "unit": unit} for meta, unit in zip(metadata, canvas["axis_units"], strict=True)]
    overrides = {item["series"]: item for item in canvas["style"]["series"]}
    geometries = [overrides.get(name, {}).get("geometry", "auto") for name in names]
    geometries = [("line" if form == "line" or mode == "dual" and name in policy["right_fields"] else "bar")
                  if geometry == "auto" else geometry for name, geometry in zip(names, geometries, strict=True)]
    positions = list(range(len(labels)))
    if mode == "panels":
        fig, panels = plt.subplots(1 if form == "barh" else len(series), len(series) if form == "barh" else 1,
                                   sharex=form != "barh", squeeze=False,
                                   **create_standard_canvas(canvas, labels, form, len(series)))
        axes = list(panels.flat)
        targets = axes
    else:
        fig, primary = plt.subplots(**create_standard_canvas(canvas, labels, form))
        axes = [primary]
        secondary = primary.twinx() if mode == "dual" else None
        if secondary is not None:
            axes.append(secondary)
        targets = [secondary if name in policy["right_fields"] else primary for name in names]
    colors = plt.get_cmap("tab10")
    visible_indexes = []
    for index, (name, values, target, meta) in enumerate(zip(names, series, targets, metadata, strict=True)):
        side = "右轴" if mode == "dual" and name in policy["right_fields"] else "左轴"
        caption = f"{name} · {side}" if mode == "dual" else name
        draw_standard_bands(target, canvas, [name], positions)
        visible = list(range(len(labels)))
        if form == "barh":
            visible = [i for i in visible if math.isfinite(values[i])]
            visible.sort(key=lambda i: values[i], reverse=policy["panel_descending"])
            if policy["panel_limit"] is not None:
                visible = visible[:policy["panel_limit"]]
            drawn_labels = [labels[i] for i in visible]
            artist = target.barh(range(len(visible)), [values[i] for i in visible], label=caption)
            artist._standard_labels = drawn_labels
            formatted_labels = standard_label_names(labels, canvas)
            target.set_yticks(range(len(visible)), [formatted_labels[i] for i in visible])
            target.invert_yaxis()
            target.set_xlabel(meta["unit"])
            target.set_xscale(policy["scale"], **({"linthresh": policy["linear_threshold"]} if policy["scale"] == "symlog" else {}))
        elif geometries[index] == "bar":
            members = [i for i, item in enumerate(targets) if item is target and geometries[i] == "bar"]
            group_width = canvas["style"]["bar_group_width"]
            width = group_width / len(members)
            offsets = [position - group_width / 2 + width / 2 + members.index(index) * width for position in positions]
            target.bar(offsets, values, width=width, color=colors(index), label=caption)
        else:
            target.plot(positions, values, marker="o", color=colors(index), label=caption)
        visible_indexes.append(visible)
        if form != "barh":
            target.set_ylabel(f"{side} · {meta['unit']}" if mode == "dual" else meta["unit"])
            target.set_yscale(policy["scale"], **({"linthresh": policy["linear_threshold"]} if policy["scale"] == "symlog" else {}))
            target.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
        if mode == "panels":
            alias = overrides.get(name, {}).get("label") or name
            target.set_title(alias + ("（独立排序）" if form == "barh" else "（独立纵轴）"), fontsize=10)
        missing = [labels[i] for i, value in enumerate(values) if not math.isfinite(value)]
        if missing:
            target.text(.01, .02 + .035 * index, name + " 缺失（保留空位）: " + "、".join(missing),
                        transform=target.transAxes, fontsize=7, color="#64748b")
    for target in axes:
        target.legend(frameon=False, loc="upper left" if target is axes[0] else "upper right")
        target.grid(axis="y", linestyle="--", alpha=.2)
        if policy["scale"] == "log":
            target.set_ylabel(target.get_ylabel() + "（对数刻度）")
        elif policy["scale"] == "symlog":
            if form == "barh":
                target.set_xlabel(target.get_xlabel() + "（对称对数刻度）")
            else:
                target.set_ylabel(target.get_ylabel() + "（对称对数刻度）")
    visible_series = [[value if i in visible_indexes[j] else float("nan") for i, value in enumerate(values)]
                      for j, values in enumerate(series)]
    for number, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            for target in axes:
                target.axvspan(first - .4, last + .4, alpha=.12, color=canvas["annotation_specs"][number]["color"] or "#e8ae53")
            continue
        target = targets[series_index]
        values = series[series_index]
        unit = metadata[series_index]["unit"]
        visible = visible_indexes[series_index]
        finite = [values[i] for i in visible if math.isfinite(values[i])]
        if not finite:
            continue
        if kind == "reference":
            color = canvas["annotation_specs"][number]["color"] or "#b55d68"
            if form == "barh":
                target.axvline(values[first], color=color, linestyle="--", linewidth=1.2)
                target.text(values[first], 1.01, f"参考 {format_standard_number(values[first], precision)}{unit}",
                            transform=target.get_xaxis_transform(), fontsize=8)
                continue
            target.axhline(values[first], color=color, linestyle="--", linewidth=1.2)
            caption = canvas["annotation_specs"][number]["caption"] or f"参考 {labels[first]}"
            target.text(.99, values[first], f"{caption}: {format_standard_number(values[first], precision)}{unit}",
                        transform=target.get_yaxis_transform(), va="bottom", ha="right", fontsize=8, color=color,
                        bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index in visible if math.isfinite(values[index]) and (kind == "values" or
                    values[index] == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, visible_series):
                continue
            coordinate = index
            if form != "barh" and geometries[series_index] == "bar":
                members = [i for i, item in enumerate(targets) if item is target and geometries[i] == "bar"]
                group_width = canvas["style"]["bar_group_width"]
                width = group_width / len(members)
                coordinate = index - group_width / 2 + width / 2 + members.index(series_index) * width
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            caption = canvas["annotation_specs"][number]["caption"] or overrides.get(names[series_index], {}).get("label") or names[series_index]
            text = f"{caption}: {format_standard_number(values[index], precision)}{unit}" + (" · " + extra if extra else "")
            xy = (values[index], visible.index(index)) if form == "barh" else (coordinate, values[index])
            standard_annotation(target, text, xy, canvas, number,
                                standard_series_color(names[series_index], canvas))
    if mode == "zoom":
        first = labels.index(policy["zoom_start"])
        last = labels.index(policy["zoom_end"])
        inset = axes[0].inset_axes(policy["zoom_bounds"])
        draw_standard_bands(inset, canvas, names, positions[first:last+1], first, last)
        local_values = []
        for index, values in enumerate(series):
            if geometries[index] == "bar":
                group_width = canvas["style"]["bar_group_width"]
                members = [i for i, geometry in enumerate(geometries) if geometry == "bar"]
                width = group_width / len(members)
                offsets = [position - group_width / 2 + width / 2 + members.index(index) * width for position in positions[first:last + 1]]
                artist = inset.bar(offsets, values[first:last + 1], width=width, color=colors(index), label=names[index])
            else:
                artist = inset.plot(positions[first:last + 1], values[first:last + 1], marker="o", color=colors(index), label=names[index])[0]
            artist._standard_labels = labels[first:last + 1]
            local_values.extend(value for value in values[first:last + 1] if math.isfinite(value))
        for band in canvas.get("band_data", []):
            local_values.extend(value for value in [*band["lower"][first:last+1], *band["upper"][first:last+1]]
                                if math.isfinite(value))
        if not local_values:
            raise ValueError("standard_chart_empty_zoom")
        low, high = min(local_values), max(local_values)
        padding = (high - low) * .1 or abs(high) * .1 or 1
        edge = canvas["style"]["bar_group_width"] / 2 + .08 if "bar" in geometries else .2
        inset.set_xlim(first - edge, last + edge)
        if policy["scale"] == "log":
            inset.set_yscale("log")
            inset.set_ylim(low / 1.2, high * 1.2)
        else:
            if policy["scale"] == "symlog":
                inset.set_yscale("symlog", linthresh=policy["linear_threshold"])
            inset.set_ylim(low - padding, high + padding)
        inset.set_xticks(positions[first:last + 1], standard_label_names(labels, canvas)[first:last + 1], rotation=45, fontsize=7)
        inset.set_title("局部放大 · " + metadata[0]["unit"], fontsize=9)
        axes[0].axvspan(first - .2, last + .2, color="#f59e0b", alpha=.1)
    fig.suptitle(title)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
    plt.close(fig)

'''


_BODY = '''import hashlib
import json
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
for input_path, digest, output_path, title, form, label_column, value_columns, category_column, unit, is_percent, annotations, axes_policy, metadata, total_field, canvas in CONFIGS:
    precision = canvas["style"]["decimals"]
    with open(input_path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart input identity changed")
    payload = json.loads(raw)
    scope = (input_path, output_path)
    if scope in ALIGNED:
        payload, dependencies = ALIGNED[scope]
        for dependency_path, dependency_digest in dependencies:
            with open(dependency_path, "rb") as handle:
                dependency_raw = handle.read()
            if hashlib.sha256(dependency_raw).hexdigest() != dependency_digest:
                raise ValueError("aligned chart input identity changed")
    columns = payload["columns"]
    if form in {"scatter", "bubble", "heatmap"}:
        render_encoded_chart(payload, canvas, form, title, output_path)
        continue
__STATISTICAL_DISPATCH__    canvas["band_data"] = standard_band_data(payload, canvas)
    label_index = columns.index(label_column)
    labels = list(dict.fromkeys(row[label_index] for row in payload["rows"]))
    if category_column:
        category_index = columns.index(category_column)
        names = list(dict.fromkeys(row[category_index] for row in payload["rows"]))
        cells = {(row[label_index], row[category_index]): row[columns.index(value_columns[0])]
                 for row in payload["rows"]}
        series = [[cells.get((label, name), float("nan")) for label in labels] for name in names]
    else:
        names = value_columns
        series = [[row[columns.index(column)] if row[columns.index(column)] is not None else float("nan")
                   for row in payload["rows"]] for column in names]
    if canvas["advanced"]:
        render_advanced(labels, names, series, metadata, axes_policy, form, title, output_path, annotations, canvas)
        continue
    if unit == "%" and is_percent is False:
        series = [[value * 100 for value in values] for values in series]
    if scope in DISPLAYS:
        factor, unit = DISPLAYS[scope]
        series = [[value * factor for value in values] for values in series]
    fig, ax = plt.subplots(**create_standard_canvas(canvas, labels, form))
    draw_standard_bands(ax, canvas, names, positions=list(range(len(labels))))
    positions = list(range(len(labels)))
    if form == "stacked-area":
        ax.stackplot(positions, *series, labels=names)
    else:
        bottom = [0.0] * len(labels)
        group_width = canvas["style"]["bar_group_width"]
        width = group_width / len(series)
        for index, (name, values) in enumerate(zip(names, series, strict=True)):
            if name == total_field:
                continue
            if form == "line":
                ax.plot(positions, values, marker="o", label=name)
            elif form in {"stacked-bar", "stacked-total"}:
                ax.bar(positions, values, width=group_width, bottom=bottom, label=name)
                bottom = [left + right for left, right in zip(bottom, values, strict=True)]
            else:
                offsets = [position - group_width / 2 + width / 2 + index * width for position in positions]
                if form == "barh":
                    ax.barh(offsets, values, height=width, label=name)
                else:
                    ax.bar(offsets, values, width=width, label=name)
    if form == "stacked-total":
        totals = (series[names.index(total_field)] if total_field else
                  [math.fsum(values[index] for values in series) for index in positions])
        caption = total_field + "（独立冻结总额，已对账）" if total_field else "分项合计（服务端求和）"
        ax.plot(positions, totals, marker="o", color="black", label=caption)
    if form == "barh":
        ax.set_yticks(positions, standard_label_names(labels, canvas))
        ax.invert_yaxis()
        ax.set_xlabel(unit or "")
    else:
        ax.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
        ax.set_ylabel(unit or "")
    if len(series) > 1 or form == "stacked-total":
        ax.legend(frameon=False)
    for index, (name, values) in enumerate(zip(names, series, strict=True)):
        missing = [labels[i] for i, value in enumerate(values) if not math.isfinite(value)]
        if missing and axes_policy["allow_nulls"]:
            ax.text(.01, .02 + .035 * index, name + " 缺失（保留空位）: " + "、".join(missing),
                    transform=ax.transAxes, fontsize=7, color="#64748b")
    for annotation_index, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            span = ax.axhspan if form == "barh" else ax.axvspan
            span(first - 0.4, last + 0.4, color=canvas["annotation_specs"][annotation_index]["color"] or "#e8ae53", alpha=0.12)
            continue
        values = series[series_index]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        if kind == "reference":
            draw = ax.axvline if form == "barh" else ax.axhline
            color = canvas["annotation_specs"][annotation_index]["color"] or "#b55d68"
            draw(values[first], linestyle="--", color=color, alpha=0.8, linewidth=1.2)
            caption = canvas["annotation_specs"][annotation_index]["caption"] or f"参考 {labels[first]} · {names[series_index]}"
            text = f"{caption}: {format_standard_number(values[first], precision)}{unit or ''}"
            if form == "barh":
                ax.text(values[first], 1.02, text, transform=ax.get_xaxis_transform(),
                        va="bottom", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            else:
                ax.text(.99, values[first], text, transform=ax.get_yaxis_transform(),
                        va="bottom", ha="right", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if math.isfinite(value) and
                    (kind == "values" or value == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, series):
                continue
            value = values[index]
            coordinate = index
            height = value
            if form in {"stacked-bar", "stacked-area", "stacked-total"} and names[series_index] != total_field:
                height += sum(previous[index] for previous_name, previous in zip(names[:series_index], series[:series_index], strict=True)
                              if previous_name != total_field)
            elif form in {"bar", "barh"}:
                coordinate = index - group_width / 2 + group_width / (2 * len(series)) + series_index * group_width / len(series)
            xy = (height, coordinate) if form == "barh" else (coordinate, height)
            prefix = {"peak": "峰值 ", "trough": "谷值 ", "point": "重点 "}.get(kind, "")
            caption = canvas["annotation_specs"][annotation_index]["caption"]
            if caption:
                prefix = caption + " "
            auxiliary_text = []
            for field in AUXILIARY.get(scope, ()):
                matching = [row for row in payload["rows"] if row[label_index] == labels[index]
                            and (not category_column or row[category_index] == names[series_index])]
                if len(matching) != 1:
                    raise ValueError("annotation row is ambiguous")
                meta = payload["columnMeta"][field]
                auxiliary_value = matching[0][columns.index(field)]
                if meta["unit"] == "%" and meta.get("isPercent") is False:
                    auxiliary_value *= 100
                auxiliary_text.append(f"{field}: {format_standard_number(auxiliary_value, precision)}{meta['unit']}")
            suffix = " · " + " / ".join(auxiliary_text) if auxiliary_text else ""
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            if extra:
                suffix += " · " + extra
            color = standard_series_color(names[series_index], canvas) if canvas["style"]["annotation_color"] == "series" else "#475569"
            point = next((item for item in canvas["style"]["points"] if item["series"] == names[series_index] and item["label"] == labels[index]), None)
            if point is not None:
                color = point["color"]
            standard_annotation(ax, f"{prefix}{format_standard_number(value, precision)}{unit or ''}{suffix}", xy,
                                canvas, annotation_index, color)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
    plt.close(fig)
'''

# 逐字复用正式输入读取与全部依赖SHA检查，只去除未消费的旧几何分支。
_FAMILY_BODY = _BODY[:_BODY.index('    columns = payload["columns"]\n')] + '''    render_family_chart(payload, canvas, form, title, output_path)
'''
