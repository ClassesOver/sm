"""五图的冻结契约和真实 Matplotlib 几何回归。"""
import json
import math

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_contract import plan_and_inputs
from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.standard_visualization import standard_visualization_preflight


def table(rows=None, *, unit='元', additive=True):
    meta = {'unit': unit}
    if additive:
        meta['measureSemantic'] = {'aggregation': 'sum', 'additiveAcross': ['period', 'source', 'target']}
    return {'columns': ['period', 'value'], 'rows': rows or [['甲', 30], ['乙', 20], ['零', 0]],
            'columnMeta': {'value': meta}}


def make(form, documents=None, **options):
    return plan_and_inputs(documents or [table()], standardForm=form, **options)


@pytest.mark.parametrize('form,width', [('pie', None), ('donut', .35)])
def test_composition_wedges_preserve_prefilter_denominator_and_zero_legend(render, form, width):
    plan, inputs = make(form, standardPresentation={'order': {'mode': 'value', 'field': 'value', 'descending': True, 'limit': 1}})
    axes = render(plan, inputs).axes[0]
    wedges = [patch for patch in axes.patches if type(patch).__name__ == 'Wedge']
    assert len(wedges) == 1
    assert wedges[0].theta2 - wedges[0].theta1 == pytest.approx(216)
    assert wedges[0].width == width
    assert any('占绑定范围合计' in text.get_text() for text in axes.figure.texts)
    all_plan, all_inputs = make(form)
    axes = render(all_plan, all_inputs).axes[0]
    assert [patch.theta2 - patch.theta1 for patch in axes.patches] == pytest.approx([216, 144, 0])
    assert any('零' in text.get_text() for text in axes.get_legend().get_texts())


def test_reference_scalar_uses_raw_auxiliary_row_not_main_alignment(render):
    denominator = {'columns': ['期间', '合计'], 'rows': [['本期', 100], ['同期', 100]], 'columnMeta': {'合计': {'unit': '元'}}}
    ref = {'sourceIndex': 1, 'field': '合计', 'labelField': '期间', 'label': '本期'}
    plan, inputs = make('pie', [table(), denominator], standardComposition={'denominator': {'mode': 'reference', 'ref': ref}})
    axes = render(plan, inputs).axes[0]
    assert [p.theta2 - p.theta1 for p in axes.patches] == pytest.approx([108, 72, 0])
    assert standard_visualization_preflight(plan, inputs).warnings
    plan, inputs = make('pie', [table(), denominator], standardComposition={'denominator': {'mode': 'reference', 'ref': {'sourceIndex': 1, 'field': '合计'}}})
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None and result.diagnostic['code'] == 'standard_scalar_ambiguous'


@pytest.mark.parametrize('fault', ['negative', 'duplicate', 'zero', 'nonadditive', 'percentage', 'overflow', 'unused', 'identity'])
def test_composition_refuses_invalid_geometry_or_unproven_additivity(fault):
    doc = table()
    docs, options = [doc], {}
    if fault == 'negative': doc['rows'][0][1] = -1
    elif fault == 'duplicate': doc['rows'][1][0] = '甲'
    elif fault == 'zero': doc['rows'] = [['甲', 0]]
    elif fault == 'nonadditive': doc['columnMeta']['value'].pop('measureSemantic')
    elif fault == 'percentage': doc['columnMeta']['value'].update(unit='%', isPercent=True)
    elif fault == 'overflow':
        docs += [table([['总', 10]])]
        options['standardComposition'] = {'denominator': {'mode': 'reference', 'ref': {'sourceIndex': 1, 'field': 'value'}}}
    else: docs += [table([['总', 100]])]
    plan, inputs = make('pie', docs, **options)
    if fault == 'identity':
        inputs = inputs.__class__(files=inputs.files, entries=tuple({**e, 'sha256': '0'*64} if i else e for i,e in enumerate(inputs.entries)))
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None and result.diagnostic is not None


def radar_table(values=(2, 4, 6), units=('元', '元', '元')):
    return {'columns': ['period', 'a', 'b', 'c'], 'rows': [['甲', *values]],
            'columnMeta': {field: {'unit': unit} for field, unit in zip(('a', 'b', 'c'), units)}}


def test_radar_polar_closed_vertices_follow_explicit_axis_order(render):
    plan, inputs = make('radar', [radar_table()], standardValueFields=['c', 'a', 'b'])
    ax = render(plan, inputs).axes[0]
    assert ax.name == 'polar'
    assert list(ax.lines[0].get_ydata()) == [6, 2, 4, 6]
    assert list(ax.lines[0].get_xdata()) == pytest.approx([0, 2*math.pi/3, 4*math.pi/3, 0])
    assert [t.get_text() for t in ax.get_xticklabels()] == ['c（元）', 'a（元）', 'b（元）']


