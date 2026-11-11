"""交付证据目录来自精确正式上下文，不丢失或猜测指标定义。"""

from copy import deepcopy

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_registered_chart_projection import registered_document
from smart_reporting.reporting.workflow.runtime.analysis import _finalize_semantic_catalog


def catalog(documents):
    return _finalize_semantic_catalog(analysis_plans={key: {'datasetIds': ['dataset-formal'],
        'organizationGrain': []} for key in documents}, fact_bundles=documents, dataset_ids=('dataset-formal',))


def test_registered_catalog_keeps_exact_metric_definition_and_calculation_output_grain():
    document = registered_document()
    datasets, metrics, warnings = catalog({'analysis_001': document})
    assert datasets == [{'datasetId': 'dataset-formal', 'rowGrain': 'registered_metric_result',
        'duplicateResolution': 'not_applicable'}]
    metric, = metrics
    definition = document['metricContext']['metrics'][0]
    assert metric['code'] == definition['id'] and metric['name'] == definition['name']
    assert metric['unit'] == 'CNY' and '@1' in metric['definition']
    assert '[2026-11-01, 2026-12-01)' in metric['periodBasis']
    assert not any(item['ruleCode'] == 'report_dataset_grain_missing' for item in warnings)
    assert catalog({'analysis_001': document, 'analysis_002': deepcopy(document)}) == (datasets, metrics, warnings)


@pytest.mark.parametrize('fault', ['batch', 'foreign_context', 'legacy_mix', 'foreign_dataset'])
def test_registered_catalog_rejects_inconsistent_or_mixed_evidence(fault):
    document = registered_document()
    documents = {'analysis_001': document}
    if fault == 'batch':
        document['metricContext']['calculations'][0]['results'][0]['calculationId'] = 'foreign'
    elif fault == 'foreign_dataset':
        document['metricContext']['calculations'][0]['results'][0]['datasetIds'] = ['foreign']
    elif fault == 'legacy_mix':
        documents['analysis_002'] = {'metrics': []}
    else:
        documents['analysis_002'] = deepcopy(document)
        documents['analysis_002']['metricContext']['reportRevision'] = 'different'
    with pytest.raises(ReportingError):
        catalog(documents)


def test_registered_ratio_catalog_names_exact_dependencies_without_recomputing():
    document = registered_document()
    context = document['metricContext']
    root = context['metrics'][0]
    root.update(kind='ratio', fieldRef=None, timeField=None, unit='%',
        numeratorVersion={'metricId': 'actual', 'revision': 1},
        denominatorVersion={'metricId': 'actual', 'revision': 1})
    context['calculations'][0]['results'][0]['unit'] = '%'
    _, metrics, _ = catalog({'analysis_001': document})
    assert 'actual@1 / actual@1' in metrics[0]['definition']
    assert '× 100' in metrics[0]['definition'] and metrics[0]['unit'] == '%'


def test_registered_catalog_never_truncates_period_identity_to_fit_display_contract():
    from datetime import date, timedelta

    document = registered_document()
    context = document['metricContext']
    original = context['calculations'][0]
    context['calculations'] = []
    for index in range(21):
        calculation = deepcopy(original)
        period = {'start': (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
            'end': (date(2026, 1, 2) + timedelta(days=index)).isoformat()}
        calculation['receiptId'] = f'calculation-{index}'
        calculation['request']['period'] = period
        calculation['results'][0].update(period=period, calculationId=calculation['receiptId'], factId=f'fact-{index}')
        context['calculations'].append(calculation)
    _, metrics, issues = catalog({'analysis_001': document})
    assert metrics == []
    assert any(item['ruleCode'] == 'report_metric_semantic_incomplete' for item in issues)
