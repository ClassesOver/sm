"""正式指标的标准静态图投影；不重算指标，不借旧业务Profile建立归属。"""

from copy import deepcopy
from decimal import Decimal

import pytest

from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs
from smart_reporting.reporting.workflow.runtime.chart_data_descriptors import (
    deterministic_chart_descriptors,
)
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputError,
    _table_for_binding,
)
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

PATH = 'metricContext.calculations[0].results[0]'


def registered_document():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    analysis, context, _ = analysis_inputs()
    return build_registered_analysis_bundle(analysis, context, ()).model_dump(mode='json', by_alias=True)


def binding():
    return ChartDataBinding(analysisId='analysis_001', factPath='facts.json', dataPath=PATH,
        fields=['label', 'value'], role='measure')


def test_registered_selector_has_exact_value_and_label_without_mutating_decimal_source():
    document = registered_document()
    original = deepcopy(document)
    descriptor, = deterministic_chart_descriptors(document)
    assert descriptor['dataPath'] == PATH
    assert descriptor['fields'] == ['label', 'value']
    assert descriptor['standardHints'] == {'standardLabelField': 'label', 'standardValueFields': ['value']}
    columns, rows, metadata = _table_for_binding(document, binding())
    assert columns == ['label', 'value']
    assert '2026-11-01' in rows[0][0] and '2026-12-01' in rows[0][0]
    assert rows[0][1] == float(Decimal('300.123456789123456789'))
    assert metadata == {'value': {'unit': 'CNY'}}
    assert document == original
    assert document['metricContext']['calculations'][0]['results'][0]['value'] == '300.123456789123456789'


@pytest.mark.parametrize('value', ['1e999', '1e-999'])
def test_nonrepresentable_drawing_value_never_becomes_infinity_or_zero(value):
    document = registered_document()
    document['metricContext']['calculations'][0]['results'][0]['value'] = value
    with pytest.raises(ChartInputError):
        _table_for_binding(document, binding())


def test_unavailable_result_stays_null_with_reason_in_frozen_source():
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    result.update(value=None, status='unavailable', issueCodes=['missing_data'])
    _, rows, metadata = _table_for_binding(document, binding())
    assert rows[0][1] is None
    assert metadata['value']['unit'] == 'CNY'
    assert result['issueCodes'] == ['missing_data']


@pytest.mark.parametrize('fault', ['basis', 'batch', 'unit', 'version', 'selector', 'fields'])
def test_projection_cannot_expand_or_rebind_registered_identity(fault):
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    selected = binding()
    if fault == 'basis':
        result['basisId'] = 'foreign'
    elif fault == 'batch':
        result['calculationId'] = 'old-calculation'
    elif fault == 'unit':
        result['unit'] = 'USD'
    elif fault == 'version':
        result['metricVersion']['revision'] = 2
    elif fault == 'selector':
        selected = selected.model_copy(update={'data_path': 'metricContext.calculations[0].results[0].value'})
    else:
        selected = selected.model_copy(update={'fields': ('label', 'value', 'invented')})
    with pytest.raises(ChartInputError):
        _table_for_binding(document, selected)


def test_complete_group_projection_keeps_unavailable_group_and_exact_order():
    document = registered_document()
    calculation = document['metricContext']['calculations'][0]
    calculation['request']['dimensions'] = ['project']
    first = calculation['results'][0]
    first['dimensions'] = [{'dimensionId': 'project', 'value': '甲'}]
    second = deepcopy(first)
    second.update(factId='group-b-fact', dimensions=[{'dimensionId': 'project', 'value': '乙'}],
        value=None, status='unavailable', issueCodes=['missing_data'])
    calculation['results'].append(second)
    selected = binding().model_copy(update={'data_path': 'metricContext.calculations[0].results'})
    columns, rows, metadata = _table_for_binding(document, selected)
    assert columns == ['label', 'value']
    assert '甲' in rows[0][0] and '乙' in rows[1][0]
    assert rows[1][1] is None
    assert metadata == {'value': {'unit': 'CNY'}}
    assert selected.data_path in {item['dataPath'] for item in deterministic_chart_descriptors(document)}


def test_whole_result_collection_cannot_mix_metric_versions_even_with_equal_units():
    document = registered_document()
    calculation = document['metricContext']['calculations'][0]
    second = deepcopy(calculation['results'][0])
    second.update(factId='other-metric-fact', metricVersion={'metricId': 'actual', 'revision': 1})
    calculation['results'].append(second)
    selected = binding().model_copy(update={'data_path': 'metricContext.calculations[0].results'})
    with pytest.raises(ChartInputError):
        _table_for_binding(document, selected)
    assert selected.data_path not in {item['dataPath'] for item in deterministic_chart_descriptors(document)}


def test_result_cannot_borrow_an_unrelated_metric_from_same_context():
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    result['metricVersion'] = {'metricId': 'actual', 'revision': 1}
    with pytest.raises(ChartInputError):
        _table_for_binding(document, binding())