@pytest.mark.parametrize('form', ['radar', 'funnel'])
@pytest.mark.parametrize('reverse', [False, True])
def test_full_family_label_selection_preserves_all_entities_and_source_order(render, form, reverse):
    document = radar_table() if form == 'radar' else table()
    if form == 'radar':
        document['rows'].append(['乙', 3, 5, 7])
    labels = ['甲', '乙'] if form == 'radar' else ['甲', '乙', '零']
    if reverse:
        labels.reverse()
    options = {'standardLabels': labels}
    if form == 'radar':
        options['standardValueFields'] = ['a', 'b', 'c']
    plan, inputs = make(form, [document], **options)
    ax = render(plan, inputs).axes[0]
    if form == 'radar':
        assert [list(line.get_ydata()) for line in ax.lines] == [[2, 4, 6, 2], [3, 5, 7, 3]]
        assert [text.get_text() for text in ax.get_legend().get_texts()] == ['甲', '乙']
    else:
        assert [patch.get_width() for patch in ax.patches] == [30, 20, 0]
        assert [text.get_text() for text in ax.get_yticklabels()] == ['甲', '乙', '零']


@pytest.mark.parametrize('form', ['radar', 'funnel'])
@pytest.mark.parametrize('labels', [['甲'], ['甲', '乙', '外部'], ['甲', '乙', '乙']])
def test_family_label_selection_never_drops_or_invents_entities(form, labels):
    document = radar_table() if form == 'radar' else table()
    if form == 'radar':
        document['rows'].append(['乙', 3, 5, 7])
    options = {'standardLabels': labels}
    if form == 'radar':
        options['standardValueFields'] = ['a', 'b', 'c']
    plan, inputs = make(form, [document], **options)
    assert standard_visualization_preflight(plan, inputs).source is None


def test_single_entity_radar_full_label_selection_stays_on_standard_route(render):
    plan, inputs = make('radar', [radar_table()], standardLabels=['甲'],
                        standardValueFields=['a', 'b', 'c'])
    ax = render(plan, inputs).axes[0]
    assert list(ax.lines[0].get_ydata()) == [2, 4, 6, 2]


@pytest.mark.parametrize('form', ['radar', 'funnel'])
@pytest.mark.parametrize('order', [{'mode': 'value', 'field': 'a'}, {'mode': 'source', 'limit': 1}])
def test_full_family_selection_cannot_bypass_order_restrictions(form, order):
    document = radar_table() if form == 'radar' else table()
    labels = ['甲'] if form == 'radar' else ['甲', '乙', '零']
    options = {'standardLabels': labels, 'standardPresentation': {'order': order}}
    if form == 'radar':
        options['standardValueFields'] = ['a', 'b', 'c']
    plan, inputs = make(form, [document], **options)
    assert standard_visualization_preflight(plan, inputs).source is None


@pytest.mark.parametrize('values', [(-5, 0, 5), (-9, -8, -7)])
def test_radar_negative_values_require_frozen_scale_and_keep_original_labels(render, values):
    doc = radar_table(values)
    plan, inputs = make('radar', [doc], standardValueFields=['a', 'b', 'c'])
    assert standard_visualization_preflight(plan, inputs).source is None
    endpoints = {'columns': ['min', 'max'], 'rows': [[-10, 10]], 'columnMeta': {'min': {'unit': '元'}, 'max': {'unit': '元'}}}
    scales = [{'field': f, 'min': {'sourceIndex': 1, 'field': 'min'}, 'max': {'sourceIndex': 1, 'field': 'max'}} for f in ('a', 'b', 'c')]
    plan, inputs = make('radar', [doc, endpoints], standardValueFields=['a', 'b', 'c'], standardRadar={'scales': scales})
    ax = render(plan, inputs).axes[0]
    assert list(ax.lines[0].get_ydata())[:3] == pytest.approx([(v+10)/20 for v in values])
    assert str(values[0]) in '\n'.join(t.get_text() for t in ax.texts)


@pytest.mark.parametrize('fault', ['mixed_units', 'too_many_axes', 'too_many_entities', 'out_of_range'])
def test_radar_never_infers_scales_or_silently_truncates(fault):
    doc = radar_table()
    options = {'standardValueFields': ['a', 'b', 'c']}
    docs = [doc]
    if fault == 'mixed_units': doc['columnMeta']['b']['unit'] = '人次'
    elif fault == 'too_many_axes': options['standardValueFields'] = ['a', 'b']
    elif fault == 'too_many_entities': doc['rows'] = [[str(i), 1, 2, 3] for i in range(9)]
    else:
        docs += [{'columns': ['lo', 'hi'], 'rows': [[0, 1]], 'columnMeta': {'lo': {'unit': '元'}, 'hi': {'unit': '元'}}}]
        options['standardRadar'] = {'scales': [{'field': f, 'min': {'sourceIndex': 1, 'field': 'lo'}, 'max': {'sourceIndex': 1, 'field': 'hi'}} for f in ('a','b','c')]}
    plan, inputs = make('radar', docs, **options)
    assert standard_visualization_preflight(plan, inputs).source is None


