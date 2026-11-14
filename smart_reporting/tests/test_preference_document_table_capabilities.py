"""原生受控表题消费者成立后才允许维护；不提升PDF采样为完整验证。"""
import pytest

from smart_reporting.preferences.approval_contract import approval_contract
from smart_reporting.preferences.capabilities import unsupported_preference_reason


@pytest.mark.parametrize('format', ['word', 'pdf'])
def test_document_table_caption_consumer_preserves_legacy_gap_history(format):
    fields = {field['path']: field for field in approval_contract()['fields']}
    field = fields[f'{format}.tables.captionNumbering']
    assert field['support'] == 'implemented' and field['editable']
    assert field['consumer'].endswith('report_runtime/table_captions.py')
    assert 'registered' in field['nativeProperty']
    assert field['legacyUnsupportedReason']
    assert unsupported_preference_reason(format, field['path']) is None
    assert fields[f'{format}.charts.imageDpi']['support'] == 'implemented'