def test_editor_uses_all_exact_registered_datasets_or_rejects_binding():
    from smart_reporting.report_editor.chart_ai import _dataset_ids_for_bindings
    document = registered_document()
    assert _dataset_ids_for_bindings({'facts.json': document}, (binding(),),
        known_dataset_ids={'dataset-formal'}) == ('dataset-formal',)
    document['metricContext']['calculations'][0]['results'][0]['datasetIds'].append('foreign')
    assert _dataset_ids_for_bindings({'facts.json': document}, (binding(),),
        known_dataset_ids={'dataset-formal'}) == ()


def registered_trace_case():
    import hashlib
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.tests.test_trace_index_builder import _build, _handle, _lineage
    from smart_reporting.reporting.trace.contracts_v1 import (
        ChartTraceV1,
        TraceFileRefV1,
        derive_resource_id,
    )

    document = registered_document()
    documents = {}

    def file(path, value):
        raw = json.dumps(value).encode()
        documents[path] = raw
        return TraceFileRefV1(resourceId=derive_resource_id(path), path=path,
            mediaType='application/json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    facts = file('facts.json', document)
    columns, rows, metadata = _table_for_binding(document, binding())
    plot = file('plot.json', {'schema': 'chart-input/v1', 'chartId': 'chart_001',
        'role': 'measure', 'source': {'analysisId': 'analysis_001', 'path': facts.path,
            'sha256': facts.sha256, 'dataPath': PATH}, 'columns': columns, 'rows': rows,
        'rowCount': len(rows), 'columnMeta': metadata})
    chart = ChartTraceV1(chartId='chart_001', imageFileResourceId=derive_resource_id('chart.png'),
        plotDataFileResourceIds=(plot.resource_id,), datasetIds=('dataset-formal',))
    image = SimpleNamespace(path='chart.png', size=10, sha256='c' * 64)
    index = _build((_handle('dataset-formal'),), (_lineage('dataset-formal'),),
        report_basis_id=document['metricContext']['basisId'],
        fact_files={'analysis_001': ArtifactFile(path=facts.path, mediaType='application/json',
            size=facts.size, sha256=facts.sha256)}, chart_trace_files=(image, plot), chart_traces=(chart,))
    return index, chart, documents


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', [None, 'basis', 'dataset'])
async def test_registered_chart_recovers_exact_fact_and_rejects_scope_changes(fault):
    from smart_reporting.reporting.trace.chart_facts import recover_chart_fact_refs
    index, chart, documents = registered_trace_case()
    if fault == 'basis':
        index = index.model_copy(update={'report_basis_id': 'foreign'})
    elif fault == 'dataset':
        chart = chart.model_copy(update={'dataset_ids': ('other',)})

    async def read(file):
        return documents[file.path]

    if fault:
        with pytest.raises(ValueError):
            await recover_chart_fact_refs(index, chart, read)
    else:
        ref, = await recover_chart_fact_refs(index, chart, read)
        assert ref.json_pointer == '/metricContext/calculations/0/results/0'
        assert ref.fact_key == 'fact-budget' and ref.fact_kind == 'metric'


def test_native_matplotlib_render_proof_and_exact_registered_semantics(tmp_path, monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.code_agent.context import ExecutionReceipt
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.tests.test_standard_chart_proof import proof_case
    from smart_reporting.reporting.tests.test_trace_index_builder import _build, _handle, _lineage
    from smart_reporting.reporting.trace.standard_chart_alignment import (
        evaluate_standard_chart_alignment,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.standard_chart_proof import (
        create_standard_render_proofs,
        recompile_standard_render_proof,
    )
    from smart_reporting.reporting.workflow.runtime.standard_visualization import (
        standard_visualization_preflight,
    )

    document = registered_document()
    facts_raw = json.dumps(document).encode()
    fact = FileIdentity(path='facts.json', size=len(facts_raw), sha256=hashlib.sha256(facts_raw).hexdigest())
    plan, _, _, _ = proof_case()
    draft = plan.charts[0].model_copy(update={'title': '已登记预算', 'metric_codes': ('budget',),
        'source_dataset_id': 'dataset-formal', 'current_period': '[2026-11-01, 2026-12-01)',
        'data_bindings': (binding(),),
        'standard_label_field': 'label', 'standard_value_fields': ('value',)})
    plan = plan.model_copy(update={'charts': (draft,)})
    inputs = materialize_chart_inputs(plan, [{'analysisId': 'analysis_001',
        'factFile': fact.model_dump(mode='json', by_alias=True),
        'dataDescriptors': deterministic_chart_descriptors(document)}], {'facts.json': document}, output_root='inputs')
    assert not inputs.fallback_chart_ids and len(inputs.files) == 1
    for file in inputs.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file.content)
    source = standard_visualization_preflight(plan, inputs).source
    assert source is not None
    (tmp_path / 'facts.json').write_bytes(facts_raw)
    (tmp_path / 'chart.py').write_text(source)
    monkeypatch.chdir(tmp_path)
    exec((tmp_path / 'chart.py').read_text(), {})
    image_raw = (tmp_path / 'chart.png').read_bytes()
    assert image_raw.startswith(b'\x89PNG')
    source_raw = source.encode()
    script = FileIdentity(path='chart.py', size=len(source_raw), sha256=hashlib.sha256(source_raw).hexdigest())
    image = FileIdentity(path='chart.png', size=len(image_raw), sha256=hashlib.sha256(image_raw).hexdigest())
    result = SimpleNamespace(script_file=script, execution_receipt=ExecutionReceipt(
        runId='registered-matplotlib-execution', sourceFile=script, outputFiles=(image,)))
    proof = create_standard_render_proofs(result, plan, inputs)[0]['proof']
    assert recompile_standard_render_proof(proof, {file.sha256: file.content for file in inputs.files}) == source_raw
    index, chart, _ = registered_trace_case()
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    chart = chart.model_copy(update={'standard_render_proof': proof, 'script_file_resource_id': derive_resource_id(script.path),
        'plot_data_file_resource_ids': tuple(derive_resource_id(file.path) for file in inputs.files)})
    plot_files = tuple(ArtifactFile(path=file.path, mediaType='application/json', size=len(file.content),
        sha256=file.sha256) for file in inputs.files)
    index = _build((_handle('dataset-formal'),), (_lineage('dataset-formal'),),
        report_basis_id=document['metricContext']['basisId'],
        fact_files={'analysis_001': ArtifactFile(path=fact.path, mediaType='application/json', size=fact.size, sha256=fact.sha256)},
        chart_trace_files=(image, script, *plot_files), chart_traces=(chart,))
    documents = {derive_resource_id('facts.json'): document,
        **{derive_resource_id(file.path): json.loads(file.content) for file in inputs.files}}
    check = evaluate_standard_chart_alignment(index, chart, documents.__getitem__)
    assert check.status == 'verified', check
    assert check.fact_ids == ('fact-budget',)
    assert evaluate_standard_chart_alignment(index.model_copy(update={'report_basis_id': 'foreign'}),
        chart, documents.__getitem__).reasons == ('chart_fact_basis_mismatch',)
    assert evaluate_standard_chart_alignment(index, chart.model_copy(update={'dataset_ids': ('other',)}),
        documents.__getitem__).reasons == ('chart_fact_dataset_mismatch',)
    bad_plan = {**proof.plan, 'charts': [{**proof.plan['charts'][0], 'metricCodes': ['actual']}]}
    changed = chart.model_copy(update={'standard_render_proof': proof.model_copy(update={'plan': bad_plan})})
    assert evaluate_standard_chart_alignment(index, changed, documents.__getitem__).status != 'verified'

    from smart_reporting.reporting.trace.chart_quality import evaluate_chart_quality
    from smart_reporting.reporting.trace.chart_subjects import freeze_chart_presentations
    from smart_reporting.reporting.trace.semantic_alignment import evaluate_semantic_alignment

    markdown = '![已登记预算](chart.png)'
    index = freeze_chart_presentations(index, markdown)
    sources = {derive_resource_id('facts.json'): facts_raw,
        derive_resource_id('chart.py'): source_raw, derive_resource_id('chart.png'): image_raw,
        **{derive_resource_id(file.path): file.content for file in inputs.files}}
    quality = evaluate_chart_quality(index, markdown, sources)
    assert quality['chart_001'].status == 'verified', quality
    alignment = evaluate_semantic_alignment(index, sources, chart_checks=quality)
    assert alignment['chart_001'].status == 'verified', alignment
    assert alignment['chart_001'].fact_ids == ('fact-budget',)
    sources[derive_resource_id('chart.png')] += b'changed'
    quality = evaluate_chart_quality(index, markdown, sources)
    assert quality['chart_001'].status == 'unknown'
    assert evaluate_semantic_alignment(index, sources, chart_checks=quality)['chart_001'].status == 'unknown'


@pytest.mark.parametrize('dependency_result', [False, True])
def test_percent_points_are_not_scaled_again_and_exact_dependencies_are_supported(dependency_result):
    document = registered_document()
    metric = document['metricContext']['metrics'][0]
    metric.update(kind='ratio', fieldRef=None, timeField=None, unit='%',
        numeratorVersion={'metricId': 'actual', 'revision': 1},
        denominatorVersion={'metricId': 'actual', 'revision': 1})
    result = document['metricContext']['calculations'][0]['results'][0]
    result.update(value='25.5', unit='%')
    if dependency_result:
        result.update(metricVersion={'metricId': 'actual', 'revision': 1}, unit='CNY')
    _, rows, metadata = _table_for_binding(document, binding())
    assert rows[0][1] == 25.5
    expected = {'value': {'unit': 'CNY'}} if dependency_result else {
        'value': {'unit': '%', 'isPercent': True}}
    assert metadata == expected
