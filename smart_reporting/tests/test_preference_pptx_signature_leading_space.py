"""只把已接入物理落款间距的一个缺口登记为可维护。"""
from smart_reporting.preferences.approval_contract import approval_contract
from smart_reporting.preferences.capabilities import unsupported_preference_reason


def test_pptx_signature_gap_consumer_is_registered_without_erasing_history():
    fields = {field['path']: field for field in approval_contract()['fields']}
    gap = fields['pptx.signature.spaceBefore']
    assert gap['support'] == 'implemented' and gap['editable']
    assert gap['consumer'].endswith('build-pptx.ts')
    assert gap['nativeProperty'] and gap['legacyUnsupportedReason']
    assert unsupported_preference_reason('pptx', gap['path']) is None
    assert {field['path'] for field in fields.values() if field['support'] == 'missing'} == {
        'xlsx.print.headerFooter.divider'}