def test_funnel_keeps_nonmonotonic_widths_and_ratios_are_not_conversion_rates(render):
    plan, inputs = make('funnel', [table([['首', 10], ['次', 20], ['零', 0]])], standardFunnel={'ratioBase': 'previous'})
    result = standard_visualization_preflight(plan, inputs)
    assert any(w['code'] == 'standard_funnel_nonmonotonic' for w in result.warnings)
    ax = render(plan, inputs).axes[0]
    assert [p.get_width() for p in ax.patches] == [10, 20, 0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ['首', '次', '零']
    text = '\n'.join(t.get_text() for t in ax.texts)
    assert '阶段值比' in text and '200.00%' in text and '转化率' not in text


@pytest.mark.parametrize('order', [{'mode': 'value', 'field': 'value'}, {'mode': 'source', 'limit': 1}, {'mode': 'reverse'}])
def test_funnel_refuses_flow_reordering_or_topn(order):
    plan, inputs = make('funnel', standardPresentation={'order': order})
    assert standard_visualization_preflight(plan, inputs).source is None


def sankey(rows=None):
    doc = table()
    return {**doc, 'columns': ['source', 'target', 'value'], 'rows': rows or [['A','B',4], ['A','C',6], ['B','D',4], ['C','D',6]]}


def flow(docs=None, **options):
    return make('sankey', docs or [sankey()], standardLabelField=None, standardEncoding={'xField':'source', 'yField':'target', 'valueField':'value'}, **options)


def test_sankey_diamond_parallel_and_cross_layer_edges_reach_all_original_endpoints(render):
    rows = [['A','B',4], ['A','C',6], ['B','D',2], ['B','D',2], ['C','D',6], ['A','D',1], ['X','Y',3]]
    plan, inputs = flow([sankey(rows)])
    ax = render(plan, inputs).axes[0]
    nodes = {p.get_gid()[5:]:p for p in ax.patches if (p.get_gid() or '').startswith('node:')}
    edges = [p for p in ax.patches if (p.get_gid() or '').startswith('edge:')]
    assert len(nodes) == 6 and len(edges) == 7
    for edge, (source,target,value) in zip(edges, rows):
        vertices = edge.get_path().vertices
        assert vertices[0][0] == pytest.approx(nodes[source].get_x()+nodes[source].get_width())
        assert vertices[3][0] == pytest.approx(nodes[target].get_x())
        assert abs(vertices[0][1]-vertices[-2][1]) == pytest.approx(value)
        assert abs(vertices[3][1]-vertices[4][1]) == pytest.approx(value)
    assert edges[2].get_path().vertices[0][1] != edges[3].get_path().vertices[0][1]
    cross = edges[5]
    for name in ('B','C'):
        node = nodes[name]
        assert not cross.get_path().intersects_bbox(node.get_bbox(), filled=True)


def test_sankey_zero_edges_still_define_topology_and_all_zero_is_explanatory(render):
    plan, inputs = flow([sankey([['A','B',0], ['B','A',0]])])
    assert standard_visualization_preflight(plan, inputs).source is None
    plan, inputs = flow([sankey([['A','B',0]])])
    ax = render(plan, inputs).axes[0]
    assert not [p for p in ax.patches if (p.get_gid() or '').startswith('edge:')]
    assert '无正流量' in '\n'.join(t.get_text() for t in ax.texts)
    assert 'A → B' in '\n'.join(t.get_text() for t in ax.texts)


@pytest.mark.parametrize('stage', [True, -1, 1.5, '1'])
def test_sankey_node_stage_requires_frozen_nonboolean_integer(stage):
    nodes={'columns':['id','name','stage'], 'rows':[['A','同名',0],['B','同名',stage]]}
    plan, inputs = flow([sankey([['A','B',1]]), nodes], standardSankey={'nodes': {'sourceIndex':1,'idField':'id','labelField':'name','stageField':'stage'}})
    assert standard_visualization_preflight(plan, inputs).source is None


def test_family_schema_rejects_scalar_constants_partial_selectors_and_unknown_fields():
    for ref in ({'sourceIndex':True,'field':'value'}, {'sourceIndex':0,'field':'value','label':'甲'}, {'sourceIndex':0,'field':'value','value':100}):
        with pytest.raises(ValidationError):
            make('pie', standardComposition={'denominator': {'mode':'reference','ref':ref}})


def test_composition_explicit_sources_keep_auxiliary_indices_and_full_denominator(render):
    unused_first = {'columns':['total'], 'rows':[[100]], 'columnMeta':{'total':{'unit':'元'}}}
    plan, inputs = make('pie', [unused_first, table()], standardLabelField='period', standardValueFields=['份额'],
        standardSources=[{'sourceIndex':1,'labelField':'period','valueField':'value','seriesName':'份额'}],
        standardComposition={'denominator':{'mode':'reference','ref':{'sourceIndex':0,'field':'total'}}},
        standardLabels=['甲'])
    ax=render(plan,inputs).axes[0]
    assert [p.theta2-p.theta1 for p in ax.patches] == pytest.approx([108])


def test_composition_percentage_requires_registered_global_base_and_scale(render):
    doc=table([['甲',.3],['乙',.2]],unit='%',additive=False)
    doc['columnMeta']['value'].update(isPercent=False,commonDenominator={'sourceIndex':1,'field':'total'},exclusiveAcross=['period'])
    total={'columns':['total'],'rows':[[100]],'columnMeta':{'total':{'unit':'人次'}}}
    plan,inputs=make('pie',[doc,total])
    ax=render(plan,inputs).axes[0]
    assert [p.theta2-p.theta1 for p in ax.patches] == pytest.approx([216,144])
    doc['columnMeta']['value']['isPercent']=True
    doc['rows']=[['甲',30],['乙',20]]
    plan,inputs=make('pie',[doc,total])
    assert [p.theta2-p.theta1 for p in render(plan,inputs).axes[0].patches] == pytest.approx([216,144])


def test_composition_mean_transform_cannot_inherit_false_additivity():
    doc=table([['甲',10],['甲',30],['乙',20]])
    plan,inputs=make('pie',[doc],standardView={'kind':'group','labelField':'period','valueFields':['value'],'aggregation':'mean'})
    result=standard_visualization_preflight(plan,inputs)
    assert result.source is None
    assert result.diagnostic['code']=='standard_family_additivity_unproven'


def test_family_execution_rechecks_all_auxiliary_sha(tmp_path,monkeypatch):
    total={'columns':['total'],'rows':[[100]],'columnMeta':{'total':{'unit':'元'}}}
    plan,inputs=make('pie',[table(),total],standardComposition={'denominator':{'mode':'reference','ref':{'sourceIndex':1,'field':'total'}}})
    script=standard_visualization_preflight(plan,inputs).source
    assert script is not None
    monkeypatch.chdir(tmp_path)
    for file in inputs.files: (tmp_path/file.path).write_bytes(file.content)
    (tmp_path/inputs.files[1].path).write_bytes(b'{}')
    with pytest.raises(ValueError,match='identity changed'): exec(script,{})


def test_radar_mixed_axes_with_explicit_frozen_units_render_original_values(render):
    doc=radar_table((2,4,6),('元','人次','%'))
    bounds={'columns':['lo_a','hi_a','lo_b','hi_b','lo_c','hi_c'],'rows':[[0,10,0,20,0,100]],
            'columnMeta':{field:{'unit':unit} for field,unit in zip(['lo_a','hi_a','lo_b','hi_b','lo_c','hi_c'],['元','元','人次','人次','%','%'])}}
    scales=[{'field':f,'min':{'sourceIndex':1,'field':'lo_'+f},'max':{'sourceIndex':1,'field':'hi_'+f}} for f in ('a','b','c')]
    plan,inputs=make('radar',[doc,bounds],standardValueFields=['a','b','c'],standardRadar={'scales':scales})
    ax=render(plan,inputs).axes[0]
    assert list(ax.lines[0].get_ydata())==pytest.approx([.2,.2,.06,.2])
    assert [t.get_text() for t in ax.get_xticklabels()]==['a（元）','b（人次）','c（%）']


def test_radar_rejects_value_order_instead_of_assigning_entity_ranks():
    plan,inputs=make('radar',[radar_table()],standardValueFields=['a','b','c'],standardPresentation={'order':{'mode':'value','field':'a'}})
    assert standard_visualization_preflight(plan,inputs).source is None


def test_funnel_wide_explicit_order_and_zero_denominator_keep_all_stages(render):
    doc={'columns':['首','次','尾'],'rows':[[0,20,10]],'columnMeta':{f:{'unit':'元'} for f in ('首','次','尾')}}
    plan,inputs=make('funnel',[doc],standardLabelField=None,standardValueFields=['首','次','尾'],standardFunnel={'ratioBase':'previous'})
    ax=render(plan,inputs).axes[0]
    assert [p.get_width() for p in ax.patches]==[0,20,10]
    assert '未定义（分母为零）' in '\n'.join(t.get_text() for t in ax.texts)


def test_sankey_full_capacity_and_over_budget_are_not_truncated():
    rows=[[f'N{i}',f'N{j}',1] for i in range(30) for j in range(30,46)]
    # 后14个节点与前46个同属DAG，逐行保留480条边。
    rows[-14:]=[[f'N{i}',f'N{46+i}',1] for i in range(14)]
    plan,inputs=flow([sankey(rows)])
    result=standard_visualization_preflight(plan,inputs)
    assert result.source is not None
    assert len(rows)==480
    plan,inputs=flow([sankey([*rows,['N0','N59',1]])])
    assert standard_visualization_preflight(plan,inputs).diagnostic['code']=='standard_sankey_capacity'
    plan,inputs=flow([sankey([[f'N{i}',f'N{i+1}',1] for i in range(60)])])
    assert standard_visualization_preflight(plan,inputs).diagnostic['code']=='standard_sankey_capacity'


def test_sankey_nodes_keep_duplicate_display_names_and_sparse_stage_order(render):
    nodes={'columns':['id','name','stage'],'rows':[['A','同名',10],['B','同名',100]]}
    plan,inputs=flow([sankey([['A','B',2]]),nodes],standardSankey={'nodes':{'sourceIndex':1,'idField':'id','labelField':'name','stageField':'stage'}})
    ax=render(plan,inputs).axes[0]
    actual=[p for p in ax.patches if (p.get_gid() or '').startswith('node:')]
    assert len(actual)==2 and actual[1].get_x()-actual[0].get_x()==3


@pytest.mark.parametrize('fault',['nonadditive','local_percent','backward_stage','missing_node','duplicate_node','negative'])
def test_sankey_refuses_unproven_flow_or_invalid_node_identity(fault):
    doc=sankey([['A','B',2]])
    docs,options=[doc],{}
    if fault=='nonadditive': doc['columnMeta']['value'].pop('measureSemantic')
    elif fault=='local_percent': doc['columnMeta']['value'].update(unit='%',isPercent=True)
    elif fault=='negative': doc['rows'][0][2]=-2
    else:
        rows=[['A',1],['B',0]] if fault=='backward_stage' else [['A',0]] if fault=='missing_node' else [['A',0],['A',1],['B',1]]
        docs.append({'columns':['id','stage'],'rows':rows})
        options['standardSankey']={'nodes':{'sourceIndex':1,'idField':'id','stageField':'stage'}}
    assert standard_visualization_preflight(*flow(docs,**options)).source is None


@pytest.mark.parametrize('options',[{'standardAxes':{'zeroBaseline':True}}, {'standardDomains':{'left':{'min':0,'max':1}}}, {'standardAnnotations':[{'kind':'reference','label':'甲'}]}])
def test_families_reject_unsupported_parameters_instead_of_ignoring_them(options):
    assert standard_visualization_preflight(*make('pie',**options)).source is None


def test_unused_auxiliary_cannot_authorize_itself_with_its_own_metadata():
    foreign=table([['外部',10]],unit='%')
    foreign['columnMeta']['value'].update(isPercent=True,commonDenominator={'sourceIndex':1,'field':'value'},exclusiveAcross=['period'])
    result=standard_visualization_preflight(*make('pie',[table(),foreign]))
    assert result.source is None and result.diagnostic['code']=='standard_source_unused'


def test_sankey_registered_percentage_uses_one_global_basis_and_no_local_renormalization(render):
    doc=sankey([['A','B',.3],['A','C',.2]])
    doc['columnMeta']['value']={'unit':'%','isPercent':False,'commonDenominator':{'sourceIndex':1,'field':'total'},'exclusiveAcross':['source','target']}
    total={'columns':['total'],'rows':[[100]],'columnMeta':{'total':{'unit':'人次'}}}
    ax=render(*flow([doc,total])).axes[0]
    edges=[p for p in ax.patches if (p.get_gid() or '').startswith('edge:')]
    assert [abs(p.get_path().vertices[0][1]-p.get_path().vertices[-2][1]) for p in edges]==pytest.approx([30,20])


def test_sankey_capacity_renders_all_480_edges_and_60_nodes(render):
    rows=[[f'N{i}',f'N{j}',1] for i in range(30) for j in range(30,46)]
    rows[-14:]=[[f'N{i}',f'N{46+i}',1] for i in range(14)]
    ax=render(*flow([sankey(rows)])).axes[0]
    assert len([p for p in ax.patches if (p.get_gid() or '').startswith('edge:')])==480
    assert len([p for p in ax.patches if (p.get_gid() or '').startswith('node:')])==60


def test_sankey_mixed_zero_nodes_remain_text_only_and_imbalance_is_warning(render):
    result=standard_visualization_preflight(*flow([sankey([['A','B',5],['B','C',3],['X','Y',0]])]))
    warning=next(w for w in result.warnings if w['code']=='standard_sankey_imbalance')
    assert warning['nodeId']=='B' and warning['inflow']==5 and warning['outflow']==3 and warning['delta']==2
    ax=render(*flow([sankey([['A','B',5],['B','C',3],['X','Y',0]])])).axes[0]
    assert {p.get_gid() for p in ax.patches if (p.get_gid() or '').startswith('node:')}=={'node:A','node:B','node:C'}
    assert 'X（零流量）' in [t.get_text() for t in ax.texts]


def test_sankey_explicit_group_sum_reuses_pipeline_for_parallel_edges(render):
    plan,inputs=flow([sankey([['A','B',2],['A','B',3]])],standardSteps=[{'view':{'kind':'group','labelField':'source','groupBy':['target'],'valueFields':['value'],'aggregation':'sum'}}])
    ax=render(plan,inputs).axes[0]
    edges=[p for p in ax.patches if (p.get_gid() or '').startswith('edge:')]
    assert len(edges)==1
    assert abs(edges[0].get_path().vertices[0][1]-edges[0].get_path().vertices[-2][1])==5


def test_explicit_source_alignment_maps_only_registered_additive_label_dimension(render):
    doc=table()
    doc['columns'][0]='area'
    doc['columnMeta']['value']['measureSemantic']['additiveAcross']=['area']
    plan,inputs=make('pie',[doc],standardValueFields=['份额'],standardLabelField='period',standardSources=[{'sourceIndex':0,'labelField':'area','valueField':'value','seriesName':'份额'}])
    assert len(render(plan,inputs).axes[0].patches)==3
    doc['columnMeta']['value']['measureSemantic']['additiveAcross']=['period']
    plan,inputs=make('pie',[doc],standardValueFields=['份额'],standardLabelField='period',standardSources=[{'sourceIndex':0,'labelField':'area','valueField':'value','seriesName':'份额'}])
    assert standard_visualization_preflight(plan,inputs).source is None


def test_sankey_long_cross_layer_edge_does_not_touch_any_intermediate_node(render):
    rows=[[f'N{i}',f'N{i+1}',1000] for i in range(58)]
    rows.append(['N0','N58',1])
    ax=render(*flow([sankey(rows)])).axes[0]
    nodes={p.get_gid()[5:]:p for p in ax.patches if (p.get_gid() or '').startswith('node:')}
    cross=next(p for p in ax.patches if p.get_gid()=='edge:58')
    assert all(not cross.get_path().intersects_bbox(node.get_bbox(),filled=True) for name,node in nodes.items() if name not in {'N0','N58'})


def test_funnel_canvas_style_and_hatch_are_applied_to_real_stages(render):
    plan,inputs=make('funnel',standardStyle={'series':[{'series':'value','color':'#112233','alpha':.4,'hatch':'//'}]})
    ax=render(plan,inputs).axes[0]
    assert ax.patches[0].get_alpha()==.4
    assert ax.patches[0].get_hatch()=='//'


def test_composition_rejects_series_line_style_instead_of_silently_ignoring_it():
    result=standard_visualization_preflight(*make('pie',standardStyle={'series':[{'series':'value','lineStyle':'--'}]}))
    assert result.source is None and result.diagnostic['code']=='standard_family_style_unsupported'


def test_reference_denominator_business_scope_mismatch_is_soft_warning_not_geometry_gate(render):
    doc=table()
    doc['columnMeta']['value'].update(periods=['2025-01'],scope={'area':'甲'})
    total=table([['总',100]])
    total['columnMeta']['value'].update(periods=['2024-01'],scope={'area':'全体'})
    plan,inputs=make('pie',[doc,total],standardComposition={'denominator':{'mode':'reference','ref':{'sourceIndex':1,'field':'value'}}})
    result=standard_visualization_preflight(plan,inputs)
    assert result.source is not None
    assert any(w['code']=='standard_composition_denominator_scope_mismatch' for w in result.warnings)
    assert [p.theta2-p.theta1 for p in render(plan,inputs).axes[0].patches]==pytest.approx([108,72,0])


@pytest.mark.parametrize('options',[{'standardAxes':{'linearThreshold':5}}, {'standardAnnotations':[{'kind':'values','caption':'自定义措辞','highlight':True}]}, {'standardStyle':{'points':[{'series':'value','label':'甲','color':'#112233','markerSize':16}]}}])
def test_unimplemented_family_axes_or_annotation_options_diagnose_explicitly(options):
    assert standard_visualization_preflight(*make('pie',**options)).source is None


@pytest.mark.parametrize('metadata',[['invalid'], True, 'invalid'])
def test_auxiliary_scalar_invalid_metadata_returns_diagnostic_not_exception(metadata):
    total={'columns':['total'],'rows':[[100]],'columnMeta':metadata}
    result=standard_visualization_preflight(*make('pie',[table(),total],standardComposition={'denominator':{'mode':'reference','ref':{'sourceIndex':1,'field':'total'}}}))
    assert result.source is None and result.diagnostic is not None


def test_composition_positive_value_that_cannot_form_an_angle_is_not_silently_zeroed():
    doc=table([['极小',1e-300],['普通',1]])
    result=standard_visualization_preflight(*make('pie',[doc]))
    assert result.source is None and result.diagnostic['code']=='standard_composition_angle_unrepresentable'


def test_multichart_shared_main_keeps_each_auxiliary_identity(tmp_path, monkeypatch):
    total={'columns':['total'],'rows':[[100]],'columnMeta':{'total':{'unit':'元'}}}
    pie,inputs=make('pie',[table(),total],standardComposition={'denominator':{'mode':'reference','ref':{'sourceIndex':1,'field':'total'}}})
    first=pie.charts[0]
    second=first.model_copy(update={'chart_id':'chart_other','source_path':'other.png','standard_form':'funnel','standard_composition':None})
    plan=pie.model_copy(update={'charts':(first,second)})
    inputs=inputs.__class__(files=inputs.files,entries=(*inputs.entries,{**inputs.entries[0],'chartId':'chart_other'}))
    result=standard_visualization_preflight(plan,inputs)
    assert result.source is not None
    monkeypatch.chdir(tmp_path)
    for file in inputs.files: (tmp_path/file.path).write_bytes(file.content)
    (tmp_path/inputs.files[1].path).write_bytes(b'{}')
    with pytest.raises(ValueError,match='identity changed'):
        exec(result.source,{})


def test_multichart_shared_main_keeps_independent_filtered_rows_and_display_units(tmp_path,monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    plan,inputs=make('bar')
    first=plan.charts[0].model_copy(update={'standard_labels':('甲',)})
    second=first.model_copy(update={'chart_id':'chart_other','source_path':'other.png','standard_labels':('乙',),'standard_display_unit':'万元'})
    plan=plan.model_copy(update={'charts':(first,second)})
    inputs=inputs.__class__(files=inputs.files,entries=(*inputs.entries,{**inputs.entries[0],'chartId':'chart_other'}))
    figures=[]
    save=Figure.savefig
    def capture(figure,*args,**kwargs):
        figures.append(figure)
        return save(figure,*args,**kwargs)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Figure,'savefig',capture)
    monkeypatch.setattr(plt,'close',lambda *args:None)
    for file in inputs.files: (tmp_path/file.path).write_bytes(file.content)
    exec(standard_visualization_preflight(plan,inputs).source,{})
    assert [p.get_height() for p in figures[0].axes[0].containers[0]]==[30]
    assert [p.get_height() for p in figures[1].axes[0].containers[0]]==[.002]


def test_sankey_first_cross_layer_edge_avoids_heavy_intermediate_nodes(render):
    rows=[['N0','N58',1],*[[f'N{i}',f'N{i+1}',1000] for i in range(58)]]
    ax=render(*flow([sankey(rows)])).axes[0]
    nodes={p.get_gid()[5:]:p for p in ax.patches if (p.get_gid() or '').startswith('node:')}
    cross=next(p for p in ax.patches if p.get_gid()=='edge:0')
    assert all(not cross.get_path().intersects_bbox(node.get_bbox(),filled=True) for name,node in nodes.items() if name not in {'N0','N58'})


@pytest.mark.parametrize('first_fraction',[True,False])
def test_wide_funnel_percentage_scale_is_converted_exactly_once(render,first_fraction):
    doc={'columns':['首','次','尾'],'rows':[[.4 if first_fraction else 40,20,.1]],
         'columnMeta':{'首':{'unit':'%','isPercent':not first_fraction},'次':{'unit':'%','isPercent':True},'尾':{'unit':'%','isPercent':False}}}
    ax=render(*make('funnel',[doc],standardLabelField=None,standardValueFields=['首','次','尾'])).axes[0]
    assert [p.get_width() for p in ax.patches]==pytest.approx([40,20,10])
    assert [t.get_text() for t in ax.texts]==['40.00%','20.00%','10.00%']


@pytest.mark.parametrize('style',[{'labelRotation':90},{'barGroupWidth':.9},{'series':[{'series':'value','label':'被忽略别名'}]}])
def test_family_style_without_supported_effect_returns_diagnostic(style):
    result=standard_visualization_preflight(*make('pie',standardStyle=style))
    assert result.source is None and result.diagnostic['code']=='standard_family_style_unsupported'


def test_all_zero_sankey_large_description_fits_canvas_or_diagnoses(render):
    rows=[[f'N{i}',f'N{j}',0] for i in range(30) for j in range(30,46)]
    rows[-14:]=[[f'N{i}',f'N{46+i}',0] for i in range(14)]
    plan,inputs=flow([sankey(rows)])
    try:
        figure=render(plan,inputs)
    except ValueError as error:
        assert 'standard_chart_layout_unresolved' in str(error)
    else:
        renderer=figure.canvas.get_renderer()
        assert all(figure.bbox.contains(*corner) for ax in figure.axes for text in ax.texts
                   for corner in text.get_window_extent(renderer).get_points())


@pytest.mark.parametrize('key,value',[('additiveAcross','other_area_not_additive'),('additiveAcross',['area',True]),('exclusiveAcross','other_area_not_exclusive'),('exclusiveAcross',['area',None])])
def test_alias_mapping_rejects_invalid_frozen_dimension_container(key,value):
    doc=table()
    doc['columns'][0]='area'
    if key=='additiveAcross':
        doc['columnMeta']['value']['measureSemantic'][key]=value
    else:
        doc['columnMeta']['value'].update(unit='%',isPercent=True,commonDenominator={'sourceIndex':0,'field':'value','labelField':'area','label':'甲'},exclusiveAcross=value)
    result=standard_visualization_preflight(*make('pie',[doc],standardValueFields=['份额'],standardLabelField='period',standardSources=[{'sourceIndex':0,'labelField':'area','valueField':'value','seriesName':'份额'}]))
    assert result.source is None
    assert result.diagnostic['code']=='standard_family_metadata_invalid'


@pytest.mark.parametrize('form',['pie','donut','radar','funnel','sankey'])
@pytest.mark.parametrize('style',[{'axisFontSize':18},{'labelRotation':90},{'annotationOffsetX':80},{'annotationOffsetY':-20},{'valueMargin':.5},{'barGroupWidth':.9},{'annotationLeader':True},{'annotationColor':'neutral'}])
def test_every_family_diagnoses_each_unconsumed_nondefault_style(form,style):
    if form=='radar':
        plan,inputs=make(form,[radar_table()],standardValueFields=['a','b','c'],standardStyle=style)
    elif form=='sankey':
        plan,inputs=flow(standardStyle=style)
    else:
        plan,inputs=make(form,standardStyle=style)
    result=standard_visualization_preflight(plan,inputs)
    assert result.source is None and result.diagnostic['code']=='standard_family_style_unsupported'


@pytest.mark.parametrize('form',['pie','donut','radar','funnel','sankey'])
def test_family_only_script_excludes_unused_renderers_but_executes_actual_geometry(render,form):
    if form=='radar':
        plan,inputs=make(form,[radar_table()],standardValueFields=['a','b','c'])
    elif form=='sankey':
        plan,inputs=flow()
    else:
        plan,inputs=make(form)
    source=standard_visualization_preflight(plan,inputs).source
    assert source is not None
    assert 'def render_encoded_chart(' not in source
    assert 'def render_advanced(' not in source
    assert 'def apply_standard_style(' not in source
    assert 'def render_statistical_chart(' not in source
    figure=render(plan,inputs)
    if form in {'pie','donut'}:
        assert [p.theta2-p.theta1 for p in figure.axes[0].patches]==pytest.approx([216,144,0])
    elif form=='radar':
        assert list(figure.axes[0].lines[0].get_ydata())==[2,4,6,2]
    elif form=='funnel':
        assert [p.get_width() for p in figure.axes[0].patches]==[30,20,0]
    else:
        assert len([p for p in figure.axes[0].patches if (p.get_gid() or '').startswith('edge:')])==4


def test_mixed_family_script_keeps_legacy_renderers_for_old_chart(tmp_path,monkeypatch):
    plan,inputs=make('pie')
    first=plan.charts[0]
    second=first.model_copy(update={'chart_id':'chart_other','source_path':'other.png','standard_form':'bar'})
    plan=plan.model_copy(update={'charts':(first,second)})
    inputs=inputs.__class__(files=inputs.files,entries=(*inputs.entries,{**inputs.entries[0],'chartId':'chart_other'}))
    source=standard_visualization_preflight(plan,inputs).source
    assert 'def render_encoded_chart(' in source and 'def render_advanced(' in source
    monkeypatch.chdir(tmp_path)
    for file in inputs.files: (tmp_path/file.path).write_bytes(file.content)
    exec(source,{})
    assert (tmp_path/'chart.png').read_bytes().startswith(b'\x89PNG')
    assert (tmp_path/'other.png').read_bytes().startswith(b'\x89PNG')
