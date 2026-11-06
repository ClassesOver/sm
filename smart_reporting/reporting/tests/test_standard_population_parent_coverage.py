"""正常冻结、模型读回与旧兼容读取都不应凭空补零月份。"""
import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context
from smart_reporting.reporting.tests.test_fact_reader_compatibility import (
    contribution_document,
    read,
)


@pytest.mark.parametrize('tail,expected', [('', ['2025-01']),
                                         ('2025-02,A,0\n', ['2025-01', '2025-02'])])
def test_normal_freeze_and_identity_model_replay_preserve_observed_periods(tail, expected):
    content = ('month,department,amount\n2025-01,A,100\n' + tail).encode()
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', content, context('current', sha256=hashlib.sha256(content).hexdigest()), ('current',)),
    ))
    metric = next(item for item in bundle.metrics if item.scope == {})
    assert [item.period for item in metric.period_values] == expected
    raw = bundle.model_dump_json(by_alias=True)
    restored = DeterministicAnalysisBundle.model_validate_json(raw)
    assert restored.metrics == bundle.metrics
    assert restored.metrics[0].period_values == bundle.metrics[0].period_values


def test_old_compatible_reader_preserves_missing_period_without_defaults_or_resigning():
    document = contribution_document()
    metric = document['metrics'][0]
    metric['periodValues'] = [{'period': '2025-01', 'value': 100}]
    metric['periodStart'] = metric['periodEnd'] = '2025-01'
    snapshot = read(document)
    assert snapshot.document['metrics'][0]['periodValues'] == metric['periodValues']
    assert snapshot.raw == json.dumps(document, ensure_ascii=False, indent=2).encode()
    assert snapshot.semantic_support_reused is False
